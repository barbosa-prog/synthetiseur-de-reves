"""Contrats HTML, cookies et CSRF du socle P20."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import get_db
from backend.app.main import create_app
from backend.app.models import AuthSession, User
from backend.app.security import token_digest
from backend.app.web.security import CSRF_COOKIE, SESSION_COOKIE

ORIGIN = "https://localhost:8443"
PASSWORD = "fictional P20 passphrase only"


def proof(response):
    return re.search(r'name="csrf" value="([a-f0-9]+)"', response.text).group(1)


@pytest.fixture
def public_client(monkeypatch):
    monkeypatch.setenv("WEB_ORIGIN", ORIGIN)
    with TestClient(create_app(), base_url=ORIGIN) as client:
        yield client


@pytest.mark.parametrize("path", ["/connexion", "/inscription"])
def test_public_html_and_cookie(public_client, path):
    response = public_client.get(path)
    assert response.status_code == 200
    assert '<html lang="fr">' in response.text and '<form method="post"' in response.text
    assert "https://cdn" not in response.text
    assert "/static/css/app.css" in response.text
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "max-age" not in cookie and "expires=" not in cookie and "domain=" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert public_client.cookies.get(CSRF_COOKIE) not in response.text


def test_protected_page_without_session(public_client):
    response = public_client.get("/accueil", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/connexion?etat=expiree"


@pytest.mark.parametrize("origin,csrf", [
    ("https://evil.example", "valid"), ("null", "valid"), (None, "valid"),
    (ORIGIN, "bad"), (ORIGIN, ""),
])
def test_csrf_rejected_before_database(public_client, origin, csrf):
    page = public_client.get("/connexion")
    response = public_client.post("/connexion", data={
        "csrf": proof(page) if csrf == "valid" else csrf,
        "email": "fiction@example.com", "password": PASSWORD,
    }, headers={"Origin": origin} if origin is not None else {})
    assert response.status_code == 403


def test_cross_site_and_unbound_csrf(public_client):
    page = public_client.get("/connexion")
    response = public_client.post("/connexion", data={"csrf": proof(page)},
                                  headers={"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    public_client.cookies.set(SESSION_COOKIE, "A" * 43)
    response = public_client.post("/connexion", data={"csrf": proof(page)},
                                  headers={"Origin": ORIGIN})
    assert response.status_code == 403


def test_https_and_host_required(public_client):
    assert public_client.get("http://localhost:8443/connexion").status_code == 400
    assert public_client.get("/connexion", headers={"Host": "evil.example"}).status_code == 400


def test_static_assets(public_client):
    css = public_client.get("/static/css/app.css")
    assert css.status_code == 200 and "tailwindcss" in css.text
    assert "@import" not in css.text and "@apply" not in css.text
    assert public_client.get("/static/js/app.js").status_code == 200
    assert public_client.get("/static/images/moon.svg").status_code == 200


@pytest.fixture
def web_client(database, monkeypatch):
    monkeypatch.setenv("WEB_ORIGIN", ORIGIN)
    engine, _ = database
    app = create_app()

    def dependency():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, engine


def submit(client, path, **data):
    page = client.get(path)
    return client.post(path, data={"csrf": proof(page), **data},
                       headers={"Origin": ORIGIN}, follow_redirects=False)


def login(client):
    assert submit(client, "/inscription", email="fiction@example.com",
                  password=PASSWORD).status_code == 303
    return submit(client, "/connexion", email="fiction@example.com", password=PASSWORD)


@pytest.mark.integration
def test_web_register_login_logout_and_bearer_unchanged(web_client, caplog):
    client, engine = web_client
    response = login(client)
    assert response.status_code == 303 and response.headers["location"] == "/accueil"
    token = client.cookies.get(SESSION_COOKIE)
    assert len(token) == 43 and token not in response.text
    page = client.get("/accueil")
    assert page.status_code == 200 and "Votre espace," in page.text
    assert token not in page.text
    assert client.get("/web/session").json()["active"] is True
    # Le transport cookie n'ouvre pas les API Bearer existantes.
    assert client.get("/api/v1/auth/session").status_code == 401
    assert client.get("/api/v1/auth/session", headers={
        "Authorization": "Bearer " + token,
    }).status_code == 200
    assert client.post("/deconnexion", data={"csrf": "bad"},
                       headers={"Origin": ORIGIN}).status_code == 403
    response = client.post("/deconnexion", data={"csrf": proof(page)},
                           headers={"Origin": ORIGIN}, follow_redirects=False)
    assert response.status_code == 303
    assert client.cookies.get(SESSION_COOKIE) is None
    assert client.get("/api/v1/auth/session", headers={
        "Authorization": "Bearer " + token,
    }).status_code == 401
    with Session(engine) as db:
        assert db.scalar(select(User)).password_hash.startswith("$argon2id$")
        assert db.scalar(select(AuthSession)).revoked_at is not None
    assert token not in caplog.text and PASSWORD not in caplog.text


@pytest.mark.integration
def test_expired_cookie_session(web_client):
    client, engine = web_client
    login(client)
    with Session(engine) as db:
        row = db.scalar(select(AuthSession))
        row.created_at = datetime.now(timezone.utc) - timedelta(hours=9)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    response = client.get("/accueil", follow_redirects=False)
    assert response.status_code == 303
    assert client.cookies.get(SESSION_COOKIE) is None


@pytest.mark.integration
def test_errors_rotation_and_csrf_replay(web_client):
    client, engine = web_client
    login(client)
    first = client.cookies.get(SESSION_COOKIE)
    old_csrf = proof(client.get("/connexion"))
    assert submit(client, "/connexion", email="fiction@example.com",
                  password="wrong fictional password").status_code == 401
    assert submit(client, "/inscription", email="fiction@example.com",
                  password=PASSWORD).status_code == 409
    assert submit(client, "/connexion", email="fiction@example.com",
                  password=PASSWORD).status_code == 303
    assert client.cookies.get(SESSION_COOKIE) != first
    with Session(engine) as db:
        old = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(first)))
        assert old.revoked_at is not None
    assert client.post("/deconnexion", data={"csrf": old_csrf},
                       headers={"Origin": ORIGIN}).status_code == 403


@pytest.mark.integration
def test_invalid_form_never_echoes_password(web_client):
    client, _ = web_client
    response = submit(client, "/inscription", email="not-an-email", password=PASSWORD)
    assert response.status_code == 422 and PASSWORD not in response.text
