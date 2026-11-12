# P08 — Phase 2C : fiabilité de mDeBERTa, CPU local

## Périmètre et définition métier

Uniquement qualification sur récits fictifs. Modèle déjà téléchargé
MoritzLaurer/mDeBERTa-v3-base-mnli-xnli, révision
8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c, licence MIT vérifiée en phase 2B.
Aucun téléchargement, installation, entraînement, GPU ou appel de classification
externe dans cette phase. Même venv CPU et dépendances qu'en phase 2B.

Les classes représentent le ressenti du narrateur : heureux = joie/bonheur ;
stressant = peur/stress/angoisse ; triste = tristesse/chagrin ; neutre =
neutralité ou absence de ressenti EXPLICITEMENT rapportée. Une absence
d'information n'est pas neutre. Autre exige une émotion identifiable hors
des quatre premières ; ce n'est ni un défaut, ni une abstention.
Pour les récits indéterminables, ambigus ou multi-émotions sans dominante,
l'abstention est attendue dans ce contrat à une seule catégorie.

Analyse des phases précédentes : une seule hypothèse composite pour autre
semblait mal adaptée à colère/dégoût/surprise/curiosité ; le score relatif entre
cinq propositions pouvait imposer une émotion malgré l'absence d'information.
Ces hypothèses de cause ont motivé la stratégie, sans prouver le mécanisme
interne du modèle. Les anciens cas de test n'ont pas été réutilisés pour choisir
les formulations ou seuils.

## Corpus et gel

DEV : les dix cas dev initiaux + dix nouveaux explicites (quatre par classe
au total), huit indéterminables, quatre ambigus et quatre multi-émotions,
soit 36 cas. Aucun cas des anciens tests des phases 2/2B.

TEST : 83 nouveaux cas, écrits avant les inférences : 50 explicites (dix par
classe), 12 indéterminables, huit ambigus, huit multi-émotions et cinq invalides.
Les invalides standards peuvent être communs à des recettes précédentes,
mais aucun récit non invalide n'est repris des tests précédents ou de DEV.
Ils ne servent jamais à régler le modèle. Les hypothèses/seuils restent
identiques pour les 83 cas ; pas de nouvelle tentative ni d'optimisation
après observation de leurs résultats.

Le jeu est synthétique et annoté par l'assistant, sans annotation indépendante
par plusieurs personnes. Les explicites contiennent souvent le vocabulaire
du ressenti : résultat potentiellement optimiste face à des rêves implicites.
Les négatifs sont volontairement difficiles. Ce n'est pas un échantillon
représentatif des utilisateurs ni une validation clinique.
Empreintes code/corpus gelées après DEV et vérifiées avant TEST ; protocole
d'acceptation exploratoire également sauvegardé avant le premier cas TEST.

## Méthode candidate

Deux formulations françaises de huit hypothèses élémentaires, complétées par
trois contrôles NLI : information absente, incertitude et pluralité émotionnelle.
Score de chaque hypothèse = entailment dans le softmax des trois sorties NLI,
pas le softmax en compétition entre cinq émotions utilisé par la référence.
Ces scores ne sont pas calibrés comme probabilités du ressenti.
Les quatre premières hypothèses correspondent aux quatre catégories principales ;
autre reçoit le maximum des quatre émotions restantes, uniquement si les
contrôles, seuil et marge autorisent une suggestion. Un faible score n'est
jamais converti en autre.

Même fenêtre maximale de 512 tokens et fragments de 300 sous-tokens que la
référence, moyenne par hypothèse sur les fragments, aucune troncature
silencieuse. Micro-lots d'au plus cinq paires, FP32 CPU, seed 42, deux threads,
modèle eval/inference, algorithmes déterministes, tokenizer rapide local.
Les effets du découpage sur de longs récits ne sont pas requalifiés ici.

Grille DEV : deux formulations ; seuil émotion 0,45/0,60/0,75/0,85 ; marge
0,05/0,15/0,25 ; seuil commun des trois contrôles 0,4/0,6/0,8 ; garde lexical
optionnel. Soit 144 configurations, calculées depuis les sorties DEV mises
en cache, pas 144 entraînements. Priorité préfixée : minimiser les suggestions
sur les négatifs DEV puis maximiser le macro-F1 explicite ; ordre de grille
pour départager. Le garde lexical, construit sur le domaine et DEV, n'est pas
un classifieur ; il n'est pas utilisé si la sélection choisit false.

