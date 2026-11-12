# P07 — Phase 2 : persistance et file des jobs image

## Schéma et migration

Migration additive `0007_image_jobs`, après `0006` :

- `image_descriptions` : PK/FK dream_id, description privée (1–500 caractères),
  version de description, version source P06 et date de modification.
  Le propriétaire est celui du rêve ; aucune duplication mutable de son identité.
- `image_generations` : PK/FK job_id, propriétaire au lancement, récit français
  et version, description et version, paramètres JSONB. Snapshot écrit uniquement
  à l'enqueue, jamais modifié par ce service lors des corrections/reprises.
- Index partiel unique `uq_active_image_dream` sur les jobs image queued/running.
  L'index des jobs STT et leurs colonnes/comportements restent inchangés.

Aucun backfill ni suppression lors de l'upgrade. Les anciens jobs image sans
snapshot ne sont pas exécutables : le claim les termine en text_conflict.
Des doublons image actifs préexistants feraient refuser la création de l'index ;
ils doivent être examinés explicitement, jamais effacés automatiquement.
Le downgrade supprime les nouvelles tables : réservé aux bases jetables de test.
La migration n'a pas été appliquée à la base personnelle dans cette campagne.

## Service interne, sans routes ni interface

`backend.app.services.image_jobs` propose :

- description_for/save_description : contrôle propriétaire, verrou du rêve,
  version optimiste attendue (0 pour création), vérification de la version P06.
  Un enregistrement identique ne change pas la version ; une reconfirmation
  après correction P06 augmente la version même si les mots sont identiques.
- enqueue : action explicite, verrou du rêve, contrôle des deux versions,
  exclusion des jobs image simultanés, snapshot privé et paramètres qualifiés.
  Le récit n'est jamais traduit ni modifié. Aucun téléchargement ou calcul IA.
- owned_job/projection : même 404 pour inconnu/autre compte ; suivi sans texte,
  description, paramètres sensibles ou jeton de réservation.
- claim : file PostgreSQL SKIP LOCKED, jeton distinct, lease timeout+60 s,
  maximum 3 réservations. Reprise après expiration si versions encore valides ;
  sinon échec text_conflict, ou interrupted après épuisement. STT ignoré.
- fail/cancel : révocation des jetons et libération du statut actif, codes
  d'erreur bornés. Un ancien worker ne peut échouer un job repris.
- authorize_publication : verrou job puis rêve, propriétaire, statut, jeton,
  expiration et versions contrôlés dans la transaction du caller. Ne commit pas.

Le futur publisher doit rattacher le média privé et terminer le job dans cette
même transaction, avant libération des verrous. Il ne doit pas appeler un
MediaService qui commit séparément. Ce garde ne publie aucun média et ne
constitue pas à lui seul une publication P19 raccordée.

## Nettoyage et limites

Les réservations expirées sont réconciliées au prochain claim image ; aucun
daemon nouveau n'est lancé. Les jobs peuvent être annulés par leur propriétaire.
Les snapshots sont conservés pour le suivi, pas effacés lors d'un abandon.
La politique de rétention/suppression RGPD devra intégrer ces nouveaux textes.
Aucun fichier image ou temporaire IA n'est créé ici : pas d'orphelin fichier
à purger dans cette phase. Les transactions et verrous sont couverts par tests.

Le worker GPU surveillé, les routes authentifiées/CSRF, l'interface P07 et la
publication atomique P19 restent à implémenter après validation. Aucun changement
de dépendances, worker P05, service P06, route FastAPI ou stockage physique.

## Commandes Windows et résultats réels

Recette autonome, avec PostgreSQL 17 natif déjà installé (P20_POSTGRES_BIN
facultatif), cluster temporaire, port libre, comptes fictifs et arrêt/nettoyage :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py
.\.venv\Scripts\python.exe -m ruff check backend scripts/verify_image_jobs.py
git diff --check
```

Résultat final : **99 tests réussis, 0 ignoré, en 41,23 s**. Inclus : tests
PostgreSQL P07, unités P07 et non-régression P05/P06 (jobs STT, versionnement,
routes/formulaires testés via TestClient), migrations appliquées dans les schémas
jetables, reconnexion, accès intercomptes, concurrence, reprises, fencing,
annulation, erreur masquée, verrou publication et versions périmées.
Ruff et diff-check réussis. Aucun test navigateur réel ni modèle IA exécuté.

Première passe sans TEST_DATABASE_URL : 46 réussis / 47 ignorés, pas considérée
comme validation PostgreSQL. Lanceur initial corrigé après attente des pipes
hérités pg_ctl ; seul son cluster temporaire identifié a été arrêté. Campagne
suivante : 50 réussis / 49 erreurs de permissions du tmp pytest partagé.
Répertoire basetemp propre à chaque campagne ajouté ; campagne finale ci-dessus.
Les services existants et la base personnelle n'ont pas été arrêtés ou migrés.

Avec une base dédiée déjà configurée, on peut aussi lancer directement pytest
sur les fichiers listés dans le script. Pour la base de l'application, la future
commande de migration sera `python -m alembic upgrade head`, à effectuer lors
de son déploiement contrôlé ; elle n'a pas été exécutée sur cette base ici.
