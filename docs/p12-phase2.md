# P12 / SCRUM-16 — Phase 2 : quota global IA

## Contrat et point d'admission

Le quota initial est **20 admissions d'exécution par compte sur une fenêtre
glissante de 24 heures**, communes à STT, image et émotion. Il ne dépend ni du
rêve, ni de l'UUID du job, ni de son cycle, ni du moteur utilisé.

Le point d'admission est la réservation P11 `queued → running`. Dans **la même
transaction PostgreSQL** : vérifications P11, contrôle du quota, insertion d'une
unité, incrément de tentative et affectation du jeton/bail. Un rollback annule
l'ensemble. Le moteur n'est appelé qu'après validation de cette transaction.
La publication vérifie aussi l'existence de l'unité correspondant exactement au
compte, au job, à sa tentative et à son jeton de réservation.

Il s'agit d'une admission d'exécution, pas d'une facturation des seuls succès :
une fois la réservation validée, l'unité n'est pas remboursée, même si le modèle
échoue, s'abstient, bloque une image, manque de mémoire ou si le processus s'arrête.
Un arrêt entre COMMIT et appel du moteur reste également comptabilisé : il est
impossible de rendre atomiques une transaction PostgreSQL et le démarrage d'un
calcul dans un autre processus. Ce choix conservateur empêche le contournement
par interruptions ; il ne prétend pas garantir une inférence effectivement achevée.

| Situation | Effet sur le quota |
| --- | --- |
| Création `queued`, sans réservation | 0 unité |
| Nouvelle réservation `running` validée | 1 unité |
| Relance manuelle vers `queued` | 0 unité à ce stade ; 1 à sa nouvelle réservation |
| Résultat existant réutilisé/dédupliqué | 0 unité, même si le quota est plein |
| Refus d'authentification, propriétaire, versions, sécurité ou budget P11 | 0 unité |
| Refus de quota | 0 unité ; tentative, relance, jeton et état inchangés |
| `done`, échec fournisseur, abstention, résultat périmé ou interruption après admission | Unité conservée |
| Annulation/suppression/expiration alors que le job n'a jamais été réservé | 0 unité |
| Suppression/purge après admission | Unité conservée ; aucune copie du contenu |

Les limites P11 restent **3 exécutions maximum et 2 relances manuelles par cycle**.
Le quota global s'y ajoute ; il ne les remplace pas. Une régénération volontaire
P07 consomme une unité à sa réservation et continue de partager le budget P11.
L'import/conversion audio P04 et les opérations purement manuelles ne sont pas
des exécutions IA et ne sont pas comptabilisés par cette phase.

## Schéma — migration additive 0010

`0010_ai_execution_quota.py`, parent `0009`, crée deux tables sans modifier les
anciennes migrations, les rêves ou les médias :

| Table | Champs et contraintes |
| --- | --- |
| `ai_quota_policy` | Ligne unique `id=1`, `execution_limit` initial 20, entier 1..10 000 |
| `ai_executions` | UUID, `user_id`, `job_id` nullable, type STT/image/émotion, tentative 1..3, jeton de réservation unique, date d'admission |

Une contrainte unique `(job_id, attempt)` et un jeton unique empêchent une double
insertion de réservation. L'index `(user_id, admitted_at)` sert la fenêtre glissante.
Les unités n'enregistrent ni récit, ni transcription, ni description, ni émotion,
ni fichier ou chemin privé.

La FK vers `jobs` est **ON DELETE SET NULL** : purger un rêve P10 ne supprime pas
ses unités et ne libère pas artificiellement son quota. Le lien utilisateur est
conservé pour compter le compte, avec **ON DELETE CASCADE** si une future procédure
autorisée supprime réellement le compte. Aucune suppression de compte n'est ajoutée.
Une unité expirée ne compte plus, mais n'est pas automatiquement effacée ici.
Les données techniques s'accumulent donc : une politique ultérieure de nettoyage
des unités expirées pourra être définie sans supprimer des unités encore actives.

