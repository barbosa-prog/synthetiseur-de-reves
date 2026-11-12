"""Retrait transactionnel sur PostgreSQL temporaire ; fichiers fictifs conservés."""

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend.app.database import session_factory
from backend.app.media_routes import PrivateMediaResponse, private_response
from backend.app.models import Dream, DreamEmotion, Job, Media
from backend.app.services import emotions, image_jobs, stt_jobs
from backend.app.services.dream_deletion import delete_dream
from backend.app.services.export_zip import ZipExportService
from backend.app.services.media import MediaNotFound
from backend.app.web.security import SESSION_COOKIE
from backend.tests.test_emotion_contract import FakeEmotionProvider
from backend.tests.test_emotion_postgresql import FAKE_CONFIG
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_media import media_environment as media_setup
from backend.tests.test_media import store_image
from backend.tests.test_private_storage import image_bytes, wav_bytes
from backend.tests.test_stt import FakeProvider
from backend.tests.test_web import proof

media_environment = media_setup


@pytest.fixture
def env(media_environment, tmp_path):
    with Session(media_environment[1]) as db:
        dream = db.get(Dream, media_environment[6])
        dream.transcript, dream.text_version = "Un récit fictif.", 1
        db.commit()
    media_environment[0].app.state.export_root = tmp_path / "exports"
    return media_environment


def remove(env):
    with Session(env[1]) as db:
        delete_dream(db, env[4], env[6])


def test_atomic_retirement_idempotent_and_other_dream_preserved(env):
    image = store_image(env)
    with Session(env[1]) as db:
        other = Dream(user_id=env[4], transcript="Autre fiction conservée.", text_version=1)
        db.add(other)
        db.flush()
        other_id = other.id
        jobs = [Job(dream_id=env[6], kind=kind, status="running", attempts=1,
                    claim_token=uuid4(), lease_until=datetime.now(timezone.utc)+timedelta(hours=1))
                for kind in ["stt", "image", "emotion"]]
        db.add_all(jobs)
        db.flush()
        db.add(DreamEmotion(dream_id=env[6], active_request=jobs[2].id,
                            suggestion_id=jobs[2].id))
        db.commit()
        identifiers = [job.id for job in jobs]
    other_media = env[3].store(env[4], other_id, io.BytesIO(image_bytes()),
                               kind="image", media_format="png")
    response = env[0].delete(f"/api/v1/dreams/{env[6]}", headers=env[7])
    assert response.status_code == 204
    with Session(env[1]) as db:
        dream = db.get(Dream, env[6])
        when = dream.deleted_at
        assert dream.status == "deleted" and when is not None
        assert dream.transcript == "Un récit fictif."  # Effacement définitif : phase 4.
        for identifier in identifiers:
            job = db.get(Job, identifier)
            assert (job.status, job.error_code, job.claim_token, job.lease_until) == (
                "failed", "dream_deleted", None, None)
        media = db.get(Media, image)
        assert media.storage_state == "deleting" and media.purge_requested_at
        assert (env[2].root / media.storage_key).is_file()  # Pas de purge physique ici.
        meta = db.get(DreamEmotion, env[6])
        assert meta.active_request is meta.suggestion_id is None
        revision = meta.revision
        assert db.get(Dream, other_id).status != "deleted"
        assert db.get(Media, other_media).storage_state == "ready"
    assert env[0].delete(f"/api/v1/dreams/{env[6]}", headers=env[7]).status_code == 204
    with Session(env[1]) as db:
        assert db.get(Dream, env[6]).deleted_at == when
        assert db.get(DreamEmotion, env[6]).revision == revision
    assert env[0].get(f"/api/v1/media/{other_media}/content", headers=env[7]).status_code == 200


@pytest.mark.parametrize("mode", ["anonymous", "invalid", "other", "unknown"])
def test_unauthorized_deletion_does_not_disclose_or_modify(env, mode):
    headers = {} if mode == "anonymous" else (
        {"Authorization": "Bearer invalid"} if mode == "invalid" else (
            env[8] if mode == "other" else env[7]))
    response = env[0].delete(f"/api/v1/dreams/{uuid4() if mode == 'unknown' else env[6]}",
                              headers=headers)
    assert response.status_code == (401 if mode in {"anonymous", "invalid"} else 404)
    with Session(env[1]) as db:
        assert db.get(Dream, env[6]).status != "deleted"


