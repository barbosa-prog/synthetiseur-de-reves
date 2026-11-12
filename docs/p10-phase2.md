# P10 — Phase 2 : ZIP et téléchargement privé

## Utilisation

Le détail `/reves/{id}` propose **Exporter ce rêve**. Le formulaire HTTPS fait
un POST `/reves/{id}/export`, avec session et preuve CSRF liée à la session.
L'API expose GET `/api/v1/dreams/{id}/export`, avec Bearer exclusivement.
Connaître l'UUID ne donne aucun droit. Un rêve absent, supprimé ou étranger
produit le même 404 ; une session web absente redirige vers la connexion.

L'export contient README.txt, recit.txt, reve.json, manifest.json et medias/.
Les documents et règles de sélection viennent de la phase 1. Les médias sont
ouverts uniquement par MediaService/stockage P19, jamais dans static. Toutes
les images disponibles sont exportées ; les versions déterminent séparément
laquelle est actuelle. La suggestion IA n'est pas une émotion retenue.

Le manifeste précise pour chaque média `exported`, `availability` et `reason`.
Un objet absent n'est pas ajouté au ZIP : `missing`, exported=false. Un objet
legacy, supprimé, expiré ou de format non reconnu reste indisponible. Une
empreinte ou taille incorrecte fait refuser l'archive entière (409). Une erreur
de stockage ou un lien/reparse dangereux n'est pas assimilé à un fichier absent.
La lecture ordinaire P19 conserve son comportement ; le mode strict est propre
à l'export et distingue intégrité, absence et stockage refusé.

## Ressources et confidentialité

- 100 médias et 100 Mio maximum. Les budgets incluent TXT/JSON et les octets
  des médias ; la taille physique du ZIP, en-têtes compris, est aussi bornée.
  EXPORT_MAX_MEDIA et EXPORT_MAX_BYTES permettent de réduire ces plafonds.
- ZIP_STORED, sans compression : temps CPU réduit, pas de charge de compression,
  aucun nom original ou chemin arbitraire utilisé. Extensions et noms générés
  par le contrat. Pas de symlink ni archive importée/réextraite côté serveur.
- Blocs de 64 Kio, sans archive ni média entier chargé en mémoire par P10.
  P19 vérifie taille/SHA-256 ; la copie les revérifie contre l'instantané initial.
- Un seul export simultané par base PostgreSQL, construction et téléchargement
  compris, via verrou advisory de session partagé entre processus. Un second
  export reçoit 409. Pas de nouvelle table ou migration.
- Construction : budget de 60 s, contrôlé entre les opérations ; les requêtes
  concernées ont des délais SQL (5 s et verrou 3 s pour les lectures de médias).
  Ce budget coopératif n'est pas un arrêt forcé d'un appel disque Windows bloqué.
- Livraison : 120 s maximum, avec annulation ASGI et nettoyage protégé contre
  l'annulation. Les délais couvrent aussi les clients lents.
- Espace initial requis : plafond de l'archive + réserve de 200 Mio.
  Le writer refuse les écritures dépassant le plafond, y compris le répertoire
  central ZIP. Une panne disque intervenue après précontrôle reste possible et
  entraîne le refus, pas une archive partielle présentée comme réussie.

Par défaut les temporaires sont sous
`%LOCALAPPDATA%\SynthetiseurDeReves\exports_tmp`, hors dépôt/OneDrive. La variable
EXPORT_TEMP_ROOT peut choisir une autre racine absolue privée soumise aux mêmes
gardes P19. Ne pas la faire pointer sur le dossier des médias privés. Le dossier
est dédié aux exports, avec marqueur et sous-dossiers aléatoires export-*.
La recette automatique injecte une racine sous son propre dossier temporaire.

