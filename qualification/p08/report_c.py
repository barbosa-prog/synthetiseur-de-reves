"""Restitution des mesures figées, sans modèle, réseau ou réajustement."""

import json
from pathlib import Path

from reliability import ELEMENTS, GATES, VARIANTS


def percent(value):
    return "non définie" if value is None else f"{value:.1%}"


def global_suggestion_quality(rows, method):
    emitted = [r for r in rows if r["outputs"][method]["prediction"] is not None]
    correct = sum(r["group"] == "explicit"
                  and r["outputs"][method]["prediction"] == r["expected"] for r in emitted)
    return dict(emitted=len(emitted), correct=correct,
                precision=correct/len(emitted) if emitted else None)


def main():
    base = Path(__file__).parent
    report = json.loads((base/"results-c-test.json").read_text(encoding="utf-8"))
    dev = json.loads((base/"results-c-dev.json").read_text(encoding="utf-8"))
    protocol = json.loads((base/"reliability_protocol.json").read_text(encoding="utf-8"))
    memory = {stage: json.loads((base/f"memory-c-{stage}.json").read_text())
              for stage in ["dev", "test"]}
    params = report["frozen"]["parameters"]
    lines = ["""# P08 — Phase 2C : fiabilité de mDeBERTa, CPU local

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
"""]
    lines += ["\n### Paramètres retenus sur DEV\n", "```json",
              json.dumps(params, indent=2, ensure_ascii=False), "```",
              f"DEV : macro-F1 {dev['best']['macro_f1']:.3f}, "
              f"couverture {percent(dev['best']['coverage'])}, "
              f"qualité des suggestions explicites {percent(dev['best']['emitted_accuracy'])}, "
              f"suggestions sur négatifs : {dev['best']['unsafe']}.\n",
              "Hypothèses retenues (ordre contractuel) :\n"]
    lines += [f"- {name} : {hypothesis}" for name, hypothesis in
              zip(ELEMENTS, VARIANTS[params["variant"]])]
    lines += ["\nContrôles :\n"]+[f"- {text}" for text in GATES]
    lines += ["\n## Résultats du nouveau TEST\n",
              "La référence est mDeBERTa sans adaptation : protocole phase 2B, "
              "hypothèses variante 0, seuil 0,55 et marge 0,05. "
              "Les méthodes sont alternées par cas sur le même modèle résident.\n",
              "| Mesure explicite | Référence | Candidate |", "|---|---:|---:|"]
    for title, metric, percentage in [("Macro-F1", "macro_f1", False),
                                      ("Exactitude (abstentions = échecs)", "accuracy", True),
                                      ("Abstention", "abstention_rate", True)]:
        values = [report["summaries"][m]["explicit"][metric] for m in ["baseline", "candidate"]]
        shown = [percent(v) if percentage else f"{v:.3f}" for v in values]
        lines.append(f"| {title} | {shown[0]} | {shown[1]} |")
    for title, key in [("Couverture explicite", "coverage"),
                       ("Qualité des seules suggestions explicites", "emitted_accuracy")]:
        lines.append(f"| {title} | {percent(report['summaries']['baseline'][key])} | "
                     f"{percent(report['summaries']['candidate'][key])} |")
    global_quality = {m: global_suggestion_quality(report["rows"], m)
                      for m in ["baseline", "candidate"]}
    lines.append("\nQualité globale des suggestions (inclut les suggestions injustifiées sur "
                 "négatifs, jamais les abstentions comme succès) : "+" ; ".join(
                     f"{m} {q['correct']}/{q['emitted']} = {percent(q['precision'])}"
                     for m, q in global_quality.items())+".\n")
    for method in ["baseline", "candidate"]:
        summary = report["summaries"][method]
        lines += [f"\n### {method}\n", "| Classe | Précision | Rappel | F1 | Support |",
                  "|---|---:|---:|---:|---:|"]
        for label, scores in summary["explicit"]["per_class"].items():
            lines.append(f"| {label} | {scores['precision']:.3f} | {scores['recall']:.3f} | "
                         f"{scores['f1']:.3f} | {scores['support']} |")
        lines += ["\nMatrice : référence en lignes, prédiction en colonnes.\n",
                  "| Classe | heureux | stressant | neutre | triste | autre | abstention |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for label, values in summary["explicit"]["matrix"].items():
            lines.append("| "+label+" | "+" | ".join(str(v) for v in values.values())+" |")
        lines += ["\n| Groupe négatif | N | Suggestions | Abstention |",
                  "|---|---:|---:|---:|"]
        for group, scores in summary["groups"].items():
            lines.append(f"| {group} | {scores['count']} | {scores['suggestions']} | "
                         f"{percent(scores['abstention_rate'])} |")
        errors = [r for r in report["rows"] if r["outputs"][method]["prediction"] is not None
                  and r["outputs"][method]["prediction"] != r["expected"]]
        lines += ["\nSuggestions erronées (cas fictifs) :\n"]
        lines += [f"- {r['id']} : {r['text']} → {r['outputs'][method]['prediction']}"
                  for r in errors]
    lines += ["\n## CPU, RAM et incidents\n",
              f"Chargement modèle/tokenizer après imports, TEST : "
              f"{report['load_seconds']:.3f} s.\n",
              "| Méthode | Latence médiane explicite | Maximum |", "|---|---:|---:|"]
    for method, latency in report["latencies"].items():
        lines.append(f"| {method} | {latency['median']:.3f} s | {latency['maximum']:.3f} s |")
    lines += ["\n| Mesure surveillant | DEV | TEST |", "|---|---:|---:|"]
    for title, key in [("Durée totale processus (s)", "seconds"),
                       ("Pic résident natif (Mio)", "peak_rss_mib"),
                       ("Pic privé natif (Mio)", "peak_private_mib"),
                       ("Pic privé groupe échantillonné (Mio)", "group_private_peak_mib"),
                       ("RAM disponible avant (Mio)", "available_before_mib"),
                       ("RAM disponible minimum (Mio)", "available_min_mib"),
                       ("RAM disponible après (Mio)", "available_after_mib")]:
        lines.append(f"| {title} | {memory['dev'][key]:.1f} | {memory['test'][key]:.1f} |")
    lines += ["""
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
"""]
    s = report["summaries"]["candidate"]
    criteria = protocol["exploratory_acceptance_not_official_jira"]
    checks = {
        "macro-F1": s["explicit"]["macro_f1"] >= criteria["macro_f1_min"],
        "rappel de chaque classe": all(v["recall"] >= criteria["recall_each_min"]
                                       for v in s["explicit"]["per_class"].values()),
        "qualité suggestions explicites": (s["emitted_accuracy"] or 0)
        >= criteria["emitted_accuracy_min"],
        "couverture explicite": s["coverage"] >= criteria["explicit_coverage_min"],
        "suggestions indéterminables": s["groups"]["undetermined"]["suggestions"]
        <= criteria["undetermined_suggestions_max"],
        "abstention ambiguë": s["groups"]["ambiguous"]["abstention_rate"]
        >= criteria["ambiguous_abstention_min"],
        "abstention multi-émotions": s["groups"]["multiple"]["abstention_rate"]
        >= criteria["multiple_abstention_min"],
    }
    lines += [f"- {name} : {'satisfait' if passed else 'NON satisfait'}"
              for name, passed in checks.items()]
    lines += ["""
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
$p08Root = Join-Path $env:LOCALAPPDATA 'SynthetiseurDeReves\\qualification\\p08'
$p08Python = Join-Path $p08Root '.venv\\Scripts\\python.exe'
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
"""]
    lines.append("\nContrôles exécutés : 124 tests unitaires réussis en 3,13 s ; "
                 "Ruff backend/scripts/qualification réussi. La non-régression ici est "
                 "unitaire : aucune suite PostgreSQL ou navigateur relancée, car ces "
                 "composants et leurs dépendances ne sont pas modifiés.")
    (base.parents[1]/"docs/p08-phase2c.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
