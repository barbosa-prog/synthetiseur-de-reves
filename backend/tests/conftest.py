"""Tests P14 : collecte sûre, PostgreSQL autorisé et moteurs réels désactivés."""
import os
import uuid

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from backend.app.database import ROOT, make_engine
from scripts.test_safety import OFFLINE, validate_target, verify_server

# Avant la collecte et les imports de l'application : ne jamais lire le .env personnel.
os.environ.update(OFFLINE)
for _key in ("IMAGE_RECEIPT_PATH", "IMAGE_MODEL_PATH", "STT_MODEL_PATH", "EMOTION_MODEL_PATH"):
    os.environ.pop(_key, None)
for _key in list(os.environ):
    if _key.startswith("RUN_") or _key.startswith("PG"):
        os.environ.pop(_key)
os.environ["EMOTION_ENABLED"] = "1" if os.environ.get("P14_FAKE_EMOTION_UI") == "1" else "0"
if not os.environ.get("P14_TEST_AUTHORIZATION"):
    os.environ["DATABASE_URL"] = ""

_original_connect = psycopg.connect


def refuse_unscoped_connection(*args, **kwargs):
    pytest.fail("Connexion PostgreSQL interdite pendant la collecte ou hors fixture")


# Avant même la collecte : aucune connexion implicite à l'import d'un module de test.
psycopg.connect = refuse_unscoped_connection


def pytest_addoption(parser):
    parser.addoption("--allow-real-ai", action="store_true", default=False)


def pytest_configure(config):
    if config.getoption("--allow-real-ai"):
        if "--allow-real-ai" not in config.invocation_params.args:
            raise pytest.UsageError("L'option IA réelle doit être passée explicitement en CLI")
        os.environ["RUN_EMOTION_REAL"] = "1"


def pytest_sessionfinish(session, exitstatus):
    """En CI, un test obligatoire ignoré ne doit pas rendre la recette verte."""
    if os.getenv("CI", "").lower() == "true":
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter and any(not getattr(report, "keywords", {}).get("qualification")
                            for report in reporter.stats.get("skipped", [])):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.path.name == "test_emotion_real.py":
            item.add_marker(pytest.mark.qualification)
        if "database" in item.fixturenames or item.get_closest_marker("browser"):
            item.add_marker(pytest.mark.integration)
        if not any(item.get_closest_marker(mark) for mark in
                   ("integration", "browser", "qualification")):
            item.add_marker(pytest.mark.unit)
        if item.get_closest_marker("qualification") and not config.getoption("--allow-real-ai"):
            item.add_marker(pytest.mark.skip(reason="Qualification IA : opt-in CLI obligatoire"))


@pytest.fixture(autouse=True)
def isolate_test_runtime(request):
    # Un undo() du test ne doit jamais retirer les gardes du runtime.
    with pytest.MonkeyPatch.context() as monkeypatch:
        import socket

        original = _original_connect

        def guarded_connect(conninfo="", **kwargs):
            from sqlalchemy import URL

            if not request.node.get_closest_marker("integration"):
                pytest.fail("Connexion PostgreSQL interdite dans un test unitaire")
            # SQLAlchemy transmet les paramètres en kwargs ; aucun libpq service implicite.
            if conninfo or set(kwargs) - {"host", "port", "dbname", "user", "password",
                                          "options", "connect_timeout", "context"}:
                pytest.fail("Connexion PostgreSQL ambiguë interdite")
            url = URL.create("postgresql+psycopg", username=kwargs.get("user"),
                             password=kwargs.get("password"), host=kwargs.get("host"),
                             port=kwargs.get("port"), database=kwargs.get("dbname"),
                             query={"options": kwargs["options"]} if kwargs.get("options") else {})
            validate_target(os.environ, url)
            connection = original(**kwargs)
            try:
                verify_server(connection, os.environ)
                connection.rollback()
            except BaseException:
                connection.close()
                raise
            return connection

        monkeypatch.setattr(psycopg, "connect", guarded_connect)
        monkeypatch.setattr(psycopg.Connection, "connect", classmethod(
            lambda cls, conninfo="", **kwargs: guarded_connect(conninfo, **kwargs)))
        connect = socket.socket.connect

        def local_only(sock, address):
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
                pytest.fail("Réseau externe interdit pendant les tests")
            return connect(sock, address)

        monkeypatch.setattr(socket.socket, "connect", local_only)
        connect_ex = socket.socket.connect_ex

        def local_only_ex(sock, address):
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
                pytest.fail("Réseau externe interdit pendant les tests")
            return connect_ex(sock, address)

        monkeypatch.setattr(socket.socket, "connect_ex", local_only_ex)
        if request.node.get_closest_marker("browser"):
            validate_target(os.environ)
            from urllib.parse import urlsplit

            origin = os.environ.get("WEB_TEST_URL", "")
            parsed = urlsplit(origin)
            if (origin != os.environ.get("WEB_ORIGIN") or parsed.scheme != "https"
                    or parsed.hostname != "127.0.0.1" or parsed.port in {None, 5434, 8443}):
                pytest.fail("Origine navigateur temporaire non autorisée")
        if not request.node.get_closest_marker("qualification"):
            import importlib.abc
            import subprocess
            import sys

            from backend.app import emotion_runner

            def forbidden(*args, **kwargs):
                pytest.fail("Moteur IA réel interdit dans les tests ordinaires")

            # Les tests d'adaptateur remplacent explicitement leurs runners/subprocessus.
            monkeypatch.setattr(emotion_runner.WatchedEmotionRunner, "run", forbidden)
            popen = subprocess.Popen

            def safe_popen(args, *extra, **kwargs):
                from pathlib import Path

                command = args if not isinstance(args, str) else [args]
                if any(Path(str(part)).name in {"image_job_bridge.py", "image_job_gpu.py",
                                               "emotion_cpu_child.py", "download_stt_model.py",
                                               "backend.app.stt_provider", "backend.app.stt_worker",
                                               "backend.app.image_worker",
                                               "backend.app.emotion_worker",
                                               "verify_stt_real.py", "verify_image_real.py"}
                       for part in command):
                    forbidden()
                return popen(args, *extra, **kwargs)

            monkeypatch.setattr(subprocess, "Popen", safe_popen)

            class NoRealModel(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split(".")[0] in {
                        "torch", "transformers", "diffusers", "faster_whisper",
                        "huggingface_hub", "sentence_transformers",
                    }:
                        forbidden()

            monkeypatch.setattr(sys, "meta_path", [NoRealModel(), *sys.meta_path])
            monkeypatch.setenv("RUN_EMOTION_REAL", "0")
            monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        yield


@pytest.fixture
def database():
    url = validate_target(os.environ)
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

