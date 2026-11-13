"""Régression initdb Windows : ACL limitée à un dossier neuf et diagnostic sûr."""

import subprocess
from types import SimpleNamespace

import pytest

from scripts import postgres_test_runtime as runtime
from scripts.test_safety import UnsafeTestTarget


def test_grant_targets_only_current_user_on_empty_temporary_root(tmp_path, monkeypatch, capsys):
    root = tmp_path / "p14_tests_acl"
    root.mkdir()
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr=b"", stdout=(
            b'"fictional","S-1-5-21-100-200-300-1001"\r\n' if len(calls) == 1 else b""))

    monkeypatch.setattr(runtime.subprocess, "run", run)
    runtime.prepare_directory(root)
    assert calls[0][0] == ["whoami.exe", "/user", "/fo", "csv", "/nh"]
    assert calls[1][0] == ["icacls.exe", str(root.resolve()), "/grant",
                           "*S-1-5-21-100-200-300-1001:(OI)(CI)F", "/q"]
    assert all(call[1]["capture_output"] for call in calls)
    assert "S-1-5" not in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["populated", "outside", "invalid_identity", "acl_failed"])
def test_unsafe_or_unavailable_acl_stops_before_initdb(tmp_path, monkeypatch, kind):
    root = tmp_path / ("other" if kind == "outside" else "p14_tests_acl")
    root.mkdir()
    if kind == "populated":
        (root / "existing").write_text("fiction")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1 if len(calls) == 2 else 0, stderr=b"private",
                               stdout=b'"fiction","bad"' if kind == "invalid_identity"
                               else b'"fiction","S-1-5-21-100-200-300-1001"')

    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises((runtime.PostgresTestFailure, UnsafeTestTarget)):
        runtime.prepare_directory(root)
    assert not any("initdb" in " ".join(args) for args in calls)
    if kind in {"populated", "outside"}:
        assert calls == []


@pytest.mark.parametrize("stderr,code,category", [
    (b'Permission denied PRIVATE_SECRET C:/private', 1, "permission_denied"),
    (b'directory exists but is not empty', 1, "directory_not_empty"),
    (b'invalid locale name', 1, "invalid_locale"),
    (b'', 0xC0000135, "runtime_unavailable"),
    (b'FICTITIOUS_UNCLASSIFIED', 1, "process_failed"),
])
def test_native_failure_never_discloses_raw_output(monkeypatch, stderr, code, category):
    def run(*args, **kwargs):
        assert "capture_output" not in kwargs  # Ne pas bloquer sur un PIPE hérité.
        kwargs["stdout"].write(stderr)
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.PostgresTestFailure) as caught:
        runtime.postgres_command(["initdb.exe", "--pwfile", "PRIVATE_PATH"])
    assert category in str(caught.value)
    assert "PRIVATE" not in str(caught.value)
    assert "FICTITIOUS" not in str(caught.value)


@pytest.mark.parametrize("failure,category", [
    (FileNotFoundError("PRIVATE"), "executable_missing"),
    (PermissionError("PRIVATE"), "executable_denied"),
    (subprocess.TimeoutExpired(["PRIVATE"], 90), "timeout"),
])
def test_process_errors_are_categorized(monkeypatch, failure, category):
    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.PostgresTestFailure, match=category) as caught:
        runtime.postgres_command(["initdb.exe"])
    assert "PRIVATE" not in str(caught.value)


def test_success_does_not_wait_for_inherited_output_pipe(monkeypatch, capsys):
    handles = []

    def run(args, **kwargs):
        assert "capture_output" not in kwargs
        assert kwargs["stderr"] == subprocess.STDOUT
        handles.append(kwargs["stdout"])
        handles[-1].write(b"PRIVATE_NATIVE_OUTPUT")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    runtime.postgres_command(["pg_ctl.exe", "start"])
    assert handles[0].closed
    assert "PRIVATE" not in capsys.readouterr().out
