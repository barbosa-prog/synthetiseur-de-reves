"""Recette P07/P05/P06 sur PostgreSQL natif temporaire, sans IA ni base personnelle."""

import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-only", action="store_true")
    parser.add_argument("--emotion-only", action="store_true")
    parser.add_argument("--emotion-real", action="store_true")
    args = parser.parse_args()
    history_only = args.history_only
    pg = Path(os.getenv("P20_POSTGRES_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
    if not (pg / "initdb.exe").is_file():
        raise SystemExit("PostgreSQL natif absent ; utiliser TEST_DATABASE_URL dédié.")
    with tempfile.TemporaryDirectory(prefix="p07_jobs_") as folder:
        directory = Path(folder)
        data, password_file = directory / "data", directory / "password"
        password, role = secrets.token_hex(24), "p07_"+secrets.token_hex(6)
        password_file.write_text(password, encoding="utf-8")

        def run(args, env=None):
            result = subprocess.run(args, env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=90)
            if result.returncode:
                raise RuntimeError("PostgreSQL temporaire : opération échouée, détails masqués.")

        run([str(pg / "initdb.exe"), "-D", str(data), "-U", role, "--pwfile",
             str(password_file), "-A", "scram-sha-256", "--encoding=UTF8", "--locale=C"])
        password_file.unlink()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        started = False
        try:
            run([str(pg / "pg_ctl.exe"), "-D", str(data), "-l", str(directory / "pg.log"),
                 "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"])
            started = True
            env = dict(os.environ, PGPASSWORD=password)
            run([str(pg / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port),
                 "-U", role, "p07_validation"], env)
            url = URL.create("postgresql+psycopg", username=role, password=password,
                             host="127.0.0.1", port=port, database="p07_validation")
            env["TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
            print("PostgreSQL temporaire démarré ; aucune base personnelle utilisée.", flush=True)
            checks = [
                "backend/tests/test_history.py", "backend/tests/test_history_rules.py",
                "backend/tests/test_history_web.py", "-x",
            ] if history_only else [
                "backend/tests/test_image_jobs.py", "backend/tests/test_image_provider.py",
                "backend/tests/test_image_job_rules.py",
                "backend/tests/test_image_execution.py", "backend/tests/test_image_runner.py",
                "backend/tests/test_media.py", "backend/tests/test_private_storage.py",
                "backend/tests/test_stt.py", "backend/tests/test_transcripts.py",
                "backend/tests/test_stt_provider.py", "backend/tests/test_text_rules.py",
            ]
            if args.emotion_only:
                checks = ["backend/tests/test_emotion_contract.py",
                          "backend/tests/test_emotion_postgresql.py",
                          "backend/tests/test_emotion_worker.py",
                          "backend/tests/test_emotion_web.py",
                          "backend/tests/test_postgresql.py"]
            if args.emotion_real:
                env["RUN_EMOTION_REAL"] = "1"
                checks = ["backend/tests/test_emotion_real.py", "-x"]
            return subprocess.run([
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                "--basetemp", str(directory / "pytest"), "--tb=short",
                *checks, "-q",
            ], env=env, cwd=ROOT, timeout=600).returncode
        finally:
            if started:
                run([str(pg / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"])


if __name__ == "__main__":
    raise SystemExit(main())
