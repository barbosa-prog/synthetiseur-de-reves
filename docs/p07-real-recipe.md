# Recette réelle P07 — Préparation après redémarrage

La recette n'a pas encore été exécutée. Aucun cluster, migration ou modèle
n'a été lancé durant cette préparation. PostgreSQL personnel port 5434 exclu.

## Garde-fous vérifiés dans le code

- Invocation explicite `--execute-real-once` obligatoire. `--help` sans effet.
- Nouveau cluster PostgreSQL 17 natif sous LOCALAPPDATA/SynthetiseurDeReves,
  nom p07-real-* ; aucune utilisation de Docker Compose ou du conteneur personnel.
- Port libre distinct de 5432/5433/5434, rôle et base aléatoires dédiés.
- URL SQLAlchemy fournie explicitement au moteur ; contrôle de l'URL transmise,
  host/port/base/rôle et du chemin de stockage avant connexion/migration.
- Preuve serveur avant migration : SHOW data_directory, current_database,
  inet_server_port, current_user doivent correspondre aux ressources créées.
- Environnement enfant distinct : DATABASE_URL, TEST_DATABASE_URL,
  PRIVATE_MEDIA_ROOT, IMAGE_MODEL_PATH et IMAGE_RECEIPT_PATH explicites.
  Paramètres PG* hérités écartés ; os.environ et .env ne sont pas modifiés.
  TestClient est configuré explicitement avec la fabrique DB et le stockage
  temporaires, sans fallback vers la configuration personnelle.
- Le script refuse le mode Python optimisé qui désactiverait ses assertions.
- Deux comptes fictifs, un rêve et un seul job ; worker --once, aucun retry.
- Précontrôle immédiat RAM/VRAM >=4096 Mio, marge commit >=4096 Mio,
  engagement <=90 %. Le surveillant refait son propre précontrôle avant GPU.
- Même pipeline qualifié : local, CUDA FP16, 512x512, 20 étapes, seed42,
  filtre et feature_extractor obligatoires, offline. Aucun téléchargement.
- Limites du pont inchangées : privé 7168 Mio, RAM1536 Mio, VRAM512 Mio,
  calcul120 s ; avant inférence RAM2048 Mio et VRAM1536 Mio libres requises.
- Résultat contrôlé en PostgreSQL, pas seulement code de sortie du worker.
  PNG réel, taille/empreinte/dimensions, sélection par versions et lecture
  authentifiée 200/404/401 vérifiées si génération autorisée.
- Si blocage/échec : aucun média ni fichier privé ne doit être publié, arrêt.
- Mesures GPU conservées avant suppression du staging par image_runner.
  Absence de membres du job GPU, récupération mémoire et absence de nouveau
  staging requises. Pas de succès sans télémétrie.
- Arrêt du seul cluster temporaire même si le lancement n'a pas retourné
  normalement : pg_ctl status/stop vise exclusivement son -D temporaire.
- Suppression du cluster, comptes, base, médias et mot de passe éphémère.
  Conservation uniquement des reçus JSON expurgés sous p07-receipts/<run_id>.
  Empreintes de .env et des fichiers P05/P06/P19 surveillés comparées après.

Un arrêt forcé du système peut empêcher le nettoyage ; le rapport ne prétendra
pas au succès si des ressources temporaires détectables subsistent. Aucun
nettoyage de verrou ou répertoire préexistant n'est automatique. Le modèle,
le venv GPU et les images de qualification précédentes sont conservés.

## Vérifications sans génération réellement exécutées

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_image_real_recipe.py backend/tests/test_image_runner.py -q
.\.venv\Scripts\python.exe -m ruff check scripts/verify_image_real.py backend/app/image_runner.py backend/tests/test_image_real_recipe.py
.\.venv\Scripts\python.exe scripts/verify_image_real.py --help
git diff --check
```

18 tests réussis ; aucun PostgreSQL, GPU, réseau ou modèle utilisé par ces
tests. Ruff et diff-check passent (avertissement Git LF/CRLF connu).
Les seuils ne sont qu'examinés à ce stade : pas de nouvelle mesure matérielle
ou preuve serveur réelle présentée comme déjà acquise après redémarrage.

## Commande prévue — Ne pas exécuter avant autorisation

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_real.py --execute-real-once
```

Le lanceur transmettra lui-même les variables temporaires à Alembic et au
worker. Ne pas lancer `alembic upgrade` ou `image_worker --once` directement
avec le .env personnel. Aucun changement de dépendance ou de production
P05/P06/P19, commit, push ou modification Jira dans cette préparation.
