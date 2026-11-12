# P10 — Phase 3 : retrait transactionnel d'un rêve

## Périmètre

Cette phase retire les accès et programme les purges. Elle ne supprime aucune
ligne PostgreSQL, n'efface aucun fichier et ne lance aucun worker IA ou de purge.
Les tables et contraintes existantes suffisent : aucune migration ajoutée.
La base personnelle n'est pas utilisée pour les tests.

## API et interface

- DELETE `/api/v1/dreams/{id}` : Bearer obligatoire, service partagé.
- GET `/reves/{id}/supprimer` : page de confirmation privée, aucune mutation.
- POST `/reves/{id}/supprimer` : session HTTPS, CSRF lié à la session, origine
  stricte et champ confirmation=`supprimer` obligatoires. Une case non cochée
  bloque aussi le formulaire HTML. Aucun choix par défaut ni suppression par GET.
- Le détail P09 propose **Supprimer ce rêve**. La confirmation présente le retrait
  d'accès immédiat, les traitements invalidés et le délai de purge physique.
  Annuler revient au rêve. Un succès redirige vers `/mes-reves` sans ajouter de
  paramètre non reconnu par la validation stricte P09.

L'identité provient exclusivement de l'authentification serveur. Un UUID inconnu
ou appartenant à un autre compte produit le même 404 générique. L'API sans
authentification ou avec un jeton invalide renvoie 401 ; le navigateur sans
session est redirigé vers la connexion. Une répétition autorisée sur un rêve
déjà supprimé renvoie 204 sans remettre à zéro sa date de suppression ni sa
révision. Cette idempotence ne révèle rien sur les rêves d'un autre compte.

## Transaction et concurrence

Le service `services/dream_deletion.py` possède la validation de la transaction :

1. Vérifier le propriétaire, sans verrou d'écriture sur le rêve.
2. Verrouiller les jobs du rêve dans l'ordre de leurs UUID, avec NOWAIT.
3. Verrouiller le rêve, avec NOWAIT, et revérifier son propriétaire.
4. Relire/verrouiller ses jobs : un job créé entre l'inventaire initial et le
   verrou du rêve est ainsi inclus. Les créations normales de jobs prennent
   elles-mêmes le verrou du rêve et ne peuvent plus s'intercaler ensuite.
5. Verrouiller ses médias puis ses métadonnées P08.
6. Marquer status=deleted, deleted_at ; terminer tous les jobs queued/running
   en failed avec error_code=dream_deleted ; supprimer les claim_token et
   lease_until. Les jobs terminés restent conservés, sans réservation.
7. Effacer active_request/suggestion_id P08 et incrémenter la révision nécessaire
   à l'invalidation. Le récit et l'émotion retenue ne sont pas effacés à cette phase.
8. Passer les médias P19 ready en deleting avec purge_requested_at.
9. Valider tout ensemble. Toute erreur provoque le rollback complet.

L'ordre job → rêve est compatible avec les publications P05/P07/P08. NOWAIT
évite qu'une seconde prise de verrou attende en tenant le rêve et crée un cycle
avec un worker. Un verrou occupé donne 409 : aucune suppression partielle,
aucun retry automatique ; l'utilisateur peut réessayer. Les délais SQL sont
10 s par instruction et 3 s de verrou. Une indisponibilité donne un 503 générique.
Une réponse de commit perdue peut laisser son résultat incertain pour le client :
la répétition idempotente permet de confirmer le retrait sans restauration.

Un calcul déjà lancé peut continuer en mémoire. Son job échoué, son ancien jeton
révoqué et l'état deleted lui interdisent de publier. Les tests utilisent des
faux fournisseurs qui déclenchent la suppression pendant le calcul : ni nouvelle
transcription, ni image, ni suggestion n'est publiée. L'arrêt forcé de processus
IA et l'effacement définitif des instantanés ne font pas partie de cette phase.

## Médias, exports et purge différée

Après le commit, les pages, API et médias du rêve sont refusés ; P09 l'exclut de
l'historique et de ses filtres, sans modifier les autres rêves ni les émotions.
Les liens P19 restent authentifiés et ne donnent plus un nouveau téléchargement.
La livraison média revérifie propriétaire, état du rêve, disponibilité et
expiration entre les blocs de 64 Kio, puis ferme le flux en cas d'interruption.
La réponse ferme aussi le descripteur si le navigateur part avant le premier bloc.
Les octets déjà reçus ne peuvent pas être rappelés ; une course après envoi des
en-têtes peut donc produire un flux tronqué, pas une nouvelle page HTTP d'erreur.

L'export conserve ses gardes de phase 2 : revalidation après préparation et avant
le premier bloc, contrôle du rêve et de la session entre blocs, nettoyage du ZIP.
La suppression n'attend pas la fin d'un export et ne prend pas son verrou global.
Une suppression pendant la préparation fait refuser la livraison ; après le début
de la livraison, le flux est interrompu lors du contrôle suivant.

Les médias déjà deleting ou purged ne sont pas remis à ready ; leurs dates sont
conservées. Le mécanisme P19 existant peut reprendre les lignes deleting lors
d'une maintenance explicitement lancée. Aucune maintenance n'est déclenchée par
ce service : la politique actuelle de purge n'est pas modifiée.

Cas legacy : les références sans clé P19/métadonnées valides sont immédiatement
inaccessibles via le rêve supprimé, mais ne sont pas transformées artificiellement
en clés gérées. Les contraintes actuelles interdiraient un simple passage en
deleting ; un chemin arbitraire ne doit jamais être effacé. La demande durable
est portée par deleted_at du rêve. L'identification/résolution de ces anciennes
références devra être traitée explicitement en phase 4, sans promettre leur purge
automatique par la maintenance P19 actuelle. Aucun fichier legacy n'est ouvert
ou supprimé pour programmer le retrait.

