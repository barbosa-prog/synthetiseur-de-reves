# Synthétiseur de rêves

Production pédagogique locale en Python 3.12. Ce dépôt contient actuellement
**P01 : le socle FastAPI**, **P02 : PostgreSQL**, **P03 : authentification et
isolation des rêves**, **P20 : interface web Jinja2/Tailwind** et **P19 : stockage
privé local**, **P04 : capture et import audio**. Worker et modèles IA ne sont
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

## P19 — Stockage privé local des médias

### Configuration Windows

Par défaut, le dossier utilisé est
`%LOCALAPPDATA%\SynthetiseurDeReves\private_media`, hors OneDrive et hors dépôt.
Il n'est créé que lors d'une première écriture autorisée, jamais au simple
démarrage de l'API. Pour personnaliser le dossier, éditer la variable facultative
`PRIVATE_MEDIA_ROOT` du `.env` privé avec un chemin absolu dédié.
Le `.env` existant n'est pas modifié automatiquement. Ne pas recopier le modèle
sur un `.env` déjà configuré.

Le service refuse un chemin relatif, une racine de disque, un partage UNC, le
dépôt (donc aussi `static/`), OneDrive et les liens symboliques/jonctions dans le
chemin. Un dossier existant non vide n'est pas adopté automatiquement : le service
initialise uniquement un dossier vide ou neuf avec le marqueur `.private-store-v1/`.
Ne pas créer ce marqueur manuellement dans un dossier contenant d'autres données.
Les fichiers sont plats : une clé hexadécimale aléatoire de 256 bits sans extension,
sans nom utilisateur, e-mail ou nom de fichier original. Aucun répertoire privé
n'est monté par FastAPI comme dossier statique.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

Lancer le backend avec la commande HTTPS P20. Pour tester un autre dossier dans
le terminal courant, sans modifier `.env` :

```powershell
$env:PRIVATE_MEDIA_ROOT = Join-Path $env:LOCALAPPDATA 'SynthetiseurDeReves\private_media'
```

Le dossier doit être sur un système de fichiers local supportant les liens durs
atomiques (NTFS sur Windows). Les permissions Windows sont héritées du profil
utilisateur : vérifier et restreindre ses ACL avant toute donnée réelle. Sous
POSIX, les nouveaux dossiers/fichiers sont demandés en modes 0700/0600.
Le service protège les accès HTTP ; il ne protège pas contre un administrateur
du poste, un compte de service compromis, une sauvegarde externe ou un déplacement
concurrent de dossiers par un programme privilégié. Il ne chiffre pas lui-même
les fichiers : chiffrement du disque et politique de sauvegarde restent à vérifier.

### Interfaces internes et formats

`PrivateStorage` définit `write/open/delete/inventory` ; `LocalPrivateStorage`
implémente ce contrat sans dépendre de FastAPI ou SQLAlchemy. `MediaService`
coordonne stockage et PostgreSQL via `store`, `download`, `request_purge` et
`reconcile`. Ces fonctions sont destinées aux futurs tickets ; aucun formulaire
d'import, endpoint d'écriture, moteur IA ou export complet n'est ajouté.

`store(user_id, dream_id, source, kind=..., media_format=...)` vérifie l'appartenance
du rêve avant toute écriture. Le nom de fichier original est facultatif, validé
puis oublié ; il n'est jamais utilisé pour construire un chemin ni conservé en
base. Les chemins, noms Windows réservés, flux alternatifs, extensions incohérentes
et caractères dangereux sont refusés. La clé est toujours générée par le service.

Formats acceptés : WAV PCM et MP3 pour audio (**15 Mio maximum**), PNG/JPEG/WebP
non animés pour image (**8 Mio maximum**, 16 millions de pixels). SVG et formats
actifs sont refusés. Pillow vérifie et décode les images, `wave` valide les données
PCM, Mutagen vérifie la structure MPEG Layer III du MP3. Cette dernière vérification
ne remplace pas un décodage audio intégral ni une analyse antivirus : P04 devra
compléter la validation d'import. Les limites sont contrôlées pendant la lecture
du flux, indépendamment d'une taille annoncée. Le contenu est validé avant écriture.

