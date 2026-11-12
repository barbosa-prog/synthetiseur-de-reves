"""P10 : uniquement données fictives et PostgreSQL temporaire fourni par database."""

import hashlib
import io
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.database import session_factory
from backend.app.export_contract import (
    ROOT_FILES,
    ExportError,
    ExportLimits,
    check_integrity,
    media_name,
)
from backend.app.models import (
    Dream,
    DreamEmotion,
    EmotionAnalysis,
    ImageDescription,
    ImageGeneration,
    Job,
    Media,
    User,
)
from backend.app.services.exports import revalidate_export, select_export


def test_contract_names_and_limits(monkeypatch):
    identifier = uuid4()
    assert media_name(identifier, "audio", "audio/wav") == f"medias/audio-{identifier}.wav"
    for kind, mime in [("../secret", "audio/wav"), ("audio", "image/png"),
                       ("image", "../../secret"), ("image", "image/svg+xml")]:
        with pytest.raises(ExportError):
            media_name(identifier, kind, mime)
    with pytest.raises(ExportError):
        media_name("../private", "audio", "audio/wav")
    for amount in [0, -1, 101, True]:
        with pytest.raises(ExportError):
            ExportLimits(max_media=amount)
    with pytest.raises(ExportError):
        ExportLimits(max_bytes=100 * 1024**2 + 1)
    monkeypatch.setenv("EXPORT_MAX_MEDIA", "2")
    assert ExportLimits.from_environment().max_media == 2
    monkeypatch.setenv("EXPORT_MAX_BYTES", "invalid")
    with pytest.raises(ExportError):
        ExportLimits.from_environment()


@pytest.mark.parametrize("content,expected", [
    (b"fiction", "verified"), (b"fictio", "integrity_error"),
    (b"fictionX", "integrity_error"), (b"FICTION", "integrity_error"),
])
def test_integrity_is_bounded(content, expected):
    source = io.BytesIO(content)
    assert check_integrity(source, 7, hashlib.sha256(b"fiction").hexdigest()) == expected
    assert source.tell() <= 8


@pytest.mark.parametrize("size", [0, -1, True, 15 * 1024**2 + 1])
def test_invalid_integrity_size_never_reads(size):
    stream = io.BytesIO(b"fiction")
    assert check_integrity(stream, size, "invalid") == "integrity_error"
    assert stream.tell() == 0


@pytest.fixture
def export_env(database):
    sessions = session_factory(database[0])
    with sessions() as db:
        a, b = User(email="export-a@example.com"), User(email="export-b@example.com")
        db.add_all([a, b])
        db.flush()
        dreams = [Dream(user_id=a.id, transcript="Fiction lumineuse.", text_version=1),
                  Dream(user_id=a.id, transcript="AUTRE_REVE_PRIVE", text_version=1),
                  Dream(user_id=b.id, transcript="AUTRE_COMPTE_PRIVE", text_version=1)]
        db.add_all(dreams)
        db.flush()
        media = Media(dream_id=dreams[0].id, kind="audio", storage_key="a" * 64,
                      size_bytes=7, media_type="audio/wav", sha256="b" * 64,
                      storage_state="ready")
        db.add_all([media, Media(dream_id=dreams[1].id, kind="audio",
                                storage_key="DONNEE_AUTRE_REVE", storage_state="legacy")])
        db.commit()
        return sessions, a.id, b.id, dreams[0].id, media.id


def test_selection_readonly_whitelist_and_reconnect(export_env):
    sessions, owner, other, dream, media = export_env
    selection = select_export(sessions, owner, dream)
    documents = selection.documents()
    assert tuple(documents) == ROOT_FILES
    assert documents["recit.txt"].decode() == "Fiction lumineuse."
    payload = json.loads(documents["reve.json"])
    assert payload["emotion"]["source"] == "unset"
    assert payload["media"][0]["id"] == str(media)
    assert payload["media"][0]["availability"] == "pending_verification"
    for secret in ["storage_key", "user_id", "password", "claim_token", "AUTRE_REVE",
                   "AUTRE_COMPTE", "DONNEE_AUTRE_REVE", owner.hex, other.hex, "a" * 64]:
        assert secret not in selection.document_json
    with sessions() as db:
        assert db.get(DreamEmotion, dream) is None  # Pas d'initialisation P08 cachée.
    revalidate_export(sessions, owner, dream, selection)


@pytest.mark.parametrize("target", ["other", "unknown", "deleted"])
def test_uniform_not_found(export_env, target):
    sessions, owner, other, dream, _ = export_env
    if target == "deleted":
        with sessions() as db:
            row = db.get(Dream, dream)
            row.status, row.deleted_at = "deleted", datetime.now(timezone.utc)
            db.commit()
    with pytest.raises(HTTPException) as error:
        select_export(sessions, other if target == "other" else owner,
                      uuid4() if target == "unknown" else dream)
    assert (error.value.status_code, error.value.detail) == (404, "Ressource introuvable")


