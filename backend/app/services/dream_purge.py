"""Maintenance P10 explicite et reprenable, jamais appelée par une route web."""

import time
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.models import (
    Dream,
    DreamEmotion,
    EmotionAnalysis,
    ImageDescription,
    ImageGeneration,
    Job,
    Media,
)
from backend.app.services.dream_deletion import delete_dream
from backend.app.services.media import lock_key
from backend.app.storage.local import KEY, StorageError


class PurgeBlocked(Exception):
    """Code stable sans donnée personnelle ni chemin."""


@dataclass(repr=False)
class Graph:
    dream: Dream
    jobs: list
    media: list
    meta: DreamEmotion | None


def query_rows(db, statement, lock):
    if lock:
        statement = statement.with_for_update(nowait=True)
    return list(db.scalars(statement.execution_options(populate_existing=True)))


def graph_for(db, owner, identifier, *, lock=False):
    # Aucune ligne d'un autre compte verrouillée avant autorisation.
    condition = (Dream.id == identifier, Dream.user_id == owner, Dream.status == "deleted")
    if db.scalar(select(Dream.id).where(*condition)) is None:
        return None
    jobs_query = select(Job).where(Job.dream_id == identifier).order_by(Job.id)
    if lock:
        query_rows(db, jobs_query, True)
    dreams = query_rows(db, select(Dream).where(*condition), lock)
    if not dreams:
        return None
    jobs = query_rows(db, jobs_query, lock)
    media = query_rows(db, select(Media).where(Media.dream_id == identifier)
                       .order_by(Media.id), lock)
    metas = query_rows(db, select(DreamEmotion).where(DreamEmotion.dream_id == identifier), lock)
    result = Graph(dreams[0], jobs, media, metas[0] if metas else None)
    job_ids, media_ids = [j.id for j in jobs], [m.id for m in media]
    owned_media = set(media_ids)
    if any(j.media_id is not None and j.media_id not in owned_media for j in jobs):
        raise PurgeBlocked("cross_reference")
    if db.scalar(select(Job.id).where(Job.media_id.in_(media_ids), Job.dream_id != identifier)
                 .limit(1)) is not None:
        raise PurgeBlocked("cross_reference")
    if result.meta and any(ref is not None and ref not in job_ids
                           for ref in [result.meta.active_request, result.meta.suggestion_id]):
        raise PurgeBlocked("cross_reference")
    if db.scalar(select(DreamEmotion.dream_id).where(
        DreamEmotion.dream_id != identifier,
        or_(DreamEmotion.active_request.in_(job_ids), DreamEmotion.suggestion_id.in_(job_ids)),
    ).limit(1)) is not None:
        raise PurgeBlocked("cross_reference")
    for cls in [ImageGeneration, EmotionAnalysis]:
        rows = query_rows(db, select(cls).where(cls.job_id.in_(job_ids)), lock)
        if any(row.user_id != owner for row in rows):
            raise PurgeBlocked("cross_reference")
    query_rows(db, select(ImageDescription).where(ImageDescription.dream_id == identifier), lock)
    if any(m.storage_state == "legacy" for m in media):
        raise PurgeBlocked("legacy_media")
    if any(not KEY.fullmatch(m.storage_key) for m in media):
        raise PurgeBlocked("invalid_key")
    return result


def timeouts(db):
    db.execute(text("SET LOCAL lock_timeout = '3s'"))
    db.execute(text("SET LOCAL statement_timeout = '10s'"))


class DreamPurgeService:
    def __init__(self, media_service):
        self.media = media_service
        self.sessions, self.storage = media_service.sessions, media_service.storage

    def inspect(self, owner, dream_id):
        """Inventaire SQL seulement, sans initialisation, verrou d'écriture ou disque."""
        try:
            with self.sessions() as db:
                db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                timeouts(db)
                graph = graph_for(db, owner, dream_id)
                if graph is None:
                    return "not_found"
                return "eligible"
        except PurgeBlocked as exc:
            return str(exc)
        except SQLAlchemyError:
            return "database_failed"

    def purge_one(self, owner, dream_id):
        """Un rêve seulement ; identifiant propriétaire obligatoire, absence idempotente.

        Le passage deleting est validé avant les fichiers. Un crash ultérieur
        laisse cette demande persistante ; l'absence des fichiers permet la reprise.
        """
        try:
            with self.sessions() as db:
                timeouts(db)
                if graph_for(db, owner, dream_id, lock=True) is None:
                    return "not_found"
                # Rattrape aussi les anciens DELETE qui ne programmaient pas les médias.
                delete_dream(db, owner, dream_id)
            with self.sessions() as db:
                timeouts(db)
                graph = graph_for(db, owner, dream_id, lock=True)
                if graph is None:
                    return "not_found"
                started = time.monotonic()

                def checkpoint():
                    if time.monotonic() - started > 60:
                        raise PurgeBlocked("timeout")

                # Précontrôle de TOUTES les clés avant le premier unlink.
                for media in sorted(graph.media, key=lambda item: item.storage_key):
                    checkpoint()
                    lock_key(db, media.storage_key)
                    self.storage.is_absent(media.storage_key)
                    self.storage.is_absent(media.storage_key, temporary=True)
                for media in graph.media:
                    checkpoint()
                    for temporary in [False, True]:
                        self.storage.delete(media.storage_key, temporary=temporary)
                        if not self.storage.is_absent(media.storage_key, temporary=temporary):
                            raise PurgeBlocked("file_remaining")
                    media.storage_state = "purged"
                    media.purged_at = db.scalar(select(func.clock_timestamp()))
                db.flush()  # Contraintes P19 validées ; rien n'est encore définitivement effacé.
                ids = [job.id for job in graph.jobs]
                db.execute(delete(DreamEmotion).where(DreamEmotion.dream_id == dream_id))
                db.execute(delete(EmotionAnalysis).where(EmotionAnalysis.job_id.in_(ids)))
                db.execute(delete(ImageGeneration).where(ImageGeneration.job_id.in_(ids)))
                db.execute(delete(ImageDescription).where(ImageDescription.dream_id == dream_id))
                db.execute(delete(Job).where(Job.dream_id == dream_id))
                db.execute(delete(Media).where(Media.dream_id == dream_id))
                db.execute(delete(Dream).where(Dream.id == dream_id, Dream.user_id == owner,
                                             Dream.status == "deleted"))
                checkpoint()
                db.commit()
            return "purged"
        except PurgeBlocked as exc:
            return str(exc)
        except (StorageError, OSError):
            return "storage_failed"
        except HTTPException as exc:
            return "busy" if exc.status_code == 409 else "database_failed"
        except SQLAlchemyError as exc:
            code = getattr(getattr(exc, "orig", None), "sqlstate", None)
            return "busy" if code in {"55P03", "40P01", "40001"} else "database_failed"

    def run(self, *, apply=False, limit=20):
        if type(apply) is not bool or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Configuration de maintenance invalide")
        with self.sessions() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            timeouts(db)
            rows = db.execute(select(Dream.user_id, Dream.id).where(Dream.status == "deleted")
                              .order_by(Dream.deleted_at, Dream.id).limit(limit)).all()
        report = {"examined": len(rows), "purged": 0, "eligible": 0, "blocked": 0,
                  "not_found": 0, "errors": {}}
        for owner, identifier in rows:
            result = self.purge_one(owner, identifier) if apply else self.inspect(owner, identifier)
            if result in {"purged", "eligible", "not_found"}:
                report[result] += 1
            else:
                report["blocked"] += 1
                report["errors"][result] = report["errors"].get(result, 0) + 1
        return report
