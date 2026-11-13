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
sys.path.insert(0, str(ROOT))

from scripts.postgres_test_runtime import postgres_command, prepare_directory  # noqa: E402
from scripts.test_safety import clean_environment, isolated_environment, probe  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-only", action="store_true")
    parser.add_argument("--all-tests", action="store_true",
                        help="Suite hors navigateur et qualification IA, PostgreSQL jetable")
    parser.add_argument("--business-coverage", action="store_true",
                        help="Suite isolée et seuil métier obligatoire de 80 %, branches incluses")
    parser.add_argument("--history-only", action="store_true")
    parser.add_argument("--emotion-only", action="store_true")
    parser.add_argument("--emotion-real", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--deletion-only", action="store_true")
    parser.add_argument("--purge-only", action="store_true")
    parser.add_argument("--p11-only", action="store_true")
    parser.add_argument("--workers-only", action="store_true")
    parser.add_argument("--tracking-only", action="store_true")
    parser.add_argument("--p11-final", action="store_true")
    parser.add_argument("--quota-only", action="store_true")
    parser.add_argument("--p12-final", action="store_true")
    args = parser.parse_args()
    if args.business_coverage:
        if any(value for key, value in vars(args).items() if key != "business_coverage"):
            parser.error("--business-coverage doit être utilisé seul")
        import importlib.util

        for dependency in ("pytest", "pytest_cov", "coverage", "psycopg", "alembic"):
            if importlib.util.find_spec(dependency) is None:
                raise SystemExit("Dépendance de test absente : " + dependency)
    if args.unit_only:
        with tempfile.TemporaryDirectory(prefix="p14_tests_unit_") as folder:
            return subprocess.run([
                sys.executable, "-m", "pytest", "-m", "unit", "-p", "no:cacheprovider",
                "--basetemp", str(Path(folder) / "pytest"), "--tb=short", "-q",
            ], cwd=ROOT, env=clean_environment(), timeout=600).returncode
    history_only = args.history_only
    pg = Path(os.getenv("P20_POSTGRES_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
    if not (pg / "initdb.exe").is_file():
        raise SystemExit("PostgreSQL natif absent ; utiliser TEST_DATABASE_URL dédié.")
    with tempfile.TemporaryDirectory(prefix="p07_jobs_") as folder:
        directory = Path(folder)
        prepare_directory(directory)
        data, password_file = directory / "data", directory / "password"
        password, role = secrets.token_hex(24), "p07_"+secrets.token_hex(6)
        password_file.write_text(password, encoding="utf-8")

        def run(args, env=None):
            postgres_command(args, env)

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
            env = dict(clean_environment(), PGPASSWORD=password)
            run([str(pg / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port),
                 "-U", role, "p07_validation"], env)
            url = URL.create("postgresql+psycopg", username=role, password=password,
                             host="127.0.0.1", port=port, database="p07_validation")
            env = isolated_environment(directory, url)
            probe(env)
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
                checks = ["backend/tests/test_emotion_real.py", "--allow-real-ai", "-x"]
            if args.export_only:
                checks = ["backend/tests/test_exports.py", "backend/tests/test_export_zip.py",
                          "backend/tests/test_transcripts.py",
                          "backend/tests/test_image_jobs.py", "backend/tests/test_history.py",
                          "backend/tests/test_emotion_postgresql.py", "backend/tests/test_media.py"]
            if args.deletion_only:
                checks = ["backend/tests/test_dream_deletion.py",
                          "backend/tests/test_export_zip.py",
                          "backend/tests/test_authentication.py", "backend/tests/test_stt.py",
                          "backend/tests/test_image_execution.py",
                          "backend/tests/test_emotion_postgresql.py", "backend/tests/test_media.py"]
            if args.purge_only:
                checks = ["backend/tests/test_dream_purge.py",
                          "backend/tests/test_dream_deletion.py",
                          "backend/tests/test_media.py", "backend/tests/test_private_storage.py"]
            if args.p11_only:
                checks = ["backend/tests/test_job_rules.py", "backend/tests/test_job_lifecycle.py",
                          "backend/tests/test_job_maintenance_cli.py",
                          "backend/tests/test_emotion_postgresql.py",
                          "backend/tests/test_postgresql.py", "-x"]
            if args.workers_only:
                checks = ["backend/tests/test_worker_jobs_p11.py",
                          "backend/tests/test_stt.py", "backend/tests/test_image_jobs.py",
                          "backend/tests/test_image_execution.py",
                          "backend/tests/test_emotion_postgresql.py",
                          "backend/tests/test_emotion_worker.py",
                          "backend/tests/test_job_lifecycle.py", "-x"]
            if args.tracking_only:
                checks = ["backend/tests/test_job_routes_p11.py",
                          "backend/tests/test_stt.py", "backend/tests/test_image_routes.py",
                          "backend/tests/test_emotion_web.py",
                          "backend/tests/test_worker_jobs_p11.py", "-x"]
            if args.p11_final:
                checks = ["backend/tests/test_p11_final_migration.py",
                          "backend/tests/test_job_rules.py", "backend/tests/test_job_lifecycle.py",
                          "backend/tests/test_job_maintenance_cli.py",
                          "backend/tests/test_job_routes_p11.py",
                          "backend/tests/test_worker_jobs_p11.py",
                          "backend/tests/test_emotion_postgresql.py",
                          "backend/tests/test_postgresql.py", "-x"]
            if args.quota_only:
                checks = ["backend/tests/test_ai_quota.py",
                          "backend/tests/test_image_jobs.py",
                          "backend/tests/test_job_lifecycle.py",
                          "backend/tests/test_worker_jobs_p11.py",
                          "backend/tests/test_job_routes_p11.py",
                          "backend/tests/test_postgresql.py", "-x"]
            if args.p12_final:
                checks = ["backend/tests/test_p12_final_security.py",
                          "backend/tests/test_p12_final_migration.py",
                          "backend/tests/test_ai_quota.py",
                          "backend/tests/test_http_guard.py", "backend/tests/test_safe_logging.py",
                          "backend/tests/test_stt_provider.py",
                          "backend/tests/test_image_provider.py",
                          "backend/tests/test_image_runner.py",
                          "backend/tests/test_emotion_worker.py",
                          "backend/tests/test_job_routes_p11.py", "backend/tests/test_api.py", "-x"]
            if args.all_tests or args.business_coverage:
                checks = ["backend/tests", "-m", "not browser and not qualification"]
            if args.business_coverage:
                reports = ROOT / "tmp/p14-coverage"
                reports.mkdir(parents=True, exist_ok=True)
                # Invalider les anciens rapports, sans supprimer de fichier du projet.
                for name in ("backend.json", "business.json", "backend.xml", "tests.xml"):
                    (reports / name).write_text("", encoding="utf-8")
                env["COVERAGE_FILE"] = str(reports / ".coverage")
                env.pop("COVERAGE_PROCESS_START", None)
                env.pop("COVERAGE_RCFILE", None)
                checks += ["--cov=backend.app", "--cov-branch",
                           f"--cov-config={ROOT / 'pyproject.toml'}", "--cov-report=term",
                           f"--junitxml={reports / 'tests.xml'}",
                           f"--cov-report=json:{reports / 'backend.json'}",
                           f"--cov-report=xml:{reports / 'backend.xml'}"]
            result = subprocess.run([
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                "--basetemp", str(directory / "pytest"), "--tb=short",
                *checks, "-q",
            ], env=env, cwd=ROOT, timeout=1200 if args.business_coverage else 600).returncode
            if result or not args.business_coverage:
                return result
            return subprocess.run([
                sys.executable, str(ROOT / "scripts/business_coverage.py"),
                str(reports / "backend.json"), "--output", str(reports / "business.json"),
            ], env=env, cwd=ROOT, timeout=60).returncode
        finally:
            if started:
                run([str(pg / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"])


if __name__ == "__main__":
    raise SystemExit(main())
