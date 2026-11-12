"""Un seul chargement du pipeline local sur CUDA ; aucun appel de génération."""

import argparse
import faulthandler
import os
import sys
import time
from pathlib import Path

from common import paths
from cpu_mini import emit, supervise


def worker():
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
    emit("pipeline_load_passed", total_seconds=round(time.perf_counter()-started, 6),
         components=components, safety_checker_present=True, weights_loaded=True,
         inference_executed=False, image_generated=False)
    time.sleep(1)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-load-once", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(worker())
    if not args.run_load_once:
        parser.error("Autorisation explicite requise : --run-load-once")
    raise SystemExit(supervise(
        worker_script=Path(__file__).resolve(), test_name="pipeline_cuda_load_once",
        output_group="pipeline-load-once", success_event="pipeline_load_passed",
        excluded_tests=(), gpu_mode=True, private_cap_mib=6144,
        initial_ram_min_mib=4096, initial_vram_min_mib=4096,
    ))
