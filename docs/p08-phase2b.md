# P08 — Phase 2B : comparaison CPU MiniLM / mDeBERTa

## Verdict

**mDeBERTa est meilleur sur les deux petits jeux, mais aucun des deux moteurs
n'est recommandé pour une intégration en production avec le protocole actuel.**
La reconnaissance du stress progresse ; la classe autre reste à rappel nul.
L'abstention sur une absence d'information émotionnelle reste insuffisante.
Une suggestion révisable et une mention non médicale ne corrigent pas ces
erreurs systématiques. Aucun modèle n'a été branché à l'application.

## Provenance et ressources préalables

Source officielle : https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
Licence MIT vérifiée via les métadonnées officielles avant téléchargement.
Révision immuable : 8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c.
Précontrôle : 3 686,7 Mio RAM disponibles, 68,61 Gio disque libres.
Les sept fichiers sont README.md, config.json, tokenizer.json,
tokenizer_config.json, special_tokens_map.json, added_tokens.json et
model.safetensors. Total 573 992 587 octets, poids 557 652 046 octets.
Tailles vérifiées, empreintes SHA-256 locales conservées ; empreintes LFS
des poids et du tokenizer comparées aux métadonnées officielles de révision.
Pas de .bin, ONNX, spm.model (tokenizer rapide JSON suffisant), code distant
ou troisième modèle téléchargé.

Le venv CPU de phase 2 est réutilisé sans installation ni changement de
dépendance. pip check réussit. Torch 2.7.1+cpu, Transformers 4.57.3,
Tokenizers 0.22.2, Safetensors 0.7.0, psutil 7.1.3, Python 3.12.14.
Le verrou complet de phase 2 reste valable. DebertaV2ForSequenceClassification
et DebertaV2TokenizerFast chargent les fichiers locaux sans SentencePiece.
Poids et inférence FP32, aucun GPU, torch.version.cuda = None.
Entailment est obtenu depuis id2label ; le neutral NLI n'est jamais directement
interprété comme émotion neutre.

Racine locale : %LOCALAPPDATA%\SynthetiseurDeReves\qualification\p08b.
Modèle sous model ; résultats/surveillance sous deberta et minilm.
Le modèle MiniLM et ses résultats de phase 2, sous p08, restent inchangés.
Les inférences utilisent local_files_only=True, trust_remote_code=False,
HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE, CUDA_VISIBLE_DEVICES vide.
Aucun récit envoyé sur le réseau : seul le téléchargement du candidat a
utilisé les services officiels Hugging Face.

## Protocole et indépendance des jeux

Comparaison initiale strictement figée : hypothèses françaises variante 0 de
MiniLM, seuil 0,55, marge 0,05, fragments 300 sous-tokens, moyenne des scores,
minimum cinq sous-tokens, maximum 20 000 caractères, deux threads CPU et seed 42.
Les cinq hypothèses exactes et tous les paramètres sont dans results-b-*.json.
Pas de réglage supplémentaire, entraînement, sélection d'hypothèses ou adaptation.
Les dix récits dev existants n'ont donc pas été réutilisés dans cette phase.
Toutes les paires sont bornées à 512 tokens, truncation=False, aucune suppression
silencieuse. Les limites et réserves restent celles de la phase 2.

Ancien jeu : 15 explicites, 10 ambigus et 5 invalides/incomplets.
Il était déjà connu : **comparaison indicative, pas un test final indépendant**.
Les prédictions et scores MiniLM sur cet ancien jeu sont exactement identiques
à la phase 2, vérification de la compatibilité du chemin de calcul.

Nouveau jeu écrit AVANT toute inférence : 15 explicites (trois par classe),
cinq sans ressenti déterminable et cinq invalides/incomplets, soit 25 cas.
Aucun exemple explicite commun à l'ancien corpus. Aucun de ces nouveaux
exemples n'a réglé les paramètres. MiniLM et mDeBERTa y sont évalués avec le
même protocole, dans des processus distincts et séquentiels.
Corpus synthétique ciblé, annotations proposées par l'assistant, sans seconde
annotation humaine indépendante : cette confirmation n'est pas une preuve
statistique de généralisation. Trois cas par classe rendent le rappel instable.
Une modification future motivée par ces résultats devra employer un autre
jeu tenu à l'écart pour sa confirmation.

## Mesures de qualité

Les abstentions réduisent rappel/exactitude ; précision mise à zéro si aucune
prédiction de la classe. Aucun score NLI n'est une probabilité calibrée du ressenti.

| Jeu | Modèle | Macro-F1 | Exactitude | Abstention |
|---|---|---:|---:|---:|
| reused | minilm | 0.400 | 40.0% | 40.0% |
| reused | deberta | 0.665 | 66.7% | 20.0% |
| confirmation | minilm | 0.250 | 26.7% | 53.3% |
| confirmation | deberta | 0.606 | 60.0% | 20.0% |

### minilm — reused

