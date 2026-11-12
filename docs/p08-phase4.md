# P08 — Phase 4 : worker CPU expérimental, activation explicite

## Périmètre et limites fonctionnelles

mDeBERTa sert seulement de suggestion facultative. Le worker ne met jamais
à jour dreams.emotion : publication du résultat et écriture du choix sont
séparées, même si la valeur serait identique. Une acceptation/correction
explicite reste indispensable. Abstention et panne ne deviennent jamais
neutre ou autre ; la saisie manuelle n'utilise pas le worker.

Politique choisie : variante prudente qualifiée en phase 2C, sans nouveau
réglage, pas la référence plus permissive de phase 2B. Variante 1, seuil 0,45,
marge 0,05, trois contrôles à 0,4, garde lexical désactivé. Colère/dégoût/
surprise/curiosité regroupés sous autre ; refus si information insuffisante,
ambiguïté ou pluralité sans dominante. Les raisons internes sont ramenées aux
abstentions contractuelles insufficient_information ou ambiguous.

Cette variante n'est PAS validée comme classifieur général : lors de 2C,
couverture 18 %, macro-F1 0,277, rappel neutre/autre nul sur le jeu explicite.
Les neuf suggestions correctes observées ne garantissent pas une précision
future de 100 %. L'avertissement non médical devra être affiché en phase 5.
Aucune interface HTML ou nouvelle migration dans cette phase.

## Architecture et isolation

- emotion_config.py : configuration publique versionnée, aucun import IA.
- emotion_provider.LocalMDeberta : adaptateur interchangeable, runner injecté.
- emotion_worker.py : boucle persistante séparée de P05/P07, une tâche à la fois.
- emotion_runner.py : pont vers le Python CPU isolé, protocole JSON par pipes.
- scripts/emotion_cpu_bridge.py : surveillant indépendant, sans import torch.
- scripts/emotion_cpu_child.py : vérification des fichiers, chargement et calcul.

Le venv existant est %LOCALAPPDATA%/SynthetiseurDeReves/qualification/p08/.venv.
Le seul modèle autorisé est sous qualification/p08b/model dans cette même racine.
Révision 8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c. Pas de chemin arbitraire
fourni par le navigateur. Aucun téléchargement, installation ou autre modèle.

Safetensors uniquement, local_files_only=True, trust_remote_code=False,
HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE, visibilité CUDA vide. PyTorch doit être
la distribution 2.7.1+cpu, sans CUDA, avec paramètres et calculs FP32 CPU.
Le manifeste local, sa provenance et les empreintes des poids/tokenizer sont
vérifiés avant chargement ; fichiers locaux cohérents et liens de fichiers
refusés. L'empreinte du code de politique qualifié doit correspondre.

Versions requises et enregistrées dans le snapshot : Python 3.12.14,
Transformers 4.57.3, Tokenizers 0.22.2, Safetensors 0.7.0, psutil 7.1.3.
Les changements de versions ou de paramètres produisent une erreur de
configuration, pas un téléchargement ou un remplacement implicite du modèle.
Le noyau de politique réutilise explicitement qualification/p08/reliability.py
(code gelé 2C) : ces sources doivent accompagner ce worker expérimental.

Chaque job dispose d'un sous-processus modèle neuf, libéré après calcul :
pas de copies conservées dans FastAPI ou le worker, pas de pipeline GPU.
Le récit passe par stdin UTF-8, jamais par argv ou fichier de journal.
Le bridge conserve seulement une sortie éphémère sans récit dans un dossier
privé LOCALAPPDATA/p08-worker, hors Git/OneDrive/statique, puis la supprime.
Erreurs et messages CLI sont des codes/textes génériques, sans traceback privé.

## Réservation, publication et activation

EMOTION_ENABLED absent ou différent de 1 : worker désactivé, sans ouverture
de base ou chargement de .env. Même activé, DATABASE_URL doit être explicitement
présent dans l'environnement du worker ; pas de sélection implicite de la
base personnelle depuis .env.

L'API enregistre la configuration d'activation au moment de la demande.
Activer plus tard un worker ne rend PAS exécutables d'anciens snapshots
désactivés ou de phase 3 : ils échouent configuration. Annuler/recréer une
demande explicite après activation cohérente des deux processus.
La configuration du worker doit être exactement celle du snapshot avant calcul.
Elle inclut modèle/tokenizer, stratégie, empreinte du code, seuils, découpage,
dépendances et limites. L'utilisateur ne fournit pas ces paramètres par API.

