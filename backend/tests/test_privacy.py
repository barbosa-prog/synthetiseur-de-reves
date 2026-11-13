"""Notice P13 publique et statique, sans base ni contenu personnel."""

from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import get_db
from backend.app.main import create_app
from backend.app.web.security import SESSION_COOKIE


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("WEB_ORIGIN", "https://localhost:8443")
    app = create_app()

    def forbidden_database():
        pytest.fail("La notice et les pages publiques ne doivent pas consulter PostgreSQL")
        yield

    app.dependency_overrides[get_db] = forbidden_database
    with TestClient(app, base_url="https://localhost:8443") as browser:
        yield browser


def test_public_notice_without_database_or_authentication(client):
    response = client.get("/confidentialite")
    assert response.status_code == 200
    assert '<html lang="fr">' in response.text
    assert "Confidentialité" in response.text
    assert "no-store" in response.headers["cache-control"]
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_notice_never_reflects_query_headers_or_session(client):
    marker = "fiction-private-P13-unique"
    token = "Q" * 43
    client.cookies.set(SESSION_COOKIE, token)
    response = client.get("/confidentialite", params={"recit": marker, "email": marker},
                          headers={"Authorization": "Bearer " + marker, "X-Private": marker})
    assert response.status_code == 200
    assert marker not in response.text
    assert token not in response.text


@pytest.mark.parametrize("path", ["/connexion", "/inscription", "/confidentialite"])
def test_footer_and_registration_links(client, path):
    html = client.get(path).text
    assert 'href="/confidentialite"' in html
    if path == "/inscription":
        assert html.count('href="/confidentialite"') == 2
        assert "Avant de créer votre compte" in html


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(value for key, value in attrs
                         if key in {"src", "href", "action", "srcset"} and value)


def test_notice_contains_only_local_resources(client):
    parser = Resources()
    parser.feed(client.get("/confidentialite").text)
    assert parser.urls
    for url in parser.urls:
        parts = urlsplit(url)
        assert not parts.netloc or parts.netloc == "localhost:8443"
        assert parts.scheme in {"", "https"}


def test_notice_distinguishes_present_rules_and_proposals(client):
    html = client.get("/confidentialite").text
    for text in ["Identité du responsable", "Bases juridiques", "à compléter",
                 "Propositions non activées", "huit heures", "quinze minutes",
                 "vingt-quatre heures", "n’est pas automatiquement effacé",
                 "pas encore de suppression complète du compte", "sauvegardes",
                 "ni un diagnostic ni un avis médical", "aucun délai automatique"]:
        assert text in html
    assert "ni des garanties actuelles" in html


def test_notice_get_does_not_enable_post_action(client):
    assert client.post("/confidentialite").status_code == 405


def test_notice_preserves_https_origin_controls(client):
    assert client.get("http://localhost:8443/confidentialite").status_code == 400
    assert client.get("/confidentialite", headers={"Host": "evil.example"}).status_code == 400
