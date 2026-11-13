"""P11 PostgreSQL temporaire ; réservations/snapshots sans moteur réel."""

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from backend.app.database import session_factory
from backend.app.emotion_provider import EmotionResult
from backend.app.image_provider import ImageRequest
from backend.app.image_worker import ImageTask
from backend.app.job_rules import EngineIdentity
from backend.app.models import Dream, DreamEmotion, EmotionAnalysis, Job, Media, User
from backend.app.services import emotions, image_jobs, stt_jobs
from backend.app.services import job_lifecycle as lifecycle
from backend.app.services.dream_deletion import delete_dream
from backend.app.services.dream_purge import DreamPurgeService
from backend.app.services.image_execution import publish
from backend.app.services.job_maintenance import maintain
from backend.app.services.media import MediaService
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_private_storage import wav_bytes


@pytest.fixture
def env(database, tmp_path):
    engine, config = database
    sessions = session_factory(engine)
    storage = LocalPrivateStorage(tmp_path / "private")
    with sessions() as db:
        a, b = User(email="p11-a@example.com"), User(email="p11-b@example.com")
        db.add_all([a, b])
        db.flush()
        dream = Dream(user_id=a.id, transcript="Un récit fictif P11.", text_version=1)
        db.add(dream)
        db.commit()
        owner, other, identifier = a.id, b.id, dream.id
    media_service = MediaService(storage, sessions)
    media = media_service.store(owner, identifier, io.BytesIO(wav_bytes()),
                                kind="audio", media_format="wav")
    with sessions() as db:
        db.get(Media, media).audio_source = "import"
        db.commit()
        image_jobs.save_description(db, owner, identifier, "Forêt fictive P11", 1, 0)
    return engine, config, sessions, owner, other, identifier, media, media_service


def settings(kind):
    return (dict(engine="fake", width=512, height=512, steps=20, seed=42,
                 dtype="float16", device="cuda", safety_checker=True) if kind == "image"
            else dict(engine="fake", model_revision="1", parameters_revision="fixed"))


def identity(kind):
    digest = hashlib.sha256(json.dumps(settings(kind), sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    return EngineIdentity(engine="fake", model_revision="1", policy_revision="p11-test",
                          settings_digest=digest)


def create(env, kind="stt", **changes):
    kwargs = dict(engine=identity(kind), parameters=settings(kind), text_version=1, explicit=True)
    if kind == "stt":
        kwargs["media_id"] = env[6]
    elif kind == "image":
        kwargs["description_version"] = 1
        kwargs["media_service"] = env[7]
    else:
        with env[2]() as db:
            meta = db.get(DreamEmotion, env[5])
            kwargs["choice_revision"] = meta.revision if meta else 0
    return lifecycle.create(env[2], env[3], env[5], kind, **{**kwargs, **changes})


def reserve(env, job, kind="stt"):
    token = uuid4()
    lifecycle.reserve_job(env[2], env[3], job, engine=identity(kind), token=token)
    return token


def fail(env, job, error="provider_failed"):
    with env[2]() as db:
        row = db.get(Job, job)
        row.status, row.error_code = "failed", error
        row.claim_token = row.lease_until = None
        if row.kind == "emotion":
            db.get(DreamEmotion, env[5]).active_request = None
        db.commit()


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_retry_budgets_survive_reconnection_and_repeated_creations(env, kind):
    job = create(env, kind)
    for index in range(3):
        reserve(env, job, kind)
        fail(env, job)
        env[0].dispose()
        with pytest.raises(HTTPException):
            create(env, kind)
        if index < 2:
            retried = lifecycle.retry_job(env[2], env[3], job, engine=identity(kind), explicit=True)
            assert retried == job
    with pytest.raises(HTTPException):
        lifecycle.retry_job(env[2], env[3], job, engine=identity(kind), explicit=True)
    with env[2]() as db:
        row = db.get(Job, job)
        assert (row.attempts, row.retry_count) == (3, 2)
        assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_concurrent_retry_only_consumes_once(env):
    job = create(env)
    reserve(env, job)
    fail(env, job)
    event = Event()

    def action():
        event.wait(5)
        try:
            lifecycle.retry_job(env[2], env[3], job, engine=identity("stt"), explicit=True)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(action), pool.submit(action)]
        event.set()
        result = [f.result(timeout=10) for f in pending]
    assert sorted(result) == [200, 409]
    with env[2]() as db:
        assert db.get(Job, job).retry_count == 1


def test_concurrent_creations_and_duplicate_media_keep_one_cycle(env):
    media2 = env[7].store(env[3], env[5], io.BytesIO(wav_bytes()), kind="audio", media_format="wav")
    with env[2]() as db:
        db.get(Media, media2).audio_source = "import"
        db.commit()
    event = Event()

    def action(media):
        event.wait(5)
        try:
            return create(env, media_id=media)
        except HTTPException:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(action, value) for value in [env[6], media2]]
        event.set()
        values = [item.result(timeout=10) for item in pending]
    job = next(v for v in values if v is not None)
    fail(env, job)
    with pytest.raises(HTTPException):
        create(env, media_id=media2)
    with env[2]() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_successful_image_dedup_and_bounded_explicit_new_generation(env):
    jobs = []
    for index in range(3):
        job = create(env, "image", new_image=index > 0)
        token = reserve(env, job, "image")
        request = ImageRequest(description="Forêt fictive P11", text_version=1,
                               description_version=1)
        task = ImageTask(job, env[5], env[3], request)
        publish(env[2], env[7].storage, task, token, FakeEngine().generate(request))
        assert create(env, "image") == job
        jobs.append(job)
    assert len(set(jobs)) == 3
    with pytest.raises(HTTPException):
        create(env, "image", new_image=True)
    with env[2]() as db:
        assert sum(db.scalars(select(Job.attempts))) == 3
    # Une intention volontaire ne blanchit pas un échec.
    fail(env, jobs[-1])
    with pytest.raises(HTTPException):
        create(env, "image", new_image=True)


