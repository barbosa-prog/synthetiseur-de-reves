"""Empreintes PostgreSQL en mémoire serveur ; aucune connexion automatique ni donnée affichée."""

from sqlalchemy import text

from backend.app import models  # noqa: F401
from backend.app.database import Base


def capture(connection, *, legacy_jobs=False):
    """Comptes et SHA-256 uniquement. L'appelant fournit sa connexion et sa transaction.

    legacy_jobs=True exclut seulement les quatre colonnes ajoutées en 0009 afin de
    comparer le contenu historique de jobs avant/après migration. False conserve
    tous les champs, notamment les budgets et réservations, pour tester un redémarrage.
    """
    connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
    result = {"revision": connection.scalar(text("SELECT version_num FROM alembic_version")),
              "tables": {}}
    for table in sorted(Base.metadata.tables):
        # Les noms viennent exclusivement des métadonnées du projet, jamais du navigateur.
        excluded = ("ARRAY['retry_count','queued_at','cycle_key','input_snapshot']::text[]"
                    if legacy_jobs and table == "jobs" else "ARRAY[]::text[]")
        row = f"(to_jsonb(r) - {excluded})::text"
        sql = (f'SELECT count(*), encode(sha256(convert_to(COALESCE(string_agg({row}, '
               f"E'\\n' ORDER BY {row} COLLATE \"C\"),''),'UTF8')),'hex') "
               f'FROM "{table}" AS r')
        count, checksum = connection.execute(text(sql)).one()
        result["tables"][table] = dict(count=count, sha256=checksum)
    return result


if __name__ == "__main__":
    raise SystemExit("Module sans connexion automatique : importer capture.")
