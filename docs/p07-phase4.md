# P07 — Phase 4 : interface utilisateur

## Parcours

Depuis le récit P06 enregistré : « Créer une image du rêve » ouvre
`/reves/{id}/image`. La description visuelle est indépendante du récit français,
limitée à 500 caractères, échappée par Jinja et enregistrée explicitement.
Aucune traduction automatique ; l'interface mentionne les limites du modèle
en français/anglais. Une description modifiée dans le formulaire doit d'abord
être enregistrée avant de générer. Aucune création automatique de job.

« Générer une image » enregistre une demande et rend immédiatement la page.
Le worker indépendant la traitera ; FastAPI ne charge aucun moteur IA.
Suivi par GET toutes les deux secondes, suspendu quand l'onglet est masqué,
sans pourcentage inventé ni relance automatique. En cas de panne de suivi ou
d'expiration, résultat masqué et demande de rechargement. Statuts affichés :
en attente, en cours, terminé, erreur, résultat dépassé.

La génération utilise la description enregistrée, la version du récit et celle
de la description. Des formulaires obsolètes reçoivent un conflit sans écraser
la nouvelle version. Une modification dans un autre onglet invalide le résultat
au prochain suivi et exige un rechargement ; la saisie locale n'est pas remplacée
par JavaScript. Les jobs actifs restent exclusifs au même rêve, même dépassés,
jusqu'à leur terminaison ou leur réconciliation par le worker.

## Routes

API Bearer P03, sans authentification implicite par cookie :

| Méthode | Route | Fonction |
| --- | --- | --- |
| GET | /api/v1/dreams/{id}/image-description | Description et versions |
| PUT | /api/v1/dreams/{id}/image-description | Enregistrer avec versions attendues |
| POST | /api/v1/dreams/{id}/images | Demande explicite, réponse 202 |
| GET | /api/v1/images/{job_id} | Statut privé et URL API du résultat courant |

Navigateur : cookie HttpOnly, origine stricte et preuve CSRF sur chaque POST :

| Méthode | Route | Fonction |
| --- | --- | --- |
| GET | /reves/{id}/image | Page responsive |
| POST | /reves/{id}/image/description | Enregistrer/reconfirmer la description |
| POST | /reves/{id}/image/generer | Demander la génération |
| GET | /reves/{id}/image/statut | Suivi par polling, aucune mutation |

La consultation utilise P19 : `/web/media/{id}/content` par cookie pour l'image
HTML, `/api/v1/media/{id}/content` par Bearer pour les clients API. Le propriétaire
est vérifié à chaque opération. Aucun chemin local, clé de stockage, jeton de
réservation ou récit n'est renvoyé dans le statut. Résultats courants déterminés
par les versions, pas simplement par la présence d'un média.

## Tests et recette Windows

Compilation locale, sans CDN ni nouvelle dépendance :

```powershell
Push-Location frontend
npm run build
Pop-Location
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe scripts/verify_p20.py
```

`verify_p20.py` utilise PostgreSQL/HTTPS temporaires et Chrome headless installé.
La nouvelle suite navigateur utilise exclusivement un moteur fictif qui produit
un aplat violet PNG : aucun résultat synthétique n'est présenté comme validation
d'une génération réelle dans cette phase. Elle couvre lien P06, enregistrement,
demande, suivi et consultation, erreur de délai, correction pendant génération,
affichage mobile sans débordement et absence d'erreurs JavaScript.

Les tests des routes couvrent validation serveur, accès anonymes/intercomptes,
CSRF et origine, HTML échappé, concurrence, version dépassée, conflit optimiste,
état en cours, erreurs moteur et image privée. La campagne globale couvre aussi
P01/P02/P03/P04/P05/P06/P19/P20. Le test de schéma historique a été mis à jour
pour attendre 0007 et ses deux tables ; les autres vérifications de cohérence,
FK, aller-retour et comparaison ORM/migrations sont conservées.

Captures synthétiques : `tmp/p07-screenshots/image-fictive-desktop.png` et
`image-fictive-mobile.png`, inspectées visuellement. Résultats chiffrés de la
campagne finale consignés dans le rapport de livraison de cette phase.

Campagne finale exécutée : **338 tests réussis, aucun ignoré, 210,35 s**,
couverture backend **89,12 %**, routes P07 **96 %**. Ruff, node --check,
compilation Tailwind locale et git diff --check réussis. La recette a ensuite
confirmé la relecture audio P04 et média privé P19 après redémarrage effectif
de PostgreSQL/Uvicorn, puis arrêté les serveurs temporaires.
Première campagne : 334 succès et un échec d'attente historique du schéma 0006 ;
test aligné sur 0007 puis campagne complète relancée et réussie.
Les restrictions de lecture Windows ont nécessité l'exécution hors sandbox
de Node pour compilation/vérification ; aucune installation effectuée.

## Tester manuellement dans Chrome après validation

La base personnelle est toujours sans migration 0007 appliquée par l'assistant.
Ne pas lancer de génération réelle ou migrer cette base avant accord explicite.
La recette automatisée ci-dessus permet de tester le parcours avec données
temporaires et faux moteur dès maintenant, puis arrête ses serveurs.

Après accord pour l'environnement choisi : appliquer sa migration, démarrer
le serveur HTTPS habituel, se connecter dans Chrome, importer un audio P04,
transcrire si souhaité P05, enregistrer/corriger P06 puis ouvrir « Créer une
image du rêve ». Enregistrer une description et demander la génération.
Le démarrage du worker GPU réel et tout clic de génération sur cet environnement
resteront soumis à l'autorisation utilisateur. Le bouton seul crée un job,
pas un calcul dans FastAPI. Aucun worker GPU démarré pendant cette phase.

Aucune nouvelle migration, modification des dépendances P05, installation,
téléchargement, commit, push ou modification Jira.
