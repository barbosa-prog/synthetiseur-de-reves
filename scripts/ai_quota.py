"""Configuration centrale explicite du quota, sans modèle ni chargement de .env."""

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.database import make_engine, session_factory  # noqa: E402
from backend.app.models import AIQuotaPolicy  # noqa: E402
from backend.app.services.ai_quota import configure  # noqa: E402
from backend.app.services.job_lifecycle import bounded  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    args = parser.parse_args()
    engine = None
    try:
        url = make_url(os.environ["DATABASE_URL"])
        if (url.drivername != "postgresql+psycopg" or not url.database
                or (args.limit is not None and not args.apply)
                or (args.apply and (args.confirm_database != url.database or args.limit is None))):
            raise ValueError
        engine = make_engine(url)
        with session_factory(engine)() as db:
            if not args.apply:
                db.execute(text("SET TRANSACTION READ ONLY"))
            bounded(db)
            if args.apply:
                configure(db, args.limit)
            policy = db.get(AIQuotaPolicy, 1)
            if policy is None:
                raise ValueError
            result = dict(execution_limit=policy.execution_limit, window_hours=24,
                          mode="apply" if args.apply else "inventory")
            db.commit()
        print(json.dumps(result))
        return 0
    except Exception:
        print("Quota indisponible ou commande refusee ; details prives masques.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