Avant calcul : réservation persistante, validation de version/propriétaire,
révision du choix et token. Après calcul : garde transactionnelle phase 3,
token/bail, récit et révision toujours actuels. Un résultat tardif est refusé.
La publication utilise save_state(update_choice=False), sans même assigner
dreams.emotion. Un test SQL confirme qu'aucun UPDATE dreams n'est émis.

Ctrl+C signale worker_stopped et ferme le canal parent ; une disparition
brutale est détectée par EOF dans le surveillant. Il arrête l'arbre CPU et
nettoie ses fichiers ; le bail abandonné reste récupérable (maximum trois
tentatives). Une erreur d'inférence, d'absence de modèle, de RAM ou de délai
reste une erreur technique, sans émotion de substitution.

## Protections et concurrence

- Verrou Windows interprocessus du worker, puis verrou du bridge : un seul
  calcul émotion par utilisateur Windows/projet, y compris pendant l'arrêt.
- Deux threads intra-op, un thread inter-op ; priorité réduite si permise.
- Départ différé si un job STT/image non expiré est running dans la même base.
  C'est un contrôle de courtoisie, pas une exclusion globale avec les workers
  existants : une course de démarrage ou une autre base reste possible.
- RAM initiale minimale 3 584 Mio ; réserve disponible pendant calcul 1 536 Mio.
  Plafond privé du groupe observé 3 072 Mio, marge engagée initiale 4 096 Mio
  puis minimale 1 024 Mio, délai modèle 120 s.
- Budget de départ conservateur fondé sur le pic résident d'environ 2 062 Mio
  et la baisse mémoire observés en 2B/2C. Aucun seuil abaissé pour réussir un test.
- Surveillance indépendante toutes les 100 ms de l'arbre Python (incluant le
  redirecteur venv et son enfant) ; arrêt de cet arbre seulement au premier
  dépassement, timeout, disparition parent ou sortie anormalement volumineuse.

Les contrôles sont échantillonnés, pas un plafond dur Windows Job Object ;
une pointe entre deux lectures est possible. Aucune garantie de performances
sous charge Whisper/Stable Diffusion simultanée. Aucun de ces moteurs n'est
démarré, arrêté ou reconfiguré par ce worker. --once peut retourner 0 sans
avoir traité de job (file vide ou déférence), ou après un job en erreur :
consulter le statut PostgreSQL, pas seulement le code de sortie du worker.

## Windows : lancement explicite

