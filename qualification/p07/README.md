# Qualification isolée P07 — préparation et mesures

État au 11 novembre 2026 : **préparation effectuée ; un essai optimisé de chargement
seul a échoué par violation d'accès native ; aucune génération lancée**. Aucune route, migration, dépendance
ou configuration P05 n'est modifiée. Le prototype n'accède ni à PostgreSQL, ni au
stockage privé des rêves, ni au `.env`. Il utilise deux descriptions fictives fixes.

## Versions proposées et compatibilité vérifiée

Python 3.12 x64 ; torch **2.7.1+cu118** et torchvision **0.22.1+cu118** depuis
l'index officiel PyTorch CUDA 11.8. Les wheels cp312 Windows x64 de ces deux
versions existent. Le pilote local **551.23** est supérieur au pilote Windows
522.06 associé à CUDA 11.8 GA ; les pilotes NVIDIA sont rétrocompatibles avec
les runtimes CUDA antérieurs. L'indication CUDA 12.4 de nvidia-smi est la capacité
du pilote, pas une obligation d'installer un runtime 12.4. Aucun CUDA Toolkit,
xformers, torchaudio ou changement de pilote n'est nécessaire dans cette proposition.

Les versions image sont épinglées dans les deux fichiers requirements de ce dossier :
Diffusers 0.35.2, Transformers 4.57.6, Accelerate 1.12.0, huggingface-hub 0.36.0,
Safetensors 0.7.0, NumPy 2.2.6, Pillow 11.3.0, Tokenizers 0.22.2 et psutil 7.1.3.
Les métadonnées PyPI ont été consultées : contraintes Python et versions cohérentes,
notamment Transformers exige hub >=0.34,<1.0 et tokenizers >=0.22,<=0.23.0.
Le hub 2.4.0 de P05 reste inchangé : **ne pas installer ces fichiers dans .venv**.

Cette compatibilité est documentaire et vérifiée sur les métadonnées/wheels,
**pas encore validée à l'exécution**. Après accord : pip check, test CUDA FP16,
chargement du pipeline avec son safety checker et génération réelle constitueront
la qualification effective. Les dépendances transitives ne constituent pas encore
un lock complet ; un pip freeze du venv isolé sera conservé après résolution validée.

Sources :

- https://pytorch.org/get-started/previous-versions/#v271
- https://docs.nvidia.com/cuda/archive/11.8.0/cuda-toolkit-release-notes/index.html
- https://pypi.org/project/diffusers/0.35.2/
- https://pypi.org/project/transformers/4.57.6/
- https://pypi.org/project/accelerate/1.12.0/

## Modèle, licence et téléchargement prévu

Modèle : `stable-diffusion-v1-5/stable-diffusion-v1-5`, miroir identifié comme tel
dans sa fiche, et non un dépôt actuellement exploité par Runway.
Révision figée : `451f4fe16113bff5a5d2269ed5ad43b0592e9a14`.

Licence **CreativeML OpenRAIL-M** : l'usage pédagogique envisagé est compatible,
sous réserve de respecter les restrictions d'usage, les notices et les obligations
de redistribution si les poids étaient partagés. Il ne s'agit pas d'un modèle
libre de toute restriction. Aucun poids ne sera ajouté à Git. Le safety checker
du modèle sera conservé et un résultat signalé ne sera pas enregistré en PNG.

Texte de licence : https://compvis-stable-diffusion-license.static.hf.space/index.html
Fiche : https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5

Fichiers de poids sélectionnés, tailles vérifiées dans les métadonnées du dépôt :

| Composant FP16 safetensors | Octets |
| --- | ---: |
| UNet | 1 719 125 304 |
| Encodeur texte | 246 144 864 |
| VAE | 167 335 342 |
| Safety checker | 608 018 440 |
| **Total des poids** | **2 740 623 950** |

Soit **2,74 Go décimaux / environ 2,55 Gio**, auxquels s'ajoutent environ 1,6 Mo
de configurations/tokenizer/model card. Aucune copie FP32, pickle `.bin`, checkpoint
monolithique, ONNX ou variante supplémentaire n'est prévue. Le snapshot utilise une
liste explicite de fichiers et une seule connexion de téléchargement simultanée.
Les empreintes LFS sont vérifiées, puis un manifeste SHA-256 local est conservé.
Un modèle déjà complet est revérifié sans accès réseau ; une interruption autorise
une reprise explicite à la même révision. Aucun téléchargement au chargement.

Le téléchargement du modèle est distinct des wheels de dépendances, qui représentent
également plusieurs Go. Garder **au moins 15 Gio libres** pour venv, cache pip,
modèle et fichiers temporaires. Cette réserve n'est pas une taille de téléchargement
mesurée des dépendances. Dernier disque libre mesuré : **72,59 Gio**.

## Mémoire et protocole

Mesure par le précontrôle : RTX 3060 Laptop **6144 Mio de VRAM**, **4638 Mio libres**,
RAM disponible **3684 Mio**, Python 3.12.14. Ces valeurs sont instantanées.

Marges prudentes du prototype, à confronter aux mesures réelles :

| Mode | RAM disponible exigée avant chargement | VRAM libre exigée |
| --- | ---: | ---: |
| gpu : FP16 complet, batch 1, 512 × 512 | 6144 Mio | 4096 Mio |
| model-offload : composants déplacés CPU/GPU | 8192 Mio | 2048 Mio |
| sequential-offload : dernier recours, plus lent | 8192 Mio | 2048 Mio |

La RAM actuelle ne suffit pas à la marge proposée. Fermer les applications inutiles,
ne pas charger Whisper simultanément et remesurer. Les seuils P05 restent inchangés.
Les seuils du prototype ne garantissent pas l'absence d'OOM ; une erreur impose de
réexaminer les ressources. Aucun repli CPU ou changement de résolution automatique.
SDPA fourni par PyTorch est privilégié ; aucun xformers. Le mode offload n'appelle
pas `.to('cuda')` et consomme davantage de RAM hôte. Le mode séquentiel est beaucoup
plus lent. Une réduction du nombre d'étapes ne constitue pas une solution fiable
au pic mémoire. Les essais sont lancés séparément, jamais simultanément.

Description française : « Une forêt lumineuse avec une lune violette dans le ciel,
illustration onirique. » Équivalent anglais fixé dans le script. Chaque seed est
réinitialisé identiquement pour les deux langues : 42 par défaut, puis éventuellement
42, 1234 et 2026. Paramètres : 20 étapes, guidance 7.5, scheduler PNDM du dépôt,
FP16, 512 × 512, une seule image à la fois. Pas de prompt négatif ni traduction IA.
Une description trop longue est refusée, sans troncature silencieuse.

