# P11 — SCRUM-15 : recette finale

Date : 13 novembre 2026. Base Git : `79a8265`, branche `main`.
Ce rapport porte sur les cinq phases P11. Aucune commande de la procédure
personnelle ci-dessous n'a été exécutée. Aucun accès à `dreams_local`, aucune IA
réelle, aucun changement Jira, aucun ajout à l'index, commit ou push.

## Critères et garanties vérifiées

| Critère | Implémentation et preuve |
| --- | --- |
| États visibles | `tracking` expose `queued`, `running`, `done`, `failed`, séparément de `outdated` et de l'abstention. Tests routes, services et Chrome STT/image/émotion. |
| Échec visible et relançable dans une limite | Messages français sûrs ; confirmation et CSRF ; au plus 3 exécutions et 2 relances manuelles par cycle. Compteurs persistants et budget agrégé entre jobs de même identité, y compris la régénération volontaire P07. Tests d'épuisement, concurrence et demandes répétées. |
| Pas de blocage définitif lorsque la maintenance fonctionne | Maintenance sans modèle, inventaire par défaut, application explicite ; expiration contrôlée vers `failed`, révocation des réservations, aucune nouvelle inférence automatique. Tests d'expiration, interruption, concurrence et reprise. |

L'attente est un polling GET non bloquant, avec timeout réseau de 8 s, recul
progressif borné et arrêt à l'état terminal. Les erreurs de suivi ne sont pas
présentées comme des échecs du traitement. Rechargement, retour sur un onglet,
rétablissement du réseau et cache de navigation ne créent aucun job.

Les API Bearer et sessions restent distinctes ; toutes les actions web vérifient
le CSRF, le propriétaire, le rêve, les versions et le budget transactionnellement.
Les anciennes réponses P05/P07/P08 sont conservées ; `tracking` est additif.
Les résultats tardifs ne peuvent publier après expiration, correction P06,
changement de description, retrait/choix manuel P08 ou suppression P10. Les
émotions retenues ne sont jamais modifiées par le worker. P09 conserve ses filtres
et `Dream.status` ; les médias restent servis par P19, jamais par `/static/`.

## Recette exécutée

