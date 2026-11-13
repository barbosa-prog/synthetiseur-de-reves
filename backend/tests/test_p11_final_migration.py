"""0008→0009 et rollback réel, exclusivement sur le cluster éphémère du lanceur."""

import json
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from scripts.p11_inventory import capture


def migrate(engine, config, target, *, down=False):
    assert engine.url.database in {"p07_validation", "p20_validation"}
    assert engine.url.port != 5434
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")
            config.attributes["connection"] = connection
            (command.downgrade if down else command.upgrade)(config, target)
    finally:
        config.attributes.pop("connection", None)


def seed_0008(database):
    engine, config = database
    migrate(engine, config, "0008", down=True)
    owner, other, dream, foreign, audio, image = [uuid4() for _ in range(6)]
    jobs = [uuid4() for _ in range(5)]
    token = uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO users(id,email) VALUES (:a,'p11-final-a@example.com'),"
                       "(:b,'p11-final-b@example.com')"), dict(a=owner, b=other))
        c.execute(text("INSERT INTO dreams(id,user_id,transcript,text_version,emotion) "
                       "VALUES (:d,:u,'Recit fictif migration P11',2,'triste')"),
                  dict(d=dream, u=owner))
        c.execute(text("INSERT INTO dreams(id,user_id) VALUES (:d,:u)"), dict(d=foreign, u=other))
        for identifier, kind in [(audio, "audio"), (image, "image")]:
            c.execute(text("INSERT INTO media(id,dream_id,kind,storage_key) VALUES (:i,:d,:k,:s)"),
                      dict(i=identifier, d=dream, k=kind, s="legacy-fiction-"+kind))
        for identifier, kind, status, attempts in zip(
            jobs, ["stt", "image", "emotion", "stt", "image"],
            ["queued", "running", "done", "failed", "queued"], [0, 2, 1, 3, 0]
        ):
            c.execute(text("INSERT INTO jobs(id,dream_id,kind,status,attempts,"
                           "expected_text_version,"
                           "media_id,claim_token,lease_until,error_code) "
                           "VALUES (:i,:d,:k,:s,:a,2,:m,:t,"
                           "CASE WHEN :running THEN now()+interval '10 minutes' ELSE NULL END,:e)"),
                      dict(i=identifier, d=foreign if identifier == jobs[-1] else dream,
                           k=kind, s=status, a=attempts, m=audio if identifier == jobs[0] else None,
                           t=token if status == "running" else None, running=status == "running",
                           e="provider_failed" if status == "failed" else None))
        c.execute(text("INSERT INTO image_descriptions(dream_id,description,version,text_version) "
                       "VALUES (:d,'Foret fictive',1,2)"), dict(d=dream))
        c.execute(text("INSERT INTO image_generations(job_id,user_id,transcript,text_version,"
                       "description,description_version,parameters) VALUES "
                       "(:j,:u,'Recit fictif migration P11',2,'Foret fictive',1,'{}'::jsonb)"),
                  dict(j=jobs[1], u=owner))
        c.execute(text("INSERT INTO dream_emotions(dream_id,source,revision,selected_text_version) "
                       "VALUES (:d,'manual',4,2),(:f,'unset',0,NULL)"), dict(d=dream, f=foreign))
        c.execute(text("INSERT INTO emotion_analyses(job_id,user_id,transcript,text_version,"
                       "choice_revision,parameters,result) VALUES "
                       "(:j,:u,'Recit fictif migration P11',2,3,'{}'::jsonb,CAST(:r AS jsonb))"),
                  dict(j=jobs[2], u=owner, r=json.dumps(dict(emotion=None,
                                                         abstention_reason="ambiguous"))))
        before = capture(c, legacy_jobs=True)
    return engine, config, before, jobs, token


def test_full_historical_migration_preserves_all_rows_states_and_reservations(database):
    engine, config, before, jobs, token = seed_0008(database)
    assert before["revision"] == "0008"
    migrate(engine, config, "0009")
    with engine.begin() as c:
        after = capture(c, legacy_jobs=True)
        assert after["revision"] == "0009" and after["tables"] == before["tables"]
        assert c.scalar(text("SELECT count(*) FROM jobs WHERE retry_count=0 AND "
                             "queued_at=created_at AND cycle_key IS NULL "
                             "AND input_snapshot IS NULL")) == 5
        assert c.scalar(text("SELECT claim_token FROM jobs WHERE id=:j"), dict(j=jobs[1])) == token
        assert {i["name"] for i in inspect(c).get_indexes("jobs")} >= {"ix_jobs_cycle"}
        assert {i["name"] for i in inspect(c).get_check_constraints("jobs")} >= {
            "ck_job_retry_count", "ck_job_cycle"}
    engine.dispose()
    with engine.begin() as c:
        assert capture(c, legacy_jobs=True)["tables"] == before["tables"]
    migrate(engine, config, "0008", down=True)
    with engine.begin() as c:
        assert capture(c, legacy_jobs=True) == before
    migrate(engine, config, "0009")


@pytest.mark.parametrize("failure", ["injected_error", "backend_terminated"])
def test_failed_or_interrupted_migration_rolls_back_schema_revision_and_data(database, failure):
    engine, config, before, _, _ = seed_0008(database)
    fired = []

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if "ADD COLUMN input_snapshot" not in statement or fired:
            return
        fired.append(True)
        if failure == "backend_terminated":
            identifier = connection.scalar(text("SELECT pg_backend_pid()"))
            with engine.begin() as killer:
                assert killer.scalar(text("SELECT pg_terminate_backend(:p)"), dict(p=identifier))
        raise RuntimeError("Interruption fictive pendant 0009")

    event.listen(engine, "after_cursor_execute", interrupt)
    try:
        with pytest.raises((RuntimeError, DBAPIError)):
            migrate(engine, config, "0009")
    finally:
        event.remove(engine, "after_cursor_execute", interrupt)
    assert fired
    with engine.begin() as c:
        assert capture(c, legacy_jobs=True) == before
        names = {column["name"] for column in inspect(c).get_columns("jobs")}
        assert not names & {"cycle_key", "input_snapshot", "retry_count", "queued_at"}
    migrate(engine, config, "0009")


@pytest.mark.parametrize("assignment", [
    "retry_count=-1", "retry_count=3", "cycle_key='wrong'",
    "cycle_key=repeat('a',64),input_snapshot='[]'::jsonb",
    "input_snapshot='{}'::jsonb",
])
def test_0009_database_constraints_refuse_invalid_persistence(database, assignment):
    engine, config, before, jobs, _ = seed_0008(database)
    migrate(engine, config, "0009")
    with pytest.raises(IntegrityError), engine.begin() as c:
        # assignment est une constante du test, jamais une entrée utilisateur.
        c.execute(text(f"UPDATE jobs SET {assignment} WHERE id=:j"), dict(j=jobs[0]))
    with engine.begin() as c:
        assert capture(c, legacy_jobs=True)["tables"] == before["tables"]