| Émotion | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| heureux | 1.000 | 1.000 | 1.000 | 3 |
| stressant | 0.000 | 0.000 | 0.000 | 3 |
| neutre | 0.667 | 0.667 | 0.667 | 3 |
| triste | 0.333 | 0.333 | 0.333 | 3 |
| autre | 0.000 | 0.000 | 0.000 | 3 |

Matrice : référence en lignes, prédiction en colonnes.

| Référence | heureux | stressant | neutre | triste | autre | abstention |
|---|---:|---:|---:|---:|---:|---:|
| heureux | 3 | 0 | 0 | 0 | 0 | 0 |
| stressant | 0 | 0 | 1 | 1 | 0 | 1 |
| neutre | 0 | 0 | 2 | 0 | 0 | 1 |
| triste | 0 | 0 | 0 | 1 | 0 | 2 |
| autre | 0 | 0 | 0 | 1 | 0 | 2 |

### deberta — reused

| Émotion | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| heureux | 1.000 | 1.000 | 1.000 | 3 |
| stressant | 1.000 | 0.667 | 0.800 | 3 |
| neutre | 0.750 | 1.000 | 0.857 | 3 |
| triste | 0.667 | 0.667 | 0.667 | 3 |
| autre | 0.000 | 0.000 | 0.000 | 3 |

Matrice : référence en lignes, prédiction en colonnes.

| Référence | heureux | stressant | neutre | triste | autre | abstention |
|---|---:|---:|---:|---:|---:|---:|
| heureux | 3 | 0 | 0 | 0 | 0 | 0 |
| stressant | 0 | 2 | 0 | 0 | 0 | 1 |
| neutre | 0 | 0 | 3 | 0 | 0 | 0 |
| triste | 0 | 0 | 0 | 2 | 0 | 1 |
| autre | 0 | 0 | 1 | 1 | 0 | 1 |

### minilm — confirmation

| Émotion | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| heureux | 1.000 | 0.333 | 0.500 | 3 |
| stressant | 0.000 | 0.000 | 0.000 | 3 |
| neutre | 0.600 | 1.000 | 0.750 | 3 |
| triste | 0.000 | 0.000 | 0.000 | 3 |
| autre | 0.000 | 0.000 | 0.000 | 3 |

Matrice : référence en lignes, prédiction en colonnes.

| Référence | heureux | stressant | neutre | triste | autre | abstention |
|---|---:|---:|---:|---:|---:|---:|
| heureux | 1 | 0 | 0 | 0 | 0 | 2 |
| stressant | 0 | 0 | 1 | 0 | 0 | 2 |
| neutre | 0 | 0 | 3 | 0 | 0 | 0 |
| triste | 0 | 0 | 0 | 0 | 0 | 3 |
| autre | 0 | 0 | 1 | 1 | 0 | 1 |

### deberta — confirmation

| Émotion | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| heureux | 1.000 | 0.667 | 0.800 | 3 |
| stressant | 1.000 | 0.667 | 0.800 | 3 |
| neutre | 0.750 | 1.000 | 0.857 | 3 |
| triste | 0.500 | 0.667 | 0.571 | 3 |
| autre | 0.000 | 0.000 | 0.000 | 3 |

Matrice : référence en lignes, prédiction en colonnes.

| Référence | heureux | stressant | neutre | triste | autre | abstention |
|---|---:|---:|---:|---:|---:|---:|
| heureux | 2 | 0 | 0 | 0 | 0 | 1 |
| stressant | 0 | 2 | 0 | 1 | 0 | 0 |
| neutre | 0 | 0 | 3 | 0 | 0 | 0 |
| triste | 0 | 0 | 0 | 2 | 0 | 1 |
| autre | 0 | 0 | 1 | 1 | 0 | 1 |

## Abstention et erreurs représentatives

Ancien jeu ambigu : MiniLM s'abstient 7/10 fois, avec deux réponses incompatibles
avec nos annotations ; mDeBERTa s'abstient 3/10 fois, avec trois incompatibles.
Cette couverture supérieure n'est pas automatiquement un gain de qualité.

Nouveau jeu émotionnellement indéterminé : MiniLM 3/5 abstentions, mDeBERTa 2/5.
mDeBERTa attribue neutre aux récits où le ressenti est oublié et heureux à la
simple description d'une fontaine. L'absence d'information ne doit pourtant
pas être transformée en émotion : ce garde reste à améliorer.

Invalides/incomplets : 5/5 rejets/abstentions par modèle sur chacun des jeux.
Ces entrées sont rejetées AVANT inférence par la validation ou la règle de
longueur ; cela ne valide pas la compréhension sémantique du modèle.

Erreurs mDeBERTa sur le nouveau jeu :

- Pont qui craque, narrateur affolé et persuadé de mourir : triste, attendu stressant.
- Ville miniature, uniquement de l'étonnement : neutre, attendu autre.
- Matière visqueuse dans le repas, dégoût : triste, attendu autre.
- Destruction de son travail, vive colère sans peur : abstention, attendu autre.

