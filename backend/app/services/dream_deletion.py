"""Retrait P10 atomique : aucune suppression physique, aucun effacement SQL."""

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.models import Dream, DreamEmotion, Job, Media


def delete_dream(db, user_id, dream_id):
    """Jobs puis rêve puis médias ; NOWAIT évite les cycles avec les workers.

    La relecture des jobs sous verrou du rêve couvre une création concurrente
    entre le premier inventaire et la prise du verrou du rêve. Toute erreur
    annule la transaction entière. L'identité doit venir de l'authentification.
    """
    try:
        db.execute(text("SET LOCAL statement_timeout = '10s'"))
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        authorized = db.scalar(select(Dream.id).where(
            Dream.id == dream_id, Dream.user_id == user_id,
        ))
        if authorized is None:
            raise HTTPException(404, "Ressource introuvable")

        def lock_jobs():
            return list(db.scalars(select(Job).where(Job.dream_id == dream_id)
                                   .order_by(Job.id).with_for_update(nowait=True)
                                   .execution_options(populate_existing=True)))

        lock_jobs()
        dream = db.scalar(select(Dream).where(
            Dream.id == dream_id, Dream.user_id == user_id,
        ).with_for_update(nowait=True).execution_options(populate_existing=True))
        if dream is None:
            raise HTTPException(404, "Ressource introuvable")
        jobs = lock_jobs()
        media = list(db.scalars(select(Media).where(Media.dream_id == dream_id)
                               .order_by(Media.id).with_for_update(nowait=True)
                               .execution_options(populate_existing=True)))
        meta = db.scalar(select(DreamEmotion).where(DreamEmotion.dream_id == dream_id)
                         .with_for_update(nowait=True).execution_options(populate_existing=True))
        now = db.scalar(select(func.clock_timestamp()))
        first = dream.status != "deleted"
        if first:
            dream.status, dream.deleted_at = "deleted", now
        for job in jobs:
            if job.status in {"queued", "running"}:
                job.status, job.error_code, job.finished_at = "failed", "dream_deleted", now
            job.claim_token = job.lease_until = None
        if meta is not None:
            if first or meta.active_request is not None or meta.suggestion_id is not None:
                meta.revision += 1
                meta.updated_at = now
            meta.active_request = meta.suggestion_id = None
        for item in media:
            if item.storage_state == "ready":
                item.storage_state, item.purge_requested_at = "deleting", now
            # deleting/purged sont déjà programmés/traités. Les clés legacy ne
            # peuvent pas être effacées comme des clés P19 : retrait via le rêve,
            # demande durable portée par deleted_at, traitement sûr en phase 4.
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        code = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if code in {"55P03", "40P01", "40001"}:
            raise HTTPException(409, "Un traitement met à jour ce rêve. Réessayez.") from None
        raise HTTPException(503, "Suppression temporairement indisponible.") from None
    except BaseException:
        db.rollback()
        raise
