# P11 — SCRUM-15, phase 1 : contrat des jobs et relances

## Statut et périmètre

Contrat pur proposé, daté du 13 novembre 2026, sur la base du commit 79a8265.
Fichiers : job_rules.py et test_job_rules.py. Aucun branchement dans les routes,
services SQL, workers ou maintenance existants. Aucun changement de réponse API,
aucune migration créée/appliquée, aucune base PostgreSQL utilisée par les tests.
Les protections décrites ici ne corrigent donc PAS encore les limites de P11
dans l'application actuelle. Les phases opérationnelles restent à autoriser.

Les fonctions reçoivent une horloge, des identités serveur et un état immuable.
Aucun appel réseau, IA, disque, SQL, horloge réelle ou UUID aléatoire implicite.
Un cycle est l'unité logique de budget, pas nécessairement un seul UUID de job.

## États et transitions

| État technique | Signification |
|---|---|
| queued | Demande explicite persistée, aucune réservation d'exécution active |
| running | Réservation exclusive avec jeton et bail ; une tentative est consommée |
| done | Résultat accepté transactionnellement ; peut être une abstention P08 |
| failed | Traitement terminé sans résultat publiable ; motif sûr distinct |

Transitions autorisées pour un job : queued → running, queued → failed,
running → done, running → failed, failed → queued. Toute autre transition est
interdite ; les répétitions de lecture/récupération sont des no-op, pas des
transitions. Un job done n'est pas réarmé. Une nouvelle demande P08 dans un
contexte révisé peut créer une autre ligne, jamais réécrire le job done précédent.

L'état technique reste séparé de stale (péremption), outcome (result/abstention)
et error_code (échec fournisseur, annulation, sécurité...). Une ancienne image
calculée avec succès peut être techniquement done et métier périmée. Une
abstention P08 reste done et ne devient ni neutre ni autre. Une annulation active
est failed/cancelled, pas un cinquième état. Un rêve absent/supprimé n'est pas
consultable même si son ancien job était done.

Les projections P05 pending/processing/completed et P07/P08 restent inchangées
à cette phase. Prévoir ensuite un champ canonique supplémentaire state, sans
supprimer/renommer le status historique. Les libellés français et informations
outdated/abstention restent distincts ; aucun pourcentage fictif de progression.

## Identité des entrées et périmètre du cycle

Inputs est interne, construit depuis la base et la configuration approuvée,
jamais accepté tel quel depuis le navigateur. Empreinte SHA-256 avec domaine
p11-input-v1, sérialisation JSON canonique et champs explicites :

| Type | Entrées définissant le cycle |
|---|---|
| Commun | UUID propriétaire, UUID rêve, type, version P06, moteur/révision modèle/politique, empreinte des paramètres d'inférence approuvés |
| STT | SHA-256 des octets audio normalisés stockés par P19 ; version du récit cible, y compris 0 |
| Image | Empreinte du récit courant, texte/version P06, empreinte/version de la description P07 |
| Émotion | Empreinte du récit courant et version P06 ; configuration qualifiée de suggestion |

Le media_id STT reste un localisateur interne pour les contrôles P19, mais ne
participe PAS à l'empreinte : copier le même audio dans un nouveau média du même
rêve ne recrée pas un budget. Un nouveau job_id, horodatage, jeton, chemin local,
action de rafraîchissement ou compteur technique ne change pas les entrées.
Les contenus sont les valeurs canoniques réellement sauvegardées : aucune
traduction ou normalisation sémantique implicite, ni suppression des accents.

Le digest des paramètres doit être calculé par le service sur une liste serveur
approuvée, pas sur un JSON client ni sur des secrets/chemins. Exemples : langue,
beam size et VAD STT ; dimensions, steps, seed, dtype et filtre image ; stratégie
et seuils P08. Les ressources volatiles (RAM libre, PID, chemin du venv, etc.) ne
doivent pas renouveler le budget. Les révisions modèle/politique sont celles
des manifestes et configurations déjà approuvés, pas une chaîne fournie par le client.

La révision P08 du choix est une GARDE de publication séparée de l'identité.
Elle avance aussi pendant les demandes/publications : l'utiliser comme clé de
cycle permettrait de contourner le budget. Modifier/accepter/retirer une émotion
ne doit jamais permettre à un ancien résultat de publier ni créer un budget neuf.
refresh_emotion_context représente une nouvelle demande explicite avec contexte
P08 plus récent : ancienne ligne conservée, nouveau snapshot, mais compteurs du
cycle conservés et une relance consommée. Les versions du récit doivent rester
identiques ; un changement de texte n'est pas une relance de l'ancien cycle.

## Budgets et actions explicites

