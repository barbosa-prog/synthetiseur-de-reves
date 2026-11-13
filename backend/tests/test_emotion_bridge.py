"""Surveillance réelle de minuscules processus synthétiques, sans modèle IA."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.emotion_config import parameters


def test_preflight_failure_exits_cleanly_with_parent_pipe_open():
    python = sys.executable  # psutil de requirements-dev ; aucun environnement IA requis.
    bridge = Path(__file__).resolve().parents[2] / "scripts/emotion_cpu_bridge.py"
    config = {**parameters(), "initial_free_mib": 999999}
    with subprocess.Popen(
        [str(python), str(bridge)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        process.stdin.write(json.dumps(dict(configuration=config, request={})).encode() + b"\n")
        process.stdin.flush()
        process.wait(timeout=10)
        assert process.returncode == 0
        assert json.loads(process.stdout.read())["error"] == "insufficient_memory"


@pytest.mark.parametrize("interrupted", [False, True])
def test_bridge_timeout_or_parent_eof_cleans_child(tmp_path, interrupted):
    python = sys.executable
    child = tmp_path / "synthetic.py"
    child.write_text("import sys,time\nsys.stdin.readline()\ntime.sleep(20)\n", encoding="utf-8")
    wrapper = tmp_path / "bridge_test.py"
    root = Path(__file__).resolve().parents[2]
    wrapper.write_text(
        "import sys, pathlib, types\n"
        f"sys.path.insert(0,{str(root)!r})\n"
        "import psutil\n"
        "psutil.virtual_memory=lambda: types.SimpleNamespace(available=8192*2**20)\n"
        "from scripts.emotion_cpu_bridge import main\n"
        "import json\n"
        f"print(json.dumps(main(child_script=pathlib.Path({str(child)!r}))),flush=True)\n",
        encoding="utf-8",
    )
    config = {**parameters(), "timeout_seconds": 1}
    with subprocess.Popen(
        [str(python), str(wrapper)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        process.stdin.write(json.dumps(dict(configuration=config, request={})).encode() + b"\n")
        process.stdin.flush()
        if interrupted:
            process.stdin.close()
        process.wait(timeout=15)
        result = json.loads(process.stdout.read())
        assert result["error"] == ("worker_stopped" if interrupted else "timeout")
        assert result["metrics"]["process_gone"]
    private = Path(os.environ["LOCALAPPDATA"]) / "SynthetiseurDeReves/qualification/p08-worker"
    assert not list(private.glob("emotion-*"))
