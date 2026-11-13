"""P11 pur : horloge injectée, identités fictives, aucun accès PostgreSQL ou IA."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.job_rules import (
    NON_RETRYABLE,
    RETRYABLE,
    TRANSITIONS,
    EngineIdentity,
    Inputs,
    JobRuleError,
    JobState,
    Policy,
    _move,
    content_digest,
    failure,
    finish,
    public_progress,
    recover,
    refresh_emotion_context,
    request_job,
    reserve,
    retry,
)

NOW = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
TOKEN = UUID(int=4)
ENGINE = EngineIdentity(engine="fake", model_revision="fictitious-1",
                        policy_revision="p11-v1", settings_digest="a" * 64)


def inputs(kind="stt", **changes):
    data = dict(owner_id=UUID(int=1), dream_id=UUID(int=2), kind=kind,
                text_version=0 if kind == "stt" else 1, engine=ENGINE)
    if kind == "stt":
        data.update(media_id=UUID(int=3), media_sha256="b" * 64)
    else:
        data["text_digest"] = content_digest("Un récit entièrement fictif.")
        if kind == "image":
            data.update(description_digest=content_digest("Une forêt fictive.", limit=500),
                        description_version=1)
    return Inputs(**{**data, **changes})


def queued(kind="stt"):
    return request_job(inputs(kind), NOW, explicit=True,
                       choice_revision=0 if kind == "emotion" else None)


def running(kind="stt"):
    state = queued(kind)
    return reserve(state, NOW, TOKEN, inputs=state.inputs,
                   choice_revision=state.choice_revision)


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_complete_cycle_and_immutable_state(kind):
    before = queued(kind)
    active = reserve(before, NOW, TOKEN, inputs=before.inputs,
                     choice_revision=before.choice_revision)
    completed = finish(active, NOW + timedelta(seconds=1), TOKEN, inputs=active.inputs,
                       choice_revision=active.choice_revision)
    assert before.status == "queued" and before.attempts == 0
    assert active.status == "running" and active.attempts == 1
    assert completed.status == "done" and completed.outcome == "result"
    assert completed.claim_token is completed.lease_until is None
    with pytest.raises(ValidationError):
        completed.attempts = 0


@pytest.mark.parametrize("source,target", [(a, b) for a in TRANSITIONS
                                          for b in TRANSITIONS if b not in TRANSITIONS[a]])
def test_forbidden_transition_graph(source, target):
    states = {"queued": queued(), "running": running()}
    states["failed"] = failure(states["running"], "timeout")
    states["done"] = finish(states["running"], NOW, TOKEN, inputs=inputs())
    with pytest.raises(JobRuleError, match="invalid_transition"):
        _move(states[source], target)


def test_two_explicit_retries_three_executions_and_no_new_uuid_reset():
    state = queued()
    for index in range(3):
        state = reserve(state, NOW + timedelta(seconds=index), UUID(int=10 + index),
                        inputs=state.inputs)
        state = finish(state, NOW + timedelta(seconds=index), UUID(int=10 + index),
                       inputs=state.inputs, error="timeout")
        assert state.attempts == index + 1
        with pytest.raises(JobRuleError, match="retry_required"):
            request_job(state.inputs, NOW, explicit=True, previous=state)
        if index < 2:
            state = retry(state, NOW + timedelta(seconds=index), inputs=state.inputs, explicit=True)
    assert state.attempts == 3 and state.retry_count == 2
    with pytest.raises(JobRuleError, match="budget_exhausted"):
        retry(state, NOW + timedelta(seconds=3), inputs=state.inputs, explicit=True)


def test_unclaimed_queue_failures_also_have_two_retry_budget():
    policy = Policy(queued_seconds=60)
    state, now = queued(), NOW
    for index in range(3):
        now += timedelta(seconds=60)
        state = recover(state, now, inputs=state.inputs, policy=policy)
        assert state.status == "failed" and state.attempts == 0
        if index < 2:
            state = retry(state, now, inputs=state.inputs, explicit=True)
    with pytest.raises(JobRuleError, match="budget_exhausted"):
        retry(state, now, inputs=state.inputs, explicit=True)


@pytest.mark.parametrize("error", sorted(RETRYABLE))
def test_retryable_codes_require_explicit_action(error):
    state = failure(running(), error)
    with pytest.raises(JobRuleError, match="explicit_action_required"):
        retry(state, NOW, inputs=state.inputs)
    assert retry(state, NOW, inputs=state.inputs, explicit=True).retry_count == 1


@pytest.mark.parametrize("error", sorted(NON_RETRYABLE))
def test_terminal_codes_cannot_retry_same_cycle(error):
    state = failure(running(), error)
    with pytest.raises(JobRuleError, match="not_retryable"):
        retry(state, NOW, inputs=state.inputs, explicit=True)


@pytest.mark.parametrize("status", ["queued", "running", "done", "failed"])
def test_repeated_request_does_not_create_budget(status):
    state = running() if status != "queued" else queued()
    if status == "done":
        state = finish(state, NOW, TOKEN, inputs=state.inputs)
    elif status == "failed":
        state = failure(state, "timeout")
    if status == "failed":
        with pytest.raises(JobRuleError):
            request_job(state.inputs, NOW, previous=state, explicit=True)
    else:
        assert request_job(state.inputs, NOW, previous=state, explicit=True) is state


@pytest.mark.parametrize("changed", [dict(owner_id=UUID(int=8)), dict(dream_id=UUID(int=9)),
                                     dict(text_version=1), dict(media_sha256="c" * 64),
                                     dict(engine=ENGINE.model_copy(
                                         update={"model_revision": "2"}))])
def test_changed_identity_is_not_a_retry(changed):
    state = failure(running(), "timeout")
    with pytest.raises(JobRuleError, match="stale_result"):
        retry(state, NOW, inputs=inputs(**changed), explicit=True)


def test_audio_duplicate_identity_and_image_emotion_identity():
    assert inputs().cycle_key == inputs(media_id=UUID(int=50)).cycle_key
    assert inputs("image").cycle_key != inputs("image", description_version=2).cycle_key
    assert inputs("image").cycle_key != inputs("image", description_digest="d"*64).cycle_key
    assert inputs("emotion").cycle_key != inputs("emotion", text_digest="d"*64).cycle_key
    old = failure(running(), "timeout")
    with pytest.raises(JobRuleError, match="wrong_cycle"):
        request_job(inputs(text_version=1), NOW, previous=old, explicit=True)
    assert request_job(inputs(text_version=1), NOW, explicit=True).attempts == 0


@pytest.mark.parametrize("value", ["", " ", "x" * 20001, None])
def test_invalid_contents(value):
    with pytest.raises(JobRuleError, match="invalid_input"):
        content_digest(value)


@pytest.mark.parametrize("operation", ["request", "reserve", "retry", "public"])
def test_deleted_or_purged_dream_never_rearmed(operation):
    state = queued()
    with pytest.raises(JobRuleError, match="dream_unavailable"):
        if operation == "request":
            request_job(inputs(), NOW, available=False, explicit=True)
        elif operation == "reserve":
            reserve(state, NOW, TOKEN, inputs=inputs(), available=False)
        elif operation == "retry":
            retry(failure(state, "timeout"), NOW, inputs=inputs(), available=False, explicit=True)
        else:
            public_progress(state, inputs=inputs(), available=False)


def test_fencing_stale_completion_expiry_and_duplicate_result():
    state = running()
    with pytest.raises(JobRuleError, match="reservation_lost"):
        finish(state, NOW, UUID(int=99), inputs=inputs())
    with pytest.raises(JobRuleError, match="lease_expired"):
        finish(state, state.lease_until, TOKEN, inputs=inputs())
    assert finish(state, NOW, TOKEN, inputs=inputs(text_version=1)).error_code == "stale_result"
    assert finish(state, NOW, TOKEN, inputs=inputs(), available=False).error_code == "dream_deleted"
    done = finish(state, NOW, TOKEN, inputs=inputs())
    with pytest.raises(JobRuleError, match="reservation_lost"):
        finish(done, NOW, TOKEN, inputs=inputs())


def test_queue_and_running_deadline_exact_boundaries_and_recovery_idempotence():
    state = queued()
    assert recover(state, NOW + timedelta(seconds=1799), inputs=inputs()) is state
    expired = recover(state, NOW + timedelta(seconds=1800), inputs=inputs())
    assert expired.error_code == "queue_timeout" and expired.claim_token is None
    assert recover(expired, NOW + timedelta(days=1), inputs=inputs()) is expired
    active = running()
    assert active.lease_until == NOW + timedelta(seconds=720)
    before_expiry = active.lease_until - timedelta(microseconds=1)
    assert recover(active, before_expiry, inputs=inputs()) is active
    terminal = recover(active, active.lease_until, inputs=inputs())
    assert terminal.status == "failed" and terminal.error_code == "interrupted"
    assert terminal.claim_token is terminal.lease_until is None
    assert terminal.attempts == 1 and terminal.retry_count == 0


def test_emotion_abstention_context_guard_and_no_choice_in_cycle_key():
    state = running("emotion")
    result = finish(state, NOW, TOKEN, inputs=state.inputs, choice_revision=0, abstention=True)
    assert result.status == "done" and result.outcome == "abstention"
    stale = finish(state, NOW, TOKEN, inputs=state.inputs, choice_revision=1)
    assert stale.stale and stale.status == "failed"
    with pytest.raises(JobRuleError, match="stale_result"):
        retry(stale, NOW, inputs=state.inputs, choice_revision=1, explicit=True)
    new = refresh_emotion_context(result, NOW, inputs=state.inputs,
                                  choice_revision=1, explicit=True)
    assert result.status == "done" and new.status == "queued"
    assert new.inputs.cycle_key == result.inputs.cycle_key
    assert new.attempts == 1 and new.retry_count == 1
    with pytest.raises(JobRuleError):
        refresh_emotion_context(new, NOW, inputs=new.inputs, choice_revision=2, explicit=True)


def test_public_projection_whitelist_and_business_stale_is_not_technical_state():
    state = failure(running(), "timeout")
    view = public_progress(state, inputs=inputs())
    assert set(view) == {"state", "attempts", "max_attempts", "retry_count", "max_retries",
                         "error_code", "stale", "outcome", "retryable"}
    assert view["retryable"]
    stale = public_progress(state, inputs=inputs(text_version=1))
    assert stale["state"] == "failed" and stale["stale"] and not stale["retryable"]
    assert "claim_token" not in str(view) and "cycle_key" not in str(view)
    assert failure(running(), "PRIVATE_PATH_AND_EXCEPTION").error_code == "unknown_error"


def test_naive_time_and_invalid_contracts_refused():
    with pytest.raises(JobRuleError, match="invalid_time"):
        request_job(inputs(), datetime(2026, 11, 13), explicit=True)
    with pytest.raises(JobRuleError, match="invalid_time"):
        reserve(queued(), NOW - timedelta(seconds=1), TOKEN, inputs=inputs())
    with pytest.raises(ValidationError):
        JobState(inputs=inputs(), queued_at=NOW, status="running")
    with pytest.raises(ValidationError):
        Inputs(owner_id=UUID(int=1), dream_id=UUID(int=2), kind="image",
               text_version=1, engine=ENGINE)


def test_execution_budget_independent_of_manual_counter():
    terminal = JobState(inputs=inputs(), queued_at=NOW, status="failed", attempts=3,
                        retry_count=0, error_code="interrupted")
    with pytest.raises(JobRuleError, match="budget_exhausted"):
        retry(terminal, NOW, inputs=terminal.inputs, explicit=True)


@pytest.mark.parametrize("status", ["queued", "running"])
def test_recovery_deletion_and_changed_inputs_never_execute(status):
    state = queued() if status == "queued" else running()
    unavailable = recover(state, NOW, inputs=state.inputs, available=False)
    assert unavailable.status == "failed" and unavailable.error_code == "dream_deleted"
    stale = recover(state, NOW, inputs=inputs(text_version=2))
    assert stale.stale and stale.error_code == "stale_result"
    assert unavailable.claim_token is unavailable.lease_until is None


@pytest.mark.parametrize("kind,seconds", [("stt", 720), ("image", 240), ("emotion", 240)])
def test_proposed_lease_budgets(kind, seconds):
    assert running(kind).lease_until == NOW + timedelta(seconds=seconds)


def test_new_request_refresh_and_foreign_projection_are_not_mutations():
    with pytest.raises(JobRuleError, match="explicit_action_required"):
        request_job(inputs(), NOW)
    state = failure(running(), "timeout")
    assert state.retry_count == 0
    with pytest.raises(JobRuleError, match="dream_unavailable"):
        public_progress(state, inputs=inputs(owner_id=UUID(int=999)))
    assert state.retry_count == 0


def test_emotion_context_refresh_never_resets_budget_or_admits_old_text():
    old = running("emotion")
    old = finish(old, NOW, TOKEN, inputs=old.inputs, choice_revision=0, abstention=True)
    with pytest.raises(JobRuleError, match="explicit_action_required"):
        refresh_emotion_context(old, NOW, inputs=old.inputs, choice_revision=1)
    with pytest.raises(JobRuleError, match="stale_result"):
        refresh_emotion_context(old, NOW, inputs=inputs("emotion", text_version=2),
                                choice_revision=1, explicit=True)
    capped = JobState.model_validate({**old.model_dump(), "attempts": 3})
    with pytest.raises(JobRuleError, match="budget_exhausted"):
        refresh_emotion_context(capped, NOW, inputs=capped.inputs, choice_revision=1, explicit=True)
