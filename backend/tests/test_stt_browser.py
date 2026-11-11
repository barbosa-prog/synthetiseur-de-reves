"""Chrome réel, worker avec faux fournisseur et PostgreSQL réel, sans téléchargement."""

import os
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from backend.app.database import ROOT, make_engine, session_factory
from backend.app.services.media import MediaService
from backend.app.services.stt_jobs import run_once
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.audio_fixtures import audio_sample
from backend.tests.test_stt import FakeProvider


@pytest.mark.browser
def test_transcription_web_journey():
    origin = os.getenv("WEB_TEST_URL")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not origin or not chrome.is_file():
        pytest.skip("Chrome/origine de recette absent ; aucun téléchargement automatique")
    screenshots = ROOT / "tmp/p05-screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    engine = make_engine()
    try:
        sessions = session_factory(engine)
        service = MediaService(LocalPrivateStorage.from_environment(), sessions)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
            context = browser.new_context(ignore_https_errors=True,
                                          viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/inscription")
            email = f"stt-{uuid.uuid4().hex[:10]}@example.com"
            password = "fictional STT browser passphrase only"
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Créer mon compte").click()
            page.wait_for_url("**/connexion?etat=inscrit")
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Me connecter").click()
            page.wait_for_url("**/accueil")
            page.goto(origin + "/nouveau-reve")
            page.get_by_role("button", name="Importer un fichier").click()
            page.locator("#audio-file").set_input_files({
                "name": "fiction.wav", "mimeType": "audio/wav", "buffer": audio_sample("wav"),
            })
            page.get_by_role("button", name="Confirmer et enregistrer l’audio").click()
            page.wait_for_url("**/audio")
            page.get_by_role("link", name="Transcrire l’audio en français").click()
            expect(page.get_by_role("heading", name="Retrouver les mots du rêve.")).to_be_visible()
            expect(page.get_by_role("button", name="Se déconnecter")).to_be_visible()
            page.get_by_role("button", name="Lancer la transcription locale").click()
            expect(page.locator("#stt-status")).to_contain_text("En attente")
            page.screenshot(path=str(screenshots / "transcription-attente.png"), full_page=True)
            assert run_once(sessions, service, FakeProvider())
            expect(page.locator("#stt-status")).to_contain_text("Transcription enregistrée",
                                                                           timeout=10000)
            page.screenshot(path=str(screenshots / "transcription-terminee.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(screenshots / "transcription-mobile.png"), full_page=True)
            assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
            page.get_by_role("link", name="Ouvrir l’éditeur du récit").click()
            expect(page.get_by_label("Récit du rêve")).to_have_value(FakeProvider().output)
            page.get_by_role("link", name="Transcription locale de l’audio").click()
            page.get_by_role("button", name="Lancer la transcription locale").click()
            assert run_once(sessions, service, FakeProvider(error="timeout"))
            expect(page.locator("#stt-status")).to_contain_text("délai", timeout=10000)
            assert not errors
            context.close()
            browser.close()
    finally:
        engine.dispose()
