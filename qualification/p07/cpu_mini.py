"""Test 1 seulement : tenseurs CPU FP16/I64 ; aucun poids, Safetensors, Diffusers ou CUDA."""

import argparse
import ctypes as c
import faulthandler
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from common import QualificationError, exclusive, paths, require_environment
from load_guard_windows import ChildJob, Performance, Telemetry

RAM_RESERVE_MIB = 1536
PRIVATE_CAP_MIB = 3286
TIMEOUT_SECONDS = 30


def emit(event, **values):
    print(json.dumps({"event": event, **values}), flush=True)


def worker():
    if sys.stdin.buffer.readline(32).rstrip(b"\r\n") != b"CPU_ONLY":
        return 1
    started = time.perf_counter()
    assert faulthandler.is_enabled()
    emit("before_torch_import", pid=os.getpid(), faulthandler_enabled=faulthandler.is_enabled())
    import torch
    if torch.__version__ != "2.7.1+cu118":
        raise QualificationError("Version PyTorch différente de la version autorisée.")
    emit("torch_imported", seconds=round(time.perf_counter() - started, 6))
    cases = [("FP16", torch.float16, [[0, 1, -2, 0.5], [3, -4, 8, 16]]),
             ("I64", torch.int64, [[0, 1, -2, 3], [4, 5, 6, 7]])]
    operations_start = time.perf_counter()
    for name, dtype, expected in cases:
        emit("before_creation", dtype=name)
        tensor = torch.tensor(expected, dtype=dtype, device="cpu")
        assert tensor.device.type == "cpu" and tensor.dtype == dtype
        emit("created", dtype=name, elements=tensor.numel(),
             bytes=tensor.numel()*tensor.element_size())
        clone = tensor.clone()
        destination = torch.empty_like(tensor, device="cpu")
        destination.copy_(tensor)
        assert tensor.tolist() == expected
        assert clone.tolist() == expected and destination.tolist() == expected
        assert tensor[0, 0].item() == 0 and tensor[0, 2].item() == -2
        assert tensor[-1, -1].item() == expected[-1][-1]
        clone[0, 0] = 2
        assert tensor[0, 0].item() == 0 and clone[0, 0].item() == 2
        assert destination.data_ptr() != tensor.data_ptr() != clone.data_ptr()
        emit("creation_copy_read_passed", dtype=name, device="cpu")
    emit("cpu_test_passed", operations_seconds=round(time.perf_counter()-operations_start, 6),
         total_seconds=round(time.perf_counter()-started, 6), tensor_payload_bytes=240,
         gpu_used=False, cuda_context_initialized=torch.cuda.is_initialized(), weights_loaded=False,
         excluded_modules_loaded=[n for n in ("safetensors", "diffusers", "accelerate")
                                  if n in sys.modules])
    time.sleep(1)  # Mesure du processus résident, pas de boucle de stress.
    return 0


def memory_reader():
    library = c.WinDLL(str(Path(os.environ["SystemRoot"]) / "System32/psapi.dll"))
    library.GetPerformanceInfo.argtypes = [c.POINTER(Performance), c.c_ulong]
    library.GetPerformanceInfo.restype = c.c_int

    def read():
        value = Performance()
        value.cb = c.sizeof(value)
        if not library.GetPerformanceInfo(c.byref(value), value.cb):
            raise QualificationError("Télémétrie RAM perdue.")
        return {"monotonic_s": time.monotonic(),
                "ram_available_mib": round(value.available*value.page_size/1024**2, 2),
                "commit_headroom_mib": round((value.limit-value.commit)*value.page_size/1024**2, 2),
                "commit_percent": round(100*value.commit/value.limit, 2)}
    return read


