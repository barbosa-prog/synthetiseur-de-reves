"""Parcours Chrome P08 sur serveur temporaire ; fournisseur déterministe uniquement."""

import os
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from backend.app.database import ROOT, make_engine, session_factory
from backend.app.emotion_web import WARNING
from backend.app.models import Dream, Job, User
from backend.app.services import emotions
from backend.app.services.transcripts import apply_correction
from backend.tests.browser_workers import wait_for_work
from backend.tests.test_emotion_web import complete_fake


@pytest.mark.browser
def test_emotion_chrome_fictional_only():
    origin = os.getenv("WEB_TEST_URL")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not origin or not chrome.is_file():
        pytest.skip("Chrome/origine temporaire absent")
    engine = make_engine()
    sessions = session_factory(engine)
    screenshots = ROOT / "tmp/p08-web-screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
            context = browser.new_context(
                ignore_https_errors=True, viewport={"width": 1280, "height": 960}
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/inscription")
            email = f"emotion-web-{uuid.uuid4().hex[:12]}@example.com"
            password = "fictional emotion browser passphrase"
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Créer mon compte").click()
            page.wait_for_url("**/connexion?etat=inscrit")
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Me connecter").click()
            page.wait_for_url("**/accueil")
            with sessions() as db:
                owner = db.scalar(select(User).where(User.email == email))
                owner_id = owner.id
                dream = Dream(
                    user_id=owner_id, transcript="Un récit fictif de forêt.", text_version=1
                )
                db.add(dream)
                db.commit()
                identifier = dream.id
            path = f"/reves/{identifier}/emotion"
            page.goto(origin + f"/reves/{identifier}")
            page.get_by_role("link", name="Émotion", exact=True).click()
            expect(page.locator("#emotion-warning")).to_have_text(WARNING)
            expect(page.get_by_role("heading", name="Récit actuel · version 1")).to_be_visible()
            page.screenshot(path=str(screenshots / "emotion-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
            page.screenshot(path=str(screenshots / "emotion-mobile.png"), full_page=True)
            page.get_by_label("Choix manuel", exact=True).select_option("triste")
            page.get_by_role("button", name="Enregistrer mon choix").click()
            expect(page.locator("#retained-emotion")).to_have_text("Triste")
            page.goto(origin + "/mes-reves?emotion=triste")
            expect(page.locator(f'article[data-dream-id="{identifier}"]')).to_be_visible()
            page.goto(origin + path)
            if os.getenv("EMOTION_ENABLED") == "1":
                page.get_by_role("button", name="Suggérer une émotion").click()
                expect(page.locator("#emotion-status")).to_contain_text("En attente")
                with sessions() as db:
                    job_id = db.scalar(select(Job.id).where(
                        Job.dream_id == identifier, Job.kind == "emotion"))
                reservation = wait_for_work(lambda: emotions.claim(sessions))
                assert reservation is not None, "Le worker fictif n'a réservé aucun job"
                assert reservation[0] == job_id, "Le worker fictif a réservé un autre job"
                with sessions() as db:
                    assert db.get(Job, job_id).status == "running"
                response = context.request.get(origin + path + "/statut")
                assert response.status == 200
                progress = response.json()
                assert progress["job_id"] == str(job_id)
                assert progress["status"] == "running"
                assert progress["tracking"]["technical_state"] == "running"
                assert progress["message"] == "Analyse en cours…"
                expect(page.locator("#emotion-status")).to_have_text("Analyse en cours…")
                assert complete_fake(sessions, reservation=reservation)
                expect(page.locator("#suggested-emotion")).to_have_text("Heureux")
                expect(page.locator("#retained-emotion")).to_have_text("Triste")
                page.get_by_role("button", name="Accepter cette suggestion").click()
                expect(page.locator("#retained-emotion")).to_have_text("Heureux")
                expect(page.locator("#emotion-origin")).to_have_text("Suggestion acceptée")
                page.get_by_role("button", name="Retirer mon choix").click()
                expect(page.locator("#retained-emotion")).to_have_text("Non renseignée")
                # Une même entrée réussie est réutilisée ; changer réellement le récit.
                with sessions() as db:
                    row = db.get(Dream, identifier, with_for_update=True)
                    apply_correction(db, row, "Une fiction différente pour une abstention.", 1)
                    db.commit()
                page.goto(origin + path)
                page.get_by_role("button", name="Suggérer une émotion").click()
                expect(page.locator("#emotion-status")).to_contain_text("En attente")
                assert complete_fake(sessions, None, "ambiguous", reservation=wait_for_work(
                    lambda: emotions.claim(sessions)))
                expect(page.locator("#emotion-status")).to_contain_text("Abstention")
                expect(page.locator("#emotion-accept")).to_be_disabled()
                with sessions() as db:
                    row = db.get(Dream, identifier, with_for_update=True)
                    apply_correction(db, row, "Une autre fiction pour une suggestion.", 2)
                    db.commit()
                page.goto(origin + path)
                page.get_by_role("button", name="Suggérer une émotion").click()
                expect(page.locator("#emotion-status")).to_contain_text("En attente")
                assert complete_fake(sessions, reservation=wait_for_work(
                    lambda: emotions.claim(sessions)))
                expect(page.locator("#suggested-emotion")).to_have_text("Heureux")
                with sessions() as db:
                    row = db.get(Dream, identifier, with_for_update=True)
                    apply_correction(db, row, "Une nouvelle fiction corrigée.", 3)
                    db.commit()
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(page.locator("#emotion-suggestion")).to_be_hidden(timeout=10000)
                expect(page.locator("#emotion-reload")).to_be_visible()
            else:
                expect(page.locator("#emotion-request")).to_be_disabled()
                expect(page.locator("#emotion-disabled")).to_be_visible()
                page.get_by_role("button", name="Retirer mon choix").click()
                expect(page.locator("#retained-emotion")).to_have_text("Non renseignée")
            assert not errors
            context.close()
            browser.close()
    finally:
        engine.dispose()
