"""P10 : effacement contrôlé sur PostgreSQL temporaire, médias fictifs seulement."""

import io
import json
import os
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from backend.app.database import session_factory
from backend.app.models import (
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
from backend.app.services import emotions, image_jobs, stt_jobs
from backend.app.services.dream_deletion import delete_dream
from backend.app.services.dream_purge import DreamPurgeService
from backend.app.services.export_zip import ZipExportService
from backend.app.storage.local import StorageError
from backend.tests.test_dream_deletion import env as deletion_environment
from backend.tests.test_emotion_contract import FakeEmotionProvider
from backend.tests.test_emotion_postgresql import FAKE_CONFIG
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_media import media_environment as media_setup
from backend.tests.test_private_storage import image_bytes, wav_bytes
from backend.tests.test_stt import FakeProvider

media_environment = media_setup
env = deletion_environment


def remove(env, identifier=None):
    with Session(env[1]) as db:
        delete_dream(db, env[4], identifier or env[6])


def service(env):
    return DreamPurgeService(env[3])


def add_image(env, dream=None):
    return env[3].store(env[4], dream or env[6], io.BytesIO(image_bytes()),
                        kind="image", media_format="png")


def complete_graph(env):
    sessions = session_factory(env[1])
    audio = env[3].store(env[4], env[6], io.BytesIO(wav_bytes()), kind="audio", media_format="wav")
    image = add_image(env)
    with sessions() as db:
        db.get(Media, audio).audio_source = "import"
        db.commit()
        stt = stt_jobs.enqueue(db, env[4], env[6], audio, 1).id
        image_jobs.save_description(db, env[4], env[6], "Description fictive privée", 1, 0)
        picture = image_jobs.enqueue(db, env[4], env[6], 1, 1).id
        emotion = emotions.enqueue(db, env[4], env[6], 1, 0, parameters=FAKE_CONFIG)["id"]
    assert emotions.run_once(sessions, FakeEmotionProvider())
    with sessions() as db:
        meta = db.get(DreamEmotion, env[6])
        emotions.accept(db, env[4], env[6], emotion, meta.revision)
        keys = [db.get(Media, identifier).storage_key for identifier in [audio, image]]
    return [stt, picture, emotion], [audio, image], keys


def test_complete_purge_preserves_other_dreams_users_and_sessions(env):
    jobs, media_ids, keys = complete_graph(env)
    with Session(env[1]) as db:
        survivors = [Dream(user_id=owner, transcript="AUTRE_FICTION", text_version=1)
                     for owner in [env[4], env[5]]]
        db.add_all(survivors)
        db.flush()
        survivor_ids = [row.id for row in survivors]
        other_job = Job(dream_id=survivor_ids[0], kind="image")
        db.add(other_job)
        db.commit()
        other_job_id = other_job.id
        users_before = db.scalar(select(func.count()).select_from(User))
        sessions_before = db.scalar(select(func.count()).select_from(AuthSession))
    other_media = add_image(env, survivor_ids[0])
    remove(env)
    assert service(env).purge_one(env[4], env[6]) == "purged"
    assert service(env).purge_one(env[4], env[6]) == "not_found"
    for key in keys:
        assert env[2].is_absent(key) and env[2].is_absent(key, temporary=True)
    with Session(env[1]) as db:
        assert db.get(Dream, env[6]) is None
        assert all(db.get(Job, identifier) is None for identifier in jobs)
        assert all(db.get(Media, identifier) is None for identifier in media_ids)
        assert db.get(DreamEmotion, env[6]) is None
        assert db.get(ImageDescription, env[6]) is None
        assert db.get(ImageGeneration, jobs[1]) is None
        assert db.get(EmotionAnalysis, jobs[2]) is None
        assert all(db.get(Dream, identifier).transcript == "AUTRE_FICTION"
                   for identifier in survivor_ids)
        assert db.get(Job, other_job_id).status == "queued"
        assert db.scalar(select(func.count()).select_from(User)) == users_before
        assert db.scalar(select(func.count()).select_from(AuthSession)) == sessions_before
    with env[3].download(env[4], other_media).stream as handle:
        assert handle.read() == image_bytes()
    for path in [f"/api/v1/dreams/{env[6]}", f"/api/v1/dreams/{env[6]}/export",
                 *[f"/api/v1/media/{identifier}/content" for identifier in media_ids]]:
        assert env[0].get(path, headers=env[7]).status_code == 404


def test_inventory_never_modifies_database_or_files(env):
    add_image(env)
    remove(env)
    statements = []

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(env[1], "before_cursor_execute", observe)
    try:
        report = service(env).run()
    finally:
        event.remove(env[1], "before_cursor_execute", observe)
    assert report["eligible"] == 1 and report["purged"] == 0
    assert not {"DELETE", "UPDATE", "INSERT"}.intersection(statements)
    with Session(env[1]) as db:
        row = db.scalar(select(Media).where(Media.dream_id == env[6]))
        assert row.storage_state == "deleting" and not env[2].is_absent(row.storage_key)


@pytest.mark.parametrize("mode", ["live", "other", "unknown"])
def test_only_deleted_dream_of_expected_owner_can_be_purged(env, mode):
    media = add_image(env)
    if mode != "live":
        remove(env)
    assert service(env).purge_one(env[5] if mode == "other" else env[4],
                                  uuid4() if mode == "unknown" else env[6]) == "not_found"
    with Session(env[1]) as db:
        row = db.get(Media, media)
        assert row is not None and not env[2].is_absent(row.storage_key)


@pytest.mark.parametrize("failure", ["crash", "commit"])
def test_resume_after_file_unlink_before_database_confirmation(env, monkeypatch, failure):
    _, ids, keys = complete_graph(env)
    remove(env)
    if failure == "crash":
        original = env[2].delete

        def crash(key, **kwargs):
            original(key, **kwargs)
            raise KeyboardInterrupt

        monkeypatch.setattr(env[2], "delete", crash)
        with pytest.raises(KeyboardInterrupt):
            service(env).purge_one(env[4], env[6])
    else:
        deleted = []

        def observed_delete(connection, cursor, statement, parameters, context, many):
            if statement.startswith("DELETE FROM dreams"):
                deleted.append(True)

        def fail_commit(db):
            if deleted:
                raise RuntimeError("Interruption fictive après fichiers")

        event.listen(env[1], "after_cursor_execute", observed_delete)
        event.listen(Session, "before_commit", fail_commit)
        try:
            with pytest.raises(RuntimeError):
                service(env).purge_one(env[4], env[6])
        finally:
            event.remove(Session, "before_commit", fail_commit)
            event.remove(env[1], "after_cursor_execute", observed_delete)
    monkeypatch.undo()
    with Session(env[1]) as db:
        assert db.get(Dream, env[6]).status == "deleted"
        assert all(db.get(Media, identifier).storage_state == "deleting" for identifier in ids)
    env[1].dispose()  # Connexions neuves pour la reprise.
    assert service(env).purge_one(env[4], env[6]) == "purged"
    assert all(env[2].is_absent(key) for key in keys)


@pytest.mark.parametrize("mode", ["missing", "permission", "noop"])
def test_missing_permission_error_and_false_delete_confirmation(env, monkeypatch, mode):
    identifier = add_image(env)
    remove(env)
    with Session(env[1]) as db:
        key = db.get(Media, identifier).storage_key
    if mode == "missing":
        env[2].delete(key)
    elif mode == "permission":
        monkeypatch.setattr(env[2], "delete", Mock(side_effect=PermissionError("PRIVATE_PATH")))
    else:
        monkeypatch.setattr(env[2], "delete", lambda *a, **k: None)
    result = service(env).purge_one(env[4], env[6])
    assert result == {"missing": "purged", "permission": "storage_failed",
                      "noop": "file_remaining"}[mode]
    if mode != "missing":
        with Session(env[1]) as db:
            assert db.get(Media, identifier).storage_state == "deleting"
            assert db.get(Dream, env[6]) is not None
        monkeypatch.undo()
        assert service(env).purge_one(env[4], env[6]) == "purged"


@pytest.mark.parametrize("case", ["foreign_job_media", "own_job_foreign_media", "foreign_meta",
                                 "own_meta_foreign_job", "image_owner", "emotion_owner"])
def test_cross_references_block_before_any_file_unlink(env, case, monkeypatch):
    jobs, _, keys = complete_graph(env)
    with Session(env[1]) as db:
        other = Dream(user_id=env[5], transcript="Autre récit privé.", text_version=1)
        db.add(other)
        db.flush()
        other_id = other.id
        foreign_media = Media(dream_id=other_id, kind="image", storage_state="legacy",
                              storage_key="FOREIGN_PRIVATE_FILE")
        foreign_job = Job(dream_id=other_id, kind="image")
        db.add_all([foreign_media, foreign_job])
        db.flush()
        own_media = db.scalar(select(Media).where(Media.dream_id == env[6]))
        if case == "foreign_job_media":
            foreign_job.media_id = own_media.id
        elif case == "own_job_foreign_media":
            db.get(Job, jobs[0]).media_id = foreign_media.id
        elif case == "foreign_meta":
            db.add(DreamEmotion(dream_id=other_id, active_request=jobs[2]))
        elif case == "own_meta_foreign_job":
            db.get(DreamEmotion, env[6]).active_request = foreign_job.id
        elif case == "image_owner":
            db.get(ImageGeneration, jobs[1]).user_id = env[5]
        else:
            db.get(EmotionAnalysis, jobs[2]).user_id = env[5]
        db.commit()
        # Pour ces données incohérentes : simule un ancien retrait sans réparation.
        row = db.get(Dream, env[6])
        row.status, row.deleted_at = "deleted", datetime.now(timezone.utc)
        db.commit()
    erase = Mock(wraps=env[2].delete)
    monkeypatch.setattr(env[2], "delete", erase)
    assert service(env).inspect(env[4], env[6]) == "cross_reference"
    assert service(env).purge_one(env[4], env[6]) == "cross_reference"
    erase.assert_not_called()
    assert all(not env[2].is_absent(key) for key in keys)
    with Session(env[1]) as db:
        assert db.get(Dream, other_id).transcript == "Autre récit privé."


@pytest.mark.parametrize("key", ["../outside", "C:/private/unknown.wav", "a" * 64])
def test_legacy_never_becomes_an_arbitrary_delete(env, key, monkeypatch):
    with Session(env[1]) as db:
        db.add(Media(dream_id=env[6], kind="audio", storage_key=key, storage_state="legacy"))
        db.commit()
    remove(env)
    erase = Mock(wraps=env[2].delete)
    monkeypatch.setattr(env[2], "delete", erase)
    assert service(env).purge_one(env[4], env[6]) == "legacy_media"
    erase.assert_not_called()


def test_file_reparse_refused_before_any_delete(env, monkeypatch):
    identifier = add_image(env)
    remove(env)
    with Session(env[1]) as db:
        key = db.get(Media, identifier).storage_key
    original = env[2].is_absent

    def dangerous(value, **kwargs):
        if value == key:
            raise StorageError("Objet de stockage refusé.")
        return original(value, **kwargs)

    monkeypatch.setattr(env[2], "is_absent", dangerous)
    erase = Mock(wraps=env[2].delete)
    monkeypatch.setattr(env[2], "delete", erase)
    assert service(env).purge_one(env[4], env[6]) == "storage_failed"
    erase.assert_not_called()


def test_busy_worker_or_media_lock_is_recoverable(env):
    jobs, ids, _ = complete_graph(env)
    remove(env)
    for cls, identifier in [(Job, jobs[0]), (Media, ids[0]), (Dream, env[6])]:
        with Session(env[1]) as holder:
            holder.scalar(select(cls).where(cls.id == identifier).with_for_update())
            assert service(env).purge_one(env[4], env[6]) == "busy"
            holder.rollback()
    assert service(env).purge_one(env[4], env[6]) == "purged"


def test_purge_does_not_wait_for_open_export(env):
    add_image(env)
    archive_service = ZipExportService(env[3], root=env[0].app.state.export_root)
    archive = archive_service.build(env[4], env[6])
    remove(env)
    assert service(env).purge_one(env[4], env[6]) == "purged"
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        next(archive.chunks())
    assert not list(archive_service.root.glob("export-*"))


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_fake_worker_returning_after_complete_purge_is_safe(env, kind):
    sessions = session_factory(env[1])

    def purge():
        remove(env)
        assert service(env).purge_one(env[4], env[6]) == "purged"

    if kind == "stt":
        audio = env[3].store(env[4], env[6], io.BytesIO(wav_bytes()),
                              kind="audio", media_format="wav")
        with sessions() as db:
            db.get(Media, audio).audio_source = "import"
            db.commit()
            stt_jobs.enqueue(db, env[4], env[6], audio, 1)
        assert stt_jobs.run_once(sessions, env[3], FakeProvider(callback=purge))
    elif kind == "image":
        from backend.app.services.image_execution import run_once
        with sessions() as db:
            image_jobs.save_description(db, env[4], env[6], "Image fictive", 1, 0)
            image_jobs.enqueue(db, env[4], env[6], 1, 1)
        assert run_once(sessions, env[2], FakeEngine(callback=purge))
    else:
        with sessions() as db:
            emotions.enqueue(db, env[4], env[6], 1, 0, parameters=FAKE_CONFIG)

        class Provider(FakeEmotionProvider):
            def analyze(self, request):
                purge()
                return super().analyze(request)

        assert emotions.run_once(sessions, Provider())
    with sessions() as db:
        assert db.get(Dream, env[6]) is None
        assert db.scalar(select(func.count()).select_from(Job)) == 0


def test_batch_limits_and_cli_never_uses_implicit_personal_database(monkeypatch, capsys):
    from scripts import dream_maintenance
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["dream_maintenance.py", "--apply"])
    engine = Mock()
    monkeypatch.setattr(dream_maintenance, "make_engine", engine)
    assert dream_maintenance.main() == 1
    engine.assert_not_called()
    assert "indisponible" in capsys.readouterr().out
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://fiction:fiction@127.0.0.1:5434/fiction")
    assert dream_maintenance.main() == 1  # --confirm-database est absent.
    engine.assert_not_called()
    monkeypatch.delenv("PRIVATE_MEDIA_ROOT", raising=False)
    monkeypatch.setattr("sys.argv", ["dream_maintenance.py", "--apply",
                                    "--confirm-database", "fiction"])
    assert dream_maintenance.main() == 1  # Aucun stockage personnel par défaut.
    engine.assert_not_called()