Le sous-processus a un délai global de 900 s et un verrou commun aux scripts.
Après arrêt brutal, vérifier l'absence du processus avant toute suppression manuelle
du verrou. Les résultats sont conservés dans un dossier unique, sans écrasement.
Le mode génération force les bibliothèques Hugging Face hors ligne.

Mesures prévues, **non encore obtenues** :

- temps de chargement jusqu'au pipeline prêt, CUDA synchronisé ;
- durée de chaque appel génération + filtre de sécurité, CUDA synchronisé ;
- pic mémoire allouée/réservée PyTorch CUDA, par phase ;
- pic RSS du processus et minimum de RAM disponible, échantillonnés toutes les 100 ms ;
- signalement éventuel du filtre, dimensions et versions exactes.

La première génération peut inclure une initialisation à froid : ne pas attribuer
sa différence de temps à la langue. Les pics CUDA PyTorch n'incluent pas toute la
mémoire des autres applications, et les mesures hôte échantillonnées peuvent manquer
un pic très bref. L'identité pixel à pixel entre matériels n'est pas garantie.
Inspecter humainement forêt, lune, couleur violette, ambiance et défauts. Tester les
deux langues car la fiche du modèle annonce une qualité inférieure hors anglais.

## Commandes Windows — À EXÉCUTER SEULEMENT APRÈS ACCORD

Toutes les commandes partent de la racine du projet. Le Python P05 sert uniquement
à créer un nouveau venv, sans copier ses site-packages.

```powershell
$p07Root = Join-Path $env:LOCALAPPDATA 'SynthetiseurDeReves\p07-qualification'
.\.venv\Scripts\python.exe -m venv "$p07Root\venv"
$p07Python = Join-Path $p07Root 'venv\Scripts\python.exe'
$env:PIP_CACHE_DIR = Join-Path $p07Root 'pip-cache'
& $p07Python -m pip install -r qualification/p07/requirements-cuda.txt
& $p07Python -m pip install -r qualification/p07/requirements.txt
& $p07Python -m pip check
& $p07Python qualification/p07/preflight.py --runtime
# Lecture de la licence et accord explicite avant cette commande réseau :
& $p07Python qualification/p07/download_model.py --authorize-download --accept-openrail-license
# Libérer au moins 6 Gio de RAM, puis remesurer avant génération :
& $p07Python qualification/p07/preflight.py
& $p07Python qualification/p07/generate.py --run --mode gpu --seeds 42
```

Deux images sont alors produites **successivement**, FR puis EN ; ce n'est pas un
batch de deux images. Un refus du filtre produit un résultat signalé, sans image
diffusée comme une réussite. Les PNG et `metrics.json` sont dans
`%LOCALAPPDATA%/SynthetiseurDeReves/p07-qualification/results/<identifiant>/`.
Ce dossier ne contient que des données fictives de qualification, aucun rêve privé.

Si OOM malgré les marges, arrêter le processus, libérer la mémoire, puis avec
**8 Gio de RAM libres** relancer séparément :

```powershell
& $p07Python qualification/p07/generate.py --run --mode model-offload --seeds 42
# Dernier recours explicite, plus lent :
& $p07Python qualification/p07/generate.py --run --mode sequential-offload --seeds 42
```

Après succès du premier seed, qualification de qualité plus large :

```powershell
& $p07Python qualification/p07/generate.py --run --mode gpu --seeds 42,1234,2026
& $p07Python -m pip freeze | Set-Content -Encoding UTF8 "$p07Root\resolved-versions.txt"
```

## Vérifications accessibles avant accord

Le précontrôle sans `--runtime` lit les ressources et métadonnées des packages sans
importer Torch/Diffusers. Il est exécutable avec le venv existant : il affiche alors
`isolated_venv=false`, ce qui est normal et ne qualifie pas le moteur.

Les aides CLI, la syntaxe et Ruff ont été vérifiés avant installation. Les scripts
de téléchargement/génération refusent le venv P05. L'état de la préparation initiale
a été remplacé par l'installation autorisée détaillée ci-dessous.

## Installation et téléchargement effectivement vérifiés

L'utilisateur a autorisé la préparation malgré une RAM inférieure à 6 Gio, sans
autoriser de contournement de la garde mémoire pour générer. Le venv séparé a été
créé dans `%LOCALAPPDATA%/SynthetiseurDeReves/p07-qualification/venv`, sans partage
des site-packages P05. Toutes les versions proposées sont installées exactement.
`pip check` réussit dans les deux environnements.

Vérifications réalisées sans chargement de poids :

- CUDA 11.8 disponible, GPU de capacité de calcul 8.6 ;
- allocation FP16 CUDA et multiplication matricielle 16 × 16 réussies ;
- imports StableDiffusionPipeline, CLIPTextModel, CLIPImageProcessor et
  StableDiffusionSafetyChecker réussis ;
- modèle téléchargé à la révision figée : 16 fichiers, dont quatre poids FP16 ;
- tailles et empreintes SHA-256/LFS validées ;
- en-têtes Safetensors lus sans matérialiser les tenseurs : flottants F16, avec
  deux tenseurs d'identifiants I64 attendus ; aucune copie FP32 téléchargée ;
- deuxième vérification complète réussie en mode hors ligne, sans requête réseau.

Le premier accès Hugging Face via requests a rencontré
`CERTIFICATE_VERIFY_FAILED` / `unable to get local issuer certificate`.
La même requête via la confiance Windows réussissait. Un bundle local de certificats
publics a donc été créé à partir de certifi et des autorités Windows approuvées
pour l'authentification serveur, dans `windows-ca-bundle.pem` sous le dossier de
qualification. `REQUESTS_CA_BUNDLE` a été défini uniquement dans le processus de
préparation. La requête HTTPS a alors été validée et le téléchargement a réussi.
Aucun contrôle TLS n'a été désactivé, aucune clé privée exportée, aucun magasin
Windows ni configuration P05 modifié. hf_xet n'a pas été ajouté : le transfert HTTP
standard a suffi. Si une reprise réseau devait être nécessaire sur ce même poste,
réutiliser explicitement ce bundle local ; la génération reste exclusivement hors ligne.

Relevé après préparation initiale : **4285 Mio RAM disponibles**, **4611 Mio VRAM
libres sur 6144 Mio**, **61,79 Gio disque libres**. La garde du mode GPU exige
6144 Mio RAM et 4096 Mio VRAM libres : la RAM manque encore. Aucun modèle n'a été
chargé et aucune génération n'a été lancée ; aucun dossier de résultats n'existe.

