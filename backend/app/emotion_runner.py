"""Pont CPU isolé ; ni torch ni psutil dans l'environnement de production."""

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

from backend.app.emotion_config import local_root, parameters
from backend.app.emotion_provider import EmotionError
from backend.app.offline import inference_environment


@contextmanager
def worker_slot():
    import msvcrt

    root = local_root() / "p08-worker"
    root.mkdir(parents=True, exist_ok=True)
    with (root / "worker.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class WatchedEmotionRunner:
    def __init__(self):
        self.last_metrics = {}

    def run(self, request, configuration):
        self.last_metrics = {}
        expected = {**parameters(), "inference_enabled": True}
        if configuration != expected:
            raise EmotionError("configuration")
        python = local_root() / "p08/.venv/Scripts/python.exe"
        bridge = Path(__file__).resolve().parents[2] / "scripts/emotion_cpu_bridge.py"
        if not python.is_file() or not bridge.is_file():
            raise EmotionError("model_unavailable")
        process = None
        try:
            process = subprocess.Popen(
                [str(python), str(bridge)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=inference_environment(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = dict(request=request.model_dump(mode="json"), configuration=configuration)
            process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            process.stdin.flush()
            # Stdin reste ouvert : EOF indique au bridge la disparition du parent.
            process.wait(timeout=configuration["timeout_seconds"] + 30)
            raw = process.stdout.read(16385)
            self.last_metrics = {"bridge_exit_code": process.returncode}
            if len(raw) > 16384:
                raise EmotionError("provider_failed")
            response = json.loads(raw)
            self.last_metrics.update({**response.get("metrics", {}), **response.get("timings", {})})
            if process.returncode:
                raise EmotionError("provider_failed")
            if response.get("error"):
                raise EmotionError(response["error"])
            return response["result"]
        except subprocess.TimeoutExpired:
            raise EmotionError("timeout") from None
        except EmotionError:
            raise
        except Exception:
            raise EmotionError("provider_failed") from None
        finally:
            if process:
                if process.stdin:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()
