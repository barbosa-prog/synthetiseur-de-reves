"""Un seul essai de chargement GPU, surveillé extérieurement, sans génération."""

import argparse
import json
import queue
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from common import QualificationError, exclusive, paths, require_environment
from load_guard_windows import ChildJob, Telemetry

RAM_RESERVE = 1536
RAM_WARNING = 2048
VRAM_RESERVE = 512
COMMIT_RESERVE = 4096
TIMEOUT = 120


def stop_reason(sample, elapsed, page_pressure_duration):
    if sample["ram_available_mib"] < RAM_RESERVE:
        return "ram_reserve"
    if sample["vram_free_mib"] < VRAM_RESERVE:
        return "vram_reserve"
    if sample["commit_headroom_mib"] < COMMIT_RESERVE or sample["commit_percent"] > 90:
        return "system_commit"
    if page_pressure_duration >= 5:
        return "sustained_page_reads_under_ram_pressure"
    if elapsed >= TIMEOUT:
        return "timeout"
    return None


def summarize(samples):
    return {
        "sample_count": len(samples),
        "ram_min_mib": min(s["ram_available_mib"] for s in samples),
        "ram_max_mib": max(s["ram_available_mib"] for s in samples),
        "vram_free_min_mib": min(s["vram_free_mib"] for s in samples),
        "vram_used_max_mib": max(s["vram_used_mib"] for s in samples),
        "commit_percent_max": max(s["commit_percent"] for s in samples),
        "page_reads_mean_per_s": round(statistics.mean(s["page_reads_per_s"] for s in samples), 2),
        "page_reads_max_per_s": max(s["page_reads_per_s"] for s in samples),
        "process_rss_peak_mib": max(s.get("process_rss_mib", 0) for s in samples),
        "process_private_peak_mib": max(s.get("process_private_mib", 0) for s in samples),
        "process_windows_peak_wset_mib": max(s.get("process_peak_wset_mib", 0) for s in samples),
    }


