"""Chrome réel : MediaRecorder avec source audio fictive et imports réellement décodés."""

import os
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from backend.app.database import ROOT
from backend.tests.audio_fixtures import audio_sample


@pytest.mark.browser
def test_chrome_microphone_import_and_errors():
    origin = os.getenv("WEB_TEST_URL")
    if not origin:
        pytest.skip("WEB_TEST_URL absent : test Chrome audio non exécuté")
    executable = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not executable.exists():
        pytest.skip("Chrome absent ; aucun navigateur téléchargé")
    screenshots = ROOT / "tmp/p04-screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(executable), headless=True,
            args=["--use-fake-device-for-media-stream"],
        )
        context = browser.new_context(ignore_https_errors=True,
                                      viewport={"width": 1440, "height": 1000})
        context.grant_permissions(["microphone"], origin=origin)
        page = context.new_page()
        errors, uploads = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: uploads.append(request.method)
                if request.url == origin + "/web/audio" else None)
        page.goto(origin + "/inscription")
        email = f"audio-{uuid.uuid4().hex[:10]}@example.com"
        password = "fictional audio test passphrase"
        page.get_by_label("Adresse e-mail").fill(email)
        page.get_by_label("Mot de passe", exact=True).fill(password)
        page.get_by_role("button", name="Créer mon compte").click()
        page.wait_for_url("**/connexion?etat=inscrit")
        page.get_by_label("Adresse e-mail").fill(email)
        page.get_by_label("Mot de passe", exact=True).fill(password)
        page.get_by_role("button", name="Me connecter").click()
        page.wait_for_url("**/accueil")
        page.goto(origin + "/nouveau-reve")
        page.screenshot(path=str(screenshots / "capture-desktop.png"), full_page=True)
        page.get_by_role("button", name="Démarrer l’enregistrement").click()
        expect(page.get_by_role("button", name="Arrêter", exact=True)).to_be_enabled()
        page.wait_for_timeout(1500)  # durée du signal synthétique capturé par le vrai MediaRecorder
        page.get_by_role("button", name="Arrêter", exact=True).click()
        expect(page.locator("#audio-review")).to_be_visible()
        assert uploads == [], "Un audio a été envoyé avant confirmation"
        page.locator("#audio-preview").evaluate("audio => audio.play()")
        expect(page.locator("#audio-preview")).not_to_have_js_property("currentTime", 0,
                                                                       timeout=10000)
        page.locator("#audio-preview").evaluate("audio => audio.pause()")
        with page.expect_response(lambda response: response.request.method == "POST"
                                  and response.url == origin + "/web/audio") as saved:
            page.get_by_role("button", name="Confirmer et enregistrer l’audio").click()
        assert saved.value.status == 201
        assert saved.value.request.headers["x-audio-source"] == "microphone"
        assert saved.value.request.headers["x-audio-format"] == "webm"
        page.wait_for_url("**/reves/*/audio")
        page.locator("#saved-audio").evaluate("audio => audio.play()")
        expect(page.locator("#saved-audio")).not_to_have_js_property("currentTime", 0,
                                                                     timeout=10000)
        expect(page.get_by_role("heading", name="Votre audio est enregistré.")).to_be_visible()
        page.screenshot(path=str(screenshots / "audio-enregistre.png"), full_page=True)

        for media_format in ["wav", "mp3"]:
            page.goto(origin + "/nouveau-reve")
            page.get_by_role("button", name="Importer un fichier").click()
            page.locator("#audio-file").set_input_files({
                "name": "fiction." + media_format, "mimeType": "application/octet-stream",
                "buffer": audio_sample(media_format),
            })
            expect(page.locator("#audio-review")).to_be_visible()
            with page.expect_response(lambda response: response.request.method == "POST"
                                      and response.url == origin + "/web/audio") as imported:
                page.get_by_role("button", name="Confirmer et enregistrer l’audio").click()
            assert imported.value.status == 201
            assert imported.value.request.headers["x-audio-format"] == media_format
            page.wait_for_url("**/reves/*/audio")

        page.goto(origin + "/nouveau-reve")
        page.get_by_role("button", name="Importer un fichier").click()
        page.locator("#audio-file").set_input_files({
            "name": "vide.wav", "mimeType": "audio/wav", "buffer": b"",
        })
        expect(page.get_by_role("alert")).to_contain_text("vide")
        page.locator("#audio-file").set_input_files({
            "name": "falsifie.wav", "mimeType": "audio/wav", "buffer": b"not audio",
        })
        page.get_by_role("button", name="Confirmer et enregistrer l’audio").click()
        expect(page.get_by_role("alert")).to_contain_text("pas un audio valide")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
        page.screenshot(path=str(screenshots / "capture-mobile.png"), full_page=True)

        # Refus réel de permission navigateur ; aucune substitution de getUserMedia.
        context.clear_permissions()
        target = context.new_cdp_session(page).send("Target.getTargetInfo")["targetInfo"]
        browser.new_browser_cdp_session().send("Browser.setPermission", {
            "permission": {"name": "microphone"}, "setting": "denied", "origin": origin,
            "browserContextId": target["browserContextId"],
        })
        page.goto(origin + "/nouveau-reve")
        assert page.evaluate(
            "async () => (await navigator.permissions.query({name: 'microphone'})).state"
        ) == "denied"
        page.get_by_role("button", name="Démarrer l’enregistrement").click()
        expect(page.get_by_role("alert")).to_contain_text("microphone refusé")
        assert not errors, "Erreur JavaScript dans le parcours audio"
        context.close()
        browser.close()
