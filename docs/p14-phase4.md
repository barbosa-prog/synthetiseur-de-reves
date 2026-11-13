# P14 — Phase 4 : GitHub Actions

## Stratégie retenue

Un seul job sur **`windows-2025`**, Python **3.12**, shell PowerShell (`pwsh`).
Le projet utilise notamment `msvcrt`, des verrous Windows et des tests de
jonctions ; les scripts existants attendent les exécutables PostgreSQL Windows.
Il n'est donc pas supposé qu'une image Docker Linux fonctionnerait sur ce runner.
Aucune matrice, aucun conteneur service, aucun déploiement.

L'inventaire officiel consulté le 13 novembre 2026 indique PostgreSQL 17 et Chrome
préinstallés sur Windows Server 2025. Le précontrôle vérifie effectivement les
binaires, la version majeure et le navigateur ; il échoue si l'image a changé.
Il ne démarre pas le service PostgreSQL préinstallé et n'utilise ni sa base ni
ses identifiants. Le lanceur appelle `initdb` dans un répertoire temporaire neuf,
crée un rôle aléatoire, une base fictive et un port dynamique hors ports interdits.

Source : [inventaire officiel Windows Server 2025](https://github.com/actions/runner-images/blob/main/images/windows/Windows2025-Readme.md).

## Workflow et permissions

Fichier : `.github/workflows/tests.yml`. Déclenchements : PR vers `main`, push
sur `main`, lancement manuel. Permission unique `contents: read` ; aucun secret
de dépôt référencé. Pas de `pull_request_target`, pas d'écriture de commentaire,
de publication applicative ou de modification Jira. Le checkout ne conserve pas
ses identifiants. Une concurrence par workflow/ref annule les anciens jobs.
Le délai global est limité à 35 minutes.

Actions officielles épinglées par SHA, références publiques vérifiées via l'API
HTTPS GitHub (sans authentification) le 13 novembre 2026 :

| Action | Référence examinée | SHA |
|---|---|---|
| checkout | v7 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| setup-python | v7 | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` |
| upload-artifact | v4 / v4.6.2 | `ea165f8d65b6e75b540449e92b4886f43607fa02` |

Les SHA sont figés ; l'image runner et le correctif Python 3.12 peuvent évoluer.
Il faudra maintenir ces versions explicitement en cas d'obsolescence.

## Étapes obligatoires

1. Checkout et sélection de Python 3.12.
2. Refus d'un `.env` dans le checkout CI ; contrôle PostgreSQL 17 et Chrome.
3. Installation des seuls `requirements-dev.txt` avec roues binaires ; `pip check`.
   Aucune installation de `requirements-stt` ou de l'environnement GPU/Transformers.
4. Ruff sur `backend scripts` et compilation Python.
5. `python scripts/verify_image_jobs.py --business-coverage` : suite unitaire et
   intégration, PostgreSQL jetable, branches et seuil métier combiné >= 80 %.
6. `python scripts/verify_p20.py --browser-only --emotion-web-test` : Chrome
   installé, serveur HTTPS et nouveau cluster jetables, modèles simulés.
7. Résumé associé à `GITHUB_SHA`, puis dépôt des seuls rapports autorisés.

Toutes les étapes sont bloquantes ; aucune utilisation de `continue-on-error`.
La publication des artefacts ne s'exécute que si les étapes précédentes passent.
Une erreur de dépendance, de base, de migration ou de couverture échoue le job.
La configuration CI est transmise aux processus ; les variables de production
ne sont jamais requises. Les protections phase 2 restent actives, y compris le
refus de `dreams_local` avant socket, le manifeste, le contrôle de `data_directory`
et la cohérence des deux URL PostgreSQL.

## Tests ignorés et modèles

En CI (`CI=true`), un test sélectionné ignoré fait échouer pytest, sauf s'il
porte explicitement le marqueur de qualification réelle. La recette de couverture
désélectionne les navigateurs et qualifications ; la recette Chrome sélectionne
les navigateurs. La qualification réelle reste hors workflow. Des tests unitaires
du garde vérifient intentionnellement cette qualification ignorée dans un pytest
enfant ; ce n'est pas un test obligatoire d'inférence manquant.

Les trois tests synthétiques du pont CPU ne dépendent plus du venv IA présent sur
le PC de développement : ils utilisent `sys.executable` et `psutil` du venv de
test. Un enfant est synthétique (attente bornée), l'autre scénario s'arrête au
précontrôle mémoire avant tout chargement. Aucun poids, GPU ou modèle téléchargé.
`psutil` et PyYAML sont ajoutés aux dépendances de développement ; coverage est
épinglé pour stabiliser le format de mesure. Les bibliothèques de production ne
sont pas changées. Les gardes réseau Python ne sont pas un pare-feu système pour
Chrome : seules des URL locales sont utilisées par les parcours applicatifs.

## Artefacts et lien au commit

Seuls cinq chemins exacts sont publiés, conservation **7 jours** :

- `tmp/p14-coverage/backend.json`
- `tmp/p14-coverage/backend.xml`
- `tmp/p14-coverage/business.json`
- `tmp/p14-coverage/ci-summary.json`
- `tmp/p14-coverage/ci-summary.md`

Pas de joker global : ni `.env`, clé TLS, journal PostgreSQL, couverture brute,
capture d'écran, fichier audio/image ou ZIP de rêve. Le JUnit `tests.xml` est
produit localement dans les rapports mais n'est **pas** publié : le script de
résumé ne conserve que ses nombres de tests/erreurs/ignorés. Il refuse un résultat
obligatoire incomplet, un seuil inférieur à 80 ou des branches absentes.
Les rapports de couverture contiennent les noms de code, pas les récits.

L'artefact porte le SHA du workflow ; le résumé JSON et le résumé du job portent
le même commit. Pour une PR, ce SHA peut être celui du commit de fusion de test
GitHub, distinct de la tête de branche. Le résultat Chrome est une étape séparée
obligatoire du même job : le résumé de couverture ne prétend pas intégrer sa
couverture ou son nombre de tests.

Les anciens rapports sont invalidés par réécriture avant une nouvelle mesure,
sans suppression de fichiers source. Aucun artefact n'est envoyé en cas d'échec.

## Commandes locales Windows

```powershell
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe scripts\verify_image_jobs.py --business-coverage
.\.venv\Scripts\python.exe scripts\verify_p20.py --browser-only --emotion-web-test
git diff --check
```

Pour tester la politique de tests ignorés : positionner `CI=true` uniquement
dans le processus de recette, puis restaurer la variable après usage. Les
campagnes de cette phase utilisent des processus Python dédiés, sans modifier
l'environnement permanent du PC. Ne pas définir une URL personnelle pour ces
commandes. `P20_POSTGRES_BIN` peut préciser le répertoire des binaires locaux.

## Première validation sur GitHub — opérations humaines

Après revue, effectuer vous-même le commit et le push. Dans Settings > Actions,
vérifier que les actions officielles et le runner Windows sont autorisés. Pour
ce dépôt privé, vérifier les minutes incluses et les limites de facturation du
compte avant lancement ; aucun lancement distant ni engagement de dépense n'est
effectué pendant cette phase.

Dans Actions, ouvrir « P14 - Tests et couverture metier » et vérifier :

1. Le SHA attendu et le runner `windows-2025`.
2. Les précontrôles, l'installation des dépendances et `pip check`.
3. Les résultats pytest sans test obligatoire ignoré, et seuil métier validé.
4. Les parcours Chrome et l'arrêt des services temporaires.
5. Les cinq artefacts autorisés et le résumé associé au commit.

Pour un premier lancement manuel, le workflow doit déjà exister sur la branche
par défaut. Les PR de forks peuvent nécessiter une approbation GitHub du
mainteneur. Les restrictions d'organisation, disponibilité de l'image et accès
aux registres de paquets ne sont pas vérifiables localement.

**Aucune exécution GitHub Actions n'a été réalisée ici.** La validation locale ne
remplace pas le premier run distant après votre push. Un blocage d'image, de
version ou de politique GitHub doit rester visible et ne pas être masqué par des
tests ignorés ou la baisse du seuil de couverture.

## Recette locale réellement exécutée — 13 novembre 2026

| Contrôle | Résultat |
|---|---|
| Couverture complète, `CI=true`, PostgreSQL jetable | **886 réussis, 15 désélectionnés**, 442,27 s ; aucun ignoré sélectionné |
| Chrome bureau/mobile, `CI=true`, nouvelle base jetable | **14 réussis, 887 désélectionnés**, 124,30 s |
| Contrat workflow, artefacts, ponts synthétiques | **13 réussis**, 3,99 s |
| Gardes phase 2 et contrat workflow, CI strict | **38 réussis**, 6,15 s |
| Contrat workflow après dernier ajustement du garde | **10 réussis**, 0,34 s |
| YAML et structure | Chargement PyYAML et contrôles contractuels réussis |
| Syntaxe PowerShell des huit scripts `run` | Analyse locale réussie, sans exécuter l'installation ou les étapes GitHub |
| Dépendances | `pip install --dry-run --only-binary=:all: -r requirements-dev.txt` et `pip check` réussis dans le venv existant |
| Qualité | Ruff `backend scripts`, compilation Python et `git diff --check` réussis |

Les campagnes se recouvrent ; les nombres ne s'additionnent pas comme des cas
uniques. Les 15 désélections de la mesure principale sont les 14 cas navigateur
exécutés séparément et la qualification réelle émotionnelle volontairement exclue.

Couverture recalculée, instructions et branches actives, périmètre métier inchangé
de **41 modules** et seuil combiné inchangé à **80 %** :

| Périmètre | Instructions | Branches | Combiné |
|---|---:|---:|---:|
| Corps de fonctions métier | **87,15 %** | **79,36 %** | **84,91 %** |
| Backend global | **91,74 %** | **80,05 %** | **89,31 %** |

Le contrôle final de la recette a retourné 0. Le taux de branches métier seul
n'est pas présenté comme supérieur à 80 %. Le résumé a aussi été généré à partir
du vrai JUnit local (886 cas, zéro ignoré) dans un répertoire temporaire distinct,
avec un SHA fictif réservé au test, puis nettoyé. Aucun résultat local n'est
attribué faussement au commit publié : les sources sont encore non commitées.
Sur GitHub, `GITHUB_SHA` fournira l'identifiant du commit effectivement testé.

Les services jetables sont arrêtés, leurs répertoires de travail nettoyés, et
le contrôle des processus PostgreSQL/Python liés aux recettes ne trouve aucun
processus restant. Le parcours Chrome vérifie également le redémarrage réel
PostgreSQL/Uvicorn, la conservation des budgets/historique, la relecture audio
fictive, puis une purge de média fictif et un refus HTTP 404.

Deux avertissements Pydantic `UnsupportedFieldAttributeWarning` ont été observés
dans les tests concurrents STT et corrections du récit, sur les alias `payload`
et `media_id`. Ils n'ont causé aucun échec et ne sont pas masqués dans la CI.
Pas de correction de production hors périmètre. Les avertissements Git LF/CRLF
restent informatifs.

Limites de validation : l'analyse PowerShell locale a utilisé le parseur disponible
sur le PC, pas une VM GitHub `windows-2025`. Le YAML a été analysé et ses règles
contrôlées par les tests, mais le moteur distant GitHub n'a pas encore compilé
ni exécuté ce workflow. Une installation depuis un runner entièrement vierge
reste donc à confirmer lors du premier run GitHub. Localement, seule la petite
dépendance `psutil` manquante a été installée depuis une roue en cache ; aucun
moteur IA n'a été installé et aucun poids téléchargé.

### Fichiers propres à cette phase

Créés : `.github/workflows/tests.yml`, `scripts/ci_report.py`,
`backend/tests/test_ci_workflow.py`, `docs/p14-phase4.md`.

Modifiés : `requirements-dev.txt` (coverage/psutil/PyYAML),
`backend/tests/test_emotion_bridge.py` (interpréteur de développement),
`backend/tests/conftest.py` (refus des ignorés obligatoires en CI),
`scripts/verify_image_jobs.py` (JUnit et invalidation des anciens rapports sans
suppression de fichier source), `README.md` (commandes et première validation).

Les travaux non commités des phases 2/3 sont conservés. Aucun fichier de
production, migration ou média personnel modifié ; CSS indépendant intact,
SHA256 `d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.
Aucun `git add`, commit, push, restore/reset ni modification Jira. Le commit,
le push et la validation distante restent vos opérations distinctes.
