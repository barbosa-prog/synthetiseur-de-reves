"""Surveillant GPU applicatif ; aucune génération avant invocation explicite du worker."""

import json
import shutil
import sys
import threading
from pathlib import Path

from common import paths
from cpu_mini import supervise


def main():
    directory = Path(sys.argv[1]).resolve()
    if directory.parent != paths()[0] or not directory.name.startswith("private-image-"):
        return 1
    stopped = threading.Event()

    def watch_parent():
        sys.stdin.buffer.read(1)  # Le parent maintient le pipe ouvert, sans contenu.
        stopped.set()

    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        supervise(worker_script=Path(__file__).with_name("image_job_gpu.py"),
                  test_name="application_image_job", output_group=directory.name,
                  success_event="application_image_finished", excluded_tests=(),
                  worker_args=(str(directory),), gpu_mode=True, private_cap_mib=7168,
                  initial_ram_min_mib=4096, initial_vram_min_mib=4096,
                  timeout_seconds=120, cancel_event=stopped)
        metrics = list(directory.glob("*/metrics.json"))
        status = {"error": "provider_failed"}
        if metrics:
            report = json.loads(metrics[0].read_text(encoding="utf-8"))
            if report.get("success"):
                event = next(e for e in report["events"]
                             if e["event"] == "application_image_finished")
                status = {"blocked": event["blocked"]}
            else:
                reason = report.get("stop_reason")
                if reason == "timeout":
                    status = {"error": "timeout"}
                elif reason == "worker_stopped":
                    status = {"error": "worker_stopped"}
                elif reason in {"ram_reserve", "vram_reserve", "system_commit"}:
                    status = {"error": "insufficient_memory"}
                elif report.get("attempts") == 0:
                    status = {"error": "insufficient_memory"}
                for event in report.get("events", []):
                    if event["event"] == "memory_refused":
                        status = {"error": "insufficient_memory"}
        (directory / "status.json").write_text(json.dumps(status), encoding="utf-8")
        return 0
    finally:
        if stopped.is_set():
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
