"""Base PostgreSQL locale isol?e, partag?e par les tests P02/P03."""
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from backend.app.database import ROOT, database_url, make_engine


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

