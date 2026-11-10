"""Intégration réelle ; schéma aléatoire isolé, aucun accès aux tables existantes."""

import os
import uuid
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.database import ROOT, Base, database_url, make_engine, session_factory
from backend.app.models import Dream, Job, Media, User

pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    load_dotenv(ROOT / ".env", override=False)
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL absent : intégration PostgreSQL non exécutée")
    url = database_url("TEST_DATABASE_URL")
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Tests limités à un serveur PostgreSQL local")
    schema = "p02_test_" + uuid.uuid4().hex
    admin = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 5})
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception:
        admin.dispose()
        pytest.fail("PostgreSQL de test inaccessible ; détails et identifiants masqués")
    engine = make_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        config = Config(str(ROOT / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine, config
    finally:
        engine.dispose()
        # Identifiant construit uniquement à partir d'un UUID interne, jamais d'une entrée.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_migration_roundtrip_and_model_consistency(database):
    engine, config = database
    with engine.begin() as connection:
        assert set(inspect(connection).get_table_names()) == {
            "users", "dreams", "media", "jobs", "alembic_version"
        }
        for table in ["dreams", "media", "jobs"]:
            assert len(inspect(connection).get_foreign_keys(table)) == 1
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
        config.attributes["connection"] = connection
        command.upgrade(config, "head")  # application répétée sans changement
        command.downgrade(config, "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"


def test_persistence_and_relationships_after_reconnect(database):
    engine, _ = database
    sessions = session_factory(engine)
    with sessions() as session:
        user = User(email="fiction@example.invalid")
        dream = Dream(user=user)
        dream.media.append(Media(kind="audio", storage_key="private/fictitious/audio.wav"))
        dream.jobs.append(Job(kind="stt"))
        session.add(dream)
        session.commit()
        identifier = dream.id
        assert dream.transcript is None and dream.emotion is None
        assert dream.status == "draft"
    engine.dispose()  # ferme aussi les connexions physiques du pool
    with sessions() as session:
        dream = session.get(Dream, identifier)
        assert dream.user.email == "fiction@example.invalid"
        assert dream.media[0].kind == "audio"
        assert dream.jobs[0].attempts == 0
        assert dream.created_at.tzinfo is not None
        for status in ["transcribing", "transcribed", "correcting", "generating", "ready"]:
            dream.status = status
            dream.transcript = "Récit fictif de validation."
            session.commit()
        dream.status = "deleted"
        dream.deleted_at = datetime.now(timezone.utc)
        session.commit()


@pytest.mark.parametrize("case", [
    "dream_fk", "media_fk", "job_fk", "emotion", "status", "blank_text", "ready",
    "deleted", "kind_media", "blank_key", "kind_job", "job_status", "attempts",
    "null_owner", "duplicate_email", "duplicate_key", "delete_parent",
])
def test_database_rejects_invalid_data(database, case):
    engine, _ = database
    with Session(engine) as session:
        user = User(email="unique@example.invalid")
        dream = Dream(user=user)
        session.add(dream)
        session.commit()
        if case == "dream_fk":
            session.add(Dream(user_id=uuid.uuid4()))
        elif case == "media_fk":
            session.add(Media(dream_id=uuid.uuid4(), kind="audio", storage_key="fake"))
        elif case == "job_fk":
            session.add(Job(dream_id=uuid.uuid4(), kind="stt"))
        elif case == "emotion":
            dream.emotion = "invalid"
        elif case == "status":
            dream.status = "invalid"
        elif case == "blank_text":
            dream.transcript = "   "
        elif case == "ready":
            dream.status = "ready"
        elif case == "deleted":
            dream.status = "deleted"
        elif case in {"kind_media", "blank_key"}:
            session.add(Media(dream=dream, kind="invalid" if case == "kind_media" else "audio",
                              storage_key="x" if case == "kind_media" else " "))
        elif case in {"kind_job", "job_status", "attempts"}:
            session.add(Job(dream=dream, kind="invalid" if case == "kind_job" else "stt",
                            status="invalid" if case == "job_status" else "queued",
                            attempts=4 if case == "attempts" else 0))
        elif case == "null_owner":
            session.add(Dream())
        elif case == "duplicate_email":
            session.add(User(email=user.email))
        elif case == "duplicate_key":
            session.add_all([Media(dream=dream, kind="audio", storage_key="same")
                             for _ in range(2)])
        elif case == "delete_parent":
            session.delete(user)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
