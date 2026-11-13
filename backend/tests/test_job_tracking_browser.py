"""Chrome P11, réseau simulé et workers fictifs ; cluster temporaire prouvé avant accès."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from backend.app.database import ROOT, make_engine, session_factory
from backend.app.emotion_provider import EmotionError
from backend.app.models import Dream, Job, Media, User
from backend.app.services import emotions, stt_jobs
from backend.app.services import image_execution as images
from backend.app.services.media import MediaService
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.browser_workers import wait_for_work
from backend.tests.test_emotion_web import complete_fake
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_private_storage import wav_bytes
from backend.tests.test_stt import FakeProvider


@pytest.mark.browser
@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_job_retry_network_and_terminal_polling_in_chrome(kind):
    origin = os.getenv("WEB_TEST_URL")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not origin or not chrome.is_file():
        pytest.skip("Chrome et recette temporaire requis")
    if kind == "emotion" and os.getenv("EMOTION_ENABLED") != "1":
        pytest.skip("Utiliser --emotion-web-test pour le parcours émotion sans modèle")
    raw = os.environ.get("DATABASE_URL", "")
    assert raw == os.environ.get("TEST_DATABASE_URL")
    target = make_url(raw)
    assert target.database == "p20_validation" and target.port != 5434
    assert target.username.startswith("p20_") and target.host == "127.0.0.1"
    engine = make_engine(target)
    sessions = session_factory(engine)
    service = MediaService(LocalPrivateStorage.from_environment(), sessions)
    screenshots = ROOT / "tmp/p11-screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
            context = browser.new_context(ignore_https_errors=True,
                                          viewport={"width": 1280, "height": 960})
            page = context.new_page()
            errors = []
            posts = []
            reads = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: posts.append(request.url)
                    if request.method == "POST" else None)
            email = f"p11-browser-{uuid.uuid4().hex[:12]}@example.com"
            page.goto(origin + "/inscription")
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill("fictional P11 browser passphrase")
            page.get_by_role("button", name="Créer mon compte").click()
            page.wait_for_url("**/connexion?etat=inscrit")
            page.get_by_label("Adresse e-mail").fill(email)
            page.get_by_label("Mot de passe", exact=True).fill("fictional P11 browser passphrase")
            page.get_by_role("button", name="Me connecter").click()
            page.wait_for_url("**/accueil")
            with sessions() as db:
                owner = db.scalar(select(User.id).where(User.email == email))
                dream = Dream(user_id=owner, transcript="Une forêt entièrement fictive.",
                              text_version=1)
                db.add(dream)
                db.commit()
                dream_id = dream.id
            if kind == "stt":
                import io
                media = service.store(owner, dream_id, io.BytesIO(wav_bytes()),
                                      kind="audio", media_format="wav")
                with sessions() as db:
                    db.get(Media, media).audio_source = "import"
                    db.commit()
            stage = {"stt": "transcription", "image": "image", "emotion": "emotion"}[kind]
            path = f"/reves/{dream_id}/{stage}"
            page.goto(origin + path)
            if kind == "image":
                page.get_by_label("Description visuelle").fill("A fictional violet forest")
                page.get_by_role("button", name="Enregistrer la description").click()
            start = {"stt": "Lancer la transcription locale", "image": "Générer une image",
                     "emotion": "Suggérer une émotion"}[kind]
            page.get_by_role("button", name=start, exact=True).click()
            expect(page.locator("[data-job-canonical]")).to_have_text("En attente")
            with sessions() as db:
                job_id = db.scalar(select(Job.id).where(Job.dream_id == dream_id, Job.kind == kind))
            page.reload()
            with sessions() as db:
                assert db.scalar(select(func.count()).select_from(Job).where(
                    Job.dream_id == dream_id)) == 1
                assert db.get(Job, job_id).attempts == 0
            status_url = origin + (path + f"/{job_id}" if kind == "stt" else path + "/statut")
            page.on("request", lambda request: reads.append(request.url)
                    if request.url == status_url else None)
            # STT éprouve le délai AbortController de 8 s ; les autres éprouvent une coupure.
            page.route(status_url, lambda route: None if kind == "stt"
                       else route.abort("internetdisconnected"))
            before_posts = len(posts)
            expect(page.locator("[data-job-network]")).to_contain_text(
                "Suivi momentanément indisponible", timeout=12000)
            expect(page.locator("[data-job-canonical]")).to_have_text("En attente")
            assert len(posts) == before_posts
            with sessions() as db:
                assert db.get(Job, job_id).attempts == 0
            page.unroute(status_url)
            expect(page.locator("[data-job-network]")).to_be_hidden(timeout=10000)

            entered, release = Event(), Event()

            def hold():
                entered.set()
                assert release.wait(15)

            class FailedEmotion:
                def analyze(self, _):
                    hold()
                    raise EmotionError("timeout")

            def fail_once():
                if kind == "stt":
                    return stt_jobs.run_once(sessions, service,
                                             FakeProvider(callback=hold, error="timeout"))
                if kind == "image":
                    return images.run_once(sessions, service.storage,
                                           FakeEngine(callback=hold, error="timeout"))
                return emotions.run_once(sessions, FailedEmotion(), timeout=120)

            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(wait_for_work, fail_once)
                try:
                    assert entered.wait(5)
                    with sessions() as db:
                        assert db.get(Job, job_id).status == "running", (
                            "Le worker fictif ne traite pas le job de ce parcours")
                    response = context.request.get(status_url)
                    assert response.status == 200
                    progress = response.json()
                    assert progress["tracking"]["job_id"] == str(job_id)
                    assert progress["tracking"]["technical_state"] == "running"
                    assert progress["tracking"]["state_label"] == "En cours"
                    expect(page.locator("[data-job-canonical]")).to_have_text("En cours")
                finally:
                    release.set()
                assert future.result(timeout=10)
            expect(page.locator("[data-job-canonical]")).to_have_text("Échec", timeout=8000)
            retry = page.locator("[data-job-retry]")
            expect(retry).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
            page.screenshot(path=str(screenshots / f"{kind}-retry-mobile.png"), full_page=True)
            before_posts = len(posts)
            retry.get_by_role("button", name="Relancer le traitement").click()
            assert len(posts) == before_posts  # HTML required empêche la soumission non confirmée.
            retry.locator("input[type=checkbox]").check()
            retry.get_by_role("button", name="Relancer le traitement").click()
            expect(page.locator("[data-job-canonical]")).to_have_text("En attente")
            with sessions() as db:
                assert db.get(Job, job_id).retry_count == 1
                assert db.scalar(select(func.count()).select_from(Job).where(
                    Job.dream_id == dream_id)) == 1
            if kind == "stt":
                assert stt_jobs.run_once(sessions, service, FakeProvider())
            elif kind == "image":
                assert images.run_once(sessions, service.storage, FakeEngine())
            else:
                assert complete_fake(sessions, reservation=wait_for_work(
                    lambda: emotions.claim(sessions)))
            expect(page.locator("[data-job-canonical]")).to_have_text("Terminé", timeout=8000)
            expect(page.locator("[data-job-budget]")).to_contain_text("2 / 3")
            expect(page.locator("[data-job-budget]")).to_contain_text("1 / 2")
            terminal_reads = len(reads)
            page.wait_for_timeout(4500)
            assert len(reads) == terminal_reads
            # Retour de cache de navigation : une seule lecture, aucune nouvelle IA.
            page.evaluate(
                "window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}))")
            before_posts = len(posts)
            with page.expect_response(status_url):
                page.evaluate(
                    "window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))")
            assert len(posts) == before_posts
            if kind == "image":
                regenerate = page.locator("[data-job-regenerate]")
                expect(regenerate).to_be_visible()
                original = page.get_by_label("Description visuelle").input_value()
                page.get_by_label("Description visuelle").fill(original + " unsaved")
                expect(regenerate.get_by_role("button")).to_be_disabled()
                page.get_by_label("Description visuelle").fill(original)
                expect(regenerate.get_by_role("button")).to_be_enabled()
                regenerate.locator("input[type=checkbox]").check()
                regenerate.get_by_role("button").click()
                expect(page.locator("[data-job-canonical]")).to_have_text("En attente")
                assert images.run_once(sessions, service.storage, FakeEngine())
                expect(page.locator("[data-job-canonical]")).to_have_text("Terminé", timeout=8000)
                expect(page.locator("[data-job-budget]")).to_contain_text("3 / 3")
                expect(page.locator("[data-job-regenerate]")).to_be_hidden()
            page.set_viewport_size({"width": 1280, "height": 960})
            page.screenshot(path=str(screenshots / f"{kind}-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
            page.screenshot(path=str(screenshots / f"{kind}-mobile.png"), full_page=True)
            page.reload()
            expect(page.locator("[data-job-canonical]")).to_have_text("Terminé")
            with sessions() as db:
                assert db.get(Job, job_id).attempts == 2
            assert not errors
            context.close()
            browser.close()
    finally:
        engine.dispose()
