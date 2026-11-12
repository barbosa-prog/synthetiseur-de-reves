"""Recette P10 explicite sur base fraîche ; non collectée par la suite ordinaire."""

import hashlib
import io
import json
import os
import subprocess
import sys
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from playwright.sync_api import sync_playwright
from sqlalchemy import func, select

from backend.app.database import ROOT, database_url, make_engine, session_factory
from backend.app.models import (
    AuthSession,
    Dream,
    DreamEmotion,
    EmotionAnalysis,
    ImageDescription,
    ImageGeneration,
    Job,
    Media,
    User,
)
from backend.app.services import emotions, image_jobs, stt_jobs
from backend.app.services.dream_purge import DreamPurgeService
from backend.app.services.image_execution import run_once as image_once
from backend.app.services.media import MediaService
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.test_emotion_contract import FakeEmotionProvider
from backend.tests.test_emotion_postgresql import FAKE_CONFIG
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_private_storage import image_bytes, wav_bytes


def test_p10_full_recipe(monkeypatch):
    origin = os.environ["WEB_TEST_URL"]
    url = database_url()
    assert url.database == "p20_validation" and url.host == "127.0.0.1" and url.port != 5434
    storage = LocalPrivateStorage.from_environment()
    assert storage.root.parent.name.startswith("dreams_p20_")
    engine = make_engine(url)
    sessions = session_factory(engine)
    media_service = MediaService(storage, sessions)
    report = {}
    password = "fictional P10 final recipe passphrase"
    text = "Je découvre une forêt fictive et ressens une grande joie."
    try:
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(User)) == 0
            assert db.scalar(select(func.count()).select_from(Dream)) == 0
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                headless=True,
            )
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True)
            other_context = browser.new_context(ignore_https_errors=True)
            emails = [f"p10-final-{uuid4().hex}@example.com" for _ in range(2)]
            owners, tokens = [], []
            for email in emails:
                created = context.request.post(origin + "/api/v1/auth/register",
                    data={"email": email, "password": password})
                assert created.status == 201
                owners.append(UUID(created.json()["id"]))
                login = context.request.post(origin + "/api/v1/auth/login",
                    data={"email": email, "password": password})
                assert login.status == 200
                tokens.append(login.json()["access_token"])
            pages = [context.new_page(), other_context.new_page()]
            for page, email in zip(pages, emails):
                page.goto(origin + "/connexion")
                page.get_by_label("Adresse e-mail").fill(email)
                page.get_by_label("Mot de passe", exact=True).fill(password)
                page.get_by_role("button", name="Me connecter").click()
                page.wait_for_url("**/accueil")
            page = pages[0]
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            with sessions() as db:
                target = Dream(user_id=owners[0], transcript=text, text_version=1)
                keepers = [Dream(user_id=owner, transcript=f"DONNEE_AUTRE_REVE_{i}", text_version=1)
                           for i, owner in enumerate(owners)]
                db.add_all([target, *keepers])
                db.flush()
                identifier, keeper_ids = target.id, [row.id for row in keepers]
                db.add_all([Job(dream_id=key, kind="tts") for key in keeper_ids])
                db.commit()
            keeper_media = [media_service.store(owner, key, io.BytesIO(image_bytes()),
                            kind="image", media_format="png")
                            for owner, key in zip(owners, keeper_ids)]
            audio = media_service.store(owners[0], identifier, io.BytesIO(wav_bytes()),
                                        kind="audio", media_format="wav")
            with sessions() as db:
                db.get(Media, audio).audio_source = "import"
                db.commit()
                image_jobs.save_description(db, owners[0], identifier, "Forêt de fiction", 1, 0)
                image_jobs.enqueue(db, owners[0], identifier, 1, 1)
                suggestion = emotions.enqueue(db, owners[0], identifier, 1, 0,
                                               parameters=FAKE_CONFIG)["id"]
            assert image_once(sessions, storage, FakeEngine())  # PNG fictif, aucun modèle IA.
            assert emotions.run_once(sessions, FakeEmotionProvider())
            with sessions() as db:
                meta = db.get(DreamEmotion, identifier)
                emotions.accept(db, owners[0], identifier, suggestion, meta.revision)
                target_media = list(db.scalars(select(Media).where(Media.dream_id == identifier)))
                media_ids = [row.id for row in target_media]
                keys = [row.storage_key for row in target_media]
                signatures = [(row.id, row.transcript, row.text_version)
                              for row in db.scalars(select(Dream).where(Dream.id.in_(keeper_ids))
                                                   .order_by(Dream.id))]
                keeper_jobs = [(row.id, row.status) for row in db.scalars(
                    select(Job).where(Job.dream_id.in_(keeper_ids)).order_by(Job.id))]
                users = [(row.id, row.email, row.password_hash) for row in db.scalars(
                    select(User).order_by(User.id))]
                session_ids = list(db.scalars(select(AuthSession.id).order_by(AuthSession.id)))
            expected = {}
            for media_id in media_ids:
                with media_service.download(owners[0], media_id).stream as stream:
                    expected[str(media_id)] = stream.read()
            for width, height in [(1280, 960), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                page.goto(origin + f"/reves/{identifier}")
                assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
                with page.expect_download() as pending:
                    page.get_by_role("button", name="Exporter ce rêve").click()
                downloaded = pending.value
                assert downloaded.failure() is None
                with ZipFile(downloaded.path()) as archive:
                    assert archive.testzip() is None
                    assert {"README.txt", "recit.txt", "reve.json", "manifest.json", "medias/"} <= (
                        set(archive.namelist()))
                    assert len(archive.namelist()) == 7
                    assert archive.read("recit.txt").decode() == text
                    data = json.loads(archive.read("reve.json"))
                    assert data["emotion"]["value"] == "heureux"
                    assert data["emotion"]["source"] == "accepted"
                    assert data["emotion"]["suggestion"]["stale"] is False
                    for entry in json.loads(archive.read("manifest.json"))["media"]:
                        content = archive.read(entry["archive_name"])
                        assert content == expected[entry["id"]]
                        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
                        assert entry["exported"]
                    public = "\n".join(archive.read(name).decode() for name in
                                       ["README.txt", "recit.txt", "reve.json", "manifest.json"])
                    for forbidden in [*tokens, *emails, *map(str, owners), str(storage.root),
                                      *keys, "DONNEE_AUTRE_REVE", "password_hash", "claim_token"]:
                        assert forbidden not in public
                downloaded.delete()
            report["zip_desktop_mobile_verified"] = True
            bearer = {"Authorization": "Bearer " + tokens[0]}
            foreign = {"Authorization": "Bearer " + tokens[1]}
            api = origin + f"/api/v1/dreams/{identifier}"
            assert context.request.get(api + "/export", headers=foreign).status == 404
            assert context.request.delete(api, headers=foreign).status == 404
            foreign_page = other_context.request.get(origin + f"/reves/{identifier}/supprimer")
            assert foreign_page.status == 404
            foreign_csrf = pages[1].locator('input[name="csrf"]').first.input_value()
            for action, fields in [
                ("supprimer", {"csrf": foreign_csrf, "confirmation": "supprimer"}),
                ("export", {"csrf": foreign_csrf}),
            ]:
                denied = other_context.request.post(origin + f"/reves/{identifier}/{action}",
                                                     form=fields, headers={"Origin": origin})
                assert denied.status == 404
            assert context.request.get(api + "/export").status == 401  # Cookie ≠ Bearer.
            bad_csrf = context.request.post(origin + f"/reves/{identifier}/supprimer",
                form={"csrf": "bad", "confirmation": "supprimer"}, headers={"Origin": origin})
            assert bad_csrf.status == 403
            assert context.request.post(origin + f"/reves/{identifier}/export",
                form={"csrf": "bad"}, headers={"Origin": origin}).status == 403
            report["isolation_csrf_bearer_verified"] = True
            with sessions() as db:
                stt_jobs.enqueue(db, owners[0], identifier, audio, 1)
                image_jobs.enqueue(db, owners[0], identifier, 1, 1)
                meta = db.get(DreamEmotion, identifier)
                emotions.enqueue(db, owners[0], identifier, 1, meta.revision,
                                 parameters=FAKE_CONFIG)
            stt_reservation = stt_jobs.claim(sessions, 30)
            image_reservation = image_jobs.claim(sessions)
            emotion_reservation = emotions.claim(sessions)
            assert stt_reservation and image_reservation and emotion_reservation
            page.set_viewport_size({"width": 1280, "height": 960})
            page.goto(origin + f"/reves/{identifier}")
            page.get_by_role("link", name="Supprimer ce rêve", exact=True).click()
            page.get_by_role("link", name="Annuler", exact=True).click()
            with sessions() as db:
                assert db.get(Dream, identifier).status != "deleted"
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("link", name="Supprimer ce rêve", exact=True).click()
            page.get_by_role("button", name="Confirmer la suppression").click()
            with sessions() as db:
                assert db.get(Dream, identifier).status != "deleted"
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="Confirmer la suppression").click()
            page.wait_for_url("**/mes-reves")
            assert page.locator(f'article[data-dream-id="{identifier}"]').count() == 0
            with sessions() as db:
                cancelled = list(db.scalars(select(Job).where(Job.dream_id == identifier)
                                           .where(Job.error_code == "dream_deleted")))
                assert len(cancelled) == 3
                assert all(row.status == "failed" and row.claim_token is None for row in cancelled)
                assert db.scalar(select(func.count()).select_from(EmotionAnalysis)) == 2
                assert db.scalar(select(func.count()).select_from(ImageGeneration)) == 2
            assert not emotions.finish(sessions, *emotion_reservation, error="provider_failed")
            with sessions() as db, pytest.raises(HTTPException):
                image_jobs.authorize_publication(db, owners[0], *image_reservation)
            for suffix in ["", "/recit", "/emotion", "/image", "/audio"]:
                assert context.request.get(origin + f"/reves/{identifier}{suffix}").status == 404
            assert context.request.get(api + "/export", headers=bearer).status == 404
            for media_id in media_ids:
                assert context.request.get(origin + f"/web/media/{media_id}/content").status == 404
            report["logical_deletion_and_late_results_verified"] = True

            def maintenance(*args):
                command = [sys.executable, str(ROOT / "scripts/dream_maintenance.py"), *args]
                outcome = subprocess.run(command, env=os.environ.copy(), capture_output=True,
                                         text=True, timeout=30)
                assert outcome.returncode == 0
                result = json.loads(outcome.stdout)
                for private in [*emails, *tokens, str(storage.root)]:
                    assert private not in outcome.stdout
                return result

            assert maintenance()["eligible"] == 1
            original_delete = storage.delete
            interrupted = []

            def interrupt(key, **kwargs):
                original_delete(key, **kwargs)
                interrupted.append(True)
                raise KeyboardInterrupt

            with monkeypatch.context() as patch:
                patch.setattr(storage, "delete", interrupt)
                with pytest.raises(KeyboardInterrupt):
                    DreamPurgeService(media_service).purge_one(owners[0], identifier)
            assert interrupted
            with sessions() as db:
                assert db.get(Dream, identifier).status == "deleted"
                assert all(row.storage_state == "deleting" for row in db.scalars(
                    select(Media).where(Media.dream_id == identifier)))
            assert maintenance("--apply", "--confirm-database", url.database)["purged"] == 1
            assert maintenance("--apply", "--confirm-database", url.database)["examined"] == 0
            with sessions() as db:
                assert db.get(Dream, identifier) is None
                assert db.get(DreamEmotion, identifier) is None
                assert db.get(ImageDescription, identifier) is None
                assert db.scalar(select(func.count()).select_from(EmotionAnalysis)) == 0
                assert db.scalar(select(func.count()).select_from(ImageGeneration)) == 0
                assert [(row.id, row.transcript, row.text_version) for row in db.scalars(
                    select(Dream).where(Dream.id.in_(keeper_ids)).order_by(Dream.id))] == signatures
                remaining_jobs = [(row.id, row.status)
                                  for row in db.scalars(select(Job).order_by(Job.id))]
                assert remaining_jobs == keeper_jobs
                assert [(row.id, row.email, row.password_hash) for row in db.scalars(
                    select(User).order_by(User.id))] == users
                remaining_sessions = list(db.scalars(
                    select(AuthSession.id).order_by(AuthSession.id)))
                assert remaining_sessions == session_ids
            assert all(storage.is_absent(key) for key in keys)
            for owner, media_id in zip(owners, keeper_media):
                with media_service.download(owner, media_id).stream as handle:
                    assert handle.read() == image_bytes()
            assert context.request.get(api + "/export", headers=bearer).status == 404
            report["purge_interrupted_resumed_idempotent_and_scope_verified"] = True
            assert not errors
            context.close()
            other_context.close()
            browser.close()
        (ROOT / "tmp").mkdir(exist_ok=True)
        (ROOT / "tmp/p10-final-recipe.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8",
        )
    finally:
        engine.dispose()
