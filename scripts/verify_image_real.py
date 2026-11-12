"""Recette unique SD/P07/P19, cluster et médias jetables, sans base personnelle."""

import argparse
import hashlib
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FICTIONAL_EMAILS = ("real-owner@example.com", "real-other@example.com")


def require(condition, code):
    """Contrôle de sécurité actif même avec Python -O ; aucun secret dans l'erreur."""
    if not condition:
        raise RuntimeError(code)


def check_isolation(env, url, directory, base, data, private):
    """Valide la cible construite avant toute connexion et toute migration."""
    from sqlalchemy.engine import make_url
    directory, base = directory.resolve(), base.resolve()
    require(directory.parent == base and directory.name.startswith("p07-real-"), "unsafe_root")
    require(not directory.is_relative_to(ROOT) and "onedrive" not in str(directory).lower(),
            "unsafe_root")
    require(data.resolve() == directory/"data" and private.resolve() == directory/"private-media",
            "unsafe_storage")
    require(url.host == "127.0.0.1" and url.port not in (None, 5432, 5433, 5434), "unsafe_port")
    require(url.database.startswith("p07_real_") and url.username.startswith("real_"),
            "unsafe_database")
    require(make_url(env["DATABASE_URL"]) == url, "environment_database_mismatch")
    require(Path(env["PRIVATE_MEDIA_ROOT"]).resolve() == private.resolve(),
            "environment_storage_mismatch")


