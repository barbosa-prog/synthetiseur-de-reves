"""Recette dans un vrai Chromium installé, sans téléchargement d'un navigateur."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import ROOT, database_url, make_engine
from backend.app.models import AuthSession
from backend.app.security import token_digest
from backend.app.web.security import SESSION_COOKIE


@pytest.mark.browser
def test_real_browser_journey():
    origin = os.getenv("WEB_TEST_URL")
    if not origin:
        pytest.skip("WEB_TEST_URL absent : recette navigateur non exécutée")
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    executable = next((path for path in candidates if path.exists()), None)
    if executable is None:
        pytest.skip("Chrome/Edge non trouvé ; aucun téléchargement automatique")
    screenshots = ROOT / "tmp/p20-screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
        # Certificat temporaire non installé dans Windows : exception limitée à ce test.
        context = browser.new_context(
            ignore_https_errors=True, viewport={"width": 1440, "height": 1000},
        )
        page = context.new_page()
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: external.append(request.url)
                if not request.url.startswith(origin + "/") else None)
        page.goto(origin + "/accueil")
        assert "/connexion" in page.url
        assert page.get_by_role("heading", name="Heureux de vous retrouver").is_visible()
        assert page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor") == (
            "rgb(11, 17, 32)"
        )
        page.screenshot(path=str(screenshots / "connexion-desktop.png"), full_page=True)
        page.goto(origin + "/inscription")
        email = f"browser-{uuid.uuid4().hex[:10]}@example.com"
        password = "fictional browser passphrase only"
        page.get_by_label("Adresse e-mail").fill(email)
        page.get_by_label("Mot de passe", exact=True).fill(password)
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url == origin + "/inscription", timeout=10000,
        ) as registration:
            page.get_by_role("button", name="Créer mon compte").click()
        assert registration.value.status == 303, (
            "Inscription navigateur refusée", registration.value.status,
            registration.value.request.headers.get("origin"),
            registration.value.request.headers.get("sec-fetch-site"),
        )
        page.wait_for_url("**/connexion?etat=inscrit")
        page.get_by_label("Adresse e-mail").fill(email)
        page.get_by_label("Mot de passe", exact=True).fill(password)
        page.get_by_role("button", name="Me connecter").click()
        page.wait_for_url("**/accueil")
        assert page.get_by_role("heading", name="Votre espace, au calme.").is_visible()
        cookie = next(c for c in context.cookies() if c["name"] == SESSION_COOKIE)
        assert cookie["httpOnly"] and cookie["secure"] and cookie["sameSite"] == "Lax"
        assert cookie["expires"] == -1
        assert page.evaluate("document.cookie") == ""
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert bool(cookie["value"] not in page.content()), "Secret présent dans le DOM"
        assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
        page.screenshot(path=str(screenshots / "accueil-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="Ouvrir la navigation").click()
        assert page.get_by_role("button", name="Se déconnecter").is_visible()
        assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
        page.screenshot(path=str(screenshots / "accueil-mobile.png"), full_page=True)
        # CSRF malveillant depuis un contexte partageant les cookies du navigateur.
        csrf = page.locator('input[name="csrf"]').input_value()
        response = context.request.post(origin + "/deconnexion", form={"csrf": csrf},
                                        headers={"Origin": "https://evil.example"})
        assert response.status == 403
        # Expiration réelle en base, puis navigation : redirection et cookie effacé.
        engine = make_engine(database_url("TEST_DATABASE_URL"))
        try:
            with Session(engine) as db:
                row = db.scalar(select(AuthSession).where(
                    AuthSession.token_hash == token_digest(cookie["value"]),
                ))
                row.created_at = datetime.now(timezone.utc) - timedelta(hours=9)
                row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
        finally:
            engine.dispose()
        page.reload()
        page.wait_for_url("**/connexion?etat=expiree")
        page.get_by_label("Adresse e-mail").fill(email)
        page.get_by_label("Mot de passe", exact=True).fill(password)
        page.get_by_role("button", name="Me connecter").click()
        page.wait_for_url("**/accueil")
        page.get_by_role("button", name="Ouvrir la navigation").click()
        page.get_by_role("button", name="Se déconnecter").click()
        page.wait_for_url("**/connexion")
        page.goto(origin + "/accueil")
        assert "/connexion" in page.url
        assert not external, "L'interface a demandé une ressource externe"
        assert not errors, "Erreur JavaScript dans le navigateur"
        context.close()
        browser.close()
