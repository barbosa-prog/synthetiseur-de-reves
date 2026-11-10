"""Tests sans serveur : configuration et génération PostgreSQL de la migration."""

from io import StringIO

import pytest
from alembic import command
from alembic.config import Config

from backend.app.database import database_url


@pytest.mark.parametrize("value", ["PRIVATE_INVALID_URL", "sqlite://", "postgresql://host/db"])
def test_invalid_database_configuration(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(ValueError) as error:
        database_url()
    assert value not in str(error.value)


def test_configuration_does_not_disclose_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "invalid://user:PRIVATE_PASSWORD@localhost/db")
    with pytest.raises(ValueError) as error:
        database_url()
    assert "PRIVATE_PASSWORD" not in str(error.value)


def test_missing_database_configuration(monkeypatch):
    monkeypatch.setattr("backend.app.database.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="Définir DATABASE_URL"):
        database_url()


def test_placeholder_is_rejected(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://fiction:REPLACE_ME@localhost/fiction"
    )
    with pytest.raises(ValueError, match="secrets masqués"):
        database_url()


def test_offline_migration():
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    for table in ["users", "dreams", "media", "jobs"]:
        assert f"CREATE TABLE {table}" in sql
    assert "FOREIGN KEY" in sql
    assert "ck_job_attempts" in sql

