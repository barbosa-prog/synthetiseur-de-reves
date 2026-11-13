# P12 / SCRUM-16 — Recette finale de sécurité

Date : 13 novembre 2026. Base Git : `4583fcf`, branche `main`.
Ce rapport consolide les phases 1 à 3. Aucune base personnelle n'est consultée ou
modifiée ; aucune inférence réelle, API payante, opération Git d'écriture ou
modification Jira n'est effectuée. Le CSS indépendant est conservé.

## Critères Jira

| Critère | Statut et preuves |
| --- | --- |
| Aucune clé API dans le frontend | Conforme aux sources et ressources contrôlées : pas de clé fournisseur, de configuration DB ou de clé privée dans les fichiers servis ; `.env` et les médias ne sont pas montés en statique. Les clés de session restent en cookies HttpOnly ; une preuve CSRF dans un formulaire n'est pas une clé fournisseur. |
| Aucun récit/transcription dans les logs | Conforme pour les chemins applicatifs Python testés : liste blanche, suppression des arguments/exceptions/tracebacks, véritables logs Uvicorn debug relus avec marqueurs fictifs dans corps, URL, en-têtes et exceptions. La sortie privée d'un moteur est un pipe capturé, pas un journal. |
| Tests automatisés accès et tailles | Bearer, sessions, CSRF, comptes distincts, rêves/médias/jobs supprimés ou périmés, réception segmentée, longueurs absentes/fausses, dépassements, délais et interruptions. Régression P01 à P11 et phases 1/2 P12. |
| Quota documenté | 20 admissions par compte sur 24 heures glissantes, commun STT/image/émotion, persistant PostgreSQL, concurrence transactionnelle et Retry-After. Voir ci-dessous et `p12-phase2.md`. |

Ces statuts ne constituent pas une certification de toutes les configurations
externes : journaux PostgreSQL, Windows, proxy, sorties natives et sauvegardes
nécessitent leurs contrôles d'exploitation propres. Aucun journal personnel
historique n'a été ouvert pour cette recette.

## Tailles, délais et erreurs

| Entrée | Taille maximale reçue | Délai de réception |
| --- | --- | --- |
| Authentification et petits formulaires publics | 8 Kio | 10 s |
| Autres routes API et formulaires de récit | 256 Kio | 10 s |
| Upload audio authentifié | 15 Mio | 30 s |
| Autres chemins | 8 Kio | 10 s |

Le comptage est progressif avant parsing, y compris sans Content-Length et en
chunked. Les messages dépassant la limite ne sont pas ajoutés au tampon. L'audio
reste reçu en flux après authentification/CSRF et conserve sa conversion isolée
de 20 s, son maximum de 8 minutes et ses deux places de réception par processus.
Les limites métier restent : récit 20 000 caractères, description 500 caractères,
image P19 8 Mio ; sortie P07 PNG 512 × 512 avec filtre de sécurité conservé.
Les exports P10 restent bornés à 100 médias/100 Mio par défaut.

- **400** : longueur malformée, ambiguë ou différente du corps présenté à l'ASGI.
- **408** : délai de réception dépassé ou corps interrompu ; une réponse ne peut
  plus être reçue par un client déjà déconnecté.
- **413** : taille annoncée ou reçue trop grande, avant traitement métier.
- **415** : format/encodage non accepté ; pas de décompression implicite du corps.
- **429** : anti-bruteforce ou quota IA ; `Retry-After` exprime le délai en secondes.

Le garde ne remplace pas un plafond global de connexions, d'en-têtes ou de stockage.
Les mémoires du parseur et les copies restent bornées, mais ce n'est pas un plafond
exact de RSS du processus. Les limites des moteurs restent distinctes de celles
de réception HTTP. Aucune nouvelle exécution n'est déclenchée par GET ou polling.

## Confidentialité et autorisations

Les mots de passe sont hachés Argon2id ; les sessions opaques sont hachées en base,
expirent et peuvent être révoquées. Les cookies sont Secure, HttpOnly, SameSite et
liés à l'hôte. Les actions navigateur vérifient l'origine et une preuve CSRF liée
à la session. Bearer reste réservé aux en-têtes API, jamais aux URL.