def summarize(samples):
    result = {"samples": len(samples),
            "ram_min_mib": min(s["ram_available_mib"] for s in samples),
            "ram_max_mib": max(s["ram_available_mib"] for s in samples),
            "commit_percent_max": max(s["commit_percent"] for s in samples),
            "rss_peak_sampled_mib": max(s.get("rss_mib", 0) for s in samples),
            "rss_peak_windows_mib": max(s.get("peak_wset_mib", 0) for s in samples),
            "private_peak_sampled_mib": max(s.get("private_mib", 0) for s in samples)}
    if "vram_free_mib" in samples[0]:
        result.update(vram_free_min_mib=min(s["vram_free_mib"] for s in samples),
                      vram_used_peak_sampled_mib=max(s["vram_used_mib"] for s in samples))
    return result


def supervise(*, worker_script=None, test_name="1_cpu_mini_only", output_group="cpu-mini",
              success_event="cpu_test_passed", excluded_tests=(2, 3, 4, 5), worker_args=(),
              gpu_mode=False, private_cap_mib=PRIVATE_CAP_MIB, initial_ram_min_mib=None,
              initial_vram_min_mib=512, timeout_seconds=TIMEOUT_SECONDS, cancel_event=None):
    import psutil
    require_environment()
    report = {"test": test_name, "attempts": 0, "weights_loaded": False,
              "generation_executed": False, "tests_not_executed": list(excluded_tests),
              "policy": {"ram_reserve_mib": RAM_RESERVE_MIB, "timeout_s": timeout_seconds,
                         "private_commit_cap_mib": private_cap_mib, "sample_target_ms": 100}}
    with exclusive():
        output = paths()[0] / output_group / uuid.uuid4().hex[:12]
        output.mkdir(parents=True, exist_ok=False)
        telemetry = Telemetry() if gpu_mode else None
        read = telemetry.read if telemetry else memory_reader()
        baseline, samples, recovery = [], [], []
        process, job, timer = None, None, None
        try:
            if gpu_mode:
                time.sleep(0.3)
                report["policy"]["vram_reserve_mib"] = 512
            for _ in range(10):
                baseline.append(read())
                time.sleep(0.2)
            report["before"] = baseline[-1]
            initial_min = initial_ram_min_mib or RAM_RESERVE_MIB + 768
            report["policy"]["initial_ram_min_mib"] = initial_min
            if (min(s["ram_available_mib"] for s in baseline) < initial_min
                    or baseline[-1]["commit_headroom_mib"] < 4096):
                raise QualificationError("Marge système insuffisante pour ce petit test.")
            if gpu_mode:
                report["policy"]["initial_vram_min_mib"] = initial_vram_min_mib
            if gpu_mode and min(s["vram_free_mib"] for s in baseline) < initial_vram_min_mib:
                raise QualificationError("Réserve VRAM initiale insuffisante.")
            job = ChildJob(private_cap_mib)
            env = dict(os.environ, CUDA_VISIBLE_DEVICES="0" if gpu_mode else "-1",
                       HF_HUB_OFFLINE="1",
                       TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
            with (output / "events.jsonl").open("wb") as events, (
                output / "faulthandler.log"
            ).open("wb") as errors:
                process = subprocess.Popen([
                    sys.executable, "-X", "faulthandler", "-X", "utf8", "-u",
                    str(worker_script or Path(__file__).resolve()), "--worker", *worker_args,
                ], stdin=subprocess.PIPE, stdout=events, stderr=errors, env=env, creationflags=0x4)
                job.attach(process)
                started = time.monotonic()
                deadline_hit = threading.Event()

                def deadline():
                    deadline_hit.set()
                    if process.poll() is None:
                        job.stop()

                timer = threading.Timer(timeout_seconds, deadline)
                timer.daemon = True
                timer.start()
                report["attempts"] = 1
                job.resume(process)
                process.stdin.write(b"CPU_ONLY\n")
                process.stdin.flush()
                process.stdin.close()
                reason = None
                while process.poll() is None:
                    if cancel_event is not None and cancel_event.is_set():
                        reason = "worker_stopped"
                        job.stop()
                        break
                    try:
                        sample = read()
                        memory = []
                        for pid in job.member_pids():
                            try:
                                memory.append(psutil.Process(pid).memory_info())
                            except psutil.NoSuchProcess:
                                pass
                        sample.update(elapsed_s=round(time.monotonic()-started, 6),
                                      rss_mib=round(sum(m.rss for m in memory)/1024**2, 2),
                                      private_mib=round(sum(m.private for m in memory)/1024**2, 2),
                                      peak_wset_mib=round(
                                          sum(m.peak_wset for m in memory)/1024**2, 2,
                                      ),
                                      actual_job_members=len(memory))
                        samples.append(sample)
                        if sample["ram_available_mib"] < RAM_RESERVE_MIB:
                            reason = "ram_reserve"
                        elif gpu_mode and sample["vram_free_mib"] < 512:
                            reason = "vram_reserve"
                        elif sample["commit_headroom_mib"] < 4096 or sample["commit_percent"] > 90:
                            reason = "system_commit"
                    except Exception:
                        reason = "telemetry_unavailable"
                    if reason:
                        job.stop()
                        break
                    time.sleep(0.1)
                process.wait(timeout=5)
                timer.cancel()
                timer.join(timeout=2)
                if deadline_hit.is_set():
                    reason = "timeout"
                report.update(exit_code=process.returncode,
                              exit_hex=f"0x{process.returncode & 0xffffffff:08X}",
                              stop_reason=reason,
                              subprocess_seconds=round(time.monotonic()-started, 6),
                              native_commit_peaks=job.memory_peaks(),
                              remaining_job_members=job.member_pids())
                job.close()
                job = None
            report["events"] = [json.loads(line) for line in (
                output / "events.jsonl"
            ).read_text(encoding="utf-8").splitlines()]
            report["weights_loaded"] = any(e.get("weights_loaded", False)
                                           for e in report["events"])
            report["generation_executed"] = any(e["event"] == "before_inference"
                                                for e in report["events"])
            log = (output / "faulthandler.log").read_text(encoding="utf-8", errors="replace")
            report["stderr_bytes"] = (output / "faulthandler.log").stat().st_size
            report["native_error_logged"] = (
                "fatal" in log.lower() or "access violation" in log.lower()
            )
            for _ in range(30):
                recovery.append(read())
                time.sleep(0.5)
            report["after"] = recovery[-1]
            before_commit = report["before"]["commit_headroom_mib"]
            report["near_initial_resources"] = (
                recovery[-1]["ram_available_mib"] >= report["before"]["ram_available_mib"]-256
                and recovery[-1]["commit_headroom_mib"] >= before_commit-256
            )
            if gpu_mode:
                report["near_initial_resources"] &= (
                    recovery[-1]["vram_free_mib"] >= report["before"]["vram_free_mib"]-256
                )
            report["success"] = (report["exit_code"] == 0 and reason is None
                                 and any(e["event"] == success_event for e in report["events"]))
        except Exception as exc:
            report.update(success=False, error=str(exc) if isinstance(exc, QualificationError)
                          else type(exc).__name__)
        finally:
            if timer is not None:
                timer.cancel()
                timer.join(timeout=2)
            if job is not None:
                job.close()
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
            if telemetry is not None:
                telemetry.close()
            report.update(baseline_summary=summarize(baseline) if baseline else None,
                          during_summary=summarize(samples) if samples else None,
                          recovery_summary=summarize(recovery) if recovery else None,
                          baseline_samples=baseline, during_samples=samples,
                          recovery_samples=recovery)
            (output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if not k.endswith("samples")}, indent=2))
        print("Rapport", test_name, ":", output.name)
        return 0 if report.get("success") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-cpu-mini", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.worker:
        raise SystemExit(worker())
    if not arguments.run_cpu_mini:
        parser.error("Autorisation explicite requise : --run-cpu-mini")
    raise SystemExit(supervise())
