"""Sessions locales et limitation PostgreSQL partagée entre processus."""

import math
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.database import make_engine, session_factory
from backend.app.models import AuthSession, AuthThrottle, User
from backend.app.security import token_digest

bearer = HTTPBearer(auto_error=False)
SESSION_DURATION = timedelta(hours=8)
THROTTLE_WINDOW = timedelta(minutes=15)


def get_db(request: Request):
    """Ouvre une transaction par requête ; aucun détail de pilote dans les logs HTTP."""
    try:
        factory = getattr(request.app.state, "db_factory", None)
        if factory is None:
            with request.app.state.db_lock:
                factory = getattr(request.app.state, "db_factory", None)
                if factory is None:
                    # Initialisation différée : santé fonctionne sans PostgreSQL.
                    engine = make_engine()
                    request.app.state.db_engine = engine
                    factory = session_factory(engine)
                    request.app.state.db_factory = factory
        with factory() as db:
            yield db
    except (SQLAlchemyError, ValueError):
        raise HTTPException(503, "Base indisponible") from None


Database = Annotated[Session, Depends(get_db)]


def unauthorized() -> HTTPException:
    """Erreur identique pour compte absent, mauvais secret ou session invalide."""
    return HTTPException(401, "Authentification requise", headers={"WWW-Authenticate": "Bearer"})


def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    """Refuse un jeton manquant avant toute ouverture de connexion."""
    if credentials is None or len(credentials.credentials) != 43:
        raise unauthorized()
    return credentials.credentials


def current_session(
    token: Annotated[str, Depends(require_token)], db: Database,
) -> AuthSession:
    """Authentifie uniquement un en-tête Bearer, jamais une URL ni un cookie."""
    session = find_session(db, token)
    if session is None:
        raise unauthorized()
    return session


def find_session(db: Session, token: str) -> AuthSession | None:
    """Résolution partagée, sans changer le transport Bearer des routes API."""
    if len(token) != 43:
        return None
    return db.scalar(select(AuthSession).where(
        AuthSession.token_hash == token_digest(token),
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > func.now(),
    ))


ActiveSession = Annotated[AuthSession, Depends(current_session)]


def current_user(session: ActiveSession, db: Database) -> User:
    """Résout le propriétaire côté serveur uniquement."""
    user = db.get(User, session.user_id)
    if user is None:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def throttle(db: Session, request: Request, email: str, action: str) -> None:
    """Compte les tentatives avant Argon2 ; fenêtres fixes partagées via PostgreSQL.

    Cinq tentatives par compte et trente par IP en quinze minutes, inscription
    et connexion séparées. Les succès comptent également. Pas de confiance dans
    X-Forwarded-For ; déploiement strictement local. Les clés sont pseudonymisées.
    """
    now = db.scalar(select(func.clock_timestamp()))
    ip = request.client.host if request.client else "unknown"
    buckets = sorted([
        (token_digest(f"{action}:account:{email}"), 5),
        (token_digest(f"{action}:ip:{ip}"), 30),
    ])
    retry = 0
    for key, limit in buckets:
        # Verrou transactionnel, ordre stable : évite une course entre workers.
        lock = int.from_bytes(bytes.fromhex(key[:16]), "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        bucket = db.get(AuthThrottle, key)
        if bucket is None:
            bucket = AuthThrottle(key=key, window_start=now, attempts=0)
            db.add(bucket)
        elif now >= bucket.window_start + THROTTLE_WINDOW:
            bucket.window_start, bucket.attempts = now, 0
        if bucket.attempts >= limit:
            retry = max(retry, math.ceil(
                (bucket.window_start + THROTTLE_WINDOW - now).total_seconds()
            ))
        else:
            bucket.attempts += 1
    db.commit()  # les échecs suivants ne doivent pas annuler le compteur
    if retry:
        raise HTTPException(429, "Trop de tentatives", headers={"Retry-After": str(max(1, retry))})
