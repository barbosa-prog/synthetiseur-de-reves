# P13 — Conservation et procédures (phase 2)

Version : 13 novembre 2026. Document de fonctionnement, pas une attestation RGPD.
La notice publique est `/confidentialite`, accessible sans connexion, depuis le
pied de page et l'inscription. Elle ne charge aucune donnée de compte ou de rêve.

## A. Règles actuellement appliquées

| Données | Règle effective | Limite |
|---|---|---|
| Comptes, récits, audios et images | Conservation jusqu'à action de suppression et maintenance | Pas de durée maximale automatique générale ; pas de suppression automatique de l'audio après STT |
| Sessions | Expiration à 8 heures, révocation à la déconnexion | Les lignes expirées/révoquées ne sont pas automatiquement purgées |
| Anti-bruteforce | Fenêtre de 15 minutes ; compteurs par action, compte et IP dérivés | Réinitialisation à l'usage après expiration, pas de nettoyage global périodique |
| Quotas IA | 20 admissions par compte sur une fenêtre glissante de 24 heures par défaut | Une admission reste comptée après échec ; déduplication sans nouvelle admission ; pas de purge automatique des anciennes admissions |
| Jobs | Délais et récupération P11 ; états persistants | Un timeout n'est pas une suppression des lignes ou instantanés |
| Export | ZIP privé ; nettoyage après téléchargement, erreur ou interruption gérée | Après crash, résidus admissibles de plus d'une heure nettoyés à une préparation ultérieure, pas à échéance par un service dédié |
| Temporaires audio/IA | Nettoyage contextuel et par les surveillants | Un arrêt système brutal peut laisser des résidus |
| Orphelins/staging P19 | Maintenance explicite ; grâce par défaut de 24 heures | Pas un effacement automatique de tout audio âgé de 24 heures |
| Sauvegardes et logs | Procédures opérateur ; logs applicatifs par liste blanche P12 | Pas de rotation générale imposée ; sources système/PostgreSQL distinctes |

`media.expires_at` peut refuser une consultation après échéance. Il ne garantit
pas à lui seul l'effacement du fichier. Les copies de récits conservées pour P07
et P08 ne sont pas un historique exhaustif ; elles suivent la purge du rêve.
Les empreintes de compte/IP ne doivent pas être présentées comme anonymes.

La purge d'un rêve retire ses jobs, descriptions, générations et analyses. Les
admissions `ai_executions` restent liées au compte, avec `job_id` mis à NULL :
elles empêchent une réinitialisation du quota par suppression de rêves.

## B. Politique proposée, non activée

| Proposition | Décision préalable et garde-fous |
|---|---|
| Audio : 7 jours après validation du récit ET au maximum 30 jours après import | Définir l'événement de validation, avertir avant effacement ; absence de possibilité de retranscription après purge ; gérer brouillons, traitements et téléchargements actifs |
| Sessions expirées : nettoyage sous 24 heures | Ne pas invalider les sessions encore valides ; fixer une règle pour les sessions révoquées |
| Admissions IA : environ 48 heures | Préserver toute la fenêtre glissante de 24 heures, les réservations actives et les garanties d'unicité ; ne jamais réinitialiser les budgets P11 |
| Journaux : rotation après 7 jours | Définir destinations, fichiers tournants et sources externes ; aucune réintroduction de contenu privé |
| Sauvegardes : rotation après 30 jours | Inventaire, accès restreint, restauration testée et traitement des suppressions |
| Fin de conservation pédagogique | Date ou événement de clôture et délai à définir, avec information préalable |

Ces propositions ne sont pas des durées légales imposées et ne déclenchent aucune
automatisation. Même les anciennes données ne doivent pas être effacées sans
validation de la politique et de sa procédure. Aucun changement de schéma ici.

## Suppression d'un rêve et vérification de purge

1. Le propriétaire ouvre le détail dans « Mes rêves », puis « Supprimer ce rêve ».
   Lire l'avertissement et confirmer explicitement ; annuler ne supprime rien.
