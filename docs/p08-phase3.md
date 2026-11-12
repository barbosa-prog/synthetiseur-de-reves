# P08 — Phase 3 : persistance, API et noyau de jobs

## Décision métier appliquée

Cette phase remplace la règle automatique envisagée en phase 1 : publish ne
modifie JAMAIS le choix retenu, même s'il est absent. dreams.emotion n'est
écrit que par une correction explicite, une acceptation ou un retrait demandé.
Une abstention reste une suggestion sans valeur, impossible à accepter comme
neutre ou autre. Aucune attribution n'a lieu à la création d'un rêve.

Les suggestions sont expérimentales et facultatives. La saisie manuelle
n'utilise aucun fournisseur, modèle ou worker. L'API rappelle le caractère
indicatif et non médical ; son affichage obligatoire dans l'interface reste
à développer dans une phase ultérieure.

## Reprise et fichiers

À la reprise, la phase 3 avait déjà commencé dans models.py,
emotion_rules.py, test_emotion_contract.py et la nouvelle migration 0008.
Leurs changements corrects sont conservés. Les autres fichiers P08 non suivis
étaient issus des phases précédentes. frontend/styles/app.css avait déjà son
changement de breakpoint 767 → 1023 ; il est préservé et reste hors P08.

Créés pour cette phase :

- backend/app/emotion_routes.py
- backend/app/services/emotions.py
- backend/migrations/versions/0008_emotion_suggestions.py
- backend/tests/test_emotion_postgresql.py
- docs/p08-phase3.md

Adaptés : models.py, emotion_rules.py, auth_schemas.py, dream_routes.py,
main.py, services/transcripts.py ; tests test_emotion_contract.py,
test_postgresql.py et test_image_jobs.py ; scripts/verify_image_jobs.py.
Les deux anciens tests de migration attendent désormais la tête 0008.
Aucun code des moteurs STT/image ni leur worker n'est changé.

## Migration additive 0008, après 0007

dreams.emotion et les tables P05/P07 sont conservés. Les migrations 0001–0007
ne sont pas modifiées.

- dream_emotions : relation 1:1 au rêve, origine du choix, révision optimiste,
  version du récit lors du choix, demande en cours, suggestion courante,
  date de modification. FK vers les jobs, sans token de réservation public.
- emotion_analyses : relation 1:1 au job ; propriétaire, instantané privé du
  récit, text_version, révision du choix au lancement, configuration JSONB
  et résultat validé séparé. Les résultats passés restent conservés, même
  lorsque le pointeur de suggestion courante est invalidé.
- jobs : ajout du type emotion et index unique partiel empêchant deux jobs
  queued/running pour le même rêve ; types stt/image/tts conservés.

La reprise des données existantes initialise source=legacy pour une émotion
non NULL et unset sinon. Aucune valeur n'est reclassée ou modifiée.
La version historique de sélection étant inconnue, selected_text_version
reste NULL pour legacy, sans inventer une ancienne version de récit.
Les nouveaux rêves obtiennent leurs métadonnées paresseusement, sous verrou.

Origines possibles : unset, manual, accepted, withdrawn et legacy. Aucun état
automatic n'est accepté. Les versions/sources sont validées par les règles
métier ; PostgreSQL impose sources permises, révisions positives, FK, types
JSON et bornes des instantanés.

Le downgrade ne supprime jamais implicitement des jobs P08 ou une provenance
ayant été modifiée : il REFUSE si un job emotion existe ou si une métadonnée
est révisée/manuelle/acceptée/retirée. Un aller-retour sans données P08 nouvelles
est possible. La garde de refus est testée dans une transaction isolée.
L'upgrade et les tests aller-retour n'ont été exécutés que sur des clusters
temporaires ; aucune migration personnelle autorisée ou appliquée.

## Transactions, versions et reprises

Les mutations et demandes verrouillent le rêve par propriétaire. Les traitements
verrouillent d'abord le job puis le rêve, dans un ordre commun. Aucun verrou
de base n'est conservé pendant l'appel fournisseur. Réservations via SKIP LOCKED,
token opaque interne, bail et maximum trois tentatives. Les expirations sont
reprises par claim ; une ancienne réservation ne peut terminer la nouvelle.

Avant publication : vérifier type/statut du job, token et bail valides,
propriétaire du snapshot égal au propriétaire courant, rêve non supprimé,
texte/version identiques, demande courante et révision émotionnelle identiques,
identifiant/version du résultat et moteur/révision conformes au snapshot.
La validation, l'écriture du résultat, le pointeur courant et la fin du job
sont dans UNE transaction. Aucune écriture de fichier média n'est nécessaire.
La publication ne remplace jamais dreams.emotion.

Toute correction/retrait/acceptation augmente la révision, même à valeur égale.
Un retrait NULL reste withdrawn, jamais unset par défaut. Une nouvelle
suggestion n'annule pas ce retrait ; l'utilisateur doit agir explicitement.
Les corrections P06 réelles (texte différent) invalident la suggestion et la
réservation, augmentent la révision et conservent le choix, sa provenance et
sa version de sélection. Un simple réenregistrement du même texte ne change
pas les versions. Le service P06 partagé couvre l'éditeur, l'API et la
publication STT. P07 conserve ses propres contrôles de version.

Une mutation du choix peut rendre un job actif périmé ; son statut projeté
l'indique immédiatement. Il n'est pas forcé à terminer sous le verrou du rêve,
ce qui évite un ordre de verrou inverse. claim ou finish le termine sans
publication ; le propriétaire peut aussi l'annuler pour libérer la place.
Annuler ne supprime pas les instantanés, n'efface pas un choix et ne publie rien.

