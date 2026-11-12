"""Recette réelle explicite ; ignorée par défaut, jamais un téléchargement."""

import json
import os
from pathlib import Path

import pytest

from backend.app.emotion_config import parameters
from backend.app.emotion_provider import LocalMDeberta
from backend.app.emotion_runner import WatchedEmotionRunner, worker_slot
from backend.app.emotion_worker import work_once
from backend.app.models import Dream, Job
from backend.app.services import emotions as service
from backend.tests import test_emotion_postgresql as cases

env = cases.env
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_EMOTION_REAL") != "1", reason="Recette réelle opt-in"),
]


def test_real_cpu_worker_fictional_only(env, monkeypatch):
    monkeypatch.setenv("EMOTION_ENABLED", "1")
    config = parameters()
    runner = WatchedEmotionRunner()
    provider = LocalMDeberta(runner, config)
    records = []
    with worker_slot() as acquired:
        assert acquired
        for index, sentence in enumerate(
            [
            "Je terminais ma construction et me sentais très satisfait et joyeux.",
                "Une valise verte se trouvait sous une table en métal.",
            ]
        ):
            with env[2]() as db:
                dream = Dream(user_id=env[3][0], transcript=sentence, text_version=1)
                db.add(dream)
                db.commit()
                identifier = dream.id
                revision = 0
                if index == 0:
                    service.correct(db, env[3][0], identifier, "triste", 0)
                    revision = 1
                job = service.enqueue(db, env[3][0], identifier, 1, revision, parameters=config)
            assert work_once(env[2], provider, config)
            with env[2]() as db:
                status = db.get(Job, job["id"])
                view = service.projection(db, env[3][0], identifier)
                records.append(
                    dict(
                        status=status.status,
                        error=status.error_code,
                        suggestion=view["suggestion"],
                        value=view["value"],
                        metrics=runner.last_metrics,
                    )
                )
                Path("tmp").mkdir(exist_ok=True)
                Path("tmp/p08-phase4-real.json").write_text(
                    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                assert status.status == "done", status.error_code
                assert view["value"] == ("triste" if index == 0 else None)
                assert view["suggestion"]["emotion"] == ("heureux" if index == 0 else None)
                assert runner.last_metrics["process_gone"]
