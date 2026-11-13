"""P11 explicite : inventaire par défaut, boucle facultative, aucune IA."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.database import make_engine, session_factory  # noqa: E402
from backend.app.job_rules import Policy  # noqa: E402
from backend.app.services.job_maintenance import maintain  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    engine = None
    try:
        if not os.getenv("DATABASE_URL"):
            raise ValueError
        url = make_url(os.environ["DATABASE_URL"])
        if (url.drivername != "postgresql+psycopg" or not url.database
                or (args.apply and args.confirm_database != url.database)):
            raise ValueError
        policy = Policy(queued_seconds=int(os.getenv("P11_QUEUE_TIMEOUT_SECONDS", "1800")),
                        recovery_interval_seconds=int(os.getenv("P11_MAINTENANCE_INTERVAL", "5")))
        engine = make_engine(url)
        sessions = session_factory(engine)
        while True:
            report = maintain(sessions, apply=args.apply, limit=args.limit, policy=policy)
            print(json.dumps({"mode": "apply" if args.apply else "inventory", **report}),
                  flush=True)
            if not args.watch:
                return 0
            time.sleep(policy.recovery_interval_seconds)
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("Maintenance indisponible ; aucun détail privé affiché.", flush=True)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
