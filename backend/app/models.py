"""Modèle relationnel P02 ; aucun fichier média ni traitement IA."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class User(Base):
    """Propriétaire d'un rêve ; authentification réservée à P03."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email IS NULL OR btrim(email) <> ''", name="ck_user_email"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    # Nullable pour préserver les comptes P02 ; ils ne peuvent pas se connecter.
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dreams: Mapped[list["Dream"]] = relationship(back_populates="user", passive_deletes="all")


Index("uq_users_email_normalized", func.lower(User.email), unique=True)


class AuthSession(Base):
    """Session révocable ; seul le condensat du jeton aléatoire est stocké."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_session_expiration"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthThrottle(Base):
    """Compteurs persistants à fenêtre fixe, clés pseudonymisées."""

    __tablename__ = "auth_throttles"
    __table_args__ = (CheckConstraint("attempts >= 0", name="ck_throttle_attempts"),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)


class Dream(Base):
    """Brouillon nullable, puis récit corrigé et résultat."""

    __tablename__ = "dreams"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','processing','transcribing','transcribed','correcting',"
            "'generating','ready','error','deleted')", name="ck_dream_status",
        ),
        CheckConstraint(
            "emotion IS NULL OR emotion IN ('heureux','stressant','neutre','triste','autre')",
            name="ck_dream_emotion",
        ),
        CheckConstraint("transcript IS NULL OR btrim(transcript) <> ''", name="ck_dream_text"),
        CheckConstraint("text_version >= 0", name="ck_dream_text_version"),
        CheckConstraint("status <> 'ready' OR transcript IS NOT NULL", name="ck_dream_ready"),
        CheckConstraint(
            "(status = 'deleted') = (deleted_at IS NOT NULL)", name="ck_dream_deleted",
        ),
        Index("ix_dreams_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    transcript: Mapped[str | None] = mapped_column(Text)
    text_version: Mapped[int] = mapped_column(Integer, server_default="0")
    text_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    emotion: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="dreams")
    media: Mapped[list["Media"]] = relationship(back_populates="dream", passive_deletes="all")
    jobs: Mapped[list["Job"]] = relationship(back_populates="dream", passive_deletes="all")


class Media(Base):
    """Référence vers un fichier privé ; aucun contenu binaire en base."""

    __tablename__ = "media"
    __table_args__ = (
        CheckConstraint("kind IN ('audio','image','sound')", name="ck_media_kind"),
        CheckConstraint("btrim(storage_key) <> ''", name="ck_media_key"),
        CheckConstraint("storage_state IN ('legacy','ready','deleting','purged')",
                        name="ck_media_state"),
        CheckConstraint("size_bytes IS NULL OR size_bytes BETWEEN 1 AND 15728640",
                        name="ck_media_size"),
        CheckConstraint(
            "storage_state = 'legacy' OR (size_bytes IS NOT NULL AND media_type IS NOT NULL "
            "AND sha256 IS NOT NULL AND storage_key ~ '^[a-f0-9]{64}$' "
            "AND sha256 ~ '^[a-f0-9]{64}$')", name="ck_media_managed",
        ),
        CheckConstraint(
            "media_type IS NULL OR (kind IN ('audio','sound') AND media_type IN "
            "('audio/wav','audio/mpeg')) OR (kind = 'image' AND media_type IN "
            "('image/png','image/jpeg','image/webp'))", name="ck_media_type",
        ),
        CheckConstraint(
            "(storage_state IN ('deleting','purged')) = (purge_requested_at IS NOT NULL)",
            name="ck_media_purge_request",
        ),
        CheckConstraint("(storage_state = 'purged') = (purged_at IS NOT NULL)",
                        name="ck_media_purged"),
        CheckConstraint("duration_ms IS NULL OR duration_ms BETWEEN 1 AND 480000",
                        name="ck_media_duration"),
        CheckConstraint("sample_rate_hz IS NULL OR sample_rate_hz = 16000",
                        name="ck_media_sample_rate"),
        CheckConstraint("channels IS NULL OR channels = 1", name="ck_media_channels"),
        CheckConstraint("sample_count IS NULL OR sample_count BETWEEN 1 AND 7680000",
                        name="ck_media_sample_count"),
        CheckConstraint("source_size_bytes IS NULL OR source_size_bytes BETWEEN 1 AND 15728640",
                        name="ck_media_source_size"),
        CheckConstraint(
            "source_format IS NULL OR source_format IN ('wav','mp3','webm','ogg','mp4')",
            name="ck_media_source_format",
        ),
        CheckConstraint("audio_source IS NULL OR audio_source IN ('import','microphone')",
                        name="ck_media_audio_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    dream_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dreams.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    media_type: Mapped[str | None] = mapped_column(String(32))
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_state: Mapped[str] = mapped_column(String(12), server_default="legacy")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    purge_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    sample_rate_hz: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    sample_count: Mapped[int | None] = mapped_column(BigInteger)
    source_format: Mapped[str | None] = mapped_column(String(12))
    source_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    audio_source: Mapped[str | None] = mapped_column(String(12))
    dream: Mapped[Dream] = relationship(back_populates="media")


class Job(Base):
    """Métadonnées de tâches futures, sans moteur d'exécution."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('stt','image','tts')", name="ck_job_kind"),
        CheckConstraint("status IN ('queued','running','done','failed')", name="ck_job_status"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_job_attempts"),
        Index("uq_active_stt_dream", "dream_id", unique=True,
              postgresql_where=text("kind = 'stt' AND status IN ('queued','running')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    dream_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dreams.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(12), server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(40))
    media_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media.id", ondelete="RESTRICT"))
    expected_text_version: Mapped[int | None] = mapped_column(Integer)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dream: Mapped[Dream] = relationship(back_populates="jobs")
