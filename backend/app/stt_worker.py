"""Worker P05 indépendant : python -m backend.app.stt_worker [--once]."""

import argparse
import time

from backend.app.database import make_engine, session_factory
from backend.app.services.media import MediaService
from backend.app.services.stt_jobs import run_once
from backend.app.storage.local import LocalPrivateStorage
from backend.app.stt_provider import LocalWhisper, STTConfig


def main():
    """Traite les réservations persistantes sans journaliser contenu ni exception privée."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine = make_engine()  # Charge .env avant la configuration STT/stockage.
    try:
        sessions = session_factory(engine)
        service = MediaService(LocalPrivateStorage.from_environment(), sessions)
        provider = LocalWhisper(STTConfig.from_environment())
        while True:
            try:
                worked = run_once(sessions, service, provider)
            except Exception:
                print("Worker indisponible ; reprise différée, détails privés masqués.", flush=True)
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
        print("Configuration du worker indisponible ; vérifiez la documentation.", flush=True)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