Les propriétaires sont déterminés côté serveur. Les rêves inconnus, supprimés
ou intercomptes ne sont pas distingués par une divulgation de contenu. P19 contrôle
les médias et leur intégrité ; P11 contrôle les réservations et versions ; P10
révoque les accès et résultats tardifs après suppression. Les nouvelles tables de
quota n'ont **aucune route publique** ni représentation ORM envoyée au navigateur.
La configuration du quota est une commande locale opérateur avec URL explicite
et confirmation de base en mode application, pas une action d'un compte web.

Les réponses privées portent `Cache-Control: no-store`, notamment les routes
`/api/v1/images/` dont l'omission dans la liste de protection a été corrigée lors
de cette recette. Les médias P19 conservent également leurs en-têtes de confidentialité.

Les logs Python ne conservent que des événements fixes, avec métadonnées limitées
(heure/gravité/PID lorsque le handler est configuré). Un message tiers devient
`diagnostic_redacted`, sans corps, headers, cookies, tokens, paramètres SQL ou
traceback. Ne pas remplacer cette politique par un dump de LogRecord ou une
journalisation de corps. Après début d'envoi HTTP, un événement sûr signale
l'interruption ; il est impossible de remplacer rétroactivement la réponse.

Le code transmet les résultats IA par pipe privé ou fichiers éphémères privés.
Ne pas lancer le décodeur Whisper directement avec sa sortie redirigée vers un
journal partagé. Les outils de qualification avec données fictives restent
distincts des commandes de production. Les logs natifs/crash dumps et les logs
PostgreSQL ne sont pas reconfigurés ici ; ne pas y activer les traces de paramètres
ou de requêtes contenant des données privées sans mesure de protection adaptée.

## Quota global et traitements asynchrones

La migration additive **0010_ai_execution_quota.py**, après 0009, crée :

- `ai_quota_policy` : une ligne centrale, limite initiale 20 configurable 1..10 000.
- `ai_executions` : compte, job nullable, type, tentative, réservation et date,
  sans récit, émotion, fichier ou chemin. Unicités de tentative/job et de jeton.

L'unité est insérée dans la transaction P11 `queued → running`, avec les contrôles
de propriétaire, versions, budget et jeton. Aucun modèle n'est appelé avant COMMIT.
Les décisions exigent READ COMMITTED ; une autre isolation échoue fermée en 503.
Le verrou de compte est PostgreSQL ; les processus ne partagent pas un compteur
Python. Les résultats ne sont publiables qu'avec l'admission exacte de la réservation.

| Événement | Coût global |
| --- | --- |
| Création en attente | 0 |
| Nouvelle réservation d'exécution | 1 |
| Relance explicite | 0 lors de la remise en file, 1 lors de sa réservation |
| Résultat réutilisé/dédupliqué | 0, même quand le quota est plein |
| Refus avant admission (droits, entrée, version, budget, quota) | 0 |
| Succès, abstention, sécurité bloquante, erreur ou interruption après admission | Unité conservée |
| Suppression/purge après admission | Unité conservée, lien job mis à NULL |

La garantie porte sur des admissions, pas uniquement des inférences achevées :
un crash après COMMIT mais avant appel du modèle reste comptabilisé. Il n'y a pas
de remboursement automatique ni d'exécutions historiques inventées à la migration.
Les budgets P11 restent 3 tentatives et 2 relances par cycle ; nouveau rêve, UUID,
texte corrigé ou nouveau cycle ne remettent pas le quota de compte à zéro.

Les unités actives ont une date strictement supérieure à maintenant moins 86 400 s,
en UTC, sans reset à minuit ni effet de changement d'heure. Pour N unités actives
et une limite L, Retry-After attend l'expiration de la date triée d'indice N-L,
puis arrondit à la seconde supérieure (minimum 1). Ceci couvre aussi une baisse
de limite. Les 429 ont un JSON sûr `rate_limited` et `Cache-Control: no-store`.

