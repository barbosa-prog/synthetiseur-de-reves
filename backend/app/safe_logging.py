"""Journaux par liste blanche ; aucun message tiers ou traceback n'est conservé."""

import logging

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
            if record.name == "dreams.safe" and type(message) is str and message in EVENTS:
                event = message
            elif record.name == "uvicorn.error" and type(message) is str:
                event = SERVER_EVENTS.get(message, "diagnostic_redacted")
            else:
                event = "diagnostic_redacted"
            record.name, record.msg, record.args = "dreams.safe", event, ()
            record.exc_info = record.exc_text = record.stack_info = None
            record.pathname = record.filename = record.module = record.funcName = ""
            record.lineno = 0
            return record
        private_record.dreams_private = True
        logging.setLogRecordFactory(private_record)
    # Uvicorn AccessFormatter attend des arguments contenant URL/client : remplacer
    # ce format évite également une erreur de formatage après leur suppression.
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s pid=%(process)d")
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