2. La suppression logique P10 bloque pages, mutations, nouveaux téléchargements
   et exports, invalide les jobs et programme les médias gérés pour purge.
   Un fichier déjà téléchargé ne peut pas être rappelé.
3. Un opérateur autorisé contrôle la base et le stockage ciblés, puis lance
   l'inventaire. Le service de maintenance n'est pas une action automatique web.
4. Après autorisation d'application, il lance la purge et vérifie son rapport.
   La réussite signifie : fichiers gérés absents puis dépendances SQL et rêve
   effacés. Les autres rêves, utilisateurs et médias doivent rester intacts.
5. Contrôler l'absence dans un nouvel inventaire et le refus des anciennes URL.
   Un rêve absent dans l'historique ne prouve pas à lui seul sa purge physique.

Exemples PowerShell pour un environnement **fictif isolé uniquement** ; aucune
commande n'a été exécutée dans cette phase. Injecter les variables depuis la
configuration approuvée, sans afficher de mot de passe ni le placer dans Git :

```powershell
# Précondition : DATABASE_URL et PRIVATE_MEDIA_ROOT désignent la recette isolée.
# Vérifier localement leur cible ; ne pas utiliser une configuration implicite.
.\.venv\Scripts\python.exe scripts/dream_maintenance.py --limit 20
# MODIFIE les données fictives : autorisation distincte requise avant application.
.\.venv\Scripts\python.exe scripts/dream_maintenance.py --apply --confirm-database recette_p13 --limit 20
```

Le nom `recette_p13` est fictif : il doit correspondre exactement à la base
temporaire approuvée. Ne pas copier ces commandes vers la base personnelle.
Les rapports ne doivent contenir ni récit ni chemin privé. Ils résument les
purges réussies et blocages ; ne pas copier des lignes SQL personnelles en ticket.

### Interruption ou blocage

Relancer d'abord l'inventaire, puis l'application explicitement autorisée sur la
même cible. Un fichier déjà absent peut être confirmé sans erreur : la reprise
est idempotente, y compris après effacement du fichier avant validation SQL.
Une panne disque ou un fichier verrouillé ne vaut jamais réussite. Résoudre
l'accès ou attendre la libération du téléchargement, puis reprendre. Les médias
legacy, liens et références croisées exigent une revue manuelle : ne pas élargir
les chemins autorisés ni supprimer arbitrairement les fichiers signalés.
La purge est bornée et peut rester différée ; pas de garantie lorsque le PC est arrêté.

## Suppression ultérieure d'un compte — procédure à concevoir

Aucun bouton ni service complet de suppression du compte n'est livré ici.
Prévoir : vérification d'identité, arrêt des nouvelles actions, révocation de
toutes les sessions, inventaire et suppression des rêves, purge vérifiée des
dépendances, puis suppression du compte et traitement des données de sécurité.
Les clés étrangères RESTRICT interdisent un simple effacement du compte sans
orchestration. Définir le devenir des admissions IA et compteurs pseudonymisés,
des sauvegardes et des preuves minimales nécessaires sans conserver les récits.
Ne pas convertir ce plan en commandes SQL manuelles sur des données réelles.

## Résidus temporaires, sauvegardes et restauration

Inventorier uniquement les répertoires temporaires gérés et approuvés : exports,
conversion audio et sous-processus image/émotion. Vérifier âge, propriétaire,
absence de traitement actif, références et liens avant nettoyage autorisé.
Le répertoire temporaire système n'est pas entièrement géré par P19. Ne jamais
faire de suppression récursive générale ni inclure les modèles dans ce nettoyage.
La maintenance P19 des orphelins est distincte de la purge complète d'un rêve.