Pour les tests actuels, utiliser EXCLUSIVEMENT la recette qui crée son cluster
et ses schémas temporaires, pas une URL récupérée de votre fichier .env :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --emotion-only
# Recette réelle opt-in, après précontrôle mémoire :
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --emotion-real
```

La seconde commande vérifie deux récits fictifs : suggestion et abstention,
statut du job, valeur retenue inchangée et ressources libérées. Elle arrête au
premier échec et n'installe rien. Le test est ignoré par défaut dans pytest.

Commande du worker, uniquement avec une URL explicitement autorisée et un
schéma 0008 déjà validé (la base personnelle n'a PAS été migrée ici) :

```powershell
# Définir DATABASE_URL vers votre base de recette autorisée et migrée.
$env:DATABASE_URL = '<URL PostgreSQL temporaire autorisée>'
$env:EMOTION_ENABLED = '1'
.\.venv\Scripts\python.exe -m backend.app.emotion_worker --once
# Boucle persistante : même commande sans --once ; arrêt par Ctrl+C.
Remove-Item Env:EMOTION_ENABLED
```

Pour créer des demandes exécutables depuis l'API, celle-ci doit aussi avoir
EMOTION_ENABLED=1 lors de la création du snapshot. Aucune demande automatique
à la création/correction d'un rêve ; aucune modification de .env réalisée.
Ne pas lancer ce code sur une base personnelle 0007 : 0008 reste soumise à
autorisation distincte. Aucun alembic upgrade personnel n'a été exécuté.

## Validation et fichiers

Ajouts : emotion_config.py, emotion_runner.py, emotion_worker.py,
scripts/emotion_cpu_bridge.py, scripts/emotion_cpu_child.py,
tests/test_emotion_worker.py, tests/test_emotion_bridge.py,
tests/test_emotion_real.py et ce rapport. Adaptations : emotion_provider.py,
services/emotions.py et scripts/verify_image_jobs.py. Le CSS et les composants
P05/P07/P09 restent préservés ; aucune migration ajoutée ou modifiée.

## Essai réel exécuté sur base temporaire

Les premiers précontrôles à 3 190 puis 3 224 Mio ont empêché le chargement.
Après libération de RAM et fin de la recette de non-régression, le précontrôle
a atteint 3 797 Mio, puis 4 007 Mio avant la recette corrigée. Aucun seuil
n'a été abaissé et aucune application ou service utilisateur n'a été arrêté
par l'assistant.

Un premier essai réel a échoué dans le pont, sans résultat validé. Un contrôle
sans modèle, avec seuil initial volontairement impossible, a reproduit un
arrêt CPython natif 0xC0000005 : _enter_buffered_busy sur stdin à la fermeture.
Le thread daemon détenait le verrou du lecteur tamponné. Correction : lecture
du descripteur avec os.read, sans verrou BufferedReader. Un test de régression
maintient stdin parent ouvert et vérifie la sortie normale après refus mémoire.
Les métriques du bridge sont désormais conservées même en cas de code natif
anormal, sans publier un résultat issu d'un processus défaillant.

Après validation de cette correction sans modèle, une nouvelle recette CPU
a réussi : 1 test, deux jobs fictifs séquentiels, 34,03 s, aucun retry interne.
Le premier récit est un exemple déjà qualifié de satisfaction/joie : suggestion
heureux, choix manuel triste conservé. Le second décrit seulement une valise :
abstention ambiguous, choix NULL conservé. Les deux jobs sont done, les deux
codes de sortie bridge/modèle sont 0. Ce test prouve le raccordement et les
protections, PAS une amélioration de la qualité mesurée en phase 2C.

| Mesure | Suggestion | Abstention |
|---|---:|---:|
| Chargement modèle/tokenizer après imports | 1,733 s | 1,396 s |
| Inférence | 1,304 s | 1,195 s |
| Sous-processus surveillé complet | 20,797 s | 9,468 s |
| Temps CPU déclaré par l'enfant | 11,219 s | 9,516 s |
| Pic résident natif | 2 061,1 Mio | 2 061,4 Mio |
| Pic privé engagé natif | 2 483,4 Mio | 2 484,2 Mio |
| RAM disponible avant | 3 795,8 Mio | 3 906,5 Mio |
| RAM disponible minimale | 1 816,9 Mio | 1 883,5 Mio |
| RAM disponible après | 3 913,8 Mio | 3 879,5 Mio |

La durée complète comprend les imports, vérifications d'empreintes et autres
coûts non inclus dans le chargement/inférence. Les caches et variations système
ne sont pas maîtrisés ; ne pas interpréter l'écart comme un gain algorithmique.
Les deux processus modèle sont absents après arrêt. Les ressources de recette
PostgreSQL et ses schémas sont nettoyés ; les seuls journaux fictifs utiles
sont sous tmp/p08-phase4-real*.json/log, ignorés par Git.

Première non-régression complète : 456 réussis, 1 ignoré (test réel opt-in),
296,14 s, couverture 86,95 %. Les tests ciblés faux moteur/PG sont passés
(90 tests avant les derniers contrôles CLI) ; trois tests de supervision sans
modèle passent en 3,58 s après correction.

Campagne complète FINALE : **460 réussis, 1 ignoré en 243,66 s**, couverture
backend **88,43 %** (seuil 80 %). Le seul ignoré est la recette réelle opt-in,
passée séparément comme décrit ci-dessus. Aucun autre test ignoré ou échec.
La non-régression P03–P09 et les parcours Chrome existants passent ; historique
identique après redémarrage PostgreSQL/Uvicorn temporaires, audio P04 et média
P19 relus, puis purge P19 et refus d'accès vérifiés.
Ruff backend/scripts et git diff --check passent (avertissements LF/CRLF seuls).
Les services de recette sont arrêtés. La migration 0008 n'a pas été appliquée
à la base personnelle ; aucun modèle n'a été téléchargé ou déployé par défaut.

Le premier essai des tests isolés de supervision a aussi rencontré un dossier
pytest global inaccessible ; un basetemp dédié et non partagé a résolu ce
problème de test. Aucun contrôle mémoire ou de droits n'a été contourné.
Aucun commit, push ou changement Jira. Phase 5 soumise à validation.
