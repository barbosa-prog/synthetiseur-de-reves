"""Chrome réel, PostgreSQL temporaire et PNG synthétique uniquement."""

import os
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from backend.app.database import ROOT, make_engine, session_factory
from backend.app.models import Dream, User
from backend.app.services.image_execution import run_once
from backend.app.services.transcripts import apply_correction
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.test_image_execution import FakeEngine


@pytest.mark.browser
def test_image_user_journey_without_gpu():
    origin = os.getenv("WEB_TEST_URL")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not origin or not chrome.is_file():
        pytest.skip("Chrome/origine temporaire absent ; aucun téléchargement")
    screenshots = ROOT/"tmp/p07-screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    engine = make_engine()
    sessions = session_factory(engine)
    storage = LocalPrivateStorage.from_environment()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
            context = browser.new_context(ignore_https_errors=True,
                                          viewport={"width": 1280, "height": 960})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin+"/inscription")
            email = f"image-{uuid.uuid4().hex[:12]}@example.com"
            password = "fictional image browser passphrase"
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Créer mon compte").click()
            page.wait_for_url("**/connexion?etat=inscrit")
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Me connecter").click()
            page.wait_for_url("**/accueil")
            with sessions() as db:
                user = db.scalar(select(User).where(User.email == email))
                dream = Dream(user_id=user.id, transcript="Récit français fictif.", text_version=1)
                db.add(dream)
                db.commit()
                dream_id = dream.id
            page.goto(origin+f"/reves/{dream_id}/recit")
            page.get_by_role("link", name="Créer une image du rêve").click()
            expect(page.get_by_role("button", name="Générer une image")).to_be_disabled()
            page.get_by_label("Description visuelle").fill("An enchanted fictional forest")
            page.get_by_role("button", name="Enregistrer la description").click()
            expect(page.get_by_text("Description enregistrée.", exact=True)).to_be_visible()
            page.get_by_role("button", name="Générer une image").click()
            expect(page.locator("#image-status")).to_contain_text("En attente")
            assert run_once(sessions, storage, FakeEngine())
            expect(page.locator("#image-status")).to_have_text("Image terminée.", timeout=10000)
            expect(page.locator("#image-result")).to_be_visible()
            page.wait_for_function("document.querySelector('#dream-image').naturalWidth === 512")
            page.screenshot(path=str(screenshots/"image-fictive-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(screenshots/"image-fictive-mobile.png"), full_page=True)
            assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
            page.get_by_role("button", name="Générer une image").click()
            expect(page.locator("#image-status")).to_have_text("Image terminée.")
            duplicate = FakeEngine(error="timeout")
            assert not run_once(sessions, storage, duplicate)
            assert duplicate.calls == 0
            page.get_by_label("Description visuelle").fill("A second fictional forest")
            page.get_by_role("button", name="Enregistrer la description").click()
            page.get_by_role("button", name="Générer une image").click()
            expect(page.locator("#image-status")).to_contain_text("En attente")
            assert run_once(sessions, storage, FakeEngine(error="timeout"))
            expect(page.locator("#image-status")).to_contain_text("délai", timeout=10000)
            page.get_by_label("Description visuelle").fill("A new fictional moon")
            expect(page.get_by_role("button", name="Générer une image")).to_be_disabled()
            page.get_by_role("button", name="Enregistrer la description").click()
            expect(page.locator("#image-result")).to_be_hidden()
            page.get_by_role("button", name="Générer une image").click()

            def correct():
                with sessions() as db:
                    dream = db.get(Dream, dream_id, with_for_update=True)
                    apply_correction(db, dream, "Un récit fictif modifié.", 1)
                    db.commit()

            assert run_once(sessions, storage, FakeEngine(callback=correct))
            expect(page.locator("#image-status")).to_contain_text("Résultat dépassé", timeout=10000)
            expect(page.locator("#image-result")).to_be_hidden()
            expect(page.get_by_role("button", name="Générer une image")).to_be_disabled()
            assert not errors
            context.close()
            browser.close()
    finally:
        engine.dispose()