Le flux, le dossier et le verrou sont libérés après téléchargement, erreur ou
déconnexion, même avant le premier bloc. Un arrêt brutal du processus/PC ne
permet pas de promettre une suppression immédiate : les résidus de plus d'une
heure sont repris au prochain export dans la racine dédiée, seulement s'ils
contiennent le fichier attendu, sans lien ni chemin extérieur. Cela ne change
pas la politique de purge des médias P19. L'accès local dépend aussi des droits
du profil Windows ; les administrateurs système restent hors de ce périmètre.

Aucun fichier ZIP n'est accessible par URL publique. Réponses attachment,
no-store et nosniff, nom `reve-<UUID>.zip` ; aucun chemin privé, clé de stockage,
secret ou token dans le nom ou les documents techniques exportés.

## Cohérence et suppression concurrente

Sélection initiale REPEATABLE READ / READ ONLY. Revalidation complète après
construction et avant le premier bloc, avec vérification du propriétaire et
de l'état du rêve. Une suppression pendant la construction annule la livraison.
Le flux revérifie le rêve et la session à chaque bloc ; une révocation ou une
suppression l'interrompt. Des octets déjà livrés ne peuvent pas être rappelés.
Une suppression après les en-têtes peut donc produire un téléchargement avorté,
et non une nouvelle page d'erreur HTTP. Les copies déjà téléchargées restent
sous le contrôle de l'utilisateur.

Les conflits avant envoi produisent un message générique 409 ; les limites 413,
les indisponibilités 503 et le délai de préparation 504. Le formulaire présente
une page d'erreur avec retour au rêve. Aucune modification des routes DELETE,
des jobs IA, du choix émotionnel, ni de la politique de purge.

## Validation reproductible

