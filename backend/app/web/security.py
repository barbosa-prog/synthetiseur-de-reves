"""Cookies hôte HTTPS et CSRF lié à la session, sans jeton d'authentification en HTML."""

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Response

SESSION_COOKIE = "__Host-dream_session"
CSRF_COOKIE = "__Host-dream_csrf"


def set_private_cookie(response: Response, name: str, value: str) -> None:
    """Cookie de session sans Domain, Expires ou Max-Age ; jamais accessible à JS."""
    response.set_cookie(name, value, path="/", secure=True, httponly=True, samesite="lax")


def csrf_proof(secret: str, session_token: str = "") -> str:
    """Preuve HMAC : clé aléatoire HttpOnly, message lié à la session ou au pré-login."""
    return hmac.new(secret.encode(), (session_token or "anonymous").encode(),
                    hashlib.sha256).hexdigest()


def check_csrf(request: Request, submitted: str) -> None:
    """Vérifie origine stricte, Fetch Metadata et preuve de formulaire en temps constant."""
    origin = request.headers.get("origin")
    if origin != request.app.state.web_origin:
        raise HTTPException(403, "Origine refusée")
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        raise HTTPException(403, "Requête interorigine refusée")
    secret = request.cookies.get(CSRF_COOKIE, "")
    session = request.cookies.get(SESSION_COOKIE, "")
    if len(secret) != 43 or len(submitted) != 64:
        raise HTTPException(403, "CSRF invalide")
    if not secrets.compare_digest(csrf_proof(secret, session), submitted):
        raise HTTPException(403, "CSRF invalide")


def clear_cookies(response: Response) -> None:
    """Efface avec les mêmes attributs que lors de la création."""
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
