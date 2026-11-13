"""Consommateurs fictifs : une contention NOWAIT n'est pas une réservation."""

import time


def wait_for_work(operation, *, timeout=5):
    """Réessaie seulement l'absence de travail, sans rejouer un job exécuté."""
    deadline = time.monotonic() + timeout
    while True:
        result = operation()
        if result:
            return result
        assert time.monotonic() < deadline, "Aucun job réservé par le worker fictif"
        time.sleep(0.05)
