# P11 — Phase 4 : relances publiques et suivi non bloquant

## Périmètre

Reprise des fichiers locaux de phases 1 à 3 et du travail de phase 4 interrompu, sans
réinitialisation. Les budgets, réservations et récupérations restent dans les services
P11 existants. Aucune migration supplémentaire, aucune migration personnelle, aucun
worker/modèle réel, aucun fournisseur distant, aucune installation ni opération Git
d'ajout/commit/push. Les tests utilisent des comptes, rêves et médias fictifs.

## Routes et confirmation

API Bearer, réponses 202 en cas d'acceptation :

| Route POST | Action |
| --- | --- |
| `/api/v1/transcriptions/{job_id}/retry` | Relance STT |
| `/api/v1/images/{job_id}/retry` | Relance image |
| `/api/v1/emotion-jobs/{job_id}/retry` | Relance émotion |
| `/api/v1/images/{job_id}/regenerate` | Nouvelle image volontaire, même budget |

Corps JSON strict, sans configuration moteur ni propriétaire fournis par le client :

```json
{
  "confirmed": true,
  "expected_text_version": 1,
  "expected_retry_count": 0,
  "expected_description_version": 1
}
```

`expected_description_version` est nécessaire pour l'image ; pour l'émotion, fournir
`expected_choice_revision` à sa place. Pour STT, seuls les trois premiers champs sont
nécessaires. Les valeurs attendues proviennent du dernier objet `tracking`. Une valeur
booléenne réelle est obligatoire, pas une chaîne ni un entier. `confirmed=false` ne
permet aucune action. Champs supplémentaires refusés.

Web session/CSRF, uniquement POST :

- `/reves/{dream_id}/traitements/{kind}/{job_id}/relancer`, kind stt/image/emotion ;
- `/reves/{dream_id}/traitements/image/{job_id}/regenerer`.

Le formulaire comporte exactement `csrf`, `expected` et `confirmed`. `expected` est
la représentation non secrète `version_récit:version_description:révision_choix:relances`.
Ce n'est ni un jeton de session ni un remplacement du CSRF. La case required vaut
`confirmed=yes` ; son absence ou sa valeur négative interdit l'action côté serveur.
Chaque changement de job, compteur ou état remet la case à décoché dans le navigateur.
Une réussite renvoie 303 vers la page existante. Une action devenue incompatible
affiche une erreur 409 dans cette page, sans détails techniques.
La régénération conserve les paramètres du job, dont la seed ; le rendu peut donc
être identique. Elle ne promet ni diversité automatique ni traduction du récit.

Le serveur vérifie le type du job, le propriétaire et le rêve non supprimé avant
ses verrous. Il réutilise `lock_job`, les projections de règles, puis `retry_job` ou
`create(new_image=True)` dans la même session transactionnelle. Versions et compteur
de relance attendu sont contrôlés sous verrou : deux requêtes concurrentes ou une
ancienne confirmation ne peuvent consommer deux relances. Les erreurs de contention
restent bornées et génériques. Les GET de ces URL ne peuvent agir (405).

Les réponses existantes STT pending/processing/completed et les statuts métier P07/P08
restent présents. Les nouveaux champs sont additifs dans `tracking`.

## Projection commune

La sélection est autorisée par le propriétaire ; la projection ne lance ni maintenance,
réservation ni fournisseur. Elle expose :

- `technical_state` : queued, running, done ou failed ; `state_label` et `state_message` sûrs ;
- `cycle_attempts`, `max_attempts=3`, `retry_count`, `max_manual_retries=2` ;
- `attempts_remaining`, `retries_remaining`, `budget_known`, `retryable`, `regeneratable` ;
- `outdated` et `outcome` (result/abstention) séparés de l'état technique ;
- versions actuelles, UUID métier du job et URL web autorisées pour préparer les formulaires.

`retries_remaining` est borné par les deux plafonds restants : des générations
volontaires peuvent épuiser les exécutions même sans consommer les relances manuelles.
Le champ historique racine `attempts` reste un compteur de ligne ; `cycle_attempts`
agrège les lignes du cycle. Aucun pourcentage ou avancement fictif n'est affiché.
Un succès ou une abstention ne devient pas un échec pour autoriser une relance.