Le fichier est écrit en staging privé, synchronisé avec `fsync`, puis publié par
lien dur atomique sans écrasement. Aucun fichier final partiellement écrit n'est
présenté à un lecteur. Le staging est retiré après publication. La lecture ouvre
un descripteur, refuse les liens/reparse points et les liens durs externes, puis
contrôle taille et SHA-256 avant de diffuser les octets. Les fichiers normaux
doivent être modifiés uniquement via le service.

### Routes de consultation

| Route GET | Protection |
| --- | --- |
| `/api/v1/media/{uuid}/content` | Session Bearer P03 |
| `/web/media/{uuid}/content` | Cookie HttpOnly, origine HTTPS P20 ; session absente/expirée redirigée vers connexion |

Chaque lecture vérifie `media → dream → user`, le rêve non supprimé, l'état prêt
et l'expiration du média. UUID inconnu, média étranger, legacy, expiré, purgé,
fichier manquant ou altéré : même réponse 404. Le transport cookie n'est pas ajouté
aux routes API Bearer. Les routes web sont en GET sans mutation : aucun changement
des règles CSRF des formulaires P20. Pas de route publique de suppression.

La réponse contient les octets et un nom généré à partir de l'UUID, jamais le nom
original, la clé opaque ou un chemin absolu. En-têtes : `Cache-Control: no-store`,
`Content-Disposition: attachment`, `nosniff` et CSP restrictive. Aucun jeton dans
les URL. Aucun contenu média ou chemin privé journalisé. Les accès Uvicorn restent
désactivés dans la commande documentée. La diffusion est séquentielle ; les requêtes
Range et l'intégration de lecture audio dans l'interface ne sont pas implémentées.
Un téléchargement déjà autorisé et ouvert peut finir après une demande de purge.

### Migration 0003 et données existantes

`0003_private_media.py` ajoute taille, MIME, SHA-256, état de stockage et dates de
création/demande de purge/purge. Clés étrangères et anciennes références sont
conservées ; aucune migration précédente n'est modifiée, aucun fichier n'est
déplacé ou supprimé. Les anciennes lignes restent `legacy` avec taille/format/
empreinte NULL : on ne prétend pas connaître un fichier non vérifié. Leur date
`created_at` correspond à la migration, pas à une date originale inventée.
Elles ne sont pas servies par les nouvelles routes. Une éventuelle reprise de
ces références exige une opération distincte explicitement autorisée.

Les nouveaux médias sont `ready`. Une demande interne explicite de purge marque
`deleting` et valide cet état avant d'effacer le fichier ; il devient immédiatement
inaccessible aux nouvelles consultations. Après effacement, la ligne reste comme
trace `purged`. Une purge échouée reste `deleting` et peut être reprise ; elle
n'est pas présentée comme réussie. Ce n'est pas encore la suppression utilisateur
complète P10.

PostgreSQL et le disque ne forment pas une transaction distribuée. Une erreur DB
confirmée déclenche une compensation si le fichier n'est pas référencé. En cas
d'accusé de commit perdu ou de DB indisponible, le service conserve le fichier
potentiellement référencé pour éviter une perte de données. Un arrêt brutal peut
laisser un staging ou un fichier orphelin ; la réconciliation le détecte. Les
écritures et nettoyages partagent des verrous transactionnels PostgreSQL par clé.

### Maintenance sans suppression par défaut

```powershell
# Inventaire : compteurs seulement, aucun chemin ni clé affiché
.\.venv\Scripts\python.exe scripts\media_maintenance.py
# À exécuter seulement après examen des compteurs :
.\.venv\Scripts\python.exe scripts\media_maintenance.py --apply
```

Le mode simulation ne modifie ni fichiers ni métadonnées. `--apply` reprend les
purges déjà demandées et retire les objets internes sans référence, âgés de plus
de **24 heures**. Les objets récents, référencés, legacy, noms inconnus et liens
ne sont pas effacés. Les fichiers référencés manquants sont comptés, jamais
remplacés ou supprimés de la base automatiquement. Aucun nettoyage n'est lancé
automatiquement au démarrage ni exécuté sur les données existantes pendant P19.
Ne pas lancer des manipulations manuelles concurrentes dans ce dossier.

### Tests Windows

```powershell
# Recette isolée : PostgreSQL natif temporaire, tous les tests et Chrome installé
.\.venv\Scripts\python.exe scripts\verify_p20.py
# Ou avec TEST_DATABASE_URL dédié déjà configuré :
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m pip check
```

