# P14 — Diagnostic de l'échec initdb sur GitHub Windows

Point de départ : commit publié `018cb65`, échec de `initdb.exe` avant lancement
de pytest. La sortie native a été supprimée par le lanceur : la trace disponible
prouve un code de sortie non nul, **pas la raison exacte** de l'échec distant.

## Hypothèse principale, fortement étayée mais à confirmer à distance

Conflit entre les ACL du répertoire `TemporaryDirectory` et le jeton restreint
des processus PostgreSQL sous Windows. Python 3.12.4+ traite le mode 0700 avec des
ACL Windows particulières. Sur un compte administrateur, des droits reposant sur
Administrators peuvent disparaître lorsque PostgreSQL retire ce groupe de son
jeton. Le SID utilisateur, lui, reste présent : il faut un droit explicite pour
ce SID, héritable par les fichiers et répertoires de la recette.

Références primaires examinées :

- [Documentation Python 3.12, os.mkdir](https://docs.python.org/3.12/library/os.html#os.mkdir)
  (changement Windows en 3.12.4).
- [Workflow officiel PostgreSQL](https://github.com/postgres/postgres/blob/master/.github/workflows/pg-ci.yml)
  : commentaire sur `CreateRestrictedProcess`, runneradmin et ACL utilisateur.

Le précontrôle GitHub ayant réussi, `initdb.exe` existe et `--version` fonctionne.
Cela n'établit ni les ACL effectives du runner ni l'accès au mot de passe et au
répertoire data avec le jeton restreint. Le nouveau précontrôle vérifie aussi
`postgres.exe`, nécessaire à l'amorçage. Le rôle, l'emplacement et les permissions
du runner n'ont pas été inspectés directement : aucun accès au run distant ici.

## Correction limitée aux ressources neuves

`scripts/postgres_test_runtime.py::prepare_directory` est appelé immédiatement
après création du dossier temporaire, avant `password` et `data`, dans les deux
lanceurs concernés (`verify_image_jobs.py` et `verify_p20.py`).

1. Réutilisation de `checked_root` P14 : hors dépôt/OneDrive, préfixe connu,
   racine sans lien/jonction. Refus d'une racine non vide.
2. Lecture privée du SID utilisateur par `whoami /user /fo csv /nh` ; validation
   stricte du format SID de compte Windows local/domaine.
3. `icacls` accorde `(OI)(CI)F` uniquement à ce SID sur la racine neuve.
   Aucun droit Everyone/Users, pas de `/T`, `/reset`, suppression d'ACL ni
   modification du dossier parent, du dépôt ou du volume personnel.
4. Échec avant initdb si cette préparation est impossible. Le nom du compte,
   le SID et le chemin ne sont pas imprimés.

Les listes de bases autorisées, refus de `dreams_local`, URL cohérentes, rôles,
ports, manifeste, contrôle de `data_directory`, tests et seuil métier de 80 %
restent inchangés. `scripts/test_safety.py` n'est pas modifié. Aucun passage en
authentification `trust`, aucune utilisation du service PostgreSQL préinstallé.

## Diagnostics natifs non sensibles

Les commandes PostgreSQL utilisent un fichier temporaire privé, lu au maximum
sur 64 Kio puis fermé, jamais envoyé comme artefact. Leur sortie native n'est
pas affichée. Un pipe est évité : sous Windows, le serveur peut conserver un
handle de sortie de `pg_ctl`, ce qui bloque la fin de `communicate()` malgré
le démarrage du serveur. Ce piège a été observé et corrigé pendant la validation
locale ; le seul cluster de cette tentative a été arrêté après vérification de
son PID et de sa racine temporaire, sans toucher aux services personnels.

Les messages n'exposent que l'étape, une catégorie et le code de sortie :

```text
postgres_setup:user_acl_failed
postgres_setup:user_acl_unavailable
postgres_temporary:initdb:permission_denied:exit=1
postgres_temporary:initdb:directory_not_empty:exit=1
postgres_temporary:initdb:invalid_locale:exit=1
postgres_temporary:initdb:runtime_unavailable:exit=...
postgres_temporary:initdb:process_failed:exit=1
postgres_temporary:pg_ctl:timeout
```

Exécutable manquant/refusé et erreur d'authentification disposent également de
catégories. Aucun mot de passe, commande complète, SID, chemin ou extrait natif
ne doit être ajouté au diagnostic public. Une catégorie de panne est un indice,
pas une preuve exhaustive de causalité.

## Tests et validation

Les nouveaux tests vérifient l'ACE visant le seul utilisateur et la seule racine,
le refus d'une racine peuplée/non autorisée, le SID invalide, l'échec d'ACL, les
catégories natives, l'absence de marqueurs privés et l'absence de PIPE pour
`pg_ctl`. Les modifications de permissions y sont simulées.

Les validations réelles utilisent seulement des clusters et comptes fictifs.
Le test natif local vérifie initdb, démarrage, migrations, autorisations et
nettoyage, mais **ne reproduit pas le jeton du compte GitHub runneradmin**.
Le succès distant reste à confirmer après votre commit/push.

Commandes conservées pour le prochain run :

```powershell
.\.venv\Scripts\python.exe scripts\verify_image_jobs.py --business-coverage
.\.venv\Scripts\python.exe scripts\verify_p20.py --browser-only --emotion-web-test
```

Attendus sur GitHub : préparation de l'accès utilisateur, cluster temporaire
démarré, pytest et couverture >= 80 %, puis Chrome. Si initdb échoue encore,
relever uniquement la nouvelle catégorie et le code : ne pas publier la sortie
native, ne pas élargir les droits à un groupe, ne pas désactiver l'intégration.
Aucune exécution distante n'a été effectuée ni revendiquée ici.

## Résultats locaux réellement exécutés

- **461 tests unitaires réussis**, 454 désélectionnés, 25,51 s, sans PostgreSQL.
- **78 tests ciblés réussis**, 27,00 s, sur un cluster natif jetable : les 14
  nouveaux cas de régression, les gardes P14, migrations/contraintes PostgreSQL,
  conservation des données historiques en 0010 et authentification/intercomptes.
  `initdb` et le démarrage du serveur avec la nouvelle préparation ACL ont réussi.
- **14 parcours Chrome réussis**, 901 désélectionnés, 114,58 s : autre cluster
  neuf préparé par le même helper, HTTPS, comptes/médias fictifs, redémarrage
  PostgreSQL/Uvicorn et contrôles de relecture/purge du média fictif.
- Ruff `backend scripts`, compilation Python et `git diff --check` réussis.
  Aucun nouveau calcul de couverture complet : code métier et seuil inchangés.
- Binaires locaux vérifiés sans connexion : initdb et postgres **17.5** ;
  Python **3.12.14**. Ces versions ne décrivent pas l'exécution distante échouée.
- Nettoyage confirmé : aucun processus PostgreSQL/Python des recettes restant.
  Aucun volume ni service personnel arrêté. Les campagnes se recouvrent et ne
  doivent pas être additionnées comme des cas uniques.

Fichiers modifiés : les deux lanceurs et `.github/workflows/tests.yml` (contrôle
supplémentaire de `postgres.exe`). Créés : le helper, son fichier de tests et ce
rapport. `scripts/test_safety.py`, la liste de bases, le seuil et le code métier
ne sont pas modifiés. Le CSS indépendant conserve son empreinte
`d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.

Statut : correction proposée et testée localement, **pas encore confirmée sur
GitHub Actions**. Aucun commit, push ou changement Jira effectué.
