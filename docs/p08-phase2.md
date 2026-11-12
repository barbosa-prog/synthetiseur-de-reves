# P08 — Phase 2 : qualification CPU réelle de MiniLM multilingue

## Verdict

Le candidat fonctionne techniquement sur CPU, hors ligne, mais **n'est pas
retenu pour la production à ce stade**. Sur 15 récits explicites réservés :
macro-F1 0,40, exactitude 40 %, abstention 40 %. Rappel nul pour stressant et
autre. Il attribue également neutre à un récit explicitement dépourvu
d'information sur le ressenti. Cela ne répond pas suffisamment au besoin P08,
même avec un choix révisable et un avertissement non médical.

Ces résultats concernent ce petit corpus et cette méthode NLI ; ils ne prouvent
pas qu'aucun réglage ou entraînement de MiniLM ne pourrait fonctionner.
Ils ne permettent pas non plus d'affirmer qu'un autre moteur serait meilleur.
Recommandation : qualifier un autre candidat multilingue NLI, par exemple
mDeBERTa, uniquement après autorisation distincte et précontrôle mémoire.
Ne pas intégrer ce candidat tel quel ni abaisser les seuils sur le jeu final.

## Provenance, fichiers et isolation

Modèle : `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`.
Révision immuable : `0a71e92a985b6e1ad1828cf67ce9c459639c1dca`.
Licence déclarée MIT dans les métadonnées du dépôt officiel, vérifiée avant
les poids. La fiche décrit un modèle NLI multilingue, pas un modèle spécialisé
dans les émotions de rêves.

Sources officielles consultées :

- https://huggingface.co/MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli
- https://huggingface.co/MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli/tree/0a71e92a985b6e1ad1828cf67ce9c459639c1dca
- https://pytorch.org/get-started/previous-versions/

Téléchargement explicite limité à README.md, config.json, tokenizer.json,
tokenizer_config.json, special_tokens_map.json et model.safetensors.
Poids : 427 997 022 octets ; pas de .bin, ONNX, autre modèle ni code distant.
Les tailles sont comparées aux métadonnées de la révision ; le SHA-256 LFS des
poids et du tokenizer est vérifié. Chaque fichier dispose aussi d'un SHA-256
local dans le manifeste conservé dans results.json. Les petits fichiers non-LFS
ont une empreinte locale, sans prétendre à une comparaison SHA-256 LFS.

Racine locale hors Git/OneDrive :
`%LOCALAPPDATA%\SynthetiseurDeReves\qualification\p08`.
Venv distinct : `.venv` dans cette racine ; modèle : `model`.
Aucune dépendance P05/P07 ou de production modifiée. Aucune donnée PostgreSQL.
PyTorch 2.7.1+cpu : torch.version.cuda = None ; paramètres exclusivement CPU.
HF_HUB_OFFLINE et TRANSFORMERS_OFFLINE actifs pendant l'évaluation,
local_files_only=True, trust_remote_code=False, Safetensors uniquement.

Versions principales : Python 3.12.14, Transformers 4.57.3, Tokenizers 0.22.2,
Safetensors 0.7.0, psutil 7.1.3. Toutes les dépendances résolues sont dans
qualification/p08/requirements-lock.txt ; pip check a réussi.
Les versions exactes du tokenizer sont liées à la même révision et aux
empreintes de ses fichiers, pas seulement à la version de la bibliothèque.

## Corpus et séparation

40 récits entièrement fictifs dans qualification/p08/dataset.py :

- 25 explicites, cinq par catégorie : deux par classe pour réglage (10),
  trois par classe pour évaluation finale (15).
- 10 ambigus : émotions mélangées, négations, récit visuel sans ressenti,
  différence entre les émotions des autres et celles du narrateur.
- 5 incomplets/invalides : vide, espaces, fragment « Je… », « Une porte. »,
  dépassement de la limite de 20 000 caractères.

Annotations de référence proposées humainement avant les inférences, sans
utiliser de rêves réels. Pas de double annotation indépendante ; le corpus
est petit et artificiel, trois exemples finaux par classe seulement.
Les cas ambigus ont des ensembles de réponses acceptables, éventuellement
vides ; l'abstention est acceptable dans ce sous-ensemble exploratoire.
Ils ne sont pas inclus dans le macro-F1 des cas explicites.

## Méthode figée avant les cas finaux

Deux variantes françaises d'hypothèses comparées sur les seuls dix cas dev.
Grille : seuil du meilleur score 0,35/0,45/0,55 ; marge entre les deux meilleurs
scores 0,05/0,15/0,25. Choix par macro-F1 dev, égalité départagée selon l'ordre
fixé de la grille. Aucune optimisation sur les cas finaux, ambigus ou incomplets.
Cette sélection sur dix cas reste fragile et n'est pas une calibration.