- Maximum 3 prises en charge du cycle, première comprise. La réservation validée
  consomme une tentative, même si un précontrôle refuse ensuite le modèle.
- Maximum 2 relances manuelles. Une relance compte dès la remise en file, même
  si aucun worker ne démarre. Les expirations successives queued ne sont donc
  pas un moyen d'obtenir des relances infinies avec attempts=0.
- Le premier plafond atteint interdit la relance. Aucun décrément/remise à zéro
  après échec, absence de RAM, interruption ou perte de réponse HTTP.
- retry exige une action explicite, un job failed, une erreur admissible, des
  entrées et un contexte toujours actuels, un rêve accessible et du budget.
- La lecture/polling ne crée rien et ne relance rien. Les doubles demandes
  actives sont dédupliquées ; une création sur un cycle failed renvoie retry_required.
- Une nouvelle validation après changement réel de récit/description/configuration
  approuvée peut ouvrir un autre cycle. Modifier un UUID seul ne suffit pas.

Le futur service DOIT rechercher le cycle correspondant dans tout l'historique
du rêve et pas seulement le dernier job. Lui passer previous=None sans cette
recherche contournerait le contrat ; aucune fonction pure ne peut prouver seule
ce qui existe dans PostgreSQL. La réservation et le contrôle des compteurs seront
transactionnels en phase 2.

Choix proposé à valider : une demande strictement identique déjà done retourne
le résultat existant, sans nouvelle exécution. P07 autorisait auparavant un
nouveau job après succès : si l'on souhaite conserver une nouvelle génération
identique sur clic explicite, il faudra distinguer une nouvelle opération
terminée avec succès d'une relance d'échec, avec un identifiant de cycle serveur.
Il ne faut pas simplement remettre le compteur à zéro. Cette décision précède
le raccordement ; aucun comportement P07 n'a été changé actuellement.

## Erreurs

Relançables manuellement, après correction de la cause si nécessaire : timeout,
interrupted, worker_stopped, worker_busy, queue_timeout, insufficient_memory,
memory_unknown, model_unavailable, provider_unavailable, worker_unavailable,
provider_failed, network_error, rate_limited. Le clic ne dispense pas le futur
worker des précontrôles mémoire/modèle/configuration.

Non relançables à l'identique : safety_blocked, cancelled, dream_deleted,
text_conflict, stale_result, media_unavailable, invalid_text, invalid_image,
invalid_result, configuration, disabled, outcome_unknown, unknown_error.
Un changement réel et validé des entrées/configuration demande une nouvelle
opération, pas un contournement de la décision de sécurité. Pour P08 seulement,
une nouvelle demande explicite après changement de contexte peut reprendre
stale_result/cancelled avec le budget restant, sans attribution automatique.

Une exception non reconnue devient unknown_error, non relançable : aucun chemin
privé ni message brut n'est exposé, et une erreur inconnue ne déclenche pas un
appel supplémentaire par défaut. network_error doit désigner une défaillance
connue ; une requête externe possiblement déjà exécutée devient outcome_unknown.
Le futur adaptateur distant devra réconcilier l'opération/idempotence avant
nouvelle exécution. Exactement une publication ne signifie pas exactement un
calcul/facturation distant. Aucun fournisseur payant n'est introduit ici.

## Délais proposés, non appliqués aux workers actuels

| Budget | Valeur proposée |
|---|---:|
| Attente queued depuis queued_at | 30 minutes, renouvelées uniquement par relance explicite |
| Exécution STT, chargement compris | 600 s par défaut ; compatible avec configuration 30–1800 s |
| Exécution image | 120 s |
| Exécution émotion CPU | 120 s |
| Marge de bail pour initialisation/arrêt/validation/publication | 120 s |
| Bail initial proposé STT / image / émotion | 720 s / 240 s / 240 s |
| Passage souhaité de récupération | Toutes les 5 s et au redémarrage |

Ces valeurs ne sont pas de nouvelles mesures de performance. La marge est plus
large que les 60 s actuelles, notamment pour les surveillants et nettoyages P07/P08.
Les budgets réels du runner et du bail devront être validés ensemble avant
raccordement. Aucun seuil RAM/VRAM ou paramètre de modèle n'est modifié.
Pas de heartbeat obligatoire proposé pour ces traitements locaux déjà bornés.

À now >= échéance : queued devient failed/queue_timeout ; running devient
failed/interrupted et perd son jeton/bail. Aucune récupération ne remet en file
et aucun modèle n'est lancé automatiquement. Une récupération répétée ne consomme
pas de budget et ne change pas un état terminal. Suppression active : failed/
dream_deleted ; entrées ou contexte changé : failed/stale_result.

