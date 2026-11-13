"""Pages Jinja2 et formulaires web ; aucun jeton d'authentification dans le DOM."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.auth import Database, find_session
from backend.app.auth_schemas import Credentials
from backend.app.models import AuthSession, User
from backend.app.security import new_token
from backend.app.services.authentication import create_login, register_user
from backend.app.web.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    check_csrf,
    clear_cookies,
    csrf_proof,
    set_private_cookie,
)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class WebLoginRequired(Exception):
    """Redirection web, distincte des réponses 401 JSON de l'API."""


def render(request: Request, template: str, status: int = 200, **context):
    """Échappement Jinja2 actif ; secret CSRF HttpOnly indépendant du jeton de session."""
    secret = request.cookies.get(CSRF_COOKIE, "")
    if len(secret) != 43:
        secret = new_token()
    response = templates.TemplateResponse(
        request=request, name=template,
        context={"csrf": csrf_proof(secret, request.cookies.get(SESSION_COOKIE, "")), **context},
        status_code=status,
    )
    set_private_cookie(response, CSRF_COOKIE, secret)
    return response


async def web_login_required(request: Request, exc: WebLoginRequired):
    """Session absente, expirée ou révoquée : retour à la connexion, cookies effacés."""
    if request.headers.get("accept") == "application/json":
        from fastapi.responses import JSONResponse
        response = JSONResponse({"detail": "Authentification requise"}, status_code=401)
    else:
        response = RedirectResponse("/connexion?etat=expiree", status_code=303)
    clear_cookies(response)
    return response


def cookie_token(request: Request) -> str:
    """Refus avant accès DB si aucun cookie d'authentification plausible."""
    token = request.cookies.get(SESSION_COOKIE, "")
    if len(token) != 43:
        raise WebLoginRequired
    return token


def browser_session(token: Annotated[str, Depends(cookie_token)], db: Database) -> AuthSession:
    """Même expiration et révocation PostgreSQL que les sessions P03."""
    session = find_session(db, token)
    if session is None:
        raise WebLoginRequired
    return session


BrowserSession = Annotated[AuthSession, Depends(browser_session)]


async def valid_form(request: Request) -> dict:
    """Contrôle CSRF avant le service métier et limite les champs des formulaires P20."""
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > 8192:
        raise HTTPException(413, "Formulaire trop volumineux")
    # HTTPGuard borne déjà le flux ; ce contrôle local reste autonome et progressif.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8192:
            raise HTTPException(413, "Formulaire trop volumineux")
        body.extend(chunk)
    request._body = bytes(body)
    form = await request.form(max_files=0, max_fields=4)
    check_csrf(request, str(form.get("csrf", "")))
    return dict(form)


ValidForm = Annotated[dict, Depends(valid_form)]


@router.get("/")
def root():
    """L'accueil décide si une session est encore valide."""
    return RedirectResponse("/accueil", status_code=303)


@router.get("/connexion")
def login_page(request: Request):
    """Page publique ; le paramètre d'état n'est jamais un secret."""
    return render(request, "auth.html", mode="login",
                  expired=request.query_params.get("etat") == "expiree",
                  registered=request.query_params.get("etat") == "inscrit")


@router.get("/inscription")
def register_page(request: Request):
    """Page publique de création de compte."""
    return render(request, "auth.html", mode="register")


@router.get("/confidentialite")
def privacy_page(request: Request):
    """Information publique statique ; aucun accès aux comptes ou aux rêves."""
    return render(request, "privacy.html")


def credentials(form: dict) -> Credentials:
    """Les erreurs de validation ne sont ni affichées brutes ni journalisées."""
    return Credentials(email=form.get("email", ""), password=form.get("password", ""))


@router.post("/inscription")
def register_action(request: Request, form: ValidForm, db: Database):
    """Réutilise le service d'inscription P03 et son limiteur partagé."""
    try:
        register_user(credentials(form), request, db)
    except ValidationError:
        return render(request, "auth.html", 422, mode="register",
                      error="Vérifiez l’adresse e-mail et un mot de passe de 15 à 128 caractères.")
    except HTTPException as exc:
        return form_error(request, "register", exc)
    return RedirectResponse("/connexion?etat=inscrit", status_code=303)


def form_error(request: Request, mode: str, exc: HTTPException):
    """Messages publics, jamais l'exception brute ni le mot de passe soumis."""
    messages = {
        401: "E-mail ou mot de passe incorrect.",
        409: "L’inscription n’est pas possible avec cette adresse.",
        429: "Trop de tentatives. Patientez avant de réessayer.",
    }
    response = render(request, "auth.html", exc.status_code, mode=mode,
                      error=messages.get(exc.status_code, "Le service est indisponible."))
    if exc.headers:
        response.headers.update(exc.headers)
    return response


@router.post("/connexion")
def login_action(request: Request, form: ValidForm, db: Database):
    """Ne renvoie jamais le jeton en JSON ou dans le formulaire."""
    try:
        result = create_login(credentials(form), request, db)
    except ValidationError:
        return render(request, "auth.html", 422, mode="login",
                      error="Vérifiez l’adresse e-mail et le format du mot de passe.")
    except HTTPException as exc:
        return form_error(request, "login", exc)
    # Révoquer l'ancienne session du navigateur, si elle existe, avant rotation.
    previous = find_session(db, request.cookies.get(SESSION_COOKIE, ""))
    if previous is not None:
        previous.revoked_at = db.scalar(select(func.clock_timestamp()))
        db.commit()
    response = RedirectResponse("/accueil", status_code=303)
    set_private_cookie(response, SESSION_COOKIE, result.access_token.get_secret_value())
    set_private_cookie(response, CSRF_COOKIE, new_token())
    return response


@router.get("/accueil")
def home(request: Request, session: BrowserSession, db: Database):
    """Page protégée ; aucune fonction audio/IA/historique simulée."""
    user = db.get(User, session.user_id)
    return render(request, "home.html", user=user, expires_at=session.expires_at.isoformat())


@router.get("/web/session")
def session_status(session: BrowserSession):
    """Statut privé pour détecter l'expiration, sans transmettre le jeton à JavaScript."""
    return JSONResponse({"active": True, "expires_at": session.expires_at.isoformat()})


@router.post("/deconnexion")
def logout_action(form: ValidForm, session: BrowserSession, db: Database):
    """CSRF obligatoire ; révoque la session P03 et efface les cookies."""
    session.revoked_at = db.scalar(select(func.clock_timestamp()))
    db.commit()
    response = RedirectResponse("/connexion", status_code=303)
    clear_cookies(response)
    return response
