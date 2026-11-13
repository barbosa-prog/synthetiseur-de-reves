# P12 / SCRUM-16 — Phase 1 : corps HTTP et journaux

Cette phase ne comprend ni quota global IA, ni migration, ni modification
Swagger/ReDoc. Aucun accès à la base personnelle, aucun modèle réel, aucun service
fournisseur et aucune modification du CSS source indépendant.

## Limites de réception

| Entrée | Plafond transmis | Délai de réception |
| --- | --- | --- |
| API d'authentification ; formulaires connexion/inscription/déconnexion ; session web | 8 Kio | 10 s |
| Autres routes `/api/v1/` et formulaires `/reves/` | 256 Kio | 10 s |
| Audio `/web/audio`, `/api/v1/dreams/audio` | 15 Mio, constante P04 réutilisée | 30 s |
| Autres chemins | 8 Kio | 10 s |

Les plafonds concernent les **octets reçus**, pas le nombre de caractères métier.
256 Kio permet de conserver un récit de 20 000 caractères, y compris son encodage
JSON échappé ou celui d'un formulaire URL-encoded. Les schémas continuent de
limiter le récit à 20 000 caractères et la description visuelle à 500 caractères.
8 Kio suffit aux identifiants bornés existants et aux petits formulaires publics.

`HTTPGuard`, middleware ASGI extérieur aux middlewares applicatifs, compte les
octets à chaque message avant de les ajouter au tampon ou de les transmettre.
Les petits corps sont mis en mémoire **après contrôle de chaque segment**, avec
une borne totale, avant le parsing JSON et les mutations métier. Les copies du
tampon et les objets décodés restent bornés ; ce n'est pas un plafond exact de
RSS du processus ni un quota global de requêtes simultanées.

L'audio n'est pas préchargé : le garde enveloppe sa réception en flux, puis le
service P04 écrit son fichier temporaire et conserve ses validations, ses deux
places de réception par processus, son décodeur isolé de 20 s et sa durée maximale
de 8 minutes. Les contrôles session/Bearer et CSRF peuvent toujours refuser un
audio **avant de lire son corps**. Les images ne disposent pas d'un nouvel import
HTTP : les limites P07/P19 de 8 Mio et de dimensions restent inchangées.

Les formulaires d'authentification sont également lus progressivement dans
`valid_form`, avec au plus 8 Kio conservés avant parsing. La mise en cache de ce
petit corps permet de préserver le parseur de formulaire existant.

### Erreurs et protocole

- 413 : taille annoncée ou réellement reçue supérieure au plafond.
- 400 : longueur malformée, répétée, incompatible avec Transfer-Encoding, ou
  différente de la taille effective du corps présenté à l'application.
- 408 : réception trop lente ou interrompue. Un client déjà déconnecté ne peut
  naturellement plus recevoir cette réponse.
- 415 : Content-Encoding autre qu'identité ; pas de décompression implicite
  susceptible de contourner les plafonds.

L'absence de Content-Length est acceptée, y compris un flux chunked, mais ne
désactive jamais le comptage. Les erreurs gardent le format JSON public, sans
corps ni détail d'exception, avec `Cache-Control: no-store`. Les refus de réception
ferment la connexion HTTP/1 pour ne pas réutiliser un flux partiellement consommé.
Les erreurs encapsulées par Starlette conservent le refus prévu, sans devenir 500.
La limite est celle du corps après cadrage HTTP par Uvicorn ; elle ne remplace pas
les validations du parseur HTTP ni des limites de transport pour un déploiement
public (nombre de connexions, en-têtes, reverse proxy).

## Journaux par liste blanche

`safe_logging.install_safe_logging()` est installé par la fabrique FastAPI et par
la création d'un moteur SQLAlchemy pour les processus de workers. Il protège les
enregistrements Python avant leur traitement par les handlers :

- Seuls des codes fixes d'événements applicatifs et de cycle de vie Uvicorn sont
  conservés : `request_failed`, `request_rejected`, `response_interrupted`, etc.
- Tout message tiers, ses arguments et les données SQL deviennent
  `diagnostic_redacted`, sans appeler leur représentation textuelle.
- `exc_info`, les tracebacks formatés, stack_info et les positions source sont
  retirés. Les avertissements Python sont redirigés vers ce même mécanisme.
- Les handlers existants utilisent un format limité à l'heure, la gravité, le
  code d'événement et le PID ; ni URL, query string, IP, cookie, en-tête, récit,
  paramètre SQL ou champ `extra` n'est sérialisé.
- Le format Uvicorn des accès est remplacé : même avec `--access-log`, il ne peut
  réintroduire les arguments de requête ni produire d'erreur de formatage.

`HTTPGuard` absorbe les exceptions inattendues avant qu'elles n'atteignent le
gestionnaire d'erreur serveur extérieur qui les transmettrait à Uvicorn. Avant
envoi, il retourne le 500 générique et un événement fixe. Après début d'envoi,
il journalise seulement `response_interrupted` : il est impossible de remplacer
des en-têtes déjà envoyés. Selon le chemin de streaming, le client observe une
interruption réseau ou une réponse déjà terminée ; aucun succès métier n'est
inventé et aucun nouveau téléchargement ou traitement n'est lancé.

