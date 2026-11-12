# P08 — Phase 1 : contrat métier, sans moteur ni persistance

## Limites de cette livraison

Les modules emotion_provider et emotion_rules sont indépendants de SQLAlchemy,
FastAPI, MiniLM et des workers existants. Ils ne sont importés par aucune route.
Aucune migration, dépendance, configuration, donnée, interface ou comportement
P06/P09 n'est modifié. La modification CSS préexistante reste intacte.
Le faux fournisseur vit uniquement dans les tests : réponse fixée à la
construction, sans règle linguistique ni prétention de qualité réelle.

## Contrat fournisseur

EmotionProvider.analyze reçoit un instantané immuable : identifiant de demande,
récit normalisé selon P06 (1 à 20 000 caractères), version du récit >= 1,
révision du choix. Le texte est exclu de repr ; ce n'est pas une protection
contre une journalisation volontaire par l'appelant, qui reste interdite.

Le résultat reprend ces identifiants et contient exactement une des valeurs
heureux, stressant, neutre, triste, autre, ou une abstention explicite.
Une abstention exige ambiguous ou insufficient_information ; elle n'est ni
neutre, ni autre, ni une erreur fournisseur. Elle ne peut pas être acceptée
comme choix utilisateur. Aucun score médical ou seuil de confiance inventé.
Le moteur et sa révision sont obligatoires ; les paramètres de segmentation et
les formulations de catégories devront être versionnés dans le futur snapshot.

La fonction analyze valide le résultat, même si le fournisseur a contourné la
validation Pydantic via model_copy. Exception fournisseur remplacée par un code
stable ; aucun retry, réseau, téléchargement ni publication implicite.

## État et priorité

EmotionState est un contrat en mémoire, pas une table ni un cache global.
Sa révision est distincte de text_version. Toute demande, publication ou action
de choix augmente cette révision ; une action exige la révision attendue.
Les transitions retournent un nouvel état validé et ne modifient pas l'ancien.

| Origine | Sens | Publication automatique autorisée à changer le choix ? |
|---|---|---|
| unset | Aucun choix | Oui |
| automatic | Suggestion courante appliquée | Oui |
| manual | Correction explicite, même identique | Non |
| accepted | Suggestion explicitement acceptée | Non |
| withdrawn | Retrait explicite, valeur NULL protégée | Non |
| legacy | Ancien choix de provenance inconnue | Non |

Une abstention publiée retire un ancien choix automatique, mais conserve
un choix protégé. Un retrait ne remet pas l'état à unset. Une nouvelle analyse
peut proposer une suggestion après retrait, sans l'appliquer automatiquement ;
seule une action explicite peut à nouveau retenir une valeur.

L'acceptation vérifie l'identifiant exact de la suggestion et la révision de
l'état. Corriger ou accepter pendant une analyse annule la demande en cours.
Un résultat tardif, dupliqué ou remplacé par une nouvelle demande est refusé.

## Correction du récit

text_changed doit recevoir la nouvelle version P06 : version égale = aucun
changement ; retour en arrière refusé. Une version supérieure invalide la
suggestion et la demande en cours, puis augmente la révision émotionnelle.
Une valeur automatic est retirée ; manual, accepted, withdrawn et legacy sont
conservés. selected_text_version permet d'indiquer qu'un choix conservé a été
fait avant la dernière correction. Aucune nouvelle analyse n'est déclenchée.

Ces règles NE sont PAS encore branchées sur apply_correction ou le PATCH des
rêves. L'intégration devra couvrir toutes les voies P06/P05/API, et faire
transiter les anciennes mutations emotion par le même service métier.

## Contrat de persistance à réaliser après validation

Migration additive envisagée, sans changer les cinq valeurs ni le filtre P09 :

- Garder dreams.emotion comme valeur retenue ; ajouter origine, révision,
  version du récit au choix et dates utiles, avec contraintes de cohérence.
- Préserver les NULL existants comme unset ; conserver les valeurs existantes
  comme legacy, avec version connue au moment de la migration sans prétendre
  connaître la version de leur sélection historique (information indisponible).
  Le schéma définitif devra distinguer cette version de reprise d'une version
  réellement connue ; le contrat en mémoire utilise la version de reprise.
- Étendre jobs.kind à emotion ; unicité partielle d'un job actif par rêve.
  Réutiliser statut, tentatives bornées, claim_token et lease_until, sans
  modifier le comportement des workers STT/image.
- Ajouter un snapshot lié au job et au rêve : propriétaire, récit privé,
  text_version, choice_revision, moteur/révision et configuration versionnée.
  Garder le résultat et l'abstention séparés du choix retenu. L'identifiant
  request_id peut correspondre à l'identifiant du job, pas à son token de bail.
- Référencer la suggestion actuelle ; une ancienne analyse peut être conservée
  comme résultat historique dépassé, sans être exposée comme courante.

La révision capturée doit être celle renvoyée par begin_analysis, après son
incrément. Publication et action utilisateur doivent être transactionnelles :
contrôle propriétaire/rêve non supprimé, verrouillage cohérent job/rêve,
vérification snapshot/version/révision/demande ET token/bail non expiré,
transition métier et écritures dans la même transaction. Une transition pure
réussie n'est pas à elle seule une autorisation de publier en base.
L'authentification, le CSRF, les contrôles d'accès et la limitation des demandes
restent les responsabilités des futurs services/routes, jamais du modèle IA.

P09 continuera de lire dreams.emotion ; NULL = non_renseignee, distinct de
neutre. Les règles futures ne doivent modifier ni récit ni illustration.

## Validation et étapes restantes

Commande sans PostgreSQL, GPU ou réseau :

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_emotion_contract.py backend/tests/test_text_rules.py backend/tests/test_history_rules.py -q
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

Tests : cinq valeurs, abstentions, récits invalides, immutabilité, normalisation,
déterminisme, exception privée masquée, sortie incohérente, résultat ancien,
double publication, demande remplacée, révisions concurrentes, choix identique,
acceptation, retrait et correction du récit pour chaque origine protégée.

Résultats exécutés : 30 tests P08 réussis en 0,25 s ; sélection élargie
P08/texte/P09/image/STT/API : 111 tests réussis en 3,20 s. Ruff sur backend
et scripts : aucun problème. Aucun test PostgreSQL, navigateur ou vrai modèle
exécuté dans cette phase, qui n'ajoute aucune intégration de ces composants.

À valider avant persistance : noms définitifs des tables/colonnes, métadonnées
legacy et rétention des snapshots. Avant un vrai moteur : qualification isolée
autorisée, jeu français, licence/révision, dépendances, RAM et latence mesurées.
La mention non médicale et l'interface appartiennent à une phase ultérieure.
