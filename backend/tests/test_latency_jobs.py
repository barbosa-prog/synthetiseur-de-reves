"""Mesures sur jobs réels et faux fournisseurs, erreurs et quota compris."""

import json
import logging

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.models import Job
from backend.app.services import ai_quota
from backend.tests import test_worker_jobs_p11 as cases
from backend.tests.test_ai_quota import new_job
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_stt import FakeProvider

env = cases.env


@pytest.mark.parametrize("kind", ["stt", "image"])
@pytest.mark.parametrize("error", [None, "timeout"])
def test_latency_distinguishes_provider_failure_from_handled_job(env, kind, error, caplog):
    identifier = cases.queue(env, kind)
    provider = FakeProvider(error=error) if kind == "stt" else FakeEngine(error=error)
    with caplog.at_level(logging.WARNING):
        assert cases.execute(env, kind, provider)
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "dreams.latency"]
    assert [(e["phase"], e["outcome"]) for e in events] == [
        ("queue", "admitted"), ("provider", "raised" if error else "returned"),
        ("worker", "handled")]
    assert all(e["kind"] == kind and e["duration_ms"] >= 0 for e in events)
    with env[2]() as db:
        assert db.get(Job, identifier).status == ("failed" if error else "done")


def test_quota_rejection_does_not_emit_a_false_admission(env, caplog):
    with env[2]() as db:
        ai_quota.configure(db, 1)
        db.commit()
    cases.queue(env, "stt")
    assert cases.execute(env, "stt")
    caplog.clear()
    with caplog.at_level(logging.WARNING), pytest.raises(HTTPException) as error:
        # La STT a changé la version du premier rêve : utiliser une entrée image
        # valide et nouvelle pour éprouver le quota, plutôt qu'un conflit 409.
        new_job(env, "image")
    assert error.value.status_code == 429
    assert not [r for r in caplog.records if r.name == "dreams.latency"]
    with env[2]() as db:
        jobs = list(db.scalars(select(Job)))
        assert len(jobs) == 1 and jobs[0].attempts == 1
