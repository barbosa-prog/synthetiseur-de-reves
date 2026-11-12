"""Qualification locale FR/EN : prompts fictifs fixes, aucune intégration FastAPI/P05."""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from common import (
    REPOSITORY,
    REVISION,
    QualificationError,
    exclusive,
    gpu_info,
    paths,
    ram_mib,
    require_environment,
    require_memory,
    verify_model,
    versions,
)

PROMPTS = {
    "fr": "Une forêt lumineuse avec une lune violette dans le ciel, illustration onirique.",
    "en": "A luminous forest with a purple moon in the sky, dreamlike illustration.",
}


def worker(args, seeds):
    """Poids locaux uniquement, une image à la fois ; mesures CUDA synchronisées."""
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
    require_environment()
    model = verify_model()
    require_memory(args.mode)
    import psutil
    import torch
    from diffusers import StableDiffusionPipeline
    if not torch.cuda.is_available() or torch.version.cuda != "11.8":
        raise QualificationError("Runtime CUDA 11.8 non qualifié.")
    require_memory(args.mode)  # Deuxième mesure après import des bibliothèques.
    torch.cuda.init()
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    process = psutil.Process()
    samples = {"peak_process_rss_mib": 0, "min_available_ram_mib": ram_mib()}
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            samples["peak_process_rss_mib"] = max(
                samples["peak_process_rss_mib"], process.memory_info().rss // 1024**2,
            )
            samples["min_available_ram_mib"] = min(samples["min_available_ram_mib"], ram_mib())
            stop.wait(0.1)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        start = time.perf_counter()
        pipe = StableDiffusionPipeline.from_pretrained(
            str(model), torch_dtype=torch.float16, variant="fp16", use_safetensors=True,
            local_files_only=True, low_cpu_mem_usage=True,
        )
        if pipe.safety_checker is None:
            raise QualificationError("Filtre de sécurité absent : qualification refusée.")
        pipe.set_progress_bar_config(disable=True)
        if args.mode == "gpu":
            pipe.to("cuda")
        elif args.mode == "model-offload":
            pipe.enable_model_cpu_offload(gpu_id=0)
        else:
            pipe.enable_sequential_cpu_offload(gpu_id=0)
        torch.cuda.synchronize()
        report = {"repository": REPOSITORY, "revision": REVISION, "versions": versions(),
                  "mode": args.mode, "gpu_before_generation": gpu_info(),
                  "loading_seconds": round(time.perf_counter() - start, 3),
                  "loading_peak_cuda_allocated_mib": torch.cuda.max_memory_allocated() // 1024**2,
                  "loading_peak_cuda_reserved_mib": torch.cuda.max_memory_reserved() // 1024**2,
                  "resolution": [512, 512], "steps": 20, "guidance_scale": 7.5, "runs": []}
        output = paths()[3] / (args.mode + "-" + uuid.uuid4().hex[:12])
        output.mkdir(parents=True, exist_ok=False)
        for seed in seeds:
            for language, prompt in PROMPTS.items():
                if len(pipe.tokenizer.encode(prompt)) > pipe.tokenizer.model_max_length:
                    raise QualificationError("Description trop longue ; troncature refusée.")
                torch.cuda.synchronize()
                torch.cuda.reset_peak_memory_stats()
                start = time.perf_counter()
                with torch.inference_mode():
                    result = pipe(prompt, width=512, height=512, num_images_per_prompt=1,
                                  num_inference_steps=20, guidance_scale=7.5,
                                  generator=torch.Generator(device="cpu").manual_seed(seed))
                torch.cuda.synchronize()
                elapsed = time.perf_counter() - start
                if result.nsfw_content_detected is None or len(result.images) != 1:
                    raise QualificationError("Résultat ou contrôle de sécurité invalide.")
                flagged = bool(result.nsfw_content_detected[0])
                image = result.images[0]
                if image.size != (512, 512):
                    raise QualificationError("Dimensions incorrectes.")
                filename = f"{language}-{seed}.png"
                if not flagged:
                    temporary = output / (filename + ".tmp")
                    image.save(temporary, format="PNG")
                    temporary.replace(output / filename)
                report["runs"].append({
                    "language": language, "seed": seed, "seconds": round(elapsed, 3),
                    "cuda_peak_allocated_mib": torch.cuda.max_memory_allocated() // 1024**2,
                    "cuda_peak_reserved_mib": torch.cuda.max_memory_reserved() // 1024**2,
                    "safety_flagged": flagged, "image": None if flagged else filename,
                })
                image.close()
                del result
        report["host_memory_sampling_100ms"] = dict(samples)
        (output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
        return 2 if any(run["safety_flagged"] for run in report["runs"]) else 0
    except torch.cuda.OutOfMemoryError:
        raise QualificationError("VRAM insuffisante ; examiner le mode offload.") from None
    finally:
        stop.set()
        thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Essai explicite après accord")
    parser.add_argument("--mode", choices=["gpu", "model-offload", "sequential-offload"],
                        default="gpu")
    parser.add_argument("--seeds", default="42", help="Un à trois seeds, séparés par virgules")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.run:
        parser.error("Exécution explicite --run requise ; aucun téléchargement automatique.")
    seeds = [int(value) for value in args.seeds.split(",")]
    if not 1 <= len(seeds) <= 3 or any(not 0 <= seed <= 2**32 - 1 for seed in seeds):
        raise QualificationError("Un à trois seeds entiers positifs au maximum.")
    require_environment()
    if args.worker:
        return worker(args, seeds)
    require_memory(args.mode)
    with exclusive():
        try:
            result = subprocess.run([
                sys.executable, str(Path(__file__).resolve()), "--run", "--worker",
                "--mode", args.mode, "--seeds", args.seeds,
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=900, check=False)
        except subprocess.TimeoutExpired:
            print("Délai de qualification dépassé (900 s) ; sous-processus arrêté.")
            return 1
        sys.stdout.buffer.write(result.stdout)
        return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        detail = str(exc) if isinstance(exc, QualificationError) else type(exc).__name__
        print(f"Qualification arrêtée : {detail}")
        raise SystemExit(1) from None
