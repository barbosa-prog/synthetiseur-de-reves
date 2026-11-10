# Synthétiseur de rêves

Production pédagogique locale en Python 3.12. Ce dépôt contient actuellement
**P01 : le socle FastAPI** et **P02 : le schéma PostgreSQL et ses migrations**.
Authentification, stockage physique des médias, worker et modèles IA ne sont pas
encore implémentés. Aucun service payant n'est nécessaire.

## Installation Windows (PowerShell)

Depuis la racine du dépôt, avec Python 3.12 accessible :

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Pour exécuter seulement le serveur, installer `requirements.txt` au lieu de
`requirements-dev.txt`. Les commandes utilisent directement l'interpréteur du
venv : aucune activation ni modification de la politique PowerShell nécessaire.
Les dépendances nécessitent un accès réseau lors de l'installation initiale.

Si `py -3.12` échoue, vérifier `py -0p` et l'accès à l'interpréteur indiqué.
Un Python Microsoft Store inaccessible ne signifie pas que le backend est défectueux.
Avec un autre interpréteur Python 3.12 déjà accessible :

```powershell
& 'C:\chemin\vers\python.exe' -m venv .venv
```

## Démarrage local

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Arrêt : `Ctrl+C`. Pour le développement, ajouter éventuellement `--reload`.
Lancement depuis la racine du dépôt. Aucun fichier `.env` n'est requis pour P01.
Le serveur reste lié à la boucle locale ; ne pas l'exposer publiquement.

Dans un second terminal :

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

| Méthode | Route | Description |
| --- | --- | --- |
| GET | `/api/v1/health` | État du processus API, réponse JSON 200 |
| GET | `/api/v1/docs` | Swagger UI |
| GET | `/api/v1/redoc` | ReDoc |
| GET | `/api/v1/openapi.json` | Contrat OpenAPI JSON |

FastAPI ajoute une route technique de redirection Swagger
`/api/v1/docs/oauth2-redirect` ; elle n'active aucune authentification.
Swagger UI et ReDoc chargent leurs ressources JavaScript/CSS depuis un CDN :
leur interface nécessite Internet avec la configuration actuelle. La route de
santé, OpenAPI JSON et les tests fonctionnent sans réseau après installation.

Réponse de santé :

```json
{"status":"ok","service":"synthetiseur-de-reves-api","version":"0.1.0"}
```

Ce contrôle vérifie uniquement que l'API répond, pas l'état des futurs services.
Les routes métier seront ajoutées dans leurs tickets respectifs.

## Contrat d'erreurs

```json
{"error":{"code":"not_found","message":"Ressource introuvable."}}
```

| Statut | Code | Cas |
| --- | --- | --- |
| 404 | `not_found` | Route ou ressource inexistante |
| 405 | `method_not_allowed` | Méthode refusée ; en-tête `Allow` préservé |
| 422 | `validation_error` | Requête ne respectant pas un schéma Pydantic |
| 500 | `internal_error` | Erreur inattendue, détail interne masqué |

Le gestionnaire prépare aussi les erreurs HTTP 400, 401, 403, 413, 415 et 429,
sans implémenter les fonctions associées. Les erreurs ne renvoient ni corps de
requête, ni détail d'exception. Le serveur ne journalise pas les corps de requête ;
les journaux techniques Uvicorn peuvent inclure URL et trace d'exception : ne pas
placer de données privées dans les URL ou les messages d'exception.

## Tests et qualité

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest --cov=backend.app --cov-report=term-missing --cov-fail-under=80
.\.venv\Scripts\python.exe -m ruff check backend
```

Les tests vérifient santé, documentation, contrat OpenAPI, 404/405, validation
422, préservation des en-têtes et masquage des détails privés pour 401/500.
Les routes de panne et validation existent uniquement dans les applications de test.

Validation P01 sur Windows avec Python 3.12.14 : 12 tests réussis, couverture des
48 instructions de `backend.app` à 100 %, Ruff sans erreur. Un avertissement de
dépréciation Starlette indique que son client de test migre de httpx vers httpx2 ;
les tests restent opérationnels. Les dépendances directes sont figées aux versions
testées ; le verrouillage complet des dépendances transitives relève de P15.

## Structure et suite

```text
backend/
  app/
    main.py       # création de l'application
    api.py        # routes /api/v1
    schemas.py    # contrats Pydantic
    errors.py     # gestionnaires d'erreurs
  tests/
    test_api.py
