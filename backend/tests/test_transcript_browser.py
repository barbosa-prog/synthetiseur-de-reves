"""Édition HTML réelle dans Chrome, après un import audio fictif P04."""

import os
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from backend.app.database import ROOT
from backend.tests.audio_fixtures import audio_sample


@pytest.mark.browser
def test_editor_after_audio_and_concurrent_tabs():
    origin = os.getenv("WEB_TEST_URL")
    if not origin:
        pytest.skip("WEB_TEST_URL absent : éditeur navigateur non testé")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        pytest.skip("Chrome absent ; aucun téléchargement automatique")
    screenshots = ROOT / "tmp/p06-screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
        context = browser.new_context(ignore_https_errors=True,
                                      viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin + "/inscription")
        email = f"editor-{uuid.uuid4().hex[:10]}@example.com"
        password = "fictional editor test passphrase"
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
            "name": "fiction.wav", "mimeType": "audio/wav", "buffer": audio_sample(),
        })
        page.get_by_role("button", name="Confirmer et enregistrer l’audio").click()
        page.wait_for_url("**/reves/*/audio")
        audio_url = page.locator("#saved-audio").get_attribute("src")
        audio_before = context.request.get(origin + audio_url).body()
        page.get_by_role("link", name="Écrire ou corriger le récit").click()
        page.wait_for_url("**/reves/*/recit")
        editor_url = page.url
        text = ("Je marchais dans une forêt lumineuse.\n\n"
                "Un récit fictif, écrit pour la démonstration.")
        expect(page.get_by_label("Récit du rêve")).to_have_value("")
        page.get_by_label("Récit du rêve").fill(text)
        page.get_by_role("button", name="Enregistrer le récit").click()
        page.wait_for_url("**/recit?enregistre=1")
        expect(page.get_by_role("status")).to_contain_text("enregistré")
        page.reload()
        expect(page.get_by_label("Récit du rêve")).to_have_value(text)
        page.screenshot(path=str(screenshots / "editeur-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
        page.screenshot(path=str(screenshots / "editeur-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

        other = context.new_page()
        other.goto(editor_url)
        other.get_by_label("Récit du rêve").fill("Correction fictive dans le second onglet.")
        other.get_by_role("button", name="Enregistrer le récit").click()
        other.wait_for_url("**/recit?enregistre=2")
        page.get_by_label("Récit du rêve").fill("Ma saisie fictive conservée malgré le conflit.")
        with page.expect_response(lambda response: response.request.method == "POST"
                                  and response.url == editor_url) as conflict:
            page.get_by_role("button", name="Enregistrer le récit").click()
        assert conflict.value.status == 409
        expect(page.get_by_role("alert")).to_contain_text("autre correction")
        expect(page.get_by_label("Récit du rêve")).to_have_value(
            "Ma saisie fictive conservée malgré le conflit.",
        )

        malicious = '</textarea><script>window.p06Injected=true</script>'
        other.get_by_label("Récit du rêve").fill(malicious)
        other.get_by_role("button", name="Enregistrer le récit").click()
        other.wait_for_url("**/recit?enregistre=3")
        expect(other.get_by_label("Récit du rêve")).to_have_value(malicious)
        assert other.evaluate("window.p06Injected === undefined")
        other.get_by_label("Récit du rêve").fill("a" * 20001)
        expect(other.get_by_role("alert")).to_contain_text("20 000")
        assert not other.get_by_label("Récit du rêve").evaluate("el => el.checkValidity()")
        other.get_by_label("Récit du rêve").fill(" ")
        expect(other.get_by_role("alert")).to_contain_text("vide")
        assert context.request.get(origin + audio_url).body() == audio_before
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert not errors, "Erreur JavaScript dans l'éditeur"
        context.close()
        browser.close()
