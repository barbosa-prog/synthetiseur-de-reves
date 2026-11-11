"""Essai local explicite sur un audio français fictif ; jamais exécuté par pytest."""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from backend.app.stt_provider import (  # noqa: E402
    LocalWhisper,
    STTConfig,
    STTError,
    available_memory_mb,
    require_memory,
)
from backend.app.text_rules import normalize_text  # noqa: E402


def main():
    """Mesure sans journaliser le récit ni télécharger de modèle."""
    parser = argparse.ArgumentParser(description="Utiliser uniquement un audio français fictif.")
    parser.add_argument("--audio", required=True, type=Path)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    try:
        print(f"RAM disponible : {available_memory_mb()} Mio ; seuil : 3072 Mio.")
        require_memory(3072)
        if not 1 <= args.audio.stat().st_size <= 15 * 1024**2:
            raise STTError("audio_invalid")
        start = time.monotonic()
        output = normalize_text(LocalWhisper(STTConfig.from_environment()).transcribe(
            args.audio.read_bytes(),
        ))
        print(f"Reconnaissance réelle terminée en {time.monotonic() - start:.2f} secondes ; "
              f"{len(output)} caractères. Aucun contenu journalisé.")
        print("Vérifier ensuite la fidélité du français dans l'éditeur P06 via le parcours web.")
        return 0
    except STTError as exc:
        print(f"Essai arrêté : {exc}")
        return 1
    except Exception:
        print("Essai indisponible ; chemins et détails privés masqués.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
