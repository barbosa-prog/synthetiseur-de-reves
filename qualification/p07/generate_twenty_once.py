"""Une seule génération fictive locale 512x512, vingt étapes, seed 42."""

import argparse
import faulthandler
import os
import sys
import time
import uuid
from pathlib import Path

from common import QualificationError, paths, ram_mib
from cpu_mini import emit, supervise


def worker(output):
    if sys.stdin.buffer.readline(32).rstrip(b"\r\n") != b"CPU_ONLY":
        return 1
    assert faulthandler.is_enabled()
    started = time.perf_counter()
    emit("before_imports", pid=os.getpid(), faulthandler_enabled=True)
    import torch
    from diffusers import StableDiffusionPipeline
    from diffusers.pipelines.pipeline_utils import SUPPORTED_DEVICE_MAP
    assert "cuda" in SUPPORTED_DEVICE_MAP
    emit("imports_ready", seconds=round(time.perf_counter()-started, 6))
    emit("before_cuda_init")
    begin = time.perf_counter()
    torch.cuda.init()
    torch.cuda.synchronize()
    emit("cuda_initialized", seconds=round(time.perf_counter()-begin, 6),
         gpu=torch.cuda.get_device_name(0))
    emit("before_pipeline_load", device_map="cuda", dtype="float16", variant="fp16")
    begin = time.perf_counter()
    pipeline = StableDiffusionPipeline.from_pretrained(
        str(paths()[2]), torch_dtype=torch.float16, variant="fp16",
        use_safetensors=True, local_files_only=True, low_cpu_mem_usage=True,
        device_map="cuda",
    )
    torch.cuda.synchronize()
    emit("after_pipeline_load", seconds=round(time.perf_counter()-begin, 6), weights_loaded=True)
    assert pipeline.safety_checker is not None and pipeline.feature_extractor is not None
    components = {}
    for name in ("unet", "vae", "text_encoder", "safety_checker"):
        model = getattr(pipeline, name)
        assert model is not None
        parameters = list(model.parameters())
        assert parameters and all(p.device.type == "cuda" for p in parameters)
        assert all(p.dtype == torch.float16 for p in parameters if p.is_floating_point())
        components[name] = {"device": str(parameters[0].device),
                            "dtype": str(parameters[0].dtype),
                            "parameters": sum(p.numel() for p in parameters)}
    emit("components_verified", components=components, safety_checker_present=True)
    free, _ = torch.cuda.mem_get_info()
    available = ram_mib()
    emit("pre_inference_memory", ram_available_mib=available, vram_free_mib=free/1024**2)
    if available < 2048 or free < 1536*1024**2:
        raise QualificationError("Marge mémoire avant inférence insuffisante ; aucun retry.")
    torch.cuda.reset_peak_memory_stats()
    emit("before_inference", steps=20, seed=42, width=512, height=512)
    begin = time.perf_counter()
    with torch.inference_mode():
        result = pipeline(
            "Une forêt enchantée sous une grande lune violette, ambiance onirique",
            width=512, height=512, num_inference_steps=20, num_images_per_prompt=1,
            generator=torch.Generator(device="cuda").manual_seed(42), output_type="pil",
        )
    torch.cuda.synchronize()
    emit("after_inference", seconds=round(time.perf_counter()-begin, 6),
         allocator_peak_allocated_mib=torch.cuda.max_memory_allocated()/1024**2,
         allocator_peak_reserved_mib=torch.cuda.max_memory_reserved()/1024**2)
    assert result.nsfw_content_detected is not None
    assert len(result.images) == 1 and len(result.nsfw_content_detected) == 1
    blocked = bool(result.nsfw_content_detected[0])
    emit("safety_result", blocked=blocked)
    if blocked:
        raise QualificationError("Image bloquée par le filtre ; aucun retry.")
    from PIL import Image
    target = Path(output).resolve()
    assert target.is_relative_to(paths()[0] / "twenty-generation")
    assert result.images[0].size == (512, 512)
    result.images[0].save(target, format="PNG")
    with Image.open(target) as saved:
        assert saved.format == "PNG" and saved.size == (512, 512)
        saved.verify()
    emit("twenty_generation_passed", total_seconds=round(time.perf_counter()-started, 6),
         filename=target.name, format="PNG", dimensions=[512, 512], image_generated=True,
         safety_blocked=False)
    time.sleep(1)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-twenty-generation", action="store_true")
    parser.add_argument("--output", help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(worker(args.output))
    if not args.run_twenty_generation:
        parser.error("Autorisation explicite requise : --run-twenty-generation")
    folder = paths()[0] / "twenty-generation"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (uuid.uuid4().hex[:12]+".png")
    raise SystemExit(supervise(
        worker_script=Path(__file__).resolve(), test_name="twenty_generation_once",
        output_group="twenty-generation", success_event="twenty_generation_passed",
        excluded_tests=(), gpu_mode=True, private_cap_mib=7168, timeout_seconds=120,
        initial_ram_min_mib=4096, initial_vram_min_mib=4096,
        worker_args=("--output", str(target)),
    ))