Critères de déploiement exploratoires déclarés avant TEST, distincts des
critères Jira : macro-F1 >= 0,75 ; rappel de chaque classe >= 0,50 ; qualité
des suggestions explicites >= 90 % ; couverture explicite >= 60 % ; au plus
une suggestion sur les 12 indéterminables ; abstention >= 75 % pour ambigu
et multi-émotions. Ces seuils ne sont pas une certification de sécurité.


### Paramètres retenus sur DEV

```json
{
  "variant": 1,
  "threshold": 0.45,
  "margin": 0.05,
  "gate_threshold": 0.4,
  "lexical_guard": false
}
```
DEV : macro-F1 0.280, couverture 25.0%, qualité des suggestions explicites 80.0%, suggestions sur négatifs : 0.

Hypothèses retenues (ordre contractuel) :

- heureux : La personne qui raconte son rêve se sent heureuse.
- stressant : La personne qui raconte son rêve se sent effrayée ou anxieuse.
- neutre : La personne qui raconte son rêve décrit explicitement son indifférence émotionnelle.
- triste : La personne qui raconte son rêve se sent triste ou éprouve du chagrin.
- colere : La personne qui raconte son rêve est furieuse.
- degout : La personne qui raconte son rêve est écœurée.
- surprise : La personne qui raconte son rêve est étonnée.
- curiosite : La personne qui raconte son rêve est curieuse.

Contrôles :

- Le récit ne précise pas ce que ressent la personne qui raconte son rêve.
- La personne qui raconte son rêve hésite et ne sait pas quelle émotion elle ressent.
- La personne ressent plusieurs émotions fortes sans émotion dominante.

## Résultats du nouveau TEST

La référence est mDeBERTa sans adaptation : protocole phase 2B, hypothèses variante 0, seuil 0,55 et marge 0,05. Les méthodes sont alternées par cas sur le même modèle résident.

| Mesure explicite | Référence | Candidate |
|---|---:|---:|
| Macro-F1 | 0.707 | 0.277 |
| Exactitude (abstentions = échecs) | 74.0% | 18.0% |
| Abstention | 6.0% | 82.0% |
| Couverture explicite | 94.0% | 18.0% |
| Qualité des seules suggestions explicites | 78.7% | 100.0% |

Qualité globale des suggestions (inclut les suggestions injustifiées sur négatifs, jamais les abstentions comme succès) : baseline 37/68 = 54.4% ; candidate 9/9 = 100.0%.


### baseline

| Classe | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| heureux | 0.900 | 0.900 | 0.900 | 10 |
| stressant | 0.818 | 0.900 | 0.857 | 10 |
| neutre | 0.714 | 1.000 | 0.833 | 10 |
| triste | 0.727 | 0.800 | 0.762 | 10 |
| autre | 1.000 | 0.100 | 0.182 | 10 |

Matrice : référence en lignes, prédiction en colonnes.

| Classe | heureux | stressant | neutre | triste | autre | abstention |
|---|---:|---:|---:|---:|---:|---:|
| heureux | 9 | 0 | 0 | 0 | 0 | 1 |
| stressant | 0 | 9 | 0 | 1 | 0 | 0 |
| neutre | 0 | 0 | 10 | 0 | 0 | 0 |
| triste | 0 | 0 | 1 | 8 | 0 | 1 |
| autre | 1 | 2 | 3 | 2 | 1 | 1 |

| Groupe négatif | N | Suggestions | Abstention |
|---|---:|---:|---:|
| ambiguous | 8 | 7 | 12.5% |
| invalid | 5 | 0 | 100.0% |
| multiple | 8 | 7 | 12.5% |
| undetermined | 12 | 7 | 41.7% |

Suggestions erronées (cas fictifs) :

