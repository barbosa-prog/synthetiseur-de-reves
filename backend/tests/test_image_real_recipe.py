"""Préparation de recette : aucune connexion PostgreSQL ni exécution GPU."""

import os

import pytest
from sqlalchemy import URL

from scripts.verify_image_real import (
    FICTIONAL_EMAILS,
    check_isolation,
    isolated_environment,
    require,
)


def configuration(tmp_path):
    base = tmp_path/"SynthetiseurDeReves"
    directory = base/"p07-real-unit"
    url = URL.create("postgresql+psycopg", username="real_fictional", password="fictional-only",
                     host="127.0.0.1", port=59417, database="p07_real_unit")
    private = directory/"private-media"
    env = isolated_environment(url, private, base/"p07-qualification", base/"receipt.json")
    return env, url, directory, base, directory/"data", private


def test_temporary_target_accepted(tmp_path):
    check_isolation(*configuration(tmp_path))


@pytest.mark.parametrize("port", [None, 5432, 5433, 5434])
def test_personal_ports_refused_before_connection(tmp_path, port):
    env, url, *paths = configuration(tmp_path)
    url = url.set(port=port) if port else URL.create(
        "postgresql+psycopg", username="real_fictional", password="fictional-only",
        host="127.0.0.1", database="p07_real_unit")
    env["DATABASE_URL"] = url.render_as_string(hide_password=False)
    with pytest.raises(RuntimeError, match="unsafe_port"):
        check_isolation(env, url, *paths)


@pytest.mark.parametrize("kind", ["database", "storage", "root", "role"])
def test_mismatched_target_fails_closed(tmp_path, kind):
    env, url, directory, base, data, private = configuration(tmp_path)
    if kind == "database":
        env["DATABASE_URL"] = url.set(port=5434).render_as_string(hide_password=False)
    elif kind == "storage":
        env["PRIVATE_MEDIA_ROOT"] = str(base/"private_media")
    elif kind == "root":
        directory = base/"personal"
    else:
        url = url.set(username="personal")
    with pytest.raises(RuntimeError):
        check_isolation(env, url, directory, base, data, private)


def test_inherited_personal_configuration_not_mutated_or_forwarded(tmp_path, monkeypatch):
    monkeypatch.setenv("PGSERVICE", "personal")
    monkeypatch.setenv("PGPORT", "5434")
    monkeypatch.setenv("DATABASE_URL", "fictional-personal-config")
    before = dict(os.environ)
    env, url, *_ = configuration(tmp_path)
    assert env["DATABASE_URL"] == env["TEST_DATABASE_URL"]
    assert "PGSERVICE" not in env and "PGPORT" not in env
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    assert dict(os.environ) == before


def test_safety_check_is_not_an_assertion():
    with pytest.raises(RuntimeError, match="test_guard"):
        require(False, "test_guard")


def test_recipe_credentials_pass_existing_auth_validation():
    from backend.app.auth_schemas import Credentials
    assert len(set(FICTIONAL_EMAILS)) == 2
    for email in FICTIONAL_EMAILS:
        validated = Credentials(email=email, password="fictitious passphrase only")
        assert str(validated.email) == email


@pytest.mark.parametrize("email", ["real-owner@example.test", "real-other@example.test"])
def test_previous_fixture_reproduces_422_without_database(email):
    from fastapi.testclient import TestClient

    from backend.app.auth import get_db
    from backend.app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app, base_url="https://localhost:8443") as client:
        response = client.post("/api/v1/auth/register", json={
            "email": email, "password": "fictitious passphrase only"})
        assert response.status_code == 422
