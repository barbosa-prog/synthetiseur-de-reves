"""Sélection P10 en lecture seule cohérente ; ni archive ni lecture de fichier."""

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text

from backend.app.emotion_provider import EmotionResult
from backend.app.export_contract import (
    ExportError,
    ExportLimits,
    ExportSelection,
    canonical,
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
)


def date(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def select_export(sessions, user_id, dream_id, *, limits=None):
    """Identité fournie par l'authentification future, jamais un champ de formulaire.

    Ouvre sa propre transaction REPEATABLE READ/READ ONLY ; n'appelle pas les
    projections qui initialisent les métadonnées P08 ou verrouillent les rêves.
    """
    limits = limits or ExportLimits.from_environment()
    with sessions() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        db.execute(text("SET LOCAL statement_timeout = '5s'"))
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        dream = db.scalar(select(Dream).where(
            Dream.id == dream_id, Dream.user_id == user_id, Dream.status != "deleted",
        ))
        if dream is None:
            raise HTTPException(404, "Ressource introuvable")
        meta = db.get(DreamEmotion, dream.id)
        description = db.get(ImageDescription, dream.id)
        media = list(db.scalars(select(Media).where(Media.dream_id == dream.id)
                               .order_by(Media.id).limit(limits.max_media + 1)))
        if len(media) > limits.max_media:
            raise ExportError("too_many_media")
        if any(m.storage_state == "ready" and m.size_bytes is None for m in media):
            raise ExportError("unknown_media_size")
        # Budget conservateur : tous les médias, et pas seulement l'image actuelle.
        total = sum(m.size_bytes or 0 for m in media)
        if total > limits.max_bytes:
            raise ExportError("export_too_large")
        suggestion = None
        row = db.execute(select(EmotionAnalysis, Job).join(
            Job, Job.id == EmotionAnalysis.job_id,
        ).where(Job.dream_id == dream.id, Job.kind == "emotion", Job.status == "done",
                EmotionAnalysis.user_id == user_id, EmotionAnalysis.result.is_not(None))
            .order_by(Job.created_at.desc(), Job.id.desc()).limit(1)).first()
        if row:
            analysis, job = row
            try:
                result = EmotionResult.model_validate_json(canonical(analysis.result))
                if (result.request_id != job.id or result.text_version != analysis.text_version
                        or result.choice_revision != analysis.choice_revision):
                    raise ValueError
            except (ValueError, TypeError):
                # Une donnée fournisseur incorrecte ne doit pas être exportée brute.
                suggestion = {"status": "invalid_result"}
            else:
                suggestion = {
                    "emotion": result.emotion, "abstention_reason": result.abstention_reason,
                    "text_version": analysis.text_version,
                    "stale": (analysis.text_version != dream.text_version
                              or analysis.transcript != dream.transcript
                              or meta is None or meta.suggestion_id != job.id),
                    "indicative_only": True,
                }
        # L'image courante est calculée sans appeler current_image (verrou d'écriture).
        current_id = None
        if description and description.text_version == dream.text_version:
            current_id = db.scalar(select(Media.id).join(Job, Job.media_id == Media.id)
                .join(ImageGeneration, ImageGeneration.job_id == Job.id).where(
                    Media.dream_id == dream.id, Media.kind == "image",
                    Media.storage_state == "ready", Job.dream_id == dream.id,
                    Job.kind == "image", Job.status == "done", ImageGeneration.user_id == user_id,
                    ImageGeneration.text_version == dream.text_version,
                    ImageGeneration.description_version == description.version,
                    (Media.expires_at.is_(None) | (Media.expires_at > datetime.now(timezone.utc))),
                ).order_by(Job.finished_at.desc(), Job.id.desc()).limit(1))
        now = datetime.now(timezone.utc)
        entries = []
        for item in media:
            reason = None
            if item.storage_state != "ready":
                reason = item.storage_state
            elif item.expires_at and item.expires_at <= now:
                reason = "expired"
            try:
                name = media_name(item.id, item.kind, item.media_type)
            except ExportError:
                name, reason = None, "unsupported_format"
            entries.append(dict(
                id=str(item.id), kind=item.kind, media_type=item.media_type,
                archive_name=name, size_bytes=item.size_bytes, sha256=item.sha256,
                created_at=date(item.created_at), is_current_image=item.id == current_id,
                availability="unavailable" if reason else "pending_verification",
                reason=reason,
            ))
        document = dict(
            format_version=1,
            dream=dict(id=str(dream.id), transcript=dream.transcript,
                       text_version=dream.text_version, created_at=date(dream.created_at),
                       text_updated_at=date(dream.text_updated_at), status=dream.status),
            emotion=dict(value=dream.emotion,
                         source=meta.source if meta else ("legacy" if dream.emotion else "unset"),
                         selected_text_version=meta.selected_text_version if meta else None,
                         suggestion=suggestion),
            visual_description=(dict(text=description.description, version=description.version,
                                     text_version=description.text_version,
                                     stale=description.text_version != dream.text_version)
                                if description else None),
            media=entries,
        )
        payload = canonical(document)
        # Inclut aussi les identifiants internes susceptibles de changer sans changer l'affichage.
        internal = canonical([payload, meta.revision if meta else None,
                              [m.storage_key for m in media]])
        fingerprint = hashlib.sha256(internal.encode()).hexdigest()
        selection = ExportSelection(payload, fingerprint)
        document_bytes = sum(len(content) for content in selection.documents().values())
        if total + document_bytes > limits.max_bytes:
            raise ExportError("export_too_large")
        return selection


def revalidate_export(sessions, user_id, dream_id, selection, *, limits=None):
    """À appeler avant livraison ; 404 si suppression, conflit si données changées.

    Ne garantit pas l'absence de suppression après retour : la phase ZIP devra
    coordonner la livraison et revérifier pendant les longs téléchargements.
    """
    current = select_export(sessions, user_id, dream_id, limits=limits)
    if current.fingerprint != selection.fingerprint:
        raise ExportError("export_changed")
