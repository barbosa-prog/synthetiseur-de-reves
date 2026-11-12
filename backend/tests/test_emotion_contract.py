"""P08 synthétique : ni PostgreSQL, ni modèle, ni réseau."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.emotion_provider import EmotionError, EmotionRequest, EmotionResult, analyze
from backend.app.emotion_rules import (
    EmotionState,
    accept,
    begin_analysis,
    choose,
    publish,
    text_changed,
)


class FakeEmotionProvider:
    """Réponse configurée, déterministe ; aucune prétention d'analyse linguistique."""

    def __init__(self, emotion="heureux", reason=None):
        self.emotion, self.reason = emotion, reason

    def analyze(self, request):
        return EmotionResult(request_id=request.request_id, text_version=request.text_version,
                             choice_revision=request.choice_revision, emotion=self.emotion,
                             abstention_reason=self.reason, engine="fake", model_revision="1")


def start(state=None, identifier=None):
    state = state or EmotionState(text_version=1)
    return begin_analysis(state, "Un récit entièrement fictif.",
                          identifier or uuid4(), state.revision)


def complete(state=None, emotion="heureux", reason=None):
    state, request = start(state)
    result = analyze(FakeEmotionProvider(emotion, reason), request)
    return publish(state, result)


@pytest.mark.parametrize("emotion", ["heureux", "stressant", "neutre", "triste", "autre"])
def test_five_values_and_explicit_acceptance(emotion):
    state = complete(emotion=emotion)
    assert state.value is None and state.source == "unset"
    selected = accept(state, state.suggestion.request_id, state.revision)
    assert selected.source == "accepted" and selected.value == emotion
    assert complete(selected, "triste").value == emotion


@pytest.mark.parametrize("reason", ["ambiguous", "insufficient_information"])
def test_abstention_is_not_neutral_or_other(reason):
    state = complete(emotion=None, reason=reason)
    assert state.value is None and state.source == "unset"
    assert state.suggestion.abstention_reason == reason
    with pytest.raises(EmotionError, match="stale_result"):
        accept(state, state.suggestion.request_id, state.revision)


@pytest.mark.parametrize("text", ["", " \n\t", "x"*20001, "fiction\x00", "\ud800"])
def test_invalid_text_rejected_before_engine(text):
    with pytest.raises(ValidationError):
        begin_analysis(EmotionState(text_version=1), text, uuid4(), 0)


def test_request_normalization_privacy_immutability_and_determinism():
    identifier = UUID(int=1)
    _, request = begin_analysis(EmotionState(text_version=1), " fiction\r\nrêve ", identifier, 0)
    assert request.text == "fiction\nrêve" and request.text not in repr(request)
    engine = FakeEmotionProvider()
    assert analyze(engine, request) == analyze(engine, request)
    with pytest.raises(ValidationError):
        request.text = "changed"
    with pytest.raises(ValidationError):
        EmotionRequest(request_id=identifier, text="fiction", text_version=0, choice_revision=0)


@pytest.mark.parametrize("value", ["heureux", "triste", None])
def test_manual_choice_during_analysis_invalidates_late_result(value):
    state, request = start()
    result = analyze(FakeEmotionProvider(), request)
    manual = choose(state, value, state.revision)
    with pytest.raises(EmotionError, match="stale_result"):
        publish(manual, result)
    assert manual.value == value
    assert complete(manual).value == value
    assert complete(manual).source == ("withdrawn" if value is None else "manual")


def test_identical_manual_value_still_protected():
    automatic = complete()
    manual = choose(automatic, "heureux", automatic.revision)
    assert manual.source == "manual" and manual.revision > automatic.revision
    assert complete(manual, "stressant").value == "heureux"


@pytest.mark.parametrize("source", ["manual", "accepted", "legacy", "withdrawn"])
def test_text_change_preserves_protected_choices(source):
    state = EmotionState(text_version=1, source=source,
                         value=None if source == "withdrawn" else "triste",
                         selected_text_version=None if source == "withdrawn" else 1)
    updated = text_changed(complete(state), 2)
    assert updated.value == state.value and updated.source == source
    assert updated.suggestion is None
    assert updated.selected_text_version == state.selected_text_version
    assert complete(updated).value == state.value


def test_text_change_clears_auto_and_late_result():
    state = complete()
    waiting, request = start(state)
    updated = text_changed(waiting, 2)
    assert updated.value is None and updated.source == "unset" and updated.suggestion is None
    with pytest.raises(EmotionError, match="stale_result"):
        publish(updated, analyze(FakeEmotionProvider(), request))
    assert text_changed(updated, 2) is updated
    with pytest.raises(EmotionError):
        text_changed(updated, 1)


def test_duplicate_and_superseded_results_and_revision_conflicts():
    state, first = start()
    state, second = start(state)
    with pytest.raises(EmotionError, match="stale_result"):
        publish(state, analyze(FakeEmotionProvider(), first))
    result = analyze(FakeEmotionProvider(), second)
    state = publish(state, result)
    with pytest.raises(EmotionError):
        publish(state, result)
    for operation in (lambda: choose(state, "triste", 0),
                      lambda: accept(state, result.request_id, 0),
                      lambda: begin_analysis(state, "fiction", uuid4(), 0)):
        with pytest.raises(EmotionError, match="choice_conflict"):
            operation()
    with pytest.raises(EmotionError):
        accept(state, uuid4(), state.revision)


@pytest.mark.parametrize("changes", [{"emotion": "peur"}, {"emotion": None},
                                    {"abstention_reason": "ambiguous"},
                                    {"text_version": True}, {"surprise": "x"}])
def test_invalid_result_contract(changes):
    _, request = start()
    result = FakeEmotionProvider().analyze(request)
    with pytest.raises(ValidationError):
        EmotionResult.model_validate({**result.model_dump(), **changes})


def test_provider_failure_invalid_and_forged_outputs_are_sanitized():
    _, request = start()

    class Broken:
        def analyze(self, request):
            raise RuntimeError("private fiction must not escape")

    with pytest.raises(EmotionError, match="^provider_failed$") as failure:
        analyze(Broken(), request)
    assert failure.value.__suppress_context__

    class Invalid:
        def analyze(self, request):
            return {"emotion": "heureux"}

    with pytest.raises(EmotionError, match="invalid_result"):
        analyze(Invalid(), request)

    class Forged:
        def analyze(self, request):
            return FakeEmotionProvider().analyze(request).model_copy(update={"emotion": "wrong"})

    with pytest.raises(EmotionError, match="invalid_result"):
        analyze(Forged(), request)

    class Stale:
        def analyze(self, request):
            return FakeEmotionProvider().analyze(request).model_copy(update={"text_version": 2})

    with pytest.raises(EmotionError, match="stale_result"):
        analyze(Stale(), request)


def test_manual_values_and_state_invariants_validated():
    state = EmotionState(text_version=1)
    with pytest.raises(ValidationError):
        choose(state, "invalid", 0)
    with pytest.raises(ValidationError):
        EmotionState(text_version=1, value="neutre")
    with pytest.raises(ValidationError):
        EmotionState(text_version=1, source="automatic", value="neutre", selected_text_version=1)
