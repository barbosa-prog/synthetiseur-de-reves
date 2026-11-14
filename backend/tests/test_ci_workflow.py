"""Contrat statique du workflow et des artefacts, sans accès GitHub."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.ci_report import render

ROOT = Path(__file__).resolve().parents[2]


def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8"))


def test_triggers_permissions_and_windows_postgresql_strategy():
    data = workflow()
    assert set(data["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert data["on"]["pull_request"]["branches"] == ["main"]
    assert data["on"]["push"]["branches"] == ["main"]
    assert data["permissions"] == {"contents": "read"}
    assert set(data["jobs"]) == {"tests"}
    job = data["jobs"]["tests"]
    assert job["runs-on"] == "windows-2025" and "services" not in job
    assert job["defaults"]["run"]["shell"] == "pwsh"
    assert 1 <= job["timeout-minutes"] <= 40
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"actions/[a-z-]+@[a-f0-9]{40}", step["uses"])
    assert job["steps"][0]["with"]["persist-credentials"] is False


def test_ci_uses_protected_commands_and_never_references_production_secrets():
    job = workflow()["jobs"]["tests"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    for command in ["--business-coverage", "--browser-only --emotion-web-test",
                    "ruff check", "compileall", "--only-binary=:all:",
                    "--require-hashes", "requirements-windows-py312.lock"]:
        assert command in commands
    for forbidden in ["secrets.", "--emotion-real", "--execute-real-once", "dreams_local",
                      "requirements-stt", "requirements-cuda", "docker compose"]:
        assert forbidden not in commands
    assert job["env"]["EMOTION_ENABLED"] == "0"
    assert job["env"]["CI"] == "true"


def test_artifact_allowlist_contains_only_reports():
    steps = workflow()["jobs"]["tests"]["steps"]
    upload = next(step for step in steps if "upload-artifact@" in step.get("uses", ""))
    assert set(upload["with"]["path"].split()) == {
        "tmp/p14-coverage/backend.json", "tmp/p14-coverage/backend.xml",
        "tmp/p14-coverage/business.json", "tmp/p14-coverage/ci-summary.json",
        "tmp/p14-coverage/ci-summary.md",
    }
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == 7
    assert "if" not in upload  # Publication seulement si toutes les étapes réussissent.


def test_p16_recipe_is_required_and_only_safe_evidence_is_uploaded():
    steps = workflow()["jobs"]["tests"]["steps"]
    recipe = next(step for step in steps if "--p16-demo" in step.get("run", ""))
    assert recipe["run"] == "python scripts/verify_p20.py --p16-demo"
    assert "if" not in recipe and not recipe.get("continue-on-error")
    upload = next(step for step in steps if step.get("with", {}).get("name", "").startswith(
        "p16-demo-"))
    filenames = {
        "01-audio-fictif.png", "02-transcription-simulee.png", "03-recit-corrige.png",
        "04-image-simulee.png", "05-emotion-acceptee.png", "06-historique.png",
        "07-suppression-confirmation.png", "08-historique-apres-purge.png", "result.json",
    }
    assert set(upload["with"]["path"].split()) == {
        "tmp/p16-demo/run-*/" + filename for filename in filenames}
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == 7
    assert "if" not in upload


@pytest.fixture
def reports(tmp_path):
    (tmp_path / "business.json").write_text(json.dumps({
        "passed": True, "threshold": 80, "totals": {"combined_percent": 85},
    }))
    (tmp_path / "backend.json").write_text(json.dumps({
        "meta": {"branch_coverage": True}, "totals": {"percent_covered": 90},
    }))
    (tmp_path / "tests.xml").write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase name="FICTION_PRIVATE_MARKER"/></testsuite></testsuites>')
    return tmp_path


def test_p17_campaign_and_artifacts_are_required_and_bounded():
    steps = workflow()["jobs"]["tests"]["steps"]
    campaign = next(step for step in steps if "--p17-performance" in step.get("run", ""))
    assert campaign["run"] == "python scripts/verify_image_jobs.py --p17-performance"
    assert "if" not in campaign and not campaign.get("continue-on-error")
    upload = next(step for step in steps if step.get("with", {}).get("name", "").startswith(
        "p17-performance-"))
    assert set(upload["with"]["path"].split()) == {
        "tmp/p17-performance/run-*/measurements.json", "tmp/p17-performance/run-*/latencies.jsonl"}
    assert upload["with"]["retention-days"] == 7
    assert upload["with"]["if-no-files-found"] == "error"
    assert "if" not in upload


def test_summary_is_bound_to_commit_without_test_payload(reports):
    markdown = render(reports, "a" * 40)
    assert "a" * 40 in markdown
    summary = (reports / "ci-summary.json").read_text()
    assert "FICTION_PRIVATE_MARKER" not in summary
    assert json.loads(summary)["tests"]["tests"] == 2


@pytest.mark.parametrize("problem", ["commit", "skip", "threshold", "branches"])
def test_summary_refuses_unverified_results(reports, problem):
    if problem == "skip":
        (reports / "tests.xml").write_text(
            '<testsuites><testsuite tests="1" skipped="1"/></testsuites>')
    elif problem == "threshold":
        (reports / "business.json").write_text(json.dumps({
            "passed": True, "threshold": 79, "totals": {"combined_percent": 99},
        }))
    elif problem == "branches":
        (reports / "backend.json").write_text(json.dumps({"meta": {"branch_coverage": False}}))
    with pytest.raises((ValueError, KeyError)):
        render(reports, "invalid" if problem == "commit" else "a" * 40)


@pytest.mark.parametrize("qualification,expected", [(False, 1), (True, 0)])
def test_mandatory_skip_fails_ci_but_qualification_remains_optional(monkeypatch,
                                                                 qualification, expected):
    import conftest

    monkeypatch.setenv("CI", "true")
    reporter = SimpleNamespace(stats={"skipped": [
        SimpleNamespace(keywords={"qualification": True} if qualification else {}),
    ]})
    session = SimpleNamespace(exitstatus=0, config=SimpleNamespace(
        pluginmanager=SimpleNamespace(get_plugin=lambda _: reporter)))
    conftest.pytest_sessionfinish(session, 0)
    assert session.exitstatus == expected