Les récits, utilisateurs, relations, instantanés P07/P08 et fichiers existent
encore après le retrait. La phase 4 devra définir l'effacement des dépendances,
les reprises, les contrôles des fichiers purgés et la conservation des sauvegardes.

## Validation sans données personnelles

```powershell
# PostgreSQL temporaire, faux fournisseurs, fichiers fictifs :
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --deletion-only
# Suite complète, couverture, confirmation Chrome bureau/mobile :
.\.venv\Scripts\python.exe scripts/verify_p20.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

Les tests couvrent l'atomicité/rollback après flush, les lignes verrouillées,
deux suppressions concurrentes, un job inséré pendant l'inventaire, les droits
intercomptes, les GET non mutateurs, le CSRF, les anciennes URL, l'idempotence,
les résultats tardifs et doublons, les baux expirés, le maintien des autres
rêves/médias, et les suppressions pendant export ou lecture média.

## Vérification manuelle Chrome après validation

Utiliser exclusivement un nouveau rêve fictif sur l'instance autorisée :

1. Noter son UUID et ses liens média, vérifier qu'un autre rêve reste visible.
2. Ouvrir le détail, cliquer Supprimer ce rêve, puis Annuler : le rêve doit rester.
3. Revenir à la confirmation ; sans cocher la case, aucun retrait ne doit avoir lieu.
4. Cocher et confirmer : retour à Mes rêves, rêve absent, autres rêves présents.
5. Recharger l'ancien détail et les anciens liens médias/export : accès refusé.
6. Refaire sur un second rêve fictif avec une largeur mobile de 390 px.

Ne pas supprimer de rêve réel pour cette validation. Aucun test manuel sur la
base personnelle n'a été effectué ; les navigateurs automatisés utilisent les
seules instances temporaires du lanceur. Aucun commit, push ou changement Jira.

## Rapport de validation

| Vérification exécutée | Résultat |
|---|---|
| Première campagne ciblée PostgreSQL | 138 réussis en 112,82 s |
| Suite complète finale avec les derniers cas de concurrence | 543 réussis, 1 ignoré en 300,24 s |
| Couverture backend | 88,81 % ; seuil requis 80 % |
| Service de suppression | Couverture 96 % |
| Tests phase 3 inclus dans la suite finale | 22 PostgreSQL/HTTP/services et 1 Chrome bureau/mobile |
| Ruff backend/scripts | Réussi |
| Syntaxe de tous les JavaScript publics | Réussie |
| Compilation Tailwind locale | Réussie en 146 ms vers tmp/p10-phase3-tailwind.css |
| git diff --check | Réussi ; avertissements LF/CRLF seulement |

Le test ignoré est l'inférence émotion réelle opt-in, conformément au périmètre.
Aucun fournisseur réel n'a été exécuté. Le scénario Chrome vérifie annulation,
case obligatoire, confirmation, disparition de l'historique, accès refusé à
l'ancien média et au détail, maintien du rêve témoin et des fichiers en attente
de purge. Les deux derniers tests PostgreSQL vérifient un job inséré entre le
premier inventaire et le verrou du rêve, et un échec après flush avant commit :
toutes les mutations sont alors annulées.

La recette a aussi confirmé la persistance P09 et la relecture P04/P19 après
redémarrage PostgreSQL/Uvicorn temporaires. Ses tests P19 purgent seulement leurs
propres fichiers fictifs ; la suppression P10 ne lance aucune purge physique.
La comparaison AST avec HEAD confirme inchangés request_purge, _finish_purge,
reconcile, LocalPrivateStorage.delete et media_maintenance.main.

### Fichiers de phase 3

Créés :

- backend/app/services/dream_deletion.py
- backend/app/deletion_routes.py
- backend/app/web/templates/delete_dream.html
- backend/tests/test_dream_deletion.py
- backend/tests/test_deletion_browser.py
- docs/p10-phase3.md

Modifiés :

- backend/app/dream_routes.py : DELETE existant raccordé au service partagé.
- backend/app/main.py : inclusion des routes de confirmation web.
- backend/app/media_routes.py : revalidation entre blocs et fermeture après interruption.
- backend/app/services/media.py : contrôle frais des droits d'accès au média.
- backend/app/web/templates/dream_detail.html : lien vers la confirmation.
- scripts/verify_image_jobs.py : option --deletion-only, PostgreSQL temporaire.

Les fichiers des phases 1 et 2 restent présents et ne sont pas recommencés.
Le CSS préexistant frontend/styles/app.css (767 → 1023 px) est intact et exclu
du périmètre P10. Aucun CSS public compilé remplacé, aucune dépendance nouvelle,
aucune migration. La revue des candidats Git ne détecte aucun ZIP, média,
poids de modèle, sauvegarde ou secret ; l'index reste vide.

### Limites restantes et validation demandée

Le retrait est effectif après commit réussi, pas après une réponse 409 ou 503.
Un calcul déjà démarré peut continuer mais son résultat ne peut plus publier.
Les données SQL et les fichiers ne sont pas encore définitivement effacés.
Les références legacy demandent une résolution sûre séparée, avant toute purge.
Les sauvegardes et copies déjà téléchargées ne sont pas supprimées par ce retrait.
La phase 4 ne doit commencer qu'après validation explicite de cette phase.
