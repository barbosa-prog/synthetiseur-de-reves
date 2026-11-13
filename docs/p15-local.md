# P15 / SCRUM-19 — Déploiement local reproductible

Audit et recette du **14 novembre 2026**, sans modification Jira. La procédure
opérationnelle est en tête du [README](../README.md#p15--installation-et-démonstration-locale-de-référence).

## Périmètre retenu

L'utilisateur a confirmé FastAPI + Jinja2 + PostgreSQL. Streamlit n'existe pas
dans les sources ou dépendances : il est une référence historique de maquette
remplacée par P20. Aucun serveur Streamlit fictif ni nouvelle interface ajouté.
Docker reste facultatif. Aucun modèle ni worker IA n'est requis pour installer,
ouvrir l'interface, créer un compte et vérifier les sessions/la base.

## Obstacles constatés et traitement

| Constat vérifié | Traitement |
| --- | --- |
| README accumulant des recettes historiques ; première commande en HTTP, incompatible avec les cookies web Secure et l'origine HTTPS contrôlée | Procédure P15 de référence en tête, historique séparé, ordre PostgreSQL → migrations → FastAPI/Jinja2 |
| Dépendances directes figées, mais transitives variables | Verrou Windows/CPython 3.12 avec 52 versions et SHA-256 de wheels ; même verrou dans la CI |
| Dans un venv neuf, `annotated-doc` devient 0.0.6 et `argon2-cffi-bindings` 26.2.0, contre 0.0.5 et 26.1.0 dans l'ancien venv | Dérive démontrée par résolution, puis figée et testée ; aucun changement des dépendances IA |
| `.env.example` désignait une base personnelle et suggérait de copier sans protection | Noms fictifs `dreams_demo` / `dreams_app`, garde contre l'écrasement du `.env`, tests via lanceurs autorisés |
| Initialisation PostgreSQL natif peu détaillée ; Compose présenté d'abord | Lanceur de démonstration native jetable, sans configuration privée et sans service Windows |
| HTTPS, certificat, stockage privé et migrations dispersés | Prérequis et configuration regroupés ; dix migrations jusqu'à 0010 ; médias/exports hors dépôt/OneDrive |
| Build Tailwind susceptible d'être pris pour un prérequis de démarrage | CSS compilé déjà versionné ; Node/npm uniquement pour reconstruire après modification |
| `py -3.12 --version` échoue ici sur l'alias Microsoft Store, accès refusé | Alternative par chemin d'un interpréteur accessible documentée ; bootstrap de recette avec l'interpréteur du venv existant |
| Validation TLS du client local bloquée par Avast | Diagnostic et limitation explicites ; aucun contournement ajouté au lanceur |

## Environnement et isolation réels

- Windows x86-64, CPython **3.12.14**, PostgreSQL natif **17.5**.
- Deux venv neufs dans `tmp/p15-clean/venv` et `tmp/p15-locked/venv`, sans
  `system-site-packages`. Le premier résout `requirements-dev.txt` ; son rapport
  pip fournit les versions et empreintes du verrou. Le second est installé
  **hors ligne** à partir des wheels téléchargées et vérifiées par hash.
- Aucune installation de moteurs IA. Les dépendances de recette incluent
  `httpx`, `trustme` et Playwright ; les tests utilisent Chrome déjà installé.
- Copie des sources dans `tmp/p15-source`, sans `.env`, `.git`, ancien venv ou
  source CSS personnelle. Le lanceur y exécute ses migrations depuis cette copie.
- Clusters créés dans de nouveaux répertoires temporaires autorisés P14 hors
  dépôt et OneDrive, rôle/mot de passe aléatoires, base `p20_validation`,
  interface et PostgreSQL liés exclusivement à `127.0.0.1`, ports libres.
- Vérification de l'identité réelle du serveur avant migration via le manifeste
  P14 : base, rôle, port et répertoire de données. Aucun accès à `dreams_local`.
- `.env` personnel ignoré par `PYTHON_DOTENV_DISABLED=1`, URL héritées et secrets
  retirés de l'environnement enfant. `.env` personnel ni lu, ni écrasé.
- API_DOCS_ENABLED=0, EMOTION_ENABLED=0, drapeaux hors ligne ; aucun worker lancé.
  Aucun certificat installé dans le magasin de confiance système.
- Seuls les processus du lanceur sont arrêtés. Aucun arrêt global de service,
  aucune commande Docker, aucun service existant utilisé.

## Commandes et résultats réellement observés

Les commandes de recette utilisent l'interpréteur neuf
`tmp/p15-locked/venv/Scripts/python.exe` ; `python` ci-dessous désigne ce chemin.

| Commande / contrôle | Résultat |
| --- | --- |
| `initdb.exe --version` | PostgreSQL 17.5 |
| `python --version` | Python 3.12.14 |
| Création de deux venv avec `.venv/Scripts/python.exe -m venv ...` | Réussie, sans héritage des paquets de l'ancien venv |
| `pip install --only-binary=:all: --report tmp/p15-clean/install.json -r requirements-dev.txt` dans le premier venv vide | Réussie ; seules les dépendances de développement demandées sont résolues |
| `pip download --require-hashes --only-binary=:all: -r requirements-windows-py312.lock --dest tmp/p15-clean/wheelhouse` | 52 wheels téléchargées avec contrôle des empreintes |
| `pip install --no-index --find-links tmp/p15-clean/wheelhouse --require-hashes --only-binary=:all: -r requirements-windows-py312.lock` dans le second venv vide | Réussie, installation hors ligne |
| `pip check` | `No broken requirements found.` |
| `scripts/local_demo.py --stop-after 2` | Code 0 ; démarrage PostgreSQL/HTTPS, arrêt des processus et suppression du répertoire vérifiés |
| `tmp/p15-source/scripts/local_demo.py`, puis Ctrl+C dans son terminal dédié | URL affichée, interruption reçue, services arrêtés et ressources supprimées ; le terminal PowerShell retourne 1 pour cette interruption |
| `alembic upgrade head`, `alembic current`, `alembic check` lancés par ces démonstrations | Codes 0 sur les nouveaux clusters |
| `tmp/p15-source/scripts/dev_https.py` | Certificats créés dans le `tmp/https` de la copie, aucune autorité installée |
| Copie protégée de `.env.example` vers `.env` | Réussie dans la copie de recette uniquement, après les essais sans `.env` ; aucun écrasement du vrai `.env` |
| `scripts/local_demo.py --check` | Échec attendu sur ce poste : `delai_demarrage_depasse_certificat_tls`, puis arrêt du cluster ; ce contrôle n'est pas présenté comme réussi |
| `scripts/verify_image_jobs.py --all-tests` | **914 passed, 15 deselected, 1 warning**, 390,23 s ; campagne avant les quatre derniers cas P15 |
| `scripts/verify_image_jobs.py --local-demo-only` après ajout de tous les cas P15 | **70 passed, 1 warning**, 10,47 s |
| `scripts/verify_image_jobs.py --unit-only` hors bac à sable | **475 passed, 458 deselected, 1 warning**, 19,96 s |
| `scripts/verify_p20.py --browser-only --emotion-web-test` | **14 passed, 915 deselected, 1 warning**, 116,58 s ; campagne avant les quatre derniers cas P15 |
| `pytest backend/tests/test_ci_workflow.py -q -p no:cacheprovider` après passage de la CI au verrou | **10 passed**, 0,52 s |
| `ruff check backend scripts`, `compileall -q backend scripts`, `git diff --check` | Réussis ; Git annonce sa conversion habituelle LF/CRLF |

Les quatre derniers cas P15 sont les trois validations de durée du lanceur et le
parcours HTTP/PostgreSQL en TestClient ; ils sont inclus dans les 70 réussites de
la recette ciblée. Aucun test ignoré pour contourner une erreur. Les 15 tests
désélectionnés de la campagne complète sont les navigateurs et la qualification IA.
La campagne Chrome désélectionne les tests hors navigateur, elle ne les ignore pas.

Le premier `--unit-only`, exécuté dans le bac à sable, a donné **2 failed,
473 passed, 458 deselected**, 19,50 s : les deux processus synthétiques de
`test_emotion_bridge.py` terminaient sans leur sortie JSON. La même commande
hors bac à sable donne les 475 réussites ci-dessus ; aucun test ni protection
n'a été modifié pour les faire passer. La campagne complète hors bac à sable
les avait également réussis. Les recettes natives/processus doivent donc être
exécutées dans un contexte autorisant leurs sous-processus et fichiers temporaires.

L'avertissement existant concerne la dépréciation de `httpx` par le TestClient
Starlette au profit de `httpx2`. Il ne provoque pas d'échec ; migrer ce client
n'est pas nécessaire au démarrage et n'est pas inclus dans P15.

## Ce qui est prouvé pour API, interface et base

La recette ciblée appelle **le même** `verify_application()` que `--check`, via
TestClient et une vraie base PostgreSQL migrée et jetable : santé du processus,
OpenAPI, docs désactivées, CSS livré, inscription/connexion Bearer, historique,
compte réellement persistant en SQL, formulaire Jinja2/CSRF, connexion web,
cookies Secure/HttpOnly, révocation et rejet du jeton révoqué.

Ce test ne prétend pas vérifier le transport TLS. Les 14 tests Chrome exercent
séparément le vrai serveur HTTPS, les pages, sessions, médias et workers fictifs.
Leur recette vérifie aussi la persistance après redémarrage réel de PostgreSQL
et Uvicorn (P11/P09/P04/P19). Ils utilisent l'exception de certificat de leur
contexte Playwright de test, déjà présente avant P15.

Les tests P15 vérifient en plus : cohérence du verrou avec les dépendances
directes, présence du pilote binaire PostgreSQL, absence de moteurs IA du verrou,
absence de sortie privée lors d'un échec de préparation, arrêt de notre cluster
même si l'arrêt du serveur expire, absence d'arrêt d'un cluster non démarré et
rejet des durées invalides avant toute création de service.

## Limites et validation sur une seconde machine

**TLS strict non validé ici.** Une sonde locale ne transmettant aucune donnée
applicative a comparé les empreintes du certificat généré et reçu : elles
diffèrent. Le certificat reçu est émis par `Avast Web/Mail Shield Untrusted Root`
et la vérification OpenSSL échoue avec le code 20. Le lanceur conserve la
validation de chaîne et d'hôte ; aucune option `verify=False` n'a été ajoutée.
Avast n'a pas été désactivé, aucune racine non fiable importée. Il reste à refaire
`--check` sur une machine sans cette interception et à vérifier la confiance du
certificat choisi pour une démonstration normale.

L'installation des binaires Python/PostgreSQL depuis leurs installateurs n'a pas
été refaite : ils étaient déjà présents. L'installation **des paquets applicatifs**
a été reproduite dans deux environnements neufs, puis les sources ont été testées
sans configuration personnelle. Ce n'est pas l'équivalent d'une seconde machine
Windows vierge. L'alias Python Microsoft Store du poste courant reste défectueux.

Linux, Docker Desktop/Compose, une base persistante avec rôle applicatif non
superutilisateur, la reconstruction npm, l'inférence réelle, microphone matériel,
certificat approuvé et arrêt après coupure électrique restent hors de cette
recette. Le verrou ne couvre que Windows x86-64 / CPython 3.12. L'image Compose
`postgres:17` n'est pas verrouillée par digest. Le workflow distant n'a pas été
déclenché : son installation est alignée sur le verrou et ses contrats statiques
passent, mais une nouvelle exécution GitHub reste nécessaire après votre commit.

La préparation est livrée ; la validation P15 intégrale sur une seconde machine,
notamment TLS strict et prérequis natifs, reste à faire avant clôture humaine du ticket.