def test_old_pages_mutations_jobs_media_and_exports_refused(env):
    media = store_image(env)
    env[0].cookies.set(SESSION_COOKIE, env[7]["Authorization"].split()[1])
    csrf = proof(env[0].get(f"/reves/{env[6]}"))
    with Session(env[1]) as db:
        jobs = [Job(dream_id=env[6], kind=kind) for kind in ["stt", "image", "emotion"]]
        db.add_all(jobs)
        db.commit()
        ids = [job.id for job in jobs]
    remove(env)
    paths = [f"/api/v1/dreams/{env[6]}", f"/api/v1/dreams/{env[6]}/transcript",
             f"/api/v1/dreams/{env[6]}/image-description", f"/api/v1/dreams/{env[6]}/emotion",
             f"/api/v1/dreams/{env[6]}/export", f"/api/v1/media/{media}/content",
             f"/api/v1/transcriptions/{ids[0]}", f"/api/v1/images/{ids[1]}",
             f"/api/v1/emotion-jobs/{ids[2]}", f"/web/media/{media}/content"]
    paths += [f"/reves/{env[6]}{suffix}" for suffix in
              ["", "/audio", "/transcription", "/recit", "/image", "/emotion", "/supprimer"]]
    for path in paths:
        assert env[0].get(path, headers=env[7]).status_code == 404, path
    updated = env[0].patch(f"/api/v1/dreams/{env[6]}", headers=env[7],
                           json={"emotion": "neutre", "expected_emotion_revision": 0})
    assert updated.status_code == 404
    assert env[0].post(f"/reves/{env[6]}/export", data={"csrf": csrf},
                       headers={"Origin": "https://localhost:8443"}).status_code == 404
    assert env[0].get("/api/v1/dreams", headers=env[7]).json()["total"] == 0


def test_web_confirmation_csrf_no_mutating_get_and_anonymous(env):
    path = f"/reves/{env[6]}/supprimer"
    assert env[0].get(path, follow_redirects=False).status_code == 303
    env[0].cookies.set(SESSION_COOKIE, env[7]["Authorization"].split()[1])
    page = env[0].get(path)
    assert page.status_code == 200
    data = {"csrf": proof(page), "confirmation": "supprimer"}
    assert env[0].post(path, data={**data, "csrf": "bad"},
                       headers={"Origin": "https://localhost:8443"}).status_code == 403
    assert env[0].post(path, data=data,
                       headers={"Origin": "https://evil.example"}).status_code == 403
    assert env[0].post(path, data={**data, "confirmation": "non"},
                       headers={"Origin": "https://localhost:8443"}).status_code == 422
    with Session(env[1]) as db:
        assert db.get(Dream, env[6]).status != "deleted"
    response = env[0].post(path, data=data, headers={"Origin": "https://localhost:8443"},
                           follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/mes-reves"


@pytest.mark.parametrize("kind", ["job", "dream", "media"])
def test_locked_row_returns_conflict_and_rolls_back_everything(env, kind):
    image = store_image(env)
    with Session(env[1]) as db:
        job = Job(dream_id=env[6], kind="image")
        db.add(job)
        db.commit()
        job_id = job.id
    with Session(env[1]) as holder:
        cls, identifier = {"job": (Job, job_id), "dream": (Dream, env[6]),
                           "media": (Media, image)}[kind]
        holder.scalar(select(cls).where(cls.id == identifier).with_for_update())
        with Session(env[1]) as db:
            with pytest.raises(HTTPException) as error:
                delete_dream(db, env[4], env[6])
            assert error.value.status_code == 409
        holder.rollback()
    with Session(env[1]) as db:
        assert db.get(Dream, env[6]).status != "deleted"
        assert db.get(Job, job_id).status == "queued"
        assert db.get(Media, image).storage_state == "ready"
    remove(env)


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_deletion_during_fake_worker_blocks_late_publication(env, kind):
    sessions = session_factory(env[1])
    if kind == "stt":
        audio = env[3].store(env[4], env[6], io.BytesIO(wav_bytes()),
                              kind="audio", media_format="wav")
        with sessions() as db:
            db.get(Media, audio).audio_source = "import"
            db.commit()
            job = stt_jobs.enqueue(db, env[4], env[6], audio, 1).id
        assert stt_jobs.run_once(sessions, env[3], FakeProvider(callback=lambda: remove(env)))
    elif kind == "image":
        from backend.app.services.image_execution import run_once
        with sessions() as db:
            image_jobs.save_description(db, env[4], env[6], "Forêt fictive", 1, 0)
            job = image_jobs.enqueue(db, env[4], env[6], 1, 1).id
        assert run_once(sessions, env[2], FakeEngine(callback=lambda: remove(env)))
    else:
        with sessions() as db:
            job = emotions.enqueue(db, env[4], env[6], 1, 0, parameters=FAKE_CONFIG)["id"]

        class Provider(FakeEmotionProvider):
            def analyze(self, request):
                remove(env)
                return super().analyze(request)

        assert emotions.run_once(sessions, Provider())
    with sessions() as db:
        row = db.get(Job, job)
        assert row.status == "failed" and row.error_code == "dream_deleted"
        assert row.claim_token is row.lease_until is None
        assert db.get(Dream, env[6]).transcript == "Un récit fictif."
        if kind == "image":
            assert row.media_id is None


@pytest.mark.parametrize("expired", [False, True])
def test_late_duplicate_and_expired_emotion_reservations(env, expired):
    sessions = session_factory(env[1])
    with sessions() as db:
        job = emotions.enqueue(db, env[4], env[6], 1, 0, parameters=FAKE_CONFIG)["id"]
    identifier, token = emotions.claim(sessions)
    if expired:
        with sessions() as db:
            db.get(Job, job).lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
    remove(env)
    for _ in range(2):
        assert not emotions.finish(sessions, identifier, token, error="provider_failed")
    assert emotions.claim(sessions) is None
    assert stt_jobs.claim(sessions, 30) is None
    assert image_jobs.claim(sessions) is None


def test_zip_in_progress_does_not_prevent_deletion_or_deliver_afterwards(env):
    store_image(env)
    service = ZipExportService(env[3], root=env[0].app.state.export_root)
    archive = service.build(env[4], env[6])
    remove(env)
    with pytest.raises(HTTPException):
        next(archive.chunks())
    assert not list(service.root.glob("export-*"))


def test_media_stream_stops_after_deletion_and_closes(env):
    media = store_image(env)
    response = private_response(env[3], env[4], media)
    assert isinstance(response, PrivateMediaResponse)

    async def scenario():
        assert await anext(response.body_iterator)
        remove(env)
        with pytest.raises(MediaNotFound):
            await anext(response.body_iterator)

    asyncio.run(scenario())
    assert response.private_stream.closed


def test_deletion_during_export_preparation_is_rejected(env, monkeypatch):
    store_image(env)
    service = ZipExportService(env[3], root=env[0].app.state.export_root)
    original = env[3].download

    def concurrent(*args, **kwargs):
        download = original(*args, **kwargs)
        remove(env)
        return download

    monkeypatch.setattr(env[3], "download", concurrent)
    with pytest.raises(HTTPException) as error:
        service.build(env[4], env[6])
    assert error.value.status_code == 404
    assert not list(service.root.glob("export-*"))


def test_race_two_deletions_are_safe(env):
    ready = Event()

    def action():
        ready.wait(5)
        try:
            remove(env)
            return 204
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(action), pool.submit(action)]
        ready.set()
        statuses = [r.result(timeout=10) for r in results]
    assert 204 in statuses and set(statuses) <= {204, 409}
    remove(env)


