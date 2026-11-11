"""Routes P04 et transactions sur PostgreSQL réel, sans voix personnelle."""

import uuid
from urllib.parse import quote

import pytest
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import ClientDisconnect, Request

from backend.app.audio_types import MAX_UPLOAD
from backend.app.models import Dream, Media
from backend.app.services.media import MediaService
from backend.app.storage.local import StorageError
from backend.app.web.security import SESSION_COOKIE
from backend.tests.audio_fixtures import audio_sample
from backend.tests.test_media import media_environment as media_setup  # noqa: F401
from backend.tests.test_web import proof

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:8443"


@pytest.fixture(name="media_environment")
def reuse_media_environment(request):
    """Réutilise la préparation P19 sans en copier les règles."""
    return request.getfixturevalue("media_setup")


def headers(owner, media_format="wav", source="import", filename=None):
    return {**owner, "X-Audio-Format": media_format, "X-Audio-Source": source,
            "X-Audio-Filename": quote(filename or ("fiction." + media_format)),
            "Content-Type": "application/octet-stream"}


def counts(engine):
    with Session(engine) as db:
        return (db.scalar(select(func.count()).select_from(Dream)),
                db.scalar(select(func.count()).select_from(Media)))


@pytest.mark.parametrize("media_format,source", [("wav", "import"), ("mp3", "import"),
                                             ("webm", "microphone"), ("ogg", "microphone"),
                                             ("mp4", "microphone")])
def test_successful_audio_upload_and_owner_isolation(media_environment, media_format, source):
    client, engine, storage, _, alice, _, _, owner, other, _ = media_environment
    before = counts(engine)
    response = client.post("/api/v1/dreams/audio", content=audio_sample(media_format),
                           headers=headers(owner, media_format, source))
    assert response.status_code == 201
    data = response.json()
    assert set(data) == {"dream_id", "media_id", "duration_ms", "sample_rate_hz", "channels",
                         "sample_count", "source_format", "source_size_bytes", "audio_source"}
    assert data["source_format"] == media_format and data["audio_source"] == source
    assert 900 <= data["duration_ms"] <= 1200 and data["sample_rate_hz"] == 16000
    assert counts(engine) == (before[0] + 1, before[1] + 1)
    with Session(engine) as db:
        dream = db.get(Dream, uuid.UUID(data["dream_id"]))
        media = db.get(Media, uuid.UUID(data["media_id"]))
        assert dream.user_id == alice and dream.status == "draft"
        assert dream.transcript is None and dream.emotion is None
        assert media.media_type == "audio/wav" and media.dream_id == dream.id
        assert media.sample_count > 0 and media.channels == 1
    assert str(storage.root) not in response.text and "storage_key" not in response.text
    path = f"/api/v1/media/{data['media_id']}/content"
    assert client.get(path, headers=owner).status_code == 200
    assert client.get(path, headers=other).status_code == 404
    assert client.patch(path, headers=other, content=b"change").status_code == 405


@pytest.mark.parametrize("payload,media_format,filename,expected", [
    (b"", "wav", "fiction.wav", 422),
    (b"not audio", "wav", "fiction.wav", 415),
    (b"ID3 no frames", "mp3", "fiction.mp3", 415),
    (b"<svg>bad</svg>", "wav", "fiction.wav", 415),
    (b"small", "wav", "../fiction.wav", 400),
    (b"small", "wav", "secret.wav:stream", 400),
    (b"small", "wav", "CON.wav", 400),
    (b"small", "webm", "fiction.webm", 415),
])
def test_bad_upload_creates_no_draft_or_file(media_environment, payload, media_format,
                                           filename, expected):
    client, engine, storage, _, _, _, _, owner, *_ = media_environment
    before = counts(engine)
    response = client.post("/api/v1/dreams/audio", content=payload,
                           headers=headers(owner, media_format, filename=filename))
    assert response.status_code == expected
    assert counts(engine) == before and storage.inventory() == []


def test_oversized_audio_refused(media_environment):
    client, engine, storage, _, _, _, _, owner, *_ = media_environment
    before = counts(engine)
    response = client.post("/api/v1/dreams/audio", content=bytes(MAX_UPLOAD + 1),
                           headers=headers(owner))
    assert response.status_code == 413 and counts(engine) == before
    assert storage.inventory() == []


def test_web_cookie_csrf_and_protected_pages(media_environment):
    client, engine, _, _, _, _, _, owner, other, _ = media_environment
    assert client.get("/nouveau-reve", follow_redirects=False).status_code == 303
    assert client.post("/api/v1/dreams/audio", content=audio_sample(),
                       headers=headers({})).status_code == 401
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    page = client.get("/nouveau-reve")
    assert page.status_code == 200 and "Racontez votre rêve." in page.text
    for token, origin in [("bad", ORIGIN), (proof(page), "https://evil.example")]:
        response = client.post("/web/audio", content=audio_sample(), headers={
            **headers({}), "X-CSRF-Token": token, "Origin": origin,
        })
        assert response.status_code == 403
    response = client.post("/web/audio", content=audio_sample(), headers={
        **headers({}), "X-CSRF-Token": proof(page), "Origin": ORIGIN,
    })
    assert response.status_code == 201
    data = response.json()
    confirmation = f"/reves/{data['dream_id']}/audio"
    assert client.get(confirmation).status_code == 200
    media_path = f"/web/media/{data['media_id']}/content"
    assert client.get(media_path).headers["content-disposition"].startswith("inline")
    client.cookies.set(SESSION_COOKIE, other["Authorization"].split()[1])
    assert client.get(confirmation).status_code == 404
    assert client.get(media_path).status_code == 404


def test_request_disconnect_rolls_back_upload(media_environment, monkeypatch):
    client, engine, storage, _, _, _, _, owner, *_ = media_environment
    original = Request.stream

    async def broken(self):
        if self.url.path == "/api/v1/dreams/audio":
            yield b"RIFF"
            raise ClientDisconnect
        async for chunk in original(self):
            yield chunk

    monkeypatch.setattr(Request, "stream", broken)
    before = counts(engine)
    response = client.post("/api/v1/dreams/audio", content=b"RIFF", headers=headers(owner))
    assert response.status_code == 408 and counts(engine) == before
    assert storage.inventory() == []


def test_draft_and_file_rollback_together(media_environment):
    _, engine, storage, _, alice, *_ = media_environment

    class FailedCommit(Session):
        def commit(self):
            raise SQLAlchemyError("fictitious database failure")

    import io

    service = MediaService(storage, sessionmaker(bind=engine, class_=FailedCommit))
    before = counts(engine)
    with pytest.raises(StorageError):
        service.store_audio_draft(alice, io.BytesIO(audio_sample()), {
            "duration_ms": 1000, "sample_rate_hz": 16000, "channels": 1, "sample_count": 16000,
            "source_format": "wav", "source_size_bytes": len(audio_sample()),
            "audio_source": "import",
        })
    assert counts(engine) == before and storage.inventory() == []


def test_migration_preserves_previous_media(media_environment):
    _, engine, _, service, alice, _, dream, *_, config = media_environment
    import io

    identifier = service.store(alice, dream, io.BytesIO(audio_sample()),
                               kind="audio", media_format="wav")
    with engine.begin() as db:
        config.attributes["connection"] = db
        command.downgrade(config, "0003")
        command.upgrade(config, "head")
    with Session(engine) as db:
        media = db.get(Media, identifier)
        assert media.storage_state == "ready" and media.duration_ms is None
