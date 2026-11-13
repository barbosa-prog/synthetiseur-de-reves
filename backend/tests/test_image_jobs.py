"""P07 phase 2 sur PostgreSQL réel ; aucune IA ni fichier image."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.database import session_factory
from backend.app.models import Dream, ImageDescription, ImageGeneration, Job, User
from backend.app.services import image_jobs as images
from backend.app.services.transcripts import apply_correction

pytestmark = pytest.mark.integration


@pytest.fixture
def env(database):
    engine, _ = database
    sessions = session_factory(engine)
    with sessions() as db:
        owner = User(email="image-owner@example.test")
        other = User(email="image-other@example.test")
        db.add_all([owner, other])
        db.flush()
        dream = Dream(user_id=owner.id, transcript="Récit fictif français.", text_version=1)
        db.add(dream)
        db.commit()
        ids = owner.id, other.id, dream.id
    return engine, sessions, *ids


def description(env, value="Forêt fictive", version=0, text_version=1):
    _, sessions, owner, _, dream = env
    with sessions() as db:
        return images.save_description(db, owner, dream, value, text_version, version).version


def enqueue(env):
    _, sessions, owner, _, dream = env
    with sessions() as db:
        return images.enqueue(db, owner, dream, 1, 1).id


def test_migration_snapshot_reconnection_and_original_unchanged(env):
    engine, sessions, owner, _, dream = env
    assert {"image_descriptions", "image_generations"} <= set(inspect(engine).get_table_names())
    assert description(env) == 1
    identifier = enqueue(env)
    engine.dispose()
    with sessions() as db:
        snapshot = db.get(ImageGeneration, identifier)
        assert snapshot.user_id == owner
        assert snapshot.transcript == db.get(Dream, dream).transcript == "Récit fictif français."
        assert snapshot.description == "Forêt fictive"
        assert snapshot.parameters["steps"] == 20 and snapshot.parameters["safety_checker"] is True
        assert db.get(Job, identifier).expected_text_version == 1
        assert "description" not in images.projection(db, owner, identifier)


def test_description_optimistic_version_and_reconfirm_after_p06(env):
    _, sessions, owner, _, dream = env
    assert description(env) == 1
    assert description(env, version=1) == 1
    assert description(env, "Lune fictive", version=1) == 2
    with pytest.raises(HTTPException) as exc:
        description(env, version=1)
    assert exc.value.status_code == 409
    with sessions() as db:
        row = db.get(Dream, dream, with_for_update=True)
        apply_correction(db, row, "Autre récit fictif.", 1)
        db.commit()
    with sessions() as db, pytest.raises(HTTPException):
        images.enqueue(db, owner, dream, 2, 2)
    assert description(env, "Lune fictive", version=2, text_version=2) == 3


@pytest.mark.parametrize("operation", ["read", "write", "enqueue", "job", "cancel", "publish"])
def test_owner_checks(env, operation):
    _, sessions, _, other, dream = env
    description(env)
    identifier = enqueue(env)
    with sessions() as db, pytest.raises(HTTPException) as exc:
        if operation == "read":
            images.description_for(db, other, dream)
        elif operation == "write":
            images.save_description(db, other, dream, "Fictif", 1, 1)
        elif operation == "enqueue":
            images.enqueue(db, other, dream, 1, 1)
        elif operation == "job":
            images.projection(db, other, identifier)
        elif operation == "cancel":
            images.cancel(db, other, identifier)
        else:
            images.authorize_publication(db, other, identifier, uuid4())
    assert exc.value.status_code == 404


def test_concurrent_requests_and_claims(env):
    _, sessions, _, _, _ = env
    description(env)

    def submit(_):
        try:
            return enqueue(env)
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(2) as pool:
        outputs = list(pool.map(submit, range(2)))
    assert outputs.count(409) == 1
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: images.claim(sessions), range(2)))
    assert sum(result is not None for result in claims) == 1


@pytest.mark.parametrize("change", ["text", "description", "deleted"])
def test_stale_publication_refused_and_cleanup(env, change):
    _, sessions, owner, _, dream = env
    description(env)
    identifier = enqueue(env)
    _, token = images.claim(sessions)
    if change == "description":
        description(env, "Description modifiée", version=1)
    else:
        with sessions() as db:
            row = db.get(Dream, dream, with_for_update=True)
            if change == "text":
                apply_correction(db, row, "Correction fictive.", 1)
            else:
                row.status, row.deleted_at = "deleted", datetime.now(timezone.utc)
            db.commit()
    with sessions() as db, pytest.raises(HTTPException):
        images.authorize_publication(db, owner, identifier, token)
    with sessions() as db:
        job = db.get(Job, identifier)
        job.lease_until = datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert images.claim(sessions) is None
    with sessions() as db:
        assert db.get(Job, identifier).error_code == (
            "dream_deleted" if change == "deleted" else "interrupted")


def test_expiration_reclaim_old_token_and_max_attempts(env):
    _, sessions, owner, _, _ = env
    description(env)
    identifier = enqueue(env)
    _, old_token = images.claim(sessions)
    from backend.app.job_config import identity, image_parameters
    from backend.app.services.job_lifecycle import retry_job
    for attempt in (2, 3):
        with sessions() as db:
            db.get(Job, identifier).lease_until = datetime.now(timezone.utc)-timedelta(seconds=1)
            db.commit()
        assert images.claim(sessions) is None
        assert not images.fail(sessions, owner, identifier, old_token, "private detail")
        retry_job(sessions, owner, identifier, engine=identity(image_parameters()), explicit=True)
        _, token = images.claim(sessions)
        assert token != old_token
        with sessions() as db:
            assert db.get(Job, identifier).attempts == attempt
        old_token = token
    with sessions() as db:
        db.get(Job, identifier).lease_until = datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert images.claim(sessions) is None
    with pytest.raises(HTTPException):
        retry_job(sessions, owner, identifier, engine=identity(image_parameters()), explicit=True)


def test_publication_guard_keeps_dream_locked(env):
    _, sessions, owner, _, dream = env
    description(env)
    identifier = enqueue(env)
    _, token = images.claim(sessions)
    with sessions() as db:
        assert images.authorize_publication(db, owner, identifier, token).job_id == identifier
        with sessions() as contender:
            assert contender.scalar(select(Dream).where(Dream.id == dream)
                                     .with_for_update(skip_locked=True)) is None
        db.rollback()


def test_cancel_failure_redaction_and_stt_untouched(env):
    _, sessions, owner, _, dream = env
    description(env)
    identifier = enqueue(env)
    with sessions() as db:
        stt = Job(dream_id=dream, kind="stt")
        db.add(stt)
        db.commit()
        stt_id = stt.id
    _, token = images.claim(sessions)
    assert images.fail(sessions, owner, identifier, token, "secret/path")
    with sessions() as db:
        assert db.get(Job, identifier).error_code == "provider_failed"
        assert db.get(Job, stt_id).status == "queued"
    from backend.app.job_config import identity, image_parameters
    from backend.app.services.job_lifecycle import retry_job
    retry_job(sessions, owner, identifier, engine=identity(image_parameters()), explicit=True)
    with sessions() as db:
        images.cancel(db, owner, identifier)
        assert db.get(Job, identifier).error_code == "cancelled"


def test_database_constraints(env):
    _, sessions, owner, _, dream = env
    with sessions() as db, pytest.raises(IntegrityError):
        db.add(ImageDescription(dream_id=dream, description=" ", version=0, text_version=0))
        db.commit()
    description(env)
    enqueue(env)
    with sessions() as db, pytest.raises(IntegrityError):
        db.add(Job(dream_id=dream, kind="image"))
        db.commit()
    with sessions() as db:
        assert db.scalar(text("select version_num from alembic_version")) == "0010"
