"""PostgreSQL réel, fichiers fictifs et routes privées P19."""

import io
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import ROOT, session_factory
from backend.app.models import Dream, Media
from backend.app.services.media import MediaNotFound, MediaService
from backend.app.storage.local import LocalPrivateStorage, StorageError, new_key
from backend.app.web.security import SESSION_COOKIE
from backend.tests.test_authentication import application_for, authorization, signup
from backend.tests.test_private_storage import image_bytes, wav_bytes

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:8443"


@pytest.fixture
def media_environment(database, tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_ORIGIN", ORIGIN)
    engine, config = database
    storage = LocalPrivateStorage(tmp_path / "private_media")
    service = MediaService(storage, session_factory(engine))
    app = application_for(engine)
    app.state.media_storage = storage
    with TestClient(app, base_url=ORIGIN) as client:
        alice = uuid.UUID(signup(client))
        bob = uuid.UUID(signup(client, "bob@example.com"))
        headers = authorization(client)
        other_headers = authorization(client, "bob@example.com")
        with Session(engine) as db:
            dream = Dream(user_id=alice)
            db.add(dream)
            db.commit()
            dream_id = dream.id
        yield client, engine, storage, service, alice, bob, dream_id, headers, other_headers, config


def store_image(environment):
    _, _, _, service, alice, _, dream, *_ = environment
    return service.store(alice, dream, io.BytesIO(image_bytes()), kind="image", media_format="png",
                         filename="fictitious.png")


def test_store_download_ownership_and_restart(media_environment):
    client, engine, storage, _, alice, bob, dream, owner, other, _ = media_environment
    identifier = store_image(media_environment)
    with Session(engine) as db:
        media = db.get(Media, identifier)
        assert media.dream_id == dream and media.dream.user_id == alice
        assert media.storage_state == "ready" and media.size_bytes == len(image_bytes())
        assert len(media.storage_key) == 64 and media.media_type == "image/png"
        key = media.storage_key
    engine.dispose()
    restarted = MediaService(LocalPrivateStorage(storage.root), session_factory(engine))
    download = restarted.download(alice, identifier)
    with download.stream:
        assert download.stream.read() == image_bytes()
    with pytest.raises(MediaNotFound):
        restarted.download(bob, identifier)
    path = f"/api/v1/media/{identifier}/content"
    response = client.get(path, headers=owner)
    assert response.status_code == 200 and response.content == image_bytes()
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]
    assert str(storage.root) not in str(response.headers) and key not in str(response.headers)
    assert client.get(path, headers=other).status_code == 404
    assert client.get(path).status_code == 401
    assert client.get(f"/api/v1/media/{uuid.uuid4()}/content", headers=owner).status_code == 404
    assert client.get("/api/v1/media/not-an-uuid/content", headers=owner).status_code == 422
    assert client.post(path, headers=owner).status_code == 405
    assert client.delete(path, headers=owner).status_code == 405


def test_cookie_routes_no_public_exposure(media_environment):
    client, engine, storage, _, _, _, _, owner, other, _ = media_environment
    identifier = store_image(media_environment)
    path = f"/web/media/{identifier}/content"
    assert client.get(path, follow_redirects=False).status_code == 303
    client.cookies.set(SESSION_COOKIE, other["Authorization"].split()[1])
    assert client.get(path).status_code == 404
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    response = client.get(path)
    assert response.status_code == 200 and response.content == image_bytes()
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert client.get(path, headers={"Host": "evil.example"}).status_code == 400
    with Session(engine) as db:
        key = db.get(Media, identifier).storage_key
    for public_path in [f"/static/{key}", f"/private_media/{key}", f"/media/{key}"]:
        assert client.get(public_path).status_code == 404
    assert not storage.root.is_relative_to(ROOT)


@pytest.mark.parametrize("case", ["expired", "deleted_dream", "missing", "corrupt", "legacy"])
def test_unavailable_media_is_not_exposed(media_environment, case):
    client, engine, storage, _, _, _, _, owner, *_ = media_environment
    identifier = store_image(media_environment)
    with Session(engine) as db:
        media = db.get(Media, identifier)
        if case == "expired":
            media.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif case == "deleted_dream":
            media.dream.status = "deleted"
            media.dream.deleted_at = datetime.now(timezone.utc)
        elif case == "missing":
            storage.delete(media.storage_key)
        elif case == "corrupt":
            payload = bytearray(image_bytes())
            payload[-1] ^= 1
            (storage.root / media.storage_key).write_bytes(payload)
        elif case == "legacy":
            media.storage_state, media.storage_key = "legacy", "../../fictitious-secret"
        db.commit()
    assert client.get(f"/api/v1/media/{identifier}/content", headers=owner).status_code == 404


def test_wrong_owner_cannot_store_or_purge(media_environment):
    _, _, storage, service, _, bob, dream, *_ = media_environment
    with pytest.raises(MediaNotFound):
        service.store(bob, dream, io.BytesIO(wav_bytes()), kind="audio", media_format="wav")
    assert storage.inventory() == []
    identifier = store_image(media_environment)
    with pytest.raises(MediaNotFound):
        service.request_purge(bob, identifier)
    assert len(storage.inventory()) == 1