Le nom historique du script `verify_p20.py` est conservé ; il lance désormais la
suite complète, incluant P19. Ses fichiers et médias de test sont dans un dossier
temporaire hors dépôt/OneDrive, supprimé après la recette. Un `--basetemp` isolé
évite les conflits de permissions du dossier pytest global sur Windows. Sans
PostgreSQL/serveur HTTPS configurés, les tests concernés restent explicitement
ignorés dans une exécution pytest simple, jamais déclarés validés.

### Validation P19

Sous Windows, Python 3.12.14 et PostgreSQL 17 natif temporaire : **143 tests
réussis, aucun ignoré**, en 63,70 s. Les 85 tests précédents restent verts ; P19
ajoute 39 tests de stockage et 19 tests d'intégration. Couverture instrumentée de
`backend.app` : **94,26 %** (887/941 instructions). Les migrations sont exécutées
et comparées aux modèles, mais ne sont pas incluses dans ce taux de couverture.

Vérifications réelles : fichiers PNG/JPEG/WebP/WAV fictifs, structure MP3 synthétique,
taille/type, noms dangereux, jonctions Windows, liens durs externes, écritures
atomiques et collisions, permissions par propriétaire Bearer/cookie, UUID inconnus,
fichiers manquants/altérés/expirés, purge et reprise, compensation DB, commit
réussi avec accusé perdu, inventaire sec et nettoyage des orphelins anciens.
La migration de références legacy a conservé les lignes et les clés originales.

Une recette HTTP supplémentaire a obtenu 200 pour un WAV fictif, puis 200 après
arrêt et redémarrage effectifs de **PostgreSQL et Uvicorn**, enfin 404 après purge.
Le parcours Chrome P20 reste validé. Les services et données temporaires ont été
arrêtés/supprimés ; aucun stockage privé existant n'a été nettoyé.
Ruff et `pip check` réussissent. L'avertissement Starlette/httpx connu subsiste.

Le premier essai global a rencontré des permissions incompatibles sur le dossier
pytest partagé ; la recette utilise désormais son propre répertoire temporaire.
Les essais n'ont pas validé un arrêt électrique brutal, une analyse antivirus,
un décodage MP3 intégral, les ACL du futur dossier utilisateur, un chiffrement
applicatif ou un déploiement Docker complet. Utiliser une racine privée distincte
pour chaque environnement/base ; ne pas mutualiser ce dossier entre plusieurs bases.

## P04 — Enregistrement et import audio privés

### Parcours disponible

Après connexion, ouvrir **https://localhost:8443/nouveau-reve**, également accessible
depuis l'accueil et la navigation. Deux modes :

- **Microphone** : démarrer, autoriser le micro, arrêter, écouter puis confirmer.
  MediaRecorder sélectionne un format pris en charge par le navigateur. Les pistes
  sont arrêtées après enregistrement et les URL Blob sont libérées. Rien n'est
  envoyé avant la confirmation explicite.
- **Import** : choisir un WAV ou MP3, écouter puis confirmer. Le navigateur contrôle
  extension, fichier vide et taille pour guider l'utilisateur ; le serveur effectue
  ses propres vérifications, indépendamment du type MIME déclaré.

Le succès ouvre `/reves/{uuid}/audio`, avec lecteur privé et durée mesurée. Cette
page concerne seulement l'audio de ce brouillon, sans historique complet. Aucun
texte, émotion, transcription réelle/factice, image ou job IA n'est créé. La
capture d'un autre rêve crée un nouveau brouillon ; aucun audio existant n'est
écrasé. Un utilisateur étranger reçoit 404 pour la confirmation et pour le média.

### Routes

| Route | Contrat |
| --- | --- |
| GET `/nouveau-reve` | Page connectée, cookie HttpOnly et HTTPS |
| POST `/web/audio` | Cookie P20, origine stricte et `X-CSRF-Token` |
| POST `/api/v1/dreams/audio` | Bearer P03, corps binaire ; schéma disponible dans OpenAPI |
| GET `/reves/{uuid}/audio` | Confirmation privée et lecteur du compte propriétaire |

