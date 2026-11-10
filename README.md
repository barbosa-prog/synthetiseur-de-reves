# Synthétiseur de rêves

Production pédagogique locale en Python 3.12. Ce dépôt contient actuellement
**P01 : le socle FastAPI**, **P02 : PostgreSQL** et **P03 : authentification et
isolation des rêves**. Stockage physique des médias, worker et modèles IA ne sont
pas encore implémentés. Aucun service payant n'est nécessaire.

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
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
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

Le gestionnaire prépare aussi les erreurs HTTP 400, 401, 403, 409, 413, 415, 429 et 503.
Les erreurs ne renvoient ni corps de
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

Cette section décrit le périmètre P02 ; P03 ajoute les routes protégées détaillées plus bas.

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

## P03 — Authentification et isolation

### Démarrage Windows

Utiliser PostgreSQL local comme dans P02. Ne pas recopier `.env.example` sur un
`.env` existant. Aucun nouveau secret partagé ni fournisseur d'identité n'est requis.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Si Docker Desktop est actif :
docker compose up -d --wait postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Le journal d'accès Uvicorn est désactivé pour éviter de conserver des URL privées.
L'application ne journalise pas les identifiants, corps JSON, mots de passe,
en-têtes Authorization ou jetons. Ne pas activer les traces HTTP détaillées ni
`--showlocals` dans les tests. HTTP local est accepté exclusivement sur la boucle
locale ; HTTPS sera obligatoire avant toute exposition réseau. Les réponses privées
portent `Cache-Control: no-store`. Aucun cookie d'authentification n'est créé.

### API et intégration Streamlit

| Méthode | Route | Contrat |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | JSON email/password ; 201 avec id/email ; doublon 409 |
| POST | `/api/v1/auth/login` | JSON email/password ; 200 avec access_token/token_type/expires_at |
| GET | `/api/v1/auth/session` | Bearer requis ; identité et expiration, sans renvoyer le jeton |
| POST | `/api/v1/auth/logout` | Bearer requis ; révocation de cette session, 204 |
| GET | `/api/v1/dreams/{uuid}` | Rêve existant du compte uniquement |
| PATCH | `/api/v1/dreams/{uuid}` | Modification minimale texte/émotion, sans changement de propriétaire |
| DELETE | `/api/v1/dreams/{uuid}` | Suppression logique du rêve du compte ; 204 |