- final-stressant-7 : Une ombre grattait au carreau et je me sentais terrifié. → triste
- final-triste-9 : Je n'avais plus personne à qui parler et ressentais une immense solitude. → neutre
- final-autre-1 : Je découvrais un piano minuscule ; ma seule émotion était la surprise. → neutre
- final-autre-2 : Une pomme chantait et j'étais stupéfait, sans joie ni peur. → neutre
- final-autre-3 : Une étoile entrait dans ma poche et je ressentais de l'étonnement. → heureux
- final-autre-5 : Je voulais comprendre cette énigme et me sentais curieux, pas inquiet. → neutre
- final-autre-6 : Quelqu'un déchirait mon dessin et j'étais en colère. → stressant
- final-autre-7 : On m'avait volé ma médaille et j'éprouvais une fureur intense. → stressant
- final-autre-9 : Je goûtais un aliment pourri et ressentais un profond dégoût. → triste
- final-autre-10 : Des vers couvraient mon assiette ; j'étais écœuré, sans peur. → triste
- final-undetermined-6 : Je tenais un billet de train mais mon ressenti n'est pas connu. → neutre
- final-undetermined-7 : La scène montrait un théâtre ; j'ai oublié ce que je ressentais. → neutre
- final-undetermined-8 : Je voyais une montagne, sans pouvoir dire quelle était mon émotion. → neutre
- final-undetermined-9 : Un enfant était heureux ; le rêve ne dit pas comment moi je me sentais. → neutre
- final-undetermined-10 : Une femme semblait effrayée, mais mon propre sentiment reste inconnu. → neutre
- final-undetermined-11 : Je notais le mot tristesse sur un panneau, sans souvenir de mon ressenti. → neutre
- final-undetermined-12 : Je racontais seulement les événements ; aucune information sur mes émotions. → neutre
- final-ambiguous-1 : Mon sourire pouvait cacher de la joie ou de l'angoisse, je ne sais pas. → autre
- final-ambiguous-2 : Je me sentais bizarre et je ne peux préciser mon émotion. → neutre
- final-ambiguous-3 : Je crois que j'étais triste, ou simplement fatigué, sans certitude. → triste
- final-ambiguous-4 : Je ne savais pas si ce tremblement venait de peur ou d'excitation. → autre
- final-ambiguous-5 : Mon émotion était incertaine, entre curiosité et inquiétude. → stressant
- final-ambiguous-6 : Je ne suis pas sûr d'avoir ressenti du bonheur plutôt que de la surprise. → stressant
- final-ambiguous-7 : Ma réaction est confuse ; je ne sais pas si j'étais neutre ou triste. → autre
- final-multiple-1 : Je ressentais simultanément de la joie et de la tristesse, aussi fortes l'une que l'autre. → autre
- final-multiple-2 : La peur et la colère étaient toutes deux très présentes, aucune ne dominait. → stressant
- final-multiple-3 : J'éprouvais autant de bonheur que d'angoisse au même instant. → heureux
- final-multiple-5 : Une surprise intense se mêlait à une peur aussi intense. → stressant
- final-multiple-6 : Je riais de bonheur et pleurais de chagrin, avec la même intensité. → heureux
- final-multiple-7 : Je me sentais furieux et heureux à parts égales. → heureux
- final-multiple-8 : Je ressentais deux émotions dominantes opposées : joie et tristesse. → triste

### candidate

| Classe | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| heureux | 1.000 | 0.300 | 0.462 | 10 |
| stressant | 1.000 | 0.300 | 0.462 | 10 |
| neutre | 0.000 | 0.000 | 0.000 | 10 |
| triste | 1.000 | 0.300 | 0.462 | 10 |
| autre | 0.000 | 0.000 | 0.000 | 10 |

Matrice : référence en lignes, prédiction en colonnes.

| Classe | heureux | stressant | neutre | triste | autre | abstention |
|---|---:|---:|---:|---:|---:|---:|
| heureux | 3 | 0 | 0 | 0 | 0 | 7 |
| stressant | 0 | 3 | 0 | 0 | 0 | 7 |
| neutre | 0 | 0 | 0 | 0 | 0 | 10 |
| triste | 0 | 0 | 0 | 3 | 0 | 7 |
| autre | 0 | 0 | 0 | 0 | 0 | 10 |

| Groupe négatif | N | Suggestions | Abstention |
|---|---:|---:|---:|
| ambiguous | 8 | 0 | 100.0% |
| invalid | 5 | 0 | 100.0% |
| multiple | 8 | 0 | 100.0% |
| undetermined | 12 | 0 | 100.0% |

Suggestions erronées (cas fictifs) :


## CPU, RAM et incidents

Chargement modèle/tokenizer après imports, TEST : 1.312 s.

| Méthode | Latence médiane explicite | Maximum |
|---|---:|---:|
| baseline | 0.491 s | 0.699 s |
| candidate | 1.154 s | 1.437 s |

| Mesure surveillant | DEV | TEST |
|---|---:|---:|
| Durée totale processus (s) | 91.0 | 137.7 |
| Pic résident natif (Mio) | 2061.7 | 2061.7 |
| Pic privé natif (Mio) | 2484.6 | 2484.5 |
| Pic privé groupe échantillonné (Mio) | 2230.5 | 2242.4 |
| RAM disponible avant (Mio) | 3824.5 | 3831.6 |
| RAM disponible minimum (Mio) | 1804.0 | 1898.7 |
| RAM disponible après (Mio) | 3848.1 | 3923.7 |