Les deux POST reçoivent le **corps binaire brut**, pas un formulaire multipart.
En-têtes : `X-Audio-Format` obligatoire (`wav`, `mp3`, `webm`, `ogg`, `mp4`),
`X-Audio-Source` (`import` par défaut ou `microphone`), et facultativement
`X-Audio-Filename`, encodé en pourcentage avec `encodeURIComponent`.
Le nom est contrôlé puis oublié ; jamais utilisé comme chemin ni conservé en base.
`import` est limité à WAV/MP3. Le tag `microphone` indique une origine déclarée,
pas une preuve matérielle ; ses autres formats restent soumis au décodage réel.

Succès 201 : `dream_id`, `media_id`, durée, nombre d'échantillons, fréquence,
canaux, format/taille de la source et origine déclarée. Aucun chemin, nom original
ou clé de stockage. Les erreurs utilisent l'enveloppe JSON existante et des messages
publics : 400 transfert/nom invalide, 401 authentification, 403 CSRF, 408 interruption,
413 taille, 415 format/contenu, 422 vide/durée, 429 saturation et 503 indisponibilité.
Les cookies ne remplacent pas un Bearer sur les routes API. La preuve CSRF du DOM
est distincte du jeton d'authentification, qui reste inaccessible à JavaScript.

### Formats et conversion réellement implémentés

PyAV 19.0.2 fournit localement les bibliothèques FFmpeg, sans exécutable FFmpeg
à installer séparément et sans API externe. La source est décodée entièrement :
signature, conteneur imposé, piste audio unique, codec, fréquence, canaux et trames.
Les conteneurs avec vidéo/pistes supplémentaires sont refusés. Les playlists et
entrées URL ne sont pas acceptées. Les références externes des conteneurs sont
désactivées. Les erreurs du décodeur ne renvoient ni logs FFmpeg ni chemins.

| Entrée | Usage | Validation réalisée |
| --- | --- | --- |
| WAV PCM | Import | Contenu PCM, trames complètes, décodage |
| MP3 MPEG Layer III | Import | Décodage effectif, au-delà de la seule structure P19 |
| WebM Opus/Vorbis | MediaRecorder | Décodage ; Chrome Opus testé de bout en bout |
| Ogg Opus/Vorbis | MediaRecorder | Ogg Opus testé avec signal synthétique encodé localement |
| MP4 AAC/Opus | MediaRecorder | MP4 AAC testé avec signal synthétique encodé localement |

Tout audio accepté est **normalisé en WAV PCM 16 bits, mono, 16 kHz** avant stockage
P19. Seul ce WAV est conservé ; la source reçue et le résultat intermédiaire sont
effacés du dossier temporaire après traitement. Le lecteur web utilise la route
privée P19, désormais en `inline` pour l'audio web ; les téléchargements Bearer et
les images gardent leur disposition `attachment`. Les contrôles de propriétaire
et d'intégrité P19 restent actifs. Pas de gestion HTTP Range dans ce ticket.

### Limites et ressources

La limite du cadrage reste **15 Mio exactement, soit 15 728 640 octets** pour la
source reçue, contrôlée par Content-Length et par comptage effectif du flux même
si cet en-tête est absent. La limite vaut aussi pour le WAV final P19.
P04 ajoute un garde-fou explicite de **8 minutes**, mesuré sur les échantillons
décodés, pour borner le travail et produire un WAV 16 kHz dans cette enveloppe.
Le client arrête également le microphone à huit minutes. Le projet vise des récits
courts ; cette borne technique n'est pas présentée comme une durée issue du cadrage.

La réception écrit progressivement sur disque temporaire privé hors dépôt/OneDrive,
sans `request.body()` ni chargement multipart intégral. Le transfert est limité à
30 secondes, le décodage à 20 secondes dans un sous-processus sans shell. Au plus
deux réceptions/conversions sont actives par processus serveur ; le surplus reçoit
429. Le décodeur utilise un thread et la sortie est écrite par blocs. Le stockage
P19 utilise ensuite sa lecture bornée du WAV normalisé (maximum 15 Mio) ; la mémoire
native totale de FFmpeg n'est pas plafonnée par une limite RSS du système.

Authentification et CSRF sont vérifiés avant lecture des octets. Un upload invalide
ou interrompu pendant la réception ne crée aucun rêve/média. Après conversion,
le brouillon et ses métadonnées sont validés dans une **seule transaction**, avec
la publication/compensation P19. Une erreur après commit mais avant réception de
la réponse peut laisser un audio correctement enregistré : l'interface parle de
résultat non confirmé, sans promettre qu'aucun enregistrement n'a eu lieu. L'idempotence
des reprises et les quotas journaliers ne sont pas ajoutés dans P04.

