"""Téléchargement explicite uniquement ; jamais importé par FastAPI ou pytest."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from backend.app.stt_provider import STTConfig, STTError, require_memory  # noqa: E402


def main():
    """Cache unique et reprise Hugging Face ; aucun audio transmis."""
    load_dotenv(ROOT / ".env", override=False)
    lock = None
    try:
        target = STTConfig.from_environment().model_path.resolve()
        if target.is_relative_to(ROOT) or any("onedrive" in part.lower() for part in target.parts):
            raise STTError("Le dossier du modèle doit être hors dépôt et hors OneDrive.")
        if (target / "download-complete.json").is_file():
            print("Modèle déjà téléchargé : aucune requête réseau.")
            return 0
        require_memory(3072)
        from huggingface_hub import HfApi, snapshot_download
        target.mkdir(parents=True, exist_ok=True)
        candidate = target / ".download-lock"
        descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        lock = candidate
        os.close(descriptor)
        repository = "Systran/faster-whisper-small"
        revision_file = target / "revision.json"
        if revision_file.exists():
            revision = json.loads(revision_file.read_text())["revision"]
        else:
            revision = HfApi().model_info(repository).sha
            revision_file.write_text(json.dumps({"revision": revision}), encoding="utf-8")
        snapshot_download(repository, revision=revision, local_dir=target, max_workers=1,
                          allow_patterns=["model.bin", "config.json", "tokenizer.json",
                                          "vocabulary.*", "preprocessor_config.json"])
        if not all((target / name).is_file() for name in (
            "model.bin", "config.json", "tokenizer.json",
        )):
            raise STTError("Téléchargement incomplet ; relancer explicitement pour reprendre.")
        (target / "download-complete.json").write_text(
            json.dumps({"repository": repository, "revision": revision}), encoding="utf-8",
        )
        print("Modèle local prêt. Aucun audio n'a été envoyé.")
        return 0
    except STTError as exc:
        print(f"Téléchargement arrêté : {exc}")
        return 1
    except FileExistsError:
        lock = None
        print("Téléchargement déjà réservé. Vérifier le processus avant toute reprise.")
        return 1
    except Exception:
        print("Téléchargement indisponible ; détails réseau et chemins masqués.")
        return 1
    finally:
        if lock is not None:
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
