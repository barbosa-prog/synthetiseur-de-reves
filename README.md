# Synthétiseur de rêves

Production pédagogique locale en Python 3.12. Ce dépôt contient actuellement
**P01 : le socle FastAPI**, **P02 : PostgreSQL**, **P03 : authentification et
isolation des rêves** et **P20 : interface web Jinja2/Tailwind**.
Stockage physique des médias, worker et modèles IA ne sont
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

Architecture finale : HTML/Jinja2, Tailwind CSS et JavaScript, FastAPI, PostgreSQL, stockage privé
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

### API Bearer et ancienne piste Streamlit

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

La piste d'intégration Streamlit ci-dessous est historique et remplacée par P20.
Un client serveur Streamlit pourrait appeler l'API via httpx, jamais PostgreSQL.
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

## P20 — Interface web Jinja2 et Tailwind local

L'interface finale est servie par la même application FastAPI que l'API.
Streamlit est exclusivement la référence de maquette de pré-production.
La charte utilise bleu nuit `#0B1120`, surfaces `#121C30`/`#172238`, lavande
`#B39AFF`, texte `#EAF0FF` et secondaire `#B9C5DC`, avec une police système locale.
Aucune police, image, feuille de style ou bibliothèque JavaScript n'est chargée
depuis un CDN. Le CSS compilé est livré dans le dépôt.

### Pages et périmètre

| Route | Fonction |
| --- | --- |
| `/` | Redirige vers l'espace protégé |
| `/inscription` GET/POST | Formulaire et création de compte fictif |
| `/connexion` GET/POST | Formulaire et connexion par cookie |
| `/accueil` GET | Espace privé et présentation des étapes à venir |
| `/deconnexion` POST | Révocation et suppression des cookies |
| `/web/session` GET | Contrôle privé d'expiration, sans jeton dans le JSON |
| `/static/...` | CSS compilé, JavaScript et favicon publics uniquement |

Navigation responsive, formulaire utilisable sans JavaScript, lien d'évitement,
labels et messages accessibles. Aucun bouton ne prétend capturer un audio ou
générer une image. Les étapes futures sont identifiées « À venir ». Aucun média
privé n'est créé ni servi dans `static/`. P04, P19 et les fonctionnalités IA ne
sont pas implémentés par P20.

### Installation et compilation sous Windows

Prérequis : Python 3.12, PostgreSQL local, Node.js et npm. L'installation télécharge
seulement les dépendances de développement, sans service payant ni modèle IA.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Push-Location frontend
npm.cmd ci --ignore-scripts --no-audit --no-fund
npm.cmd run build
Pop-Location
```

`frontend/package-lock.json` fige les dépendances JavaScript. Tailwind CLI 4.3.0
compile `frontend/styles/app.css` en `backend/app/web/static/css/app.css`.
`npm.cmd run watch`, depuis `frontend`, recompile pendant le développement.
Le serveur n'a pas besoin de Node pour servir le CSS déjà compilé.
`frontend/.gitignore` exclut uniquement son `node_modules/` ; le `.gitignore`
principal est conservé. En cas d'erreur de chaîne de certificats npm, utiliser
l'autorité approuvée de l'environnement via `NODE_EXTRA_CA_CERTS`, sans désactiver
la vérification TLS ni modifier la configuration globale pour la contourner.

### HTTPS local

Les cookies sont toujours `Secure` : aucun mode HTTP avec cookies affaiblis.
Configurer `WEB_ORIGIN=https://localhost:8443` dans le `.env` privé si nécessaire.
Le schéma et l'hôte des pages doivent correspondre à cette origine exacte.
Les API Bearer P03 restent utilisables sur leur origine locale HTTP historique.

```powershell
# PostgreSQL déjà démarré et DATABASE_URL configurée
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\dev_https.py
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8443 --no-access-log --no-proxy-headers --ssl-keyfile tmp/https/key.pem --ssl-certfile tmp/https/cert.pem
```

Ouvrir **https://localhost:8443/connexion**. Arrêt : `Ctrl+C`.
Le script crée un certificat de développement dans `tmp/https`, déjà ignoré par
Git, sans écraser les fichiers existants et sans installer d'autorité dans Windows.
Ce certificat n'est pas publiquement approuvé : un avertissement navigateur est
attendu. Pour une utilisation normale sans exception de certificat, configurer
un certificat local approuvé par le poste. N'accepter une éventuelle exception
manuelle que pour cette instance locale identifiée, jamais pour un site distant.
Aucune clé privée ni certificat de développement n'est ajouté au dépôt.

### Sessions, CSRF et compatibilité P03

Le formulaire de connexion réutilise le service P03, extrait sans changement de
ses règles métier. Les routes JSON `/api/v1/auth/*` gardent leur contrat Bearer
et ne prennent pas les cookies comme justificatif d'authentification. Les routes
web résolvent le cookie vers les mêmes sessions PostgreSQL : empreinte SHA-256,
expiration absolue huit heures, révocation immédiate pour les requêtes suivantes.
Pas de migration supplémentaire. Aucune dépendance à un service externe.

