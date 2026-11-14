# P16 / SCRUM-20 — Parcours complet de démonstration

Recette du **14 novembre 2026**, sur l'architecture existante
**FastAPI + Jinja2 + PostgreSQL**. Le travail commencé dans
`p16_demo_recipe.py` et `verify_p20.py`
a été conservé et terminé. Aucune modification Jira ni création de commit.

## Scénario pour la soutenance

Annoncer avant les captures : **« L'interface, le stockage, les jobs et la base
fonctionnent réellement ; les fournisseurs IA sont simulés. L'audio est un signal
synthétique Chrome, sans voix humaine. »**

| Étape | Action dans la même session Chrome | Résultat vérifié |
| --- | --- | --- |
| 1. Audio | Créer un compte fictif, ouvrir « Capturer un rêve », enregistrer environ deux secondes avec le faux périphérique Chrome, écouter puis confirmer | Vrai MediaRecorder ; aucun envoi avant confirmation ; réponse 201 ; WAV mono 16 kHz stocké, lisible et lié à un seul rêve |
| 2. Transcription | Cliquer « Lancer la transcription locale » | Job PostgreSQL réel ; `FakeProvider` invoqué une fois ; texte prédéfini enregistré en version 1 et affiché dans l'éditeur |
| 3. Correction | Compléter le récit puis cliquer « Enregistrer le récit » | Version 2 relue après rechargement ; audio d'origine inchangé octet pour octet |
| 4. Image | Enregistrer une description visuelle puis demander la génération | Job réel ; `FakeEngine` invoqué une fois ; PNG violet 512 × 512 publié par le service existant et affiché dans Chrome |
| 5. Émotion | Demander une suggestion, attendre « Analyse en cours… », puis accepter « Heureux » | Suggestion simulée liée à la version 2 ; aucune émotion retenue avant acceptation ; provenance « Suggestion acceptée » ensuite |
| 6. Historique | Filtrer sur « Heureux », recharger, ouvrir le rêve | Même UUID et même propriétaire ; récit corrigé, image et audio relus ; trois jobs terminés avec une tentative chacun |
| 7. Suppression | Ouvrir la confirmation, cocher la case, supprimer, puis appliquer la maintenance ciblée | Retrait immédiat et HTTP 404 ; fichiers d'abord marqués `deleting`, puis suppression physique et SQL par la purge P10 ; seconde purge idempotente |

Texte de transcription **simulé**, sans reconnaissance vocale :

> Récit fictif : je marche sous une lune bleue.

Correction effectuée via le formulaire réel :

> Récit fictif de démonstration : je marche dans une forêt lumineuse, sous une lune bleue. Je me sens heureux et apaisé.

Description saisie : `A fictional luminous forest under a blue moon, peaceful atmosphere`.
Le PNG violet ne représente pas cette scène : il est volontairement un résultat
de test déterministe. Les libellés habituels « générée par IA » de l'interface
ne doivent pas être présentés comme une preuve d'inférence pendant cette recette.

Pour une soutenance, présenter les captures dans l'ordre 01 à 08, puis le
rapport JSON pour expliquer les contrôles SQL et fichiers non visibles à l'écran.
La commande ci-dessous rejoue automatiquement le parcours en Chrome headless ;
ce n'est pas un serveur interactif avec faux workers disponible après son arrêt.

## Reproduire sans données personnelles

Prérequis P15 : Windows x86-64, Python 3.12, dépendances du verrou
`requirements-windows-py312.lock`, binaires PostgreSQL 17 et Chrome installé à
`C:\Program Files\Google\Chrome\Application\chrome.exe`. Recette réalisée ici
avec Python **3.12.14** et PostgreSQL **17.5**. Aucun navigateur ni modèle n'est
téléchargé par le lanceur. Utiliser le venv déjà préparé selon le README.

Depuis la racine du dépôt, dans PowerShell :

```powershell
# Facultatif si les binaires PostgreSQL sont ailleurs :
# $env:P20_POSTGRES_BIN = 'C:\chemin\PostgreSQL\17\bin'
.\.venv\Scripts\python.exe scripts\verify_p20.py --p16-demo
```

Ne pas exécuter le fichier pytest directement contre une base configurée à la
main. Le lanceur crée son cluster, rôle/mot de passe aléatoires, base
`p20_validation`, ports libres et certificat éphémère. La cible PostgreSQL doit
passer les protections P14 : autorisation temporaire et identité réelle du
serveur vérifiée avant migration. Le `.env` personnel est neutralisé, jamais lu
ni écrasé. Les médias et exports restent dans le répertoire jetable, hors dépôt
et OneDrive. Aucun service existant n'est arrêté.

