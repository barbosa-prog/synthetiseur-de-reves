# P10 — Phase 4 : purge définitive et reprise explicite

## Périmètre et déclenchement

La suppression utilisateur (phase 3) retire l'accès immédiatement ; elle ne
déclenche pas cette maintenance. Le nouveau `scripts/dream_maintenance.py` est
une commande d'administration locale, sans route HTTP ni tâche au démarrage.
Son mode par défaut est un inventaire SQL sans écriture ni suppression de fichier.
Le lanceur P19 `media_maintenance.py` reste inchangé : sa politique, ses orphelins
et ses délais ne sont pas remplacés par P10.

Le service ne traite que les rêves dont status=deleted et dont le propriétaire
correspond à l'identifiant attendu. Un rêve vivant, inconnu, déjà purgé ou d'un
autre propriétaire renvoie not_found sans effacement. L'inventaire parcourt au
maximum 20 rêves par passage par défaut ; --limit accepte 1 à 100. Relancer la
commande est une décision explicite ; aucun worker IA n'est démarré.

## Préconditions et contrôles de références

DATABASE_URL et PRIVATE_MEDIA_ROOT doivent être explicitement présents dans
l'environnement de la commande. Celle-ci n'adopte pas le .env personnel ni la
racine de médias par défaut. L'application exige aussi --confirm-database égal
au nom de la base configurée. Cela protège contre une invocation implicite ;
l'opérateur doit toujours vérifier que la base et sa racine de stockage forment
la paire autorisée. Il n'existe pas de liaison cryptographique entre une base
et une racine dans le schéma actuel. Ne jamais pointer une base de recette
restaurée vers le stockage privé personnel.

Avant tout unlink :

- autorisation par propriétaire et état supprimé, puis verrous jobs → rêve →
  relecture des jobs → médias → métadonnées/snapshots ; prises de ligne NOWAIT ;
- vérification des médias référencés par les jobs du rêve et des jobs étrangers
  référençant ses médias ;
- vérification des références active_request/suggestion_id, entrantes et sortantes ;
- vérification du propriétaire des snapshots ImageGeneration/EmotionAnalysis ;
- contrôle des clés gérées et de toutes les cibles physiques avant le premier
  effacement : racine P19 approuvée hors dépôt/OneDrive, pas de symlink/jonction,
  fichier régulier, pas de lien physique partagé.

Une référence croisée bloque le rêve entier avec cross_reference. Aucune
réparation automatique, aucun effacement du rêve voisin et aucune cascade SQL.
Les verrous FOR UPDATE sur les cibles de clés étrangères empêchent de créer
une nouvelle référence vers elles pendant la transaction d'effacement.

Tous les médias legacy bloquent la purge avec legacy_media, même si leur clé
ressemble à une clé P19. Un chemin absolu ou ../ n'est jamais interprété pour
effacer un fichier. Il faudra résoudre ces références séparément, avec preuve
de provenance et autorisation explicite ; aucune conversion automatique n'est
incluse. Le retrait applicatif reste effectif pendant ce blocage.

## Déroulement et reprise

1. Dans une première transaction, contrôler le graphe et réutiliser le service
   phase 3 pour confirmer le retrait, invalider les réservations et programmer
   les médias ready en deleting. Cela rattrape aussi les anciens DELETE.
2. Ouvrir une nouvelle transaction et revérifier/verrouiller tout le graphe.
3. Prendre les verrous de stockage P19 partagés avec publication/maintenance.
4. Effacer chaque objet principal et son staging .tmp de même clé, dans la seule
   racine approuvée. Un objet déjà absent est un succès idempotent.
5. Confirmer l'absence après chaque effacement par is_absent. Un refus d'accès,
   un fichier encore présent ou une cible dangereuse n'est jamais une absence.
   Seulement alors passer le média en purged, valider ses contraintes par flush.
6. Effacer, sans cascade : DreamEmotion, EmotionAnalysis, ImageGeneration,
   ImageDescription, Job, Media, puis Dream. Users et sessions ne sont pas supprimés.
7. Valider la transaction finale. Les dates/états P19 intermédiaires disparaissent
   avec leurs lignes ; le rêve n'est enlevé qu'après toutes les confirmations.

Un arrêt entre unlink et commit laisse les médias deleting et le rêve deleted
en base : les fichiers déjà absents sont reconnus au passage suivant. Un échec
du commit final annule les effacements SQL, pas les unlinks déjà faits ; les
snapshots restent inaccessibles et le passage suivant reprend sans restaurer
les fichiers. Une coupure après commit mais avant compte rendu donne au passage
suivant not_found : aucune seconde suppression hors périmètre.