La correction de péremption vérifie aussi les métadonnées image avant d'appeler le
constructeur d'entrées : propriétaire du snapshot, récit/version, texte/version de
description et leur association. Si la description n'est plus liée au récit courant,
le refus de construction d'entrées ne laisse plus `outdated=false` par défaut.
Le sélecteur d'image actuelle compare également les textes du snapshot au récit et
à la description courants. Une incohérence est masquée dès le rendu HTML, sans attendre
un premier polling et sans transformer l'état technique done en failed.
Une sortie STT dont la version a été incrémentée reste actuelle si son empreinte de
sortie correspond encore au récit. Les codes d'erreur historiques inconnus sont
réduits à `unknown_error` dans les projections publiques STT/émotion ; aucun détail
fournisseur, clé de stockage, chemin, instantané privé ou token de réservation n'est exposé.

Pour l'historique sans identité fiable : budget inconnu, aucune relance autorisée.
Pour P08 désactivé : pas de relance IA ; le choix manuel reste disponible. Le travail
de reprise des historiques signalé en phase 3 n'est pas remplacé par une migration
automatique dans cette phase.

## Interface et suivi

Un composant Jinja commun affiche état, budgets et confirmations sur les trois écrans.
Le bouton Relancer le traitement n'est visible que si `retryable=true`. Une génération
volontaire dispose de son propre formulaire et de sa propre confirmation. Les actions
sur une description éditée mais non enregistrée restent désactivées.

`job-polling.js` fournit une seule mécanique aux trois scripts :

- uniquement GET, credentials same-origin, no-store, Accept application/json ;
- AbortController : délai maximal de lecture **8 s**, aucune requête de suivi chevauchante ;
- suivi actif environ toutes les **2 s**, pause des lectures quand l'onglet est caché ;
- panne temporaire : bannière « Suivi momentanément indisponible », état technique
  conservé, reprise des lectures avec délais 2/4/8/15 s ; aucune mutation automatique ;
- 401/403/404 : arrêt et invitation à recharger/se reconnecter ; la session expirée
  retourne 401 JSON pour ces lectures, tandis que la navigation HTML conserve son 303 ;
- done/failed : arrêt de la boucle périodique ; retour sur l'onglet, reconnexion ou
  restauration du cache de navigation : contrôle ponctuel en lecture ;
- page quittée : annulation de la requête et du timer ; rechargement : identifiant et
  états restaurés par PostgreSQL, aucun job créé.

Une panne réseau n'est pas présentée comme un échec IA. L'image est masquée tant que
son état ne peut pas être revérifié. Les choix manuels P08 ne sont pas désactivés par
une simple panne de suivi. Une modification de versions dans une autre page impose
un rechargement ; le serveur refuserait de toute façon une ancienne confirmation.

Le détail P09 affiche un résumé des derniers états par type **au chargement**, avec
liens vers les écrans de suivi. Ni Dream.status ni les filtres d'émotion ne sont modifiés.
La suppression/purge P10 garde ses refus immédiats : aucun lien ne réactive un rêve.

## Commandes de vérification Windows

Depuis la racine, avec les dépendances déjà installées :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --tracking-only
.\.venv\Scripts\python.exe scripts/verify_p20.py --p11-browser --emotion-web-test
.\.venv\Scripts\python.exe scripts/verify_p20.py --emotion-web-test
.\.venv\Scripts\python.exe -m ruff check backend scripts
git diff --check
```

Les lanceurs créent leurs propres clusters, bases, utilisateurs et stockages temporaires.
`--emotion-web-test` active uniquement la disponibilité de l'interface **dans ce serveur
temporaire** ; aucun worker ni modèle réel n'est lancé. Le test Chrome P11 vérifie avant
accès que DATABASE_URL=TEST_DATABASE_URL, base p20_validation, rôle p20_*, hôte 127.0.0.1,
port différent de 5434. Ne pas exécuter de test sur dreams_local.

Les captures fictives vont dans `tmp/p11-screenshots/` (ignoré par Git). Elles couvrent
STT/image/émotion, ordinateur et 390 px. La compilation Tailwind de contrôle utilise
un fichier temporaire et ne réécrit pas le CSS préexistant.

## Fichiers de phase 4

Créés :

- `backend/app/job_routes.py`
- `backend/app/services/job_tracking.py`
- `backend/app/web/static/js/job-polling.js`
- `backend/app/web/templates/_job_controls.html`
- `backend/tests/test_job_routes_p11.py`
- `backend/tests/test_job_tracking_browser.py`
- `docs/p11-phase4.md`

Modifiés :

- `backend/app/main.py`, `stt_routes.py`, `image_routes.py`, `emotion_web.py`, `history_routes.py`
- `backend/app/services/stt_jobs.py`, `emotions.py`
- `backend/app/services/image_execution.py` (garde de cohérence de l'image actuelle)
- `backend/app/web/routes.py`
- `backend/app/web/static/js/stt.js`, `image.js`, `emotion.js`
- `backend/app/web/templates/transcription.html`, `image.html`, `emotion.html`, `dream_detail.html`
- `backend/tests/test_emotion_browser.py`
- `scripts/verify_image_jobs.py`, `scripts/verify_p20.py`

Les fichiers des phases antérieures sont conservés. `frontend/styles/app.css` reste
hors périmètre, avec son empreinte préexistante
`d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.

