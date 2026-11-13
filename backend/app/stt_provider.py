"""Adaptateur STT local : aucune importation IA ni téléchargement au démarrage API."""

import ctypes
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.app.offline import OFFLINE_FLAGS, inference_environment


class STTError(Exception):
    """Code stable uniquement ; jamais de contenu fournisseur ou de chemin privé."""


def available_memory_mb() -> int:
    """Mémoire physique disponible ; échec fermé si la mesure est indisponible."""
    if sys.platform == "win32":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total", "available", "page_total", "page_available", "virtual_total",
                    "virtual_available", "extended",
                )
            ]
        state = Memory()
        state.length = ctypes.sizeof(state)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            raise STTError("memory_unknown")
        return state.available // 1024**2
    try:
        lines = Path("/proc/meminfo").read_text().splitlines()
        available = next(line.split()[1] for line in lines if line.startswith("MemAvailable:"))
        return int(available) // 1024
    except (OSError, StopIteration, ValueError):
        raise STTError("memory_unknown") from None


def require_memory(minimum: int) -> None:
    """Ne force jamais le chargement lorsque la mémoire mesurée est insuffisante."""
    if available_memory_mb() < minimum:
        raise STTError("insufficient_memory")


@dataclass(frozen=True)
class STTConfig:
    """Paramètres non secrets ; moteur remplaçable via le contrat Provider."""

    engine: str
    model_path: Path
    timeout: int = 600

    @classmethod
    def from_environment(cls):
        base = Path(os.getenv("LOCALAPPDATA", str(Path.home() / ".local/share")))
        path = Path(os.getenv("STT_MODEL_PATH", str(base / "Synthetiseur/models/whisper-small")))
        engine = os.getenv("STT_ENGINE", "faster-whisper")
        try:
            timeout = int(os.getenv("STT_TIMEOUT_SECONDS", "600"))
            if engine != "faster-whisper" or not path.is_absolute() or not 30 <= timeout <= 1800:
                raise ValueError
        except ValueError:
            raise STTError("configuration") from None
        return cls(engine, path, timeout)


class Provider(Protocol):
    """Contrat pour un moteur futur ; le faux fournisseur reste réservé aux tests."""

    timeout: int

    def transcribe(self, audio: bytes) -> str: ...


class LocalWhisper:
    """Sous-processus borné et tué au timeout ; audio privé uniquement via stdin."""

    def __init__(self, config: STTConfig):
        self.config, self.timeout = config, config.timeout

    def transcribe(self, audio: bytes) -> str:
        require_memory(3072)
        if not self.config.model_path.is_dir():
            raise STTError("model_unavailable")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "backend.app.stt_provider", str(self.config.model_path)],
                input=audio, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=inference_environment(),
                timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise STTError("timeout") from None
        except OSError:
            raise STTError("provider_unavailable") from None
        if result.returncode != 0 or len(result.stdout) > 256 * 1024:
            raise STTError("provider_failed")
        try:
            output = json.loads(result.stdout)
            if output.get("error"):
                raise STTError(output["error"] if output["error"] in {
                    "insufficient_memory", "memory_unknown", "invalid_text",
                } else "provider_failed")
            return output["text"]
        except (ValueError, KeyError, TypeError):
            raise STTError("provider_failed") from None


def main():
    """Entrée privée du décodeur : français, CPU INT8, fichiers locaux exclusivement."""
    os.environ.update(OFFLINE_FLAGS)
    from backend.app.text_rules import normalize_text
    try:
        require_memory(3072)
        from faster_whisper import WhisperModel

        from backend.app.stt_audio import decode_private_wav
        model = WhisperModel(sys.argv[1], device="cpu", compute_type="int8", cpu_threads=4,
                             num_workers=1, local_files_only=True)
        audio = sys.stdin.buffer.read(15 * 1024**2 + 1)
        if not audio or len(audio) > 15 * 1024**2:
            raise STTError("provider_failed")
        samples = decode_private_wav(audio)
        segments, _ = model.transcribe(samples, language="fr", beam_size=5,
                                       vad_filter=False, condition_on_previous_text=False)
        pieces, size = [], 0
        for segment in segments:
            size += len(segment.text)
            if size > 20000:
                raise STTError("invalid_text")
            pieces.append(segment.text)
        print(json.dumps({"text": normalize_text("".join(pieces))}, ensure_ascii=True))
    except STTError as exc:
        print(json.dumps({"error": str(exc)}))
    except Exception:
        print(json.dumps({"error": "provider_failed"}))


if __name__ == "__main__":
    main()
