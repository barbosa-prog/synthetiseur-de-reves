# P14 — Phase 3 : couverture métier obligatoire

## Périmètre officiel

Le manifeste calculable est `scripts/business_coverage.py::business_files`.
Il sélectionne 41 modules actuellement, sans retirer les fichiers peu couverts :

- Tous les fichiers Python de `backend/app/services/` et les modules `*_rules.py`
  de `backend/app/` : persistance métier, versions, autorisations, jobs, quotas,
  historique, export, suppression et purge.
- `auth.py`, `security.py`, `auth_schemas.py` : sessions, contrôles d'identité,
  anti-bruteforce, mots de passe et validation des identifiants.
- `audio_types.py`, `export_contract.py`, `history_schemas.py`,
  `transcript_schemas.py` : contraintes métier des entrées et contrats.
- `storage/local.py`, `stt_audio.py`, `audio_worker.py` : intégrité et validation
  des médias, décodage et normalisation audio.
- Les trois fournisseurs `stt_provider.py`, `image_provider.py`,
  `emotion_provider.py`, les trois workers correspondants, `image_runner.py`
  et `emotion_runner.py` : contrats et orchestration des succès/échecs, arrêts et
  sous-processus. Leurs branches non couvertes restent dans le dénominateur.
- `emotion_config.py`, `job_config.py` : configuration et délais ayant un effet
  sur l'admission et le traitement des demandes.

Les nouveaux services/règles sont inclus automatiquement. Tout fichier métier
attendu absent du rapport fait échouer le contrôle : il ne peut pas disparaître
silencieusement pour améliorer le score.

### Exclusions de périmètre, pas exclusions de tests

Les routes API et web, `main.py`, `database.py`, `models.py`, `schemas.py`,
`http_guard.py`, `safe_logging.py` et `offline.py` restent mesurés dans le rapport
backend global et leurs tests restent exécutés. Ils sont exclus du taux métier
spécifique pour distinguer présentation/transport HTTP, assemblage, descriptions
ORM et infrastructure des services exécutant les opérations métier.
Cela ne dispense pas les chemins d'accès, la sécurité HTTP, les erreurs ou les
contraintes de base d'être testés.

Les migrations, scripts de qualification, dépendances, tests, HTML/CSS/JavaScript
ne sont pas du Python métier `backend.app` et ne sont pas dans ce dénominateur.
Les véritables calculs dans les environnements IA séparés ne sont pas exécutés
ni revendiqués comme couverts par cette campagne simulée.

## Mesure précise

pytest-cov instrumente tout `backend.app` avec `--cov-branch`. La configuration
versionnée `pyproject.toml` active aussi les branches ; la commande choisit ce
fichier explicitement, sans dépendre d'un fichier coverage utilisateur.

Le rapport spécifique sélectionne les instructions appartenant aux **corps** des
fonctions synchrones/asynchrones et méthodes des modules retenus. L'analyse AST
sert à localiser ces corps ; coverage détermine les instructions exécutables et
les arcs de branchement. Imports et déclarations au niveau module ne gonflent
pas la métrique métier. Les fonctions imbriquées sont comptées par union des
lignes/arcs, sans double comptabilisation.

Le dénominateur ne contient ni lignes vides ni commentaires. Les exclusions
standards de coverage pour les interfaces `Protocol` sont conservées ; aucun
`pragma: no cover`, `omit` ou liste d'exclusion spécifique n'est ajouté pour
améliorer le score. Le rapport global permet de contrôler les exclusions.

Trois taux sont publiés :

1. Instructions : instructions exécutées / instructions exécutables.
2. Branches : sorties de branches parcourues / sorties possibles.
3. **Taux combiné obligatoire** : (instructions exécutées + sorties parcourues)
   / (instructions exécutables + sorties possibles).

Le taux combiné doit être **au moins 80 %**, comparé sans arrondi. C'est une
couverture d'instructions et de branches dans les fonctions, pas un pourcentage
de fonctions entièrement testées. Les taux de branches et d'instructions sont
affichés séparément ; il n'existe pas de seuil distinct de 80 % sur les branches
seules. Un rapport sans instrumentation des branches, vide ou incomplet échoue.

