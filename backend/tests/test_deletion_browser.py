"""Confirmation et retrait dans Chrome bureau/mobile : rêves fictifs uniquement."""

import io
import os
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from backend.app.database import database_url, make_engine, session_factory
from backend.app.models import Dream, Job, Media, User
from backend.app.services.media import MediaService
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.test_private_storage import image_bytes


@pytest.mark.browser
def test_confirmation_and_deletion_chrome_desktop_mobile():
    origin = os.getenv("WEB_TEST_URL")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not origin or not chrome.is_file():
        pytest.skip("Chrome/origine temporaire absent")
    url = database_url()
    assert url.database == "p20_validation" and url.port != 5434
    engine = make_engine(url)
    sessions = session_factory(engine)
    storage = LocalPrivateStorage.from_environment()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            email, password = f"delete-{uuid4().hex}@example.com", "fictional deletion passphrase"
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
                survivor = Dream(user_id=owner, transcript="Fiction conservée.", text_version=1)
                db.add(survivor)
                db.commit()
                survivor_id = survivor.id
            for width, height in [(1280, 960), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                with sessions() as db:
                    dream = Dream(user_id=owner, transcript="Fiction à retirer.", text_version=1)
                    db.add(dream)
                    db.commit()
                    identifier = dream.id
                media = MediaService(storage, sessions).store(
                    owner, identifier, io.BytesIO(image_bytes()), kind="image", media_format="png",
                )
                with sessions() as db:
                    db.add_all([Job(dream_id=identifier, kind=kind)
                                for kind in ["stt", "image", "emotion"]])
                    db.commit()
                page.goto(origin + f"/reves/{identifier}")
                page.get_by_role("link", name="Supprimer ce rêve", exact=True).click()
                expect(page.get_by_role("heading", name="Supprimer ce rêve ?")).to_be_visible()
                assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
                page.get_by_role("link", name="Annuler", exact=True).click()
                page.wait_for_url(f"**/reves/{identifier}")
                page.get_by_role("link", name="Supprimer ce rêve", exact=True).click()
                page.get_by_role("button", name="Confirmer la suppression").click()
                # La validation HTML bloque le POST tant que la case n'est pas cochée.
                with sessions() as db:
                    assert db.get(Dream, identifier).status != "deleted"
                page.get_by_role("checkbox").check()
                page.get_by_role("button", name="Confirmer la suppression").click()
                page.wait_for_url("**/mes-reves")
                assert page.locator(f'article[data-dream-id="{identifier}"]').count() == 0
                expect(page.locator(f'article[data-dream-id="{survivor_id}"]')).to_be_visible()
                assert context.request.get(origin + f"/web/media/{media}/content").status == 404
                assert context.request.get(origin + f"/reves/{identifier}").status == 404
                with sessions() as db:
                    assert db.get(Dream, identifier).deleted_at
                    record = db.get(Media, media)
                    assert record.storage_state == "deleting"
                    assert (storage.root / record.storage_key).is_file()
                    assert all(j.status == "failed" and j.claim_token is None
                               for j in db.scalars(select(Job).where(Job.dream_id == identifier)))
            assert not errors
            context.close()
            browser.close()
    finally:
        engine.dispose()
