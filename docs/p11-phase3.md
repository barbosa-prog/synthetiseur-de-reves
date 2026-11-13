# P11 — Phase 3 : raccordement des workers

## Périmètre et garanties

Les créations STT, image et émotion des services existants passent désormais par
`job_lifecycle.create`, via `enqueue_existing` qui utilise la transaction de session
existante. Aucune seconde file, aucune nouvelle table ni migration n'est créée.
Les trois fonctions `claim` délèguent à `claim_next`, puis `reserve_job` et aux règles
pures `job_rules`. Il n'existe plus de chemin applicatif incrémentant directement
les tentatives hors de cette réservation commune.

Les réponses historiques restent compatibles : STT pending/processing/completed/failed,
image et émotion queued/running/done/failed. Les routes existantes restent protégées
par Bearer ou session/CSRF. Aucun endpoint ou écran de relance n'est ajouté.
Le champ historique `attempts` reste celui de la ligne de job. La phase 4 devra
exposer séparément le budget agrégé du cycle, sans renommer ce champ ni laisser
croire qu'une nouvelle ligne de génération dispose d'un budget neuf.

Le budget est conservé par identité des entrées et configuration serveur : 3
réservations au total, 2 relances explicites. L'UUID d'un nouveau job ou d'une copie
audio identique ne renouvelle pas le cycle. Une création après échec ne constitue
pas une relance et renvoie un conflit. Les tests historiques attendant une reprise
automatique ont été adaptés pour exiger un échec contrôlé, puis une relance explicite
avec compteur vérifié. Les autres contrôles historiques sont conservés.

## Configuration et publication

`job_config` construit les identités côté serveur. Aucun chemin, PID, RAM disponible,
timeout de supervision ou secret ne fait partie du digest des paramètres d'inférence.
La révision image est celle déjà qualifiée
`451f4fe16113bff5a5d2269ed5ad43b0592e9a14`. Les paramètres de suggestion émotionnelle
proviennent de P08 et restent contrôlés avant analyse et publication.

Pour STT, `download-complete.json` fournit la révision du modèle local, sans lecture
des poids ni accès réseau. En l'absence de manifeste exploitable, l'identité indique
explicitement `local-unverified`. Le véritable adaptateur LocalWhisper refuse alors
l'inférence avec une erreur de configuration. Les faux fournisseurs des tests
permettent de tester la file sans modèle disponible. Si la configuration réelle du
worker diffère de l'instantané de la demande, aucune inférence Whisper n'est exécutée.
Le modèle n'est jamais téléchargé automatiquement.

La garde commune de publication revérifie l'identité, le propriétaire, le rêve,
les versions courantes, les compteurs agrégés et le contexte émotionnel, en plus des
gardes de bail et jeton déjà présentes. Les publications P19 conservent leur protocole
transactionnel, compensation des écritures et contrôle de version juste avant commit.
Un ancien token, une suppression P10 ou une correction P06 ne donnent jamais droit
de publier. Aucune suggestion n'écrit automatiquement `dreams.emotion`.

STT conserve dans `input_snapshot._output` la version de sortie P06 et son empreinte.
L'identité d'entrée reste immuable : cette information de sortie est séparée et ne
participe pas à `cycle_key`. Une demande portant sur le même audio/configuration peut
réutiliser le succès si le récit courant correspond encore exactement à cette sortie.
Une correction ultérieure ne sera pas confondue avec la sortie STT d'origine.

Une image réussie identique est réutilisée par défaut après contrôle physique P19 de
disponibilité et d'intégrité. Les routes existantes injectent leur service privé P19,
y compris le stockage fictif des tests. `new_generation=True` sur le service image
reste une intention volontaire distincte : au plus 3 exécutions pour les mêmes entrées,
succès compris. L'exposition explicite de cette intention dans l'interface relève de
la phase 4 ; aucun champ de relance publique n'est ajouté ici.

Une nouvelle demande P08 après un changement explicite de contexte manuel peut
remplacer un ancien job échoué/annulé selon `refresh_emotion_context`. Elle consomme
une relance du même cycle et conserve toutes les tentatives précédentes. L'annulation
seule ne permet pas de recréer gratuitement le job. Suggestion et abstention réussies
restent réutilisables ; aucun choix retenu n'est changé implicitement.

## Historiques et déploiement

Un job sans identité fiable n'est jamais réétiqueté en inventant une révision.
Un historique queued rencontré par un consommateur devient failed/configuration
sans appel IA. Un historique running expire par maintenance ; sa publication par le
code courant est refusée. Les résultats historiques déjà publiés restent consultables
selon les protections existantes P06/P07/P08/P19.

