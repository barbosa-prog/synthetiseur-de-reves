"""Protections P14 : aucune tentative vers une base personnelle."""

import importlib
import json
import os
import subprocess
import sys

import psycopg
import pytest
from sqlalchemy import URL

from scripts.test_safety import (
    UnsafeTestTarget,
    checked_url,
    clean_environment,
    isolated_environment,
    validate_target,
    verify_server,
)


@pytest.fixture
def authorized(tmp_path):
    root = tmp_path / "p14_tests_fiction"
    (root / "data").mkdir(parents=True)
    (root / "data/PG_VERSION").write_text("17")
    url = URL.create("postgresql+psycopg", username="p20_012345abcdef",
                     password="fictitious-only", host="127.0.0.1", port=59123,
                     database="p20_validation")
    return isolated_environment(root, url), url


@pytest.mark.parametrize("change", [
    {"database": "dreams_local"}, {"database": "unknown"}, {"host": "localhost"},
    {"port": 5434}, {"port": 5432}, {"query": {"service": "personal"}},
    {"query": {"options": "-csearch_path=public"}}, {"username": "postgres"},
])
def test_dangerous_urls_rejected_without_connection(authorized, change):
    _, url = authorized
    with pytest.raises(UnsafeTestTarget):
        checked_url(url.set(**change))


def test_authorized_target_and_schema(authorized):
    env, url = authorized
    assert validate_target(env) == url
    schema = url.update_query_dict({"options": "-csearch_path=p02_test_" + "a" * 32})
    assert validate_target(env, schema) == schema


def test_libpq_redirect_environment_is_refused(authorized):
    env, _ = authorized
    env["PGHOSTADDR"] = "192.0.2.1"
    with pytest.raises(UnsafeTestTarget):
        validate_target(env)


def test_external_network_is_refused_without_connection():
    import socket

    with socket.socket() as connection:
        with pytest.raises(pytest.fail.Exception, match="externe"):
            connection.connect(("192.0.2.1", 443))


@pytest.mark.parametrize("kind", ["absent", "contradictory", "tampered", "bad_json"])
def test_absent_or_contradictory_authorization(authorized, kind):
    from pathlib import Path

    env, url = authorized
    if kind == "absent":
        env.pop("P14_TEST_AUTHORIZATION")
    elif kind == "contradictory":
        env["DATABASE_URL"] = url.set(database="dreams_local").render_as_string(False)
    else:
        Path(env["P14_TEST_AUTHORIZATION"]).write_text(
            "not-json" if kind == "bad_json" else json.dumps({"version": 1, "target": "wrong"}))
    with pytest.raises(UnsafeTestTarget) as caught:
        validate_target(env)
    assert "fictitious-only" not in str(caught.value)


def test_inherited_configuration_is_sanitized():
    source = dict(DATABASE_URL="personal", TEST_DATABASE_URL="personal", PGSERVICE="private",
                  PGPASSWORD="private", RUN_EMOTION_REAL="1", HF_TOKEN="private",
                  IMAGE_RECEIPT_PATH="personal", STT_MODEL_PATH="personal",
                  PYTEST_ADDOPTS="--allow-real-ai", PYTEST_PLUGINS="unsafe_plugin",
                  HTTP_PROXY="private", EMOTION_ENABLED="1", PATH="preserved")
    env = clean_environment(source)
    assert env["DATABASE_URL"] == env["TEST_DATABASE_URL"] == ""
    assert env["PYTHON_DOTENV_DISABLED"] == "1" and env["EMOTION_ENABLED"] == "0"
    assert env["HF_HUB_OFFLINE"] == "1" and env["PATH"] == "preserved"
    assert not any(k in env for k in ["PGSERVICE", "PGPASSWORD", "RUN_EMOTION_REAL",
                                    "HF_TOKEN", "HTTP_PROXY", "IMAGE_RECEIPT_PATH",
                                    "STT_MODEL_PATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"])
    assert source["DATABASE_URL"] == "personal"


def test_unit_cannot_open_postgresql(monkeypatch):
    # Une restauration des mocks du test ne doit pas enlever le garde indépendant.
    monkeypatch.undo()
    with pytest.raises(pytest.fail.Exception, match="unitaire"):
        psycopg.connect(host="127.0.0.1", dbname="dreams_local")


def test_unit_cannot_bypass_driver_guard_with_connection_class():
    with pytest.raises(pytest.fail.Exception, match="unitaire"):
        psycopg.Connection.connect(host="127.0.0.1", dbname="dreams_local")


@pytest.mark.parametrize("script", ["image_job_bridge.py", "emotion_cpu_child.py",
                                   "backend.app.stt_provider"])
def test_real_ai_subprocess_refused(script):
    with pytest.raises(pytest.fail.Exception, match="IA réel"):
        subprocess.Popen([sys.executable, script])


def test_actual_server_identity_checked(authorized):
    env, url = authorized

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql):
            assert sql.startswith("SELECT current_database()")

        def fetchone(self):
            return "dreams_local", url.username, url.port, "untrusted"

    class Connection:
        def cursor(self):
            return Cursor()

    with pytest.raises(UnsafeTestTarget):
        verify_server(Connection(), env)


def test_dotenv_disabled_before_application_import():
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"


def test_real_model_import_is_refused():
    with pytest.raises(pytest.fail.Exception, match="IA réel"):
        importlib.import_module("faster_whisper")


@pytest.mark.integration
def test_driver_rejects_personal_target_before_opening_socket(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://fiction@127.0.0.1:5434/dreams_local")
    with pytest.raises(UnsafeTestTarget):
        psycopg.connect(host="127.0.0.1", port=5434, dbname="dreams_local",
                        user="fiction", password="fictitious-only")


@pytest.mark.integration
def test_driver_rejects_implicit_service_without_connection():
    with pytest.raises(pytest.fail.Exception, match="ambiguë"):
        psycopg.connect(service="untrusted")


@pytest.mark.parametrize("inherited_option", [False, True])
def test_inherited_opt_in_never_enables_real_qualification(tmp_path, inherited_option):
    env = clean_environment()
    env["RUN_EMOTION_REAL"] = "1"
    if inherited_option:
        env["PYTEST_ADDOPTS"] = "--allow-real-ai"
    result = subprocess.run([
        sys.executable, "-m", "pytest", "backend/tests/test_emotion_real.py",
        "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "child-pytest"), "-q",
    ], env=env, capture_output=True, timeout=30)
    if inherited_option:
        assert result.returncode == 4  # Option venant de l'environnement, pas de la CLI.
    else:
        assert result.returncode == 0 and b"1 skipped" in result.stdout
