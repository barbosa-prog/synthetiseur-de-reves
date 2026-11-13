"""Recette isolée Windows : PostgreSQL natif temporaire, HTTPS, pytest et Chrome/Edge."""

import argparse
import io
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import trustme
from sqlalchemy import URL, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.database import make_engine, session_factory  # noqa: E402
from backend.app.models import AIExecution, AuthSession, Dream, Job, Media, User  # noqa: E402
from backend.app.security import new_token, token_digest  # noqa: E402
from backend.app.services.media import MediaService  # noqa: E402
from backend.app.storage.local import LocalPrivateStorage  # noqa: E402
from scripts.p11_inventory import capture  # noqa: E402
from scripts.test_safety import clean_environment, isolated_environment, probe  # noqa: E402


def free_port() -> int:
    """Réserve un numéro libre pour les services de test locaux."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    """Ne touche à aucune base ou service existant et n'affiche aucun secret."""
    parser = argparse.ArgumentParser(description="Recette locale isolée des tickets développés.")
    parser.add_argument("--browser-only", action="store_true", help="Tests navigateur seulement")
    parser.add_argument("--emotion-web-test", action="store_true",
                        help="Disponibilité P08 simulée dans le serveur temporaire, sans worker")
    parser.add_argument("--p10-final", action="store_true",
                        help="Recette intégrée P10 sur la base temporaire fraîche")
    parser.add_argument("--p11-browser", action="store_true",
                        help="Parcours Chrome P11 uniquement, sans fournisseur réel")
    args = parser.parse_args()
    pg = Path(os.getenv("P20_POSTGRES_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
    if not (pg / "initdb.exe").is_file():
        raise SystemExit("PostgreSQL natif absent : configurer P20_POSTGRES_BIN.")
    with tempfile.TemporaryDirectory(prefix="dreams_p20_") as temporary:
        directory = Path(temporary)
        data = directory / "data"
        password = secrets.token_hex(24)
        role = "p20_" + secrets.token_hex(6)
        password_file = directory / "password"
        password_file.write_text(password, encoding="utf-8")

        def run_pg(args, env=None):
            result = subprocess.run(args, env=env if env is not None else clean_environment(),
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=90)
            if result.returncode:
                raise RuntimeError("Opération PostgreSQL temporaire échouée ; détails masqués.")

        run_pg([str(pg / "initdb.exe"), "-D", str(data), "-U", role,
                "--pwfile", str(password_file), "-A", "scram-sha-256",
                "--encoding=UTF8", "--locale=C"])
        password_file.unlink()
        db_port, web_port = free_port(), free_port()
        started, server = False, None
        try:
            run_pg([str(pg / "pg_ctl.exe"), "-D", str(data), "-l", str(directory / "pg.log"),
                    "-o", f"-h 127.0.0.1 -p {db_port}", "-w", "start"])
            started = True
            print("PostgreSQL temporaire démarré.", flush=True)
            env = clean_environment()
            env["PGPASSWORD"] = password
            run_pg([str(pg / "createdb.exe"), "-h", "127.0.0.1", "-p", str(db_port),
                    "-U", role, "p20_validation"], env)
            url = URL.create("postgresql+psycopg", username=role, password=password,
                             host="127.0.0.1", port=db_port, database="p20_validation")
            raw_url = url.render_as_string(hide_password=False)
            origin = f"https://127.0.0.1:{web_port}"
            env = isolated_environment(directory, url)
            probe(env)
            env.update(DATABASE_URL=raw_url, TEST_DATABASE_URL=raw_url,
                       WEB_ORIGIN=origin, WEB_TEST_URL=origin,
                       PRIVATE_MEDIA_ROOT=str(directory / "private_media"))
            env["EXPORT_TEMP_ROOT"] = str(directory / "exports")
            env["EMOTION_ENABLED"] = "1" if args.emotion_web_test else "0"
            if args.emotion_web_test:
                env["P14_FAKE_EMOTION_UI"] = "1"
            result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                    cwd=ROOT, env=env, capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError("Migration de test échouée ; détails privés masqués.")
            authority = trustme.CA()
            certificate = authority.issue_cert("localhost", "127.0.0.1")
            certificate.private_key_pem.write_to_path(directory / "key.pem")
            certificate.cert_chain_pems[0].write_to_path(directory / "cert.pem")
            server_command = [
                sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1",
                "--port", str(web_port), "--no-access-log", "--no-proxy-headers",
                "--ssl-keyfile", str(directory / "key.pem"),
                "--ssl-certfile", str(directory / "cert.pem"),
            ]
            server = subprocess.Popen(server_command, cwd=ROOT, env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with httpx.Client(verify=False, trust_env=False) as client:
                for _ in range(100):
                    try:
                        if client.get(origin + "/api/v1/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Serveur HTTPS temporaire indisponible.")
            checks = (["-m", "browser"] if args.browser_only else [
                "--cov=backend.app", "--cov-report=term-missing", "--cov-fail-under=80",
            ])
            if args.p10_final:
                checks = ["backend/tests/p10_final_recipe.py", "-x"]
            if args.p11_browser:
                checks = ["backend/tests/test_job_tracking_browser.py", "-x"]
            result = subprocess.run([
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                "--basetemp", str(directory / "pytest"), "--tb=short",
                *checks,
            ], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
            output = result.stdout + result.stderr
            for secret in (raw_url, password, role):
                output = output.replace(secret, "[MASQUÉ]")
            print(output, flush=True)
            if result.returncode == 0:
                # P19 : vérifie aussi un vrai redémarrage des deux processus, pas seulement du pool.
                engine = make_engine(url)
                service = MediaService(LocalPrivateStorage(directory / "private_media"),
                                       session_factory(engine))
                token = new_token()
                try:
                    with Session(engine) as db:
                        user = User(email="restart-fiction@example.com")
                        dream = Dream(user=user)
                        db.add(dream)
                        db.flush()
                        user_id, dream_id = user.id, dream.id
                        db.add(AuthSession(
                            user_id=user.id, token_hash=token_digest(token),
                            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                        ))
                        # Données de persistance uniquement : aucun worker n'est lancé.
                        # Budgets non nuls et réservation garantissent un contrôle non vide.
                        restart_jobs = [
                            Job(dream_id=dream.id, kind="stt", status="failed", attempts=3,
                                retry_count=2, cycle_key="a" * 64,
                                input_snapshot={"fictitious_restart_check": True}),
                            Job(dream_id=dream.id, kind="image", status="running", attempts=2,
                                retry_count=1, cycle_key="b" * 64,
                                input_snapshot={"fictitious_restart_check": True},
                                claim_token=uuid4(),
                                lease_until=datetime.now(timezone.utc) + timedelta(hours=1)),
                        ]
                        db.add_all(restart_jobs)
                        db.flush()
                        # Admissions fictives non vides pour vérifier aussi P12 après redémarrage.
                        for job in restart_jobs:
                            db.add(AIExecution(user_id=user.id, job_id=job.id, kind=job.kind,
                                attempt=job.attempts,
                                reservation_token=job.claim_token or uuid4()))
                        db.commit()
                    audio = io.BytesIO()
                    with wave.open(audio, "wb") as sample:
                        sample.setnchannels(1)
                        sample.setsampwidth(2)
                        sample.setframerate(16000)
                        sample.writeframes(b"\x00\x00" * 160)
                    payload = audio.getvalue()
                    identifier = service.store(user_id, dream_id, io.BytesIO(payload),
                                               kind="audio", media_format="wav")
                    uploaded = None
                    with Session(engine) as db:
                        candidate = db.scalar(select(Media).where(
                            Media.audio_source.is_not(None), Media.storage_state == "ready",
                        ).limit(1))
                        if candidate is not None:
                            recorded_token = new_token()
                            recorded_owner = candidate.dream.user_id
                            uploaded = (candidate.id, recorded_owner, recorded_token)
                            db.add(AuthSession(
                                user_id=recorded_owner, token_hash=token_digest(recorded_token),
                                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                            ))
                            db.commit()
                    recorded_payload = None
                    if uploaded is not None:
                        recorded = service.download(uploaded[1], uploaded[0])
                        with recorded.stream:
                            recorded_payload = recorded.stream.read()
                    endpoint = origin + f"/api/v1/media/{identifier}/content"
                    headers = {"Authorization": "Bearer " + token}
                    with httpx.Client(verify=False, trust_env=False) as client:
                        response = client.get(endpoint, headers=headers)
                        if response.status_code != 200 or response.content != payload:
                            raise RuntimeError("Lecture privée HTTP initiale échouée.")
                        history_before = client.get(origin + "/api/v1/dreams", headers=headers)
                        if (history_before.status_code != 200
                                or history_before.json()["total"] != 1
                                or history_before.json()["items"][0]["id"] != str(dream_id)):
                            raise RuntimeError("Historique P09 initial non validé.")
                    with engine.begin() as connection:
                        p11_before_restart = capture(connection)
                    server.terminate()
                    server.wait(timeout=15)
                    server = None
                    engine.dispose()
                    run_pg([str(pg / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"])
                    run_pg([str(pg / "pg_ctl.exe"), "-D", str(data),
                            "-l", str(directory / "pg.log"),
                            "-o", f"-h 127.0.0.1 -p {db_port}", "-w", "start"])
                    server = subprocess.Popen(server_command, cwd=ROOT, env=env,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with httpx.Client(verify=False, trust_env=False) as client:
                        for _ in range(100):
                            try:
                                if client.get(origin + "/api/v1/health").status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            time.sleep(0.1)
                        with engine.begin() as connection:
                            if capture(connection) != p11_before_restart:
                                raise RuntimeError("Données ou budgets perdus après redémarrage.")
                        print("P11 : données, budgets et réservations identiques après "
                              "redémarrage PostgreSQL/Uvicorn.", flush=True)
                        response = client.get(endpoint, headers=headers)
                        if response.status_code != 200 or response.content != payload:
                            raise RuntimeError("Persistance après redémarrage non validée.")
                        history_after = client.get(origin + "/api/v1/dreams", headers=headers)
                        if (history_after.status_code != 200
                                or history_after.json() != history_before.json()):
                            raise RuntimeError("Historique P09 perdu après redémarrage.")
                        print("P09 : historique identique après redémarrage PostgreSQL/Uvicorn.",
                              flush=True)
                        if uploaded is not None:
                            recorded_response = client.get(
                                origin + f"/api/v1/media/{uploaded[0]}/content",
                                headers={"Authorization": "Bearer " + uploaded[2]},
                            )
                            if (recorded_response.status_code != 200
                                    or recorded_response.content != recorded_payload):
                                raise RuntimeError("Audio P04 perdu après redémarrage.")
                            print("P04 : audio importé relu après redémarrage réel, HTTP 200.",
                                  flush=True)
                        service.request_purge(user_id, identifier)
                        if client.get(endpoint, headers=headers).status_code != 404:
                            raise RuntimeError("Purge du média de test non validée.")
                    print("P19 HTTP : lecture 200, redémarrage PostgreSQL/Uvicorn, "
                          "relecture 200, purge puis 404.", flush=True)
                finally:
                    engine.dispose()
            return result.returncode
        finally:
            if server is not None:
                server.terminate()
                server.wait(timeout=15)
            if started:
                run_pg([str(pg / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"])
            print("Serveurs temporaires arrêtés.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