La mise en file n'est pas une réservation de capacité : un job peut attendre si
le quota s'épuise entre création et réservation. Aucun modèle n'est lancé ; la
maintenance P11 peut le passer en échec après 30 minutes d'attente. Toute relance
reste explicite et bornée. Le préfiltre des comptes épuisés évite de bloquer les
autres utilisateurs derrière une longue file. Ni suivi GET ni rafraîchissement
n'ajoute d'unité. L'interface d'un compteur de quota n'est pas développée.

Les unités expirées ne comptent plus mais ne sont pas automatiquement purgées
dans cette livraison. Leur rétention technique doit être revue avant un service
durable. Ce quota ne limite ni les inscriptions multiples, ni les conversions
audio hors IA, ni la durée totale de calcul ou la place disque.

## Moteurs locaux et documentation interactive

Whisper, Stable Diffusion et mDeBERTa ne sont pas des appels API distants dans cette
architecture. Les téléchargements explicites de préparation sont des opérations
séparées, jamais déclenchées par une requête ou un démarrage FastAPI.

`offline.py` impose HF_HUB_OFFLINE, TRANSFORMERS_OFFLINE, désactive télémétrie et
token implicite. Les trois runners utilisent cet environnement pour leurs enfants,
sans modifier celui du worker parent. Les URLs DB, mots de passe courants,
variables POSTGRES, tokens/clés/secrets identifiés et proxies ne sont pas transmis
inutilement. Les paramètres système, chemins et CUDA existants sont conservés.
Tous les chargeurs restent `local_files_only=True` ; mDeBERTa garde
`trust_remote_code=False`. Aucun seuil RAM/VRAM, timeout, filtre ou modèle n'est changé.

Les tests utilisent des chargeurs simulés et interdisent DNS/connexions Python,
vérifient les options réelles passées aux chargeurs, l'absence de lancement de
runner sans modèle, et l'échec générique si les fichiers manquent. Ils ne chargent
aucun poids. **Aucune capture de trafic d'une inférence réelle n'est revendiquée**.
Les variables hors ligne ne sont pas un pare-feu OS contre du code arbitraire ;
un besoin d'isolation native stricte demanderait une qualification et des règles
de sortie réseau spécifiques aux processus IA, sans bloquer PostgreSQL/FastAPI.

Swagger/ReDoc chargent encore des CDN quand `API_DOCS_ENABLED=1` (valeur par défaut
pour compatibilité P01). Ne pas y saisir de vrais tokens ni récits. La mesure
minimale livrée est **API_DOCS_ENABLED=0**, recommandée hors développement et dans
`.env.example` : pages docs/redoc/redirect désactivées (404), OpenAPI JSON conservé
(200, schémas seulement, aucune donnée utilisateur). Aucun asset n'est téléchargé.
Ne pas prétendre que le mode 1 est entièrement hors ligne ou auto-hébergé.
Le `.env` personnel et les services personnels ne sont pas modifiés ici.

## Précautions pour votre sauvegarde et migration 0009 → 0010

**À réaliser par vous, distinctement de cette recette. Aucune de ces opérations
n'a été exécutée sur la base personnelle.** Aucun dump de données réelles n'est créé.

1. Arrêter proprement FastAPI, tous les workers et les maintenances jobs/médias/purge.
   Ne pas arrêter ou supprimer le volume PostgreSQL pour sauvegarder.
2. Confirmer l'instance, l'hôte, le port, `dreams_local`, sa santé et la révision
   initiale **0009**. Ne pas se fier à une simple valeur d'exemple de port.
3. Créer une nouvelle archive PostgreSQL avec **pg_dump -Fc**, sans mot de passe
   dans les arguments ou l'historique. Ne pas utiliser une redirection PowerShell
   textuelle pour une archive binaire ; écrire avec l'option fichier de pg_dump.
4. Sauvegarder P19 séparément, avec tailles et SHA-256, source au repos. Écarter les
   liens/jonctions et confirmer la racine privée attendue avant copie. Le dump SQL
   n'inclut ni ces fichiers, ni les modèles, ni la configuration `.env`.
5. Conserver archives, manifestes et configuration nécessaire dans des dossiers
   privés protégés, hors Git/OneDrive. Ne pas imprimer les URL ou secrets. Les ACL
   ne constituent pas à elles seules un chiffrement de sauvegarde.
