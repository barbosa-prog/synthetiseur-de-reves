# P14 — Phase 2 : isolation des tests

Cette phase n'ajoute ni CI, ni seuil de couverture métier, ni tests fonctionnels
supplémentaires des workers. Aucun code de production, migration ou CSS modifié.

## Reprise du travail existant

Le fichier non suivi `scripts/test_safety.py` a été lu intégralement et conservé.
Il proposait déjà : liste de cibles, manifeste d'autorisation, empreinte de cible,
contrôle du serveur et nettoyage de l'environnement. Il n'était raccordé à aucun
lanceur ni fixture et n'empêchait donc pas l'ancienne fixture de se connecter à
une base personnelle locale. La reprise raccorde ces protections et ajoute les
tests déterministes, le contrôle avant migration et les barrières IA.

## Autorisation exacte des cibles

Les lanceurs créent un nouveau répertoire temporaire et exécutent `initdb` sur
son sous-dossier `data`, sans réutiliser le volume Docker personnel. Ils créent
leur base, puis une autorisation exclusive `p14-test-target.json` avec ouverture
en mode `x` : une autorisation existante n'est pas écrasée.

Une connexion d'intégration exige toutes les conditions suivantes :

- Pilote `postgresql+psycopg`, hôte numérique exact `127.0.0.1` et port explicite
  autre que 5432, 5433 ou 5434. Localhost seul n'est jamais une autorisation.
- Base `p07_validation` ou `p20_validation`. Le validateur accepte également
  `p07_real_` suivi de 12 caractères hexadécimaux pour la qualification séparée.
  Tout autre nom, notamment `dreams_local`, est refusé avant connexion.
- Rôle `p07_`, `p20_` ou `real_` suivi de 12 caractères hexadécimaux et mot de passe
  explicite. Les mots de passe sont aléatoires et ne sont pas imprimés.
- Répertoire d'autorisation hors dépôt et OneDrive, sans lien/jonction à sa
  racine, préfixé `p07_jobs_`, `dreams_p20_`, `p14_tests_` ou `p07-real-`, avec
  `data/PG_VERSION`. Manifeste borné à 1 024 octets et de version connue.
- `DATABASE_URL` et `TEST_DATABASE_URL` correspondent à l'empreinte exacte du
  manifeste : hôte, port, base, rôle et mot de passe. Aucune URL contradictoire
  ne doit être masquée par un simple remplacement dans une fixture.
- Aucun paramètre d'URL libpq arbitraire. Seule l'option générée
  `-csearch_path=p02_test_` suivie de 32 caractères hexadécimaux est acceptée
  pour les schémas de test ; elle ne change pas l'identité du cluster.
- Aucune variable `PG*` ne peut rediriger une connexion autorisée. Les lanceurs
  les retirent ; le validateur refuse leur réintroduction.

Après l'autorisation et avant migration, `probe` vérifie réellement le nom de
base, le rôle courant, le port et `data_directory`. Le garde psycopg répète ce
contrôle avant que SQLAlchemy puisse utiliser une nouvelle connexion dans pytest.
La vérification est annulée par rollback avant les opérations du test.

Le manifeste protège contre les mauvaises configurations et utilisations
accidentelles. Ce n'est pas un mécanisme de défense contre un programme malveillant
disposant des mêmes droits Windows et pouvant modifier le code ou les fichiers.

## Fixture et environnement

`conftest.py` ne charge plus `.env`. `PYTHON_DOTENV_DISABLED=1` est positionné
avant la collecte des modules applicatifs ; les fichiers personnels ne servent
pas de solution de repli. Les connexions à l'import, hors fixture ou dans un
test unitaire sont refusées. Les chemins standards `psycopg.connect` et
`psycopg.Connection.connect` sont gardés, avec validation avant tout socket libpq.

Chaque test PostgreSQL conserve son schéma UUID indépendant, migré jusqu'à la
révision courante, puis supprimé dans le cluster explicitement autorisé. Les
lanceurs arrêtent leur propre cluster et nettoient leur propre répertoire, sans
`DROP DATABASE` ni arrêt d'un service existant. Le simple lancement d'un test
d'intégration sans autorisation provoque un échec sûr, pas une validation ignorée.

`clean_environment` retire les URL et options PostgreSQL héritées, les variables
`RUN_*`, les anciennes autorisations P14, les secrets et proxies courants, puis
fixe les modes hors ligne. `isolated_environment` injecte seulement les URL et
racines privées du cluster créé. L'émotion est désactivée par défaut.

## Catégories pytest