Les lanceurs créent un PostgreSQL natif temporaire sur un port libre distinct
de 5434, des médias fictifs et un serveur temporaire. Ils ne chargent aucun modèle.

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --p11-final
.\.venv\Scripts\python.exe scripts/verify_p20.py --emotion-web-test
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend scripts
Get-ChildItem backend/app/web/static/js -Filter *.js | ForEach-Object {
    node --check $_.FullName
    if ($LASTEXITCODE -ne 0) { throw 'JavaScript invalide' }
}
& frontend/node_modules/.bin/tailwindcss.cmd -i frontend/styles/app.css -o "$env:TEMP/p11-final-tailwind.css" --minify
git diff --check
```

Résultats ciblés : **212 tests réussis en 57,47 s** (une première campagne avait
également réussi : 212 en 57,06 s). Les huit nouveaux tests de recette finale
complètent les tests des phases précédentes. Campagne finale complète :
**742 réussis, 1 ignoré en 471,07 s**, couverture backend **89,47 %**
(4 236 instructions, 446 non couvertes). Aucun avertissement dans cette campagne.
Le test ignoré est l'inférence réelle mDeBERTa opt-in, interdite dans cette recette.
Les trois parcours Chrome P11 STT/image/émotion réussissent sur ordinateur et
à 390 px ; captures inspectées visuellement, confirmations et absence de
débordement vérifiées. La suite couvre aussi P01 à P10, P19 et P20.

Première campagne complète : 741 réussis, 1 échec, 1 ignoré en 461,61 s,
couverture 89,40 %. L'échec venait de l'attente du test Chrome P09 : une expression
JavaScript sous forme de chaîne était refusée par CSP. Correction limitée au test
(fonction fléchée), sans modification de sécurité de production. Un avertissement
Pydantic relatif à un alias a également été observé pendant le test concurrent STT.
La campagne finale a confirmé la correction et n'a pas reproduit cet avertissement.

Ruff, compilation Python, syntaxe des **8 fichiers JavaScript**, compilation
Tailwind **4.3.0** vers un fichier temporaire et `git diff --check` : réussis.
Les avertissements Git LF/CRLF concernent la normalisation Windows, sans erreur
de contenu. Le CSS source et le CSS compilé livré ne sont pas réécrits.

## Migration 0008 → 0009

`0009_job_retries.py` ajoute seulement `retry_count`, `queued_at`, `cycle_key` et
`input_snapshot` dans `jobs`, les contraintes associées et l'index `ix_jobs_cycle`.
Les anciens jobs reçoivent `retry_count=0`, `queued_at=created_at` ; leur identité
et instantané restent NULL. Aucun récit, média ou instantané P07/P08 n'est effacé.

Le test final compare les nombres et SHA-256 de **toutes les tables métier** en
0008 et 0009, en excluant uniquement les quatre nouveaux champs pour cette
comparaison. Il comprend deux utilisateurs, deux rêves, des médias, les quatre
états de jobs STT/image/émotion, des réservations actives, descriptions, instantanés,
émotions explicites et une abstention. Les données historiques restent identiques.
Une reconnexion est testée ainsi qu'un aller-retour 0008/0009 sur ces données.
Les contraintes de budget et de cohérence JSON/identité rejettent les cas invalides.

Deux défaillances sont injectées après un ALTER TABLE : exception et **coupure
réelle de la connexion de migration temporaire**. Dans les deux cas, la transaction
annule le DDL et les écritures : révision 0008, absence des nouvelles colonnes,
empreintes et compteurs inchangés. Une migration normale est ensuite vérifiée
sur la copie. Ce test ne prétend pas simuler une panne matérielle ou électrique.

Le lanceur complet compare aussi l'intégralité des données, budgets et
réservations après arrêt puis redémarrage effectif du PostgreSQL/Uvicorn temporaire.
Ce contrôle a réussi, y compris avec deux jobs ajoutés explicitement : budget
épuisé (3 exécutions, 2 relances) et réservation active avec compteurs non nuls.
L'historique P09 est identique, l'audio P04 est relu en HTTP 200 ; le média P19
est relu en 200 puis refusé en 404 après programmation de sa purge fictive.
Les serveurs et leurs ressources temporaires sont nettoyés par le lanceur.
L'inventaire final des processus de recette retourne **0 processus restant**.
La sortie de compilation Tailwind temporaire a également été retirée.
L'inventaire `scripts/p11_inventory.py` ne se connecte pas seul : son appelant doit
fournir une connexion. Il ne retourne que révision, compteurs et empreintes ; les
contenus sont hachés côté PostgreSQL, avec UTC et collation C pour la reproductibilité.

### Restrictions historiques et déploiement

- Un ancien compteur à zéro ne prouve pas l'absence de tentatives antérieures.
  Aucun cycle n'est inventé pour les jobs historiques sans identité fiable.
  Leur relance est refusée ; un job historique en attente échoue de façon contrôlée,
  un job en cours est récupéré à expiration. Une famille rêve/type contenant une
  identité historique NULL bloque également les nouvelles demandes jusqu'à examen
  explicite. Ne pas supprimer l'historique pour contourner cette protection.
- Le downgrade refuse de retirer les budgets si des cycles P11 ou relances existent.
  La réversibilité est démontrée sur les jobs historiques, pas après utilisation P11.
- Les API et points d'entrée actuels sont compatibles ; **les anciens exécutables
  de workers ne doivent pas fonctionner avec les nouveaux** : arrêter puis mettre
  à jour tous les processus. Il n'y a pas de garantie contre un vieux binaire qui
  écrirait directement en base en ignorant P11.
- Les ALTER TABLE et le remplissage de `queued_at` prennent des verrous. Prévoir
  arrêt des écrivains, délais bornés et sauvegarde fraîche vérifiée.

## Délais et limites opérationnelles

Attente initiale : 1 800 s ; STT : timeout réellement configuré (600 s par défaut,
jusqu'à 1 800 s), image et émotion : 120 s par défaut ; marge de bail : 120 s.
Les délais des ponts image/émotion et de leurs sous-processus restent inférieurs
au bail ; le STT ne reçoit pas un bail plus court que son processus.
Maintenance : intervalle de 5 s lorsque son service fonctionne.

Si tous les processus sont arrêtés ou PostgreSQL indisponible, aucune maintenance
ne peut agir ; la récupération a lieu au retour du service. Les erreurs DB sont
traitées sans nouvelle exécution IA automatique. Révoquer un résultat n'arrête pas
nécessairement instantanément un calcul externe déjà commencé. Pas de progression
fine ni de push serveur ; une vue terminale se met à jour au retour/rechargement.
Les résultats de qualité et performances des modèles ne sont pas réévalués ici.

## Procédure personnelle PowerShell — préparée, NON exécutée

**Chaque accès à la base personnelle et chaque écriture décrite ici nécessitent
une autorisation humaine séparée.** La recette actuelle n'autorise aucun de ces
blocs. La révision personnelle n'a donc pas été vérifiée pendant cette phase.
La cible attendue est `127.0.0.1:5434/dreams_local` en 0008 ; le Compose déclare
PostgreSQL 17, service `postgres`, volume nommé `postgres_data`. La valeur exemple
du port n'est pas une preuve de la configuration effective. Ne jamais publier
`docker compose config`, DATABASE_URL ou les variables contenant les mots de passe.

### 1. Arrêt contrôlé et sauvegarde — autorisation distincte

Arrêter proprement FastAPI et tous les workers STT/image/émotion, ainsi que les
maintenances jobs/médias/purge. Inventorier leurs PID et les arrêter dans leurs
terminaux par Ctrl+C ; ne pas arrêter Docker ou PostgreSQL. Vérifier ensuite
l'absence de ces processus. Ne pas imprimer leurs lignes de commande complètes.

Les commandes suivantes sont à lancer à la racine du dépôt **après autorisation** :

```powershell
$ErrorActionPreference = 'Stop'
$p11Container = (& docker compose ps -q postgres).Trim()
if (-not $p11Container) { throw 'Conteneur PostgreSQL absent' }
if ((& docker inspect --format '{{.State.Health.Status}}' $p11Container).Trim() -ne 'healthy') { throw 'PostgreSQL non healthy' }
if ((& docker port $p11Container 5432/tcp).Trim() -ne '127.0.0.1:5434') { throw 'Mauvais port cible' }
$p11Stamp = (Get-Date -Format yyyyMMdd-HHmmss) + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$env:P11_BACKUP_ROOT = Join-Path $env:LOCALAPPDATA "SynthetiseurDeReves/backups/p11-$p11Stamp"
New-Item -ItemType Directory -Path $env:P11_BACKUP_ROOT | Out-Null
$p11Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls $env:P11_BACKUP_ROOT /inheritance:r /grant:r "*${p11Sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F'
if ($LASTEXITCODE -ne 0) { throw 'ACL sauvegarde non appliquee' }
```

Définir ce contrôle Python dans la session PowerShell. Il n'est exécuté que par
les appels explicites suivants. Les secrets sont lus en mémoire, jamais affichés.

```powershell
$p11Control = @'
import json, os
from pathlib import Path
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from scripts.p11_inventory import capture

