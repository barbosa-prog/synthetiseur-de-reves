"""Journaux par liste blanche ; aucun message tiers ou traceback n'est conservé."""

import json
import logging
import math

LATENCY_OUTCOMES = {
    "queue": {"admitted"},
    "provider": {"returned", "raised", "interrupted"},
    "worker": {"handled", "idle", "raised", "interrupted"},
}


def latency_payload(value):
    """Liste blanche fermée, sans extra, identifiant ni texte libre."""
    if type(value) is not dict or set(value) != {
        "event", "kind", "phase", "duration_ms", "outcome",
    }:
        return None
    kind, phase, outcome, duration = (value[k] for k in (
        "kind", "phase", "outcome", "duration_ms"))
    if (type(value["event"]) is not str or value["event"] != "job_latency"
            or type(kind) is not str or kind not in {"stt", "image"}
            or type(phase) is not str or phase not in LATENCY_OUTCOMES
            or type(outcome) is not str or outcome not in LATENCY_OUTCOMES[phase]
            or type(duration) not in {int, float} or not 0 <= duration <= 86_400_000
            or not math.isfinite(duration)):
        return None
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        if record.name == "dreams.latency":
            return record.getMessage()
        return super().format(record)

EVENTS = frozenset({"request_rejected", "request_failed", "response_interrupted"})
SERVER_EVENTS = {
    "Started server process [%d]": "server_started",
    "Application startup complete.": "application_ready",
    "Application shutdown complete.": "application_stopped",
    "Shutting down": "server_stopping",
}


def install_safe_logging():
    """Protège les loggers Python du processus, y compris SQL et Uvicorn.

    Les sorties stdout privées des moteurs ne passent pas par logging et restent
    des canaux IPC capturés. Ne jamais ajouter un dump de LogRecord en production.
    """
    logging.captureWarnings(True)
    previous = logging.getLogRecordFactory()
    if not getattr(previous, "dreams_private", False):
        def private_record(*args, **kwargs):
            record = previous(*args, **kwargs)
            message = record.msg
            payload = latency_payload(message) if record.name == "dreams.latency" else None
            if payload is not None:
                event = payload
            elif record.name == "dreams.safe" and type(message) is str and message in EVENTS:
                event = message
            elif record.name == "uvicorn.error" and type(message) is str:
                event = SERVER_EVENTS.get(message, "diagnostic_redacted")
            else:
                event = "diagnostic_redacted"
            record.name = "dreams.latency" if payload is not None else "dreams.safe"
            record.msg, record.args = event, ()
            record.exc_info = record.exc_text = record.stack_info = None
            record.pathname = record.filename = record.module = record.funcName = ""
            record.lineno = 0
            return record
        private_record.dreams_private = True
        logging.setLogRecordFactory(private_record)
    # Uvicorn AccessFormatter attend des arguments contenant URL/client : remplacer
    # ce format évite également une erreur de formatage après leur suppression.
    formatter = SafeFormatter("%(asctime)s %(levelname)s %(message)s pid=%(process)d")
    loggers = [logging.getLogger(), *[
        logger for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    ]]
    for logger in loggers:
        for handler in logger.handlers:
            handler.setFormatter(formatter)


def event(code):
    if code not in EVENTS:
        raise ValueError("Evenement non autorise")
    logging.getLogger("dreams.safe").warning(code)
