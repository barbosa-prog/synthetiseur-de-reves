"""Pont explicite vers le Python GPU isolé ; jamais importé par FastAPI."""

import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from backend.app.image_provider import ImageError


def qualification_root():
    return Path(os.environ["LOCALAPPDATA"]) / "SynthetiseurDeReves/p07-qualification"


@contextmanager
def gpu_slot():
    """Verrou OS interprocessus, libéré même après crash ; fichier non supprimé."""
    import msvcrt
    root = qualification_root()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "image-gpu.lock").open("a+b") as handle:
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


class WatchedSD15Runner:
    """Surveillant externe dans le venv P07 ; prompt par fichier privé éphémère.

    Le pont reste vivant si le worker applicatif s'arrête : il tue le seul job
    GPU, attend sa sortie puis efface le dossier éphémère.
    """

    def run(self, config, request):
        root = qualification_root()
        python = root / "venv/Scripts/python.exe"
        bridge = Path(__file__).resolve().parents[2] / "qualification/p07/image_job_bridge.py"
        if not python.is_file() or not bridge.is_file():
            raise ImageError("worker_unavailable")
        root.mkdir(parents=True, exist_ok=True)
        # Le bridge détient le nettoyage, y compris si le parent est interrompu.
        directory = Path(tempfile.mkdtemp(prefix="private-image-", dir=root))
        payload = {"description": request.description, "seed": request.seed,
                   "model_path": str(config.model_path)}
        (directory / "request.json").write_text(json.dumps(payload), encoding="utf-8")
        process = None
        try:
            process = subprocess.Popen(
                [str(python), str(bridge), str(directory)], stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Un thread du bridge écoute EOF : crash/arrêt parent => arrêt du job GPU.
            process.wait(timeout=config.timeout_seconds+45)
            status_path = directory / "status.json"
            if not status_path.is_file() or status_path.stat().st_size > 1024:
                raise ImageError("provider_failed")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("error"):
                raise ImageError(status["error"])
            if status.get("blocked") is True:
                return b"", True
            image = directory / "output.png"
            if not image.is_file() or image.stat().st_size > 8*1024**2:
                raise ImageError("invalid_image")
            return image.read_bytes(), status.get("blocked")
        except subprocess.TimeoutExpired:
            raise ImageError("timeout") from None
        finally:
            receipt = os.getenv("IMAGE_RECEIPT_PATH")
            if receipt:
                try:
                    metrics = list(directory.glob("*/metrics.json"))
                    if metrics:
                        Path(receipt).write_text(metrics[0].read_text(encoding="utf-8"),
                                                 encoding="utf-8")
                except OSError:
                    pass  # Une télémétrie absente ne vaut jamais validation de recette.
            if process is not None and process.stdin:
                process.stdin.close()
            if process is not None and process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # Ne pas tuer le surveillant : son timer indépendant reste garant du GPU.
                    pass
            if process is None or process.poll() is not None:
                import shutil
                shutil.rmtree(directory, ignore_errors=True)
