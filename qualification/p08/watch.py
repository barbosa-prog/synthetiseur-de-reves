"""Surveillant CPU indépendant ; ne charge ni torch ni Transformers."""

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

MIB = 2**20
MIN_FREE = 1536*MIB
MAX_PRIVATE = 3072*MIB
TIMEOUT = 600


def memory():
    return psutil.virtual_memory().available


def commit_headroom():
    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in
            ["total", "available", "page", "page_available", "virtual", "virtual_available", "ext"]]
    status = Status()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise RuntimeError("Lecture mémoire Windows impossible")
    return status.page_available


def main(*, root=None, script=None, arguments=None):
    root = root or Path(os.environ["LOCALAPPDATA"])/"SynthetiseurDeReves/qualification/p08"
    script = script or Path(__file__).with_name("evaluate.py")
    arguments = sys.argv[1:] if arguments is None else arguments
    root.mkdir(parents=True, exist_ok=True)
    before = memory()
    headroom = commit_headroom()
    if before < MIN_FREE+1024*MIB or headroom < 4096*MIB:
        raise SystemExit("Précontrôle défavorable : réserve 1536 + budget initial 1024 Mio requis")
    print(f"RAM avant : {before/MIB:.1f} Mio ; marge engagée : {headroom/MIB:.1f} Mio", flush=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}
    start = time.perf_counter()
    minimum, peak_rss, peak_private, group_private_peak = before, 0, 0, 0
    per_process = {}
    samples, stop_reason = [], None
    with (root/"evaluation.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-X", "faulthandler",
                                  str(script), *arguments],
                                 env=env, stdout=log, stderr=subprocess.STDOUT)
        process = psutil.Process(child.pid)
        try:
            while child.poll() is None:
                available = memory()
                minimum = min(minimum, available)
                try:
                    members = [process, *process.children(recursive=True)]
                    private, rss = 0, 0
                    for member in members:
                        try:
                            info = member.memory_info()
                        except psutil.NoSuchProcess:
                            continue
                        private += info.private
                        rss += info.rss
                        peak_rss = max(peak_rss, info.peak_wset)
                        peak_private = max(peak_private, info.peak_pagefile)
                        per_process[member.pid] = max(per_process.get(member.pid, 0),
                                                      info.peak_pagefile/MIB)
                    group_private_peak = max(group_private_peak, private)
                except psutil.NoSuchProcess:
                    break
                elapsed = time.perf_counter()-start
                samples.append(dict(seconds=elapsed, available_mib=available/MIB,
                                    rss_mib=rss/MIB, private_mib=private/MIB))
                if available < MIN_FREE:
                    stop_reason = "ram_reserve"
                elif private > MAX_PRIVATE:
                    stop_reason = "private_limit"
                elif elapsed > TIMEOUT:
                    stop_reason = "timeout"
                elif commit_headroom() < 1024*MIB:
                    stop_reason = "commit_headroom"
                if stop_reason:
                    for member in reversed(members):
                        try:
                            member.kill()
                        except psutil.NoSuchProcess:
                            pass
                    child.kill()
                    break
                time.sleep(0.1)
            code = child.wait(timeout=10)
        finally:
            if child.poll() is None:
                for member in process.children(recursive=True):
                    try:
                        member.kill()
                    except psutil.NoSuchProcess:
                        pass
                child.kill()
                child.wait(timeout=10)
    duration = time.perf_counter()-start
    time.sleep(3)
    report = dict(exit_code=code, stop_reason=stop_reason, seconds=duration,
                  reserve_mib=MIN_FREE/MIB, private_limit_mib=MAX_PRIVATE/MIB,
                  timeout_seconds=TIMEOUT, available_before_mib=before/MIB,
                  available_min_mib=minimum/MIB, available_after_mib=memory()/MIB,
                  peak_rss_mib=peak_rss/MIB, peak_private_mib=peak_private/MIB,
                  group_private_peak_mib=group_private_peak/MIB,
                  per_process_private_peak_mib=per_process,
                  commit_headroom_before_mib=headroom/MIB,
                  commit_headroom_after_mib=commit_headroom()/MIB,
                  process_gone=not psutil.pid_exists(child.pid))
    (root/"memory.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (root/"memory-samples.json").write_text(json.dumps(samples), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 1 if stop_reason or code else 0


if __name__ == "__main__":
    raise SystemExit(main())
