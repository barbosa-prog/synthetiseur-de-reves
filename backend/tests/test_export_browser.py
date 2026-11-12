"""Téléchargements Chrome bureau/mobile sur recette HTTPS temporaire seulement."""

import io
import json
import os
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from backend.app.database import database_url, make_engine, session_factory
from backend.app.models import Dream, User
from backend.app.services.media import MediaService
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.test_private_storage import image_bytes


@pytest.mark.browser
def test_export_chrome_desktop_and_mobile():
    origin = os.getenv("WEB_TEST_URL")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not origin or not chrome.is_file():
        pytest.skip("Chrome/origine temporaire absent")
    url = database_url()
    assert url.database == "p20_validation" and url.port != 5434
    engine = make_engine(url)
    sessions = session_factory(engine)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            email = f"export-{uuid4().hex}@example.com"
            password = "fictional export browser passphrase"
            page.goto(origin + "/inscription")
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Créer mon compte").click()
            page.wait_for_url("**/connexion?etat=inscrit")
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill(password)
            page.get_by_role("button", name="Me connecter").click()
            page.wait_for_url("**/accueil")
            with sessions() as db:
                owner = db.scalar(select(User.id).where(User.email == email))
                dream = Dream(user_id=owner, transcript="Un rêve fictif pour exporter.",
                              text_version=1)
                db.add(dream)
                db.commit()
                identifier = dream.id
            media = MediaService(LocalPrivateStorage.from_environment(), sessions).store(
                owner, identifier, io.BytesIO(image_bytes()), kind="image", media_format="png",
            )
            for width, height in [(1280, 960), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                page.goto(origin + f"/reves/{identifier}")
                button = page.get_by_role("button", name="Exporter ce rêve")
                expect(button).to_be_visible()
                assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
                with page.expect_download() as download_info:
                    button.click()
                download = download_info.value
                assert download.failure() is None
                assert download.suggested_filename == f"reve-{identifier}.zip"
                with ZipFile(download.path()) as archive:
                    assert archive.testzip() is None
                    assert archive.read("recit.txt").decode() == "Un rêve fictif pour exporter."
                    assert archive.read(f"medias/image-{media}.png") == image_bytes()
                    assert json.loads(archive.read("manifest.json"))["media"][0]["exported"]
                download.delete()
            assert not errors
            context.close()
            browser.close()
    finally:
        engine.dispose()