Les preuves locales, hors Git/OneDrive, sont conservées sous le même dossier :
`readiness.json`, `resolved-versions.txt` et `model/qualification-manifest.json`.
Le dossier `model/` est prêt et ne doit pas être retéléchargé. Les temps de chargement,
génération et la qualité FR/EN ne sont pas encore mesurés.

Le contrôle final des versions P05 et des empreintes des fichiers de dépendances,
du fournisseur/décodeur Whisper et du service de versionnement P06 est identique
au relevé initial. Git ne montre que le dossier de qualification préparé ; aucun
fichier de production modifié, commit, push ou changement Jira effectué.

## Qualification progressive : surveillance externe et chargement seul

Après autorisation distincte, un mode `load_only.py` a été ajouté exclusivement
dans ce dossier. Il ne modifie pas les seuils des autres modes ni de P05/P06.
Il charge le pipeline avec `device_map="cuda"`, `torch_dtype=float16`,
`low_cpu_mem_usage=True`, fichiers locaux Safetensors et filtre de sécurité requis.
Le worker ne contient aucun prompt ni appel de génération. Aucune image n'est créée.

Protections du parent, sans import de Torch :

- RAM physique/commit via PSAPI, VRAM globale via NVML, lectures disque sur défauts
  de page via PDH ; échantillonnage visé de 100 ms ;
- arrêt sous 1536 Mio de RAM libre ou 512 Mio de VRAM libre ; alerte RAM sous
  2048 Mio ; arrêt si marge de commit système sous 4096 Mio ou utilisation >90 % ;
- arrêt si RAM sous 2048 Mio ET lectures sur défauts de page supérieures au
  maximum de 100/s et quatre fois le niveau haut initial, pendant cinq secondes ;
- délai maximal de 120 s, avec minuterie indépendante de la boucle de mesures ;
- Job Object Windows : plafond de commit privé par processus et global, arrêt
  des seuls processus attachés à la fermeture du job ;
- démarrage suspendu puis attachement au job avant reprise et signal de chargement.
  Deux membres au maximum : redirecteur du venv Windows et véritable Python.
  Aucun processus utilisateur n'est attaché ni arrêté ;
- aucune nouvelle tentative automatique ; mesures de récupération pendant 15 s.

Le plafond de commit privé n'est pas une limite de RSS. Il est calculé à partir
du minimum de RAM initiale, moins la réserve de 1536 Mio et 256 Mio de marge de
surveillance, plus 1024 Mio de commit pour imports/DLL déjà observé, avec un maximum
de 4096 Mio. Le commit global du Job Object dispose de 64 Mio supplémentaires pour
le redirecteur. Ce plafond ne remplace pas la réserve physique surveillée.
Un budget restant de moins de 1024 Mio interdit le lancement.

### Contrôles de phase 1 exécutés

**11 tests unittest réussis en 1,120 s**, avant chargement : réserves RAM/VRAM,
commit, délai, pression de lecture persistante, télémétrie comparée à psutil et
nvidia-smi, absence d'appel de génération dans le worker, arrêt explicite et
kill-on-close de processus factices, allocation mémoire refusée par un plafond
Windows volontairement faible sur un processus factice. Aucun modèle chargé
par ces tests. Ruff passe. La vérification de sortie tient compte du fait qu'un
PID Windows peut subsister tant qu'un handle reste ouvert après terminaison.

### Résultat de l'unique essai de phase 2

Un seul essai a été lancé avec :

```powershell
$p07Root = Join-Path $env:LOCALAPPDATA 'SynthetiseurDeReves\p07-qualification'
& "$p07Root\venv\Scripts\python.exe" qualification/p07/load_only.py --run-load-only
```