## Résultats mesurés et limites

Campagne ciblée initiale de reprise : 95 réussis, puis 99 et **101 réussis en 71,37 s**
après ajout des contrôles de péremption, confidentialité et désactivation du moteur.
Première recette Chrome P11 : **3 réussis en 58,42 s**, incluant le délai réseau, la
coupure, le rechargement, les quatre états et une relance confirmée sur chaque type.
La seconde recette vérifie en plus le cache de navigation et la régénération volontaire.
La dernière campagne ciblée a donné **103 réussis en 70,03 s**. La recette Chrome finale
a donné **3 réussis en 59,54 s**, avec les confirmations et la régénération effectuées
à 390 px, puis vérification du rendu ordinateur. Les captures mobiles ont également
été inspectées visuellement.
Une première campagne complète a donné **732 réussis, 1 ignoré en 454,97 s**,
couverture **89,02 %** ; la consolidation complète après les derniers contrôles est
terminée : **734 réussis, 1 ignoré en 452,38 s**, couverture backend **89,47 %**.
Les **29 nouveaux cas phase 4** (26 routes/services et 3 parcours Chrome) sont inclus.
Couverture du service de projection/actions : **96 %** ; routes P11 : **93 %**.
Le test ignoré est l'inférence réelle mDeBERTa opt-in, volontairement non exécutée.
Aucun avertissement n'a été remonté dans cette campagne finale.
Les corrections comprennent aussi le maintien d'une nouvelle demande STT
légitime après correction du récit, sans autoriser la relance de l'ancien job périmé.

La campagne complète inclut P01 à P10, P19 et P20. Le lanceur a également confirmé
la persistance P09/P04 après un vrai redémarrage PostgreSQL/Uvicorn temporaires,
puis la lecture P19 refusée après purge du média fictif. Les serveurs temporaires
ont été arrêtés et leurs ressources nettoyées.

Ruff backend/scripts, compilation Python ciblée, syntaxe des **8 fichiers JavaScript**,
compilation locale Tailwind 4.3.0 et `git diff --check` : réussis. La sortie Tailwind
de contrôle est temporaire ; le CSS source préexistant et le CSS livré ne sont pas
réécrits. Le contrôle des 50 fichiers modifiés/non suivis présents (phases antérieures
comprises) ne détecte aucun modèle, environnement virtuel, archive, média privé ou
secret selon les extensions/noms et motifs examinés. `.env`, `.venv`, `.coverage` et
les captures `tmp/p11-screenshots/` sont ignorés par Git. Aucun git add n'a été fait.

Les tests existants du scénario émotion activé utilisent désormais de vrais changements
de récits fictifs entre suggestions, conformément à la déduplication validée en phase 3.
Ils ne fabriquent pas une relance par répétition d'une demande réussie.

Limites : pas de progression fine ni push serveur ; une page terminale ne détecte pas
instantanément une modification externe sans retour sur l'onglet ou rechargement.
La maintenance doit fonctionner pour récupérer les jobs expirés lorsque les workers
sont arrêtés. Révoquer un job empêche sa publication sans garantir l'arrêt immédiat
d'un calcul externe déjà commencé. Aucune nouvelle qualification matérielle ou inférence
réelle n'est revendiquée. Le déploiement personnel requiert toujours une autorisation
distincte, la migration 0009 et la mise à jour de tous les consommateurs.
