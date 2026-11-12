"""Fiabilité du protocole et métriques, sans poids ni réseau."""

import pytest
from confirmation import confirmation_cases
from dataset import cases
from reliability import decide, select_parameters, summary
from reliability_data import development, final_cases
from report_c import global_suggestion_quality


def test_corpus_independence_and_balance():
    dev, test = development(), final_cases()
    assert len(dev) == 36 and len(test) == 83
    for label in ["heureux", "stressant", "neutre", "triste", "autre"]:
        assert sum(r["expected"] == label for r in dev) == 4
        assert sum(r["expected"] == label for r in test) == 10
    old_test = {r["text"] for r in cases() if r["split"] != "dev"}
    old_test |= {r["text"] for r in confirmation_cases()}
    # Invalides standards réutilisés à dessein, jamais pour régler.
    assert not {r["text"] for r in dev} & old_test
    assert not {r["text"] for r in test if r["group"] != "invalid"} & old_test
    assert not {r["text"] for r in dev} & {r["text"] for r in test}
    assert len({r["id"] for r in test}) == 83


PARAMS = dict(threshold=0.6, margin=0.15, gate_threshold=0.6, lexical_guard=True)


def raw(**changes):
    return {"invalid": None, "categories": [0.9, 0.05, 0.05, 0.05, 0.05],
            "gates": [0.1, 0.1, 0.1], "lexical_evidence": True, **changes}


@pytest.mark.parametrize("reason,index", [("undetermined", 0), ("ambiguous", 1), ("multiple", 2)])
def test_distinct_abstention_reasons(reason, index):
    gates = [0.1]*3
    gates[index] = 0.8
    assert decide(raw(gates=gates), PARAMS) == (None, reason)


def test_other_not_fallback_and_uncertainty():
    assert decide(raw(categories=[0.1]*4+[0.9]), PARAMS) == ("autre", None)
    assert decide(raw(categories=[0.1]*5), PARAMS) == (None, "uncertain_scores")
    assert decide(raw(categories=[0.8, 0.75, 0, 0, 0]), PARAMS)[0] is None
    assert decide(raw(lexical_evidence=False), PARAMS)[0] is None
    assert decide({"invalid": "invalid_text"}, PARAMS) == (None, "invalid_text")


def test_metrics_never_count_abstention_as_correct_classification():
    rows = [{**r, "prediction": None} for r in final_cases()]
    report = summary(rows)
    assert report["explicit"]["accuracy"] == 0 and report["explicit"]["macro_f1"] == 0
    assert report["coverage"] == 0 and report["emitted_accuracy"] is None
    assert report["groups"]["undetermined"]["suggestions"] == 0


def test_global_quality_penalizes_unjustified_suggestions():
    rows = [dict(group="explicit", expected="heureux",
                 outputs={"test": dict(prediction="heureux")}),
            dict(group="undetermined", expected=None,
                 outputs={"test": dict(prediction="neutre")}),
            dict(group="explicit", expected="triste", outputs={"test": dict(prediction=None)})]
    assert global_suggestion_quality(rows, "test") == dict(emitted=2, correct=1, precision=0.5)


def test_dev_selection_has_no_test_input():
    rows = []
    for row in development():
        categories = [0.1]*5
        if row["expected"] is not None:
            categories[["heureux", "stressant", "neutre", "triste", "autre"]
                       .index(row["expected"])] = 0.95
        sample = raw(categories=categories,
                     gates=[0.9]*3 if row["expected"] is None else [0.0]*3)
        rows.append({**row, "features": [sample, sample]})
    best, experiments = select_parameters(rows)
    assert len(experiments) == 144
    assert best["unsafe"] == 0 and best["macro_f1"] == 1
