"""Test 4 uniquement : tenseurs synthétiques CPU vers CUDA puis CPU."""

import argparse
import faulthandler
import os
import sys
import time
from pathlib import Path

from common import QualificationError
from cpu_mini import emit, supervise


def worker():
    if sys.stdin.buffer.readline(32).rstrip(b"\r\n") != b"CPU_ONLY":
        return 1
    assert faulthandler.is_enabled()
    started = time.perf_counter()
    emit("before_import", pid=os.getpid(), faulthandler_enabled=True)
    import torch
    if torch.__version__ != "2.7.1+cu118":
        raise QualificationError("Version PyTorch différente de celle autorisée.")
    emit("torch_imported", seconds=round(time.perf_counter()-started, 6))
    assert not torch.cuda.is_initialized()
    emit("before_cuda_init")
    begin = time.perf_counter()
    torch.cuda.init()
    torch.cuda.synchronize()
    init_seconds = time.perf_counter()-begin
    name = torch.cuda.get_device_name(0)
    if "RTX 3060" not in name:
        raise QualificationError("GPU différent du GPU autorisé.")
    emit("cuda_initialized", seconds=round(init_seconds, 6), gpu=name,
         torch_cuda=torch.version.cuda)
    torch.cuda.reset_peak_memory_stats()
    for label, dtype, values in (
        ("FP16", torch.float16, [[0, 1, -2, 0.5], [3, -4, 8, 16]]),
        ("I64", torch.int64, [[0, 1, -2, 3], [2**40, -(2**40), 6, 7]]),
    ):
        original = torch.tensor(values, dtype=dtype, device="cpu")
        emit("before_cpu_to_cuda", dtype=label)
        begin = time.perf_counter()
        device_tensor = original.to("cuda:0")
        torch.cuda.synchronize()
        to_gpu = time.perf_counter()-begin
        begin = time.perf_counter()
        result = device_tensor + 1
        torch.cuda.synchronize()
        operation = time.perf_counter()-begin
        begin = time.perf_counter()
        restored = result.to("cpu")
        torch.cuda.synchronize()
        to_cpu = time.perf_counter()-begin
        assert restored.device.type == "cpu"
        assert restored.dtype == dtype and restored.shape == original.shape
        assert restored.tolist() == [[v+1 for v in row] for row in values]
        assert torch.equal(restored, original+1)
        emit("roundtrip_verified", dtype=label, shape=list(restored.shape),
             cpu_to_cuda_seconds=round(to_gpu, 6), gpu_add_seconds=round(operation, 6),
             cuda_to_cpu_seconds=round(to_cpu, 6), exact_values_equal=True)
        del device_tensor, result, original, restored
    excluded = [n for n in ("safetensors", "diffusers", "transformers", "accelerate")
                if n in sys.modules]
    assert not excluded
    emit("cuda_test_passed", total_seconds=round(time.perf_counter()-started, 6),
         allocator_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
         allocator_peak_reserved_bytes=torch.cuda.max_memory_reserved(),
         weights_loaded=False, excluded_modules_loaded=excluded)
    time.sleep(1)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-cuda-mini", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(worker())
    if not args.run_cuda_mini:
        parser.error("Autorisation explicite requise : --run-cuda-mini")
    raise SystemExit(supervise(
        worker_script=Path(__file__).resolve(), test_name="4_cuda_mini_only",
        output_group="cuda-mini", success_event="cuda_test_passed",
        excluded_tests=(5,), gpu_mode=True,
    ))
