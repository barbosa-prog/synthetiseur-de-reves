"""Chargement uniquement : aucune description, aucun appel de génération d'image."""

import json
import os
import sys
import time
import traceback
from pathlib import Path

from common import QualificationError, require_environment, verify_model


def emit(event, **values):
    print(json.dumps({"event": event, **values}), flush=True)


def main():
    # Le parent doit attacher le Job Object et démarrer la surveillance avant ce signal.
    if sys.stdin.buffer.readline(32).rstrip(b"\r\n") != b"LOAD_ONLY":
        return 1
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
    require_environment()
    stage = "verify_local_files"
    started = time.perf_counter()
    try:
        model = verify_model()
        emit("files_verified", seconds=round(time.perf_counter() - started, 3))
        stage = "imports"
        import torch
        from diffusers import StableDiffusionPipeline
        if not torch.cuda.is_available() or torch.version.cuda != "11.8":
            raise QualificationError("Runtime CUDA non qualifié.")
        torch.cuda.init()
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        emit("imports_ready", elapsed_seconds=round(time.perf_counter() - started, 3))
        stage = "load_to_gpu"
        load_start = time.perf_counter()
        pipeline = StableDiffusionPipeline.from_pretrained(
            str(model), torch_dtype=torch.float16, variant="fp16", use_safetensors=True,
            local_files_only=True, low_cpu_mem_usage=True, device_map="cuda",
        )
        torch.cuda.synchronize()
        if pipeline.safety_checker is None or pipeline.feature_extractor is None:
            raise QualificationError("Filtre de sécurité ou prétraitement absent.")
        placements = {}
        for name in ("unet", "vae", "text_encoder", "safety_checker"):
            component = getattr(pipeline, name)
            parameters = list(component.parameters())
            if any(p.device.type != "cuda" for p in parameters):
                raise QualificationError("Un composant est resté hors GPU.")
            if any(p.is_floating_point() and p.dtype != torch.float16 for p in parameters):
                raise QualificationError("Un composant flottant n'est pas en FP16.")
            placements[name] = {"device": str(parameters[0].device), "floating_dtype": "float16"}
        emit("pipeline_loaded", loading_seconds=round(time.perf_counter() - load_start, 3),
             total_seconds=round(time.perf_counter() - started, 3), components=placements,
             safety_checker_present=True,
             cuda_allocated_mib=round(torch.cuda.memory_allocated() / 1024**2, 2),
             cuda_reserved_mib=round(torch.cuda.memory_reserved() / 1024**2, 2),
             cuda_peak_allocated_mib=round(torch.cuda.max_memory_allocated() / 1024**2, 2),
             cuda_peak_reserved_mib=round(torch.cuda.max_memory_reserved() / 1024**2, 2),
             generation_executed=False)
        # Laisser au surveillant cinq secondes de mesures avec le pipeline résident.
        time.sleep(5)
        emit("load_only_complete", generation_executed=False)
        return 0
    except Exception as exc:
        # Les messages des bibliothèques peuvent contenir des chemins : ne pas les imprimer.
        frames = [{"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                  for frame in traceback.extract_tb(exc.__traceback__)]
        emit("error", stage=stage, exception_type=type(exc).__name__, frames=frames,
             safe_detail=str(exc) if isinstance(exc, QualificationError) else None)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