Résultat : **chargement non abouti**, sortie native Windows **0xC0000005**
(3221225477, violation d'accès). L'événement Application Error 1000 désigne
**torch_cpu.dll du venv P07**. Vérification des fichiers locaux réussie en
2,341 s ; imports et initialisation CUDA prêts à 9,976 s. Le processus s'est arrêté
à 18,797 s pendant le chargement. La durée d'un chargement complet n'est pas connue.
Aucun événement `pipeline_loaded` n'a été reçu.

| Mesure | Avant (dernier relevé initial) | Pendant | Après récupération |
| --- | ---: | ---: | ---: |
| RAM libre | 4055,23 Mio | minimum 3233,27 Mio | 4357,13 Mio |
| VRAM globale libre | 4701,13 Mio | minimum 4594,83 Mio | 4702,57 Mio |
| Commit système utilisé | 50,41 % | maximum 57,27 % | 50,53 % |
| Lectures disque sur défauts de page | 0/s à cet instant | moyenne 2282,23/s, pic 18822,15/s | 4/s |

Pic résident Windows du sous-processus, redirecteur compris : **1327,30 Mio**.
Pic résident échantillonné : 1182,60 Mio ; mémoire privée engagée échantillonnée
maximale : **2394,01 Mio**, pour un plafond par processus de **3286 Mio**.
Les pics échantillonnés peuvent manquer une allocation très brève. Le rôle éventuel
du plafond de commit dans le crash natif n'est donc pas exclu par ces seules valeurs.
L'intervalle maximal observé entre deux mesures est de 156 ms.

Aucun seuil surveillé franchi et aucun arrêt demandé par le parent : le processus
a quitté par crash natif. Aucun événement système 2004 d'épuisement mémoire dans
la fenêtre examinée. Les lectures sur défauts de page peuvent correspondre aux
fichiers de poids mappés, pas uniquement au fichier d'échange ; leur pic ne prouve
pas une saturation de RAM. La surveillance est restée active.

Le processus a quitté et RAM/VRAM sont revenues près du niveau initial, sans
fermeture d'application utilisateur ni reset global GPU. Les mesures complètes
sont dans `%LOCALAPPDATA%/SynthetiseurDeReves/p07-qualification/load-only/<identifiant>/metrics.json`.
**Aucune image générée et aucune relance effectuée.** Les causes exactes de la
violation d'accès restent à diagnostiquer avant une autre tentative autorisée.
La génération 512 × 512 n'est pas encore qualifiée. Cet échec ne prouve pas une
insuffisance de RAM physique ni la nécessité d'exiger systématiquement 6 Gio libres.

## Diagnostic autorisé — test 1 : PyTorch CPU miniature

Un seul test CPU miniature a été exécuté, indépendamment de Safetensors, Diffusers
et du pipeline SD. Le worker ne les importe pas ; leurs modules sont absents à
la fin de l'essai. GPU masqué dans l'environnement du seul sous-processus et
contexte CUDA non initialisé. Aucun poids chargé, aucune génération, aucun test
2 à 5 exécuté. La version utilisée reste PyTorch 2.7.1+cu118.

Deux tenseurs de huit éléments, en FP16 puis I64, ont été créés sur CPU. Clone,
copie vers un tenseur distinct, lecture complète et scalaire et indépendance du
clone après modification ont été vérifiés. Les données des tenseurs et copies
représentent seulement 240 octets ; le coût mémoire est essentiellement celui
des imports et bibliothèques natives.

Le processus démarre suspendu, est attaché au Job Object puis reçoit le signal
CPU_ONLY. Réserve RAM de 1536 Mio, plafond privé de 3286 Mio, délai de 30 s et
surveillant externe. Contrairement au premier profil, les PID suivis sont ceux
réellement attachés au job, sans agréger d'éventuels rapporteurs WER externes.
Les pics de commit du Job Object sont lus avant sa fermeture.

Résultat : **succès, sortie 0 / 0x00000000, aucun arrêt de protection**.

| Mesure | Résultat |
| --- | ---: |
| Durée totale du sous-processus | 5,094 s, dont 1 s d'observation après les opérations |
| Import PyTorch | 3,440 s |
| Opérations sur tenseurs | 0,005152 s |
| Pic résident Windows, lanceur compris | 328,39 Mio |
| Pic de commit par processus, compteur Windows | 877,14 Mio |
| Pic de commit du job complet | 878,04 Mio |
| RAM libre avant / minimum pendant / après | 4374,68 / 4032,76 / 4409,43 Mio |
| Marge de commit système avant / après | 21191,74 / 21203,75 Mio |

Après 15 s de récupération, les ressources sont proches du niveau initial et aucun
membre ne reste dans le job. `faulthandler` confirmé actif, journal stderr vide
(0 octet), aucun événement Application Error 1000 pour le PID du worker dans
la fenêtre vérifiée. Ruff passe. Les fichiers `events.jsonl`, `faulthandler.log`
et `metrics.json` sont conservés dans le dossier local de qualification
`cpu-mini/a50e5bdae3b8/`, hors Git/OneDrive.

Interprétation : les opérations CPU élémentaires FP16/I64 fonctionnent dans cette
configuration et sous le même plafond privé. Ce test ne valide ni le chargement
Safetensors, ni le transfert CUDA, ni le pipeline complet ; l'échec natif initial
n'est pas résolu. Le prochain essai, Safetensors miniature en mémoire, attend une
autorisation distincte. Aucun fichier de production P05/P06 modifié, aucune
installation, téléchargement, fermeture d'application, commit, push ou action Jira.

## Test 2 — Aller-retour Safetensors en mémoire

Exécuté une seule fois : `safetensors_memory_mini.py --run-memory-roundtrip`
avec le Python du venv de qualification. Le surveillant CPU existant est
paramétrable pour ce worker ; ses limites restent inchangées : réserve RAM
1536 Mio, plafond privé par processus 3286 Mio, délai 30 s.

PyTorch `2.7.1+cu118`, Safetensors `0.7.0` : deux tenseurs CPU de dimensions
2 × 4, FP16 et I64, représentent 80 octets utiles. `safetensors.torch.save`
produit 208 octets en mémoire ; `load` les désérialise. Les valeurs exactes
(y compris des entiers ±2**40), types, dimensions et copies distinctes sont
vérifiés. Aucun fichier Safetensors, mmap, poids du modèle, contexte CUDA ni
module Diffusers n'est utilisé. Les journaux ordinaires restent sur disque.

| Mesure réelle | Résultat |
| --- | --- |
| Code de sortie | 0 / 0x00000000 |
| Durée du sous-processus, observation de 1 s comprise | 3,578 s |
| Imports | 2,088854 s |
| Sérialisation / désérialisation | 0,008460 / 0,001515 s |
| Ensemble des opérations et vérifications | 0,011930 s |
| Pic résident Windows, lanceur compris | 328,23 Mio |
| Pic de commit par processus / du job | 877,46 / 878,36 Mio |
| RAM libre avant / minimum pendant / après | 4335,41 / 3967,11 / 4379,06 Mio |
| Marge de commit système avant / après | 21152,86 / 21160,45 Mio |

Faulthandler actif, stderr vide (0 octet), aucune erreur native journalisée,
aucun arrêt de sécurité. Après 15 s de récupération, aucun membre du job ne
subsiste et les ressources sont proches du niveau initial (tolérance 256 Mio).
Rapports : `%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\safetensors-memory-mini\c611657cc0e6\`
(`metrics.json`, `events.jsonl`, `faulthandler.log`). Ruff passe.

Le chemin de sérialisation en mémoire fonctionne pour ces tenseurs synthétiques.
Cela ne valide pas la lecture depuis un fichier, mmap, CUDA ou le pipeline SD.
Le crash initial reste à élucider. Le test 3, petit fichier Safetensors, n'a pas
été exécuté et nécessite une nouvelle autorisation ; les tests 4 et 5 également.

## Test 3 — Petit fichier Safetensors sur CPU

Un seul essai autorisé : `safetensors_file_mini.py --run-file-roundtrip`,
avec le venv de qualification. Deux tenseurs synthétiques FP16/I64 de forme
2 × 4, identiques aux références du test 2, sont enregistrés par `save_file`
dans un dossier temporaire sous le dossier local de qualification, hors Git
et OneDrive. Le fichier fait 208 octets (80 octets de tenseurs).
`safe_open(..., framework="pt", device="cpu")` puis `get_tensor` vérifient
les valeurs exactes, types et dimensions. Les références incluent ±2**40.

| Mesure réelle | Résultat |
| --- | --- |
| Code de sortie | 0 / 0x00000000 |
| Durée du sous-processus, observation de 1 s comprise | 3,593 s |
| Imports | 2,016483 s |
| Écriture du fichier | 0,003666 s |
| Ouverture, lecture et vérifications | 0,004783 s |
| Ensemble des opérations et vérifications | 0,009480 s |
| Pic résident Windows, lanceur compris | 329,40 Mio |
| Pic de commit par processus / du job | 880,29 / 881,20 Mio |
| RAM libre avant / minimum pendant / après | 4331,23 / 4016,16 / 4409,41 Mio |
| Marge de commit système avant / après | 21110,07 / 21162,41 Mio |

Protections inchangées : réserve RAM 1536 Mio, plafond privé par processus
3286 Mio, délai 30 s. Faulthandler actif, stderr vide, aucun arrêt de sécurité.
Le fichier a été supprimé dans le worker et le parent confirme la suppression
du dossier temporaire. Après 15 s, aucun membre du job ne subsiste et les
ressources sont proches du niveau initial (tolérance 256 Mio).
Journaux conservés hors Git/OneDrive dans
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\safetensors-file-mini\7879d285eaaf\`.

Comparaison avec le test 2 : mêmes valeurs, types et dimensions correctement
restitués ; pics résidents proches (329,40 contre 328,23 Mio). Les durées
ne constituent pas un benchmark comparable : les opérations fichier incluent
les vérifications, contrairement au chronométrage de désérialisation seule.

Le crash torch_cpu.dll n'est pas reproduit par cette lecture miniature.
Cela écarte une défaillance systématique de safe_open/get_tensor pour ces
tenseurs et cet environnement, sans exclure un problème lié à de gros fichiers,
à une pression mémoire élevée ou à l'intégration du pipeline. Aucun poids SD
lu, aucun contexte CUDA initialisé, aucun module Diffusers chargé ; tests 4/5
non exécutés. Aucun changement de production, installation ou téléchargement.

## Test 4 — Petits tenseurs CPU/CUDA/CPU

Un seul essai : `cuda_mini.py --run-cuda-mini`, dans le venv de qualification.
PyTorch 2.7.1+cu118, runtime CUDA 11.8, RTX 3060 Laptop. Tenseurs synthétiques
FP16 et I64 de forme 2 × 4, transférés vers CUDA, additionnés de 1 puis rapatriés
sur CPU. Valeurs exactes, dimensions et types vérifiés, y compris entiers ±2**40.
Chaque durée GPU comprend une synchronisation. Aucun poids, Safetensors,
Diffusers ou autre pipeline chargé.

| Mesure réelle | Résultat |
| --- | --- |
| Sortie / durée du sous-processus (observation de 1 s comprise) | 0 / 3,890 s |
| Import PyTorch / initialisation CUDA synchronisée | 1,976528 / 0,196178 s |
| FP16 : CPU→GPU / addition GPU / GPU→CPU | 4,137 / 102,455 / 0,719 ms |
| I64 : CPU→GPU / addition GPU / GPU→CPU | 0,077 / 0,099 / 0,044 ms |
| Pic résident Windows, lanceur compris | 454,07 Mio |
| Pic de commit par processus / du job | 1179,78 / 1180,68 Mio |
| RAM libre avant / minimum pendant / après | 4340,91 / 3877,34 / 4353,07 Mio |
| VRAM libre avant / minimum pendant / après | 4683,48 / 4559,61 / 4693,29 Mio |
| VRAM globale utilisée, maximum échantillonné | 1584,39 Mio |
| Allocateur PyTorch : pic alloué / réservé | 1024 octets / 2 Mio |

La VRAM globale inclut Windows et les autres applications ; son augmentation
maximale par rapport au dernier échantillon initial est de 123,87 Mio, non
une mesure dédiée au seul processus. Les compteurs PyTorch excluent notamment
le contexte CUDA. Ces mesures sur premier appel ne sont pas un benchmark de
débit ; l'addition FP16 inclut le coût du premier lancement de noyau.

Surveillant miniature étendu à la télémétrie native RAM/VRAM existante.
Réserve RAM 1536 Mio, plafond privé 3286 Mio et délai 30 s inchangés ; réserve
VRAM 512 Mio reprise du surveillant de chargement. Arrêt du seul job d'essai
si télémétrie perdue, réserve atteinte ou délai dépassé. Faulthandler actif,
stderr vide, aucun arrêt de sécurité. Après 15 s de récupération, aucun membre
du job ne subsiste, RAM/commit/VRAM proches du niveau initial (tolérance 256 Mio).
Journaux conservés hors Git/OneDrive sous
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\cuda-mini\86dd23ab2736\`.
Ruff passe.

Les transferts et opérations CUDA élémentaires fonctionnent pour cet essai.
Ce résultat ne valide pas le chargement des gros poids ni Diffusers et ne
résout pas le crash initial de torch_cpu.dll. Test 5 non exécuté ; toute suite
attend une nouvelle autorisation. Aucun fichier de production modifié,
installation, téléchargement, commit, push ou changement Jira.

## Test 5 — Intégration Diffusers miniature

Un seul essai `diffusers_mini.py --run-diffusers-mini`, sous le surveillant
miniature existant, sans modifier ses seuils (RAM 1536 Mio, VRAM 512 Mio,
commit privé par processus 3286 Mio, délai 30 s).
Versions vérifiées : PyTorch 2.7.1+cu118, Diffusers 0.35.2, Accelerate 1.12.0.
UNet2DModel à poids aléatoires : 10724 paramètres, un bloc de 8 canaux,
sans attention, entrée/sortie 1 × 4 × 8 × 8. Construction et calcul CPU FP32
validés ; dispatch_model CPU restitue exactement la même sortie.
Placement intégral par dispatch_model sur CUDA puis calcul FP16 validés.
Ce test de placement simple ne valide ni offload, ni device_map d'un pipeline,
ni low_cpu_mem_usage ou chargement depuis un fichier.

| Mesure réelle | Résultat |
| --- | --- |
| Sortie / durée du sous-processus, observation de 1 s comprise | 0 / 10,047 s |
| Imports | 7,260028 s |
| Construction CPU / calcul CPU | 5,393 / 7,505 ms |
| Initialisation CUDA synchronisée | 137,426 ms |
| Placement CUDA FP16 et transfert entrée synchronisés | 5,759 ms |
| Premier calcul GPU synchronisé | 594,475 ms |
| Écart absolu maximal GPU FP16 / CPU FP32 | 0,00197833 |
| Pic résident Windows, lanceur compris | 798,75 Mio |
| Pic commit par processus / du job | 1592,37 / 1593,27 Mio |
| RAM libre avant / minimum / après | 4248,57 / 3469,92 / 4308,72 Mio |
| VRAM libre avant / minimum / après | 4613,82 / 4455,43 / 4616,10 Mio |
| VRAM globale utilisée, maximum échantillonné | 1688,57 Mio |
| Allocateur PyTorch : pic alloué / réservé | 9,179199 / 22 Mio |

Résultats finis, forme et types vérifiés ; comparaison CPU/GPU avec
atol=0,02 et rtol=0,02. Les durées comprennent les coûts des premiers appels.
Les mesures NVML sont globales et échantillonnées, les compteurs PyTorch
excluent notamment le contexte CUDA.
Faulthandler actif, stderr vide, aucun arrêt de sécurité. Après 15 s,
aucun membre du job ne subsiste et RAM/commit/VRAM sont proches de l'état
initial (tolérance 256 Mio). Journaux hors Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\diffusers-mini\660ce5eb429a\`.
Ruff passe.

Les cinq essais miniatures n'ont pas reproduit le crash torch_cpu.dll.
L'intégration élémentaire CPU/CUDA de ces versions fonctionne pour ce cas.
Le chargement des gros poids et la construction complète du pipeline restent
non validés ; le rôle du plafond privé dans le crash initial reste indéterminé.
Aucun modèle préentraîné chargé ni image générée. Aucun nouveau chargement
SD n'a été lancé ; il nécessite une autorisation distincte. Aucun changement
de production, installation, téléchargement, commit, push ou modification Jira.

## VAE réel — Chargement CPU uniquement

Un seul essai autorisé via `vae_cpu_only.py --run-vae-cpu-only` dans le venv
isolé. AutoencoderKL.from_pretrained sur le sous-dossier VAE local, FP16,
variant fp16, use_safetensors=True, low_cpu_mem_usage=True,
local_files_only=True, device_map={"": "cpu"}. Aucun pipeline, CUDA,
encodage, décodage ou calcul sur les poids. Les 83653863 paramètres sont
présents sur CPU en FP16 après chargement.

| Mesure réelle | Résultat |
| --- | --- |
| Code de sortie | 0 / 0x00000000 |
| Durée du sous-processus, observation de 1 s comprise | 8,625 s |
| Imports / appel de chargement VAE | 6,642351 / 0,105474 s |
| Pic résident Windows, lanceur compris | 460,88 Mio |
| Pic natif de commit par processus / du job | 1339,75 / 1340,65 Mio |
| Pic privé échantillonné du job | 1184,74 Mio |
| RAM disponible avant / minimum / après | 4467,87 / 3983,62 / 4527,80 Mio |
| Marge de commit système avant / après | 21087,60 / 21075,97 Mio |

Faulthandler actif, stderr vide, aucune erreur native ni arrêt de sécurité.
Limites inchangées : RAM 1536 Mio, privé par processus 3286 Mio, délai 30 s.
Après 15 s, aucun membre du job ne subsiste et les ressources sont proches
de l'état initial (tolérance 256 Mio). Requête Windows Application 1000/1001
effectuée après l'essai, fenêtre de 10 minutes : aucun événement trouvé.
Journaux hors Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\vae-cpu-only\d8e21d95b144\`.
Ruff passe. Le surveillant renseigne désormais weights_loaded à partir des
événements du worker, pour distinguer cet essai des tenseurs synthétiques.

Le crash torch_cpu.dll ne s'est pas reproduit. Ce résultat valide le chemin
de chargement CPU du VAE sous ce plafond, pas l'ensemble du pipeline ni
le transfert des poids réels sur CUDA. La durée mesure le retour du chargeur,
pas un parcours numérique de toutes les pages des poids mappés ; les valeurs
ne sont pas validées par un calcul. Aucun autre composant testé et aucune
nouvelle tentative. Aucun changement de production, installation,
téléchargement, génération d'image, commit, push ou action Jira.

## CLIP réel — Encodeur de texte sur CPU uniquement

Un seul essai `clip_cpu_only.py --run-clip-cpu-only`, venv isolé.
CLIPTextModel.from_pretrained depuis text_encoder local, dtype=float16,
variant=fp16, use_safetensors=True, local_files_only=True, device_map CPU.
Transformers 4.57.6 accepte mais ignore l'ancien argument low_cpu_mem_usage ;
son chemin standard utilise no_init_weights et init_empty_weights.
Les 123060480 paramètres chargés sont sur CPU en FP16, les buffers sur CPU
(buffers flottants en FP16). Aucun module Diffusers chargé, CUDA non initialisé,
aucune inférence ni autre composant.

| Mesure réelle | Résultat |
| --- | --- |
| Code de sortie / durée du sous-processus | 0 / 8,015 s |
| Imports / appel de chargement CLIP | 6,090678 / 0,066969 s |
| Pic résident Windows, lanceur compris | 444,07 Mio |
| Pic natif commit par processus / groupe | 1539,72 / 1540,62 Mio |
| RAM libre avant / minimum / après | 4512,38 / 4028,57 / 4545,25 Mio |
| Marge de commit système avant / après | 21016,15 / 21091,04 Mio |

Faulthandler actif, stderr vide, aucun arrêt de sécurité. Réserve RAM 1536 Mio,
plafond privé 3286 Mio, délai 30 s inchangés. Après 15 s, aucun membre du job
ne subsiste et les ressources sont proches du niveau initial. Journaux hors
Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\clip-cpu-only\6199ea7c71bc\`.
Le crash natif ne s'est pas reproduit. Le temps de chargement ne représente
pas une validation numérique ou un parcours intégral des pages mappées.
Ruff passe. Aucun autre composant ni essai supplémentaire exécuté, aucun
changement de production, installation, téléchargement, commit, push ou Jira.

## Filtre de sécurité réel — CPU uniquement

Un seul essai `safety_cpu_only.py --run-safety-cpu-only`, venv isolé.
StableDiffusionSafetyChecker.from_pretrained depuis safety_checker local,
dtype=float16, variant=fp16, use_safetensors=True, local_files_only=True,
device_map CPU ; stratégie meta standard de Transformers 4.57.6 (ancien
argument low_cpu_mem_usage=True accepté mais ignoré dans cette version).
Les 303981588 paramètres sont sur CPU en FP16 ; buffers CPU, buffers flottants
FP16. Aucun autre composant instancié, aucune inférence ou analyse d'image,
aucune initialisation CUDA.

| Mesure réelle | Résultat |
| --- | --- |
| Sortie / durée du sous-processus | 0 / 7,718 s |
| Imports / appel de chargement | 5,849221 / 0,142905 s |
| Pic résident Windows, lanceur compris | 446,36 Mio |
| Pic natif commit par processus / du groupe | 2171,64 / 2172,58 Mio |
| Pic privé échantillonné du groupe | 1595,60 Mio |
| RAM libre avant / minimum / après | 4478,73 / 3994,72 / 4517,62 Mio |
| Marge de commit système avant / après | 21038,38 / 21099,12 Mio |

Faulthandler actif, stderr vide, aucun crash ni arrêt de sécurité. Limites
inchangées : RAM 1536 Mio, privé par processus 3286 Mio, délai 30 s.
Après 15 s, aucun membre du job ne subsiste et les ressources sont proches
du niveau initial. Les pics natifs capturent les allocations transitoires
non observées entre deux échantillons. Le temps de chargement mesure le retour
du chargeur, pas une inférence ou un parcours intégral des pages des poids.
Journaux hors Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\safety-cpu-only\841278e5b169\`.
Ruff passe. Crash torch_cpu.dll non reproduit ; UNet et pipeline complet
non testés dans cet essai. Aucun changement de production, installation,
téléchargement, génération d'image, commit, push ou modification Jira.

## UNet réel — Essai CPU unique avec plafond dédié

Un seul essai `unet_cpu_only.py --run-unet-cpu-only`, venv isolé.
UNet2DConditionModel.from_pretrained sur unet local, FP16, variant fp16,
use_safetensors=True, low_cpu_mem_usage=True, local_files_only=True,
device_map CPU. Les 859520964 paramètres sont sur CPU en FP16.
Aucun autre composant chargé, aucune inférence ni initialisation CUDA.

Plafond privé autorisé 4608 Mio appliqué exclusivement au Job Object de cet
essai par argument du surveillant ; valeur par défaut 3286 Mio inchangée.
Le job agrégé garde la marge technique de 64 Mio du lanceur Windows.
Réserve RAM 1536 Mio et délai 30 s inchangés. Précontrôle initial renforcé
à 4096 Mio disponibles pour rester près des conditions de qualification
précédentes : minimum observé 4353,19 Mio, aucun écart important constaté.

| Mesure réelle | Résultat |
| --- | --- |
| Code de sortie / durée du sous-processus | 0 / 8,531 s |
| Imports / appel de chargement UNet | 6,462364 / 0,218114 s |
| Pic résident Windows, lanceur compris | 463,46 Mio |
| Pic privé natif par processus / du job | 4364,62 / 4365,52 Mio |
| Pic privé échantillonné du groupe | 2728,22 Mio |
| RAM disponible avant / minimum / après | 4362,78 / 3941,80 / 4414,77 Mio |
| Marge de commit système avant / après | 20888,08 / 20929,43 Mio |

Faulthandler actif, stderr vide, aucun arrêt de sécurité. Aucun événement
Windows Application Error/WER 1000/1001 trouvé dans la fenêtre de 10 minutes
vérifiée après l'essai. Après 15 s, aucun membre du job ne subsiste et les
ressources sont proches du niveau initial. Journaux hors Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\unet-cpu-only\0c9908022366\`.
Ruff passe.

Le pic natif dépasse l'ancien plafond de 1078,62 Mio et reste à 243,38 Mio
du plafond dédié. Les échantillons de 100 ms manquent ce pic transitoire.
Cela confirme que l'ancien plafond est inférieur au besoin observé de ce
chemin CPU, et renforce l'hypothèse d'un rôle dans le crash initial, sans
prouver la cause de sa violation d'accès dans un pipeline CUDA différent.
Le temps de chargement n'est pas une inférence ni une validation numérique
des poids mappés. Aucun essai multi-composants, aucune nouvelle tentative.
Aucun changement de production, installation, téléchargement, commit, push
ou modification Jira.

## Pipeline complet — Chargement CUDA unique, aucune génération

Un seul essai `pipeline_load_once.py --run-load-once`, avec le venv isolé,
StableDiffusionPipeline.from_pretrained local, torch_dtype=float16,
variant=fp16, use_safetensors=True, local_files_only=True,
low_cpu_mem_usage=True, device_map="cuda" (support vérifié à l'import).
UNet, VAE, text_encoder et safety_checker présents sur cuda:0 en FP16 ;
feature_extractor présent. Aucun appel de pipeline, inférence ou image.

Plafond privé dédié 6144 Mio : budget prudent couvrant base des imports,
poids combinés et allocations transitoires. Défaut des autres tests inchangé
à 3286 Mio. Précontrôles initiaux RAM et VRAM >=4096 Mio ; minimum initial
RAM 4420,63 Mio et VRAM 4723,16 Mio, donc lancement autorisé. Réserve RAM
1536 Mio, réserve VRAM 512 Mio et délai 30 s conservés.

| Mesure réelle | Résultat |
| --- | --- |
| Code de sortie / durée du sous-processus | 0 / 12,469 s |
| Imports / initialisation CUDA / chargement synchronisé | 6,570288 / 0,103782 / 3,882673 s |
| Pic privé natif par processus / du job | 5484,50 / 5485,39 Mio |
| Pic RAM résidente, lanceur compris | 2231,88 Mio |
| RAM disponible avant / minimum / après | 4423,30 / 2380,56 / 4578,86 Mio |
| VRAM libre avant / minimum / après | 4723,16 / 1979,86 / 4732,16 Mio |
| VRAM globale utilisée, maximum échantillonné | 4164,14 Mio |
| Marge de commit système avant / après | 20985,31 / 21054,29 Mio |

Faulthandler actif. Stderr contient la progression et un avertissement
de dépréciation torch_dtype issu de Transformers, aucune erreur native.
Aucun événement Application Error/WER 1000/1001 correspondant au PID trouvé
dans la fenêtre de 10 minutes vérifiée après le test. Aucun arrêt de sécurité.
Après 15 s, aucun membre du job et RAM/commit/VRAM proches du niveau initial.
Journaux hors Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\pipeline-load-once\5c8589b2668c\`.
Ruff passe. Le crash initial n'est pas reproduit avec ce plafond, qui dépasse
de 2198,50 Mio l'ancien plafond au pic réellement observé. Cela renforce
l'hypothèse de sa contribution, sans établir une causalité complète.
Le succès du chargement ne qualifie pas la mémoire ou la stabilité d'une
génération. Aucune seconde tentative ; toute génération attend autorisation.
Aucun changement de production, dépendance, installation, téléchargement,
commit, push ou action Jira.

## Première génération — Deux étapes, sortie bloquée par le filtre

Un seul essai `generate_first_once.py --run-first-generation`, venv isolé,
poids locaux et chargement CUDA FP16 identique à l'essai précédent.
Description fictive française demandée, seed CUDA 42, 512 × 512, une image,
num_inference_steps=2, scheduler local inchangé, filtre conservé.
Plafond privé dédié 7168 Mio pour laisser une marge aux allocations
d'inférence au-delà du pic de chargement de 5484,50 Mio ; délai total 120 s
bornant imports, chargement et premiers noyaux GPU. Défauts des autres tests
3286 Mio/30 s inchangés. Réserves surveillées RAM 1536 Mio, VRAM 512 Mio.

Précontrôle favorable : RAM 4499,57 Mio, VRAM libre 4710,66 Mio. Juste avant
inférence : RAM 4003 Mio et VRAM libre CUDA 2460 Mio, au-dessus des marges
additionnelles de lancement 2048/1536 Mio. Les mesures NVML globales et CUDA
ne sont pas identiques ; les séries NVML servent aux minima avant/pendant/après.

| Mesure réelle | Résultat |
| --- | --- |
| Code de sortie du worker / durée | 1 / 10,656 s |
| Imports / chargement synchronisé | 6,387366 / 1,911328 s |
| Inférence complète synchronisée, filtre inclus | 1,156667 s |
| Pic privé natif par processus / du job | 5669,74 / 5670,64 Mio |
| Pic RAM résidente Windows, lanceur compris | 2214,30 Mio |
| RAM disponible avant / minimum / après | 4499,57 / 2508,84 / 4699,15 Mio |
| VRAM libre avant / minimum / après | 4710,66 / 836,05 / 4720,73 Mio |
| VRAM utilisée globale, maximum échantillonné | 5307,95 Mio |
| Pic allocateur PyTorch alloué / réservé | 3244,00 / 3744 Mio |

Les deux étapes ont fini, mais nsfw_content_detected=[True]. Diffusers a
remplacé la sortie par une image noire. Le script a levé QualificationError
et n'a enregistré aucun PNG ; format et dimensions du fichier final ne sont
donc pas validés. L'objectif d'une image exploitable non bloquée n'est pas
atteint. On ne peut conclure sur le contenu original ni affirmer un faux
positif sans autre essai autorisé. Aucun filtre contourné, aucun retry.

Faulthandler actif ; journal avec progression, avertissement torch_dtype,
message du filtre et exception contrôlée, sans erreur native. Aucun événement
Application Error/WER 1000/1001 correspondant au PID dans la fenêtre vérifiée
de 10 minutes. Aucune limite atteinte. Après 15 s, aucun membre du job,
RAM/commit/VRAM proches de l'état initial. Journaux hors Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\first-generation\aff81bb98d66\`.
Ruff passe. Aucun autre essai, aucune installation, téléchargement ou API
externe. Aucun fichier de production modifié, commit, push ou action Jira.

## Génération française — Essai unique à 20 étapes

`generate_twenty_once.py --run-twenty-generation` exécuté une seule fois,
CUDA FP16, modèle local, 512 × 512, une image, seed 42, même description
française et filtre de sécurité actif. Aucun autre essai ni comparaison anglais.
Protections conservées : plafond privé dédié 7168 Mio, réserve RAM 1536 Mio,
VRAM 512 Mio, délai 120 s. Précontrôle initial RAM/VRAM >=4096 Mio passé ;
avant inférence RAM 4123 Mio et VRAM CUDA libre 2474 Mio, marges suffisantes.

| Mesure réelle | Résultat |
| --- | --- |
| Sortie / durée totale du sous-processus | 0 / 13,781 s |
| Imports / chargement synchronisé | 6,346520 / 1,906758 s |
| Génération synchronisée, filtre inclus | 3,291049 s |
| Pic privé natif par processus / groupe | 5648,33 / 5649,23 Mio |
| Pic résident Windows, lanceur compris | 2233,34 Mio |
| RAM disponible avant / minimum / après | 4675,29 / 2485,53 / 4689,21 Mio |
| VRAM libre avant / minimum / après | 4694,35 / 829,30 / 4698,98 Mio |
| Pic VRAM utilisée global échantillonné | 5314,70 Mio |
| Pic alloué / réservé PyTorch | 3246,85 / 3728 Mio |

nsfw_content_detected=[False]. PNG enregistré, format et dimensions 512 × 512
vérifiés par Pillow, puis inspection visuelle : forêt brumeuse, sol violet,
grande lune violette non nettement représentée. Image exploitable techniquement,
fidélité partielle au prompt. Fichier hors Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\twenty-generation\eebb978c5628.png`.
Journaux : même dossier, sous-dossier `faaf1efff2d0`.
Faulthandler actif, aucun crash natif ni arrêt de sécurité ; journal de
progression et avertissement torch_dtype. Après 15 s, aucun membre du job
ne subsiste et RAM/commit/VRAM proches du niveau initial. Ruff passe.
Aucun téléchargement, installation, API externe, changement de production,
commit, push ou modification Jira. Aucun essai supplémentaire lancé.

## Comparaison anglaise — Un seul essai à paramètres identiques

`generate_english_once.py --run-english-generation` : modèle local CUDA FP16,
20 étapes, seed 42, 512 × 512, une image, filtre actif. Prompt exact :
"An enchanted forest under a large violet moon, dreamy atmosphere."
Protections inchangées : 7168 Mio privé, réserve RAM 1536 Mio, VRAM 512 Mio,
délai 120 s. Précontrôles initiaux et pré-inférence passés.

| Mesure réelle | Français | Anglais |
| --- | --- | --- |
| Code de sortie | 0 | 0 |
| Chargement synchronisé | 1,906758 s | 1,860241 s |
| Génération, filtre inclus | 3,291049 s | 3,284678 s |
| Durée du sous-processus | 13,781 s | 13,875 s |
| Pic privé natif par processus | 5648,33 Mio | 5651,04 Mio |
| Pic résident Windows, lanceur compris | 2233,34 Mio | 2210,70 Mio |
| RAM libre minimale | 2485,53 Mio | 2442,07 Mio |
| VRAM libre minimale globale | 829,30 Mio | 839,83 Mio |
| Filtre : sortie bloquée | Non | Non |

PNG anglais sauvegardé et vérifié par Pillow (PNG, 512 × 512), puis inspecté :
`%LOCALAPPDATA%\SynthetiseurDeReves\p07-qualification\english-generation\c3a52ae2229a.png`.
Journaux dans le sous-dossier `40df5518b51a`. Aucun crash natif ni arrêt de
sécurité ; faulthandler actif. Après 15 s, aucun membre du job et ressources
proches de l'état initial : RAM 4714,96 Mio, VRAM libre 4705,88 Mio.

Comparaison visuelle : forêt et ambiance brumeuse/onirique dans les deux.
Français : sol violet, lune peu identifiable. Anglais : lune bien visible
au-dessus du chemin, mais pâle jaunâtre, pas violette ; violet surtout sur
le sol et dans l'atmosphère. Anglais plus fidèle sur cette paire pour la
présence de la lune, sans respecter tous les attributs. Ce seul couple
ne prouve pas une supériorité générale ; les temps sont pratiquement égaux.
Recommandation provisoire pour la suite : prompt anglais, récit français
préservé, sans implémenter de traduction à cette étape. Ruff passe.
Aucun autre essai, téléchargement, API externe, changement de production,
commit, push ou action Jira.
