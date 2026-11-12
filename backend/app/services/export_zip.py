"""ZIP privé P10 borné ; aucune suppression de rêve ni purge P19."""

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_STORED, ZipFile

from fastapi import HTTPException
from sqlalchemy import func, select, text

from backend.app.export_contract import ExportError, ExportLimits, ExportSelection
from backend.app.models import AuthSession, Dream
from backend.app.services.exports import revalidate_export, select_export
from backend.app.services.media import MediaIntegrityError, MediaNotFound
from backend.app.storage.local import MARKER, LocalPrivateStorage, StorageError, has_reparse

SLOT = 714100010  # Verrou session PostgreSQL partagé entre processus ; aucune table ajoutée.
BUILD_SECONDS = 60
DELIVERY_SECONDS = 120
DISK_RESERVE = 200 * 1024**2


def temporary_root():
    if os.getenv("EXPORT_TEMP_ROOT"):
        return Path(os.environ["EXPORT_TEMP_ROOT"])
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "SynthetiseurDeReves/exports_tmp"
    return Path.home() / ".local/share/synthetiseur-de-reves/exports_tmp"


class BoundedWriter:
    def __init__(self, stream, limit, checkpoint):
        self.stream, self.limit, self.checkpoint = stream, limit, checkpoint

    def write(self, data):
        self.checkpoint()
        if self.stream.tell() + len(data) > self.limit:
            raise ExportError("export_too_large")
        return self.stream.write(data)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class Archive:
    """Propriétaire du dossier, du flux et du verrou jusqu'à fin de réponse."""

    def __init__(self, service, owner, dream, selection, connection):
        self.service, self.owner, self.dream = service, owner, dream
        self.selection, self.connection = selection, connection
        self.directory = self.path = self.stream = None
        self.started = time.monotonic()
        self.delivered_at = None
        self.acquired = False

    def checkpoint(self):
        if time.monotonic() - self.started > BUILD_SECONDS:
            raise ExportError("export_timeout")

    def close(self):
        failed = False
        try:
            if self.stream:
                self.stream.close()
                self.stream = None
            if self.directory:
                # Dossier créé par ce processus sous la racine privée déjà vérifiée.
                self.directory.cleanup()
                self.directory = None
        except OSError:
            failed = True
        finally:
            if self.connection:
                try:
                    if self.acquired:
                        self.connection.execute(text("SELECT pg_advisory_unlock(:slot)"),
                                                {"slot": SLOT})
                except Exception:
                    self.connection.invalidate()
                    failed = True
                finally:
                    self.connection.close()
                    self.connection = None
        if failed:
            raise ExportError("cleanup_failed") from None

    def guard(self, session_id=None):
        with self.service.sessions() as db:
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            if db.scalar(select(Dream.id).where(
                Dream.id == self.dream, Dream.user_id == self.owner, Dream.status != "deleted",
            )) is None:
                raise HTTPException(404, "Rêve inaccessible")
            if session_id and db.scalar(select(AuthSession.id).where(
                AuthSession.id == session_id, AuthSession.user_id == self.owner,
                AuthSession.revoked_at.is_(None), AuthSession.expires_at > func.now(),
            )) is None:
                raise HTTPException(401, "Session expirée")

    def chunks(self, session_id=None):
        try:
            revalidate_export(self.service.sessions, self.owner, self.dream, self.selection,
                              limits=self.service.limits)
            self.delivered_at = time.monotonic()
            while True:
                if time.monotonic() - self.delivered_at > DELIVERY_SECONDS:
                    raise ExportError("export_timeout")
                self.guard(session_id)
                chunk = self.stream.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            self.close()


class ZipExportService:
    def __init__(self, media_service, *, root=None, limits=None):
        self.media = media_service
        self.sessions = media_service.sessions
        self.root = root if root is not None else temporary_root()
        self.limits = limits if limits is not None else ExportLimits.from_environment()

    def _prepare_root(self):
        media_root = getattr(self.media.storage, "root", None)
        if media_root is not None and (
            self.root.resolve().is_relative_to(media_root.resolve())
            or media_root.resolve().is_relative_to(self.root.resolve())
        ):
            raise StorageError("Racine temporaire non dédiée.")
        # Réutilise les gardes P19 : hors dépôt/OneDrive, pas de jonction ni lien.
        guard = LocalPrivateStorage(self.root)
        guard._guard()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / MARKER).mkdir(exist_ok=True)
        # Seulement des résidus anciens dans cette racine dédiée ; jamais les médias.
        for child in self.root.glob("export-*"):
            if (child.is_dir() and not has_reparse(child)
                    and child.resolve().parent == self.root.resolve()
                    and child.stat().st_mtime < time.time() - 3600):
                if all(p.name == "archive.zip" and p.is_file() and not has_reparse(p)
                       for p in child.iterdir()):
                    shutil.rmtree(child)
        if shutil.disk_usage(self.root).free < self.limits.max_bytes + DISK_RESERVE:
            raise ExportError("insufficient_disk")

    def build(self, owner, dream):
        selection = select_export(self.sessions, owner, dream, limits=self.limits)
        # Une archive globale à la fois dans cette base, construction ET livraison.
        connection = self.sessions.kw["bind"].connect().execution_options(
            isolation_level="AUTOCOMMIT",
        )
        acquired = False
        archive = Archive(self, owner, dream, selection, connection)
        try:
            acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:slot)"), {"slot": SLOT})
            if not acquired:
                raise ExportError("export_busy")
            archive.acquired = True
            self._prepare_root()
            archive.directory = tempfile.TemporaryDirectory(prefix="export-", dir=self.root)
            archive.path = Path(archive.directory.name) / "archive.zip"
            document = json.loads(selection.document_json)
            included = 0
            with archive.path.open("w+b") as output:
                bounded = BoundedWriter(output, self.limits.max_bytes, archive.checkpoint)
                with ZipFile(bounded, "w", compression=ZIP_STORED, allowZip64=False) as zip_file:
                    zip_file.writestr("medias/", b"")
                    for entry in document["media"]:
                        archive.checkpoint()
                        if entry["availability"] != "pending_verification":
                            entry["exported"] = False
                            continue
                        try:
                            download = self.media.download(owner, UUID(entry["id"]),
                                strict_integrity=True, checkpoint=archive.checkpoint)
                        except MediaNotFound:
                            entry.update(availability="unavailable", reason="missing",
                                         exported=False)
                            continue
                        except MediaIntegrityError:
                            raise ExportError("integrity_error") from None
                        with (download.stream as source,
                              zip_file.open(entry["archive_name"], "w") as dest):
                            digest, size = hashlib.sha256(), 0
                            while chunk := source.read(65536):
                                archive.checkpoint()
                                size += len(chunk)
                                if size > entry["size_bytes"]:
                                    raise ExportError("integrity_error")
                                included += len(chunk)
                                if included > self.limits.max_bytes:
                                    raise ExportError("export_too_large")
                                digest.update(chunk)
                                dest.write(chunk)
                            if size != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]:
                                raise ExportError("integrity_error")
                        entry.update(availability="verified", reason=None, exported=True)
                    documents = ExportSelection(json.dumps(document), "").documents()
                    if included + sum(map(len, documents.values())) > self.limits.max_bytes:
                        raise ExportError("export_too_large")
                    for name, content in documents.items():
                        zip_file.writestr(name, content)
            archive.checkpoint()
            revalidate_export(self.sessions, owner, dream, selection, limits=self.limits)
            archive.checkpoint()
            archive.stream = archive.path.open("rb")
            return archive
        except BaseException:
            archive.close()
            raise
