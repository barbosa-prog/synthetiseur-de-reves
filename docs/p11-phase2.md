# P11 — Phase 2 : persistance, relances et maintenance

## Périmètre

Services internes PostgreSQL, migration additive et maintenance sans IA. Aucune nouvelle
route publique, aucun écran de relance, aucun lancement de modèle, aucune migration
personnelle. Le raccordement des créations et des boucles des workers est réservé à la
phase suivante. Les services P05/P07/P08 conservent leurs réponses existantes.

## Migration 0008 → 0009

Quatre colonnes sont ajoutées à `jobs`, sans nouvelle table :

| Colonne | Usage et reprise historique |
| --- | --- |
| `retry_count` | Relances explicites de cette ligne ; défaut 0, contrainte 0..2 |
| `queued_at` | Dernière mise en attente ; initialisée à `created_at` pour l'historique |
| `cycle_key` | SHA-256 des entrées validées et de la configuration serveur |
| `input_snapshot` | Identité interne figée, versions et empreintes ; aucun récit ni chemin |

La paire identité/instantané reste NULL pour les anciens jobs. L'index
`ix_jobs_cycle(dream_id,kind,cycle_key)` permet de retrouver le cycle entier, y compris
ses échecs et les générations volontaires précédentes. Les contraintes imposent une
paire complète ou complètement NULL. Aucun compteur historique n'est réinitialisé.
La valeur 0 des relances historiques signifie absence d'information P11, pas preuve
d'absence de demandes antérieures.

Le downgrade est réversible sur un historique non activé P11. Il refuse explicitement
de supprimer des identités ou compteurs P11 déjà utilisés ; transaction annulée. Il
ne faut pas effacer ces données pour forcer le retour arrière. La migration requiert
les verrous DDL usuels PostgreSQL et un UPDATE de reprise : prévoir une fenêtre d'arrêt
des services lors d'un futur déploiement autorisé. Elle n'a été appliquée qu'aux
clusters temporaires des tests.

## Identité et budgets transactionnels

`job_lifecycle` réutilise `job_rules`, les tables `jobs`, `image_generations` et
`emotion_analyses`. L'identité inclut propriétaire, rêve, type, version du récit,
révision du moteur et de sa politique, paramètres canoniques. STT ajoute l'empreinte
audio (changer seulement l'UUID d'un audio identique ne crée pas de budget) ; image
ajoute empreinte/version de description ; image et émotion incluent l'empreinte du récit.
Les configurations sont fournies exclusivement par du code serveur de confiance.

Le verrou du rêve sérialise les créations. Les relances/réservations verrouillent le
job puis le rêve avec NOWAIT ; une contention produit un conflit générique plutôt
qu'une attente cyclique. Délais locaux : verrou 3 s, instruction 10 s. Le budget est
la somme persistante de toutes les lignes de même cycle, pas un compteur en mémoire.

- Au plus **3 réservations d'exécution** et **2 relances manuelles** par cycle.
- Une relance exige un échec relançable et une action explicite ; elle conserve
  `attempts`, incrémente `retry_count`, réinitialise l'attente, révoque l'ancien bail.
- Une création répétée après échec est refusée : changer l'UUID du job ne blanchit pas
  le budget. Les erreurs inconnues, sécurité, versions périmées et suppressions ne
  sont pas relançables.
- Un succès identique valide est réutilisé. Pour une image, la disponibilité et
  l'intégrité sont revérifiées via le service P19 injecté ; sans ce service, aucun
  cache image n'est déclaré valide. Aucun stockage personnel n'est ouvert par défaut.
- Une nouvelle image volontaire exige `explicit=True,new_image=True` en interne.
  Elle conserve **le même budget de 3 exécutions**, succès compris : après une première
  réussite, au plus deux nouvelles générations sans changement des entrées. Elle
  ne peut pas remplacer la relance d'une dernière demande échouée.
- Les versions et propriétaires sont relus à la relance et à la réservation ; la
  révision du choix émotionnel doit également correspondre. Aucune émotion retenue
  n'est modifiée par ces services.

## Compatibilité et raccordement restant

