"""P10 explicite ; inventaire par défaut, aucune configuration personnelle implicite."""

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.database import make_engine, session_factory  # noqa: E402
from backend.app.services.dream_purge import DreamPurgeService  # noqa: E402
from backend.app.services.media import MediaService  # noqa: E402
from backend.app.storage.local import LocalPrivateStorage  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Purge explicite des seuls rêves supprimés.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    engine = None
    try:
        # Vérifier AVANT tout chargement de .env ou ouverture d'une base.
        if (not os.getenv("DATABASE_URL") or not os.getenv("PRIVATE_MEDIA_ROOT")
                or not 1 <= args.limit <= 100):
            raise ValueError
        url = make_url(os.environ["DATABASE_URL"])
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError
        if args.apply and args.confirm_database != url.database:
            raise ValueError
        engine = make_engine(url)
        service = DreamPurgeService(MediaService(
            LocalPrivateStorage.from_environment(), session_factory(engine),
        ))
        report = service.run(apply=args.apply, limit=args.limit)
        print(json.dumps({"mode": "apply" if args.apply else "inventory", **report}))
        return 2 if report["blocked"] else 0
    except KeyboardInterrupt:
        print("Maintenance interrompue ; reprise explicite nécessaire.")
        return 130
    except Exception:
        print("Maintenance refusée ou indisponible ; aucun détail privé affiché.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