Un seul modèle résident par processus, jamais une copie par méthode.
Le pic RAM est commun aux deux méthodes et ne permet pas d'attribuer une
différence mémoire à l'une d'elles. Surveillant indépendant, arbre Python,
échantillonnage 100 ms ; réserve système 1 536 Mio, limite privée observée
3 072 Mio, marge engagée minimale 1 024 Mio, délai 600 s par étape.
Les pics natifs et observés diffèrent par définition. Ce n'est pas un
plafond dur Job Object. Pas de mesure sous charge Whisper/image simultanée.

Un premier essai DEV a échoué avec NameError sur importlib, après chargement
mais avant analyse du corpus. L'import a été corrigé, journal et mémoire
conservés localement. Aucun résultat de cet essai n'est utilisé. Le DEV réussi
et l'unique TEST final sont les mesures ci-dessus, pas des relances ajustées
sur les résultats finaux. Tous les paramètres et expériences de grille sont
dans results-c-dev.json ; le fichier results-c-test.json conserve chaque
sortie, durée, raison d'abstention et score brut. Les raisons des contrôles
sont des diagnostics du modèle, pas des annotations fiables de la cause réelle.

## Limites et décision

- macro-F1 : NON satisfait
- rappel de chaque classe : NON satisfait
- qualité suggestions explicites : satisfait
- couverture explicite : NON satisfait
- suggestions indéterminables : satisfait
- abstention ambiguë : satisfait
- abstention multi-émotions : satisfait

La sélection très prudente peut gagner en refus sans savoir classer mieux.
Sur ce TEST, les dix neutres sont refusés : huit pour scores insuffisants,
deux par le contrôle multi-émotions. Les dix autres sont aussi refusés : six
pour scores insuffisants, quatre par le contrôle multi-émotions. Ce dernier
peut donc confondre les négations (« sans joie ni peur ») ou les descriptions
avec une pluralité réelle ; la raison de rejet ne garantit pas sa justesse.
Les scores absolus NLI et les nouvelles formulations ne sont pas calibrés ;
les résultats ne prouvent pas que mDeBERTa est incapable de reconnaître ces
classes dans toute autre méthode. Rien n'a été réajusté pour les améliorer.
Neuf suggestions correctes ne suffisent pas à garantir 100 % de précision
future, encore moins sur des rêves implicites ou un autre matériel.
Les abstentions ne sont jamais comptées comme des classifications explicites
correctes. Les corpus synthétiques et la grille choisie ne couvrent pas tous
les réglages possibles ; une baisse ne prouve pas l'impossibilité d'améliorer
mDeBERTa. Le contrôle automatique du non-ressenti reste une tâche difficile.

Ne pas déployer cette variante en l'état. Poursuivre éventuellement la
recherche ciblée avec un nouveau test tenu à l'écart, revue humaine des
annotations et une méthode de vérification du ressenti mieux évaluée.
Pour le projet pédagogique, une aide facultative limitée et systématiquement
confirmée par l'utilisateur serait plus prudente qu'un classement automatique.
Ce serait une décision de périmètre à valider : elle ne permet pas de déclarer
les cinq catégories P08 fiables ni le ticket entièrement satisfait.
La correction manuelle et le retrait explicite restent indispensables.

## Reproduction et contrôles

Nouveaux fichiers de qualification : reliability_data.py, reliability.py,
watch_c.py, reliability_protocol.json, test_reliability.py et report_c.py.
Artefacts fictifs : results-c-{dev,test}.json, memory-c-{dev,test}.json,
protocol-c-before-test.json. Aucun poids, venv ou secret dans le dépôt.
Racine locale : %LOCALAPPDATA%/SynthetiseurDeReves/qualification/p08c.
Les commandes ne téléchargent rien et n'accèdent à aucune base :

```powershell
$p08Root = Join-Path $env:LOCALAPPDATA 'SynthetiseurDeReves\qualification\p08'
$p08Python = Join-Path $p08Root '.venv\Scripts\python.exe'
& $p08Python qualification/p08/watch_c.py --stage dev
& $p08Python qualification/p08/watch_c.py --stage test
```

Ne pas relancer pour une simple lecture du rapport ; cela écrirait de nouvelles
mesures locales. Le modèle et les dépendances sont ceux de phase 2B, versions
et empreintes enregistrées dans les résultats. Le protocole gelé et les
empreintes vérifiées rendent les décisions auditables, sans garantir une
reproduction bit à bit sur une autre machine.
Aucun composant de production, CSS, route, worker, base ou migration modifié.
Aucun troisième modèle, GPU, service distant, commit, push ou changement Jira.


Contrôles exécutés : 124 tests unitaires réussis en 3,13 s ; Ruff backend/scripts/qualification réussi. La non-régression ici est unitaire : aucune suite PostgreSQL ou navigateur relancée, car ces composants et leurs dépendances ne sont pas modifiés.