def isolated_environment(url, private, runtime, receipt):
    """Ne modifie pas os.environ ; aucune cible PostgreSQL héritée n'est réutilisée."""
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("PG")
           and key not in {"DATABASE_URL", "TEST_DATABASE_URL", "PRIVATE_MEDIA_ROOT",
                           "IMAGE_MODEL_PATH", "IMAGE_RECEIPT_PATH"}}
    env.update(DATABASE_URL=url.render_as_string(hide_password=False),
               TEST_DATABASE_URL=url.render_as_string(hide_password=False),
               PRIVATE_MEDIA_ROOT=str(private), IMAGE_MODEL_PATH=str(runtime/"model"),
               IMAGE_RECEIPT_PATH=str(receipt), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


def main():
    require(not sys.flags.optimize, "recipe_requires_assertions_enabled")
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-real-once", action="store_true")
    if not parser.parse_args().execute_real_once:
        parser.error("Autorisation explicite nécessaire : --execute-real-once")
    from fastapi.testclient import TestClient
    from PIL import Image
    from sqlalchemy import URL, func, select, text

    from backend.app.database import make_engine, session_factory
    from backend.app.main import create_app
    from backend.app.models import Dream, Job, Media
    from backend.app.services import image_jobs
    from backend.app.services.image_execution import current_image
    from backend.app.storage.local import LocalPrivateStorage

    base = Path(os.environ["LOCALAPPDATA"]) / "SynthetiseurDeReves"
    runtime = base / "p07-qualification"
    python_gpu = runtime / "venv/Scripts/python.exe"
    pg = Path(os.getenv("P20_POSTGRES_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
    assert python_gpu.is_file() and (pg / "initdb.exe").is_file()
    assert not (runtime / "qualification.lock").exists(), "Qualification déjà occupée"
    existing_staging = set(runtime.glob("private-image-*"))
    watched = [ROOT / ".env", *list((ROOT / "backend/app").glob("stt*.py")),
               ROOT / "backend/app/services/transcripts.py", ROOT / "backend/app/storage/local.py"]
    fingerprints = {p: hashlib.sha256(p.read_bytes()).digest() for p in watched if p.is_file()}
    run_id = uuid.uuid4().hex[:12]
    logs = base / "p07-receipts" / run_id
    logs.mkdir(parents=True)
    report = {"attempts": 0, "success": False, "run_id": run_id}
    # Aucun import torch : seule télémétrie native du venv qualifié.
    check_code = (
        "import sys,time,json;sys.path.insert(0,sys.argv[1]);"
        "from load_guard_windows import Telemetry;"
        "t=Telemetry();time.sleep(.4);print(json.dumps(t.read()));t.close()"
    )
    pre = subprocess.run([str(python_gpu), "-c", check_code, str(ROOT/"qualification/p07")],
                         capture_output=True, timeout=15, check=True)
    before = json.loads(pre.stdout)
    report["precheck"] = before
    if (before["ram_available_mib"] < 4096 or before["vram_free_mib"] < 4096
            or before["commit_headroom_mib"] < 4096 or before["commit_percent"] > 90):
        (logs / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Précontrôle défavorable ; aucun cluster, migration ou calcul lancé.")
        return 1
    temporary_path = None
    try:
        with tempfile.TemporaryDirectory(prefix="p07-real-", dir=base) as temporary:
            directory = Path(temporary).resolve()
            temporary_path = directory
            assert directory.is_relative_to(base.resolve())
            assert not directory.is_relative_to(ROOT) and "onedrive" not in str(directory).lower()
            data, private = directory/"data", directory/"private-media"
            assert not data.exists() and not private.exists()
            password, role = secrets.token_hex(24), "real_"+secrets.token_hex(6)
            password_file = directory/"password"
            password_file.write_text(password, encoding="utf-8")

            def pg_run(args, env=None):
                result = subprocess.run(args, env=env, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=90)
                if result.returncode:
                    raise RuntimeError("postgres_temporary_failed")

            pg_run([str(pg/"initdb.exe"), "-D", str(data), "-U", role, "--pwfile",
                    str(password_file), "-A", "scram-sha-256", "--encoding=UTF8", "--locale=C"])
            password_file.unlink()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            require(port not in (5432, 5433, 5434), "unsafe_port")
            start_requested, engine = False, None
            try:
                start_requested = True
                pg_run([str(pg/"pg_ctl.exe"), "-D", str(data), "-l", str(directory/"pg.log"),
                        "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"])
                db_name = "p07_real_"+run_id
                url = URL.create("postgresql+psycopg", username=role, password=password,
                                 host="127.0.0.1", port=port, database=db_name)
                env = isolated_environment(url, private, runtime, logs/"gpu-metrics.json")
                check_isolation(env, url, directory, base, data, private)
                pg_run([str(pg/"createdb.exe"), "-h", "127.0.0.1", "-p", str(port),
                        "-U", role, db_name], dict(env, PGPASSWORD=password))
                # Vérification serveur effective AVANT migration, sans afficher l'URL.
                engine = make_engine(url)
                with engine.connect() as db:
                    assert Path(db.scalar(text("SHOW data_directory"))).resolve() == data.resolve()
                    assert db.scalar(text("select current_database()")) == db_name
                    assert db.scalar(text("select inet_server_port()")) == port
                    assert db.scalar(text("select current_user")) == role
                assert env["PRIVATE_MEDIA_ROOT"] == str(directory/"private-media")
                assert private.resolve() != (base/"private_media").resolve()
                report["isolation_proven_before_migration"] = True
                report["personal_port_5434_excluded"] = True
                print("Isolation serveur, base, port et stockage prouvée avant migration.",
                      flush=True)
                migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0007"],
                                           cwd=ROOT, env=env, capture_output=True, timeout=60)
                assert migration.returncode == 0, "temporary_migration_failed"
                with engine.connect() as db:
                    assert db.scalar(text("select version_num from alembic_version")) == "0007"
                report["migration"] = "0007"
                sessions = session_factory(engine)
                storage = LocalPrivateStorage(private)
                app = create_app()
                app.state.db_factory, app.state.media_storage = sessions, storage
                with TestClient(app, base_url="https://localhost:8443") as client:
                    ids, tokens = [], []
                    for index, email in enumerate(FICTIONAL_EMAILS):
                        report["stage"] = f"register_fictional_user_{index+1}"
                        credentials = {"email": email, "password": secrets.token_hex(24)}
                        registration = client.post("/api/v1/auth/register", json=credentials)
                        report["registration_status"] = registration.status_code
                        require(registration.status_code == 201, "fictional_registration_failed")
                        ids.append(uuid.UUID(registration.json()["id"]))
                        report["stage"] = f"login_fictional_user_{index+1}"
                        login = client.post("/api/v1/auth/login", json=credentials)
                        report["login_status"] = login.status_code
                        require(login.status_code == 200, "fictional_login_failed")
                        tokens.append({"Authorization": "Bearer "+login.json()["access_token"]})
                    report["stage"] = "create_fictional_dream_and_job"
                    with sessions() as db:
                        dream = Dream(user_id=ids[0], transcript="Une forêt et une lune fictives.",
                                      text_version=1)
                        db.add(dream)
                        db.commit()
                        dream_id = dream.id
                        prompt = "An enchanted forest under a large violet moon, dreamy atmosphere."
                        image_jobs.save_description(db, ids[0], dream_id, prompt, 1, 0)
                        job_id = image_jobs.enqueue(db, ids[0], dream_id, 1, 1, seed=42).id
                        assert db.scalar(select(func.count()).select_from(Job)) == 1
                    report["attempts"] = 1
                    report["stage"] = "worker_once"
                    begin = time.perf_counter()
                    worker = subprocess.run(
                        [sys.executable, "-m", "backend.app.image_worker", "--once"],
                        cwd=ROOT, env=env, capture_output=True, timeout=200)
                    report["worker_seconds"] = round(time.perf_counter()-begin, 6)
                    report["worker_exit_code"] = worker.returncode
                    metrics_path = logs/"gpu-metrics.json"
                    require(metrics_path.is_file(), "gpu_metrics_missing")
                    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
                    report["resources_recovered"] = metrics.get("near_initial_resources", False)
                    report["gpu_stop_reason"] = metrics.get("stop_reason")
                    require(report["resources_recovered"], "gpu_resources_not_recovered")
                    require(metrics.get("remaining_job_members") == [], "gpu_child_not_exited")
                    require(not (set(runtime.glob("private-image-*"))-existing_staging),
                            "gpu_staging_not_cleaned")
                    with sessions() as db:
                        job = db.get(Job, job_id)
                        report.update(job_status=job.status, error_code=job.error_code,
                                      job_attempts=job.attempts)
                        if job.status != "done":
                            assert db.scalar(select(func.count()).select_from(Media)) == 0
                            assert not storage.inventory()
                            report["no_publication_on_failure"] = True
                            raise RuntimeError("image_job_failed_no_retry")
                        assert worker.returncode == 0 and job.attempts == 1
                        assert job.claim_token is None and job.lease_until is None
                        media = db.get(Media, job.media_id)
                        assert media and media.kind == "image" and media.media_type == "image/png"
                        assert media.dream_id == dream_id and media.storage_state == "ready"
                        assert current_image(db, ids[0], dream_id) == media.id
                        media_id, size, digest = media.id, media.size_bytes, media.sha256
                    response = client.get(f"/api/v1/media/{media_id}/content", headers=tokens[0])
                    other = client.get(f"/api/v1/media/{media_id}/content", headers=tokens[1])
                    anonymous = client.get(f"/api/v1/media/{media_id}/content")
                    report["http_statuses"] = [response.status_code, other.status_code,
                                               anonymous.status_code]
                    assert report["http_statuses"] == [200, 404, 401]
                    assert len(response.content) == size <= 8*1024**2
                    assert hashlib.sha256(response.content).hexdigest() == digest
                    assert response.headers["cache-control"] == "no-store"
                    assert str(private) not in str(response.headers)
                    with Image.open(io.BytesIO(response.content)) as image:
                        assert image.format == "PNG" and image.size == (512, 512)
                        image.verify()
                    report.update(png_verified=True, png_bytes=size, success=True)
                    report["stage"] = "verification_complete"
            finally:
                if engine is not None:
                    engine.dispose()
                if start_requested:
                    status = subprocess.run([str(pg/"pg_ctl.exe"), "-D", str(data), "status"],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            timeout=10)
                    if status.returncode == 0:
                        pg_run([str(pg/"pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"])
                    else:
                        require(status.returncode == 3, "temporary_pg_status_unknown")
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        frames = traceback.extract_tb(exc.__traceback__)
        if frames:
            last = frames[-1]
            report["failure_location"] = {"file": Path(last.filename).name,
                                          "line": last.lineno, "function": last.name}
    finally:
        report["temporary_resources_removed"] = (
            temporary_path is not None and not temporary_path.exists())
        report["personal_files_unchanged"] = all(
            p.is_file() and hashlib.sha256(p.read_bytes()).digest() == digest
            for p, digest in fingerprints.items())
        report["new_gpu_staging_removed"] = not (
            set(runtime.glob("private-image-*"))-existing_staging)
        report["success"] = (report["success"] and "failure_type" not in report
                             and report["temporary_resources_removed"]
                             and report["personal_files_unchanged"]
                             and report["new_gpu_staging_removed"])
        (logs/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("Journaux conservés :", logs)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
