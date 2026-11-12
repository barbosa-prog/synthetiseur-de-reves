"""Contrôles préalables : aucune bibliothèque IA ni aucun poids chargé."""

import ast
import subprocess
import sys
import time
import unittest
from pathlib import Path

import psutil
from common import gpu_info
from load_guard_windows import ChildJob, Telemetry
from load_only import stop_reason


class LoadProtectionTests(unittest.TestCase):
    def sample(self, **changes):
        return {"ram_available_mib": 3000, "vram_free_mib": 2000,
                "commit_headroom_mib": 15000, "commit_percent": 50, **changes}

    def test_no_model_generation_in_worker(self):
        tree = ast.parse(Path(__file__).with_name("load_only_worker.py").read_text("utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(call.func, ast.Name) and call.func.id == "pipeline"
                             for call in calls))
        self.assertFalse(any(isinstance(call.func, ast.Attribute) and call.func.attr == "__call__"
                             for call in calls))
        self.assertNotIn("generate.py", ast.unparse(tree))

    def test_ram_reserve(self):
        self.assertEqual(stop_reason(self.sample(ram_available_mib=1535), 0, 0), "ram_reserve")

    def test_vram_reserve(self):
        self.assertEqual(stop_reason(self.sample(vram_free_mib=511), 0, 0), "vram_reserve")

    def test_commit_reserve(self):
        self.assertEqual(stop_reason(self.sample(commit_headroom_mib=4095), 0, 0), "system_commit")
        self.assertEqual(stop_reason(self.sample(commit_percent=91), 0, 0), "system_commit")

    def test_timeout(self):
        self.assertEqual(stop_reason(self.sample(), 120, 0), "timeout")

    def test_sustained_page_pressure(self):
        self.assertEqual(stop_reason(self.sample(), 0, 5),
                         "sustained_page_reads_under_ram_pressure")

    def test_good_sample(self):
        self.assertIsNone(stop_reason(self.sample(), 0, 0))

    def test_native_telemetry(self):
        telemetry = Telemetry()
        try:
            time.sleep(0.3)
            sample = telemetry.read()
            reference = psutil.virtual_memory().available / 1024**2
            self.assertLess(abs(reference - sample["ram_available_mib"]), 256)
            self.assertLess(abs(gpu_info()["free_mib"] - sample["vram_free_mib"]), 128)
            self.assertGreater(sample["commit_headroom_mib"], 0)
            self.assertGreaterEqual(sample["page_reads_per_s"], 0)
        finally:
            telemetry.close()

    def launch(self, code, limit):
        job = ChildJob(limit)
        process = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, creationflags=0x4)
        try:
            job.attach(process)
            job.resume(process)
            process.stdin.write("START\n")
            process.stdin.flush()
            process.stdin.close()
        except Exception:
            job.close()
            process.wait(timeout=5)
            raise
        return job, process

    def test_job_kill_on_close_only_owned_process(self):
        code = "import sys,time; sys.stdin.readline(); print('READY',flush=True); time.sleep(20)"
        job, process = self.launch(code, 64)
        try:
            self.assertEqual(process.stdout.readline().strip(), "READY")
            members = [psutil.Process(process.pid), *psutil.Process(process.pid).children()]
            self.assertNotIn(psutil.Process().pid, [p.pid for p in members])
            job.close()
            process.wait(timeout=5)
            for member in members:
                # Un PID Windows peut subsister tant qu'un handle est ouvert, après sa sortie.
                try:
                    member.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
        finally:
            job.close()
            process.wait(timeout=5)
            process.stdout.close()

    def test_job_memory_cap_is_effective(self):
        code = ("import sys; sys.stdin.readline()\ntry:\n x=bytearray(128*1024**2)\n"
                " print('NOT_BOUND',flush=True)\nexcept MemoryError:\n"
                " print('MEMORY_BOUND',flush=True)\n")
        job, process = self.launch(code, 48)
        try:
            self.assertEqual(process.stdout.readline().strip(), "MEMORY_BOUND")
            process.wait(timeout=5)
        finally:
            job.close()
            process.wait(timeout=5)
            process.stdout.close()

    def test_job_explicit_stop_is_effective(self):
        code = "import sys,time; sys.stdin.readline(); print('READY',flush=True); time.sleep(20)"
        job, process = self.launch(code, 64)
        try:
            self.assertEqual(process.stdout.readline().strip(), "READY")
            job.stop()
            process.wait(timeout=5)
            self.assertNotEqual(process.returncode, 0)
        finally:
            job.close()
            process.wait(timeout=5)
            process.stdout.close()


if __name__ == "__main__":
    unittest.main()
