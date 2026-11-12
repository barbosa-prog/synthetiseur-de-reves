"""Surveillant indépendant du modèle et du worker ; aucune dépendance production."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def stop_reason(available, private, elapsed, config):
    if available < config["min_free_mib"]:
        return "insufficient_memory"
    if private > config["private_limit_mib"]:
        return "insufficient_memory"
    if elapsed > config["timeout_seconds"]:
        return "timeout"
    return None


def main(*, child_script=None):
    import msvcrt

    import psutil

    qualification = Path(__file__).resolve().parents[1] / "qualification/p08"
    sys.path.insert(0, str(qualification))
    from watch import commit_headroom

    payload = json.loads(sys.stdin.buffer.readline(131073))
    config = payload["configuration"]
    root = Path(os.environ["LOCALAPPDATA"]) / "SynthetiseurDeReves/qualification/p08-worker"
    root.mkdir(parents=True, exist_ok=True)
    gone = threading.Event()

    def parent_watch():
        # Ne pas garder le verrou BufferedReader dans un thread daemon : cela
        # provoque un arrêt natif de CPython à la fermeture sous Windows.
        try:
            os.read(sys.stdin.fileno(), 1)
        finally:
            gone.set()

    threading.Thread(target=parent_watch, daemon=True).start()
    before = psutil.virtual_memory().available / 2**20
    commit_before = commit_headroom() / 2**20
    if before < config["initial_free_mib"] or commit_before < 4096:
        return dict(error="insufficient_memory", metrics=dict(available_before_mib=before))
    with (root / "cpu.lock").open("a+b") as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return dict(error="worker_busy")
        with tempfile.TemporaryDirectory(prefix="emotion-", dir=root) as temporary:
            output = Path(temporary) / "output.json"
            start = time.perf_counter()
            minimum, peak_rss, peak_private, cpu_seconds = before, 0, 0, 0
            child = None
            members = []
            error = None
            with output.open("wb") as out:
                try:
                    child = subprocess.Popen(
                        [
                            sys.executable,
                            "-X",
                            "faulthandler",
                            str(child_script or Path(__file__).with_name("emotion_cpu_child.py")),
                        ],
                        stdin=subprocess.PIPE,
                        stdout=out,
                        stderr=subprocess.DEVNULL,
                        env={
                            **os.environ,
                            "CUDA_VISIBLE_DEVICES": "",
                            "HF_HUB_OFFLINE": "1",
                            "TRANSFORMERS_OFFLINE": "1",
                        },
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    child.stdin.write(
                        json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
                    )
                    child.stdin.close()
                    process = psutil.Process(child.pid)
                    members = [process]
                    while child.poll() is None:
                        available = psutil.virtual_memory().available / 2**20
                        minimum = min(minimum, available)
                        private = 0
                        try:
                            members = [process, *process.children(recursive=True)]
                        except psutil.NoSuchProcess:
                            break
                        for member in members:
                            try:
                                info = member.memory_info()
                                try:
                                    member.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                                except psutil.AccessDenied:
                                    pass
                                private += info.private / 2**20
                                peak_rss = max(peak_rss, info.peak_wset / 2**20)
                                peak_private = max(peak_private, info.peak_pagefile / 2**20)
                                times = member.cpu_times()
                                cpu_seconds = max(cpu_seconds, times.user + times.system)
                            except psutil.NoSuchProcess:
                                pass
                        error = stop_reason(available, private, time.perf_counter() - start, config)
                        if gone.is_set():
                            error = "worker_stopped"
                        if commit_headroom() / 2**20 < 1024:
                            error = "insufficient_memory"
                        if output.stat().st_size > 16384:
                            error = "invalid_result"
                        if error:
                            break
                        time.sleep(0.1)
                finally:
                    if child and child.poll() is None:
                        for member in reversed(members):
                            try:
                                member.kill()
                            except psutil.NoSuchProcess:
                                pass
                        child.kill()
                    if child:
                        child.wait(timeout=10)
            duration = time.perf_counter() - start
            if error:
                result = dict(error=error)
            elif child.returncode or output.stat().st_size > 16384:
                result = dict(error="provider_failed")
            else:
                result = json.loads(output.read_text(encoding="utf-8"))
            time.sleep(1)
            result["metrics"] = dict(
                seconds=duration,
                peak_rss_mib=peak_rss,
                peak_private_mib=peak_private,
                available_before_mib=before,
                available_min_mib=minimum,
                available_after_mib=psutil.virtual_memory().available / 2**20,
                cpu_seconds=cpu_seconds,
                exit_code=child.returncode,
                commit_headroom_before_mib=commit_before,
                commit_headroom_after_mib=commit_headroom() / 2**20,
                process_gone=not psutil.pid_exists(child.pid),
            )
            return result


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        result = dict(error="provider_failed")
    print(json.dumps(result), flush=True)
