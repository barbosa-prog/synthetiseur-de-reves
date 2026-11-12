# P07 — Phase 1 : contrat image et noyau du worker

## Références relues

Le PDF officiel Bloc 3 PRODUCTION demande une génération Stable Diffusion ou
DALL-E, une gestion des erreurs/délais et des tests des fonctionnalités critiques.
Le CSV local `tickets_jira_production_corriges.csv`, P07, demande une image
nouvelle issue du récit corrigé, aucune URL fixe présentée comme résultat IA,
un adaptateur interchangeable et la documentation du moteur effectivement testé.
Sa référence Imagen 4 Fast est provisoire ; le choix validé ici est SD 1.5 local.
Le ticket Jira distant n'a pas été consulté ou modifié dans cette phase.

## Livré dans cette phase

- `image_provider.py` : contrat `ImageProvider`, demande immuable Pydantic,
  configuration SD 1.5 et adaptateur `LocalStableDiffusion15`.
- Description visuelle utilisateur distincte du récit français : 1 à 500 caractères,
  versions du récit et de la description obligatoires. Aucune traduction automatique.
  Le contrat accepte un texte français ou anglais ; le récit P06 reste inchangé.
- Entrée `SD15Config` avec chemin absolu explicite vers le modèle déjà téléchargé.
  Paramètres qualifiés : 512 × 512, 20 étapes, délai 120 s, seed par défaut 42.
- Frontière `IsolatedImageRunner` : reçoit config/demande, restitue PNG/statut
  du filtre. Sans runner injecté, l'adaptateur refuse d'exécuter. Il ne charge
  ni PyTorch ni Diffusers, ne télécharge rien et n'appelle aucune API externe.
- Présence des fichiers locaux, notamment filtre, contrôlée avant délégation.
  Ce contrôle n'est pas une validation cryptographique des poids.
- Résultat refusé si filtre bloquant ou statut absent, mauvais PNG, dimensions
  incorrectes, taille >8 Mio (limite P19) ou versions incohérentes.
- Codes stables pour erreurs/timeout ; exceptions moteur masquées, aucun retry.
- `image_worker.py` : tâche explicite avec IDs utilisateur/rêve/job et snapshot
  de description. Contrôle de validité avant/après calcul avec moteur injecté.
  Aucune boucle, connexion DB, route ou génération automatique.

## Raccordements préparés, pas encore implémentés

Le faux moteur n'est pas un fournisseur de production. Le runner CUDA réel,
la surveillance système et l'application effective du délai restent à raccorder
au worker image séparé, dans son environnement distinct de celui de P05.
Le maintien du filtre doit être vérifié dans ce runner, pas seulement déclaré
dans sa réponse. Les scripts de qualification restent une référence séparée.

Les jobs PostgreSQL existants ont `kind=image`, `expected_text_version`,
`claim_token`, `lease_until` et les états queued/running/done/failed. Prévoir une
nouvelle migration additive pour le snapshot privé de description, sa version,
et la version source du récit ; ne pas modifier les migrations P05/P06.
Prévoir un index unique pour un job image actif par rêve et des réservations
expirables filtrées exclusivement sur `kind=image`, distinctes de P05.

La création d'un job devra être une action explicite authentifiée, avec CSRF
sur le navigateur. L'interface de description modifiable et sa persistance ne
sont pas encore développées. Une correction P06 rendra un ancien snapshot
inutilisable jusqu'à confirmation de la description pour la nouvelle version.

Publication future : reverrouiller le job et le rêve, vérifier propriétaire,
état non supprimé, bail/token et versions récit/description dans la transaction
qui référence le média. Les deux contrôles du noyau actuel ne suffisent pas à
eux seuls contre une course entre contrôle et publication.
Réutiliser les clés opaques/validation PNG/compensations P19, avec coordination
transactionnelle adaptée ; un appel naïf à `MediaService.store` suivi d'un
contrôle de version tardif serait insuffisant. Aucun fichier avant validation
du filtre, aucun média obsolète visible, nettoyage compensable en cas d'échec.
Réutiliser les routes privées P19 pour la lecture par le propriétaire, jamais
le dossier static. Aucun de ces raccordements n'est actif dans cette phase.

## Validation Windows exécutée

Depuis la racine :

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_image_provider.py backend/tests/test_api.py backend/tests/test_stt_provider.py backend/tests/test_text_rules.py -q
.\.venv\Scripts\python.exe -m ruff check backend
git diff --check
```

Résultat final : 58 tests réussis, Ruff et diff-check réussis. Première passe :
57 succès, 1 échec dû à l'import indirect de la configuration DB via le module
stockage ; dépendance supprimée et test d'import isolé désormais réussi.
Tests image exclusivement synthétiques, sans modèle, GPU ni réseau.
Vérifiés : descriptions/versions, absence de traduction, PNG et dimensions,
filtre obligatoire, modèle manquant, timeout, erreurs masquées, absence de retry,
conflits avant/après calcul, imports sans IA ni DB.
Pas de test PostgreSQL, navigateur ou génération réelle dans cette phase.
Les fichiers et comportements existants P05/P06/P19 restent inchangés.

P07 n'est pas terminé : l'image réellement générée dans l'application,
sa publication atomique, le worker persistant et les parcours web seront
validés dans les phases suivantes, après accord utilisateur.