Variante retenue, dans l'ordre des catégories :

1. Ce récit exprime de la joie et du bonheur.
2. Ce récit exprime de la peur et du stress.
3. Ce récit exprime une absence d'émotion particulière.
4. Ce récit exprime de la tristesse.
5. Ce récit exprime une autre émotion : surprise, curiosité, colère ou dégoût.

Score : softmax des logits entailment en compétition entre les cinq hypothèses
(classification NLI single-label), avec vérification de id2label. Ce n'est pas
une probabilité calibrée du ressenti. Seuil retenu 0,55 ; marge 0,05.
Abstention si seuil ou marge non atteint. Entrées invalides rejetées avant
inférence ; moins de cinq sous-tokens : information insuffisante sans modèle.
Cette règle de longueur est une heuristique explicite, insuffisante pour
détecter toutes les absences d'information émotionnelle.

Seed 42, FP32 CPU, deux threads intra-op et un inter-op, mode eval/inference,
algorithmes déterministes. L'empreinte du jeu est dans results.json.

## Résultats finaux mesurés

| Classe | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| heureux | 1,000 | 1,000 | 1,000 | 3 |
| stressant | 0,000 | 0,000 | 0,000 | 3 |
| neutre | 0,667 | 0,667 | 0,667 | 3 |
| triste | 0,333 | 0,333 | 0,333 | 3 |
| autre | 0,000 | 0,000 | 0,000 | 3 |

Précision mise à zéro par convention lorsqu'aucune prédiction de la classe.
Macro-précision et macro-rappel : 0,40 ; macro-F1 : 0,40.
Six bonnes réponses sur quinze ; six abstentions et trois mauvaises réponses.
Exactitude des seules réponses émises : 6/9 = 66,7 %, couverture 60 %.
Les abstentions comptent dans le support et réduisent donc le rappel.

Matrice : lignes = référence, colonnes = prédiction.

| Référence | heureux | stressant | neutre | triste | autre | abstention |
|---|---:|---:|---:|---:|---:|---:|
| heureux | 3 | 0 | 0 | 0 | 0 | 0 |
| stressant | 0 | 0 | 1 | 1 | 0 | 1 |
| neutre | 0 | 0 | 2 | 0 | 0 | 1 |
| triste | 0 | 0 | 0 | 1 | 0 | 2 |
| autre | 0 | 0 | 0 | 1 | 0 | 2 |

Erreurs représentatives :

- « Les murs se refermaient et je cherchais désespérément une sortie,
  angoissé. » : neutre au lieu de stressant (score maximal environ 0,556).
- « Un incendie approchait ; je tremblais de terreur sans pouvoir
  m'enfuir. » : triste au lieu de stressant.
- « Une odeur infecte envahissait la cuisine et je ressentais du dégoût. » :
  triste au lieu de autre.
- Le récit explicite de chagrin lié à une lettre d'un proche disparu :
  abstention au lieu de triste.

Ambigus : 7/10 abstentions ; trois réponses neutre dont deux incompatibles
avec nos annotations : joie/chagrin mélangés, et grande lune dans une chambre
avec ressenti explicitement oublié. Le troisième, négation de la peur chez le
narrateur, était acceptable. Pas de conversion systématique en neutre, mais
la protection contre une absence d'information demeure insuffisante.

Incomplets/invalides : 5/5 abstentions/rejets, aucune inférence pour ces cinq
cas. Ce résultat mesure le garde d'entrée, pas une compétence du modèle.

## Temps et mémoire réels

Précontrôle initial : 3 083 Mio RAM disponibles, 16 475 Mio de marge de mémoire
engagée Windows, 70,9 Gio libres sur disque.

Deux passages CPU ont été réalisés. Le premier a réglé les paramètres sur dev
puis évalué le jeu final. Le relevé par processus suivait initialement le
redirecteur du venv Windows (4,4 Mio seulement) : ces pics sont INVALIDES et
ne sont pas retenus. Le surveillant a été corrigé pour suivre l'arbre Python.

Le second passage utilise --frozen : aucun réglage dev, paramètres inchangés.
Toutes les prédictions et tous les scores finaux sont identiques au premier.
Il vérifie la répétabilité sur cette machine et mesure les ressources ; ce
n'est pas une seconde évaluation indépendante ni une garantie intermachines.

