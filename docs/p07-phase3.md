# P07 — Phase 3 : worker GPU et publication privée

## Parcours implémenté

Le worker `backend.app.image_worker` est indépendant de P05 et de FastAPI.
Il réserve exclusivement les jobs image PostgreSQL. Le noyau `prepare_image`
contrôle les versions avant/après calcul ; `image_execution.publish` vérifie
à nouveau propriétaire, snapshot, versions, statut, token et expiration sous
verrous transactionnels du job et du rêve. L'écriture PNG P19, la référence
Media et la terminaison du Job sont coordonnées dans cette transaction.
Une seconde vérification après l'écriture interdit de publier avec un bail
expiré pendant celle-ci. Aucune nouvelle migration : 0007 reste suffisante.

`Job.media_id` représente le résultat pour kind=image (inchangé comme source
audio pour kind=stt). `current_image` choisit le dernier résultat done dont
les versions correspondent encore au récit et à la description. Modifier
P06 ou la description invalide immédiatement cette sélection ; les anciens
médias privés peuvent être conservés, sans redevenir l'image courante.
La consultation du média utilise les routes authentifiées P19 existantes,
notamment `/api/v1/media/{id}/content`, avec contrôle propriétaire. Aucune
route publique ni chemin disque renvoyé, aucune image dans static.

La publication utilise `PrivateStorage.write`, ses validations et clés opaques,
ainsi que `lock_key` commun avec la réconciliation P19. Aucun commit séparé du
service MediaService. En cas d'échec, un nouveau contrôle de référence protège
les fichiers déjà validés si l'accusé de commit a été perdu. Un fichier non
référencé est supprimé ; si DB/FS indisponible ou crash brutal, la réconciliation
P19 existante retire l'orphelin après son délai de grâce. Aucun effacement
automatique de fichier préexistant ni de donnée personnelle dans les tests.

## Isolation GPU et protections

`WatchedSD15Runner` lance uniquement le Python du venv P07 déjà installé.
Le pont `qualification/p07/image_job_bridge.py` réutilise le surveillant natif
qualifié : Job Object Windows, enfant suspendu avant attachement, timer externe,
RAM/VRAM/commit mesurés, arrêt du seul sous-processus. Le worker GPU distinct
`image_job_gpu.py` charge un seul pipeline par job et le détruit à sa sortie.
Pas de modèle conservé dans FastAPI, le worker DB ou entre deux générations.

Paramètres fixes : CUDA FP16, 512 × 512, 20 étapes, seed du snapshot, modèle
local, low_cpu_mem_usage=True, device_map=cuda, filtre + feature_extractor
obligatoires. Aucun téléchargement ; HF_HUB_OFFLINE et TRANSFORMERS_OFFLINE.
Le récit reste français ; seule la description fournie est utilisée, sans
traduction automatique. Un résultat bloqué ne produit aucun fichier PNG.

Limites reprises de la qualification : délai 120 s, plafond privé du processus
7168 Mio, réserve RAM 1536 Mio, VRAM 512 Mio ; démarrage avec RAM/VRAM >=4096 Mio,
inférence avec RAM >=2048 Mio et VRAM >=1536 Mio. Les autres essais gardent leurs
valeurs par défaut. Le parent accorde jusqu'à 45 s supplémentaires au surveillant
pour son observation de récupération et sa sortie, sans prolonger le calcul GPU.

Verrou OS interprocessus image-gpu.lock avant claim et jusqu'à publication ;
le verrou de qualification commun protège également le calcul natif contre
une qualification parallèle. Si un verrou de qualification reste après une
interruption brutale du surveillant, aucune suppression automatique : vérifier
l'absence de processus d'essai avant maintenance explicite.
EOF du pipe du worker applicatif provoque l'arrêt du job GPU par le pont.
Un job abandonné reste récupérable après expiration du bail ; l'ancien token
ne peut publier. Un nouveau worker ne démarre pas un deuxième pipeline natif
pendant le nettoyage du précédent.

Les descriptions transitent par un dossier local éphémère hors Git/OneDrive,
jamais par les arguments ou stdout. Les exceptions GPU Python sont masquées ;
faulthandler reste actif pour les erreurs natives. Le dossier est nettoyé après
lecture du résultat, ou par le pont s'il observe l'arrêt du parent. Une panne
machine peut laisser du staging privé à traiter lors d'une maintenance future.

## Commandes Windows (non exécutées contre la base personnelle)

Ne pas lancer le worker avant validation de la migration 0007 sur cette base.
Le worker ne crée ni ne migre le schéma automatiquement.

```powershell
# Facultatif : emplacement local déjà téléchargé, jamais un identifiant distant.
$env:IMAGE_MODEL_PATH = Join-Path $env:LOCALAPPDATA 'SynthetiseurDeReves\p07-qualification\model'
# Après autorisation de migration et création explicite d'un job :
.\.venv\Scripts\python.exe -m backend.app.image_worker --once
# Ou boucle persistante indépendante :
.\.venv\Scripts\python.exe -m backend.app.image_worker
```

La configuration DATABASE_URL et PRIVATE_MEDIA_ROOT est celle des services
existants. La dépendance GPU aux scripts de qualification est explicite :
ils devront être livrés avec le worker lors du packaging ultérieur. Cette
phase vise Windows ; le surveillant et verrou OS ne sont pas portés Linux.

## Tests réellement exécutés

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py
.\.venv\Scripts\python.exe -m pytest backend/tests/test_image_runner.py -q
.\.venv\Scripts\python.exe -m ruff check backend qualification/p07 scripts/verify_image_jobs.py
```

Campagne PostgreSQL temporaire : **176 réussis, aucun ignoré, 65,48 s**.
Inclut P07 et non-régression P05/P06/P19, publication/lecture PNG synthétique,
contrôle intercomptes, conflit récit/description pendant calcul, annulation,
reprise avec nouveau token, blocage filtre, timeout, manque mémoire simulés,
échec après écriture, commit validé mais accusé perdu et bail expirant à l'écriture.
Les services existants et la base personnelle ne sont pas migrés ou arrêtés.

Suite ciblée du pont après ajout du test d'arrêt du surveillant : **7 réussis,
0,47 s**, sans IA/GPU. Vérifie canal privé, nettoyage, erreurs, fermeture du pipe
sur interruption du parent, exclusion des verrous et arrêt de l'enfant simulé.
Ce dernier test manquait initialement d'un faux module psutil ; injection du
double ajoutée sans installer psutil dans le venv de production. Ruff passe.

**Aucune génération réelle applicative n'a été exécutée.** Les protections
natives et le modèle avaient été qualifiés précédemment ; le nouveau raccordement
complet pont/worker/P19 doit encore être validé lors d'un essai réel autorisé.
Arrêt brutal réel du parent et récupération native n'ont pas été retestés ici.
Aucun résultat de test synthétique n'est présenté comme une image IA réelle.

## Suite après validation

Autoriser séparément migration personnelle et essai réel de bout en bout si
souhaités ; ajouter ensuite routes/API/CSRF et interface P07 selon le périmètre
de phase 4 validé. Pas d'interface, lancement automatique ou modification des
dépendances P05 dans cette phase. Aucun commit, push ou changement Jira.