requirements.txt
requirements-dev.txt
pyproject.toml
```

Architecture validée pour la suite : Streamlit, FastAPI, PostgreSQL, stockage privé
et worker séparé ; modèles IA locaux à sélectionner après essais matériels.
P09 devra inclure filtre date/humeur, fréquences et émotions dominantes.
P15 devra inclure installation reproductible, build et déploiement local automatisé.
Ces fonctions ne sont pas implémentées dans P01/P02.

Git existant conservé. Aucun commit, push ou changement Jira sans accord préalable.

## P02 — PostgreSQL local sous Windows

Les routes P01 restent inchangées. `/api/v1/health` reste un contrôle du processus,
sans connexion automatique à PostgreSQL. Aucun CRUD métier n'est exposé dans P02.

### Installation et démarrage avec Docker Compose

Prérequis : Docker Desktop déjà installé et démarré en mode conteneurs Linux,
Compose v2 et Python 3.12. PostgreSQL 17 est utilisé, sans service cloud.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Éditer `.env` localement : remplacer le mot de passe fictif par une valeur
aléatoire privée, puis renseigner la même valeur dans `DATABASE_URL` (encodage URL
si caractères spéciaux). Ne pas afficher `.env`, ni copier son contenu dans une
capture, un terminal partagé ou Git. Les variables système priment sur `.env`.
Le port Windows par défaut est **5433**, lié à `127.0.0.1` uniquement.

```powershell
docker version
docker compose up -d --wait postgres
docker compose ps
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

Ne pas utiliser `docker compose config` dans une sortie partagée : il peut afficher
les secrets interpolés. Les identifiants du conteneur sont consultables par un
administrateur Docker ; `.env` n'est pas un coffre-fort. Le volume nommé conserve
les données après arrêt. Modifier le mot de passe dans `.env` ne change pas celui
d'un volume PostgreSQL déjà initialisé. L'image est fixée au majeur 17 ; elle n'est
pas encore verrouillée par digest (travail de reproductibilité P15).

```powershell
# Arrêter sans supprimer les données
docker compose stop postgres
# Reprendre
docker compose start postgres
# Retirer le conteneur et le réseau en conservant le volume
docker compose down
```

Ne pas ajouter `-v` à `down` : cela supprimerait le volume. Le volume contient des
données privées ; sa protection au repos reste à vérifier avant tout usage réel.

### Alternative PostgreSQL 17 déjà installé

Docker n'est pas obligatoire. Utiliser une instance locale et créer une base et un
rôle dédiés à l'aide de pgAdmin, avec saisie privée du mot de passe. Renseigner
`DATABASE_URL` avec le port de cette instance, puis lancer `alembic upgrade head`.
Ne pas modifier une base existante pour les essais. Le rôle de migration doit
pouvoir créer les tables et contraintes ; ne pas utiliser le superutilisateur pour
l'application finale. Aucun service PostgreSQL Windows n'est modifié par ce dépôt.

### Schéma et migration

Migration initiale **0001**, écrite explicitement à partir du modèle ; aucune
génération automatique depuis une base préexistante. `upgrade head` crée aussi la
table technique `alembic_version`. Aucune création via `Base.metadata.create_all`
au démarrage : Alembic est l'unique voie de création du schéma.

| Table | Champs et contraintes principales |
| --- | --- |
| `users` | UUID PK, email nullable unique/non blanc, création TIMESTAMPTZ |
| `dreams` | UUID PK, propriétaire FK obligatoire, texte/émotion nullables, statut, dates |
| `media` | UUID PK, rêve FK obligatoire, type audio/image/sound, clé privée unique/non blanche, expiration |
| `jobs` | UUID PK, rêve FK obligatoire, type stt/image/tts, état, tentatives 0–3, code erreur |

Relations : `users 1 → n dreams`, `dreams 1 → n media`, `dreams 1 → n jobs`.
UUID générés par PostgreSQL ou l'ORM, dates avec fuseau, index utilisateur/date
et index sur les FK des médias/jobs. Toutes les FK utilisent `ON DELETE RESTRICT` :
aucune suppression en cascade susceptible de perdre les références de fichiers
avant leur purge. P10/P19 devront organiser explicitement cette purge.