temporary = os.environ.get('P11_TARGET') == 'temporary'
url = make_url(os.environ['DATABASE_URL'] if temporary else dotenv_values('.env')['DATABASE_URL'])
assert url.drivername == 'postgresql+psycopg'
assert url.host in ('127.0.0.1', 'localhost')
assert not url.query, 'Refuser les substitutions de connexion'
assert (url.database == 'p11_copy' and url.port != 5434) if temporary else (url.database == 'dreams_local' and url.port == 5434)
root = Path(os.environ['P11_BACKUP_ROOT'])
action = os.environ.get('P11_ACTION', 'before')
engine = create_engine(url, hide_parameters=True)
try:
    with engine.begin() as c:
        c.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
        c.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
        c.exec_driver_sql('SET LOCAL search_path = public')
        if action != 'upgrade':
            c.exec_driver_sql('SET TRANSACTION READ ONLY')
        assert c.scalar(text('SELECT current_database()')) == url.database
        before = capture(c, legacy_jobs=True)
        saved = root / 'before-0008.json'
        if action == 'before' and not temporary:
            assert before['revision'] == '0008'
            assert not saved.exists(), 'Ne pas remplacer l inventaire'
            saved.write_text(json.dumps(before, indent=2), encoding='utf-8')
        else:
            original = json.loads(saved.read_text(encoding='utf-8'))
            assert before['tables'] == original['tables'], 'Donnees changees : arret'
            assert before['revision'] == ('0009' if action == 'after' else '0008')
        if action == 'upgrade':
            cfg = Config('alembic.ini')
            cfg.attributes['connection'] = c
            command.upgrade(cfg, '0009')
            after = capture(c, legacy_jobs=True)
            assert after['revision'] == '0009' and after['tables'] == before['tables']
            assert c.scalar(text('''SELECT count(*) FROM jobs WHERE retry_count <> 0
                OR queued_at IS DISTINCT FROM created_at OR cycle_key IS NOT NULL
                OR input_snapshot IS NOT NULL''')) == 0
            assert c.scalar(text("SELECT to_regclass('ix_jobs_cycle') IS NOT NULL"))
            assert c.scalar(text("""SELECT count(*) FROM pg_constraint
                WHERE conrelid='jobs'::regclass
                AND conname IN ('ck_job_retry_count','ck_job_cycle')""")) == 2
    print('Controle termine sans afficher de donnees privees :', action)