@pytest.mark.parametrize("cause", ["other", "deleted", "text", "engine", "safety"])
def test_retry_ownership_versions_and_nonretryable_errors(env, cause):
    job = create(env, "image")
    reserve(env, job, "image")
    fail(env, job, "safety_blocked" if cause == "safety" else "timeout")
    if cause in {"text", "deleted"}:
        with env[2]() as db:
            if cause == "text":
                db.get(Dream, env[5]).text_version = 2
            else:
                delete_dream(db, env[3], env[5])
            db.commit()
    approved = identity("image")
    if cause == "engine":
        approved = approved.model_copy(update={"model_revision": "changed"})
    with pytest.raises(HTTPException) as exc:
        lifecycle.retry_job(env[2], env[4] if cause == "other" else env[3], job,
                            engine=approved, explicit=True)
    assert exc.value.status_code == (404 if cause in {"other", "deleted"} else 409)


def test_existing_enqueue_and_claim_share_managed_cycle(env):
    job = create(env)
    with env[2]() as db, pytest.raises(HTTPException):
        stt_jobs.enqueue(db, env[3], env[5], env[6], 1)
    assert stt_jobs.claim(env[2], 30)[0] == job
    assert stt_jobs.claim(env[2], 30) is None
    assert image_jobs.claim(env[2]) is None
    assert emotions.claim(env[2]) is None
    with env[2]() as db:
        assert db.get(Job, job).attempts == 1


@pytest.mark.parametrize("running", [False, True])
def test_model_free_maintenance_expiry_restart_and_idempotence(env, running):
    job = create(env)
    if running:
        reserve(env, job)
    with env[2]() as db:
        row = db.get(Job, job)
        if running:
            row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        else:
            row.queued_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        db.commit()
    assert maintain(env[2])["candidates"] == 1
    env[0].dispose()
    assert maintain(env[2], apply=True)["failed"] == 1
    assert maintain(env[2], apply=True)["failed"] == 0
    with env[2]() as db:
        row = db.get(Job, job)
        assert row.status == "failed" and row.claim_token is row.lease_until is None
        assert row.error_code == ("interrupted" if running else "queue_timeout")


def test_two_maintenances_only_fail_once(env):
    job = create(env)
    with env[2]() as db:
        db.get(Job, job).queued_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: maintain(env[2], apply=True), [1, 2]))
    assert sum(r["failed"] for r in results) == 1


def test_emotion_expired_reservation_cannot_publish_or_overwrite_manual_choice(env):
    job = create(env, "emotion")
    token = reserve(env, job, "emotion")
    with env[2]() as db:
        row = db.get(EmotionAnalysis, job)
        result = EmotionResult(request_id=job, text_version=1, choice_revision=row.choice_revision,
                               emotion="heureux", engine="fake", model_revision="1")
        db.get(Dream, env[5]).emotion = "triste"
        db.get(Job, job).lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert maintain(env[2], apply=True)["failed"] == 1
    assert not emotions.finish(env[2], job, token, result)
    with env[2]() as db:
        assert db.get(Dream, env[5]).emotion == "triste"
        assert db.get(DreamEmotion, env[5]).active_request is None


def test_p10_purge_removes_managed_jobs_and_old_tokens_are_useless(env):
    job = create(env, "emotion")
    token = reserve(env, job, "emotion")
    with env[2]() as db:
        delete_dream(db, env[3], env[5])
    assert DreamPurgeService(env[7]).purge_one(env[3], env[5]) == "purged"
    assert not emotions.finish(env[2], job, token, error="provider_failed")
    with pytest.raises(HTTPException) as exc:
        lifecycle.retry_job(env[2], env[3], job, engine=identity("emotion"), explicit=True)
    assert exc.value.status_code == 404


