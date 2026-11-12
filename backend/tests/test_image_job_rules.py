"""Règles de file image testables sans base ni moteur IA."""

from types import SimpleNamespace

import pytest

from backend.app.services.image_jobs import _fail, claim


@pytest.mark.parametrize("timeout", [0, 29, 601, True, "120"])
def test_invalid_lease_timeout_never_opens_database(timeout):
    def forbidden():
        raise AssertionError("Connexion non attendue")

    with pytest.raises(ValueError, match="Délai image invalide"):
        claim(forbidden, timeout)


def test_terminal_cleanup_revokes_reservation():
    job = SimpleNamespace(status="running", claim_token="fake", lease_until="fake")
    _fail(job, "synthetic-time", "cancelled")
    assert job.status == "failed" and job.finished_at == "synthetic-time"
    assert job.claim_token is None and job.lease_until is None
