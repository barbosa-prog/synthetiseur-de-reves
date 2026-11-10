"""Primitives et refus avant connexion DB ; toutes les valeurs sont fictives."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.auth_schemas import Credentials, DreamUpdate
from backend.app.main import create_app
from backend.app.security import hash_password, new_token, token_digest, verify_password


def test_argon2id_and_random_salt():
    password = "fictional passphrase for tests"
    first, second = hash_password(password), hash_password(password)
    assert first.startswith("$argon2id$")
    assert first != second
    assert password not in first
    assert verify_password(first, password)
    assert not verify_password(first, "another fictional passphrase")
    assert not verify_password(None, password)
    assert not verify_password("corrupt hash", password)


def test_opaque_tokens():
    first, second = new_token(), new_token()
    assert len(first) == 43 and first != second
    assert len(token_digest(first)) == 64
    assert first not in token_digest(first)


def test_credentials_mask_password_and_normalize_email():
    credentials = Credentials(email="Fiction@EXAMPLE.COM", password="fictional passphrase")
    assert credentials.email == "fiction@example.com"
    assert "fictional passphrase" not in repr(credentials)


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_password_length(password):
    with pytest.raises(ValidationError):
        Credentials(email="fiction@example.com", password=password)


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/auth/session"), ("POST", "/api/v1/auth/logout"),
    ("GET", f"/api/v1/dreams/{uuid.uuid4()}"),
    ("PATCH", f"/api/v1/dreams/{uuid.uuid4()}"),
    ("DELETE", f"/api/v1/dreams/{uuid.uuid4()}"),
])
def test_missing_authentication_before_database(method, path):
    with TestClient(create_app()) as client:
        response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


def test_invalid_token_and_query_token_are_refused():
    with TestClient(create_app()) as client:
        for headers in [{}, {"Authorization": "Bearer invalid"},
                        {"Authorization": "Basic fictitious"}]:
            response = client.get("/api/v1/auth/session?access_token=fictitious", headers=headers)
            assert response.status_code == 401


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_correction_is_rejected(value):
    with pytest.raises(ValidationError):
        DreamUpdate(transcript=value)


def test_database_failure_is_generic(monkeypatch):
    def fail():
        raise ValueError("PRIVATE_CONNECTION_URL")

    monkeypatch.setattr("backend.app.auth.make_engine", fail)
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/auth/login", json={
            "email": "fiction@example.com", "password": "fictional passphrase",
        })
    assert response.status_code == 503
    assert "PRIVATE_CONNECTION_URL" not in response.text