finally:
    engine.dispose()
'@
$env:P11_TARGET = 'personal'
$env:P11_ACTION = 'before'
$p11Control | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Precontrole personnel refuse' }
```

**Écriture de sauvegarde personnelle — autorisation distincte.** Utiliser un nom
unique dans `/tmp` du conteneur ; aucune redirection binaire PowerShell :

```powershell
$p11DumpInside = "/tmp/p11-$p11Stamp.dump"
& docker exec $p11Container sh -c 'umask 077; test "$POSTGRES_DB" = dreams_local || exit 1; exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl -f "$1"' sh $p11DumpInside
if ($LASTEXITCODE -ne 0) { throw 'pg_dump a echoue' }
& docker cp "${p11Container}:$p11DumpInside" "$env:P11_BACKUP_ROOT/dreams-0008.dump"
if ($LASTEXITCODE -ne 0) { throw 'Copie sauvegarde echouee' }
$p11Pg = 'C:/Program Files/PostgreSQL/17/bin'
& "$p11Pg/pg_restore.exe" --list "$env:P11_BACKUP_ROOT/dreams-0008.dump" | Set-Content "$env:P11_BACKUP_ROOT/archive-list.txt"
if ($LASTEXITCODE -ne 0) { throw 'Archive illisible' }
(Get-FileHash "$env:P11_BACKUP_ROOT/dreams-0008.dump" -Algorithm SHA256).Hash | Set-Content "$env:P11_BACKUP_ROOT/archive.sha256" -Encoding Ascii
```

La liste seule ne prouve pas la restauration : étape suivante obligatoire.
Copier aussi tous les fichiers P19 avec leurs empreintes, sans suivre de lien :

```powershell
@'
import hashlib, json, os, shutil
from pathlib import Path
from dotenv import dotenv_values
cfg = dotenv_values('.env')
candidate = Path(cfg.get('PRIVATE_MEDIA_ROOT') or Path(os.environ['LOCALAPPDATA']) / 'SynthetiseurDeReves/private_media')
assert candidate.is_absolute()
assert all(not p.is_symlink() and not p.is_junction() for p in (candidate, *candidate.parents))
src = candidate.resolve()
root = Path(os.environ['P11_BACKUP_ROOT']).resolve()
assert all(not p.is_symlink() and not p.is_junction() for p in (root, *root.parents))
repo = Path.cwd().resolve()
assert src.is_dir() and src != src.parent
assert not src.is_relative_to(repo) and not root.is_relative_to(src) and not src.is_relative_to(root)
assert not any(p.lower().startswith('onedrive') for p in (*src.parts, *root.parts))
def manifest(base):
    rows = {}
    for current, dirs, files in os.walk(base, followlinks=False):
        for name in dirs + files:
            p = Path(current) / name
            assert not p.is_symlink() and not p.is_junction(), 'Lien refuse'
        for name in files:
            p = Path(current) / name
            with p.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            rows[p.relative_to(base).as_posix()] = [p.stat().st_size, digest]
    return rows