Les messages couvrent refus de permission, micro absent/occupé, format invalide,
taille et interruption. La CSP autorise uniquement `media-src 'self' blob:` pour
la préécoute et la lecture privée ; scripts inline et `unsafe-eval` restent interdits.
La permission microphone est limitée à la même origine et la caméra est désactivée.
Le contenu audio n'est pas journalisé. JavaScript est nécessaire au parcours audio.

### Migration 0004

`0004_audio_capture.py` ajoute à `media` des champs nullables : durée mesurée,
fréquence, canaux, nombre d'échantillons, format/taille de la source et origine.
Les médias antérieurs sont conservés sans métadonnées supposées. Des contraintes
bornent les nouvelles mesures ; aucun changement des migrations 0001–0003, aucun
backfill audio ni migration destructive exécutée sur les données existantes.
Ces informations préparent P05 sans implémenter de transcription.

### Installation et démarrage Windows

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
Push-Location frontend
npm.cmd run build
Pop-Location
# Générer les certificats seulement s'ils n'existent pas déjà :
# .\.venv\Scripts\python.exe scripts\dev_https.py
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8443 --no-access-log --no-proxy-headers --ssl-keyfile tmp/https/key.pem --ssl-certfile tmp/https/cert.pem
```

Conserver la configuration PostgreSQL/stockage P19 et `WEB_ORIGIN` du `.env` privé.
Ouvrir l'origine HTTPS exacte, se connecter puis accéder à `/nouveau-reve`. Un
certificat local approuvé est préférable ; les certificats de développement P20
ne sont pas installés dans Windows et peuvent afficher un avertissement. La commande
ne démarre pas PostgreSQL : utiliser son instance locale ou Compose comme dans P02.

```powershell
# Recette complète PostgreSQL/HTTPS/Chrome temporaires
.\.venv\Scripts\python.exe scripts\verify_p20.py
# Diagnostic des seuls parcours navigateur (ce n'est pas la suite complète)
.\.venv\Scripts\python.exe scripts\verify_p20.py --browser-only
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m pip check
```

### Validation P04 du 11 novembre 2026

**180 tests réussis, aucun ignoré**, en 87,15 s avec Python 3.12.14 et PostgreSQL 17.
Les 143 tests précédents restent verts. P04 ajoute 18 tests de conversion/réception,
18 tests d'intégration et un parcours Chrome. Couverture du Python instrumenté
`backend.app` : **92,34 %** (1085/1175 instructions) ; les sous-processus de décodage,
le processus HTTP et le JavaScript ne sont pas inclus dans ce pourcentage.

Réellement exécutés : imports WAV/MP3 et décodage des cinq formats ci-dessus,
WAV exactement à 15 Mio, refus d'un WAV synthétique de 481 secondes, rejet des
contenus falsifiés/vides/trop grands, CSRF, absence d'authentification, noms malveillants,
isolation entre comptes, transaction brouillon/média et nettoyage après erreurs.
Après la suite, un audio importé par P04 a été relu en HTTP 200 après arrêt et
redémarrage effectifs de PostgreSQL et Uvicorn. Les services/données temporaires
ont ensuite été arrêtés/supprimés, sans toucher à une instance existante.

Chrome réel en mode headless : MediaRecorder, préécoute avant confirmation, sauvegarde,
lecture du WAV privé, import WAV/MP3, messages d'erreur, affichage desktop/mobile.
La source microphone est le **périphérique fictif fourni par Chrome**, pas un micro
matériel. Le refus de permission est réglé dans Chrome via DevTools, sans remplacer
getUserMedia. L'interruption d'upload ASGI et l'expiration du décodeur sont simulées
dans les tests ; un câble réseau débranché et un processus réellement bloqué n'ont
pas été testés. Captures inspectées dans `tmp/p04-screenshots`.

Les adaptations du test navigateur ont conservé la CSP stricte : assertions sans
`eval`, synchronisation sur la progression du lecteur et absence de relecture d'une
réponse après navigation. Ruff et `pip check` réussissent. L'avertissement connu
Starlette/httpx subsiste. Non vérifiés : microphone physique, sortie haut-parleur,
Firefox/Safari réels, antivirus et livraison Docker complète. Aucun service payant,
modèle IA, transcription, éditeur de texte, image ou classification ajouté.
