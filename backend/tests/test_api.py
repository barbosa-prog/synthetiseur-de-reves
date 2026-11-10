"""Tests du contrat public et des erreurs ; aucune dépendance externe."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.app.main import create_app


@pytest.fixture
def client():
    """Crée un client isolé par test."""
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok", "service": "synthetiseur-de-reves-api", "version": "0.1.0"
    }


@pytest.mark.parametrize("path", ["/", "/health", "/api/v1/unknown", "/api/v1/dreams"])
def test_missing_route(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Ressource introuvable."}
    }


def test_wrong_method(client):
    response = client.post("/api/v1/health")
    assert response.status_code == 405
    assert "GET" in response.headers["allow"]
    assert response.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize("path", ["/api/v1/docs", "/api/v1/redoc"])
def test_documentation(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/api/v1/openapi.json" in response.text


def test_openapi_contract(client):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/auth/login" in schema["paths"]
    responses = schema["paths"]["/api/v1/health"]["get"]["responses"]
    assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/HealthResponse"
    )
    for status in ["404", "405", "422", "500"]:
        assert responses[status]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/ErrorResponse"
        )


def test_validation_does_not_echo_private_input():
    application = create_app()

    class TestPayload(BaseModel):
        count: int

    # Route de test uniquement : aucun endpoint artificiel dans l'API livrée.
    @application.post("/_test/validation")
    def validate(payload: TestPayload):
        return payload

    with TestClient(application) as test_client:
        response = test_client.post("/_test/validation", json={"count": "PRIVATE_DREAM"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "PRIVATE_DREAM" not in response.text


def test_http_error_preserves_headers_and_hides_details():
    application = create_app()

    @application.get("/_test/http-error")
    def fail():
        raise HTTPException(401, "PRIVATE_TOKEN", headers={"WWW-Authenticate": "Bearer"})

    with TestClient(application) as test_client:
        response = test_client.get("/_test/http-error")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"
    assert "PRIVATE_TOKEN" not in response.text


def test_internal_error_is_generic():
    application = create_app()

    @application.get("/_test/crash")
    def crash():
        raise RuntimeError("PRIVATE_SECRET")

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/_test/crash")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Une erreur interne est survenue."}
    }
    assert "PRIVATE_SECRET" not in response.text
