"""Worker P08 explicitement activé, indépendant des workers P05/P07."""

import argparse
import os
import time

from sqlalchemy import func, select

from backend.app.emotion_config import TIMEOUT, enabled, parameters
from backend.app.emotion_provider import LocalMDeberta
from backend.app.emotion_runner import WatchedEmotionRunner, worker_slot


def heavy_jobs_running(sessions):
    from backend.app.models import Job

    with sessions() as db:
        return (
            db.scalar(
                select(Job.id)
                .where(
                    Job.kind.in_(["stt", "image"]),
                    Job.status == "running",
                    Job.lease_until > func.clock_timestamp(),
                )
                .limit(1)
            )
            is not None
        )


def work_once(sessions, provider, configuration):
    from backend.app.services.emotions import run_once

    if heavy_jobs_running(sessions):
        return False
    return run_once(sessions, provider, timeout=TIMEOUT, required_parameters=configuration)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    # Ne charge pas .env ni une connexion quand la variable n'est pas explicitement activée.
    if not enabled():
        print("Worker émotion désactivé. Activation explicite requise.", flush=True)
        return 0
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL explicite requise ; aucune connexion ouverte.", flush=True)
        return 1
    from backend.app.database import make_engine, session_factory

    with worker_slot() as acquired:
        if not acquired:
            print("Un worker émotion est déjà actif.", flush=True)
            return 2
        engine = make_engine()
        try:
            sessions = session_factory(engine)
            configuration = parameters()
            provider = LocalMDeberta(WatchedEmotionRunner(), configuration)
            while True:
                try:
                    worked = work_once(sessions, provider, configuration)
                except Exception:
                    print("Worker émotion indisponible ; reprise différée.", flush=True)
                    if args.once:
                        return 1
                    time.sleep(5)
                    continue
                if args.once:
                    return 0
                if not worked:
                    time.sleep(2)
        except KeyboardInterrupt:
            return 0
        except Exception:
            print("Worker émotion indisponible ; détails privés masqués.", flush=True)
            return 1
        finally:
            engine.dispose()


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        print("Configuration du worker indisponible ; détails privés masqués.", flush=True)
        code = 1
    raise SystemExit(code)