L'horloge est injectée, timezone obligatoire ; PostgreSQL devra fournir la date
de référence. Une borne passée est refusée, pas silencieusement assimilée à une
nouvelle attente. Un résultat au moment exact de l'expiration ne publie pas.

PostgreSQL indisponible : pas de nouvelle réservation/relance réputée réussie,
pas de publication sans validation transactionnelle, erreur de suivi distincte
d'un échec du calcul. Au retour, maintenance avant reprise des moteurs. Tous
processus arrêtés/PC éteint : rien ne fait évoluer les lignes ; elles sont
reprises au prochain passage, sans promettre une échéance murale impossible.
La récupération opérationnelle future doit fonctionner sans moteur installé ou
activé, et ne pas faire échouer la santé FastAPI si la base est indisponible.

## Concurrence et suivi public

Les fonctions pures ne réservent pas réellement de ressources. La phase 2 devra
réutiliser index actifs, SKIP LOCKED, jetons serveur uniques, transaction et ordre
job → rêve. Les compteurs et l'absence d'un autre cycle actif devront être vérifiés
dans la même transaction. Deux relances simultanées ne doivent consommer qu'une
relance, la seconde étant refusée/dédupliquée. Un ancien jeton ou un doublon de
résultat n'a jamais droit de publier. Les verrous locaux de ressources restent
distincts de la table de jobs et ne doivent pas être contournés par un reaper.

public_progress expose seulement state, attempts/max_attempts,
retry_count/max_retries, error_code sûr, stale, outcome et retryable. Une version
de récit dépassée reste une information métier, sans falsifier l'état technique.
Les identités, empreintes, jetons, chemins, texte et configuration restent internes.
Les codes seront traduits en messages génériques par les futures routes. Les
UUID publics de jobs déjà autorisés pourront rester dans leurs réponses historiques.

P09 conserve ses filtres et l'émotion explicitement retenue. Une synthèse des
jobs éventuelle sera calculée à la lecture, sans faire de Dream.status une copie
ambiguë de plusieurs jobs. P10 reste prioritaire : rêve deleted/purgé inaccessible,
aucune relance, réservations révoquées ; disparition d'un job pendant purge
tolérée par les workers. Le contrat n'ajoute pas de référence qui empêcherait
l'effacement actuel des dépendances.

## Persistance à préparer en phase 2

retry_count est nécessaire pour distinguer les relances demandées des réservations,
notamment après expiration sans worker. queued_at est nécessaire pour donner à
une relance sa propre échéance sans modifier created_at. Une clé d'entrées
cycle_key persistée/indexée est recommandée pour empêcher le reset via nouveaux
UUID et l'aller-retour entre anciennes entrées. Pas de seconde file ni table
de tâches proposée. Les trois champs n'existent pas dans le schéma courant.

Si plusieurs lignes P08 appartiennent au cycle, JobState représente leur budget
AGRÉGÉ ; les services devront compter les lignes correspondantes sous verrou et
écrire uniquement les deltas sur la tentative courante, pas recopier le total
dans chaque ligne. Le regroupement exact et les reprises des historiques P05
sans snapshot de configuration devront être validés ; ne pas inventer une
provenance ou un historique de relances absent.

Une migration additive est donc justifiée après validation du contrat, mais
aucune migration n'est créée ici. Si les nouvelles opérations après done sont
conservées, valider aussi leur identifiant de cycle pour séparer les budgets
fermés des échecs ouverts. Les schémas API existants resteront compatibles.

## Validation exécutée et décisions restantes

Campagne finale : 140 tests unitaires réussis en 1,05 s, dont 73 P11. Elle inclut
les contrats P08, P06 et image P07 existants, sans PostgreSQL et sans inférence.
Ruff backend/scripts réussi. Les défauts initiaux de longueur/import ont été
corrigés. Aucun test PostgreSQL, navigateur ou worker réel n'est revendiqué.

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_job_rules.py `
  backend/tests/test_emotion_contract.py backend/tests/test_text_rules.py `
  backend/tests/test_image_provider.py -q -p no:cacheprovider `
  --basetemp tmp/p11-phase1-unit-final
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

Avant phase 2 : valider les délais proposés, la déduplication après done ou
la conservation de nouvelles opérations explicites, puis le regroupement SQL
des cycles et la migration additive correspondante. Les règles d'échec/reprise
définies ici remplaceront seulement après accord la reprise automatique actuelle.

Seuls job_rules.py, test_job_rules.py et ce document sont ajoutés. Le CSS
préexistant est préservé, aucune route ou worker modifié. Aucun secret ni média
fictif binaire enregistré, aucun git add/commit/push ou changement Jira.
