"""ZIP réels et HTTP P10 ; PostgreSQL temporaire, fichiers exclusivement fictifs."""

import asyncio
import io
import json
import wave
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.export_contract import ExportError, ExportLimits
from backend.app.export_routes import ArchiveResponse
from backend.app.models import AuthSession, Dream, Media
from backend.app.security import token_digest
from backend.app.services.export_zip import Archive, BoundedWriter, ZipExportService
from backend.app.services.media import MediaIntegrityError
from backend.app.web.security import SESSION_COOKIE
from backend.tests.test_media import media_environment as base_environment
from backend.tests.test_media import store_image
from backend.tests.test_private_storage import image_bytes
from backend.tests.test_web import proof

media_environment = base_environment


@pytest.fixture
def zip_env(media_environment, tmp_path):
    client, engine, _, service, owner, _, dream, *_ = media_environment
    client.app.state.export_root = tmp_path / "exports"
    with Session(engine) as db:
        row = db.get(Dream, dream)
        row.transcript, row.text_version = "Une forêt fictive.", 1
        db.commit()
    return media_environment, ZipExportService(service, root=tmp_path / "exports")


def assert_clean(service):
    assert not list(service.root.glob("export-*"))


def test_real_zip_contents_and_cleanup(zip_env):
    env, service = zip_env
    identifier = store_image(env)
    client, _, storage, _, owner, _, dream, headers, *_ = env
    response = client.get(f"/api/v1/dreams/{dream}/export", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert str(storage.root) not in str(response.headers)
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "README.txt", "recit.txt", "reve.json", "manifest.json", "medias/",
            f"medias/image-{identifier}.png",
        }
        assert archive.read(f"medias/image-{identifier}.png") == image_bytes()
        assert archive.read("recit.txt").decode() == "Une forêt fictive."
        entry = json.loads(archive.read("manifest.json"))["media"][0]
        assert entry["availability"] == "verified" and entry["exported"]
        assert "storage_key" not in archive.read("reve.json").decode()
    assert_clean(service)
    # Le verrou ne reste pas détenu après téléchargement.
    again = service.build(owner, dream)
    again.close()
    assert_clean(service)


@pytest.mark.parametrize("action", ["missing", "corrupt"])
def test_missing_file_is_reported_corrupt_file_refused(zip_env, action):
    env, service = zip_env
    identifier = store_image(env)
    client, engine, storage, _, _, _, dream, headers, *_ = env
    with Session(engine) as db:
        key = db.get(Media, identifier).storage_key
    path = storage.root / key
    if action == "missing":
        path.unlink()
    else:
        path.write_bytes(b"tampered-fiction")
    response = client.get(f"/api/v1/dreams/{dream}/export", headers=headers)
    if action == "missing":
        assert response.status_code == 200
        with ZipFile(io.BytesIO(response.content)) as archive:
            entry = json.loads(archive.read("manifest.json"))["media"][0]
            assert entry["reason"] == "missing" and not entry["exported"]
            assert entry["archive_name"] not in archive.namelist()
    else:
        assert response.status_code == 409
        assert str(storage.root) not in response.text
    assert_clean(service)


@pytest.mark.parametrize("target", ["anonymous", "other", "unknown", "deleted"])
def test_api_isolation(zip_env, target):
    env, service = zip_env
    client, engine, _, _, _, _, dream, headers, other_headers, _ = env
    if target == "deleted":
        with Session(engine) as db:
            row = db.get(Dream, dream)
            row.status, row.deleted_at = "deleted", datetime.now(timezone.utc)
            db.commit()
    response = client.get(f"/api/v1/dreams/{uuid4() if target == 'unknown' else dream}/export",
                          headers={} if target == "anonymous" else (
                              other_headers if target == "other" else headers))
    assert response.status_code == (401 if target == "anonymous" else 404)
    assert_clean(service)


