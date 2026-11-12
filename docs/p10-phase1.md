# P10 — Phase 1 : contrat d'export et sécurité

## Périmètre

Cette phase ne crée aucune archive, aucun téléchargement ni page HTML. Elle ne
modifie pas la suppression et n'exécute aucune purge. Aucun modèle IA n'est
chargé. Aucune migration n'est nécessaire et aucune base personnelle n'est
utilisée pour les tests.

## Interface réutilisable

`select_export(sessions, user_id, dream_id, limits=...)` ouvre une transaction
PostgreSQL REPEATABLE READ / READ ONLY dédiée. L'identité devra provenir de
l'authentification Bearer ou de la session web dans la future route, jamais d'un
champ utilisateur. Le service ne constitue pas lui-même une authentification.
Un rêve inconnu, supprimé ou étranger produit le même HTTP 404 générique.

La transaction donne un instantané cohérent des tables. Elle n'appelle pas les
projections P08 qui créent paresseusement des métadonnées, ni les projections
P07 qui verrouillent le rêve en écriture. Elle n'écrit aucune donnée.

`ExportSelection` contient une sérialisation immuable et une empreinte interne.
`documents()` produit uniquement quatre documents en mémoire, pas un ZIP :

```text
README.txt
recit.txt
reve.json
manifest.json
medias/                  # entrées prévues ; aucun fichier lu ou copié ici
```

## Champs publics autorisés

- Format version 1, un seul UUID de rêve, récit courant nullable, version P06,
  dates UTC et état du rêve.
- Émotion retenue, origine P08 et version du récit associée au choix.
  En l'absence de métadonnées : `legacy` pour une valeur existante, `unset`
  pour NULL, sans créer de ligne en base.
- Dernier résultat de suggestion terminé du rêve et du propriétaire : émotion
  ou abstention, version analysée, indicateur de péremption et mention indicative.
  Le résultat est revalidé ; un objet fournisseur malformé est remplacé par
  `invalid_result`, jamais exporté brut. Un instantané d'un autre compte est exclu.
- Description visuelle courante, sa version et celle du récit, indicateur périmé.
- Médias strictement filtrés par rêve : UUID, catégorie, type MIME, taille,
  empreinte, date, nom d'archive et état de disponibilité. Une image n'est marquée
  actuelle que si les versions P07, le propriétaire et les références concordent.

Les anciennes images restent listées sans être présentées comme actuelles.
Les suggestions sont indépendantes de l'émotion retenue. Une suggestion est
périmée si le texte/version ne correspond plus ou si elle n'est plus référencée
comme suggestion par les métadonnées P08. Une abstention n'est pas une émotion.
Les instantanés techniques P07/P08 ne sont pas un historique exhaustif : leur
texte et leurs paramètres bruts ne sont pas exportés.

Sont exclus : e-mail et UUID utilisateur, secrets, mots de passe, sessions,
tokens, clés de stockage, chemins, paramètres internes et réservations des jobs.
Les textes rédigés par l'utilisateur restent fidèlement exportés : le service
ne prétend pas retirer un secret qu'un utilisateur aurait lui-même écrit dans
son récit. L'exclusion concerne les champs techniques de l'application.

## Noms, limites et intégrité

Les noms sont fabriqués à partir d'une catégorie autorisée, d'un UUID typé et
d'une extension issue du type MIME reconnu : `medias/audio-<UUID>.wav`, etc.
Aucun nom original, chemin fourni, HTML/SVG ou segment `..` n'est accepté.
Les seuls noms racine sont les quatre noms fixes documentés ci-dessus.

Limites par défaut : 100 médias et 100 Mio de contenu décompressé, documents
TXT/JSON inclus. Les variables `EXPORT_MAX_MEDIA` et `EXPORT_MAX_BYTES` permettent
de réduire ces budgets, pas de dépasser ces plafonds. Une taille inconnue sur
un média ready est refusée. Les tailles connues de tous les médias sont comptées
de façon conservatrice, y compris s'ils ne seront pas inclus.
Le futur ZIP devra également borner la taille réelle de l'archive et ses frais
de structure : cette phase n'en produit pas et ne garantit pas sa taille finale.

Un média ready non expiré est `pending_verification`, jamais déclaré présent ou
intègre par une simple requête PostgreSQL. Les médias legacy, deleting, purged,
expirés ou de format non reconnu sont indisponibles. Les médias manquants sur
disque seront signalés par le lecteur P19 en phase 2 ; aucun disque privé n'est
consulté maintenant. `check_integrity` définit le contrôle du futur flux : lecture
par blocs, arrêt au premier octet excédentaire, comparaison taille et SHA-256.
Une erreur d'intégrité doit faire refuser l'export ; un fichier manquant doit
être signalé explicitement dans le manifeste. Aucun fichier non vérifié ne doit
être inclus silencieusement.

## Modifications concurrentes

`revalidate_export` resélectionne un instantané neuf pour le même propriétaire.
Suppression : 404. Changement du contenu exporté, des révisions de choix ou des
clés internes : `export_changed`. L'empreinte n'est ni un secret d'accès ni un
jeton de téléchargement et n'est pas incluse dans les documents.

La phase 2 devra revalider avant livraison, contrôler chaque média réellement
lu et nettoyer les fichiers temporaires. Cette revalidation ne ferme pas seule
la course avec une suppression après son retour. La coordination de livraison,
l'authentification des routes, le CSRF web, les quotas simultanés, les délais,
l'espace disque et l'interruption des longs flux restent à implémenter.

## Tests reproductibles sans données personnelles

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --export-only
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

Le lanceur crée un cluster PostgreSQL local temporaire, injecte son URL de test,
applique les migrations dans les schémas jetables puis arrête le cluster et
supprime son dossier. Il n'utilise pas dreams_local. La sélection de tests inclut
P10 ainsi que P06/P07/P08/P09/P19 sans fournisseur réel. Le CSS local préexistant
est préservé. Aucune opération Git d'écriture, aucun push ou changement Jira.

### Résultats de validation

Campagne finale sur PostgreSQL temporaire : **105 tests réussis en 52,10 s**,
aucun test ignoré ni échec. Elle remplace la première campagne de 99 tests,
réussie avant ajout de six cas de sécurité. Ruff backend/scripts réussit ;
git diff --check réussit (avertissements LF/CRLF seulement). Une ligne trop
longue détectée par Ruff a été corrigée. Aucun test de ZIP, HTTP ou navigateur
P10 n'est revendiqué : ces composants n'existent pas encore dans cette phase.