Les sauvegardes PostgreSQL, médias et WAL ne sont pas effacés par P10. Tenir un
inventaire des copies et dates d'expiration, restreindre les accès et prévoir
une protection adaptée. Un manifeste d'intégrité ne chiffre pas les données.
Ne pas modifier une sauvegarde vérifiée pour en retirer quelques lignes : créer
une nouvelle sauvegarde après purge et expirer les anciennes selon la politique
autorisée. Lors d'une restauration isolée, réconcilier les retraits intervenus
depuis la sauvegarde avant remise en service, sans recréer de liens publics.
La suppression applicative ne garantit pas l'effacement forensic des supports.

## Informations humaines à compléter

Identité et contact du responsable ; périmètre réel d'utilisation ; bases
juridiques par finalité ; éventuel consentement et modalités de retrait ; canal
et vérification d'identité pour les droits ; durées définitives ; rotation et
protection des sauvegardes ; conditions des services externes et rôles à qualifier.
L'autorisation microphone ou l'acceptation d'une émotion n'est pas un consentement
général à tous les traitements. Pas de case obligatoire « consentement RGPD »
ajoutée sans décision justifiée. Les licences des modèles ne sont pas des accords
de sous-traitance. Aucun fournisseur distant d'inférence n'est raccordé ici.

## Validation et limites de cette phase

Tests dédiés : page publique sans dépendance PostgreSQL, liens, non-réflexion de
marqueurs fictifs, ressources locales et distinction des propositions. Les tests
ne prétendent pas prouver l'absence de toute donnée personnelle possible ; ils
vérifient que la page statique ne sélectionne ni ne reflète de données privées.
Compléter par les parcours d'authentification sur PostgreSQL temporaire.
Vérification manuelle : ouvrir `/confidentialite` sans connexion et à 390 px,
suivre les liens depuis inscription et pied de page, contrôler les décisions à
compléter. Aucun tiers ajouté. Classes Tailwind existantes réutilisées ; aucune
modification ni compilation du CSS indépendant nécessaire.

### Résultats exécutés le 13 novembre 2026

- 59 tests réussis : `test_privacy.py` (9 cas), `test_web.py`,
  `test_authentication.py` et `test_history_web.py`. Cluster PostgreSQL natif
  jetable, port dynamique et schémas de test ; URL applicative également remplacée
  par l'URL temporaire. Cluster arrêté et répertoire temporaire nettoyé par le
  lanceur existant. Aucun accès à la base personnelle et aucune inférence.
- Une première campagne sans PostgreSQL a révélé deux défauts de test/intégration :
  page absente de la liste des protections web, et assertion ne reconnaissant pas
  les URL absolues locales de Jinja2. Corrections puis campagne verte ci-dessus.
- Ruff ciblé, compilation Python et `git diff --check` réussis. Avertissements
  Git LF/CRLF uniquement. Classes utilisées vérifiées dans le CSS déjà compilé ;
  pas de génération Tailwind ni de modification du CSS source ou compilé.
- Pas de campagne complète ni de validation visuelle Chrome exécutée dans cette
  phase documentaire. Les contrôles HTML passent par TestClient, pas par Chrome.