La migration ne reconstruit pas arbitrairement les exécutions historiques : les
unités commencent à l'activation de 0010. Arrêter et mettre à jour tous les workers
est nécessaire pour un futur déploiement ; un ancien binaire ne sait pas appliquer
ce quota. Un résultat sans admission correspondante est refusé à la publication.
La migration personnelle n'est ni exécutée ni préparée sous forme de commande ici.

Le downgrade vers 0009 est possible si le registre est vide ; il **refuse** de
détruire un registre utilisé. Ne pas supprimer les unités pour forcer un downgrade.

## Concurrence et fenêtre glissante

Ordre conservé : verrou job/rêve P11, verrou partagé sur la politique centrale,
puis verrou transactionnel PostgreSQL propre au compte. Deux workers ne peuvent
donc pas admettre simultanément la dernière unité du même compte. Les verrous
existants restent bornés (3 s de verrouillage, 10 s par instruction).
Le calcul n'est pas exécuté dans la transaction.
L'admission exige explicitement l'isolation **READ COMMITTED** du projet. En
REPEATABLE READ ou SERIALIZABLE, elle échoue en 503 sans unité : un instantané
pris avant l'attente d'un verrou ne doit pas masquer une admission concurrente.
Le refus est testé ; aucune configuration d'isolation personnelle n'est modifiée.

La politique est **centrale en PostgreSQL**, pas dans une variable Python ou une
variable d'environnement divergente entre workers. Une reconfiguration explicite
verrouille sa ligne ; aucun navigateur ne choisit sa limite. Un préfiltre SQL des
comptes épuisés évite qu'une longue file d'un compte bloque les autres utilisateurs.
Ce préfiltre ne constitue pas une autorisation : chaque réservation refait le
contrôle atomique avec le verrou du compte.

L'heure vient de `clock_timestamp()` PostgreSQL, relue après acquisition du verrou.
Les calculs sont normalisés en UTC ; 24 heures signifient 86 400 secondes, y compris
au changement d'heure en Europe/Paris. Le préfiltre SQL utilise lui aussi un
intervalle de 24 heures, pas un jour civil dépendant du fuseau.
Une unité est active si `admitted_at > maintenant - 24 heures`. À l'égalité exacte,
elle ne compte plus. Aucun changement à minuit, redémarrage ou nouveau rêve ne
remet le registre à zéro.

### Refus HTTP et Retry-After

Les créations et relances font un contrôle anticipé **sans consommer** après les
validations métier et après les chemins de réutilisation de résultat. Si le quota
est déjà plein, elles retournent **429**, format public historique `rate_limited`,
message générique et en-têtes `Retry-After` et `Cache-Control: no-store`.
Le refus ne révèle aucun récit, jeton, chemin ni données d'un autre compte.

Pour `N` unités actives et une limite `L`, les dates sont triées de la plus ancienne
à la plus récente ; le délai utilise la date d'indice **N − L**, base zéro :

`Retry-After = max(1, ceil((date[N − L] + 24 h − maintenant).total_seconds()))`

Ce calcul attend suffisamment d'expirations, y compris si l'administrateur a
abaissé la limite sous l'utilisation actuelle. Ce n'est pas un délai fixe de
24 h ni une moyenne. Il est exact à l'heure de décision PostgreSQL, arrondi à la
seconde supérieure ; une nouvelle utilisation ou reconfiguration ultérieure peut
modifier l'admissibilité avant la prochaine demande.

Une requête `202 queued` n'est pas une réservation de capacité globale : plusieurs
demandes peuvent être acceptées tant qu'il reste des unités, puis certains jobs
attendre si d'autres réservations les épuisent. Le worker ne démarre pas de modèle
dans ce cas ; le job garde zéro nouvelle tentative et son jeton vide. La maintenance
P11 peut l'échouer après son délai d'attente (30 minutes par défaut), sans exécution.
Une relance ultérieure reste explicite et soumise aux deux budgets.
L'interface de compteur/quota n'est pas ajoutée ; une action web refusée reçoit
le même JSON 429 sûr. Aucun rafraîchissement ou polling n'ajoute d'unité.