La formulation composite de autre (surprise/curiosité/colère/dégoût) est une
cause possible, pas une cause démontrée. Les négations et le raisonnement sur
le ressenti nécessitent aussi une revue. Aucun réglage n'a été effectué après
lecture des cas finaux. Une adaptation pourrait être étudiée uniquement sur
dev, par exemple des hypothèses élémentaires puis une correspondance vers les
cinq catégories ; son efficacité n'est pas mesurée et n'est pas revendiquée.

## Mesures CPU et mémoire

Même machine et dépendances, processus séquentiels. Temps après imports pour
le chargement ; latences sur les 30 récits explicites des deux jeux, première
inférence incluse. Pas de benchmark à froid ni de test avec charge IA concurrente.

| Mesure | MiniLM | mDeBERTa |
|---|---:|---:|
| Chargement (s) | 1.145 | 1.431 |
| Latence médiane (ms) | 44.809 | 506.408 |
| Latence maximale (ms) | 137.853 | 636.100 |
| Durée sous-processus (s) | 9.3 | 30.2 |
| Pic résident natif (Mio) | 959.4 | 2061.5 |
| Pic privé natif (Mio) | 1743.1 | 2483.9 |
| Pic privé groupe échantillonné (Mio) | 1707.1 | 2241.8 |
| RAM disponible avant (Mio) | 3797.6 | 3590.5 |
| RAM disponible minimale (Mio) | 2849.1 | 1917.8 |
| RAM disponible après (Mio) | 3731.0 | 3771.8 |
| Marge engagée avant (Mio) | 16624.8 | 16513.2 |
| Marge engagée après (Mio) | 16584.3 | 16591.7 |

Surveillant indépendant, échantillonnage 100 ms de tout l'arbre Python,
faulthandler, réserve système 1 536 Mio, limite privée groupe observée
3 072 Mio, délai 600 s, arrêt si marge engagée < 1 024 Mio. Pas de plafond
dur Job Object : une pointe entre deux échantillons est possible. Les pics
natifs peuvent donc dépasser les pics observés du groupe.
Les deux essais sortent avec code 0, sans dépassement ni crash ; tous leurs
PID ont disparu. La RAM revient près du niveau initial avec fluctuations
des autres applications. Aucune application utilisateur fermée.
mDeBERTa laisse seulement environ 382 Mio au-dessus de la réserve au minimum
observé : cela impose de différer un futur travail si la mémoire est trop
basse, pas de diminuer la réserve ou de charger plusieurs moteurs ensemble.

## Reproduction, fichiers et décision

Nouveaux scripts : download_b.py (révision/fichiers explicitement bornés),
confirmation.py, compare_b.py (aucun ajustement), watch_b.py, test_comparison.py,
report_b.py ; artefacts results-b-{minilm,deberta}.json et memory-b-*.json.
download.py et watch.py acceptent désormais une destination explicite ; leurs
valeurs par défaut MiniLM et leurs limites restent inchangées.
Le générateur report_b.py restitue les mesures JSON, sans lancer de modèle.
Les fichiers locaux de modèles et venv ne sont pas dans le dépôt.

Depuis la racine du dépôt, commandes de reproduction explicites, à ne pas
relancer pour une simple lecture des résultats :

```powershell
$p08Root = Join-Path $env:LOCALAPPDATA 'SynthetiseurDeReves\qualification\p08'
$p08Python = Join-Path $p08Root '.venv\Scripts\python.exe'
& $p08Python -m pip check
& $p08Python qualification/p08/download_b.py
& $p08Python qualification/p08/watch_b.py --candidate deberta
& $p08Python qualification/p08/watch_b.py --candidate minilm
```

Les résultats locaux sont sous LOCALAPPDATA/p08b/{deberta,minilm} dans la racine
de qualification indiquée plus haut ; les copies JSON du dépôt ne contiennent
que récits fictifs, paramètres et mesures. Les empreintes des modèles,
tokenizers, corpus et paramètres de référence y sont conservées.

**Choix recommandé : mDeBERTa pour une éventuelle poursuite de qualification,
aucun des deux pour production à ce stade.** Son gain sur stressant/triste
est réel sur ces exemples, mais son rappel autre reste nul et il ne s'abstient
pas assez quand aucune émotion n'est exprimée. Pas de troisième modèle
téléchargé ni de résultat théorique présenté comme mesure.

Aucune base PostgreSQL, route FastAPI, worker, migration, dépendance de
production, récit réel ou CSS modifié. Aucun GPU, fournisseur de classification,
commit, push ou changement Jira. Toute intégration reste soumise à validation.


Validation : 116 tests unitaires réussis en 3,36 s ; Ruff et pip check réussis. Aucun test PostgreSQL/navigateur exécuté : aucune intégration de ces composants ne change dans cette qualification.