Les lignes historiques restent utilisables par les chemins historiques. L'ancien
SQL INSERT/UPDATE fonctionne grâce aux valeurs par défaut. En revanche, une identité
fiable ne peut pas être reconstruite à partir d'une configuration supposée : le
nouveau service refuse la prise en charge d'une famille rêve/type contenant des jobs
historiques non identifiés. Une politique explicite de reprise de cet historique
devra être validée avant bascule des routes existantes.

Les boucles actuelles ignorent les jobs portant une identité P11, et les anciens
enqueue refusent de recréer un job pour une famille déjà activée P11. Cette frontière
empêche un chemin historique de contourner le budget d'un cycle géré. Elle ne constitue
pas encore la bascule des routes/consommateurs : les jobs P11 internes attendent le
raccordement phase 3. Un ancien binaire non mis à jour ne connaît pas cette frontière ;
arrêter et mettre à jour tous les consommateurs avant toute activation en application.
L'ORM courant exige désormais 0009 : ne pas redémarrer l'application personnelle sur
0008 avec ce code avant une procédure de migration expressément autorisée.

Le cache STT est conservateur et exige la version attendue actuelle. La publication
STT qui incrémente la version du récit devra être raccordée à un contrôle explicite
de sa version de sortie en phase 3, sans assimiler une correction P06 à un succès
réutilisable. Les paramètres image/émotion doivent rester ceux de l'instantané.

## Maintenance sans modèle

`job_maintenance.maintain` utilise uniquement PostgreSQL et les modèles de données.
Inventaire en transaction READ ONLY ; application par petites transactions, job
SKIP LOCKED puis rêve NOWAIT, relecture après verrou. Deux maintenances ne peuvent
valider deux fois le même échec. Les conflits sont différés pour le prochain passage.

- `queued` expiré après 1 800 s : `failed / queue_timeout`.
- `running` avec bail expiré ou absent : `failed / interrupted`.
- Rêve supprimé : `failed / dream_deleted`.
- Jeton et bail supprimés, référence de demande émotion active retirée.
- Aucun retour automatique vers `queued`, aucun appel fournisseur, aucun modèle.

Les compteurs ne changent pas à la maintenance. Les anciens jetons ne permettent plus
de publier. P10 conserve la responsabilité de suppression et purge ; aucun job purgé
n'est recréé. La maintenance n'efface ni fichier ni donnée dépendante.

Valeurs P11 : STT 600 s, image/émotion 120 s, marge de bail 120 s. Le pont image attend
au plus timeout+45 s, le pont émotion timeout+30 s, avec arrêts bornés : la marge de
120 s est supérieure à ces surcoûts par défaut. Whisper utilise 600 s par défaut,
configurable jusqu'à 1 800 s : **à la phase 3, construire Policy avec le timeout STT
effectif**, sinon un bail de 720 s serait trop court pour une configuration à 1 800 s.
Les anciens baux timeout+60 s restent lus tels quels ; ils ne sont pas raccourcis.

## Commandes PowerShell — cible temporaire exclusivement pour la validation

Depuis la racine du dépôt, sans installer de dépendance :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --p11-only
.\.venv\Scripts\python.exe -m pytest backend/tests/test_job_maintenance_cli.py -q
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

Le premier lanceur crée son propre cluster, choisit un port libre, applique les
migrations dans les schémas fictifs et nettoie le cluster. Il n'utilise pas dreams_local.

Pour une maintenance future sur une cible temporaire préparée par l'opérateur,
`DATABASE_URL` doit être explicitement fournie par ce lanceur dans le processus :
le CLI ne charge pas `.env` et ne récupère pas silencieusement la cible personnelle.
Ne pas copier de mot de passe dans l'historique PowerShell.

```powershell
$env:P11_QUEUE_TIMEOUT_SECONDS = '1800'
$env:P11_MAINTENANCE_INTERVAL = '5'
# DATABASE_URL doit déjà désigner le cluster temporaire contrôlé.
.\.venv\Scripts\python.exe scripts/job_maintenance.py
.\.venv\Scripts\python.exe scripts/job_maintenance.py --apply --confirm-database p11_temporary
.\.venv\Scripts\python.exe scripts/job_maintenance.py --apply --confirm-database p11_temporary --watch
# Ctrl+C arrête la boucle. Retirer ensuite les variables temporaires du processus.
```

