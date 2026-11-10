"""Inscription, connexion, session et révocation locale."""

from fastapi import HTTPException, Request
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.auth import (
    SESSION_DURATION,
    Database,
    throttle,
    unauthorized,
)
from backend.app.auth_schemas import Credentials, LoginResponse
from backend.app.models import AuthSession, User
from backend.app.security import hash_password, hasher, new_token, token_digest, verify_password


def register_user(payload: Credentials, request: Request, db: Database) -> User:
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


def create_login(payload: Credentials, request: Request,
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
    return LoginResponse(access_token=SecretStr(token), expires_at=expires)