Le service refuse encore de créer un cycle pour une famille rêve/type comportant un
historique sans identité : c'est une restriction conservatrice, pas une réparation
automatique. Une procédure de revue des historiques est nécessaire avant usage de
ces familles dans la base personnelle. Aucun compteur historique n'est remis à zéro.

Il faut arrêter et mettre à jour **tous** les anciens consommateurs lors du déploiement.
Un ancien binaire antérieur à P11 possédant toujours les identifiants PostgreSQL ne
peut pas être rendu sûr rétroactivement par une modification Python : aucun trigger
ou révocation de rôle n'est ajouté dans cette phase. Les points d'entrée historiques
du code courant utilisent tous P11. L'ORM exige 0009, jamais appliquée à dreams_local
pendant ce développement. Ne pas redémarrer l'application personnelle avant migration
et contrôle explicitement autorisés.

## Récupération, délais et arrêt

Chaque prise en charge commence par une maintenance PostgreSQL sans IA. Une première
itération de worker traite donc les expirations avant toute nouvelle réservation.
La commande indépendante de phase 2 reste utilisable lorsque tous les workers IA sont
arrêtés ; en mode `--watch --apply`, elle effectue un passage toutes les 5 secondes.
Les contrôles opportunistes des workers peuvent être plus fréquents, sans relance IA.

- queued : expiration après 30 minutes par défaut ; failed/queue_timeout.
- running : expiration du bail ; failed/interrupted et révocation du token.
- rêve supprimé : failed/dream_deleted ; aucune réactivation.
- Aucun passage automatique failed → queued, même après redémarrage.

`P11_QUEUE_TIMEOUT_SECONDS` est partagé par la maintenance indépendante et les
consommateurs : augmenter ce délai ne doit pas laisser un worker appliquer encore
le défaut de 30 minutes. Le test couvre une attente de 31 minutes avec un réglage
à 3 600 s. Les compteurs et l'identité restent inchangés.

Les échéances utilisent l'horloge PostgreSQL. Whisper utilise le timeout effectivement
fourni par son adaptateur : 600 s par défaut, jusqu'à 1 800 s, plus 120 s de marge de
bail. Le timeout ne modifie pas l'identité d'inférence ni le budget. Image/émotion :
120 s par défaut et bail de 240 s. Les ponts attendent respectivement timeout+45 s et
timeout+30 s ; les procédures d'arrêt existantes restent bornées et inférieures à la
marge par défaut. Les tests de pont simulent processus, timeout et interruption.

En cas de Ctrl+C, les runners ferment leurs canaux/arrêtent leurs sous-processus selon
leurs protections existantes ; le service révoque la réservation et marque worker_stopped.
Si PostgreSQL est inaccessible pendant cet arrêt, le bail persistant permet la
récupération ultérieure. La panne ne crée aucune tentative supplémentaire. Un arrêt
brutal ne garantit pas un nettoyage immédiat : le surveillant puis la maintenance
restent nécessaires. Aucun modèle n'est invoqué pour effectuer cette récupération.
Une suppression ou annulation en base révoque immédiatement le droit de publier ;
elle ne garantit pas l'arrêt instantané d'un calcul externe déjà commencé. Celui-ci
reste borné par son surveillant et son timeout, et son résultat tardif est refusé.

Les transactions utilisent les bornes P11 (verrou 3 s, instruction 10 s). Les conflits
de réservation n'autorisent jamais un second calcul. Une contention temporaire
est différée avec un signal Retry-After ; elle ne transforme pas un job encore
valide en résultat périmé et ne consomme aucune tentative. STT et image conservent leur
dégradation avec attente de 5 s lors d'une panne ; la boucle émotion possède maintenant
le même comportement. `--once` retourne une erreur générique plutôt que boucler.
Si tous les services sont arrêtés, la récupération attend le prochain démarrage :
aucun traitement ne peut s'exécuter en l'absence de processus.

## Commandes Windows