## Commande de recette Windows

```powershell
.\.venv\Scripts\python.exe scripts\verify_image_jobs.py --business-coverage
```

Cette option s'utilise seule. Elle vérifie les dépendances de test, utilise les
binaires PostgreSQL locaux existants, initialise un cluster neuf, valide son
autorisation P14 et son identité, puis exécute tous les tests hors `browser` et
`qualification`. Les fixtures migrent seulement les schémas de ce cluster.
Les tests ignorés/désélectionnés sont signalés par pytest (`-ra`/résumé).
Aucune IA réelle, aucun téléchargement, aucune URL personnelle autorisée.
En cas de manque de dépendance ou de PostgreSQL, la commande échoue explicitement.

Les rapports sont conservés dans `tmp/p14-coverage/`, déjà ignoré par Git :

- `.coverage` : données brutes de cette campagne, distinctes de l'ancien fichier
  `.coverage` à la racine ;
- `backend.json` : mesures détaillées, branches et résultats globaux ;
- `backend.xml` : rapport Cobertura ;
- `business.json` : périmètre, mesure par module, résultats et seuil métier.

Les anciens rapports JSON/XML de ce répertoire sont retirés avant campagne pour
éviter une validation sur un artefact périmé. Un échec pytest est propagé ; sinon
le contrôle métier retourne 0 en cas de succès, 1 si le seuil n'est pas atteint,
2 si le rapport est invalide. Le cluster est arrêté et nettoyé dans tous ces cas
par le mécanisme existant du lanceur. Les rapports ne contiennent pas de récits,
de variables privées ni d'identifiants PostgreSQL ; ils référencent le code.

### Vérification négative sans réexécuter les tests

```powershell
.\.venv\Scripts\python.exe scripts\business_coverage.py tmp\p14-coverage\backend.json --threshold 100
# Résultat attendu : échec et code 1 si le taux réel est inférieur à 100 %.
```

La valeur minimale autorisée reste 80 : l'option ne peut pas abaisser la politique.
Ne pas exécuter directement une campagne PostgreSQL avec une URL personnelle.

## Tests du mécanisme

`test_business_coverage.py` couvre la borne exacte de 80 %, le rejet d'un seuil
trop faible ou non fini, le refus d'un rapport sans branches ou d'un module
manquant, l'exclusion des déclarations de module, la sélection de la sécurité et
des workers, et la propagation du code d'échec avec un rapport généré.
Les données de ces tests sont synthétiques et ne nécessitent pas PostgreSQL.

Les limites persistent : la couverture n'est pas une preuve de conformité ou
d'absence de défaut ; les branches prises ne prouvent pas toutes les combinaisons
de conditions. Les sous-processus non instrumentés ne sont pas crédités comme
exécutés ; leurs fonctions sélectionnées restent au dénominateur. Le navigateur
et les inférences réelles sont exclus explicitement de cette commande.

Aucun workflow GitHub Actions n'est ajouté dans cette phase.

## Résultats mesurés le 13 novembre 2026

### Campagnes et renforcement ciblé

1. Commande isolée `--business-coverage` : **860 tests réussis**, **15
   désélectionnés**, **422,94 secondes**. Les 15 cas correspondent aux 14 tests
   navigateur et à la qualification émotionnelle réelle, explicitement hors
   campagne. Aucun test sélectionné ignoré ou en échec. Le contrôle métier
   automatique a retourné **0** avec 82,10 % combinés (83,93 % des instructions,
   77,55 % des branches). Aucun résultat historique réutilisé.
2. Les premières mesures ont révélé une couverture faible des boucles CLI.
   Ajout de **16 tests déterministes** dans `test_worker_entrypoints.py` : succès,
   erreur générique, interruption, attente puis erreur et arrêt, occupation du
   GPU/verrou émotion, configuration indisponible et libération du moteur SQL.
   Moteur, sessions, stockage, verrous, appels fournisseur et sommeil sont simulés.
   Aucune connexion, aucun processus IA ni poids de modèle dans ces tests.