`--p16-demo` active uniquement la disponibilité émotionnelle **de recette**
autorisée P14 ; aucun worker réel n'est démarré. Les trois faux fournisseurs sont
injectés depuis les tests. Les protections qui interdisent modèles réels et
réseau externe dans les tests ordinaires restent actives.

Pour retrouver les nouvelles preuves locales :

```powershell
Get-ChildItem -LiteralPath docs/evidence/p16 -Filter result.json -Recurse
```

Chaque exécution écrit dans un nouveau `run-<identifiant aléatoire>` sans écraser
une preuve existante. Un dossier sans `result.json` avec `result: passed` ne
constitue pas une recette validée : il peut provenir d'une tentative interrompue.
Le lanceur arrête PostgreSQL/Uvicorn et supprime leurs ressources temporaires
après le test. Les PNG et le rapport de preuve restent disponibles.

## Preuves disponibles

Exécution de référence : [rapport JSON](evidence/p16/run-3c8bd9705471/result.json),
daté du **14 novembre 2026 à 08:28:12, heure de Paris**. Les huit PNG ont été
inspectés visuellement : pages lisibles, récit fictif uniquement, aucun mot de
passe, cookie, jeton, chemin privé ou URL PostgreSQL affiché. Il n'y a ni trace
Playwright, ni HAR, ni enregistrement du DOM, ni capture de l'écran de connexion.

| Preuve | Ce qu'elle montre |
| --- | --- |
| [01 — Audio fictif](evidence/p16/run-3c8bd9705471/01-audio-fictif.png) | Audio synthétique enregistré, durée mesurée, lecteur et format WAV |
| [02 — Transcription simulée](evidence/p16/run-3c8bd9705471/02-transcription-simulee.png) | Texte prédéfini affiché en version 1 |
| [03 — Récit corrigé](evidence/p16/run-3c8bd9705471/03-recit-corrige.png) | Correction sauvegardée en version 2 |
| [04 — Image simulée](evidence/p16/run-3c8bd9705471/04-image-simulee.png) | Job terminé et PNG violet de test, sans modèle génératif |
| [05 — Émotion acceptée](evidence/p16/run-3c8bd9705471/05-emotion-acceptee.png) | Récit version 2, valeur « Heureux » et acceptation explicite |
| [06 — Historique](evidence/p16/run-3c8bd9705471/06-historique.png) | Même récit retrouvé avec le filtre émotionnel |
| [07 — Confirmation](evidence/p16/run-3c8bd9705471/07-suppression-confirmation.png) | Confirmation et distinction retrait d'accès / effacement physique |
| [08 — Après purge](evidence/p16/run-3c8bd9705471/08-historique-apres-purge.png) | Historique vide ; l'effacement SQL et disque est prouvé par les assertions et le rapport |

Le rapport contient une liste blanche de résultats, les dimensions des images
et leurs SHA-256, sans identifiant de compte/rêve/job, email, cookie, secret,
configuration SQL ou contenu d'environnement. Aucune vidéo n'est nécessaire
aux critères : les huit captures couvrent les étapes essentielles.

## Continuité et suppression réellement vérifiées

Le test garde **une seule page, un seul contexte Chrome et le même cookie de
session** jusqu'à la fin. Le rêve n'est pas créé ou prérempli directement en SQL :
il provient du vrai enregistrement audio confirmé dans l'interface. Les requêtes
web créent les trois jobs ; seul leur fournisseur d'inférence est fictif.

Les services existants gèrent réellement réservation, budgets, résultat,
stockage et publication. Des sessions SQL neuves et une réouverture du pool
avant l'historique contrôlent la persistance. Les instantanés image/émotion
référencent exactement le récit corrigé version 2. Les mêmes octets audio/image
sont relus via leurs URL privées. Le code ne remplace pas l'attente du navigateur
par des réponses réseau simulées.

La suppression est volontairement vérifiée en deux phases :

1. **Suppression web** : rêve `deleted`, date renseignée, médias `deleting`,
   fichiers encore présents mais détail/audio/récit/image/émotion et médias
   inaccessibles en HTTP 404 ; aucune confusion avec un effacement déjà réalisé.
2. **Purge explicite** : `DreamPurgeService.purge_one(owner, dream_id)`, service
   existant de maintenance P10, vise seulement ce rêve supprimé. Rêve, médias,
   trois jobs, description d'image, instantanés image/émotion et métadonnées
   d'émotion disparaissent en SQL ; les deux fichiers et leurs fichiers
   temporaires sont absents. Une nouvelle purge renvoie `not_found`.

**Éléments conservés volontairement :** compte fictif, session active et trois
événements de quota liés au compte, avec `job_id = NULL`. Ils ne contiennent ni
récit ni média et leur conservation évite de réinitialiser le quota par suppression
d'un rêve. Le scénario ne revendique donc pas l'effacement du compte ou de toute
métadonnée de sécurité. Le cluster jetable entier est ensuite détruit par le lanceur.