Statuts rêve : `draft`, `processing` (compatibilité architecture), `transcribing`,
`transcribed`, `correcting`, `generating`, `ready`, `error`, `deleted`.
Ces valeurs préparent les phases ; aucune orchestration ou transition automatique
n'est développée ici. Le texte et l'émotion peuvent rester NULL au départ ; un
texte présent doit être non blanc et `ready` exige un texte. L'émotion reste
facultative même pour `ready`. `deleted` exige `deleted_at` et réciproquement.
Les clés médias sont des références internes, pas des URL : leur sécurité physique,
validation de chemin et accès seront traités dans P19. Aucun fichier réel n'est créé.

La migration est réversible avec `alembic downgrade base`, mais cette commande
**supprime les quatre tables** : à réserver à une base jetable. Pour préparer une
future évolution après modification des modèles :

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "description"
# Relire la migration avant application
```

### Tests PostgreSQL

Sans configuration PostgreSQL, les tests d'intégration sont explicitement ignorés.
Ce résultat ne valide pas la persistance ni les migrations sur un serveur réel.

Créer une **base de test locale dédiée**, puis renseigner `TEST_DATABASE_URL` dans
le `.env` privé (valeur fictive commentée dans `.env.example`). Le rôle de test doit
pouvoir créer et supprimer un schéma dans cette base. Les tests refusent les hôtes
distants et utilisent un schéma aléatoire `p02_test_<uuid>` par test, supprimé à la
fin. Ne jamais pointer cette variable vers une base de production. Ne pas exécuter
avec `--showlocals` : cela pourrait afficher des variables privées lors d'un échec.

```powershell
# Suite complète, incluant les 12 tests P01
.\.venv\Scripts\python.exe -m pytest
# Intégration seule : doit afficher des réussites, pas seulement des skips
.\.venv\Scripts\python.exe -m pytest -m integration
# Tests accessibles sans serveur
.\.venv\Scripts\python.exe -m pytest -m "not integration"
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m pip check
```

Les tests PostgreSQL appliquent la migration, contrôlent tables/FK, comparent le
schéma aux modèles, testent downgrade/upgrade et réapplication, puis insertions,
relations et lecture après fermeture des sessions et connexions physiques.
Ils vérifient le rejet des FK inexistantes, propriétaires absents, doublons,
statuts/types/émotions invalides, texte/clé blancs, tentatives hors limites et
suppression d'un parent référencé. Toutes les données sont fictives.

Les erreurs de configuration et de migration masquent les URL privées. Les moteurs
désactivent l'écho SQL et masquent les paramètres. Ne jamais journaliser une URL de
connexion, un objet de configuration privé ou une exception brute de pilote.

### Validation réalisée le 10 novembre 2026

Sous Windows, Python 3.12.14 et PostgreSQL 17 natif : instance temporaire isolée,
mot de passe aléatoire non affiché, aucun changement d'une base existante.
`alembic upgrade head`, `alembic current` et `alembic check` ont terminé avec le code 0.
Suite complète : **38 tests réussis** (12 P01, 7 configuration/SQL hors ligne,
19 intégration PostgreSQL), couverture des 119 instructions de `backend.app` :
**100 %**, durée 7,11 s. La couverture des migrations n'est pas incluse dans ce taux ;
leur comportement est vérifié par les tests d'intégration.
Ruff et `pip check` : aucune erreur. Avertissement Starlette/httpx déjà présent en P01.
Le cache pytest a été désactivé pour cette campagne (`-p no:cacheprovider`) après
un avertissement de permissions lors du premier essai. Le serveur temporaire a
été arrêté et son répertoire supprimé après validation.

Docker Compose n'a pas été démarré : client installé mais moteur Docker Desktop
indisponible. Les instructions Compose restent à valider quand ce moteur sera actif.
Les PDF/CSV sources de l'audit initial ne sont plus accessibles à leurs anciens
emplacements ; le schéma a été repris du relevé d'audit et des exigences P02 de
l'échange. Le texte et l'émotion nullables, ainsi que les phases explicites, sont
les adaptations demandées pour le cycle de brouillon.
