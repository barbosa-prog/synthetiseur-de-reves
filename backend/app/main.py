"""Point d'entrée : python -m uvicorn backend.app.main:app."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api import router
from backend.app.audio_routes import router as audio_router
from backend.app.auth_routes import router as auth_router
from backend.app.dream_routes import router as dream_router
from backend.app.errors import register_error_handlers
from backend.app.image_routes import router as image_router
from backend.app.media_routes import router as media_router
from backend.app.schemas import ErrorResponse
from backend.app.stt_routes import router as stt_router
from backend.app.transcript_routes import router as transcript_router
from backend.app.web.routes import WebLoginRequired, web_login_required
from backend.app.web.routes import router as web_router


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
        Application API et interface web locale.
    """
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    origin = os.getenv("WEB_ORIGIN", "https://localhost:8443").rstrip("/")
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.netloc or parts.path or parts.query or parts.fragment:
        raise ValueError("WEB_ORIGIN doit être une origine HTTPS sans chemin.")
    if parts.username or parts.password:
        raise ValueError("WEB_ORIGIN ne doit pas contenir d'identifiants.")
    application = FastAPI(
        title="Synthétiseur de rêves — API",
        version="0.1.0",
        description=(
            "Backend local pédagogique : API, sessions, interface web et médias privés. "
            "Capture audio privée et transcription locale via worker séparé."
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
    application.state.web_origin = origin
    application.include_router(router)
    application.include_router(auth_router)
    application.include_router(dream_router)
    application.include_router(web_router)
    application.include_router(media_router)
    application.include_router(audio_router)
    application.include_router(transcript_router)
    application.include_router(stt_router)
    application.include_router(image_router)
    application.add_exception_handler(WebLoginRequired, web_login_required)
    application.mount("/static", StaticFiles(directory=Path(__file__).parent / "web/static"),
                      name="static")

    @application.middleware("http")
    async def private_responses(request, call_next):
        is_web = request.url.path.startswith(("/web/media/", "/reves/")) or request.url.path in {
            "/", "/connexion", "/inscription", "/accueil", "/deconnexion", "/web/session",
            "/nouveau-reve", "/web/audio",
        }
        if is_web and (
            request.url.scheme != "https" or request.headers.get("host") != parts.netloc
        ):
            return PlainTextResponse("Utilisez l’origine HTTPS configurée pour l’interface.",
                                     status_code=400, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        if is_web or request.url.path.startswith((
            "/api/v1/auth/", "/api/v1/dreams/", "/api/v1/media/", "/api/v1/transcriptions/",
        )):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        if (is_web and not request.url.path.startswith("/web/media/")) or (
            request.url.path.startswith("/static/")
        ):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                "connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            # no-referrer peut rendre Origin « null » sur un formulaire POST.
            # same-origin préserve le contrôle CSRF sans transmettre de référence externe.
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Permissions-Policy"] = "microphone=(self), camera=()"
        return response

    return application


app = create_app()