6. Vérifier SHA-256 et `pg_restore --list`, puis **restaurer réellement dans une
   autre base temporaire** : une liste d'archive seule ne prouve pas sa restauration.
   Utiliser une cible/port distincts et des variables de connexion explicites.
7. Comparer compteurs et empreintes de toutes les tables historiques et vérifier
   la copie des médias ; répéter la migration sur cette restauration avant la réelle.
8. Exécuter uniquement **alembic upgrade 0010** sur la cible confirmée, dans une
   transaction PostgreSQL, avec délais de verrouillage et d'instruction bornés
   (exemple de politique : 3 s / 30 s). L'environnement Alembic accepte une connexion
   transactionnelle explicitement fournie ; ne pas laisser une cible implicite.
9. Vérifier révision 0010, données/empreintes historiques identiques, politique
   centrale 20 et registre initial vide. Ne pas inventer des unités historiques.
   Vérifier de nouveau les fichiers P19, qui ne sont pas modifiés par cette migration.
10. Au premier échec : rester arrêté, contrôler l'annulation transactionnelle,
    conserver des journaux sûrs ; pas de stamp, suppression ou correction destructive.
11. Après utilisation du quota, le downgrade refuse de supprimer les admissions.
    Ne pas effacer le registre pour le forcer. En cas de restauration, préserver
    d'abord le nouvel état, restaurer dans une instance distincte et comparer avant
    une bascule humaine ; attention à toute écriture postérieure à la sauvegarde.
12. Redémarrer uniquement des versions cohérentes de tous les services, avec
    READ COMMITTED, la bonne racine P19, les modèles locaux et les limites qualifiées.
    Recommander API_DOCS_ENABLED=0 et ne pas activer automatiquement l'émotion.

La recette de migration exécutée ici utilise une **copie synthétique** en 0009,
pas une restauration de vos données personnelles. Elle contient des lignes dans
les tables utilisateurs, rêves, médias, jobs (quatre états/réservations), sessions,
descriptions, instantanés P07, émotions et analyses P08. Leurs empreintes complètes
sont comparées après 0010 et reconnexion. Les tests de rollback/échec injecté et
de refus du downgrade avec unités proviennent aussi de la phase 2.

## Recette exécutée et validation manuelle

