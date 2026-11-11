"""Coordination PostgreSQL/stockage privé avec compensation et purge récupérable."""

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Dream, Media
from backend.app.storage.local import PrivateStorage, StorageError, new_key


class MediaNotFound(Exception):
    """Même erreur pour absent, étranger, expiré, supprimé, legacy ou fichier manquant."""


@dataclass
class PrivateDownload:
    """Uniquement des métadonnées publiques sûres et un descripteur déjà ouvert."""

    identifier: uuid.UUID
    stream: BinaryIO
    size: int
    media_type: str


def lock_key(db: Session, key: str) -> None:
    """Sérialise publication/purge/réconciliation entre processus via PostgreSQL."""
    lock = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})


class MediaService:
    """Transactions explicites ; aucune route d'import utilisateur dans P19."""

    def __init__(self, storage: PrivateStorage, sessions: sessionmaker[Session]):
        self.storage, self.sessions = storage, sessions

    def store(self, user_id: uuid.UUID, dream_id: uuid.UUID, source: BinaryIO, *,
              kind: str, media_format: str, filename: str | None = None) -> uuid.UUID:
        """Vérifie le propriétaire, publie le fichier puis valide sa référence en base."""
        key, written = new_key(), False
        try:
            with self.sessions() as db:
                dream = db.scalar(select(Dream).where(
                    Dream.id == dream_id, Dream.user_id == user_id, Dream.status != "deleted",
                ).with_for_update())
                if dream is None:
                    raise MediaNotFound
                lock_key(db, key)
                stored = self.storage.write(source, key=key, kind=kind,
                                            media_format=media_format, filename=filename)
                written = True
                media = Media(dream_id=dream.id, kind=kind, storage_key=stored.key,
                              size_bytes=stored.size, media_type=stored.media_type,
                              sha256=stored.sha256, storage_state="ready")
                db.add(media)
                db.commit()
                return media.id
        except Exception as exc:
            if written:
                try:
                    # En cas de réponse COMMIT perdue, ne jamais effacer un fichier référencé.
                    with self.sessions() as db:
                        lock_key(db, key)
                        referenced = db.scalar(select(Media.id).where(Media.storage_key == key))
                        if referenced is None:
                            self.storage.delete(key)
                        db.commit()
                except Exception:
                    pass  # Réconciliation ultérieure, sans journal de chemin ni contenu.
            if isinstance(exc, (MediaNotFound, StorageError)):
                raise
            raise StorageError("Enregistrement du média impossible ; reprise nécessaire.") from None

    def download(self, user_id: uuid.UUID, media_id: uuid.UUID) -> PrivateDownload:
        """Contrôle de propriétaire à chaque lecture ; empreinte et taille vérifiées."""
        handle = None
        try:
            with self.sessions() as db:
                media = db.scalar(select(Media).join(Dream).where(
                    Media.id == media_id, Dream.user_id == user_id, Dream.status != "deleted",
                    Media.storage_state == "ready",
                    (Media.expires_at.is_(None) | (Media.expires_at > func.now())),
                ))
                if media is None:
                    raise MediaNotFound
                lock_key(db, media.storage_key)
                # Le statut peut avoir changé pendant l'attente du verrou.
                db.refresh(media)
                if media.storage_state != "ready":
                    raise MediaNotFound
                handle = self.storage.open(media.storage_key)
                digest = hashlib.sha256()
                size = 0
                while chunk := handle.read(65536):
                    size += len(chunk)
                    if size > media.size_bytes:
                        raise MediaNotFound
                    digest.update(chunk)
                if size != media.size_bytes or digest.hexdigest() != media.sha256:
                    raise MediaNotFound
                handle.seek(0)
                return PrivateDownload(media.id, handle, media.size_bytes, media.media_type)
        except (MediaNotFound, StorageError, OSError):
            if handle is not None:
                handle.close()
            raise MediaNotFound from None
        except SQLAlchemyError:
            if handle is not None:
                handle.close()
            raise StorageError("Consultation du média indisponible.") from None

    def request_purge(self, user_id: uuid.UUID, media_id: uuid.UUID) -> None:
        """Service interne explicite, pas une suppression de rêve P10 ; tombstone conservé."""
        try:
            with self.sessions() as db:
                media = db.scalar(select(Media).join(Dream).where(
                    Media.id == media_id, Dream.user_id == user_id,
                    Media.storage_state != "legacy",
                ).with_for_update(of=Media))
                if media is None:
                    raise MediaNotFound
                if media.storage_state == "purged":
                    return
                media.storage_state = "deleting"
                media.purge_requested_at = datetime.now(timezone.utc)
                db.commit()  # devient inaccessible avant l'effacement physique
            self._finish_purge(media_id)
        except SQLAlchemyError:
            raise StorageError("Demande de purge indisponible.") from None

    def _finish_purge(self, media_id: uuid.UUID) -> None:
        with self.sessions() as db:
            media = db.get(Media, media_id)
            if media is None:
                return
            lock_key(db, media.storage_key)
            db.refresh(media)
            if media.storage_state != "deleting":
                return
            self.storage.delete(media.storage_key)
            media.storage_state = "purged"
            media.purged_at = datetime.now(timezone.utc)
            db.commit()

    def reconcile(self, *, apply: bool = False, grace_seconds: int = 86400) -> dict[str, int]:
        """Inventaire sec par défaut ; ne supprime que les objets internes orphelins anciens.

        Les verrous sont partagés avec store/purge. Le délai protège le staging récent.
        Aucun fichier legacy, nom arbitraire ou lien n'est effacé par cette maintenance.
        """
        if grace_seconds < 3600:
            raise StorageError("Le délai de grâce doit être d’au moins une heure.")
        report = {"pending_purges": 0, "orphan_files": 0, "staging_files": 0,
                  "missing_files": 0, "cleaned": 0}
        try:
            with self.sessions() as db:
                pending = list(db.scalars(select(Media.id).where(
                    Media.storage_state == "deleting",
                )))
            report["pending_purges"] = len(pending)
            if apply:
                for identifier in pending:
                    self._finish_purge(identifier)
                    report["cleaned"] += 1
            for entry in self.storage.inventory():
                if entry.modified_at > time.time() - grace_seconds:
                    continue
                with self.sessions() as db:
                    lock_key(db, entry.key)
                    referenced = db.scalar(select(Media.id).where(Media.storage_key == entry.key))
                    if referenced is None:
                        report["staging_files" if entry.temporary else "orphan_files"] += 1
                        if apply:
                            self.storage.delete(entry.key, temporary=entry.temporary)
                            report["cleaned"] += 1
                    db.commit()
            with self.sessions() as db:
                for media in db.scalars(select(Media).where(Media.storage_state == "ready")):
                    try:
                        with self.storage.open(media.storage_key):
                            pass
                    except StorageError:
                        report["missing_files"] += 1
            return report
        except SQLAlchemyError:
            raise StorageError("Réconciliation indisponible ; détails privés masqués.") from None