Pannes fournisseur, sortie invalide, timeout signalé et arrêt signalé produisent
des codes stables sans message brut du fournisseur. Une interruption non
interceptée laisse un bail à reprendre. Aucun ordonnanceur ou vrai worker IA
n'est démarré ici. run_once est uniquement un noyau injectant un fournisseur,
exercé avec le faux moteur ; il n'impose pas de timeout système à lui seul.
Le futur processus isolé/surveillant relèvera de la phase suivante autorisée.

## API Bearer

| Méthode | Route | Action |
|---|---|---|
| GET | /api/v1/dreams/{id}/emotion | Choix, provenance, versions, suggestion courante et avertissement |
| PUT | /api/v1/dreams/{id}/emotion | Choix explicite ou retrait NULL, expected_revision obligatoire |
| POST | /api/v1/dreams/{id}/emotion/suggestions | Demande, expected_text_version et expected_revision obligatoires ; 202 |
| POST | /api/v1/dreams/{id}/emotion/accept | Accepter suggestion_id courant, expected_revision obligatoire |
| GET | /api/v1/emotion-jobs/{id} | Statut, tentatives, code stable et indicateur stale |
| DELETE | /api/v1/emotion-jobs/{id} | Annulation propriétaire, 204 ; aucune suppression de données |

L'ancien PATCH /api/v1/dreams/{id} utilise le même service : toute mutation
emotion exige expected_emotion_revision (409 si absent ou périmé). La révision
s'obtient par le GET émotion ci-dessus. Un PATCH conjoint texte/émotion vérifie
la révision initiale et applique les deux actions atomiquement. Les PATCH de
récit seuls gardent le contrat P06 existant.

401 sans Bearer valide ; cookie seul refusé. 404 identique pour autre compte,
UUID absent ou rêve supprimé. Aucun user_id accepté dans les requêtes. Routes
non mises en cache. Les projections ne renvoient ni instantané du récit, ni
configuration privée, ni chemin local, ni jeton de réservation. Un UUID de job
n'est pas un secret d'authentification. Pas de nouveau formulaire navigateur
ou authentification cookie : pas de nouvelle surface CSRF dans cette phase.
La future interface réutilisera les contrôles CSRF P20.

Les paramètres par défaut figent la révision publique du candidat mDeBERTa et
du tokenizer déjà qualifiés, mais inference_enabled=False et stratégie non
configurée. Aucune politique 2C n'est présentée comme retenue pour production.
Une demande API peut être persistée, mais aucun moteur ne la traite ici.
Les tests injectent une configuration fake/1 fixe ; sa sortie ne peut être
publiée comme provenant d'un autre moteur ou d'une autre révision.

## P09 et confidentialité

P09 continue de lire exactement dreams.emotion ; NULL reste non_renseignee,
distinct de neutre. Une suggestion seule ne modifie aucun filtre. Une
acceptation/correction explicite alimente ensuite ce même filtre SQL.
Les choix historiques restent inchangés. Les snapshots sont des copies de
récits privés en PostgreSQL : les futures opérations de rétention/purge
devront les prendre en compte. Aucun contenu n'est journalisé ni transmis.

## Validation Windows

Uniquement les recettes qui créent leurs propres services temporaires :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --emotion-only
.\.venv\Scripts\python.exe scripts/verify_p20.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

Ne pas appliquer alembic upgrade head à votre base personnelle sans validation.
La suite vérifie la cohérence modèles/migration, aller-retour et reprise legacy,
contraintes PostgreSQL, conservation après reconnexion, accès anonymes et
intercomptes, concurrence réelle de demandes/réservations, résultats périmés ou
dupliqués, expiration/reprise, correction en cours de calcul, abstention,
acceptation explicite, retrait, erreurs fournisseur et compatibilité P06/P07/P09.
Les timeouts et arrêts fournisseur sont simulés par codes ; aucune mesure ou
inférence MiniLM/mDeBERTa n'est réalisée dans cette phase.

Résultats réellement exécutés :

- Ciblés P08 + cohérence/migrations PostgreSQL : 75 réussis en 19,75 s,
  aucun ignoré, faux fournisseur uniquement.
- Campagne complète finale backend et navigateur : 441 réussis en 242,99 s,
  aucun échec ni test ignoré ; couverture backend 90,62 % (seuil 80 %).
- Historique P09 identique après redémarrage réel PostgreSQL/Uvicorn jetables ;
  audio P04 relu, média P19 relu puis purgé et refusé en HTTP.
- Ruff backend/scripts réussi ; git diff --check réussi avec avertissements
  habituels LF/CRLF uniquement ; tête Alembic unique 0008.

La campagne intermédiaire de 437 tests passait également avant les contrôles
complémentaires d'annulation/acceptation ; un avertissement TestClient cookies
dans un test a été corrigé. La campagne finale n'a pas cet avertissement.
Les services temporaires sont arrêtés et les journaux ignorés par Git.

Le code P08 requiert le schéma 0008, y compris pour l'invalidation P06 : ne
pas utiliser cette version avec la base personnelle restée en 0007 avant
autorisation et application de la migration. Les tests prouvent la compatibilité
P06/P07/P09 sur le schéma migré temporaire, pas sur une base personnelle non migrée.
Aucun commit, push ou changement Jira. Phase 4 soumise à validation.