## Configuration — environnement temporaire uniquement pour cette validation

`scripts/ai_quota.py` exige `DATABASE_URL` **explicitement fourni** ; il ne charge
pas `.env`. Sans option, il fait un inventaire en transaction lecture seule.
Pour changer la limite, `--apply`, `--limit` et la confirmation exacte du nom de
base sont obligatoires. Une limite invalide ou une cible non confirmée est refusée.

Exemples à lancer seulement dans la session déjà configurée vers la base temporaire
isolée (ne pas utiliser une session pointant vers la base personnelle) :

```powershell
.\.venv\Scripts\python.exe scripts/ai_quota.py
.\.venv\Scripts\python.exe scripts/ai_quota.py --apply --limit 20 --confirm-database p07_validation
```

Sorties : uniquement limite, fenêtre de 24 h et mode ; aucun compte ni secret.
La limite enregistrée s'applique aux décisions suivantes dans tous les processus.
Une augmentation n'efface pas les unités ; une diminution conserve tout l'historique.

## Fichiers de phase 2

Créés :

- `backend/app/services/ai_quota.py` : contrôle, admission, preuve de réservation et configuration centrale.
- `backend/migrations/versions/0010_ai_execution_quota.py` : tables, index et contraintes.
- `backend/tests/test_ai_quota.py` : tests PostgreSQL, HTTP, CLI et concurrence multiprocessus.
- `scripts/ai_quota.py` : inventaire et configuration explicites, sans IA.
- `docs/p12-phase2.md` : contrat et résultats.

Modifiés :

- `backend/app/models.py` : modèles des deux nouvelles tables.
- `backend/app/services/job_lifecycle.py` : précontrôle, admission atomique, sélection de file et publication.
- `backend/tests/test_postgresql.py` : schéma courant 0010 et comparaison modèle/migrations.
- `backend/tests/test_job_lifecycle.py` : révision attendue après rollback sur le nouveau head ; règles P11 conservées.
- `backend/tests/test_image_jobs.py` : assertion du schéma courant actualisée en 0010 ; contraintes inchangées.
- `scripts/p11_inventory.py` : ne cherche pas les tables P12 sur les schémas historiques 0008/0009 ; les inclut en 0010.
- `scripts/verify_image_jobs.py` : campagne ciblée `--quota-only` sur cluster temporaire.
- `scripts/verify_p20.py` : unités fictives explicites et contrôle d'empreintes après vrai redémarrage.

Les dix fichiers de phase 1 déjà présents sont conservés ; cette phase ne les
réécrit pas. Le CSS préexistant garde l'empreinte
`d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.

## Recette

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --quota-only
.\.venv\Scripts\python.exe scripts/verify_p20.py --emotion-web-test
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend scripts
git diff --check
```

Les tests utilisent PostgreSQL temporaire, des comptes/récits/médias fictifs et
des faux moteurs uniquement. Ils vérifient la limite 20, les trois types, les
nouveaux rêves et cycles, les relances, la déduplication gratuite, les réservations
concurrentes (connexions et processus OS distincts), les deux comptes, la fenêtre
glissante, sa frontière exacte, une baisse de limite, les rollbacks, les erreurs
après admission, les baux expirés, l'arrêt et la purge P10. Les refus Bearer et
session/CSRF sont vérifiés sans divulgation ; les compteurs restent inchangés.
Les migrations aller/retour sans unités et un échec injecté sont testés, ainsi que
le refus d'un downgrade destructeur et l'absence de publication sans admission.