`--confirm-database` doit correspondre exactement au nom de la base temporaire réelle.
La confirmation est un garde-fou d'opérateur, pas une détection automatique d'une base
personnelle. Aucun démarrage automatique n'est configuré. En panne PostgreSQL, sortie
1 avec message générique et libération du pool ; redémarrage explicite nécessaire.
Si tous les processus sont arrêtés, aucune récupération ne peut avoir lieu avant
le redémarrage de la maintenance ; les échéances restent en PostgreSQL.

## Validation mesurée

Campagne complète finale (`scripts/verify_p20.py`) : **674 réussis, 1 ignoré**, en
349,82 s ; couverture backend **89,21 %**, service de cycle **89 %**, maintenance
**85 %**. Le test ignoré est la recette mDeBERTa réelle opt-in, volontairement non
autorisée dans cette phase. Les scénarios navigateur existants sont passés. Le lanceur
a également confirmé l'historique et l'audio après redémarrage réel PostgreSQL/Uvicorn,
puis le refus du média fictif après purge. Les serveurs temporaires sont arrêtés.

Une première campagne avait donné 666 réussis, 1 échec, 1 ignoré : le test historique
P08 utilisait l'ORM courant après être resté en 0008. Ses assertions sur 0008 ont été
conservées, puis une remontée à head a été ajoutée avant les opérations ORM. La
campagne finale ci-dessus confirme cette correction. Un avertissement non bloquant
Pydantic subsiste dans `test_image_routes.py::test_concurrent_http_requests` : alias
`dream_id` sans effet dans le contexte de Field. Aucun échec associé ; aucun changement
de route publique n'a été ajouté pour le masquer.

Ruff backend/scripts, compilation Python ciblée, syntaxe des sept fichiers JavaScript,
compilation Tailwind locale 4.3.0 vers un fichier temporaire et `git diff --check` :
réussis. Le CSS temporaire a été supprimé. L'empreinte du CSS utilisateur est restée
`d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.
Les 19 fichiers modifiés/non suivis examinés ne présentent aucun artefact privé ni
secret selon les motifs contrôlés. `.env`, `.venv` et `.coverage` sont ignorés par Git.

Dernière campagne ciblée étendue : **147 tests réussis en 33,71 s** : 73 règles P11,
24 tests PostgreSQL P11, 5 tests CLI, 19 contrôles PostgreSQL existants et 26 tests P08.
Les 5 tests CLI ont aussi été exécutés séparément (0,33 s), sans connexion. Ces essais couvrent migration
historique aller/retour, garde de downgrade, budgets après reconnexion, concurrence de
création/relance/maintenance, cache image et fichier absent, versions P06/P07/P08,
propriétaire, expiration, résultats tardifs et suppression/purge P10.

Aucun test réel de modèle, aucune nouvelle route de relance, aucune validation
opérationnelle des workers raccordés P11 n'est revendiquée dans cette phase.

## Fichiers de cette phase

Créés :

- `backend/app/services/job_lifecycle.py`
- `backend/app/services/job_maintenance.py`
- `backend/migrations/versions/0009_job_retries.py`
- `backend/tests/test_job_lifecycle.py`
- `backend/tests/test_job_maintenance_cli.py`
- `scripts/job_maintenance.py`
- `docs/p11-phase2.md`

Modifiés :

- `backend/app/models.py`
- `backend/app/services/stt_jobs.py`
- `backend/app/services/image_jobs.py`
- `backend/app/services/emotions.py`
- `backend/tests/test_postgresql.py`
- `backend/tests/test_image_jobs.py`
- `backend/tests/test_emotion_postgresql.py`
- `scripts/verify_image_jobs.py`

Les trois fichiers de phase 1 (`job_rules.py`, `test_job_rules.py`, `p11-phase1.md`)
étaient déjà présents et restent non suivis tant qu'aucune opération Git n'est autorisée.
`frontend/styles/app.css` conserve uniquement son changement préexistant 767 → 1023 px ;
il est exclu du périmètre P11 et n'a pas été réécrit. La compilation de contrôle
Tailwind vise un fichier temporaire, pas le CSS livré.