| Mesure du second passage | Valeur |
|---|---:|
| Chargement modèle + tokenizer, après imports | 1,069 s |
| Inférence explicite courte, médiane | 42,0 ms |
| Inférence explicite courte, maximum | 146,7 ms |
| Sous-processus complet, imports et contrôle long inclus | 10,135 s |
| Pic résident natif du processus Python | 960,8 Mio |
| Pic privé engagé natif du processus Python | 1 744,5 Mio |
| Pic privé du groupe observé par échantillonnage | 1 371,4 Mio |
| RAM système disponible avant / minimum / après | 3 695,5 / 2 725,9 / 3 691,3 Mio |
| Marge engagée Windows avant / après | 16 728,9 / 16 742,2 Mio |
| Code de sortie / processus terminé | 0 / oui |

Les pics natifs peuvent être supérieurs au pic observé du groupe : mesure
toutes les 100 ms, allocations transitoires possibles. Ce n'est pas une
contradiction, ni un plafond dur Windows Job Object. Le surveillant externe
arrête seulement son arbre d'essai : réserve RAM 1 536 Mio, limite privée
observée 3 072 Mio, marge engagée minimale 1 024 Mio, délai 600 s.
Aucun arrêt de protection, crash ou GPU. Trois secondes après la sortie,
la RAM revient à environ 4,3 Mio du niveau initial, avec fluctuations système.
Les temps reflètent notamment les caches disque : pas un benchmark de démarrage
à froid ni une mesure de charge simultanée avec Whisper/Stable Diffusion.

## Récits longs et limites

Tokenizer : XLMRobertaTokenizerFast, model_max_length 512 ; configuration du
modèle : max_position_embeddings 514 (positions internes, pas une permission
d'envoyer une paire de 514 tokens).
Les hypothèses occupent aussi une partie de la fenêtre.
Découpage explicite du récit en fragments de 300 sous-tokens, sans suppression
de fin, moyenne des scores par fragment. Chaque paire est vérifiée <= 512,
truncation=False ; un dépassement provoque une erreur, jamais un tronquage.
Un cas technique supplémentaire de 11 000 caractères / 2 200 sous-tokens a
été traité en huit fragments en 2,026 s, avec abstention finale.
Ce cas répétitif n'appartient pas aux 40 annotations et ne valide pas la
fidélité sur de vrais longs récits. La moyenne peut diluer une émotion rare,
et une frontière de fragment peut casser le contexte ou une négation.
La limite applicative de 20 000 caractères est contrôlée avant tokenisation.

Le tokenizer a émis un avertissement sur les 2 200 tokens avant découpage :
ils n'ont pas été envoyés ensemble au modèle ; les huit paires sont bornées.
Transformers signale aussi la dépréciation de torch_dtype ; aucun échec.

## Reproduction Windows et livrables

Scripts, corpus, résultats synthétiques et versions verrouillées :
qualification/p08/{dataset.py,download.py,evaluate.py,watch.py,test_protocol.py,
requirements.txt,requirements-lock.txt,results.json,memory.json}.
Les poids et l'environnement restent exclusivement dans LOCALAPPDATA.
Les journaux, échantillons mémoire, paramètres figés et premier passage restent
aussi dans cette racine locale ; results.json en conserve les paramètres.

```powershell
$p08Root = Join-Path $env:LOCALAPPDATA 'SynthetiseurDeReves\qualification\p08'
.\.venv\Scripts\python.exe -m venv (Join-Path $p08Root '.venv')
$p08Python = Join-Path $p08Root '.venv\Scripts\python.exe'
& $p08Python -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
& $p08Python -m pip install -r qualification/p08/requirements-lock.txt
& $p08Python -m pip check
# Téléchargement explicite uniquement ; réutilise les fichiers déjà vérifiés.
& $p08Python qualification/p08/download.py
# Qualification complète : réglage sur dev seulement, puis gel et cas finaux.
& $p08Python qualification/p08/watch.py
# Répétition sans réajustement, après une qualification complète :
& $p08Python qualification/p08/watch.py --frozen
```

Ne pas relancer ces commandes pour une simple utilisation du rapport.
33 tests déterministes de protocole et de phase 1 P08 réussis (0,33 s).
Sélection élargie finale protocole/P08/texte/P09/image/STT/API : 114 tests
réussis en 2,83 s. Aucun processus de qualification restant.
Ruff backend/scripts/qualification P08 réussi, pip check réussi.
Ces contrôles ne remplacent pas une recette d'intégration future.

Aucune route FastAPI, worker, P06, P09, CSS, dépendance de production ou
migration modifiée. Aucune base personnelle ouverte. Aucun récit envoyé à un
fournisseur, aucun téléchargement d'autre modèle, aucun commit/push/Jira.
La phase 3 et tout autre candidat attendent validation.