| Marqueur | Sélection et comportement |
|---|---|
| `unit` | Aucun accès PostgreSQL, même si une configuration personnelle est présente |
| `integration` | Attribué aussi par la fermeture des dépendances de fixtures : toute dépendance transitive à `database` est identifiée |
| `browser` | Également intégration ; exige autorisation du cluster et origine HTTPS temporaire cohérente |
| `qualification` | Test réel émotionnel séparé ; option CLI `--allow-real-ai` obligatoire |

Les marqueurs automatiques sont ajoutés avant le filtre `-m`. Cela corrige les
anciens tests PostgreSQL non marqués sans modifier leur logique métier.

Pour Chrome, `WEB_TEST_URL` doit être identique à `WEB_ORIGIN`, en HTTPS sur
`127.0.0.1`, avec un port explicite différent de 5434/8443. Le lanceur fournit
un profil, un certificat et des données fictifs. `--emotion-web-test` active
uniquement la disponibilité de l'interface temporaire via un indicateur explicite
`P14_FAKE_EMOTION_UI` ; aucun worker ni modèle réel n'est démarré.

## IA, réseau et qualification séparée

Les tests ordinaires retirent les opt-in hérités et gardent les drapeaux HF hors
ligne et sans télémétrie. Ils bloquent les connexions réseau Python non locales,
les imports réels de torch/Transformers/Diffusers/Whisper/Hugging Face et les
commandes connues des workers, téléchargements et sous-processus IA réels. Les
tests d'adaptateurs installent explicitement des stubs ou faux sous-processus.
Les ponts synthétiques existants restent testables sans lire de poids.

`RUN_EMOTION_REAL=1` hérité ne suffit plus. Seul le test de qualification marqué
avec `--allow-real-ai` peut lever ces barrières ; le lanceur historique
`--emotion-real` ajoute cette option de façon explicite. Cette commande réelle
n'a pas été exécutée dans cette phase et nécessite une autorisation humaine.

Le lanceur réel P07 conserve son opt-in `--execute-real-once` et ses propres
contrôles de cluster/répertoire ; son environnement est nettoyé et les deux URL
doivent correspondre. Il n'a pas été exécuté. `verify_stt_real.py` est une commande
manuelle séparée sans PostgreSQL ; aucun lancement de celle-ci dans les tests.

Les gardes Python ne sont pas un pare-feu système pour un navigateur ou un binaire
natif. Ils couvrent les chemins standards du dépôt, pas l'exécution de tests
arbitraires hostiles ou un service local malveillant servant de proxy.

## Commandes Windows reproductibles

Préconditions : venv de développement existant, dépendances déjà installées.
Pour l'intégration : binaires PostgreSQL 17 présents ; si nécessaire définir
`P20_POSTGRES_BIN` vers leur répertoire. Ne pas exporter une URL personnelle.

```powershell
# Sans PostgreSQL, sans IA réelle : dossier pytest neuf et nettoyé à la fin.
.\.venv\Scripts\python.exe scripts\verify_image_jobs.py --unit-only

# Toute la suite hors navigateur et qualification, cluster neuf autorisé.
.\.venv\Scripts\python.exe scripts\verify_image_jobs.py --all-tests

# Chrome installé, HTTPS et cluster temporaires, interface émotion simulée.
.\.venv\Scripts\python.exe scripts\verify_p20.py --browser-only --emotion-web-test

.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend scripts
git diff --check
```

Un simple `pytest -m unit` est aussi possible mais peut rencontrer des permissions
sur l'ancien dossier temporaire partagé de Windows : le lanceur `--unit-only`
évite ce dossier. Aucun téléchargement de navigateur ou de modèle n'est prévu.

## Vérifications et difficultés traitées

Tests P14 : refus de base personnelle, cible inconnue, ports personnels, hôte
ambigu, options libpq, rôle non autorisé, manifeste absent/altéré, URL
contradictoires, `PGHOSTADDR`, import IA, sous-processus réel, réseau externe,
pilote direct et classe Connection, absence de chargement dotenv et contrôle
de l'identité serveur. Les chaînes de test sont fictives et les refus n'ouvrent
aucune connexion à une base personnelle.

Un ancien test CLI de quota présentait une URL fictive contradictoire pendant
une lecture effective de la base temporaire. Il utilise maintenant la cible
autorisée ; son objectif de confirmation explicite et de configuration centrale
est conservé. Son sous-processus de concurrence vérifie aussi cible et serveur.

