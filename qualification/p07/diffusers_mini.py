"""Test 5 uniquement : UNet aléatoire miniature, sans modèle préentraîné."""

import argparse
import faulthandler
import os
import sys
import time
from pathlib import Path

from common import QualificationError, ram_mib
from cpu_mini import emit, supervise


def worker():
    if sys.stdin.buffer.readline(32).rstrip(b"\r\n") != b"CPU_ONLY":
        return 1
    assert faulthandler.is_enabled()
    started = time.perf_counter()
    emit("before_imports", pid=os.getpid(), faulthandler_enabled=True)
    import accelerate
    import diffusers
    import torch
    from accelerate import dispatch_model
    from diffusers import UNet2DModel
    if (torch.__version__ != "2.7.1+cu118" or diffusers.__version__ != "0.35.2"
            or accelerate.__version__ != "1.12.0"):
        raise QualificationError("Versions différentes de celles autorisées.")
    emit("imports_ready", seconds=round(time.perf_counter()-started, 6),
         torch=torch.__version__, diffusers=diffusers.__version__,
         accelerate=accelerate.__version__)
    torch.set_num_threads(1)
    torch.manual_seed(7)
    emit("before_cpu_construction")
    begin = time.perf_counter()
    model = UNet2DModel(sample_size=8, in_channels=4, out_channels=4,
                        layers_per_block=1, block_out_channels=(8,),
                        down_block_types=("DownBlock2D",), up_block_types=("UpBlock2D",),
                        norm_num_groups=4, add_attention=False).eval()
    assert all(p.device.type == "cpu" for p in model.parameters())
    emit("cpu_constructed", seconds=round(time.perf_counter()-begin, 6),
         parameters=sum(p.numel() for p in model.parameters()))
    sample = torch.linspace(-1, 1, 256).reshape(1, 4, 8, 8)
    begin = time.perf_counter()
    with torch.inference_mode():
        expected = model(sample, timestep=1).sample
    assert expected.shape == sample.shape and expected.dtype == torch.float32
    assert torch.isfinite(expected).all().item()
    emit("cpu_forward_passed", seconds=round(time.perf_counter()-begin, 6),
         shape=list(expected.shape), dtype=str(expected.dtype))
    emit("before_accelerate_cpu_dispatch")
    model = dispatch_model(model, device_map={"": "cpu"})
    with torch.inference_mode():
        actual = model(sample, timestep=1).sample
    assert torch.equal(expected, actual)
    emit("accelerate_cpu_passed", device_map=model.hf_device_map, exact_values_equal=True)
    # Marge supplémentaire pour le contexte CUDA ; aucune baisse des réserves du surveillant.
    if ram_mib() < 2304:
        emit("cuda_skipped", reason="ram_margin_below_2304_mib")
    else:
        emit("before_cuda_init")
        begin = time.perf_counter()
        torch.cuda.init()
        torch.cuda.synchronize()
        name = torch.cuda.get_device_name(0)
        if "RTX 3060" not in name:
            raise QualificationError("GPU différent du GPU autorisé.")
        emit("cuda_initialized", seconds=round(time.perf_counter()-begin, 6), gpu=name)
        free, _ = torch.cuda.mem_get_info()
        if free < 1024**3 or ram_mib() < 2304:
            emit("cuda_skipped", reason="insufficient_gpu_or_ram_margin")
        else:
            torch.cuda.reset_peak_memory_stats()
            emit("before_accelerate_cuda_dispatch")
            begin = time.perf_counter()
            model = dispatch_model(model.to(dtype=torch.float16), device_map={"": "cuda:0"})
            gpu_sample = sample.to(device="cuda:0", dtype=torch.float16)
            torch.cuda.synchronize()
            emit("accelerate_cuda_dispatched", seconds=round(time.perf_counter()-begin, 6))
            begin = time.perf_counter()
            with torch.inference_mode():
                result = model(gpu_sample, timestep=1).sample
            torch.cuda.synchronize()
            elapsed = time.perf_counter()-begin
            assert result.device.type == "cuda" and result.dtype == torch.float16
            assert result.shape == sample.shape and torch.isfinite(result).all().item()
            restored = result.float().cpu()
            error = (restored-expected).abs().max().item()
            assert torch.allclose(restored, expected, atol=0.02, rtol=0.02)
            emit("cuda_forward_passed", seconds=round(elapsed, 6), shape=list(result.shape),
                 dtype=str(result.dtype), max_absolute_error=error,
                 allocator_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                 allocator_peak_reserved_bytes=torch.cuda.max_memory_reserved())
    emit("diffusers_test_passed", total_seconds=round(time.perf_counter()-started, 6),
         pretrained_weights_loaded=False, image_generated=False)
    time.sleep(1)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-diffusers-mini", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(worker())
    if not args.run_diffusers_mini:
        parser.error("Autorisation explicite requise : --run-diffusers-mini")
    raise SystemExit(supervise(
        worker_script=Path(__file__).resolve(), test_name="5_diffusers_mini_only",
        output_group="diffusers-mini", success_event="diffusers_test_passed",
        excluded_tests=(), gpu_mode=True,
    ))