Commandes exécutables de recette isolée, sans modèle réel ni base personnelle :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --p12-final
.\.venv\Scripts\python.exe scripts/verify_p20.py --emotion-web-test
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend scripts
git diff --check
```

Résultats : 12 tests finaux hors ligne/publics réussis en 1,58 s ; campagne ciblée
PostgreSQL **176 réussis en 49,66 s**. Première campagne complète de phase 3 : **825 réussis,
1 ignoré en 510,74 s**, couverture backend **90,07 %** (4 451 instructions,
442 non couvertes). Le test ignoré est l'inférence réelle mDeBERTa opt-in,
volontairement non exécutée. Aucun avertissement dans cette campagne ;
l'avertissement Pydantic intermittent documenté en phase 2 n'est pas reproduit
ici et n'a pas fait l'objet d'une correction hors périmètre. Le complément minimal
`no-store` de l'API image a ensuite passé **25 tests ciblés en 3,09 s** (sécurité
finale et API). **Confirmation complète sur le code final : 826 réussis, 1 ignoré
en 506,99 s**, couverture backend **90,07 %**, sans avertissement.
Les 14 nouveaux cas phase 3 (13 sécurité et 1 migration) sont inclus.

La campagne inclut P01 à P11 et P12 : droits intercomptes, sessions/CSRF/Bearer,
corps absents/segmentés/interrompus/lents, logs serveur, quota glissant et
concurrence, suppression/purge et résultats tardifs. Les parcours Chrome passent,
notamment STT/image/émotion sur ordinateur et à 390 px. Le lanceur confirme après
un vrai redémarrage PostgreSQL/Uvicorn temporaires les empreintes identiques des
données, budgets et réservations (quota inclus), l'historique P09 identique et
l'audio P04 relu en 200. P19 est relu en 200, puis refusé en 404 après purge fictive.
Les serveurs sont arrêtés et leurs ressources temporaires nettoyées.
Le contrôle final des processus de recette retourne **0 processus restant**.

Ruff backend/scripts, compilation Python et `git diff --check` : réussis.
Aucune dépendance, modèle ou ressource CDN n'est installé/téléchargé.

Pour une vérification humaine ultérieure, utiliser d'abord un environnement
temporaire migré en 0010 et deux comptes fictifs. Après votre propre migration
et validation de sauvegarde, les mêmes vérifications peuvent se faire uniquement
sur un nouveau rêve fictif, sans supprimer un rêve personnel :

- Vérifier inscription/connexion, historique, détails et médias de chaque compte.
  Copier un lien fictif vers l'autre compte : refus sans divulgation. Déconnecté :
  refus ou retour à la connexion selon la route.
- Vérifier les formulaires et un fichier audio fictif. Les dépassements sans
  Content-Length, le client lent et les longs flux sont validés par les tests ASGI,
  pas par une simple limite JavaScript du sélecteur de fichiers.
- Vérifier suivi P11, rechargement, coupure réseau et retour sans nouveau job.
  Utiliser les parcours automatisés avec faux moteurs pour tester les refus de
  quota/relances ; ne pas démarrer une IA réelle pour épuiser artificiellement 20 unités.
- Vérifier qu'un 429 conserve le JSON générique et Retry-After sans données privées.
  La limite peut être abaissée **sur la copie temporaire seulement** par la commande
  explicite documentée en phase 2, jamais en modifiant un compteur côté navigateur.
- Avec API_DOCS_ENABLED=0 dans le processus de test, vérifier docs/redoc en 404 et
  openapi.json en 200. Le mode 1 est réservé aux comptes et récits fictifs de développement.
- Tester ordinateur et 390 px. Ne jamais copier un vrai token ou corps privé dans
  les captures, tickets, consoles partagées ou journaux pour prouver le résultat.

## Fichiers et Git

La recette est prête pour votre vérification et votre gestion de la livraison.
Les 12 fichiers de phase 3 sont : `offline.py`, les trois providers/runners STT,
image et émotion, `main.py`, `.env.example`, `test_api.py`, les deux tests finaux,
`verify_image_jobs.py`, `README.md` et ce rapport. Les phases précédentes restent
présentes dans l'arbre de travail.

Liste cumulée exacte des **33 fichiers P12** : 18 suivis modifiés (`M`) et 15 nouveaux
non suivis (`??`). L'index Git est vide. Le 34e chemin de git status est le CSS
indépendant, exclu de cette liste.

```text
M  .env.example
M  README.md
M  backend/app/database.py
M  backend/app/emotion_runner.py
M  backend/app/errors.py
?? backend/app/http_guard.py
M  backend/app/image_runner.py
M  backend/app/main.py
M  backend/app/models.py
?? backend/app/offline.py
?? backend/app/safe_logging.py
?? backend/app/services/ai_quota.py
M  backend/app/services/job_lifecycle.py
M  backend/app/stt_provider.py
M  backend/app/web/routes.py
?? backend/migrations/versions/0010_ai_execution_quota.py
?? backend/tests/p12_server_fixture.py
?? backend/tests/test_ai_quota.py
M  backend/tests/test_api.py
?? backend/tests/test_http_guard.py
M  backend/tests/test_image_jobs.py
M  backend/tests/test_job_lifecycle.py
?? backend/tests/test_p12_final_migration.py
?? backend/tests/test_p12_final_security.py
M  backend/tests/test_postgresql.py
?? backend/tests/test_safe_logging.py
?? docs/p12-final.md
?? docs/p12-phase1.md
?? docs/p12-phase2.md
?? scripts/ai_quota.py
M  scripts/p11_inventory.py
M  scripts/verify_image_jobs.py
M  scripts/verify_p20.py
```

Le CSS `frontend/styles/app.css` est toujours indépendant, exclu, avec
l'empreinte `d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.
La migration à livrer est uniquement la nouvelle 0010 ; aucune ancienne migration
n'est modifiée. Aucun ajout à l'index, commit, push, restore, reset ou changement Jira.
