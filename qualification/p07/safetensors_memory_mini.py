"""Test 2 uniquement : sérialisation/désérialisation Safetensors en mémoire, sur CPU."""

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
    emit("before_imports", pid=os.getpid(), faulthandler_enabled=faulthandler.is_enabled())
    import safetensors
    import torch
    from safetensors.torch import load, save
    if torch.__version__ != "2.7.1+cu118" or safetensors.__version__ != "0.7.0":
        raise QualificationError("Versions différentes de celles autorisées.")
    emit("imports_ready", seconds=round(time.perf_counter()-started, 6),
         torch_version=torch.__version__, safetensors_version=safetensors.__version__)
    operations_start = time.perf_counter()
    reference = {
        "fp16": [[0, 1, -2, 0.5], [3, -4, 8, 16]],
        "i64": [[0, 1, -2, 3], [2**40, -(2**40), 6, 7]],
    }
    original = {
        "fp16": torch.tensor(reference["fp16"], dtype=torch.float16, device="cpu"),
        "i64": torch.tensor(reference["i64"], dtype=torch.int64, device="cpu"),
    }
    emit("tensors_created", shapes={name: list(t.shape) for name, t in original.items()},
         tensor_payload_bytes=sum(t.numel()*t.element_size() for t in original.values()))
    emit("before_serialize_bytes")
    begin = time.perf_counter()
    payload = save(original)
    serialize_s = time.perf_counter()-begin
    assert isinstance(payload, bytes)
    emit("serialized_bytes", bytes=len(payload), seconds=round(serialize_s, 6))
    emit("before_deserialize_bytes")
    begin = time.perf_counter()
    restored = load(payload)
    deserialize_s = time.perf_counter()-begin
    emit("deserialized_bytes", seconds=round(deserialize_s, 6))
    assert set(restored) == set(original)
    for name, expected in original.items():
        actual = restored[name]
        assert actual.device.type == "cpu"
        assert actual.dtype == expected.dtype
        assert actual.shape == expected.shape
        assert actual.tolist() == reference[name]
        assert torch.equal(actual, expected)
        assert actual.data_ptr() != expected.data_ptr()
        emit("roundtrip_verified", tensor=name, dtype=str(actual.dtype), shape=list(actual.shape),
             exact_values_equal=True, device="cpu")
    assert not torch.cuda.is_initialized()
    excluded = [name for name in ("diffusers", "transformers", "accelerate") if name in sys.modules]
    assert not excluded
    emit("safetensors_memory_test_passed", serialized_bytes=len(payload),
         operations_seconds=round(time.perf_counter()-operations_start, 6),
         total_seconds=round(time.perf_counter()-started, 6),
         safetensors_file_used=False, mmap_used=False, weights_loaded=False,
         cuda_context_initialized=False, excluded_modules_loaded=excluded)
    time.sleep(1)  # Observation mémoire du processus résident, sans autre test.
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-memory-roundtrip", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.worker:
        raise SystemExit(worker())
    if not arguments.run_memory_roundtrip:
        parser.error("Autorisation explicite requise : --run-memory-roundtrip")
    raise SystemExit(supervise(
        worker_script=Path(__file__).resolve(), test_name="2_safetensors_memory_only",
        output_group="safetensors-memory-mini", success_event="safetensors_memory_test_passed",
        excluded_tests=(3, 4, 5),
    ))