```powershell
# Recette ciblée : ZIP + P06/P07/P08/P09/P19, base temporaire uniquement.
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --export-only
# Suite complète, couverture et Chrome bureau/mobile :
.\.venv\Scripts\python.exe scripts/verify_p20.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

Ne jamais définir une TEST_DATABASE_URL personnelle. Le lanceur crée et nettoie
son cluster temporaire ; aucune inférence réelle n'est nécessaire. Les tests
ouvrent réellement les ZIP, contrôlent textes, manifeste, octets médias et CRC,
les erreurs, les accès, le CSRF, les limites, la concurrence et le nettoyage.

## Vérification manuelle Chrome (après validation)

Utiliser de préférence une instance et un compte de recette avec récit/médias
fictifs. Les serveurs des recettes automatiques s'arrêtent après les tests.

1. Se connecter, ouvrir Mes rêves, puis un rêve fictif.
2. Cliquer Exporter ce rêve et ouvrir le ZIP téléchargé.
3. Lire recit.txt/reve.json et vérifier manifest.json et les médias attendus.
4. Vérifier qu'aucun autre rêve, nom local ou token n'est présent.
5. Refaire à une largeur mobile de 390 px et vérifier l'accessibilité du bouton.
6. Tester séparément un compte non propriétaire, sans jamais supprimer de rêve
   personnel pour vérifier le comportement.

Le test automatisé Chrome réalise ces téléchargements avec données fictives.
Aucun test manuel sur vos données, export personnel, migration ou worker IA
n'a été exécuté pour cette phase. Le CSS préexistant reste séparé de P10.

## Rapport final de phase 2

Le travail interrompu a été conservé. À la reprise, la dernière campagne déjà
lancée a été récupérée avec succès ; il n'a pas été nécessaire de recommencer
le développement ni de relancer une suite complète identique.

| Contrôle réellement exécuté | Résultat |
|---|---|
| Suite complète finale sur PostgreSQL/HTTPS temporaires | 520 réussis, 1 ignoré en 265,29 s |
| Couverture backend finale | 88,75 % ; minimum requis 80 % |
| Tests spécifiques P10 inclus | 48 : 23 contrat, 24 ZIP/HTTP, 1 parcours Chrome bureau/mobile |
| Dernière campagne ciblée antérieure | 127 réussis en 91,24 s |
| Ruff backend/scripts à la reprise | Réussi |
| Syntaxe de tous les JavaScript publics à la reprise | Réussie |
| Compilation Tailwind 4.3.0 à la reprise | Réussie en 110 ms vers tmp/p10-phase2-tailwind.css |
| git diff --check | Réussi ; avertissements LF/CRLF seulement |
| Ressources de recette restantes | Aucun processus ni dossier temporaire |

Le seul test ignoré est l'inférence émotion réelle opt-in. Aucune inférence
réelle n'a été effectuée. Les résultats précédents de 516 tests / couverture
87,89 % ont été remplacés par la campagne finale après ajout des derniers cas.
La couverture des routes d'export est de 91 %, celle du service ZIP de 89 %.

Les ZIP ont été réellement ouverts et leur CRC contrôlé ; les octets du PNG,
le récit UTF-8 et le manifeste ont été vérifiés. Les tests couvrent : absence
de fichier, altération, isolation entre comptes et entre rêves d'un même compte,
CSRF, Bearer, refus d'accès anonyme/supprimé, export concurrent, suppression
pendant préparation, suppression/révocation avant livraison, interruption avant
le premier bloc, abandon après le premier bloc, expiration du flux, panne disque
simulée, nettoyage et libération du verrou. Un WAV fictif réel d'environ 600 Ko
est refusé avec un budget réduit à 512 Kio ; le dépassement du plafond global
est également testé via les métadonnées, sans écrire inutilement 100 Mio.
Le writer est testé pour refuser un octet au-delà du budget physique.
L'échec de nettoyage simulé conserve un message générique, libère le verrou,
puis son résidu fictif est nettoyé par le test.

La recette confirme aussi P09 après redémarrage PostgreSQL/Uvicorn, la relecture
audio P04 et la lecture/purge contrôlée P19 sur ses seules données fictives.
La comparaison AST avec HEAD confirme inchangés : delete_dream, request_purge,
_finish_purge, reconcile, LocalPrivateStorage.delete et media_maintenance.main.
Les adaptations P19 concernent seulement la distinction d'absence/intégrité,
les délais de lecture stricts et la fermeture du flux après erreur.

### Fichiers de cette phase

Créés :

- backend/app/export_routes.py
- backend/app/services/export_zip.py
- backend/app/web/templates/export_error.html
- backend/tests/test_export_zip.py
- backend/tests/test_export_browser.py
- docs/p10-phase2.md

Modifiés :

- backend/app/main.py : inclusion des routes.
- backend/app/services/exports.py : délais SQL des sélections de phase 1.
- backend/app/services/media.py : mode de lecture strict pour l'export.
- backend/app/storage/local.py : erreur explicite pour un objet absent.
- backend/app/web/templates/dream_detail.html : formulaire d'export.
- scripts/verify_image_jobs.py : ajout des tests ZIP à la recette ciblée.
- scripts/verify_p20.py : racine d'archives exclusivement temporaire pour la recette.

Les autres fichiers non suivis de phase 1 sont conservés. La modification locale
frontend/styles/app.css (767 → 1023 px) n'a pas été touchée et ne fait pas partie
de P10. Aucun remplacement du CSS public compilé, aucune nouvelle dépendance,
aucune migration ou modification de la base personnelle, aucun export de rêve
personnel. L'index Git est vide ; aucun commit, push ou changement Jira.

### Limites restant à connaître

Le nettoyage immédiat n'est pas garanti après un arrêt brutal du PC/processus
ou un refus d'effacement Windows ; les résidus admissibles sont repris lors
d'un export ultérieur après une heure. Les octets déjà téléchargés ne peuvent
pas être révoqués. La phase 3 doit traiter séparément la suppression coordonnée
et sa politique de purge ; elle n'est ni commencée ni nécessaire au téléchargement
déjà testé. La validation manuelle utilisateur de cette phase reste attendue.
