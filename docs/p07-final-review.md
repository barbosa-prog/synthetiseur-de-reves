# P07 — Revue finale avant commit

Aucun staging, commit, push, changement Jira ou génération réelle dans cet audit.
Le parcours manuel réel P04 → P05 → P06 → P07 a été validé par l'utilisateur.

## Liste exacte proposée pour le commit

Inclure uniquement les fichiers ci-dessous : application, tests, documentation,
recettes et sources de qualification P07. Les scripts de diagnostic conservent
la reproductibilité des choix matériels et de l'analyse du crash natif.
Les cinq modules common/cpu_mini/load_guard_windows/image_job_bridge/image_job_gpu
sont aussi des dépendances effectives du worker : ne pas omettre qualification/.
Les autres scripts de qualification sont des outils explicites, jamais exécutés
par FastAPI ou automatiquement par pytest. Aucun modèle ou résultat de recette
n'est inclus. Ne pas utiliser un ajout Git global sans contrôler ce manifeste.

```text
backend/app/image_provider.py
backend/app/image_routes.py
backend/app/image_runner.py
backend/app/image_worker.py
backend/app/main.py
backend/app/models.py
backend/app/services/image_execution.py
backend/app/services/image_jobs.py
backend/app/web/static/css/app.css
backend/app/web/static/js/image.js
backend/app/web/templates/image.html
backend/app/web/templates/transcript.html
backend/migrations/versions/0007_image_jobs.py
backend/tests/test_image_browser.py
backend/tests/test_image_execution.py
backend/tests/test_image_job_rules.py
backend/tests/test_image_jobs.py
backend/tests/test_image_provider.py
backend/tests/test_image_real_recipe.py
backend/tests/test_image_routes.py
backend/tests/test_image_runner.py
backend/tests/test_postgresql.py
docs/p07-final-review.md
docs/p07-phase1.md
docs/p07-phase2.md
docs/p07-phase3.md
docs/p07-phase4.md
docs/p07-real-recipe.md
docs/p07-recipe-diagnostic-abda85e2b698.md
qualification/p07/README.md
qualification/p07/clip_cpu_only.py
qualification/p07/common.py
qualification/p07/cpu_mini.py
qualification/p07/cuda_mini.py
qualification/p07/diffusers_mini.py
qualification/p07/download_model.py
qualification/p07/generate.py
qualification/p07/generate_english_once.py
qualification/p07/generate_first_once.py
qualification/p07/generate_twenty_once.py
qualification/p07/image_job_bridge.py
qualification/p07/image_job_gpu.py
qualification/p07/load_guard_windows.py
qualification/p07/load_only.py
qualification/p07/load_only_worker.py
qualification/p07/pipeline_load_once.py
qualification/p07/preflight.py
qualification/p07/requirements-cuda.txt
qualification/p07/requirements.txt
qualification/p07/safetensors_file_mini.py
qualification/p07/safetensors_memory_mini.py
qualification/p07/safety_cpu_only.py
qualification/p07/test_load_only.py
qualification/p07/unet_cpu_only.py
qualification/p07/vae_cpu_only.py
scripts/verify_image_jobs.py
scripts/verify_image_real.py
```

Proposition : 57 fichiers. Les fichiers déjà suivis modifiés sont main.py,
models.py, le CSS compilé, transcript.html et test_postgresql.py. Les autres sont
des créations P07. Aucun changement à requirements.txt/requirements-stt.txt,
.gitignore, .env.example ou à la migration 0006.

## Contrôles de confidentialité

Inventaire Git intégral : fichiers texte seulement (.py/.md/.txt/.html/.js/.css),
aucun fichier de plus de 1 Mio, aucun média, poids IA, base locale, clé privée
ou .env parmi les candidats. Aucune donnée personnelle ou secret détecté par
la revue et la recherche de signatures courantes ; cette recherche ne constitue
pas une garantie universelle de détection de secrets.
.env, tmp/ et les poids Safetensors sont ignorés ; modèles, médias et reçus
restent sous LOCALAPPDATA. Aucun fichier protégé de ces types n'est déjà suivi.
Les identifiants de tests sont fictifs ou aléatoires. Index Git vide.

## Intégrité et sécurité

0006 inchangée ; 0007 descend de 0006 et constitue l'unique tête Alembic. Upgrade
additif : descriptions, snapshots et unicité des jobs image actifs. Roundtrip
et comparaison migrations/ORM couverts par la campagne PostgreSQL isolée.
Aucune migration lancée sur la base personnelle par cet audit.

Récit français et description séparés ; snapshot des versions, verrou du rêve,
token/bail et revalidation avant publication. Une correction ou modification de
description empêche le résultat tardif de devenir courant. Propriétaire vérifié
sur les routes Bearer et cookie ; origine stricte et CSRF des POST navigateur.
Échappement Jinja et textContent ; aucun jeton d'authentification dans JavaScript.

Filtre actif, image bloquée non publiée. PNG, dimensions, taille et stockage
privé validés. Compensation après échec écriture/DB, contrôle de référence
avant suppression en cas de commit ambigu, maintenance P19 avec délai de grâce
après crash brutal. Rétention/suppression RGPD des snapshots à intégrer à P10.

## Validation de l'audit

Nouvelle campagne complète : **338 tests réussis, aucun ignoré, 198,10 s**,
couverture backend **89,12 %**. PostgreSQL/HTTPS temporaires et Chrome réel,
moteurs fictifs, aucune génération réelle. Relecture P04/P19 après redémarrage
PostgreSQL/Uvicorn réussie, purge P19 puis 404, serveurs temporaires arrêtés.
Ruff, Tailwind local, node --check, pip check et git diff --check réussis.
Seuls avertissements Git : conversion LF/CRLF habituelle sous Windows.

Inventaire final Windows : **0 processus temporaire de recette ou GPU**.
Le worker personnel préexistant (lanceur venv et enfant Python) est laissé intact.
PostgreSQL Docker personnel healthy ; aucun conteneur existant arrêté.
Aucun contenu de base personnelle interrogé ou modifié durant cet audit.

État Git : **5 fichiers suivis modifiés, 52 nouveaux, 0 staged**. Le manifeste
inclut ce rapport, seul fichier créé pendant l'audit. Aucun correctif métier
supplémentaire nécessaire. Aucun commit, push ou changement Jira.

Message proposé après validation :
`feat(p07): ajouter la génération locale privée avec jobs versionnés et interface web`