Cookie d'authentification `__Host-dream_session` : `HttpOnly`, `Secure`,
`SameSite=Lax`, `Path=/`, aucun `Domain`, `Expires` ou `Max-Age`. Le navigateur
peut restaurer un cookie de session lors de la restauration d'une session ;
l'expiration serveur reste l'autorité. Aucun jeton d'authentification dans l'URL,
le HTML, les réponses JSON web, JavaScript ou un stockage navigateur applicatif.
Il reste naturellement présent dans la gestion interne des cookies du navigateur.

Un second cookie HttpOnly `__Host-dream_csrf` contient un secret aléatoire distinct.
Le formulaire contient seulement une preuve HMAC de ce secret liée à la session
actuelle (ou au pré-login), jamais le jeton d'authentification. Cette preuve CSRF
est visible dans le DOM ; elle n'est pas un secret permettant de se connecter.
Chaque POST web exige cette preuve et une origine exacte ; les contextes
Fetch Metadata interorigines sont refusés. Les cookies/prouves sont renouvelés
à la connexion, l'ancienne session du navigateur est révoquée, puis les cookies
sont effacés à la déconnexion. Les formulaires d'autres onglets peuvent devoir
être rechargés après une rotation. Une requête CSRF refusée retourne 403 JSON.

L'échappement Jinja2 reste actif. Une CSP autorise uniquement les ressources de
même origine, interdit les scripts inline et l'intégration dans une iframe.
Les réponses privées ne sont pas mises en cache. Les logs d'accès sont désactivés
dans la commande documentée. Les limites de tentatives P03 s'appliquent aussi aux
formulaires web. Le formulaire ne réaffiche jamais un mot de passe soumis.

À l'expiration, l'accès serveur est refusé et le navigateur revient à la connexion.
Un minuteur et un contrôle périodique/au retour dans l'onglet accompagnent cette
expiration dans l'interface ; aucun jeton n'est transmis au JavaScript.

### Tests reproductibles

Les tests pytest habituels utilisent `TEST_DATABASE_URL` vers une base dédiée ;
sans cette configuration les tests PostgreSQL sont explicitement ignorés.
`WEB_TEST_URL` permet de tester un serveur HTTPS de test avec Chrome/Edge installé.
Ne pas pointer ces variables vers un environnement contenant de vraies données.

Une recette autonome Windows est fournie pour PostgreSQL 17 natif déjà installé :

```powershell
.\.venv\Scripts\python.exe scripts\verify_p20.py
# Si nécessaire, avant la commande :
# $env:P20_POSTGRES_BIN = 'C:\chemin\PostgreSQL\17\bin'
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m pip check
```

Cette recette crée une instance PostgreSQL temporaire, applique Alembic, démarre
Uvicorn HTTPS sur un port libre, exécute les tests P01/P02/P03/P20 puis arrête les
services et supprime les données temporaires. Elle ne modifie aucune instance
existante et masque les identifiants PostgreSQL. Chrome/Edge est lancé avec un
profil temporaire ; aucun navigateur n'est téléchargé. Les captures de contrôle
sont écrites dans `tmp/p20-screenshots`, ignoré par Git. Les tests navigateur
acceptent uniquement dans leur contexte de test le certificat HTTPS temporaire
non approuvé ; cela ne vérifie pas la confiance du certificat sur le poste.

### Validation P20 du 10 novembre 2026

Compilation Tailwind locale réussie (CLI 4.3.0), CSS minifié livré sans CDN.
La recette finale a exécuté **85 tests : 85 réussites, aucun ignoré**, en 36,53 s :
69 tests précédents, 15 tests web, un parcours navigateur multiétape dans Chrome
réel en mode headless. PostgreSQL 17 natif et Uvicorn HTTPS ont été démarrés pour
les essais puis arrêtés ; aucune base existante n'a été modifiée.
Couverture du code Python `backend.app` instrumenté par pytest : **98,68 %**
(524/531 instructions). Ce taux ne mesure ni le CSS ni le JavaScript, ni les
instructions exécutées dans le processus Uvicorn séparé ; leur comportement est
contrôlé par le test navigateur.

Contrôles effectués : inscription/connexion PostgreSQL, page privée inaccessible
sans session, rotation/révocation/expiration, compatibilité Bearer, attributs des
cookies, CSRF absent/invalide/interorigine, navigation mobile, absence de
débordement horizontal à 1440 et 390 px, absence de ressources externes et d'erreurs
JavaScript dans la recette. Les captures desktop/mobile ont été inspectées.
Ruff, `pip check` et `git diff --check` réussissent. L'avertissement de dépréciation
Starlette/httpx connu reste présent.

Un premier essai navigateur a révélé que `Referrer-Policy: no-referrer` faisait
envoyer `Origin: null` pour les formulaires. La politique a été corrigée en
`same-origin`, sans relâcher la vérification CSRF. La recette finale passe après
correction. L'installation npm a également nécessité l'autorité publique déjà
approuvée par Windows ; la vérification TLS est restée active.

Non vérifiés : Firefox/Safari, matériel mobile réel, confiance du certificat
local dans Windows et livraison Docker complète (P15). Les critères appliqués
à P20 sont ceux fournis dans la demande ; aucun accès Jira ni changement Jira
n'a été effectué.
