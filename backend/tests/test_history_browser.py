"""Chrome P09 sur la recette temporaire ; aucune IA, seulement un PNG synthétique."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from backend.app.database import ROOT, make_engine, session_factory
from backend.app.models import Dream, User
from backend.app.services import image_jobs
from backend.app.services.image_execution import run_once
from backend.app.services.transcripts import apply_correction
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.test_image_execution import FakeEngine


@pytest.mark.browser
def test_history_journey_and_mobile_without_ai():
    origin = os.getenv("WEB_TEST_URL")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not origin or not chrome.is_file():
        pytest.skip("Chrome/origine de recette absents ; aucun téléchargement")
    screenshots = ROOT/"tmp/p09-screenshots"
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
            page.goto(origin+"/mes-reves")
            page.wait_for_url("**/connexion?etat=expiree")
            page.goto(origin+"/inscription")
            email = f"history-{uuid.uuid4().hex[:12]}@example.com"
            password = "fictional history browser passphrase"
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Créer mon compte").click()
            page.wait_for_url("**/connexion?etat=inscrit")
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Me connecter").click()
            page.wait_for_url("**/accueil")
            page.get_by_role("link", name="Mes rêves", exact=True).first.click()
            expect(page.get_by_role("heading", name="Aucun rêve à afficher")).to_be_visible()
            now = datetime.now(timezone.utc)
            with sessions() as db:
                owner = db.scalar(select(User).where(User.email == email))
                owner_id = owner.id
                for number in range(26):
                    db.add(Dream(user_id=owner.id, emotion=None if number < 13 else "heureux",
                                 created_at=now-timedelta(hours=number),
                                 transcript=None if number < 13 else "Récit fictif heureux."))
                featured = Dream(user_id=owner.id, transcript="Récit fictif illustré.",
                                 text_version=1, emotion="autre",
                                 created_at=now+timedelta(minutes=1))
                db.add(featured)
                db.commit()
                dream_id = featured.id
                image_jobs.save_description(db, owner_id, dream_id, "Fictional forest", 1, 0)
                image_jobs.enqueue(db, owner_id, dream_id, 1, 1)
            assert run_once(sessions, storage, FakeEngine())
            page.reload()
            expect(page.locator("#dream-list article")).to_have_count(12)
            expect(page.locator("#dream-list article").first).to_have_attribute(
                "data-dream-id", str(dream_id))
            page.get_by_label("Émotion", exact=True).select_option("non_renseignee")
            page.get_by_role("button", name="Filtrer", exact=True).click()
            expect(page.locator("#dream-list article")).to_have_count(12)
            page.get_by_role("link", name="Page suivante").click()
            assert "emotion=non_renseignee" in page.url
            expect(page.locator("#dream-list article")).to_have_count(1)
            page.get_by_label("Émotion", exact=True).select_option("neutre")
            page.get_by_role("button", name="Filtrer", exact=True).click()
            expect(page.get_by_role("heading", name="Aucun rêve à afficher")).to_be_visible()
            page.get_by_role("link", name="Réinitialiser", exact=True).click()
            page.screenshot(path=str(screenshots/"history-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 800, "height": 960})
            assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
            page.get_by_role("button", name="Ouvrir la navigation").click()
            expect(page.locator("#navigation")).to_be_visible()
            page.get_by_role("button", name="Ouvrir la navigation").click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(screenshots/"history-mobile.png"), full_page=True)
            assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
            page.locator(f'article[data-dream-id="{dream_id}"]').get_by_role(
                "link", name="Ouvrir le rêve").click()
            expect(page.locator("#current-image-panel")).to_be_visible()
            page.wait_for_function("document.querySelector('#current-dream-image').naturalWidth===512")
            page.screenshot(path=str(screenshots/"detail-mobile-fictitious.png"), full_page=True)
            assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
            with sessions() as db:
                dream = db.get(Dream, dream_id, with_for_update=True)
                apply_correction(db, dream, "Un récit fictif corrigé.", 1)
                db.commit()
            expect(page.locator("#current-image-panel")).to_be_hidden(timeout=10000)
            page.get_by_role("link", name="Corriger le récit").click()
            expect(page.get_by_label("Récit du rêve")).to_have_value("Un récit fictif corrigé.")
            assert not errors
            context.close()
            browser.close()
    finally:
        engine.dispose()