L'e-mail est validé syntaxiquement et normalisé en minuscules ; la possession de
l'adresse n'est pas vérifiée (aucun envoi d'e-mail). Mot de passe : 15 à 128
caractères, espaces autorisés, sans règle artificielle de composition. L'inscription
ne connecte pas automatiquement. Les identifiants incorrects, comptes inconnus et
comptes P02 sans mot de passe reçoivent la même réponse 401. L'inscription en
doublon retourne 409 : ce compromis pédagogique permet d'inférer qu'une adresse
est déjà enregistrée, même si le message reste générique.

Streamlit devra appeler l'API depuis son serveur via httpx, jamais PostgreSQL.
Après login, conserver `access_token` uniquement dans `st.session_state` de la
session courante ; le transmettre dans `Authorization: Bearer <jeton>`.
Ne pas le placer dans une URL, une zone affichée, un cache global `st.cache_data`
ou `st.cache_resource`, le navigateur ou un fichier. Sur 401, effacer l'état
d'authentification ; à la déconnexion appeler logout puis vider l'état local.
Aucun écran Streamlit n'est ajouté dans P03. Swagger permet un essai manuel via
Authorize, mais ne constitue pas l'intégration Streamlit et ne doit pas être filmé
avec un jeton visible. Aucun exemple contenant un secret réel n'est fourni.

### Mots de passe et sessions

Argon2id via argon2-cffi, sel aléatoire individuel, mémoire 64 Mio, trois passes,
parallélisme 1. Seul `users.password_hash` contient le résultat ; aucune copie du
mot de passe en clair en base. Le serveur doit recevoir le mot de passe pour le
vérifier, mais ne le persiste ni ne le journalise. Les modèles d'entrée utilisent
`SecretStr` pour masquer leurs représentations. Une vérification factice est
effectuée pour les comptes inconnus. Un hachage dont les paramètres sont anciens
est renouvelé après une connexion réussie.

Chaque login crée un nouveau jeton cryptographique de 32 octets (256 bits),
sans données utilisateur encodées. Il est communiqué une seule fois dans la
réponse login ; seule son empreinte SHA-256 est enregistrée dans `auth_sessions`.
Expiration absolue **8 heures**, sans prolongation implicite. Chaque requête
vérifie en base l'expiration et la révocation. Logout invalide immédiatement le
jeton présenté pour les requêtes suivantes ; les autres sessions restent actives.
Une requête déjà authentifiée avant la révocation peut finir son traitement.
Pas de renouvellement automatique, de révocation globale ou de réinitialisation
de mot de passe dans P03.

### Isolation et limites du ticket

Chaque sélection de rêve combine son UUID et `user_id` issu de la session serveur,
en excluant les rêves supprimés. Un UUID inconnu, un rêve d'un autre compte et un
rêve supprimé renvoient le même 404. Les champs `user_id`, `status` et clés privées
ne sont pas modifiables via PATCH. Aucune route de création audio, d'historique,
d'export, de média ou de job n'est ajoutée. Les accès privés existants sont protégés.
La modification est volontairement minimale pour vérifier P03 ; le parcours de
correction P06 et le dashboard P09 restent à développer.

DELETE pose `deleted_at` et l'état `deleted`, sans effacer les références de
médias/jobs : ce n'est pas encore une suppression RGPD complète. La purge physique
relève de P10/P19. Les sessions expirées/révoquées et les anciennes clés de
limitation ne sont pas purgées automatiquement ; leur rétention et une tâche de
nettoyage seront à traiter dans P12/P13. Utiliser seulement des comptes fictifs
pour cette démonstration. Aucune authentification ni sécurité au niveau PostgreSQL
RLS n'est revendiquée : les droits sont appliqués dans l'API.

### Protection contre les tentatives répétées

Fenêtres de 15 minutes : **5 tentatives par e-mail** et **30 par IP**, pour login
et inscription séparément. Les succès comptent aussi ; la sixième tentative du
même compte est bloquée jusqu'à fin de fenêtre. Réponse 429 avec `Retry-After`.
Les compteurs sont persistants dans PostgreSQL, partagés entre processus et
protégés par verrous transactionnels, y compris sous requêtes simultanées.
L'e-mail et l'IP ne sont pas stockés dans ces compteurs : clé SHA-256 pseudonymisée,
ce qui n'est pas une anonymisation et n'empêche pas une attaque par dictionnaire.

L'IP provient de la connexion directe, jamais d'un X-Forwarded-For fourni par le
client. Désactiver aussi les proxy headers Uvicorn si le service est placé derrière
un relais non fiable. Pour Streamlit local, les utilisateurs partagent l'IP du
serveur Streamlit et donc son quota IP. Cette limitation peut être utilisée pour
provoquer un blocage temporaire de compte ; elle n'est pas une protection complète
contre un déni de service. La protection réseau, les tailles de requêtes et la
supervision approfondie restent dans P12.

### Migration 0002 et données P02

`0002_authentication.py`, descendante de `0001`, ajoute `password_hash` nullable,
l'index unique `lower(email)`, `auth_sessions` et `auth_throttles`. Les quatre tables
P02 et leurs données sont conservées. Les comptes hérités sans hachage ne peuvent
pas se connecter et aucun mot de passe par défaut n'est créé. Leur éventuelle
activation nécessitera une procédure distincte autorisée.

Si des adresses P02 diffèrent uniquement par leur casse, l'index unique empêche la
migration : il faut les examiner et les corriger volontairement, sans fusion ou
suppression automatique. `downgrade 0001` retire les sessions, compteurs et
hachages ; il n'est à utiliser que dans une base jetable ou avec procédure validée.

### Tests

Avec `TEST_DATABASE_URL` vers une base locale dédiée :

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --cov=backend.app --cov-report=term-missing --cov-fail-under=80
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m pip check
```

Sans PostgreSQL configuré, les tests d'intégration sont signalés comme ignorés,
jamais comme validés. Les tests utilisent exclusivement des comptes fictifs.
Les assertions P01/P02 sur l'ensemble des routes/tables et la révision courante
sont adaptées à P03 ; leurs comportements précédents restent vérifiés.

Validation P03 réalisée le 10 novembre 2026 sous Windows et Python 3.12.14, avec
PostgreSQL 17 natif temporaire : **69 tests réussis, aucun ignoré**, en 28,20 s.
Répartition : 12 tests API P01, 7 configuration P02, 19 intégration PostgreSQL P02,
15 tests de primitives/refus P03 et 16 tests d'intégration authentification P03.
Couverture `backend.app` : **99,72 %** (360/361 instructions ; migrations exclues
de ce taux mais exécutées dans les tests). Ruff et `pip check` sans erreur.
Deux avertissements observés : dépréciation Starlette/httpx connue et avertissement
Pydantic sur un attribut d'alias lors du test d'inscription concurrente ; aucun
échec ni fuite de données observé dans ces essais.

Alembic `upgrade head`, `current`, `check` ont terminé avec code 0. Un test part
de la révision 0001 avec données fictives puis applique 0002 et vérifie leur
conservation. Inscription concurrente : un seul compte créé ; six connexions
concurrentes sur un même e-mail : cinq tentatives traitées, une refusée en 429.
La recette réseau réelle Uvicorn/PostgreSQL a obtenu successivement 201 (register),
200 (login), 200 (session), 204 (logout), 401 (réutilisation du jeton révoqué).
Les serveurs temporaires ont été arrêtés et leur répertoire supprimé.
Docker Compose et l'interface Streamlit n'ont pas été testés dans cette campagne.
