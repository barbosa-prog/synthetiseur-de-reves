# Synthétiseur de rêves

Production pédagogique locale en Python 3.12. Ce dépôt contient actuellement
**P01 : le socle FastAPI**, sans PostgreSQL, authentification, stockage de médias,
worker ou modèle IA. Aucun service payant n'est nécessaire.

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
Ces fonctions ne sont pas implémentées dans P01.

Git existant conservé. Aucun commit, push ou changement Jira sans accord préalable.
