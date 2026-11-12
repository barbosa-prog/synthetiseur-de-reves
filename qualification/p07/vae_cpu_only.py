"""Un seul essai de chargement du VAE réel sur CPU, sans calcul ni CUDA."""

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
    from diffusers import AutoencoderKL
    assert not torch.cuda.is_initialized()
    emit("imports_ready", seconds=round(time.perf_counter()-started, 6))
    emit("before_vae_load", device="cpu", dtype="float16", low_cpu_mem_usage=True,
         local_files_only=True, variant="fp16")
    begin = time.perf_counter()
    model = AutoencoderKL.from_pretrained(
        str(paths()[2] / "vae"), torch_dtype=torch.float16, variant="fp16",
        use_safetensors=True, low_cpu_mem_usage=True, local_files_only=True,
        device_map={"": "cpu"},
    )
    elapsed = time.perf_counter()-begin
    emit("after_vae_load", seconds=round(elapsed, 6), weights_loaded=True)
    assert all(p.device.type == "cpu" and p.dtype == torch.float16
               for p in model.parameters())
    assert not torch.cuda.is_initialized()
    emit("vae_cpu_load_passed", parameters=sum(p.numel() for p in model.parameters()),
         total_seconds=round(time.perf_counter()-started, 6), weights_loaded=True,
         cuda_context_initialized=False, encode_decode_executed=False)
    time.sleep(1)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-vae-cpu-only", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(worker())
    if not args.run_vae_cpu_only:
        parser.error("Autorisation explicite requise : --run-vae-cpu-only")
    raise SystemExit(supervise(
        worker_script=Path(__file__).resolve(), test_name="real_vae_cpu_only",
        output_group="vae-cpu-only", success_event="vae_cpu_load_passed",
        excluded_tests=(),
    ))
