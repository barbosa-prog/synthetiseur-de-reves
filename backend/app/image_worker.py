"""Noyau testable du futur worker image séparé ; aucune boucle ou connexion à l'import."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from backend.app.image_provider import ImageError, ImageProvider, ImageRequest, validate_result
from backend.app.latency import provider_latency


@dataclass(frozen=True)
class ImageTask:
    """Snapshot à persister dans un job image, jamais dans le récit P06."""

    job_id: UUID
    dream_id: UUID
    user_id: UUID
    request: ImageRequest


def prepare_image(task: ImageTask, provider: ImageProvider,
                  is_current: Callable[[ImageTask], bool]):
    """Calcule sans publier ; le futur publisher devra reverrouiller rêve et job.

    is_current vérifie propriétaire, rêve non supprimé, versions texte/description
    et bail courant. Son second contrôle n'est pas une transaction de publication.
    Aucun stockage n'a lieu ici : pas de résultat tardif visible entre deux verrous.
    """
    if not is_current(task):
        raise ImageError("text_conflict")
    try:
        with provider_latency("image"):
            generated = provider.generate(task.request)
        result = validate_result(generated, task.request)
    except ImageError:
        raise
    except Exception:
        raise ImageError("provider_failed") from None
    if not is_current(task):
        raise ImageError("text_conflict")
    return result


def main():
    """Worker Windows indépendant, explicitement lancé, aucun modèle dans FastAPI."""
    import argparse
    import os
    import time

    from backend.app.database import make_engine, session_factory
    from backend.app.image_provider import LocalStableDiffusion15, SD15Config
    from backend.app.image_runner import WatchedSD15Runner, gpu_slot, qualification_root
    from backend.app.services.image_execution import run_once
    from backend.app.storage.local import LocalPrivateStorage

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine = make_engine()
    try:
        sessions = session_factory(engine)
        config = SD15Config(Path(os.getenv("IMAGE_MODEL_PATH", str(qualification_root()/"model"))))
        provider = LocalStableDiffusion15(config, WatchedSD15Runner())
        storage = LocalPrivateStorage.from_environment()
        while True:
            try:
                with gpu_slot() as acquired:
                    worked = run_once(sessions, storage, provider) if acquired else False
                if args.once:
                    return 0
                if not worked:
                    time.sleep(2)
            except Exception:
                print("Worker image indisponible ; détails privés masqués.", flush=True)
                if args.once:
                    return 1
                time.sleep(5)
    except KeyboardInterrupt:
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
