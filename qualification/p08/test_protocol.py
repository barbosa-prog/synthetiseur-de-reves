"""Tests sans chargement de poids, tokenizer ni accès au réseau."""

from dataset import LABELS, cases
from evaluate import metrics, predict


def test_split_and_balance():
    data = cases()
    assert len(data) == 40 and len({row["id"] for row in data}) == 40
    assert sum(row["group"] == "ambiguous" for row in data) == 10
    assert sum(row["group"] == "incomplete" for row in data) == 5
    for label in LABELS:
        assert sum(r["expected"] == label and r["split"] == "dev" for r in data) == 2
        assert sum(r["expected"] == label and r["split"] == "test" for r in data) == 3
    assert not ({r["text"] for r in data if r["split"] == "dev"}
                & {r["text"] for r in data if r["split"] == "test"})


def test_abstention_and_classification():
    assert predict(None, 0.55, 0.05) is None
    assert predict([0.2]*5, 0.55, 0.05) is None
    assert predict([0.58, 0.57, 0, 0, 0], 0.55, 0.05) is None
    assert predict([0.9, 0.025, 0.025, 0.025, 0.025], 0.55, 0.05) == "heureux"


def test_metrics_count_abstention_as_missed_recall():
    perfect = [dict(expected=label, prediction=label) for label in LABELS]
    assert metrics(perfect)["macro_f1"] == 1
    absent = [dict(expected=label, prediction=None) for label in LABELS]
    report = metrics(absent)
    assert report["macro_f1"] == 0 and report["abstention_rate"] == 1
    assert all(report["matrix"][label]["abstention"] == 1 for label in LABELS)