## Vérifications et résultats

Les commandes suivantes ont été utilisées avec le venv local, PostgreSQL et HTTPS
temporaires ; aucune campagne ne repose sur des données personnelles.

| Vérification | Résultat observé |
| --- | --- |
| Recette P16 locale, après correction | **1 passed**, 17,73 s |
| Même recette avec `CI=true` et preuves dans `tmp/p16-demo` | **1 passed**, 16,32 s |
| `verify_p20.py --browser-only --emotion-web-test` | **14 passed, 920 deselected**, 112,84 s |
| `verify_image_jobs.py --purge-only` : suppression, purge, médias et stockage | **109 passed**, 73,68 s |
| Contrats du workflow, avec `--basetemp` neuf | **11 passed**, 0,34 s |
| Empreintes des huit captures de référence | Huit SHA-256 conformes au rapport ; inspection visuelle réalisée |
| Ruff | Réussi |
| Compilation Python | Réussie |
| `pip check` | `No broken requirements found.` |

Erreurs rencontrées et traitées sans affaiblissement : quatre lignes dépassaient
la longueur Ruff ; le premier lancement Chrome a échoué car « Capturer un rêve »
désignait deux liens. Le sélecteur est désormais limité au contenu principal,
sans `.first()` ni changement d'assertion métier. Le lancement direct des contrats
CI avait **6 passed, 5 errors** à cause des permissions de l'ancien répertoire
temporaire pytest ; un nouveau `--basetemp` dédié corrige ce problème d'environnement.
Aucun test n'a été ignoré et aucun délai d'assertion augmenté.
La première recette Chrome avait **1 failed**, 4,57 s ; elle s'est arrêtée au
sélecteur ambigu avant la capture audio. Les campagnes finales ci-dessus n'ont
aucun échec ni skip. Les 920 désélections correspondent aux tests hors campagne
navigateur, pas à des erreurs contournées.

La suite complète avec couverture métier n'a pas été relancée pour ce changement
de recette et de documentation, sans modification du code applicatif. Le workflow
la conserve avant les deux campagnes Chrome. La validation distante après commit,
l'inférence réelle et une seconde machine ne sont pas des résultats obtenus ici.

## GitHub Actions et limites

Le workflow conserve les vérifications P14/P15 et ajoute une étape obligatoire
`python scripts/verify_p20.py --p16-demo`. Le scénario utilise un nom de fichier
de recette ciblée, comme P10 : il est exécuté explicitement dans cette étape,
sans être confondu avec les 14 parcours navigateur indépendants.

Avec `CI=true`, les preuves vont dans `tmp/p16-demo/run-*` plutôt que dans les
captures locales versionnables. Un second artefact, `p16-demo-<sha>`, publie
uniquement les huit noms PNG attendus et `result.json`, pendant sept jours et
uniquement si le job réussit. Aucun glob de `.env`, journaux, clés TLS, données
PostgreSQL ou traces de session n'est ajouté. Un test vérifie cette liste blanche
et le caractère obligatoire de la recette. Aucun workflow distant n'est déclenché
dans cette intervention ; une exécution GitHub après votre commit reste nécessaire.

**TLS :** conformément au choix validé, le contexte Chrome réutilise exclusivement
l'exception de certificat HTTPS de recette P14. Les protections HTTPS, origine,
CSRF et cookies Secure/HttpOnly de production restent inchangées. Ces tests ne
prouvent pas la confiance de la chaîne TLS du poste ; l'interception Avast
documentée en P15 reste une limite distincte. Le lanceur P14 garde son comportement
de santé HTTPS temporaire existant ; aucun nouveau contournement TLS n'est ajouté.

**IA et matériel :** aucune reconnaissance vocale, génération par modèle ou
classification émotionnelle réelle n'est exécutée. Le signal Chrome ne raconte
pas le récit affiché ; celui-ci est fixé par le faux fournisseur. Aucune mesure de
précision, de qualité artistique ou de performance des modèles n'est revendiquée.
La capture ne teste pas le microphone physique de la soutenance. Le parcours P16
est réalisé en Chrome desktop ; mobile, autres navigateurs et Linux restent hors
de ce scénario. Les tests P14 couvrent séparément plusieurs vues mobiles.

La carte d'historique conserve actuellement le libellé global **« Brouillon »**
(visible dans la capture 06), malgré les trois jobs terminés. La recette vérifie
leurs états propres et la persistance des résultats ; elle ne modifie pas
l'orchestration du statut global du rêve et ne prétend pas observer un libellé « Prêt ».

Enfin, la purge ne retire pas d'éventuelles copies déjà exportées, captures,
sauvegardes externes ou données présentes sur un autre poste. Aucun de ces éléments
n'est créé par ce scénario, hors les preuves fictives explicitement conservées.