def test_0009_legacy_roundtrip_and_old_sql_worker_compatibility(database):
    engine, config = database
    with engine.begin() as c:
        config.attributes["connection"] = c
        command.downgrade(config, "0008")
        owner, dream, job = uuid4(), uuid4(), uuid4()
        c.execute(text("INSERT INTO users(id,email) VALUES (:id,'legacy-p11@example.com')"),
                  {"id": owner})
        c.execute(text("INSERT INTO dreams(id,user_id) VALUES (:id,:owner)"),
                  {"id": dream, "owner": owner})
        c.execute(text("INSERT INTO jobs(id,dream_id,kind,attempts) VALUES (:id,:dream,'stt',2)"),
                  {"id": job, "dream": dream})
        before = c.execute(text("SELECT created_at,attempts,status FROM jobs WHERE id=:id"),
                           {"id": job}).one()
        command.upgrade(config, "0009")
        after = c.execute(text("SELECT created_at,attempts,status,queued_at,retry_count,cycle_key "
                               "FROM jobs WHERE id=:id"), {"id": job}).one()
        assert after[:3] == before and after[3] == before[0] and after[4:] == (0, None)
        # Ancien binaire : INSERT/UPDATE ne connaissant pas les nouveaux champs.
        c.execute(text("UPDATE jobs SET attempts=3,status='failed',error_code='interrupted' "
                       "WHERE id=:id"), {"id": job})
        c.execute(text("INSERT INTO jobs(dream_id,kind) VALUES (:id,'image')"), {"id": dream})
        command.downgrade(config, "0008")
        assert c.scalar(text("SELECT count(*) FROM jobs")) == 2
        command.upgrade(config, "0009")


def test_downgrade_refuses_to_discard_managed_history(env):
    create(env)
    with pytest.raises(DBAPIError), env[0].begin() as c:
        env[1].attributes["connection"] = c
        command.downgrade(env[1], "0008")
    with env[0].connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0010"


def test_completed_image_is_not_reused_when_private_file_is_missing(env):
    job = create(env, "image")
    token = reserve(env, job, "image")
    request = ImageRequest(description="Forêt fictive P11", text_version=1,
                           description_version=1)
    task = ImageTask(job, env[5], env[3], request)
    publish(env[2], env[7].storage, task, token, FakeEngine().generate(request))
    with env[2]() as db:
        media = db.get(Media, db.get(Job, job).media_id)
        env[7].storage.delete(media.storage_key)
    with pytest.raises(HTTPException) as exc:
        create(env, "image")
    assert exc.value.status_code == 409
    with env[2]() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_retry_rejects_changed_emotion_choice_and_image_description(env):
    emotion = create(env, "emotion")
    reserve(env, emotion, "emotion")
    fail(env, emotion)
    with env[2]() as db:
        db.get(DreamEmotion, env[5]).revision += 1
        db.commit()
    with pytest.raises(HTTPException):
        lifecycle.retry_job(env[2], env[3], emotion, engine=identity("emotion"), explicit=True)
    image = create(env, "image")
    reserve(env, image, "image")
    fail(env, image)
    from backend.app.models import ImageDescription
    with env[2]() as db:
        db.get(ImageDescription, env[5]).version += 1
        db.commit()
    with pytest.raises(HTTPException):
        lifecycle.retry_job(env[2], env[3], image, engine=identity("image"), explicit=True)


def test_live_reservation_and_recent_queue_are_not_recovered(env):
    job = create(env)
    assert maintain(env[2], apply=True)["candidates"] == 0
    token = reserve(env, job)
    assert maintain(env[2], apply=True)["candidates"] == 0
    with env[2]() as db:
        row = db.get(Job, job)
        assert row.status == "running" and row.claim_token == token and row.attempts == 1


@pytest.mark.parametrize("abstention", [False, True])
def test_emotion_success_and_abstention_are_reused_without_assigning_emotion(env, abstention):
    job = create(env, "emotion")
    token = reserve(env, job, "emotion")
    with env[2]() as db:
        revision = db.get(EmotionAnalysis, job).choice_revision
    result = EmotionResult(request_id=job, text_version=1, choice_revision=revision,
                           emotion=None if abstention else "heureux",
                           abstention_reason="ambiguous" if abstention else None,
                           engine="fake", model_revision="1")
    assert emotions.finish(env[2], job, token, result)
    assert create(env, "emotion") == job
    with env[2]() as db:
        row = db.get(Job, job)
        state = lifecycle.state_for(db, row, [row])
        assert state.outcome == ("abstention" if abstention else "result")
        assert row.attempts == 1 and db.get(Dream, env[5]).emotion is None
