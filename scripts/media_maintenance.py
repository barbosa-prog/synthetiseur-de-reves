"""Maintenance privée P19 : simulation par défaut, aucun chemin ou contenu affiché."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.database import make_engine, session_factory  # noqa: E402
from backend.app.services.media import MediaService  # noqa: E402
from backend.app.storage.local import LocalPrivateStorage, StorageError  # noqa: E402


def main() -> int:
    """Ne purge pas les rêves ; reprend les purges explicitement demandées et les orphelins."""
    parser = argparse.ArgumentParser(description="Inventaire privé sans affichage des clés.")
    parser.add_argument("--apply", action="store_true", help="Appliquer les nettoyages admissibles")
    args = parser.parse_args()
    engine = None
    try:
        engine = make_engine()  # charge la configuration .env privée
        service = MediaService(LocalPrivateStorage.from_environment(), session_factory(engine))
        report = service.reconcile(apply=args.apply)
        print("Mode :", "application" if args.apply else "simulation")
        for label, count in report.items():
            print(f"{label}: {count}")
        return 0
    except (StorageError, ValueError):
        print("Maintenance indisponible ; vérifier la configuration privée et les permissions.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
