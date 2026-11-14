"""Durées uniquement : aucun argument, résultat métier ou identifiant journalisé."""

import logging
from contextlib import contextmanager
from functools import wraps
from time import perf_counter

from backend.app.safe_logging import latency_payload


def emit(kind, phase, seconds, outcome):
    payload = dict(event="job_latency", kind=kind, phase=phase,
                   duration_ms=round(seconds * 1000, 6), outcome=outcome)
    if latency_payload(payload) is None:
        raise ValueError("Mesure de latence invalide")
    try:
        # Niveau visible même sans configuration INFO des workers ; message JSON borné.
        logging.getLogger("dreams.latency").warning(payload)
    except Exception:
        # Une destination de logs indisponible ne doit pas casser une réservation validée.
        return False
    return True


@contextmanager
def provider_latency(kind):
    start, outcome = perf_counter(), "returned"
    try:
        yield
    except KeyboardInterrupt:
        outcome = "interrupted"
        raise
    except BaseException:
        outcome = "raised"
        raise
    finally:
        emit(kind, "provider", perf_counter() - start, outcome)


def worker_latency(kind):
    def decorate(operation):
        @wraps(operation)
        def measured(*args, **kwargs):
            start, outcome = perf_counter(), "raised"
            try:
                result = operation(*args, **kwargs)
                outcome = "handled" if result else "idle"
                return result
            except KeyboardInterrupt:
                outcome = "interrupted"
                raise
            finally:
                if outcome != "idle":
                    emit(kind, "worker", perf_counter() - start, outcome)
        return measured
    return decorate
