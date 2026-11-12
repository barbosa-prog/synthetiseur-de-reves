"""Publication réelle de PNG synthétiques sur PostgreSQL ; aucun GPU ni réseau IA."""

import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from backend.app.image_provider import ImageError, ImageRequest, ImageResult
from backend.app.image_worker import ImageTask
from backend.app.models import Dream, Job, Media
from backend.app.services import image_jobs
from backend.app.services.image_execution import current_image, publish, run_once
from backend.app.services.media import MediaNotFound, MediaService
from backend.app.services.transcripts import apply_correction
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.test_image_jobs import description, enqueue
from backend.tests.test_image_jobs import env as image_environment  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
def env(request):
    return request.getfixturevalue("image_environment")


@pytest.fixture
def storage(tmp_path):
    return LocalPrivateStorage(tmp_path / "private-media")


def png():
    stream = io.BytesIO()
    Image.new("RGB", (512, 512), "purple").save(stream, format="PNG")
    return stream.getvalue()


class FakeEngine:
    def __init__(self, callback=None, error=None):
        self.callback, self.error, self.calls = callback, error, 0

    def generate(self, request):
        self.calls += 1
        if self.callback:
            self.callback()
        if self.error:
            raise ImageError(self.error)
        return ImageResult(png(), request.text_version, request.description_version)


def test_success_private_owner_and_current_version(env, storage):
    engine, sessions, owner, other, dream = env
    description(env)
    identifier = enqueue(env)
    assert run_once(sessions, storage, FakeEngine())
    with sessions() as db:
        job = db.get(Job, identifier)
        media_id = current_image(db, owner, dream)
        assert job.status == "done" and job.media_id == media_id
        assert job.claim_token is None and job.lease_until is None
    engine.dispose()
    service = MediaService(storage, sessions)
    with service.download(owner, media_id).stream as handle:
        assert handle.read() == png()
    with pytest.raises(MediaNotFound):
        service.download(other, media_id)
    with sessions() as db, pytest.raises(HTTPException):
        current_image(db, other, dream)
    description(env, "Autre description", version=1)
    with sessions() as db:
        assert current_image(db, owner, dream) is None


@pytest.mark.parametrize("code", ["safety_blocked", "timeout", "insufficient_memory",
                                  "worker_stopped", "provider_failed"])
def test_failures_never_publish(env, storage, code):
    _, sessions, _, _, _ = env
    description(env)
    identifier = enqueue(env)
    provider = FakeEngine(error=code)
    run_once(sessions, storage, provider)
    with sessions() as db:
        assert db.get(Job, identifier).status == "failed"
        assert db.get(Job, identifier).error_code == code
        assert db.scalar(select(Media.id)) is None
    assert not storage.inventory() and provider.calls == 1


@pytest.mark.parametrize("change", ["text", "description", "cancel", "reclaim"])
def test_changes_during_generation_are_not_published(env, storage, change):
    _, sessions, owner, _, dream = env
    description(env)
    identifier = enqueue(env)

    def callback():
        if change == "description":
            description(env, "Une autre forêt", version=1)
        elif change == "reclaim":
            with sessions() as db:
                db.get(Job, identifier).lease_until = (
                    datetime.now(timezone.utc)-timedelta(seconds=1))
                db.commit()
            assert image_jobs.claim(sessions) is not None
        else:
            with sessions() as db:
                if change == "text":
                    row = db.get(Dream, dream, with_for_update=True)
                    apply_correction(db, row, "Correction fictive tardive.", 1)
                    db.commit()
                else:
                    image_jobs.cancel(db, owner, identifier)

    run_once(sessions, storage, FakeEngine(callback))
    with sessions() as db:
        assert db.get(Job, identifier).status != "done"
        assert db.scalar(select(Media.id)) is None
    assert not storage.inventory()


def reserved(env):
    _, sessions, owner, _, dream = env
    description(env)
    identifier = enqueue(env)
    _, token = image_jobs.claim(sessions)
    task = ImageTask(identifier, dream, owner, ImageRequest(description="Forêt fictive",
                     text_version=1, description_version=1))
    return task, token, ImageResult(png(), 1, 1)


def test_write_failure_after_physical_write_compensates(env, storage, monkeypatch):
    _, sessions, _, _, _ = env
    task, token, result = reserved(env)
    write = storage.write

    def broken(*a, **kw):
        write(*a, **kw)
        raise OSError("synthetic failure")

    monkeypatch.setattr(storage, "write", broken)
    with pytest.raises(OSError):
        publish(sessions, storage, task, token, result)
    assert not storage.inventory()
    with sessions() as db:
        assert db.scalar(select(Media.id)) is None


def test_commit_acknowledgment_lost_preserves_referenced_file(env, storage):
    _, sessions, owner, _, dream = env
    task, token, result = reserved(env)
    first = True

    def ambiguous_session():
        nonlocal first
        db = sessions()
        if first:
            first = False
            commit = db.commit

            def ambiguous_commit():
                commit()
                raise OSError("synthetic lost acknowledgment")

            db.commit = ambiguous_commit
        return db

    with pytest.raises(OSError):
        publish(ambiguous_session, storage, task, token, result)
    assert len(storage.inventory()) == 1
    with sessions() as db:
        assert current_image(db, owner, dream) is not None
        assert db.get(Job, task.job_id).status == "done"


def test_expired_during_write_is_compensated(env, storage, monkeypatch):
    _, sessions, _, _, _ = env
    task, token, result = reserved(env)
    authorize = image_jobs.authorize_publication
    calls = 0

    def expire(db, *args):
        nonlocal calls
        calls += 1
        if calls == 2:
            db.get(Job, task.job_id).lease_until = datetime.now(timezone.utc)-timedelta(seconds=1)
        return authorize(db, *args)

    monkeypatch.setattr(image_jobs, "authorize_publication", expire)
    with pytest.raises(HTTPException):
        publish(sessions, storage, task, token, result)
    assert not storage.inventory()
