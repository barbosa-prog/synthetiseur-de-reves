"""Le consommateur fictif répète une réservation différée, jamais une exécution."""

import pytest

from backend.tests import browser_workers


@pytest.mark.parametrize("deferred", [None, False])
def test_wait_for_work_retries_only_until_work_is_reserved(monkeypatch, deferred):
    reservation = object()
    results = iter([deferred, reservation])
    pauses = []
    monkeypatch.setattr(browser_workers.time, "sleep", pauses.append)
    assert browser_workers.wait_for_work(lambda: next(results)) is reservation
    assert pauses == [0.05]


def test_wait_for_work_does_not_hide_worker_errors():
    def fail():
        raise RuntimeError("fake worker failed")

    with pytest.raises(RuntimeError, match="fake worker failed"):
        browser_workers.wait_for_work(fail)


def test_wait_for_work_fails_when_no_job_can_be_reserved(monkeypatch):
    ticks = iter([0, 6])
    monkeypatch.setattr(browser_workers.time, "monotonic", lambda: next(ticks))
    with pytest.raises(AssertionError, match="Aucun job réservé"):
        browser_workers.wait_for_work(lambda: None)