@pytest.mark.parametrize("change", ["text", "emotion", "media", "deleted"])
def test_revalidation_after_concurrent_change(export_env, change):
    sessions, owner, _, dream, media = export_env
    snapshot = select_export(sessions, owner, dream)
    with sessions() as db:
        row = db.get(Dream, dream)
        if change == "text":
            row.transcript, row.text_version = "Autre fiction.", 2
        elif change == "emotion":
            row.emotion = "triste"
        elif change == "deleted":
            row.status, row.deleted_at = "deleted", datetime.now(timezone.utc)
        else:
            item = db.get(Media, media)
            item.storage_state, item.purge_requested_at = "deleting", datetime.now(timezone.utc)
        db.commit()
    with pytest.raises(HTTPException if change == "deleted" else ExportError):
        revalidate_export(sessions, owner, dream, snapshot)


def test_limits_incomplete_and_unavailable_media(export_env):
    sessions, owner, _, dream, media = export_env
    with pytest.raises(ExportError, match="export_too_large"):
        select_export(sessions, owner, dream, limits=ExportLimits(max_bytes=6))
    with sessions() as db:
        db.get(Dream, dream).transcript = None
        db.add(Media(dream_id=dream, kind="image", storage_key="legacy-local-private-path",
                     storage_state="legacy"))
        item = db.get(Media, media)
        item.storage_state, item.purge_requested_at = "deleting", datetime.now(timezone.utc)
        db.commit()
    with pytest.raises(ExportError, match="too_many_media"):
        select_export(sessions, owner, dream, limits=ExportLimits(max_media=1))
    payload = json.loads(select_export(sessions, owner, dream).document_json)
    assert payload["dream"]["transcript"] is None
    assert all(m["availability"] == "unavailable" for m in payload["media"])
    assert "legacy-local-private-path" not in json.dumps(payload)


@pytest.mark.parametrize("stale,abstention", [(False, False), (True, False), (False, True)])
def test_emotions_description_and_current_image(export_env, stale, abstention):
    sessions, owner, _, dream, _ = export_env
    with sessions() as db:
        db.get(Dream, dream).emotion = "triste"
        job = Job(dream_id=dream, kind="emotion", status="done")
        image_job = Job(dream_id=dream, kind="image", status="done",
                        finished_at=datetime.now(timezone.utc))
        db.add_all([job, image_job])
        db.flush()
        db.add(DreamEmotion(dream_id=dream, source="manual", selected_text_version=1,
                            suggestion_id=job.id))
        version = 2 if stale else 1
        db.add(EmotionAnalysis(job_id=job.id, user_id=owner, transcript="Fiction lumineuse.",
            text_version=version, choice_revision=1, parameters={"secret": "NE_PAS_EXPORTER"},
            result=dict(request_id=str(job.id), text_version=version, choice_revision=1,
                        emotion=None if abstention else "heureux",
                        abstention_reason="ambiguous" if abstention else None,
                        engine="fake", model_revision="1")))
        db.add(ImageDescription(dream_id=dream, description="Forêt fictive", version=1,
                                text_version=version))
        image = Media(dream_id=dream, kind="image", storage_key="c" * 64, size_bytes=7,
                      sha256="d" * 64, media_type="image/png", storage_state="ready")
        db.add(image)
        db.flush()
        image_job.media_id = image.id
        db.add(ImageGeneration(job_id=image_job.id, user_id=owner, transcript="Fiction lumineuse.",
                               text_version=1, description="Forêt fictive", description_version=1,
                               parameters={"secret": "NE_PAS_EXPORTER"}))
        db.commit()
    payload = json.loads(select_export(sessions, owner, dream).document_json)
    assert payload["emotion"]["value"] == "triste"
    assert payload["emotion"]["suggestion"]["stale"] == stale
    assert payload["emotion"]["suggestion"]["emotion"] == (None if abstention else "heureux")
    assert payload["visual_description"]["stale"] == stale
    assert any(m["is_current_image"] for m in payload["media"]) == (not stale)
    assert "NE_PAS_EXPORTER" not in json.dumps(payload)
    with sessions() as db:
        assert db.scalar(select(Dream.emotion).where(Dream.id == dream)) == "triste"


@pytest.mark.parametrize("foreign", [True, False])
def test_foreign_or_malformed_analysis_never_leaks_raw_result(export_env, foreign):
    sessions, owner, other, dream, _ = export_env
    with sessions() as db:
        job = Job(dream_id=dream, kind="emotion", status="done")
        db.add(job)
        db.flush()
        db.add(EmotionAnalysis(job_id=job.id, user_id=other if foreign else owner,
                               transcript="PRIVATE_SNAPSHOT_NOT_FOR_EXPORT", text_version=1,
                               choice_revision=1, parameters={},
                               result={"secret": "SECRET_NOT_FOR_EXPORT"}))
        db.commit()
    selection = select_export(sessions, owner, dream)
    assert "PRIVATE_SNAPSHOT" not in selection.document_json
    assert "SECRET_NOT_FOR_EXPORT" not in selection.document_json
    result = json.loads(selection.document_json)["emotion"]["suggestion"]
    assert result == (None if foreign else {"status": "invalid_result"})