def test_web_session_csrf_and_bearer_transport_separation(zip_env):
    env, service = zip_env
    client, engine, _, _, _, _, dream, headers, *_ = env
    with Session(engine) as db:
        session = db.scalar(select(AuthSession).where(
            AuthSession.token_hash == token_digest(headers["Authorization"].split()[1])))
        assert session
    client.cookies.set(SESSION_COOKIE, headers["Authorization"].split()[1])
    page = client.get(f"/reves/{dream}")
    assert "Exporter ce rêve" in page.text
    data = {"csrf": proof(page)}
    url = f"/reves/{dream}/export"
    assert client.post(url, data={"csrf": "bad"},
                       headers={"Origin": "https://localhost:8443"}).status_code == 403
    assert client.post(url, data=data,
                       headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get(f"/api/v1/dreams/{dream}/export").status_code == 401
    response = client.post(url, data=data, headers={"Origin": "https://localhost:8443"})
    assert response.status_code == 200
    assert ZipFile(io.BytesIO(response.content)).read("recit.txt").decode() == "Une forêt fictive."
    assert_clean(service)


def test_single_export_and_release_on_abandoned_download(zip_env):
    env, service = zip_env
    archive = service.build(env[4], env[6])
    with pytest.raises(ExportError, match="export_busy"):
        service.build(env[4], env[6])
    iterator = archive.chunks()
    assert next(iterator).startswith(b"PK")
    iterator.close()
    assert_clean(service)
    service.build(env[4], env[6]).close()


def test_deletion_during_preparation_aborts_delivery(zip_env, monkeypatch):
    env, service = zip_env
    store_image(env)
    original = service.media.download

    def delete_during_read(*args, **kwargs):
        result = original(*args, **kwargs)
        with Session(env[1]) as db:
            row = db.get(Dream, env[6])
            row.status, row.deleted_at = "deleted", datetime.now(timezone.utc)
            db.commit()
        return result

    monkeypatch.setattr(service.media, "download", delete_during_read)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        service.build(env[4], env[6])
    assert error.value.status_code == 404
    assert_clean(service)


def test_deletion_after_build_and_session_revocation_stop_stream(zip_env):
    env, service = zip_env
    for mode in ["session", "deleted"]:
        archive = service.build(env[4], env[6])
        with Session(env[1]) as db:
            auth = db.scalar(select(AuthSession).where(
                AuthSession.token_hash == token_digest(env[7]["Authorization"].split()[1])))
            session_id = auth.id
            if mode == "session":
                auth.revoked_at = datetime.now(timezone.utc)
            else:
                row = db.get(Dream, env[6])
                row.status, row.deleted_at = "deleted", datetime.now(timezone.utc)
            db.commit()
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            next(archive.chunks(session_id))
        assert_clean(service)


@pytest.mark.parametrize("failure", ["disk", "timeout", "integrity"])
def test_failure_cleanup(zip_env, monkeypatch, failure):
    env, service = zip_env
    store_image(env)
    if failure == "disk":
        monkeypatch.setattr("backend.app.services.export_zip.shutil.disk_usage",
                            lambda _: SimpleNamespace(free=1))
    elif failure == "timeout":
        def expired(_):
            raise ExportError("export_timeout")
        monkeypatch.setattr(Archive, "checkpoint", expired)
    else:
        def invalid(*args, **kwargs):
            raise MediaIntegrityError
        monkeypatch.setattr(service.media, "download", invalid)
    with pytest.raises(ExportError):
        service.build(env[4], env[6])
    assert_clean(service)


def test_large_metadata_and_quantity_rejected(zip_env):
    env, service = zip_env
    with Session(env[1]) as db:
        db.add_all([Media(dream_id=env[6], kind="audio", storage_key=f"fiction-{i}",
                          size_bytes=15 * 1024**2, storage_state="legacy") for i in range(7)])
        db.commit()
    with pytest.raises(ExportError, match="export_too_large"):
        service.build(env[4], env[6])
    with Session(env[1]) as db:
        for row in db.scalars(select(Media).where(Media.dream_id == env[6])):
            row.size_bytes = None
        db.add_all([Media(dream_id=env[6], kind="audio", storage_key=f"extra-{i}",
                          storage_state="legacy") for i in range(94)])
        db.commit()
    with pytest.raises(ExportError, match="too_many_media"):
        service.build(env[4], env[6])
    assert_clean(service)


def test_bounded_zip_writer_limits_actual_disk_bytes():
    sink = io.BytesIO()
    writer = BoundedWriter(sink, 4, lambda: None)
    writer.write(b"1234")
    with pytest.raises(ExportError, match="export_too_large"):
        writer.write(b"5")
    assert len(sink.getvalue()) == 4


def test_reject_root_in_repository(zip_env):
    from backend.app.database import ROOT
    from backend.app.storage.local import StorageError
    env, service = zip_env
    service.root = ROOT / "tmp/forbidden-exports"
    with pytest.raises(StorageError):
        service.build(env[4], env[6])
    assert not Path(service.root).exists()


def test_disconnect_before_first_chunk_cleans_archive(zip_env):
    from starlette.requests import ClientDisconnect
    env, service = zip_env
    archive = service.build(env[4], env[6])
    response = ArchiveResponse(archive, None)

    async def disconnected_send(message):
        raise OSError("Client fictif déconnecté")

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(ClientDisconnect):
        asyncio.run(response({"type": "http", "asgi": {"spec_version": "2.4"}},
                             receive, disconnected_send))
    assert_clean(service)
    service.build(env[4], env[6]).close()


def test_no_other_dream_in_archive(zip_env):
    env, service = zip_env
    with Session(env[1]) as db:
        other = Dream(user_id=env[4], transcript="AUTRE_REVE_EXCLU", text_version=1)
        db.add(other)
        db.commit()
        other_id = other.id
    identifier = service.media.store(env[4], other_id, io.BytesIO(image_bytes()),
                                     kind="image", media_format="png")
    archive = service.build(env[4], env[6])
    try:
        with ZipFile(archive.path) as content:
            assert str(identifier) not in str(content.namelist())
            assert "AUTRE_REVE_EXCLU" not in content.read("reve.json").decode()
    finally:
        archive.close()


def test_delivery_timeout_and_cleanup(zip_env, monkeypatch):
    env, service = zip_env
    archive = service.build(env[4], env[6])
    monkeypatch.setattr("backend.app.services.export_zip.DELIVERY_SECONDS", -1)
    with pytest.raises(ExportError, match="export_timeout"):
        next(archive.chunks())
    assert_clean(service)


def test_reject_root_overlapping_private_media(zip_env):
    from backend.app.storage.local import StorageError
    env, service = zip_env
    identifier = store_image(env)
    service.root = env[2].root
    with pytest.raises(StorageError):
        service.build(env[4], env[6])
    with service.media.download(env[4], identifier).stream as original:
        assert original.read() == image_bytes()


def test_web_busy_error_keeps_authenticated_navigation(zip_env):
    env, service = zip_env
    client = env[0]
    client.cookies.set(SESSION_COOKIE, env[7]["Authorization"].split()[1])
    page = client.get(f"/reves/{env[6]}")
    archive = service.build(env[4], env[6])
    try:
        response = client.post(f"/reves/{env[6]}/export", data={"csrf": proof(page)},
                               headers={"Origin": "https://localhost:8443"})
        assert response.status_code == 409
        assert "Un export est déjà en cours" in response.text
        assert "Mes rêves" in response.text
        assert str(service.root) not in response.text
    finally:
        archive.close()


def test_real_audio_larger_than_configured_budget(zip_env):
    env, service = zip_env
    audio = io.BytesIO()
    with wave.open(audio, "wb") as sample:
        sample.setnchannels(1)
        sample.setsampwidth(2)
        sample.setframerate(16000)
        sample.writeframes(b"\x00\x00" * 300000)
    service.media.store(env[4], env[6], io.BytesIO(audio.getvalue()),
                        kind="audio", media_format="wav")
    service.limits = ExportLimits(max_bytes=512 * 1024)
    with pytest.raises(ExportError, match="export_too_large"):
        service.build(env[4], env[6])
    assert_clean(service)


def test_cleanup_error_is_generic_and_releases_lock(zip_env, monkeypatch):
    env, service = zip_env
    archive = service.build(env[4], env[6])
    original = archive.directory.cleanup

    def failed_cleanup():
        raise PermissionError("PRIVATE_PATH_MUST_NOT_LEAK")

    monkeypatch.setattr(archive.directory, "cleanup", failed_cleanup)
    with pytest.raises(ExportError, match="^cleanup_failed$") as error:
        archive.close()
    assert "PRIVATE_PATH" not in str(error.value)
    assert archive.connection is None
    # Le verrou est libéré malgré l'échec ; le résidu fictif est ensuite nettoyé.
    again = service.build(env[4], env[6])
    again.close()
    original()
    archive.directory = None
    assert_clean(service)