def test_purge_idempotent_preserves_metadata(media_environment):
    client, engine, storage, service, alice, _, _, owner, *_ = media_environment
    identifier = store_image(media_environment)
    service.request_purge(alice, identifier)
    assert storage.inventory() == []
    assert client.get(f"/api/v1/media/{identifier}/content", headers=owner).status_code == 404
    service.request_purge(alice, identifier)
    with Session(engine) as db:
        media = db.get(Media, identifier)
        assert media.storage_state == "purged"
        assert media.purge_requested_at is not None and media.purged_at is not None


def test_failed_purge_is_inaccessible_and_resumable(media_environment, monkeypatch):
    client, engine, storage, service, alice, _, _, owner, *_ = media_environment
    identifier = store_image(media_environment)
    original = storage.delete

    def fail(*args, **kwargs):
        raise StorageError("Suppression temporairement indisponible.")

    monkeypatch.setattr(storage, "delete", fail)
    with pytest.raises(StorageError):
        service.request_purge(alice, identifier)
    with Session(engine) as db:
        assert db.get(Media, identifier).storage_state == "deleting"
    assert client.get(f"/api/v1/media/{identifier}/content", headers=owner).status_code == 404
    monkeypatch.setattr(storage, "delete", original)
    assert service.reconcile()["pending_purges"] == 1
    assert service.reconcile(apply=True)["cleaned"] == 1
    assert storage.inventory() == []


def test_orphan_reconciliation_dry_run_grace_and_safe_cleanup(media_environment):
    _, engine, storage, service, *_ = media_environment
    identifier = store_image(media_environment)
    orphan = new_key()
    storage.write(io.BytesIO(image_bytes()), key=orphan, kind="image", media_format="png")
    staging_key = new_key()
    staged = storage.root / f".{staging_key}.tmp"
    staged.write_bytes(b"fictitious interrupted write")
    assert service.reconcile(apply=True)["cleaned"] == 0
    old = time.time() - 90000
    os.utime(storage.root / orphan, (old, old))
    os.utime(staged, (old, old))
    unknown = storage.root / "do-not-delete.txt"
    unknown.write_text("fictitious unknown object")
    report = service.reconcile()
    assert report["orphan_files"] == 1 and report["staging_files"] == 1
    assert len(storage.inventory()) == 3 and unknown.exists()
    assert service.reconcile(apply=True)["cleaned"] == 2
    assert len(storage.inventory()) == 1 and unknown.exists()
    with Session(engine) as db:
        storage.delete(db.get(Media, identifier).storage_key)
    assert service.reconcile()["missing_files"] == 1


def test_database_failure_compensates_file(media_environment):
    _, engine, storage, _, alice, _, dream, *_ = media_environment

    class FailingCommit(Session):
        def commit(self):
            raise SQLAlchemyError("fictitious commit failure")

    service = MediaService(storage, sessionmaker(bind=engine, class_=FailingCommit))
    with pytest.raises(StorageError):
        service.store(alice, dream, io.BytesIO(image_bytes()), kind="image", media_format="png")
    assert storage.inventory() == []
    with Session(engine) as db:
        assert db.scalar(select(Media)) is None


def test_lost_commit_ack_does_not_remove_referenced_file(media_environment):
    _, engine, storage, original, alice, _, dream, *_ = media_environment

    class LostAcknowledgement(Session):
        def commit(self):
            super().commit()
            raise SQLAlchemyError("fictitious lost acknowledgement")

    service = MediaService(storage, sessionmaker(bind=engine, class_=LostAcknowledgement))
    with pytest.raises(StorageError):
        service.store(alice, dream, io.BytesIO(image_bytes()), kind="image", media_format="png")
    with Session(engine) as db:
        identifier = db.scalar(select(Media.id))
        assert identifier is not None
    assert len(storage.inventory()) == 1
    download = original.download(alice, identifier)
    with download.stream:
        assert download.stream.read() == image_bytes()


def test_migration_preserves_legacy_media(media_environment):
    _, engine, _, _, _, _, dream, *_, config = media_environment
    with engine.begin() as db:
        config.attributes["connection"] = db
        command.downgrade(config, "0002")
        identifier = uuid.uuid4()
        db.execute(text(
            "INSERT INTO media(id,dream_id,kind,storage_key) VALUES (:id,:dream,'audio',:key)"
        ), {"id": identifier, "dream": dream, "key": "legacy/fictitious.wav"})
        command.upgrade(config, "head")
    with Session(engine) as db:
        media = db.get(Media, identifier)
        assert media.storage_key == "legacy/fictitious.wav" and media.storage_state == "legacy"
        assert media.size_bytes is None and media.media_type is None


@pytest.mark.parametrize("field,value", [("size_bytes", -1), ("media_type", "text/html"),
                                       ("sha256", "invalid"), ("storage_key", "../bad"),
                                       ("storage_state", "invalid")])
def test_metadata_constraints(media_environment, field, value):
    _, engine, *_ = media_environment
    identifier = store_image(media_environment)
    with Session(engine) as db:
        setattr(db.get(Media, identifier), field, value)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
