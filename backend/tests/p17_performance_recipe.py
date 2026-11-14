"""Mesures locales réelles de fournisseurs fictifs, PostgreSQL jetable uniquement."""

import io
import json
import logging
import os
import platform
import sys
import wave
from datetime import datetime, timezone
from importlib.metadata import version
from uuid import uuid4

import psutil
from sqlalchemy import func, select, text

from backend.app.database import ROOT, session_factory
from backend.app.models import AIExecution, AIQuotaPolicy, Dream, ImageDescription, Job, Media, User
from backend.app.services import image_execution, job_lifecycle, stt_jobs
from backend.app.services.media import MediaService
from backend.app.storage.local import LocalPrivateStorage
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_job_lifecycle import identity, settings
from backend.tests.test_stt import FakeProvider
from scripts.performance_stats import summarize

TRIALS, WARMUPS = 30, 2


class LatencyCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events = []

    def emit(self, record):
        if record.name == "dreams.latency":
            self.events.append(json.loads(record.getMessage()))


def test_measured_simulated_stt_and_image(database, tmp_path):
    engine, _ = database
    sessions = session_factory(engine)
    service = MediaService(LocalPrivateStorage(tmp_path / "private"), sessions)
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 32000)
    collector = LatencyCapture()
    logger = logging.getLogger("dreams.latency")
    previous_propagate = logger.propagate
    logger.propagate = False
    logger.addHandler(collector)
    records, samples = [], {kind: {phase: [] for phase in ("queue", "provider", "worker")}
                           for kind in ("stt", "image")}
    try:
        with sessions() as db:
            assert db.get(AIQuotaPolicy, 1).execution_limit == 20
            postgres = db.scalar(text("SHOW server_version"))
        for trial in range(WARMUPS + TRIALS):
            # Deux admissions par compte fictif, sous la politique inchangée de 20/24 h.
            with sessions() as db:
                owner = User(email=f"p17-fiction-{uuid4().hex}@example.com")
                db.add(owner)
                db.commit()
                owner_id = owner.id
            for kind in ("stt", "image"):
                with sessions() as db:
                    dream = Dream(user_id=owner_id, transcript="Recit fictif de mesure.",
                                  text_version=1)
                    db.add(dream)
                    db.commit()
                    dream_id = dream.id
                options = dict(text_version=1, engine=identity(kind), parameters=settings(kind),
                               explicit=True)
                if kind == "stt":
                    media_id = service.store(owner_id, dream_id, io.BytesIO(audio.getvalue()),
                                             kind="audio", media_format="wav")
                    with sessions() as db:
                        db.get(Media, media_id).audio_source = "import"
                        db.commit()
                    options["media_id"] = media_id
                else:
                    with sessions() as db:
                        db.add(ImageDescription(dream_id=dream_id, description="Foret fictive",
                                                version=1, text_version=1))
                        db.commit()
                    options["description_version"] = 1
                collector.events.clear()
                job_id = job_lifecycle.create(sessions, owner_id, dream_id, kind, **options)
                provider = FakeProvider() if kind == "stt" else FakeEngine()
                if kind == "stt":
                    assert stt_jobs.run_once(sessions, service, provider)
                else:
                    assert image_execution.run_once(sessions, service.storage, provider)
                assert provider.calls == 1
                with sessions() as db:
                    job = db.get(Job, job_id)
                    assert job.status == "done" and job.attempts == 1
                events = collector.events.copy()
                assert [(e["phase"], e["outcome"]) for e in events] == [
                    ("queue", "admitted"), ("provider", "returned"), ("worker", "handled")]
                assert all(e["kind"] == kind for e in events)
                if trial >= WARMUPS:
                    records.extend(events)
                    for event in events:
                        samples[kind][event["phase"]].append(event["duration_ms"])
            with sessions() as db:
                assert db.scalar(select(func.count()).select_from(AIExecution).where(
                    AIExecution.user_id == owner_id)) == 2
                assert db.get(AIQuotaPolicy, 1).execution_limit == 20
    finally:
        logger.removeHandler(collector)
        logger.propagate = previous_propagate
    report = dict(schema_version=1, result="passed", scope="simulated-local-workers-only",
                  captured_at_utc=datetime.now(timezone.utc).isoformat(),
                  environment=dict(os=platform.system(), machine=platform.machine(),
                      python=sys.version.split()[0], cpu_logical=os.cpu_count(),
                      ram_gib=round(psutil.virtual_memory().total / 1024**3, 2),
                      postgresql=postgres, sqlalchemy=version("SQLAlchemy"),
                      pillow=version("Pillow")),
                  trials_per_kind=TRIALS, warmups_per_kind=WARMUPS,
                  method="R7-linear:h=(n-1)*p; p=0.50 or 0.95",
                  clocks=dict(queue="PostgreSQL:admitted_at-minus-queued_at",
                              provider="perf_counter", worker="perf_counter"),
                  inputs=dict(audio_seconds=2, audio_hz=16000, audio_channels=1,
                              audio="synthetic-silence-pcm16",
                              image="synthetic-purple-png-512x512"),
                  external_spend_eur=0, model_inference_measured=False,
                  quota_limit_24h=20, admissions_per_fictional_account=2,
                  samples_ms=samples,
                  summaries={kind: {phase: summarize(values) for phase, values in phases.items()}
                             for kind, phases in samples.items()})
    root = ROOT / ("tmp/p17-performance" if os.getenv("CI", "").lower() == "true"
                   else "docs/evidence/p17") / ("run-" + uuid4().hex[:12])
    root.mkdir(parents=True, exist_ok=False)
    (root / "measurements.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (root / "latencies.jsonl").write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8")