Le contexte d'adaptateurs de SQLAlchemy est autorisé comme argument technique
psycopg ; les arguments libpq permettant une redirection restent refusés. Les
tests d'import sans inférence ne sont pas assimilés à une commande de lancement
du moteur. Aucun comportement de production n'a été adapté pour ces tests.

La recette complète a aussi révélé que deux tests de purge appellent
`monkeypatch.undo()` pour simuler une reprise. Les gardes emploient désormais
leur propre contexte `MonkeyPatch`, indépendant de celui fourni au test. Une
restauration volontaire des mocks ne peut donc plus enlever le garde PostgreSQL.
Le test unitaire d'interdiction PostgreSQL vérifie explicitement cette propriété.

## Résultats réellement exécutés le 13 novembre 2026

| Campagne | Résultat |
|---|---|
| Non-régression hors navigateur/qualification, cluster temporaire autorisé | **849 réussis, 15 désélectionnés**, 333,41 s |
| Commande unitaire finale `--unit-only`, sans PostgreSQL | **412 réussis, 454 désélectionnés**, 23,37 s |
| Tests de sécurité P14 finaux, sans base réelle ni modèle | **28 réussis**, 4,60 s |
| Ciblés PostgreSQL : sécurité, authentification, quota et préparation P07 réelle (sans exécution) | **99 réussis**, 38,02 s |
| Lanceur Windows Chrome `--browser-only --emotion-web-test` | **14 réussis, 847 désélectionnés**, 128,63 s |

Les nombres se recouvrent : ne pas les additionner comme tests uniques. La
collecte de la campagne à 849 précédait l'ajout des deux derniers cas de pytest
enfant ; ces deux cas ont été validés dans les campagnes finales à 412 et 28.
Les 15 désélections de cette campagne sont les 14 cas navigateur et la
qualification émotionnelle réelle. Les parcours navigateur ont leur campagne
séparée ; la qualification réelle n'a pas été exécutée, conformément à la mission.
Dans les deux scénarios enfant des tests de sécurité, le résultat attendu est
respectivement une qualification ignorée ou une erreur d'usage CLI, sans modèle.

La recette Chrome a aussi vérifié un redémarrage réel du PostgreSQL temporaire
et d'Uvicorn : historique, budgets et réservations conservés, audio fictif
reconsultable, puis purge du média fictif et réponse 404. Aucun navigateur ni
modèle n'a été téléchargé. Ces vérifications utilisent des comptes fictifs.

Ruff sur `backend scripts`, compilation Python et `git diff --check` réussis.
Seuls avertissements Git : conversions LF/CRLF annoncées, sans erreur de diff.
Le garde n'a pas été désactivé pour obtenir ces résultats. Les échecs des
campagnes intermédiaires (contexte SQLAlchemy, ancien test CLI contradictoire,
undo partagé, permissions du répertoire pytest partagé) ont été diagnostiqués
et corrigés dans l'isolation ou les tests, sans changement de production.

Les lanceurs se sont terminés, ont arrêté leurs clusters et nettoyé leurs
répertoires temporaires. Le contrôle des processus PostgreSQL/Python associés
aux préfixes des recettes ne trouve aucun processus restant. Aucun service ou
volume personnel n'a été arrêté, et aucune connexion à `dreams_local` effectuée.

### Fichiers de cette phase

- `scripts/test_safety.py` : travail repris et complété, validation et environnement.
- `backend/tests/conftest.py` : raccordement, catégories et gardes indépendants.
- `backend/tests/test_test_safety.py` : 28 cas déterministes P14.
- `scripts/verify_image_jobs.py` : autorisation, contrôle serveur, modes unit/all-tests.
- `scripts/verify_p20.py` : environnement contrôlé et vérification avant migration.
- `scripts/verify_image_real.py` : nettoyage d'environnement et cohérence des URL,
  uniquement testé en préparation ; aucune recette GPU exécutée.
- `backend/tests/test_ai_quota.py` : cohérence du test CLI et vérification de la
  cible dans son enfant de concurrence PostgreSQL.
- `pyproject.toml` : marqueurs unit/qualification, aucun seuil modifié.
- `README.md` et ce document : commandes et limites.

Le changement local de `frontend/styles/app.css` reste indépendant et intact :
SHA256 `d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.
Les seuls nouveaux fichiers candidats sont du Python et de la documentation ;
aucun modèle, média, sauvegarde ou secret ajouté. Aucun `git add`, commit, push,
restore, reset ni changement Jira. Les phases couverture métier, nouveaux tests
fonctionnels des workers et GitHub Actions ne sont pas commencées.
