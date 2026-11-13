"""Jobs STT sur PostgreSQL réel, fournisseur fictif exclusivement."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import session_factory
from backend.app.models import Dream, Job
from backend.app.services.stt_jobs import claim, run_once
from backend.app.stt_provider import STTError
from backend.app.web.security import SESSION_COOKIE
from backend.tests.audio_fixtures import audio_sample
from backend.tests.test_authentication import application_for
from backend.tests.test_media import media_environment as media_setup  # noqa: F401
from backend.tests.test_web import proof

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:8443"


class FakeProvider:
    """Réservé à cette suite : aucun import IA, coût ou requête réseau."""

    timeout = 30

    def __init__(self, output="Récit fictif : une lune bleue.", error=None, callback=None):
        self.output, self.error, self.callback = output, error, callback
        self.calls = 0

    def transcribe(self, audio):
        assert audio.startswith(b"RIFF")
        self.calls += 1
        if self.callback:
            self.callback()
        if self.error:
            raise STTError(self.error)
        return self.output


@pytest.fixture
def environment(request):
    env = request.getfixturevalue("media_setup")
    client, _, _, _, _, _, dream, owner, *_ = env
    response = client.post("/api/v1/dreams/audio", content=audio_sample("wav"), headers={
        **owner, "Content-Type": "application/octet-stream", "X-Audio-Format": "wav",
        "X-Audio-Source": "import",
    })
    assert response.status_code == 201
    data = response.json()
    return env, uuid.UUID(data["dream_id"]), uuid.UUID(data["media_id"])


def submit(environment, version=0):
    env, dream, media = environment
    return env[0].post(f"/api/v1/dreams/{dream}/transcriptions", headers=env[7], json={
        "media_id": str(media), "expected_version": version,
    })


def execute(environment, provider=None):
    env, *_ = environment
    return run_once(session_factory(env[1]), env[3], provider or FakeProvider())


def test_success_reload_editor_audio_and_safe_logs(environment, caplog):
    env, dream, media = environment
    client, engine, _, _, _, _, _, owner, *_ = env
    before = client.get(f"/api/v1/media/{media}/content", headers=owner).content
    response = submit(environment)
    assert response.status_code == 202 and response.json()["status"] == "pending"
    job = response.json()["id"]
    assert execute(environment)
    engine.dispose()
    status = client.get(f"/api/v1/transcriptions/{job}", headers=owner)
    assert status.json()["status"] == "completed" and status.json()["attempts"] == 1
    result = client.get(f"/api/v1/dreams/{dream}/transcript", headers=owner).json()
    assert result["transcript"] == FakeProvider().output and result["text_version"] == 1
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    assert FakeProvider().output in client.get(f"/reves/{dream}/recit").text
    assert client.get(f"/api/v1/media/{media}/content", headers=owner).content == before
    assert FakeProvider().output not in caplog.text
    assert "storage_key" not in status.text and "claim_token" not in status.text


@pytest.mark.parametrize("error", ["provider_failed", "timeout", "insufficient_memory",
                                   "model_unavailable", "secret-provider-detail"])
def test_provider_failures_are_safe(environment, error):
    env, dream, _ = environment
    identifier = submit(environment).json()["id"]
    execute(environment, FakeProvider(error=error))
    result = env[0].get(f"/api/v1/transcriptions/{identifier}", headers=env[7]).json()
    assert result["status"] == "failed"
    expected = error if error != "secret-provider-detail" else "provider_failed"
    assert result["error_code"] == expected
    with Session(env[1]) as db:
        assert db.get(Dream, dream).transcript is None


@pytest.mark.parametrize("output", ["", "   ", "a" * 20001, "a\x00b"])
def test_invalid_provider_text_is_not_saved(environment, output):
    env, dream, _ = environment
    identifier = submit(environment).json()["id"]
    execute(environment, FakeProvider(output=output))
    result = env[0].get(f"/api/v1/transcriptions/{identifier}", headers=env[7]).json()
    assert result["error_code"] == "invalid_text"
    with Session(env[1]) as db:
        assert db.get(Dream, dream).text_version == 0


def test_late_result_keeps_manual_correction(environment):
    env, dream, _ = environment
    identifier = submit(environment).json()["id"]

    def correct():
        assert env[0].patch(f"/api/v1/dreams/{dream}/transcript", headers=env[7], json={
            "transcript": "Correction manuelle fictive prioritaire.", "expected_version": 0,
        }).status_code == 200

    execute(environment, FakeProvider(callback=correct))
    result = env[0].get(f"/api/v1/transcriptions/{identifier}", headers=env[7]).json()
    assert result["error_code"] == "text_conflict"
    with Session(env[1]) as db:
        assert db.get(Dream, dream).transcript == "Correction manuelle fictive prioritaire."
        assert db.get(Dream, dream).text_version == 1


def test_preflight_conflict_avoids_provider(environment):
    env, dream, _ = environment
    submit(environment)
    env[0].patch(f"/api/v1/dreams/{dream}/transcript", headers=env[7], json={
        "transcript": "Correction fictive avant worker", "expected_version": 0,
    })
    fake = FakeProvider()
    execute(environment, fake)
    assert fake.calls == 0


def test_duplicate_requests_are_serialized(environment):
    env, dream, media = environment
    apps = [application_for(env[1]) for _ in range(2)]

    def send(index):
        with TestClient(apps[index]) as client:
            return client.post(f"/api/v1/dreams/{dream}/transcriptions", headers=env[7], json={
                "media_id": str(media), "expected_version": 0,
            }).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(send, range(2))) == [202, 409]
    assert execute(environment)
    assert not execute(environment)


def test_owner_uuid_auth_and_version_guards(environment):
    env, dream, media = environment
    client, _, _, _, _, _, other_dream, owner, other, _ = env
    path = f"/api/v1/dreams/{dream}/transcriptions"
    payload = {"media_id": str(media), "expected_version": 0}
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, headers=other, json=payload).status_code == 404
    assert client.post(f"/api/v1/dreams/{other_dream}/transcriptions", headers=owner,
                       json=payload).status_code == 404
    assert client.post(path, headers=owner, json={**payload, "media_id": str(uuid.uuid4())}
                       ).status_code == 404
    assert client.post(path, headers=owner, json={**payload, "expected_version": 4}
                       ).status_code == 409
    assert client.post(path, headers=owner, json={"media_id": str(media)}).status_code == 422
    identifier = submit(environment).json()["id"]
    status = f"/api/v1/transcriptions/{identifier}"
    assert client.get(status).status_code == 401
    assert client.get(status, headers=other).status_code == 404
    assert client.get(f"/api/v1/transcriptions/{uuid.uuid4()}", headers=owner).status_code == 404


def test_cookie_csrf_and_foreign_jobs(environment):
    env, dream, media = environment
    client, _, _, _, _, _, _, owner, other, _ = env
    path = f"/reves/{dream}/transcription"
    assert client.get(path, follow_redirects=False).status_code == 303
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    page = client.get(path)
    fields = {"csrf": proof(page), "media_id": str(media), "expected_version": "0"}
    assert client.post(path, data=fields).status_code == 403
    assert client.post(path, data={**fields, "csrf": "bad"}, headers={"Origin": ORIGIN}
                       ).status_code == 403
    response = client.post(path, data=fields, headers={"Origin": ORIGIN}, follow_redirects=False)
    assert response.status_code == 303
    with Session(env[1]) as db:
        identifier = db.scalar(select(Job.id).where(Job.dream_id == dream))
    status = f"{path}/{identifier}"
    assert client.get(status).json()["status"] == "pending"
    assert client.get(status).headers["cache-control"] == "no-store"
    client.cookies.set(SESSION_COOKIE, other["Authorization"].split()[1])
    assert client.get(path).status_code == 404
    assert client.get(status).status_code == 404


def test_restart_expired_lease_and_fencing(environment):
    env, dream, _ = environment
    identifier = uuid.UUID(submit(environment).json()["id"])
    sessions = session_factory(env[1])
    first = claim(sessions, 30)
    assert first[0] == identifier
    assert claim(sessions, 30) is None  # bail actif, pas de vol par un autre worker
    with sessions() as db:
        db.get(Job, identifier).lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    env[1].dispose()
    fake = FakeProvider()
    assert not execute(environment, fake)
    assert fake.calls == 0
    with sessions() as db:
        job = db.get(Job, identifier)
        assert job.status == "failed" and job.attempts == 1 and job.claim_token is None
        assert job.error_code == "interrupted"
        assert db.get(Dream, dream).text_version == 0


def test_stale_worker_cannot_publish(environment):
    env, dream, _ = environment
    identifier = uuid.UUID(submit(environment).json()["id"])

    def steal_after_expiry():
        with Session(env[1]) as db:
            db.get(Job, identifier).lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        claim(session_factory(env[1]), 30)

    execute(environment, FakeProvider(callback=steal_after_expiry))
    with Session(env[1]) as db:
        assert db.get(Job, identifier).attempts == 1
        assert db.get(Dream, dream).transcript is None


def test_three_interruptions_finish_failed(environment):
    env, _, _ = environment
    identifier = uuid.UUID(submit(environment).json()["id"])
    with Session(env[1]) as db:
        job = db.get(Job, identifier)
        job.status, job.attempts = "running", 3
        job.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert not execute(environment)
    with Session(env[1]) as db:
        job = db.get(Job, identifier)
        assert job.status == "failed" and job.error_code == "interrupted"


def test_purged_audio_does_not_get_transcribed(environment):
    env, dream, media = environment
    submit(environment)
    env[3].request_purge(env[4], media)
    fake = FakeProvider()
    execute(environment, fake)
    assert fake.calls == 0
    with Session(env[1]) as db:
        assert db.get(Dream, dream).transcript is None


def test_worker_entrypoint_with_fake_provider(environment, monkeypatch):
    from backend.app import stt_worker

    env, _, _ = environment
    identifier = uuid.UUID(submit(environment).json()["id"])
    fake = FakeProvider()
    monkeypatch.setattr("sys.argv", ["stt_worker", "--once"])
    monkeypatch.setattr(stt_worker, "make_engine", lambda: env[1])
    monkeypatch.setattr(stt_worker, "LocalWhisper", lambda _: fake)
    monkeypatch.setattr(stt_worker.LocalPrivateStorage, "from_environment", lambda: env[2])
    assert stt_worker.main() == 0
    assert fake.calls == 1
    with Session(env[1]) as db:
        assert db.get(Job, identifier).status == "done"