def run():
    import psutil
    require_environment()
    with exclusive():
        telemetry = Telemetry()
        process, job, deadline_timer = None, None, None
        report = {"generation_executed": False, "attempt_count": 0, "events": [],
                  "policy": {"ram_reserve_mib": RAM_RESERVE, "ram_warning_mib": RAM_WARNING,
                             "vram_reserve_mib": VRAM_RESERVE, "timeout_s": TIMEOUT,
                             "commit_reserve_mib": COMMIT_RESERVE, "sampling_target_s": 0.1}}
        output = paths()[0] / "load-only" / uuid.uuid4().hex[:12]
        output.mkdir(parents=True, exist_ok=False)
        try:
            time.sleep(0.3)  # Deux collectes PDH sont nécessaires pour calculer un taux.
            baseline = []
            for _ in range(20):
                baseline.append(telemetry.read())
                time.sleep(0.25)
            report["baseline"] = summarize(baseline)
            report["baseline_samples"] = baseline
            before = baseline[-1]
            if stop_reason(before, 0, 0):
                raise QualificationError("Réserves système initiales non respectées.")
            budget = min(s["ram_available_mib"] for s in baseline) - RAM_RESERVE - 256
            if budget < 1024:
                raise QualificationError("Budget de profilage inférieur à 1 Gio après réserves.")
            # Le commit privé inclut environ 1 Gio d'import/DLL déjà observé, pas seulement du RSS.
            private_cap = int(min(4096, budget + 1024))
            report["policy"]["process_private_commit_cap_mib"] = private_cap
            page_limit = max(100, sorted(s["page_reads_per_s"] for s in baseline)[-2] * 4)
            report["policy"]["page_reads_pressure_threshold_per_s"] = page_limit
            job = ChildJob(private_cap)
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name("load_only_worker.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", creationflags=0x4,
            )
            job.attach(process)
            child = psutil.Process(process.pid)
            events = queue.Queue()

            def read_events():
                for line in process.stdout:
                    try:
                        events.put(json.loads(line))
                    except ValueError:
                        events.put({"event": "non_json_output_redacted"})

            reader = threading.Thread(target=read_events, daemon=True)
            reader.start()
            started = time.monotonic()
            deadline_hit = threading.Event()

            def deadline_stop():
                deadline_hit.set()
                if process.poll() is None:
                    job.stop()

            deadline_timer = threading.Timer(TIMEOUT, deadline_stop)
            deadline_timer.daemon = True
            deadline_timer.start()
            pressure_since = None
            samples = []
            report["attempt_count"] = 1
            job.resume(process)
            process.stdin.write("LOAD_ONLY\n")
            process.stdin.flush()
            process.stdin.close()
            reason = None
            while process.poll() is None:
                try:
                    sample = telemetry.read()
                    members = [child, *child.children(recursive=True)]
                    memory = [member.memory_info() for member in members]
                    sample.update(
                        elapsed_s=round(time.monotonic() - started, 3),
                        process_rss_mib=round(sum(m.rss for m in memory) / 1024**2, 2),
                        process_private_mib=round(sum(m.private for m in memory) / 1024**2, 2),
                        process_peak_wset_mib=round(sum(m.peak_wset for m in memory) / 1024**2, 2),
                        owned_process_count=len(members),
                    )
                    samples.append(sample)
                    pressured = (sample["ram_available_mib"] < RAM_WARNING
                                 and sample["page_reads_per_s"] > page_limit)
                    if pressured and pressure_since is None:
                        pressure_since = time.monotonic()
                    if not pressured:
                        pressure_since = None
                    duration = time.monotonic() - pressure_since if pressure_since else 0
                    reason = stop_reason(sample, time.monotonic() - started, duration)
                except psutil.NoSuchProcess:
                    break
                except Exception:
                    reason = "telemetry_unavailable"
                while not events.empty():
                    report["events"].append(events.get_nowait())
                if reason:
                    job.stop()
                    break
                time.sleep(0.1)
            process.wait(timeout=10)
            if deadline_hit.is_set() and reason is None:
                reason = "timeout"
            deadline_timer.cancel()
            deadline_timer.join(timeout=2)
            reader.join(timeout=2)
            while not events.empty():
                report["events"].append(events.get_nowait())
            report.update(stop_reason=reason, child_exit_code=process.returncode,
                          child_elapsed_s=round(time.monotonic() - started, 3),
                          during=summarize(samples) if samples else None, during_samples=samples)
            job.close()
            job = None
            report["child_exited"] = process.poll() is not None
            recovery = []
            for _ in range(30):
                recovery.append(telemetry.read())
                time.sleep(0.5)
            report["recovery"] = summarize(recovery)
            report["after"] = recovery[-1]
            report["recovery_samples"] = recovery
            report["resources_near_baseline"] = (
                recovery[-1]["ram_available_mib"] >= before["ram_available_mib"] - 256
                and recovery[-1]["vram_free_mib"] >= before["vram_free_mib"] - 256
            )
            report["load_success"] = (
                reason is None and process.returncode == 0
                and any(e["event"] == "load_only_complete" for e in report["events"])
            )
        except Exception as exc:
            report["supervisor_error"] = (str(exc) if isinstance(exc, QualificationError)
                                          else type(exc).__name__)
            report["load_success"] = False
        finally:
            if deadline_timer is not None:
                deadline_timer.cancel()
                deadline_timer.join(timeout=2)
            if job is not None:
                job.close()  # Kill-on-close ne vise que le sous-processus attaché.
            if process is not None:
                if process.poll() is None:
                    process.terminate()  # Uniquement notre Popen, jamais une recherche par nom.
                process.wait(timeout=10)
                if process.stdout:
                    process.stdout.close()
            telemetry.close()
            (output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        summary = {k: v for k, v in report.items() if not k.endswith("samples")}
        print(json.dumps(summary, indent=2))
        return 0 if report.get("load_success") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-load-only", action="store_true")
    arguments = parser.parse_args()
    if not arguments.run_load_only:
        parser.error("Accord explicite de chargement seul requis : --run-load-only")
    try:
        raise SystemExit(run())
    except Exception as error:
        print(json.dumps({"load_success": False, "generation_executed": False,
                          "supervisor_error": type(error).__name__}))
        raise SystemExit(1) from None
