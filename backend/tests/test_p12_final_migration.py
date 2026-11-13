"""Copie 0009 fictive complète, empreintes de toutes les données avant/après 0010."""

from sqlalchemy import text

from backend.tests.test_p11_final_migration import migrate, seed_0008
from scripts.p11_inventory import capture


def test_0009_copy_preserves_all_historical_states_snapshots_and_authentication(database):
    engine, config, _, _, _ = seed_0008(database)
    migrate(engine, config, "0009")
    with engine.begin() as c:
        c.execute(text("INSERT INTO auth_sessions(user_id,token_hash,expires_at) "
                       "SELECT id,repeat('a',64),now()+interval '1 hour' FROM users "
                       "ORDER BY id LIMIT 1"))
        before = capture(c)
        assert before["revision"] == "0009"
        for name in ["users", "dreams", "media", "jobs", "image_descriptions",
                     "image_generations", "dream_emotions", "emotion_analyses", "auth_sessions"]:
            assert before["tables"][name]["count"] > 0
    migrate(engine, config, "0010")
    with engine.begin() as c:
        after = capture(c)
        assert after["revision"] == "0010"
        assert {name: value for name, value in after["tables"].items()
                if not name.startswith("ai_")} == before["tables"]
        assert after["tables"]["ai_executions"]["count"] == 0
        assert c.scalar(text("SELECT execution_limit FROM ai_quota_policy WHERE id=1")) == 20
    engine.dispose()
    with engine.begin() as c:
        assert capture(c) == after
