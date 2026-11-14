"""P16 : un compte, un rêve, sept étapes Chrome ; aucun moteur IA réel."""

import hashlib
import io
import json
import os
import re
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from backend.app.database import ROOT, make_engine, session_factory
from backend.app.models import (
    AIExecution,
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
from backend.app.services import emotions, image_execution, stt_jobs
from backend.app.services.dream_purge import DreamPurgeService
from backend.app.services.media import MediaService
from backend.app.storage.local import LocalPrivateStorage
from backend.app.web.security import SESSION_COOKIE
from backend.tests.browser_workers import wait_for_work
from backend.tests.test_emotion_web import complete_fake
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_stt import FakeProvider
from scripts.test_safety import validate_target

TRANSCRIPT = "Récit fictif : je marche sous une lune bleue."
CORRECTED = ("Récit fictif de démonstration : je marche dans une forêt lumineuse, "
             "sous une lune bleue. Je me sens heureux et apaisé.")
DESCRIPTION = "A fictional luminous forest under a blue moon, peaceful atmosphere"


@pytest.mark.browser
def test_seven_steps_in_one_chrome_session():
    # Une recette obligatoire ne doit jamais devenir verte par un skip.
    url = validate_target(os.environ)
    assert url.database == "p20_validation"
    origin = os.environ["WEB_TEST_URL"]
    assert os.environ["EMOTION_ENABLED"] == "1", "Utiliser verify_p20.py --p16-demo"
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    assert chrome.is_file(), "Chrome installé requis ; aucun téléchargement automatique"
    proof_root = "tmp/p16-demo" if os.getenv("CI", "").lower() == "true" else "docs/evidence/p16"
    proof = ROOT / proof_root / ("run-" + uuid4().hex[:12])
    proof.mkdir(parents=True, exist_ok=False)
    assets = []

    def capture(page, filename):
        target = proof / filename
        page.screenshot(path=str(target), full_page=True)
        with Image.open(target) as screenshot:
            width, height = screenshot.size
        assets.append(dict(file=filename, sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                           width=width, height=height))

    engine = make_engine(url)
    sessions = session_factory(engine)
    storage = LocalPrivateStorage.from_environment()
    service = MediaService(storage, sessions)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True,
                args=["--use-fake-device-for-media-stream"])
            # Exception autorisée pour cette recette, identique au contexte P14.
            # Aucune modification de TLS, cookies, CSRF ou origine en production.
            context = browser.new_context(ignore_https_errors=True,
                                          viewport={"width": 1280, "height": 960})
            try:
                context.grant_permissions(["microphone"], origin=origin)
                page = context.new_page()
                errors, uploads = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: uploads.append(request.method)
                        if request.url == origin + "/web/audio" else None)
                email = f"p16-fiction-{uuid4().hex[:12]}@example.com"
                page.goto(origin + "/inscription")
                page.get_by_label("Adresse e-mail").fill(email)
                page.get_by_label("Mot de passe", exact=True).fill(
                    "P16 fictional demonstration passphrase")
                page.get_by_role("button", name="Créer mon compte").click()
                page.wait_for_url("**/connexion?etat=inscrit")
                page.get_by_label("Adresse e-mail").fill(email)
                page.get_by_label("Mot de passe", exact=True).fill(
                    "P16 fictional demonstration passphrase")
                page.get_by_role("button", name="Me connecter").click()
                page.wait_for_url("**/accueil")
                with sessions() as db:
                    owner = db.scalar(select(User.id).where(User.email == email))
                    login_id = db.scalar(select(AuthSession.id).where(AuthSession.user_id == owner))
                assert owner is not None and login_id is not None
                initial_session = next(c for c in context.cookies() if c["name"] == SESSION_COOKIE)
                assert initial_session["secure"] and initial_session["httpOnly"]

                # 1. Vrai MediaRecorder, faux périphérique Chrome ; aucun micro humain.
                page.get_by_role("main").get_by_role(
                    "link", name="Capturer un rêve", exact=True).click()
                page.get_by_role("button", name="Démarrer l’enregistrement").click()
                expect(page.get_by_role("button", name="Arrêter", exact=True)).to_be_enabled()
                # Attendre la durée effectivement affichée du signal, pas un délai de polling.
                expect(page.locator("#recording-time")).to_have_text(
                    re.compile(r"00:(?:0[2-9]|[1-5][0-9])"))
                page.get_by_role("button", name="Arrêter", exact=True).click()
                expect(page.locator("#audio-review")).to_be_visible()
                assert uploads == [], "Aucun audio ne doit être envoyé avant confirmation"
                with page.expect_response(lambda response: response.url == origin + "/web/audio"
                                          and response.request.method == "POST") as saved:
                    page.get_by_role("button", name="Confirmer et enregistrer l’audio").click()
                assert saved.value.status == 201
                assert saved.value.request.headers["x-audio-source"] == "microphone"
                page.wait_for_url("**/reves/*/audio")
                dream_id = UUID(page.url.split("/reves/")[1].split("/")[0])
                base = origin + f"/reves/{dream_id}"
                audio_path = page.locator("#saved-audio").get_attribute("src")
                audio_response = context.request.get(origin + audio_path)
                assert audio_response.status == 200
                audio_bytes = audio_response.body()
                with wave.open(io.BytesIO(audio_bytes), "rb") as audio:
                    assert audio.getnchannels() == 1 and audio.getframerate() == 16000
                    assert audio.getnframes() >= 16000
                page.locator("#saved-audio").evaluate("audio => audio.play()")
                expect(page.locator("#saved-audio")).not_to_have_js_property("currentTime", 0)
                page.locator("#saved-audio").evaluate("audio => audio.pause()")
                with sessions() as db:
                    dream = db.get(Dream, dream_id)
                    assert dream.user_id == owner and dream.text_version == 0
                    audio_row = db.scalar(select(Media).where(Media.dream_id == dream_id))
                    assert audio_row.audio_source == "microphone"
                    audio_id = audio_row.id
                capture(page, "01-audio-fictif.png")

                # 2. Le formulaire crée le job réel ; seul le fournisseur est fictif.
                page.get_by_role("link", name="Transcrire l’audio en français").click()
                page.get_by_role("button", name="Lancer la transcription locale").click()
                expect(page.locator("#stt-status")).to_contain_text("En attente")
                provider = FakeProvider(output=TRANSCRIPT)
                assert wait_for_work(lambda: stt_jobs.run_once(sessions, service, provider))
                assert provider.calls == 1
                expect(page.locator("#stt-status")).to_contain_text("Transcription enregistrée")
                page.get_by_role("link", name="Ouvrir l’éditeur du récit").click()
                expect(page.get_by_label("Récit du rêve")).to_have_value(TRANSCRIPT)
                with sessions() as db:
                    assert db.get(Dream, dream_id).text_version == 1
                capture(page, "02-transcription-simulee.png")

                # 3. Correction par le navigateur, persistée et relue en version 2.
                page.get_by_label("Récit du rêve").fill(CORRECTED)
                page.get_by_role("button", name="Enregistrer le récit").click()
                page.wait_for_url("**/recit?enregistre=2")
                page.reload()
                expect(page.get_by_label("Récit du rêve")).to_have_value(CORRECTED)
                assert context.request.get(origin + audio_path).body() == audio_bytes
                capture(page, "03-recit-corrige.png")

                # 4. Description humaine puis PNG fictif via la publication réelle P07.
                page.get_by_role("link", name="Créer une image du rêve").click()
                page.get_by_label("Description visuelle").fill(DESCRIPTION)
                page.get_by_role("button", name="Enregistrer la description").click()
                page.get_by_role("button", name="Générer une image").click()
                expect(page.locator("#image-status")).to_contain_text("En attente")
                image_engine = FakeEngine()
                assert wait_for_work(lambda: image_execution.run_once(sessions, storage,
                                                                       image_engine))
                assert image_engine.calls == 1
                expect(page.locator("#image-status")).to_have_text("Image terminée.")
                expect(page.locator("#dream-image")).to_have_js_property("naturalWidth", 512)
                image_path = page.locator("#dream-image").get_attribute("src")
                image_response = context.request.get(origin + image_path)
                assert image_response.status == 200
                image_bytes = image_response.body()
                with Image.open(io.BytesIO(image_bytes)) as image:
                    assert image.format == "PNG" and image.size == (512, 512)
                capture(page, "04-image-simulee.png")

                # 5. Même rêve et même texte corrigé ; aucun choix automatique imposé.
                page.goto(base)
                page.get_by_role("link", name="Émotion", exact=True).click()
                expect(page.locator("#retained-emotion")).to_have_text("Non renseignée")
                page.get_by_role("button", name="Suggérer une émotion").click()
                expect(page.locator("#emotion-status")).to_contain_text("En attente")
                reservation = wait_for_work(lambda: emotions.claim(sessions))
                with sessions() as db:
                    assert db.get(Job, reservation[0]).dream_id == dream_id
                expect(page.locator("#emotion-status")).to_have_text("Analyse en cours…")
                assert complete_fake(sessions, reservation=reservation)
                expect(page.locator("#suggested-emotion")).to_have_text("Heureux")
                expect(page.locator("#retained-emotion")).to_have_text("Non renseignée")
                page.get_by_role("button", name="Accepter cette suggestion").click()
                expect(page.locator("#retained-emotion")).to_have_text("Heureux")
                expect(page.locator("#emotion-origin")).to_have_text("Suggestion acceptée")
                capture(page, "05-emotion-acceptee.png")

                # 6. Historique réel, filtre, détail et relecture après nouvelles connexions SQL.
                engine.dispose()
                page.get_by_role("link", name="Mes rêves", exact=True).click()
                page.get_by_label("Émotion", exact=True).select_option("heureux")
                page.get_by_role("button", name="Filtrer", exact=True).click()
                page.reload()
                card = page.locator(f'article[data-dream-id="{dream_id}"]')
                expect(card).to_contain_text(CORRECTED)
                expect(card).to_contain_text("Heureux")
                expect(page.locator("article[data-dream-id]")).to_have_count(1)
                capture(page, "06-historique.png")
                card.get_by_role("link", name="Ouvrir le rêve").click()
                assert page.url == base
                expect(page.locator("#current-dream-image")).to_have_js_property(
                    "naturalWidth", 512)
                assert context.request.get(origin + image_path).body() == image_bytes
                assert context.request.get(origin + audio_path).body() == audio_bytes
                with sessions() as db:
                    dream = db.get(Dream, dream_id)
                    assert (dream.user_id, dream.transcript, dream.text_version, dream.emotion) == (
                        owner, CORRECTED, 2, "heureux")
                    jobs = list(db.scalars(select(Job).where(Job.dream_id == dream_id)))
                    assert {job.kind for job in jobs} == {"stt", "image", "emotion"}
                    assert len(jobs) == 3
                    assert all(j.status == "done" and j.attempts == 1 for j in jobs)
                    job_ids = [job.id for job in jobs]
                    image_job = next(j for j in jobs if j.kind == "image")
                    emotion_job = next(j for j in jobs if j.kind == "emotion")
                    for cls, job in [(ImageGeneration, image_job), (EmotionAnalysis, emotion_job)]:
                        snapshot = db.get(cls, job.id)
                        assert snapshot.transcript == CORRECTED and snapshot.text_version == 2
                    assert db.get(EmotionAnalysis, emotion_job.id).result["emotion"] == "heureux"
                    assert db.get(DreamEmotion, dream_id).source == "accepted"
                    media = list(db.scalars(select(Media).where(Media.dream_id == dream_id)))
                    assert len(media) == 2 and {m.kind for m in media} == {"audio", "image"}
                    media_ids, keys = [m.id for m in media], [m.storage_key for m in media]
                    assert audio_id in media_ids and all(m.storage_state == "ready" for m in media)

                # 7a. Confirmation web ; retrait immédiat, fichiers encore en attente de purge.
                page.get_by_role("link", name="Supprimer ce rêve", exact=True).click()
                expect(page.get_by_role("heading", name="Supprimer ce rêve ?")).to_be_visible()
                capture(page, "07-suppression-confirmation.png")
                page.get_by_role("checkbox").check()
                page.get_by_role("button", name="Confirmer la suppression").click()
                page.wait_for_url("**/mes-reves")
                expect(page.locator("article[data-dream-id]")).to_have_count(0)
                with sessions() as db:
                    assert db.get(Dream, dream_id).status == "deleted"
                    assert db.get(Dream, dream_id).deleted_at is not None
                    assert all(db.get(Media, identifier).storage_state == "deleting"
                               for identifier in media_ids)
                assert all(not storage.is_absent(key) for key in keys)
                for suffix in ["", "/audio", "/recit", "/image", "/emotion"]:
                    assert context.request.get(base + suffix).status == 404
                for media_id in media_ids:
                    media_url = origin + f"/web/media/{media_id}/content"
                    assert context.request.get(media_url).status == 404

                # 7b. Maintenance P10 explicite, ciblée sur CE rêve supprimé seulement.
                purge = DreamPurgeService(service)
                assert purge.inspect(owner, dream_id) == "eligible"
                assert purge.purge_one(owner, dream_id) == "purged"
                assert purge.purge_one(owner, dream_id) == "not_found"
                with sessions() as db:
                    for cls in [Dream, DreamEmotion, ImageDescription]:
                        assert db.get(cls, dream_id) is None
                    assert list(db.scalars(select(Job).where(Job.dream_id == dream_id))) == []
                    assert list(db.scalars(select(Media).where(Media.dream_id == dream_id))) == []
                    for cls in [EmotionAnalysis, ImageGeneration]:
                        assert list(db.scalars(select(cls).where(cls.job_id.in_(job_ids)))) == []
                    assert db.get(User, owner) is not None
                    assert db.get(AuthSession, login_id).revoked_at is None
                    quota = list(db.scalars(select(AIExecution).where(
                        AIExecution.user_id == owner)))
                    assert len(quota) == 3 and all(event.job_id is None for event in quota)
                assert all(storage.is_absent(key) and storage.is_absent(key, temporary=True)
                           for key in keys)
                page.reload()
                expect(page.get_by_role("heading", name="Aucun rêve à afficher")).to_be_visible()
                capture(page, "08-historique-apres-purge.png")
                assert context.request.get(origin + "/web/session").status == 200
                final_session = next(c for c in context.cookies() if c["name"] == SESSION_COOKIE)
                assert final_session["value"] == initial_session["value"]
                assert len(context.pages) == 1 and uploads == ["POST"]
                assert not errors, "Erreur JavaScript dans la démonstration P16"
            finally:
                context.close()
                browser.close()
        # Liste blanche : aucune URL, identité, clé, cookie, token ou configuration SQL.
        report = dict(schema_version=1, result="passed", steps_completed=7,
                      captured_at_utc=datetime.now(timezone.utc).isoformat(),
                      audio="chrome-synthetic-device", ai="simulated-only",
                      tls="p14-test-context-exception-not-a-trust-validation",
                      same_session=True, same_dream=True, text_version=2,
                      successful_jobs=3, removed_media=2, physical_purge=True,
                      retained_account=True, retained_session=True, retained_quota_events=3,
                      screenshots=assets)
        (proof / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Preuves P16 : " + proof.relative_to(ROOT).as_posix())
    finally:
        engine.dispose()
