"""Test 3 uniquement : petit fichier synthétique, safe_open/get_tensor CPU."""

import argparse
import faulthandler
import os
import sys
import tempfile
import time
from pathlib import Path

from common import QualificationError, paths, require_environment
from cpu_mini import emit, supervise


def worker(filename):
    if sys.stdin.buffer.readline(32).rstrip(b"\r\n") != b"CPU_ONLY":
        return 1
    assert faulthandler.is_enabled()
    target = Path(filename).resolve()
    root = paths()[0] / "safetensors-file-mini"
    if not target.is_relative_to(root) or target.name != "synthetic.safetensors":
        raise QualificationError("Fichier synthétique hors du dossier autorisé.")
    started = time.perf_counter()
    emit("before_imports", pid=os.getpid(), faulthandler_enabled=True)
    import safetensors
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file
    if torch.__version__ != "2.7.1+cu118" or safetensors.__version__ != "0.7.0":
        raise QualificationError("Versions différentes de celles autorisées.")
    emit("imports_ready", seconds=round(time.perf_counter()-started, 6),
         torch_version=torch.__version__, safetensors_version=safetensors.__version__)
    operations_start = time.perf_counter()
    reference = {"fp16": [[0, 1, -2, 0.5], [3, -4, 8, 16]],
                 "i64": [[0, 1, -2, 3], [2**40, -(2**40), 6, 7]]}
    original = {"fp16": torch.tensor(reference["fp16"], dtype=torch.float16, device="cpu"),
                "i64": torch.tensor(reference["i64"], dtype=torch.int64, device="cpu")}
    emit("before_save_file", tensor_payload_bytes=80)
    begin = time.perf_counter()
    save_file(original, str(target))
    emit("file_saved", bytes=target.stat().st_size, seconds=round(time.perf_counter()-begin, 6))
    emit("before_safe_open")
    begin = time.perf_counter()
    with safe_open(str(target), framework="pt", device="cpu") as handle:
        emit("safe_open_entered")
        assert set(handle.keys()) == set(original)
        for name, expected in original.items():
            emit("before_get_tensor", tensor=name)
            actual = handle.get_tensor(name)
            emit("get_tensor_returned", tensor=name)
            assert actual.device.type == "cpu"
            assert actual.dtype == expected.dtype
            assert actual.shape == expected.shape
            assert actual.tolist() == reference[name]
            assert torch.equal(actual, expected)
            emit("file_tensor_verified", tensor=name, dtype=str(actual.dtype),
                 shape=list(actual.shape), exact_values_equal=True)
            del actual
    emit("file_read_verified", seconds=round(time.perf_counter()-begin, 6))
    del handle
    target.unlink()
    emit("temporary_file_removed", exists=target.exists())
    assert not torch.cuda.is_initialized()
    excluded = [n for n in ("diffusers", "transformers", "accelerate") if n in sys.modules]
    assert not excluded
    emit("safetensors_file_test_passed", operations_seconds=round(
        time.perf_counter()-operations_start, 6),
        total_seconds=round(time.perf_counter()-started, 6),
        weights_loaded=False, cuda_context_initialized=False, excluded_modules_loaded=excluded)
    time.sleep(1)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-file-roundtrip", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--synthetic-file", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if not args.synthetic_file:
            parser.error("Fichier synthétique requis.")
        raise SystemExit(worker(args.synthetic_file))
    if not args.run_file_roundtrip:
        parser.error("Autorisation explicite requise : --run-file-roundtrip")
    require_environment()
    folder = paths()[0] / "safetensors-file-mini"
    folder.mkdir(parents=True, exist_ok=True)
    # Le parent nettoie également le fichier si le worker subit un crash natif.
    with tempfile.TemporaryDirectory(prefix="synthetic-", dir=folder) as temporary:
        result = supervise(
            worker_script=Path(__file__).resolve(), test_name="3_safetensors_file_only",
            output_group="safetensors-file-mini", success_event="safetensors_file_test_passed",
            excluded_tests=(4, 5),
            worker_args=("--synthetic-file", str(Path(temporary) / "synthetic.safetensors")),
        )
    print("Dossier temporaire supprimé :", not Path(temporary).exists())
    raise SystemExit(result)