Il n'y a pas de journal contenant le récit. La demande durable reste le rêve
deleted et les états P19, jusqu'au commit final. La sortie est limitée aux
compteurs et codes : eligible, purged, not_found, cross_reference, legacy_media,
storage_failed, file_remaining, busy, database_failed ou timeout. Aucun UUID,
e-mail, chemin privé, jeton ou contenu de rêve n'est journalisé par la commande.

## Délais, conflits et téléchargements

Délais SQL : 10 s par instruction, 3 s de verrou. Le traitement des fichiers et
la finalisation ont un budget coopératif de 60 s par rêve ; les contrôles entre
opérations ne peuvent pas interrompre un appel disque Windows bloqué dans l'OS.
Les conflits de ligne ou de verrou P19 font échouer/reporter la transaction,
sans boucle de retry interne. Un passage peut traiter d'autres rêves supprimés
indépendants ; le rapport indique les blocages et le code de sortie 2.

Sous Windows, un téléchargement qui garde le fichier ouvert peut empêcher
l'unlink : le média reste deleting, le rêve reste deleted et la purge reprend
après fermeture du flux. Sous POSIX, l'unlink peut réussir alors que le processus
possède encore un descripteur. Les gardes phase 3 interrompent sa prochaine
lecture ; les octets déjà reçus ne peuvent pas être rappelés.

Un export déjà construit ne bloque pas la purge : avant livraison et entre
blocs, il constate l'absence du rêve et supprime son temporaire. Les exports
abandonnés restent soumis au nettoyage privé de phase 2, pas au balayage P19.
Les workers peuvent finir leur calcul en mémoire ; leurs réservations sont
révoquées et les gardes de publication refusent les résultats. P05/P07/P08
tolèrent aussi la disparition des lignes entre réservation, calcul et retour.
L'effacement forcé de leur mémoire ou leur arrêt OS n'est pas promis.

## Sauvegardes et restauration

La commande n'efface aucune sauvegarde, aucun volume Docker ni journal WAL.
Le retrait concerne les lignes actives et les fichiers accessibles au stockage,
pas un effacement forensic des blocs disque, de RAM ou des anciens backups.
La sauvegarde personnelle vérifiée reste inchangée par ce développement.

Politique locale proposée : maintenance explicite après les suppressions,
puis inventaire jusqu'à disparition des blocages ; aucune garantie de délai
calendaire lorsque le PC est arrêté. Conserver les sauvegardes dans un répertoire
privé avec accès restreint, définir séparément leur rétention et leur effacement
autorisé. Privilégier une nouvelle sauvegarde après purge avant d'expirer les
anciennes ; aucune expiration automatique n'est ajoutée ici.

Une restauration ancienne peut réintroduire des rêves purgés. La restaurer
d'abord en environnement isolé, sans worker et sans pointer sur les médias
personnels ; réappliquer les demandes de suppression connues avant toute remise
en service. Le service ne possède pas de registre externe exhaustif après purge :
sans trace fiable des suppressions, il ne peut pas garantir qu'une ancienne
sauvegarde respecte ces retraits. La remise en ligne exige alors une revue et
une autorisation distinctes ; ne pas présenter la restauration comme automatique.

## Commandes Windows

Ces commandes sont préparées pour une base ET un stockage temporaires autorisés,
jamais exécutées sur dreams_local pendant cette phase. Ne pas remplacer les
valeurs sans vérifier la paire base/stockage et son autorisation.

```powershell
$env:DATABASE_URL = '<URL postgresql+psycopg de la base temporaire autorisée>'
$env:PRIVATE_MEDIA_ROOT = '<chemin absolu du stockage fictif associé>'

# Inventaire seul, sortie JSON de compteurs, aucun effacement :
.\.venv\Scripts\python.exe scripts/dream_maintenance.py --limit 20

# Application explicite ; remplacer NOM_BASE_TEMPORAIRE par le nom exact :
.\.venv\Scripts\python.exe scripts/dream_maintenance.py --apply `
  --confirm-database NOM_BASE_TEMPORAIRE --limit 20
