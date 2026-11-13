"""Contrat du seuil métier : bornes, branches et rapports incomplets."""

import json

import pytest

from scripts import business_coverage as metric


@pytest.fixture
def example(tmp_path, monkeypatch):
    name = "backend/app/services/example.py"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("def classify(flag):\n    if flag:\n        return 1\n    return 0\n")
    monkeypatch.setattr(metric, "business_files", lambda root: [name])
    report = {
        "meta": {"branch_coverage": True}, "totals": {"percent_covered": 80.0},
        "files": {name: {"executed_lines": [1, 2, 3, 4], "missing_lines": [],
                         "executed_branches": [[2, 3]], "missing_branches": [[2, 4]],
                         "excluded_lines": []}},
    }
    return tmp_path, report


def test_exact_eighty_passes_without_counting_module_definitions(example):
    root, report = example
    result = metric.evaluate(report, root)
    assert result["passed"]
    assert result["totals"]["combined_percent"] == 80
    assert result["totals"]["statements"] == 3  # Le def au niveau module ne gonfle pas le taux.
    assert result["totals"]["branch_percent"] == 50
    functions = next(iter(result["files"].values()))["functions"]
    assert functions["classify:1"]["combined_percent"] == 80


def test_high_threshold_rejects_same_measurement(example):
    root, report = example
    assert not metric.evaluate(report, root, threshold=100)["passed"]


@pytest.mark.parametrize("threshold", [79, 101, float("nan")])
def test_threshold_cannot_weaken_minimum(example, threshold):
    root, report = example
    with pytest.raises(ValueError):
        metric.evaluate(report, root, threshold=threshold)


def test_missing_branch_instrumentation_refuses_report(example):
    root, report = example
    report["meta"]["branch_coverage"] = False
    with pytest.raises(ValueError, match="branches"):
        metric.evaluate(report, root)


def test_unmeasured_business_module_cannot_disappear(example):
    root, report = example
    report["files"].clear()
    with pytest.raises(ValueError, match="absent"):
        metric.evaluate(report, root)


def test_cli_failure_propagates_and_writes_report(example, monkeypatch, capsys):
    root, report = example
    original = metric.evaluate
    monkeypatch.setattr(metric, "evaluate", lambda data, threshold: original(data, root, threshold))
    source, output = root / "input.json", root / "result.json"
    source.write_text(json.dumps(report))
    assert metric.main([str(source), "--threshold", "100", "--output", str(output)]) == 1
    assert json.loads(output.read_text())["passed"] is False
    assert "100.00" in capsys.readouterr().out


def test_scope_contains_security_and_workers_but_not_routes_or_models():
    paths = metric.business_files()
    for name in ["auth.py", "security.py", "image_worker.py", "stt_worker.py",
                 "emotion_worker.py", "storage/local.py", "services/ai_quota.py"]:
        assert "backend/app/" + name in paths
    assert "backend/app/models.py" not in paths
    assert "backend/app/dream_routes.py" not in paths