Résultats : campagnes ciblées successives **126**, **131**, **138**, **139**, puis
**141 tests réussis en 77,95 s** (cette dernière comprend les deux cas UTC/changement
d'heure). Le profil ciblé inclut désormais aussi les 16 tests d'image, déjà présents
dans la suite complète.
La dernière campagne ciblée donne **159 réussis en 77,10 s**, incluant les deux cas
d'isolation transactionnelle refusée ; les **43 tests P12 phase 2** sont inclus.
La première suite complète a donné **807 réussis, 1 échec, 1 ignoré en 506,14 s**,
couverture **89,83 %** : un test d'image attendait encore le head 0009 ; seule cette
assertion a été actualisée en 0010. Aucun contrôle métier n'a été assoupli.
Les consolidations complètes suivantes confirment la correction.
Une campagne intermédiaire a ensuite réussi : **810 réussis, 1 ignoré en 524,47 s**,
avant la consolidation du garde d'isolation.

**Campagne finale stabilisée : 812 réussis, 1 ignoré en 491,20 s**, couverture
backend **89,84 %** (4 437 instructions, 451 non couvertes), service quota **98 %**.
Les 43 tests spécifiques de cette phase sont inclus. Le test ignoré est l'inférence
réelle mDeBERTa opt-in, volontairement non exécutée. Aucun modèle réel ni appel IA
externe n'est exécuté.

Un avertissement Pydantic `UnsupportedFieldAttributeWarning` sur l'alias `media_id`
est remonté dans le test concurrent préexistant d'image. Il n'a pas provoqué
d'échec ni de fuite ; les validations et contrats API testés passent. Il reste un
point de suivi non bloquant, sans modification hors périmètre pour le masquer.

Le lanceur a vérifié les empreintes du registre et de la politique après un vrai
arrêt/redémarrage PostgreSQL/Uvicorn temporaire : mêmes données, mêmes unités et
mêmes paramètres, y compris les deux admissions fictives ajoutées explicitement
au scénario de redémarrage. L'historique P09 est identique ; l'audio P04 est relu
en HTTP 200 et P19 vérifie 200 après redémarrage, puis 404 après purge fictive.
Les parcours Chrome existants passent, dont STT/image/émotion sur ordinateur et
à 390 px. Les serveurs et leurs ressources temporaires sont nettoyés.
Le contrôle final des processus retourne **0 processus de recette restant**.

Ruff backend/scripts, compilation Python et `git diff --check` : réussis.
La seule migration créée est 0010 ; aucune ancienne migration n'est modifiée.
Aucune anomalie bloquante dans la recette finale.

## Limites restantes

- Le quota borne des admissions, pas la durée CPU/GPU ni le stockage ; les limites
  existantes de temps, taille et concurrence restent nécessaires.
- Le volume des jobs en attente et l'inscription de plusieurs comptes ne sont pas
  un quota d'identité humaine ; aucune nouvelle protection anti-inscription n'est ajoutée.
- Pas de remboursement après COMMIT ; pas de reconstruction des dernières 24 h
  avant activation de la migration.
- Les dates du serveur PostgreSQL doivent être correctes ; aucun timestamp client
  n'est utilisé pour autoriser des unités.
- Pas de nettoyage automatique du registre expiré ni de compteur web dans cette phase.
- La base personnelle n'a pas été consultée/modifiée ; aucun plan de migration
  personnelle n'est exécuté ni proposé avant validation de cette recette.
- Les protections HTTP/logs de phase 1 restent actives. Swagger/ReDoc, modèles,
  dépendances de production et interface ne sont pas modifiés.

Aucun git add, commit, push, restore, reset ou changement Jira.
État Git cumulé P12 : 23 fichiers candidats (12 suivis modifiés, 11 nouveaux), dont
13 pour cette phase (8 suivis modifiés, 5 nouveaux) et 10 de phase 1 préservés.
La 24e entrée est le CSS indépendant, intact et exclu. Index Git vide.
Le contrôle de noms, extensions et motifs sensibles ne détecte aucun modèle,
archive, média privé, secret ou fichier temporaire parmi les candidats.