- `frontend/styles/app.css` préservé : SHA256
  `d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.

## Phase 3 — Recette finale du 13 novembre 2026

### Campagnes réellement exécutées

- Suite complète `backend/tests` sur PostgreSQL natif temporaire : **823 réussis,
  13 ignorés**, durée **459,21 secondes**. Couverture backend : **90,17 %**
  (4 454 instructions, 438 non couvertes). Les URL applicative et de test ont été
  dirigées vers le cluster jetable, jamais vers la base personnelle.
- Parmi les 13 cas ignorés : 12 parcours navigateur faute de serveur web dans
  cette première campagne, et un test réel émotionnel explicitement opt-in.
- Campagne Chrome séparée sur HTTPS et PostgreSQL temporaires : **14 réussis,
  824 désélectionnés**, durée **127,12 secondes**. Elle comprend les 12 parcours
  précédemment ignorés et les deux nouveaux cas P13 (1280 et 390 px). Les
  désélections sont le filtre `browser`, pas des échecs. Aucune inférence réelle.
- Les deux cas P13 ont aussi été exécutés seuls : **2 réussis en 5,47 secondes**.
  Il s'agit des mêmes tests, pas de deux validations supplémentaires distinctes.
- Ruff sur `backend` et `scripts`, compilation Python et `git diff --check` :
  réussis. Avertissements de conversion LF/CRLF uniquement, aucun défaut bloquant.

### Contrôles Chrome et confidentialité

L'accès interactif au navigateur n'était pas disponible dans cette session.
Les contrôles ont donc utilisé Chrome installé en mode sans interface, avec un
profil de test vierge et un certificat HTTPS de recette. Ce n'est pas une
navigation manuelle sur l'instance personnelle. Le contrôle ordinateur manuel
fourni par l'utilisateur complète cette recette automatisée.

`test_privacy_browser.py` vérifie aux deux largeurs : HTTP 200 sans session,
titre visible, distinction des propositions non activées, absence de débordement
horizontal, lien du pied de page et lien dans le formulaire d'inscription,
navigation jusqu'à la notice, absence d'erreur JavaScript et requêtes limitées
à l'origine temporaire. Les captures publiques ordinateur/mobile ont été
inspectées : texte et liens lisibles, aucune donnée de compte affichée.
Les captures de recette sont hors Git dans un répertoire temporaire dédié.

Les tests statiques P13 refusent tout accès à PostgreSQL sur les pages publiques
et vérifient la non-réflexion de marqueurs fictifs dans les paramètres, en-têtes
et cookies. Six contrôles de cohérence notice/documentation ont confirmé les
durées effectives, l'absence d'effacement audio automatique, les propositions
inactives et les informations humaines à compléter. Aucun CDN ajouté.

### Non-régression et purge audio

P10/P11/P12 sont inclus dans la suite : exports, droits, CSRF, suppression,
purge, relances bornées, maintenance, quotas persistants, limites HTTP et logs.
`test_complete_purge_preserves_other_dreams_users_and_sessions` crée notamment
un audio WAV et une image fictifs, puis vérifie l'absence de leurs fichiers,
des lignes et instantanés associés, le refus des anciennes URL et la conservation
des autres données. La reprise après interruption et les blocages sont couverts
par les autres tests du service de purge. Aucun mécanisme de purge n'a été modifié.

Les recettes ont terminé avec succès et leurs serveurs/clusters jetables ont
été arrêtés, répertoires de travail nettoyés. Le contrôle des processus associés
aux préfixes des recettes ne trouve aucun processus PostgreSQL/Python restant.
Aucun volume Docker personnel ni aucune donnée personnelle n'a été utilisé.

### Critères SCRUM-17 et réserves humaines

| Critère | Résultat |
|---|---|
| Notice compréhensible | Validé techniquement : page française publique, liens, lecture ordinateur/mobile et limites explicites |
| Suppression audio prévue | Validé : purge complète existante testée et documentée ; délais audio proposés clairement non activés |
| Prestataires et conditions avant données réelles | Information et condition préalable documentées ; validation contractuelle/juridique non réalisée et non revendiquée |

Avant ouverture à des utilisateurs réels, compléter responsable et contact,
bases juridiques, éventuel consentement, modalités d'exercice des droits, durées
définitives et vérifications applicables aux services utilisés. La notice ne
déclare pas une conformité RGPD. Pas de suppression de compte en libre-service,
de rotation générale ni de garantie de purge lorsque la maintenance est arrêtée.
La restauration des sauvegardes doit tenir compte des suppressions.

Aucun défaut bloquant P13 constaté. En phase 3, seul le test navigateur a été
ajouté et ce rapport complété ; aucun changement fonctionnel ni migration.
Le CSS indépendant conserve l'empreinte indiquée ci-dessus. Aucun `git add`,
commit, push, restauration Git ou changement Jira ; aucune automatisation activée.
