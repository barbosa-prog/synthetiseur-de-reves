"""P17 : quantiles connus, logs fermés et propagation des erreurs sans contenu."""

import json
import logging

import pytest

from backend.app import latency
from backend.app.safe_logging import install_safe_logging
from backend.app.stt_provider import STTConfig, STTError
from scripts.performance_stats import percentile, summarize


def test_empirical_r7_percentiles_and_unsorted_samples():
    assert percentile([4, 1, 3, 2], 50) == 2.5
    assert percentile([4, 1, 3, 2], 95) == pytest.approx(3.85)
    assert percentile([7], 95) == 7
    assert percentile([3, 1], 0) == 1
    assert percentile([3, 1], 100) == 3
    assert summarize([1, 2, 3, 4]) == dict(n=4, p50_ms=2.5, p95_ms=3.85, min_ms=1, max_ms=4)


@pytest.mark.parametrize("samples,percent", [
    ([], 50), ([float("nan")], 50), ([float("inf")], 50), ([-1], 50),
    ([True], 50), (["secret"], 50), ([1], -1), ([1], 101), ([1], float("nan")),
])
def test_invalid_samples_are_not_silently_dropped(samples, percent):
    with pytest.raises(ValueError):
        percentile(samples, percent)


def test_provider_log_records_duration_but_never_exception_content(monkeypatch, caplog):
    install_safe_logging()
    clock = iter([10.0, 10.125])
    monkeypatch.setattr(latency, "perf_counter", lambda: next(clock))
    private_error = RuntimeError("PRIVATE_STORY_PROMPT_TOKEN")
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as error:
        with latency.provider_latency("stt"):
            raise private_error
    assert error.value is private_error
    record = next(r for r in caplog.records if r.name == "dreams.latency")
    assert json.loads(record.getMessage()) == dict(event="job_latency", kind="stt",
        phase="provider", duration_ms=125.0, outcome="raised")
    assert "PRIVATE" not in caplog.text
    assert record.exc_info is record.stack_info is None


@pytest.mark.parametrize("extra", [
    {"prompt": "PRIVATE"}, {"duration_ms": float("nan")}, {"duration_ms": True},
    {"kind": "PRIVATE_USER_ID"}, {"outcome": "PRIVATE_EXCEPTION"}, {"event": ["job_latency"]},
])
def test_latency_logger_rejects_unknown_fields_and_values(extra, caplog):
    install_safe_logging()
    payload = dict(event="job_latency", kind="image", phase="provider",
                   duration_ms=1.0, outcome="returned")
    with caplog.at_level(logging.WARNING):
        logging.getLogger("dreams.latency").warning({**payload, **extra})
    assert caplog.records[-1].getMessage() == "diagnostic_redacted"
    assert "PRIVATE" not in caplog.text


def test_logging_destination_failure_does_not_change_worker_result(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("PRIVATE_LOG_DESTINATION")

    monkeypatch.setattr(logging.getLogger("dreams.latency"), "warning", fail)

    @latency.worker_latency("image")
    def work():
        return True

    assert work() is True


def test_remote_stt_engine_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("STT_ENGINE", "paid-remote-api")
    with pytest.raises(STTError, match="configuration"):
        STTConfig.from_environment()


def test_idle_worker_does_not_flood_latency_logs(caplog):
    install_safe_logging()

    @latency.worker_latency("stt")
    def idle():
        return False

    with caplog.at_level(logging.WARNING):
        assert idle() is False
    assert not [r for r in caplog.records if r.name == "dreams.latency"]


def test_interrupted_provider_propagates_and_logs_no_details(caplog):
    install_safe_logging()
    with caplog.at_level(logging.WARNING), pytest.raises(KeyboardInterrupt):
        with latency.provider_latency("image"):
            raise KeyboardInterrupt("PRIVATE_INTERRUPTION")
    event = json.loads(next(r.getMessage() for r in caplog.records if r.name == "dreams.latency"))
    assert event["outcome"] == "interrupted"
    assert "PRIVATE" not in caplog.text