3. Campagne ciblée après ajout : **25 réussis en 3,95 secondes** (les 16 nouveaux
   cas et les 9 tests du contrôleur). Mesure fusionnée avec la première campagne
   par `--cov-append`, branches actives et même source/configuration. Les rapports
   JSON/XML finaux et le contrôle métier ont été régénérés. Ce résultat n'est
   pas présenté comme une nouvelle campagne complète de 876 tests.
4. Les 9 tests du contrôleur avaient également réussi seuls en 0,39 seconde.
   Les campagnes se recouvrent : ne pas additionner les 9 cas deux fois.

### Mesures finales fusionnées

| Périmètre | Instructions | Branches | Combiné |
|---|---:|---:|---:|
| Corps des fonctions métier | **2 034 / 2 334 = 87,15 %** | **746 / 940 = 79,36 %** | **2 780 / 3 274 = 84,91 %** |
| Backend global | **4 086 / 4 454 = 91,74 %** | **935 / 1 168 = 80,05 %** | **5 021 / 5 622 = 89,31 %** |

Le seuil métier obligatoire de 80 % combiné est **validé**. Le taux de branches
métier seul reste à 79,36 % et n'est pas présenté comme supérieur à 80 %.
Le périmètre a été élargi par rapport à l'estimation historique de phase 1 :
les taux ne sont pas directement comparables à l'ancien 91,23 %.

Couverture combinée des modules workers après les nouveaux tests : STT **93,33 %**,
image **95,77 %**, émotion **89,74 %**. Il s'agit ici des modules globaux, distincts
du sous-ensemble des corps de fonctions. Les ponts natifs non exécutés restent
moins couverts ; aucune exclusion ajoutée pour compenser cette limite.

### Contrôles positifs, négatifs et sécurité

- Contrôleur réel sur `backend.json`, seuil 80 : **code 0**, 84,91 %.
- Même rapport, seuil volontairement fixé à 100 : **code 1**, échec attendu.
  Aucun PostgreSQL ni test IA relancé pour ce contrôle négatif.
- Métadonnée JSON `branch_coverage=true` ; les 940 sorties métier et les 1 168
  sorties globales sont réellement instrumentées, pas extrapolées.
- Le JSON contient 20 lignes exclues par les mécanismes standards de coverage,
  correspondant aux interfaces Protocol ; aucun nouveau motif d'exclusion ajouté.
- Vérification des comptages : pour chaque fichier, les instructions exécutées
  JSON correspondent au résumé standard coverage. Option de campagne combinée
  avec `--unit-only` refusée avant initialisation PostgreSQL.
- Ruff `backend scripts`, compilation Python, `git diff --check` : réussis.
  Avertissements Git LF/CRLF uniquement.
- Rapports `tmp/p14-coverage/` ignorés par Git. Aucun modèle, archive ou média
  personnel produit, aucun accès à `dreams_local`. La migration 0010 a été
  appliquée uniquement aux schémas du cluster temporaire autorisé.
- Le lanceur est terminé avec succès ; aucun processus PostgreSQL/Python des
  recettes temporaires ne reste actif après nettoyage.

### Fichiers de phase 3 et limites

Créés : `scripts/business_coverage.py`, `backend/tests/test_business_coverage.py`,
`backend/tests/test_worker_entrypoints.py`, `docs/p14-phase3.md`.
Modifiés : `scripts/verify_image_jobs.py`, `pyproject.toml`, `README.md`.
Le travail phase 2 non commité reste conservé ; aucun code de production modifié.

Le CSS indépendant garde son empreinte
`d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.
Aucune inférence réelle, aucun téléchargement, aucune opération Git d'écriture
ou modification Jira. Aucune CI ajoutée. Les contrôles ne constituent pas une
garantie contre un programme malveillant ayant les mêmes droits Windows.