assert all(not p.is_symlink() and not p.is_junction() for p in (src, *src.parents))
before = manifest(src)
dst = root / 'private_media'
shutil.copytree(src, dst)
assert before == manifest(dst) == manifest(src)
(root / 'media-manifest.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
print('Medias copies et verifies ; chemins non affiches.')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Sauvegarde medias non validee' }
```

Ne pas continuer si un fichier change, si un lien est trouvé ou si les services
écrivains ne sont pas arrêtés. Conserver les manifestes dans le dossier protégé,
jamais dans Git. Les ACL ne constituent pas un chiffrement de sauvegarde.

### 2. Restauration et répétition isolées — autorisation distincte

Ces commandes créent seulement un cluster natif temporaire, pas de volume Docker.
La copie contient des données personnelles : ne démarrer ni serveur web ni worker.

```powershell
$p11RestoreRoot = Join-Path $env:P11_BACKUP_ROOT ('p11-restore-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $p11RestoreRoot | Out-Null
$p11Listen = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
$p11Listen.Start(); $p11Port = $p11Listen.LocalEndpoint.Port; $p11Listen.Stop()
if ($p11Port -eq 5434) { throw 'Port personnel interdit' }
$p11Pw = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
[IO.File]::WriteAllText("$p11RestoreRoot/pw.txt", $p11Pw)
& "$p11Pg/initdb.exe" -D "$p11RestoreRoot/data" -U p11_review --encoding=UTF8 --locale=C --auth=scram-sha-256 "--pwfile=$p11RestoreRoot/pw.txt"
if ($LASTEXITCODE -ne 0) { throw 'initdb a echoue' }
Remove-Item -LiteralPath "$p11RestoreRoot/pw.txt"
$p11OldUrl = $env:DATABASE_URL; $p11OldPass = $env:PGPASSFILE
$env:PGPASSFILE = "$p11RestoreRoot/pgpass.conf"
[IO.File]::WriteAllText($env:PGPASSFILE, "127.0.0.1:${p11Port}:*:p11_review:$p11Pw")
$p11Pw = $null
& "$p11Pg/pg_ctl.exe" -D "$p11RestoreRoot/data" -l "$p11RestoreRoot/postgres.log" -o "-h 127.0.0.1 -p $p11Port" -w start
if ($LASTEXITCODE -ne 0) { throw 'Cluster temporaire non demarre' }
try {
    & "$p11Pg/createdb.exe" -h 127.0.0.1 -p $p11Port -U p11_review p11_copy
    if ($LASTEXITCODE -ne 0) { throw 'Creation copie echouee' }
    & "$p11Pg/pg_restore.exe" -h 127.0.0.1 -p $p11Port -U p11_review -d p11_copy --exit-on-error --no-owner --no-acl "$env:P11_BACKUP_ROOT/dreams-0008.dump"
    if ($LASTEXITCODE -ne 0) { throw 'Restauration echouee' }
    $env:DATABASE_URL = "postgresql+psycopg://p11_review@127.0.0.1:$p11Port/p11_copy"
    $env:P11_TARGET = 'temporary'; $env:P11_ACTION = 'before'
    $p11Control | .\.venv\Scripts\python.exe -
    if ($LASTEXITCODE -ne 0) { throw 'Donnees restaurees incoherentes' }
    $env:P11_ACTION = 'upgrade'
    $p11Control | .\.venv\Scripts\python.exe -
    if ($LASTEXITCODE -ne 0) { throw 'Repetition 0009 echouee' }
    $env:P11_ACTION = 'after'
    $p11Control | .\.venv\Scripts\python.exe -
    if ($LASTEXITCODE -ne 0) { throw 'Verification apres repetition echouee' }
} finally {
    & "$p11Pg/pg_ctl.exe" -D "$p11RestoreRoot/data" -m fast -w stop
    $env:DATABASE_URL = $p11OldUrl; $env:PGPASSFILE = $p11OldPass
}
```

Vérifier l'arrêt du seul cluster temporaire avant nettoyage. Exécuter cette
vérification d'intégrité après restauration et de nouveau après migration
personnelle (chaque accès personnel exige son autorisation) :

```powershell
if ((Get-FileHash "$env:P11_BACKUP_ROOT/dreams-0008.dump" -Algorithm SHA256).Hash -ne (Get-Content "$env:P11_BACKUP_ROOT/archive.sha256").Trim()) { throw 'Archive modifiee' }
@'
import hashlib, json, os
from pathlib import Path
from dotenv import dotenv_values
root = Path(os.environ['P11_BACKUP_ROOT'])
expected = json.loads((root / 'media-manifest.json').read_text(encoding='utf-8'))
cfg = dotenv_values('.env')
source = Path(cfg.get('PRIVATE_MEDIA_ROOT') or Path(os.environ['LOCALAPPDATA']) / 'SynthetiseurDeReves/private_media')
for base in (source, root / 'private_media'):
    assert base.is_dir()
    assert all(not p.is_symlink() and not p.is_junction() for p in (base, *base.parents))
    actual = {}
    for current, dirs, files in os.walk(base, followlinks=False):
        for name in dirs + files:
            p = Path(current) / name
            assert not p.is_symlink() and not p.is_junction()
        for name in files:
            p = Path(current) / name
            with p.open('rb') as f:
                actual[p.relative_to(base).as_posix()] = [p.stat().st_size, hashlib.file_digest(f, 'sha256').hexdigest()]
    assert actual == expected, 'Medias modifies ou manquants'
print('Archive et medias proteges : controle termine sans contenu affiche.')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Integrite medias refusee' }
```

Conserver sauvegardes et manifestes. Pour effacer uniquement la copie : résoudre `$p11RestoreRoot`,
vérifier que son parent est exactement `$env:P11_BACKUP_ROOT`, que son nom commence
par `p11-restore-`, qu'il ne contient aucun lien et que `postmaster.pid` est absent,
puis seulement `Remove-Item -LiteralPath $p11RestoreRoot -Recurse`.
Ne jamais supprimer le dossier parent, l'archive ou le volume Docker personnel.
Retirer aussi le seul fichier `/tmp/p11-<identifiant>.dump` créé par cette procédure
après copie vérifiée, sans commande de suppression globale.

### 3. Migration personnelle — AUTORISATION HUMAINE DISTINCTE OBLIGATOIRE

Ne pas exécuter actuellement. Refaire santé, arrêt des écrivains, intégrité des
sauvegardes et comparaison avec l'inventaire 0008. Toute différence exige une
nouvelle sauvegarde et une nouvelle validation ; ne jamais remplacer l'ancienne.
Le bloc de contrôle garde une transaction unique, `lock_timeout=3s`,
`statement_timeout=30s`, cible exacte, révision initiale 0008 et cible 0009 uniquement.
Les vérifications avant/après sont dans la même transaction que le DDL.

```powershell
# ECRITURE PERSONNELLE : executer uniquement apres autorisation distincte.
$env:P11_TARGET = 'personal'; $env:P11_ACTION = 'upgrade'
$p11Control | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Migration arretee : conserver les services arretes' }
$env:P11_ACTION = 'after'
$p11Control | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Verification finale refusee' }
Remove-Item Env:P11_TARGET, Env:P11_ACTION, Env:P11_BACKUP_ROOT
```

Résultats attendus : révision 0009, toutes les empreintes historiques et tous les
compteurs conservés, nouveaux budgets par défaut, réservations historiques intactes
au niveau DDL, fichiers P19 inchangés. Faire valider les restrictions historiques
avant de redémarrer les services mis à jour. La maintenance peut ensuite invalider
les anciens jobs selon le contrat, ce qui est distinct de la migration.

En cas d'échec : rester arrêté, vérifier le rollback en 0008 avec une autorisation
de lecture, conserver les journaux sans secrets ; pas de `stamp`, correction SQL
des budgets ou retry automatique. Si la migration a été validée puis utilisée,
ne pas forcer le downgrade. Restaurer l'archive dans un **cluster de remplacement
distinct**, comparer ses empreintes et ses médias, puis demander une autorisation
de bascule avec la version applicative 0008 compatible (`79a8265`). Conserver une
sauvegarde du nouvel état avant toute restauration ; une restauration ancienne
perdrait les écritures effectuées depuis la sauvegarde. Aucune commande `--clean`,
suppression de base ou de volume personnel n'est proposée comme retour automatique.

## Git et décision de livraison

Liste complète des **53 fichiers P11** à inclure (phases 1 à 5) :
30 fichiers suivis modifiés et 23 nouveaux fichiers non suivis.
Le 54e chemin de `git status` est le CSS préexistant exclu.
Les statuts ci-dessous sont ceux de l'arbre de travail : `M` modifié, `??` nouveau.

```text
M  backend/app/emotion_web.py
M  backend/app/emotion_worker.py
M  backend/app/history_routes.py
M  backend/app/image_routes.py
?? backend/app/job_config.py
?? backend/app/job_routes.py
?? backend/app/job_rules.py
M  backend/app/main.py
M  backend/app/models.py
M  backend/app/services/emotions.py
M  backend/app/services/image_execution.py
M  backend/app/services/image_jobs.py
?? backend/app/services/job_lifecycle.py
?? backend/app/services/job_maintenance.py
?? backend/app/services/job_tracking.py
M  backend/app/services/stt_jobs.py
M  backend/app/stt_routes.py
M  backend/app/web/routes.py
M  backend/app/web/static/js/emotion.js
M  backend/app/web/static/js/image.js
?? backend/app/web/static/js/job-polling.js
M  backend/app/web/static/js/stt.js
?? backend/app/web/templates/_job_controls.html
M  backend/app/web/templates/dream_detail.html
M  backend/app/web/templates/emotion.html
M  backend/app/web/templates/image.html
M  backend/app/web/templates/transcription.html
?? backend/migrations/versions/0009_job_retries.py
M  backend/tests/test_emotion_browser.py
M  backend/tests/test_emotion_postgresql.py
M  backend/tests/test_emotion_web.py
M  backend/tests/test_history_browser.py
M  backend/tests/test_image_browser.py
M  backend/tests/test_image_jobs.py
?? backend/tests/test_job_lifecycle.py
?? backend/tests/test_job_maintenance_cli.py
?? backend/tests/test_job_routes_p11.py
?? backend/tests/test_job_rules.py
?? backend/tests/test_job_tracking_browser.py
?? backend/tests/test_p11_final_migration.py
M  backend/tests/test_postgresql.py
M  backend/tests/test_stt.py
M  backend/tests/test_stt_browser.py
?? backend/tests/test_worker_jobs_p11.py
?? docs/p11-final.md
?? docs/p11-phase1.md
?? docs/p11-phase2.md
?? docs/p11-phase3.md
?? docs/p11-phase4.md
?? scripts/job_maintenance.py
?? scripts/p11_inventory.py
M  scripts/verify_image_jobs.py
M  scripts/verify_p20.py
```

`frontend/styles/app.css` est explicitement exclu et conservé à l'empreinte
`d1fda91e232b38f31bfd3ccf71ec689a94d0b4f01cecf9d352c74e5daa7f3c2d`.

Message proposé : `feat(p11): fiabiliser les jobs asynchrones et les relances bornees`.

Contrôle des candidats : aucun modèle, environnement virtuel, média, archive ZIP,
clé privée, sauvegarde ou fichier `.env`. Aucun motif de jeton ou d'URL de
connexion contenant un mot de passe n'a été détecté dans les fichiers candidats.
Ce contrôle de noms et motifs complète la revue des différences. `.env`, `.venv`,
`.coverage` et les captures fictives `tmp/p11-screenshots/` sont ignorés.
L'index Git est vide.

Le seul changement du test d'historique préexistant transforme une expression
`wait_for_function` en fonction fléchée : cela évite une évaluation de chaîne
refusée par CSP. Aucune politique CSP de production n'est assouplie.

**Avis final : prêt pour validation du commit P11**, sans anomalie bloquante
reproduite dans la campagne finale. La livraison personnelle reste conditionnée
à l'examen des jobs historiques, à une sauvegarde/restauration contrôlée, à
l'autorisation explicite de migration et à la mise à jour de tous les workers.
Ne pas annoncer un déploiement personnel ou une migration personnelle validés.

Le commit, le déploiement personnel et la clôture Jira restent des opérations
distinctes soumises à validation ; aucune n'est réalisée par cette recette.