Validation isolée, sans poids ni réseau fournisseur :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --workers-only
.\.venv\Scripts\python.exe scripts/verify_p20.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
git diff --check
```

Les lanceurs créent exclusivement leurs clusters et répertoires de test temporaires.
Ne pas définir TEST_DATABASE_URL sur la base personnelle. Aucun worker réel n'a été
lancé pendant ces recettes. Les commandes opérationnelles existantes restent :

```powershell
# À exécuter uniquement sur une cible autorisée migrée en 0009 :
.\.venv\Scripts\python.exe -m backend.app.stt_worker --once
.\.venv\Scripts\python.exe -m backend.app.image_worker --once
# Émotion : activation explicite et DATABASE_URL explicite restent obligatoires.
.\.venv\Scripts\python.exe -m backend.app.emotion_worker --once
```

Ces trois dernières commandes ne font pas partie de la recette automatique de cette
phase et ne doivent pas être lancées sur les rêves personnels sans autorisation.
La maintenance indépendante conserve son inventaire par défaut et exige la confirmation
du nom de base pour appliquer des changements ; voir `p11-phase2.md`.

## Fichiers

Créés : `backend/app/job_config.py`, `backend/tests/test_worker_jobs_p11.py`, ce rapport.

Modifiés dans cette phase : `backend/app/services/job_lifecycle.py`, `stt_jobs.py`,
`image_jobs.py`, `emotions.py`, `image_execution.py`, `backend/app/image_routes.py`,
`backend/app/emotion_worker.py`, `backend/tests/test_stt.py`, `test_image_jobs.py`,
`test_emotion_postgresql.py`, `test_job_lifecycle.py`, `scripts/verify_image_jobs.py`.
Les scénarios de `test_emotion_web.py`, `test_image_browser.py` et
`test_stt_browser.py` vérifient maintenant la réutilisation des succès/abstentions,
puis utilisent un nouveau récit, une nouvelle description ou un autre rêve fictif
pour éprouver un nouveau traitement.
Les modules exécutables STT/image réutilisent automatiquement ces services communs.
Les fichiers des phases 1 et 2 restent présents ; aucune migration supplémentaire.
Le CSS préexistant n'est ni modifié ni restauré. Aucune opération Git d'ajout/commit/push.

## Résultats mesurés

La première campagne ciblée achevée après adaptation des attentes de récupération :
138 tests réussis en 67,61 s. La campagne ciblée finale a donné **146 réussis en
87,08 s**, dont **31 nouveaux cas P11 phase 3**. Le test de manifeste malformé a
aussi été exécuté seul : 1 réussi en 1,33 s, sans connexion ni modèle.

La campagne complète corrigée a donné **703 réussis, 1 ignoré** en 388,32 s,
couverture backend **88,43 %**, incluant Chrome ordinateur/mobile et la persistance
P04/P09/P19 après redémarrage PostgreSQL/Uvicorn temporaires. Les deux derniers
tests de manifeste et de contention ont ensuite été couverts dans les 146 tests
ciblés.

**Consolidation complète sur l'état final figé : 705 réussis, 1 ignoré en 364,99 s**,
couverture backend **89,17 %**. Les 31 cas spécifiques de ce module sont inclus.
Couvertures : `job_config` 100 %, `job_lifecycle` 92 %, maintenance 87 %.
Le test ignoré reste `test_emotion_real.py` (inférence réelle opt-in interdite ici).
Aucun avertissement n'est remonté dans cette dernière campagne. Les avertissements
Pydantic d'alias observés lors de campagnes concurrentes intermédiaires n'ont pas été
masqués ni traités par un changement hors périmètre.

Les recettes ont confirmé l'historique P09 et l'audio P04 après un redémarrage réel
PostgreSQL/Uvicorn temporaires, puis le refus P19 après purge du média fictif. Les
processus de recette ont été arrêtés et les répertoires temporaires nettoyés.
La base personnelle n'a jamais été utilisée et aucune migration personnelle exécutée.

Ruff backend/scripts, compilation Python ciblée, vérification des sept fichiers
JavaScript, compilation locale Tailwind 4.3.0 vers un fichier temporaire et
`git diff --check` : réussis. Le CSS temporaire a été supprimé. L'empreinte du CSS
préexistant reste exactement
`d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.
Les 29 fichiers modifiés/non suivis examinés ne présentent aucun modèle, environnement,
archive, média privé ou secret selon les noms/extensions et motifs contrôlés.
Les modifications déjà présentes des phases 1 et 2 ne sont pas attribuées à la phase 3.

Une campagne intermédiaire complète a donné 699 réussis, 3 échecs et 1 ignoré : les
trois scénarios web/navigateur demandaient implicitement une nouvelle IA sur des
entrées déjà réussies ou une abstention. Les attentes ont été adaptées au contrat
P11 en conservant les vérifications d'échec sur de véritables nouvelles entrées.
Il ne s'agissait pas d'autoriser une relance cachée pour faire passer les tests.

Les faux fournisseurs et fichiers synthétiques couvrent les cycles raccordés, les
budgets, le cache STT après changement de version de sortie, les réservations uniques,
le redémarrage sans nouvelle IA, l'historique non identifié, Ctrl+C, les délais,
la panne PostgreSQL simulée, l'abstention et les choix manuels, les versions périmées,
la suppression/purge et les résultats tardifs. Les tests de non-régression existants
complètent ces contrôles, dont l'isolation des comptes et les médias privés.

Aucune compatibilité matérielle nouvelle ni performance d'inférence réelle n'est
revendiquée : aucun modèle, GPU, téléchargement ou appel fournisseur n'a été utilisé.
