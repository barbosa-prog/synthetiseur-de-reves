"""Bornes P09 et requêtes invalides sans ouvrir de connexion PostgreSQL."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.auth import current_user, get_db
from backend.app.history_schemas import HistoryQuery
from backend.app.main import create_app


@pytest.mark.parametrize("params", [
    {"page": 0}, {"page": -1}, {"page": 10001}, {"page_size": 0}, {"page_size": 51},
    {"page": "1.0"}, {"page": "1e2"}, {"page": "abc"}, {"page": ""}, {"page_size": "1.2"},
    {"emotion": "NULL"}, {"emotion": "non renseignée"}, {"emotion": ""}, {"emotion": "invalid"},
    {"user_id": "another-user"},
])
def test_invalid_parameters_fail_before_history_query(params):
    app = create_app()
    app.dependency_overrides[current_user] = lambda: object()
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.get("/api/v1/dreams", params=params).status_code == 422


def test_service_query_defaults_and_strict_types():
    assert HistoryQuery().page_size == 12
    assert HistoryQuery(page="2").page == 2
    assert HistoryQuery(page=10000, page_size=50).page == 10000
    for value in (True, 1.0, None):
        with pytest.raises(ValidationError):
            HistoryQuery(page=value)


def test_collection_response_is_not_cached_even_without_authentication():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/dreams")
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
