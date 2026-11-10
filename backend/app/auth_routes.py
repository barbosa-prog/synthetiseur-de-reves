"""Inscription, connexion, session et révocation locale."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from backend.app.auth import (
    ActiveSession,
    CurrentUser,
    Database,
)
from backend.app.auth_schemas import Credentials, LoginResponse, SessionResponse, UserResponse
from backend.app.models import User
from backend.app.schemas import ErrorResponse
from backend.app.services.authentication import create_login, register_user

router = APIRouter(prefix="/api/v1/auth", tags=["Authentification"], responses={
    401: {"model": ErrorResponse, "description": "Authentification absente ou invalide."},
    409: {"model": ErrorResponse, "description": "Inscription impossible avec cet e-mail."},
    429: {"model": ErrorResponse, "description": "Limite atteinte ; consulter Retry-After."},
    503: {"model": ErrorResponse, "description": "Base indisponible."},
})


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: Credentials, request: Request, db: Database) -> User:
    """Inscription API P03, contrat inchangé."""
    return register_user(payload, request, db)


@router.post("/login", response_model=LoginResponse)
def login(payload: Credentials, request: Request, response: Response,
          db: Database) -> LoginResponse:
    """Connexion Bearer P03, contrat inchangé."""
    response.headers["Cache-Control"] = "no-store"
    return create_login(payload, request, db)


@router.get("/session", response_model=SessionResponse)
def session_info(session: ActiveSession, user: CurrentUser) -> SessionResponse:
    """Identité et échéance de la session actuelle ; pas de prolongation implicite."""
    return SessionResponse(user=UserResponse.model_validate(user), expires_at=session.expires_at)


@router.post("/logout", status_code=204)
def logout(session: ActiveSession, db: Database) -> Response:
    """Révoque uniquement la session présentée, immédiatement en base."""
    session.revoked_at = db.scalar(select(func.clock_timestamp()))
    db.commit()
    return Response(status_code=204)