```

Codes de sortie : 0 passage sans blocage, 2 blocage/reprise nécessaire,
1 configuration/connexion refusée ou indisponible, 130 interruption Ctrl+C.
Un inventaire eligible signifie graphe SQL admissible ; il ne promet pas que
le disque est accessible ou que tous les fichiers existent. Seul le mode apply
vérifie les cibles physiques et confirme leurs effacements.

Pour reproduire les tests sans configuration personnelle :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --purge-only
.\.venv\Scripts\python.exe scripts/verify_p20.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

Les lanceurs fournissent eux-mêmes PostgreSQL, schémas, stockage et HTTPS
temporaires. Aucun moteur IA réel n'est utilisé. Aucun déploiement personnel,
commit, push ou changement Jira ne fait partie de cette phase.

## Rapport de validation

| Vérification réellement exécutée | Résultat |
|---|---|
| Première campagne ciblée PostgreSQL temporaire | 108 réussis en 63,71 s |
| Suite complète finale avec le cas de téléchargement ouvert | 572 réussis, 1 ignoré en 333,93 s |
| Couverture backend | 89,07 % ; seuil 80 % |
| Couverture du service de purge | 93 % |
| Tests spécifiques de phase 4 dans la campagne finale | 29 réussis |
| Ruff backend/scripts | Réussi |
| Syntaxe de tous les JavaScript publics | Réussie |
| Compilation Tailwind locale | Réussie en 182 ms vers tmp/p10-phase4-tailwind.css |
| git diff --check | Réussi ; avertissements LF/CRLF seulement |

Le seul ignoré est l'inférence émotion réelle opt-in. Aucun modèle réel ni GPU
n'a été utilisé. Tous les essais PostgreSQL et fichiers concernent la recette
temporaire et des données fictives. Les tests P19 de non-régression conservent
leurs opérations de purge fictive habituelles ; aucune donnée personnelle n'est
consultée ni purgée. La campagne Chrome existante, les exports et la suppression
phase 3 passent aussi. La recette confirme P09 et la lecture audio/média après
redémarrage réel PostgreSQL/Uvicorn temporaires, puis nettoie ses services.

Les tests vérifient :

- audio, image, récit, jobs STT/image/émotion, description P07, snapshots et
  résultats P08 présents avant purge, puis absents après validation ;
- autres rêves du compte et d'un autre compte, utilisateurs, sessions, médias
  et jobs témoins conservés ;
- interruption après unlink et échec avant commit final, avec rollback SQL,
  nouvelles connexions et reprise réussie ;
- deuxième purge sûre, absence initiale de fichier, permission refusée simulée,
  faux succès d'un adaptateur delete sans effacement ;
- six incohérences de références entrantes/sortantes et propriétaires de snapshots,
  bloquées avant le premier unlink ;
- legacy, chemins dangereux, liens physiques partagés et cible refusée ;
- verrous job/rêve/média, export ouvert, téléchargement ouvert, retours tardifs
  des faux fournisseurs STT/image/émotion ;
- anciennes URL refusées et inventaire sans aucune instruction de mutation SQL ;
- refus du CLI sans DATABASE_URL, sans racine de stockage explicite ou sans
  confirmation du nom de base ; compte rendu limité aux compteurs/codes.

Le cas téléchargement ouvert accepte les deux comportements OS sûrs : unlink
effectif, ou storage_failed sans faux marquage purged. Dans ce second cas, la
fermeture du flux permet une reprise réussie.

### Fichiers de phase 4

Créés :

- backend/app/services/dream_purge.py
- scripts/dream_maintenance.py
- backend/tests/test_dream_purge.py
- docs/p10-phase4.md

Modifiés :

- backend/app/storage/local.py : is_absent et contrat PrivateStorage, absence
  confirmée et refus des liens physiques partagés.
- backend/app/services/stt_jobs.py : retour tardif avec job disparu/bail absent.
- backend/app/services/image_execution.py : réservation dont le job/snapshot a disparu.
- backend/app/services/emotions.py : réservation dont le job a disparu.
- scripts/verify_image_jobs.py : option --purge-only sur PostgreSQL temporaire.

Les fichiers des phases précédentes sont conservés. La comparaison AST avec
HEAD confirme inchangés les méthodes P19 request_purge, _finish_purge, reconcile
et l'ancien CLI media_maintenance.main. Le CSS local préexistant
frontend/styles/app.css (767 → 1023 px) est intact, hors périmètre P10. Aucun CSS
public remplacé ni nouvelle dépendance. L'index Git reste vide ; aucun candidat
ZIP, média, modèle, sauvegarde ou secret détecté par la revue. Aucun commit,
push ou changement Jira.

### Procédure de validation finale proposée

Après validation de cette phase, utiliser exclusivement une nouvelle recette
PostgreSQL et son stockage fictif, jamais une base restaurée pointant sur les
médias personnels : créer le graphe fictif, supprimer logiquement, contrôler
l'inventaire, appliquer explicitement, puis vérifier SQL, fichiers et anciens
liens. Les lanceurs automatisés ci-dessus ont déjà réalisé ces contrôles.
L'utilisation sur dreams_local exigerait une autorisation distincte, un contrôle
de la paire base/stockage et la validation de la politique de sauvegardes.
La phase 5 n'est pas commencée.