def test_batch_report_is_minimal_and_repeated_safe(env):
    add_image(env)
    remove(env)
    report = service(env).run(apply=True, limit=1)
    assert report["purged"] == 1 and report["blocked"] == 0
    assert service(env).run(apply=True)["examined"] == 0
    assert str(env[4]) not in json.dumps(report)
    assert str(env[2].root) not in json.dumps(report)
    for value in [0, 101, True]:
        with pytest.raises(ValueError):
            service(env).run(limit=value)


def test_absence_check_rejects_links_and_outside_key(tmp_path):
    from backend.app.storage.local import LocalPrivateStorage
    store = LocalPrivateStorage(tmp_path / "files")
    assert store.is_absent("a" * 64)
    with pytest.raises(StorageError):
        store.is_absent("../outside")
    key = store.write(io.BytesIO(image_bytes()), key="b" * 64, kind="image",
                      media_format="png").key
    os.link(store.root / key, tmp_path / "outside-link")
    with pytest.raises(StorageError):
        store.is_absent(key)


def test_open_media_download_cannot_turn_disk_failure_into_success(env):
    from backend.app.media_routes import private_response
    identifier = add_image(env)
    response = private_response(env[3], env[4], identifier)
    remove(env)
    try:
        # Windows peut refuser l'unlink d'un descripteur ouvert ; POSIX l'autorise.
        result = service(env).purge_one(env[4], env[6])
        assert result in {"purged", "storage_failed"}
        if result == "storage_failed":
            with Session(env[1]) as db:
                assert db.get(Media, identifier).storage_state == "deleting"
    finally:
        response.private_stream.close()
    assert service(env).purge_one(env[4], env[6]) in {"purged", "not_found"}
