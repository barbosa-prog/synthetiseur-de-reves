"""Pont isolé et arrêt simulés ; aucun lancement du Python GPU."""

import io
import json
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app import image_runner
from backend.app.image_provider import ImageError, ImageRequest, SD15Config


@pytest.mark.parametrize("error", [None, "timeout", "insufficient_memory", "worker_stopped"])
def test_runner_private_channel_and_cleanup(tmp_path, monkeypatch, error):
    root = tmp_path / "runtime"
    python = root / "venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(image_runner, "qualification_root", lambda: root)
    calls = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.stdin = io.BytesIO()
            directory = Path(command[-1])
            payload = json.loads((directory / "request.json").read_text())
            assert payload["description"] == "Private fictitious forest"
            assert "Private fictitious" not in str(command)
            status = {"error": error} if error else {"blocked": False}
            (directory / "status.json").write_text(json.dumps(status))
            (directory / "output.png").write_bytes(b"fake-bytes-validated-by-adapter")
            calls.append(self)

        def wait(self, timeout):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(image_runner.subprocess, "Popen", FakeProcess)
    request = ImageRequest(description="Private fictitious forest", text_version=1,
                           description_version=1)
    runner = image_runner.WatchedSD15Runner()
    if error:
        with pytest.raises(ImageError, match=error):
            runner.run(SD15Config(tmp_path), request)
    else:
        assert runner.run(SD15Config(tmp_path), request)[1] is False
    assert len(calls) == 1 and calls[0].stdin.closed
    assert not list(root.glob("private-image-*"))


def test_worker_interrupt_closes_bridge_pipe(tmp_path, monkeypatch):
    root = tmp_path
    python = root / "venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(image_runner, "qualification_root", lambda: root)
    pipe = io.BytesIO()

    class Process:
        stdin = pipe
        attempts = 0

        def wait(self, timeout):
            self.attempts += 1
            if self.attempts == 1:
                raise KeyboardInterrupt
            return 0

        def poll(self):
            return None if self.attempts == 1 else 0

    monkeypatch.setattr(image_runner.subprocess, "Popen", lambda *a, **kw: Process())
    with pytest.raises(KeyboardInterrupt):
        image_runner.WatchedSD15Runner().run(SD15Config(tmp_path), ImageRequest(
            description="Synthetic", text_version=1, description_version=1))
    assert pipe.closed
    assert not list(root.glob("private-image-*"))


def test_gpu_slot_excludes_second_worker(tmp_path, monkeypatch):
    pytest.importorskip("msvcrt")
    monkeypatch.setattr(image_runner, "qualification_root", lambda: tmp_path)
    with image_runner.gpu_slot() as first:
        assert first
        with image_runner.gpu_slot() as second:
            assert not second
    with image_runner.gpu_slot() as released:
        assert released


def test_external_supervisor_stops_owned_child_on_parent_eof(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/"qualification/p07"))
    import cpu_mini
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace())
    stopped = threading.Event()
    stopped.set()
    processes, stops = [], []

    class Child:
        def __init__(self, *args, **kwargs):
            self.stdin, self.returncode = io.BytesIO(), None
            processes.append(self)

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            return self.returncode

    class Job:
        def __init__(self, cap):
            pass

        def attach(self, process):
            pass

        def resume(self, process):
            pass

        def stop(self):
            stops.append(True)
            processes[0].returncode = 125

        def memory_peaks(self):
            return {}

        def member_pids(self):
            return []

        def close(self):
            pass

    sample = {"ram_available_mib": 5000, "commit_headroom_mib": 10000, "commit_percent": 50}
    monkeypatch.setattr(cpu_mini, "require_environment", lambda: None)
    monkeypatch.setattr(cpu_mini, "paths", lambda: (tmp_path,))
    monkeypatch.setattr(cpu_mini, "exclusive", nullcontext)
    monkeypatch.setattr(cpu_mini, "memory_reader", lambda: lambda: dict(sample))
    monkeypatch.setattr(cpu_mini.time, "sleep", lambda _: None)
    monkeypatch.setattr(cpu_mini, "ChildJob", Job)
    monkeypatch.setattr(cpu_mini.subprocess, "Popen", Child)
    assert cpu_mini.supervise(cancel_event=stopped) == 1
    assert stops == [True] and processes[0].returncode == 125
