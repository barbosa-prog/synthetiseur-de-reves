"""Point d'entrée : python -m uvicorn backend.app.main:app."""

from fastapi import FastAPI

from backend.app.api import router
from backend.app.errors import register_error_handlers
from backend.app.schemas import ErrorResponse


def create_app() -> FastAPI:
    """Construit une application indépendante pour le serveur et les tests.

    Returns:
        Application du ticket P01.
    """
    application = FastAPI(
        title="Synthétiseur de rêves — API",
        version="0.1.0",
        description=(
            "Backend local pédagogique. P01 : contrôle de santé et contrat d'erreurs. "
            "Aucune base, authentification ou intégration IA n'est encore active."
        ),
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        openapi_url="/api/v1/openapi.json",
        swagger_ui_oauth2_redirect_url="/api/v1/docs/oauth2-redirect",
        responses={
            404: {"model": ErrorResponse, "description": "Ressource introuvable."},
            405: {"model": ErrorResponse, "description": "Méthode non autorisée."},
            422: {"model": ErrorResponse, "description": "Données invalides."},
            500: {"model": ErrorResponse, "description": "Erreur interne sans détail privé."},
        },
    )
    register_error_handlers(application)
    application.include_router(router)
    return application


app = create_app()
