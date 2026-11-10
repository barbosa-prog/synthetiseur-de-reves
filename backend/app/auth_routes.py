"""Inscription, connexion, session et révocation locale."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.auth import (
    SESSION_DURATION,
    ActiveSession,
    CurrentUser,
    Database,
    throttle,
    unauthorized,
)
from backend.app.auth_schemas import Credentials, LoginResponse, SessionResponse, UserResponse
from backend.app.models import AuthSession, User
from backend.app.schemas import ErrorResponse
from backend.app.security import hash_password, hasher, new_token, token_digest, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["Authentification"], responses={
    401: {"model": ErrorResponse, "description": "Authentification absente ou invalide."},
    409: {"model": ErrorResponse, "description": "Inscription impossible avec cet e-mail."},
    429: {"model": ErrorResponse, "description": "Limite atteinte ; consulter Retry-After."},
    503: {"model": ErrorResponse, "description": "Base indisponible."},
})


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: Credentials, request: Request, db: Database) -> User:
    """Crée un compte sans le connecter ; ne revendique pas la possession de l'e-mail."""
    throttle(db, request, payload.email, "register")
    if db.scalar(select(User.id).where(func.lower(User.email) == payload.email)):
        raise HTTPException(409, "Inscription impossible")
    user = User(
        email=payload.email, password_hash=hash_password(payload.password.get_secret_value()),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # L'index unique couvre aussi deux inscriptions simultanées.
        raise HTTPException(409, "Inscription impossible") from None
    return user


@router.post("/login", response_model=LoginResponse)
def login(payload: Credentials, request: Request, response: Response,
          db: Database) -> LoginResponse:
    """Retourne une session de huit heures, sans cookie ni jeton en URL."""
    throttle(db, request, payload.email, "login")
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    stored = user.password_hash if user else None
    if not verify_password(stored, payload.password.get_secret_value()):
        raise unauthorized()
    if hasher.check_needs_rehash(stored):
        user.password_hash = hash_password(payload.password.get_secret_value())
    token = new_token()
    now = db.scalar(select(func.clock_timestamp()))
    expires = now + SESSION_DURATION
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token),
                       created_at=now, expires_at=expires))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(access_token=SecretStr(token), expires_at=expires)


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