Les logs volontairement pauvres évitent une tentative fragile de recherche et
remplacement de secrets. Le diagnostic disponible est le code, la date, la
gravité et le processus ; il n'y a pas de traceback détaillé en production.
Les commandes existantes `--no-access-log --no-proxy-headers` restent recommandées.

### Frontières de la garantie

Les résultats de sous-processus IA sur stdout restent des canaux IPC privés
capturés, **pas des logs** : aucune redirection de stdout globale n'est ajoutée.
Les messages opérationnels `print` des workers restent génériques ; les moteurs
et leurs traitements ne sont pas modifiés. Ne pas lancer le décodeur Whisper
directement dans un journal partagé ni recopier sa sortie privée dans un log.

Cette politique concerne le logging Python du processus applicatif. Elle ne
configure pas les journaux PostgreSQL, Windows/WER, un proxy, un agent externe,
les sorties natives ou les crash dumps. Elle ne doit pas être remplacée par une
autre LogRecordFactory ou par une sérialisation de `LogRecord.__dict__`/des corps.
Une reconfiguration externe des handlers exige une nouvelle validation.
La couverture ne prétend pas supprimer des journaux historiques.
Sans handler configuré, le dernier recours standard de Python peut n'afficher
que le code fixe de l'événement ; il ne récupère pas le message privé supprimé.

## Fichiers de cette phase

| Fichier | Raison |
| --- | --- |
| `backend/app/http_guard.py` (nouveau) | Réception bornée, contrôles de longueur/temps et frontière des erreurs inattendues |
| `backend/app/safe_logging.py` (nouveau) | Liste blanche des événements et format de journaux sûr |
| `backend/app/main.py` | Installation du garde et de la politique de logs |
| `backend/app/database.py` | Politique de logs également installée pour les consommateurs PostgreSQL/ workers |
| `backend/app/errors.py` | Réponse générique 408 cohérente |
| `backend/app/web/routes.py` | Lecture progressive du formulaire 8 Kio avant parsing |
| `backend/tests/test_http_guard.py` (nouveau) | Segments, plafonds, longueurs, délais, interruptions et erreurs Starlette |
| `backend/tests/test_safe_logging.py` (nouveau) | Logging, canal stdout privé et vrais logs Uvicorn |
| `backend/tests/p12_server_fixture.py` (nouveau) | Serveur de test sans DB ni IA, avec erreurs privées fictives ; aucune route livrée |
| `docs/p12-phase1.md` (nouveau) | Contrat, résultats et limites |

## Recette et résultats

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_http_guard.py backend/tests/test_safe_logging.py backend/tests/test_api.py -p no:cacheprovider -q
.\.venv\Scripts\python.exe scripts/verify_p20.py --emotion-web-test
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend scripts
git diff --check
```

Les tests ASGI simulent les segments, les tailles déclarées fausses/absentes,
les doubles longueurs, les encodages refusés, un délai borné et une déconnexion.
Un vrai Uvicorn temporaire, accès et niveau debug activés, reçoit des marqueurs
fictifs dans le récit, les en-têtes, l'URL et des exceptions. Ses sorties stdout
et stderr sont réellement relues ; les marqueurs et tracebacks doivent être
absents. Le test couvre aussi un avertissement Python, une erreur de streaming
et une nouvelle requête de santé après erreur. Ce serveur ne se connecte à aucune
base. Le serveur de non-régression utilise exclusivement PostgreSQL temporaire et
des faux moteurs, jamais `dreams_local`.

Campagne ciblée finale : **39 réussis en 3,90 s**, incluant 27 cas P12 et les 12
tests API P01. Une première campagne complète a donné **768 réussis, 1 ignoré
en 476,37 s**, couverture **89,15 %**. La consolidation finale donne
**769 réussis, 1 ignoré en 462,76 s**, couverture backend **89,67 %**
(4 376 instructions, 452 non couvertes). Couverture du garde HTTP : **98 %** ;
politique de logs : **94 %**. Aucun avertissement dans la campagne finale.
Le test ignoré est l'inférence réelle
mDeBERTa opt-in, volontairement non exécutée. Les quatre tests web ignorés lors
du premier lancement sans TEST_DATABASE_URL ont bien été exécutés dans la suite
complète PostgreSQL temporaire.

Les parcours Chrome existants passent, dont les trois parcours de traitements
STT/image/émotion sur ordinateur et à 390 px. Les contrôles complémentaires du
lanceur confirment après redémarrage réel de PostgreSQL/Uvicorn temporaires :
données, budgets et réservations P11 identiques, historique P09 identique, audio
P04 relu en 200 et média P19 relu en 200 puis refusé en 404 après purge fictive.
Les serveurs sont arrêtés et le répertoire du cluster temporaire est nettoyé.
Le contrôle final des processus retourne **0 processus de recette restant**.

Ruff backend/scripts, compilation Python et `git diff --check` : réussis.
Les fichiers JavaScript, templates, CSS, dépendances et migrations sont inchangés.

Git : aucun ajout à l'index, commit, push, restore ou reset. Aucun changement Jira.
État final : 4 fichiers suivis modifiés et 6 nouveaux fichiers P12 ; index vide.
La seule autre modification est le CSS indépendant préexistant, non modifié ici.
`frontend/styles/app.css` est hors périmètre ; son empreinte reste
`d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.
