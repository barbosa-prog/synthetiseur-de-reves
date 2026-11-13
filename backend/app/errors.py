"""Gestion centralisée des erreurs, sans renvoi du contenu des requêtes."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.app.schemas import ErrorDetail, ErrorResponse

HTTP_ERRORS = {
    400: ("bad_request", "Requête incorrecte."),
    401: ("unauthorized", "Authentification requise."),
    403: ("forbidden", "Accès refusé."),
    404: ("not_found", "Ressource introuvable."),
    405: ("method_not_allowed", "Méthode HTTP non autorisée."),
    408: ("request_timeout", "Réception interrompue ou délai dépassé."),
    409: ("registration_conflict", "Inscription impossible avec cet e-mail."),
    413: ("payload_too_large", "Requête trop volumineuse."),
    415: ("unsupported_media_type", "Format non accepté."),
    422: ("validation_error", "Données de requête invalides."),
    429: ("rate_limited", "Trop de requêtes."),
    503: ("service_unavailable", "Service temporairement indisponible."),
}


def error_response(status: int, code: str, message: str,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    """Construit une réponse JSON conforme au schéma public.

    Args:
        status: Statut HTTP de la réponse.
        code: Code stable de l'erreur.
        message: Message public sans données privées.
        headers: En-têtes HTTP à préserver, notamment Allow.

    Returns:
        Réponse JSON structurée.
    """
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    """Enregistre les gestionnaires d'erreurs sur une application.

    Args:
        app: Application à configurer.
    """

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code, message = HTTP_ERRORS.get(
            exc.status_code, ("http_error", "La requête n'a pas pu aboutir.")
        )
        # Ne pas exposer exc.detail : il peut contenir des données privées.
        return error_response(exc.status_code, code, message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(422, *HTTP_ERRORS[422])

    @app.exception_handler(Exception)
    async def handle_internal_error(request: Request, exc: Exception) -> JSONResponse:
        return error_response(500, "internal_error", "Une erreur interne est survenue.")
