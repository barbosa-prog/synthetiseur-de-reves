"""Point d'entrée : python -m uvicorn backend.app.main:app."""

from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI

from backend.app.api import router
from backend.app.auth_routes import router as auth_router
from backend.app.dream_routes import router as dream_router
from backend.app.errors import register_error_handlers
from backend.app.schemas import ErrorResponse


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Libère le pool de connexions au terme de la vie du serveur."""
    yield
    engine = getattr(application.state, "db_engine", None)
    if engine is not None:
        engine.dispose()


def create_app() -> FastAPI:
    """Construit une application indépendante pour le serveur et les tests.

    Returns:
        Application du ticket P01.
    """
    application = FastAPI(
        title="Synthétiseur de rêves — API",
        version="0.1.0",
        description=(
            "Backend local pédagogique P01–P03 : santé, PostgreSQL et sessions privées. "
            "Aucune intégration IA ni stockage physique de médias."
        ),
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        openapi_url="/api/v1/openapi.json",
        swagger_ui_oauth2_redirect_url="/api/v1/docs/oauth2-redirect",
        lifespan=lifespan,
        responses={
            404: {"model": ErrorResponse, "description": "Ressource introuvable."},
            405: {"model": ErrorResponse, "description": "Méthode non autorisée."},
            422: {"model": ErrorResponse, "description": "Données invalides."},
            500: {"model": ErrorResponse, "description": "Erreur interne sans détail privé."},
        },
    )
    register_error_handlers(application)
    application.state.db_lock = Lock()
    application.include_router(router)
    application.include_router(auth_router)
    application.include_router(dream_router)

    @application.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/api/v1/auth/", "/api/v1/dreams/")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    return application


app = create_app()
