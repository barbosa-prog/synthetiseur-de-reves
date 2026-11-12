"""Contrôles du corpus et protocole comparatif sans inférence."""

import json
from pathlib import Path

from compare_b import summarize
from confirmation import confirmation_cases
from dataset import LABELS, cases


def test_confirmation_balance_and_no_explicit_overlap():
    new = confirmation_cases()
    assert len(new) == 25 and len({r["id"] for r in new}) == 25
    for label in LABELS:
        assert sum(r["expected"] == label for r in new) == 3
    assert sum(r["group"] == "undetermined" for r in new) == 5
    assert sum(r["group"] == "incomplete" for r in new) == 5
    old_texts = {r["text"] for r in cases() if r["group"] == "explicit"}
    assert not old_texts & {r["text"] for r in new if r["group"] == "explicit"}
    assert all(r["split"] == "confirmation" for r in new)


def test_frozen_baseline_and_group_metrics():
    baseline = json.loads(Path(__file__).with_name("results.json").read_text(encoding="utf-8"))
    parameters = baseline["parameters"]
    assert parameters["threshold"] == 0.55 and parameters["margin"] == 0.05
    assert parameters["chunk_tokens"] == 300 and parameters["min_tokens"] == 5
    assert parameters["variant"] == 0
    rows = [{**r, "prediction": r["expected"]} for r in confirmation_cases()]
    summary = summarize(rows)
    assert summary["explicit"]["accuracy"] == 1
    assert summary["groups"]["undetermined"]["abstention_rate"] == 1
    assert summary["groups"]["incomplete"]["incompatible"] == []