def test_legacy_media_never_interpreted_as_filesystem_path(env):
    with Session(env[1]) as db:
        legacy = Media(dream_id=env[6], kind="audio", storage_key="C:/private/arbitrary.wav",
                       storage_state="legacy")
        db.add(legacy)
        db.commit()
        identifier = legacy.id
    remove(env)
    with Session(env[1]) as db:
        assert db.get(Media, identifier).storage_state == "legacy"
        assert db.get(Dream, env[6]).deleted_at is not None


def test_job_inserted_between_inventory_and_dream_lock_is_invalidated(env):
    created = []

    def concurrent_insert(connection, cursor, statement, parameters, context, many):
        if not created and "FROM dreams" in statement and "FOR UPDATE NOWAIT" in statement:
            created.append(None)  # Empêche la récursion du listener.
            with Session(env[1]) as other:
                job = Job(dream_id=env[6], kind="emotion")
                other.add(job)
                other.commit()
                created[0] = job.id

    event.listen(env[1], "before_cursor_execute", concurrent_insert)
    try:
        remove(env)
    finally:
        event.remove(env[1], "before_cursor_execute", concurrent_insert)
    assert created and created[0]
    with Session(env[1]) as db:
        assert db.get(Job, created[0]).error_code == "dream_deleted"


def test_failure_after_flush_rolls_back_dream_jobs_and_media(env, monkeypatch):
    media = store_image(env)
    with Session(env[1]) as db:
        job = Job(dream_id=env[6], kind="stt")
        db.add(job)
        db.commit()
        identifier = job.id
    with Session(env[1]) as db:
        def failed_commit():
            db.flush()
            raise RuntimeError("Interruption fictive avant commit")
        monkeypatch.setattr(db, "commit", failed_commit)
        with pytest.raises(RuntimeError):
            delete_dream(db, env[4], env[6])
    with Session(env[1]) as db:
        assert db.get(Dream, env[6]).status != "deleted"
        assert db.get(Job, identifier).status == "queued"
        assert db.get(Media, media).storage_state == "ready"
