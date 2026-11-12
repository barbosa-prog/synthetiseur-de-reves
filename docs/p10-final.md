# P10 — SCRUM-14 : recette finale et préparation du commit

## Verdict soumis à validation

Les trois critères fournis pour SCRUM-14 et le complément de purge sont couverts
par les essais exécutés. Aucune anomalie bloquante détectée dans ces scénarios.
P10 est prêt pour la validation utilisateur et le commit proposé ci-dessous,
avec les limites explicites de sauvegarde, legacy et téléchargement déjà reçu.
Cela ne constitue ni une clôture Jira ni une autorisation de maintenance personnelle.

Base Git contrôlée : main, commit 424c391. Aucun git add, commit, push ou changement
Jira. Aucun accès à dreams_local ou aux médias personnels, aucune migration
personnelle, aucun volume Docker modifié et aucun worker IA réel démarré.

## Critères d'acceptation

| Exigence | Preuve exécutée | Conclusion |
|---|---|---|
| Suppression inaccessible à un autre compte | API Bearer et formulaire session/CSRF valide : 404, rêve témoin conservé | Validé |
| Export lisible | ZIP téléchargé dans Chrome, CRC, TXT UTF-8, JSON et manifeste relus | Validé |
| Médias associés pris en compte | WAV et PNG fictifs, octets et SHA-256 contrôlés ; disponibilité explicite | Validé |
| Retrait immédiat des liens | Historique, pages, anciens médias et export refusés après suppression | Validé |
| Purge programmée et documentée | États deleting, inventaire puis application explicite, reprise et idempotence | Validé pour les médias gérés ; legacy bloqué prudemment |

## Recette intégrée réellement exécutée

La nouvelle option --p10-final du lanceur existant crée une base PostgreSQL
fraîche p20_validation, un rôle aléatoire, un stockage privé et un serveur HTTPS
temporaires. La recette exige une base vide, un port différent de 5434 et une
racine de médias située sous ce dossier de recette. Elle ne peut pas s'appuyer
sur les six rêves personnels. Son fichier n'est pas collecté par défaut : la
recette fraîche doit être appelée explicitement, indépendamment de la suite.

Deux comptes fictifs sont créés, avec un rêve cible et deux rêves témoins,
un par compte. Le cible contient récit version 1, audio WAV, image PNG, description
visuelle P07, émotion Heureux acceptée explicitement et instantanés P07/P08.
Le PNG et la suggestion sont produits par les fournisseurs déterministes des
tests, sans moteur IA réel ni GPU. Les rêves témoins possèdent leurs médias et jobs.

Parcours vérifié :

1. Connexion des deux comptes dans des contextes Chrome séparés.
2. Téléchargement sur ordinateur (1280 × 960) puis mobile (390 × 844).
   Le ZIP contient exactement README.txt, recit.txt, reve.json, manifest.json,
   medias/ et deux médias. Les fichiers s'ouvrent, leur CRC et leurs empreintes
   correspondent, le récit et l'émotion/provenance sont cohérents.
3. Contrôle des quatre documents : ni jeton, e-mail, UUID utilisateur, clé de
   stockage, chemin privé ni donnée des rêves témoins. Les médias correspondent
   exactement aux fichiers du rêve cible.
4. Refus de l'export et de la suppression du cible par l'autre compte : Bearer
   et formulaire web avec CSRF valide. Refus du CSRF incorrect pour les deux
   opérations. Le cookie seul ne permet pas d'utiliser l'API Bearer.
5. Création/réservation de trois nouveaux jobs STT/image/émotion, sans calcul.
   Annulation de la confirmation : le rêve reste. Case non cochée : aucun retrait.
   Confirmation explicite sur mobile : retrait de l'historique et trois jobs
   invalidés, sans ancien token utilisable. Résultats tardifs refusés.
6. Pages, médias et export devenus inaccessibles avant la purge physique.
7. Exécution réelle du CLI dream_maintenance en mode inventaire : un rêve éligible.
8. Interruption simulée après un unlink réel, avant confirmation SQL. Le rêve
   reste deleted et ses médias deleting. Aucune fausse purge réussie.
9. Exécution du CLI --apply avec confirmation de la base temporaire : reprise et
   purge terminées. Deuxième exécution : aucun rêve supplémentaire à purger.
10. Vérification SQL des données et instantanés disparus, fichiers absents,
    autres rêves/médias/jobs intacts, utilisateurs et sessions inchangés.

Les assertions de la recette produisent seulement quatre indicateurs dans
tmp/p10-final-recipe.json, ignoré par Git. Aucun ZIP n'est conservé dans le dépôt.

## Résultats mesurés pendant la phase 5

| Commande / contrôle | Résultat |
|---|---|
| verify_p20.py --p10-final, première exécution | 1 réussi en 10,00 s |
| Recette renforcée : contrôles web intercomptes/CSRF et tous documents | 1 réussi en 9,93 s |
| verify_p20.py, suite complète réexécutée | 572 réussis, 1 ignoré en 330,43 s |
| Couverture backend | 89,07 % ; seuil requis 80 % |
| Service dream_purge | 93 % |
| Ruff backend/scripts | Réussi |
| node --check sur tous les JavaScript publics | Réussi |
| Tailwind 4.3.0, sortie temporaire | Réussi en 131 ms |
| git diff --check | Réussi ; avertissements LF/CRLF seulement |

La recette dédiée est exécutée séparément, pas ajoutée artificiellement aux 572
tests de la suite courante. L'unique ignoré est l'inférence émotion réelle opt-in.
Les campagnes utilisent exclusivement PostgreSQL et médias temporaires. Les
recettes confirment aussi P09 après redémarrage PostgreSQL/Uvicorn, la lecture
audio P04 et les lectures/purges fictives P19, puis arrêtent leurs services.

Les tests des phases précédentes, réexécutés dans la suite, couvrent notamment :
fichier manquant signalé dans le manifeste, fichier altéré refusé à l'export,
limites de taille/nombre/concurrence, arrêt du téléchargement, nettoyage ZIP,
rollback de suppression, baux expirés, retours tardifs STT/image/émotion,
permission disque refusée, absence initiale, faux succès d'un unlink, reprises
après coupure/échec de commit, références croisées et médias legacy dangereux.

## Sécurité, limites et risques résiduels

- Authentification serveur et propriétaire imposé ; aucun user_id de formulaire
  ne décide du compte. Les mutations web utilisent le CSRF existant et HTTPS.
- Aucun lien public permanent, aucun fichier privé sous static. Noms d'archive
  générés côté serveur, refus des chemins arbitraires, liens et objets dangereux.
- Un rêve par export, 100 médias/100 Mio maximum, espace disque et délais bornés,
  un seul export simultané par base. Limites complètes dans p10-phase2.md.
- Une suppression conflictuelle n'est pas présentée comme réussie : 409 et
  rollback complet. Les fichiers ne sont effacés qu'en maintenance explicite.
- La transaction SQL et le système de fichiers ne sont pas atomiques ensemble :
  la reprise est précisément prévue et testée. Un disque inaccessible reste un
  blocage, jamais une confirmation d'absence.
- Les données legacy ou croisées restent inaccessibles mais non purgées tant
  qu'une résolution sûre et autorisée n'a pas été réalisée.
- Le PC arrêté, un refus Windows sur fichier ouvert ou une maintenance non
  exécutée empêchent de garantir un délai calendaire de purge.
- Les octets déjà téléchargés et les copies conservées par l'utilisateur ne
  sont pas révocables. Un calcul déjà lancé peut finir en mémoire sans publication.
- Les sauvegardes/WAL ne sont pas effacés. Une restauration ancienne peut
  réintroduire des données ; isolement et revue des suppressions sont nécessaires.
  La politique détaillée et ses limites sont dans p10-phase4.md.
- La suite ne prétend pas tester un crash matériel réel, un effacement forensic
  ou toutes les variantes de système de fichiers. Les interruptions simulées
  couvrent les frontières pertinentes entre unlink, flush et commit.

Aucune correction du code de production n'a été nécessaire pendant cette phase.
Les ajouts portent sur la recette dédiée, son option de lancement et ce rapport.

## Revue Git et fichiers proposés

33 fichiers P10 à inclure, listés exactement ci-dessous. La modification locale
frontend/styles/app.css (767 → 1023 px) est vérifiée intacte et EXCLUE. Aucun
remplacement du CSS public compilé. Aucun changement de .gitignore, dépendance,
modèle SQL ou migration requis pour P10.

Le scan des candidats ne détecte aucun ZIP, média, modèle, environnement virtuel,
sauvegarde ou secret réel. Un motif de connexion a été inspecté dans
test_dream_purge.py : fiction:fiction, base fiction, moteur de connexion mocké
avec assertion de non-appel. Ce jeu négatif ne contient pas de véritable secret
et n'ouvre pas le port personnel. Les chemins négatifs de tests sont fictifs.
Les chemins système Chrome/PostgreSQL ne sont pas des chemins de données privées.
.env, .venv, tmp et les reçus/compilations temporaires sont ignorés par Git.
Ce scan n'est pas une garantie absolue : la liste explicite reste à approuver.

### Fichiers suivis modifiés — 11

```text
backend/app/dream_routes.py
backend/app/main.py
backend/app/media_routes.py
backend/app/services/emotions.py
backend/app/services/image_execution.py
backend/app/services/media.py
backend/app/services/stt_jobs.py
backend/app/storage/local.py
backend/app/web/templates/dream_detail.html
scripts/verify_image_jobs.py
scripts/verify_p20.py
```

### Nouveaux fichiers non suivis — 22

```text
backend/app/deletion_routes.py
backend/app/export_contract.py
backend/app/export_routes.py
backend/app/services/dream_deletion.py
backend/app/services/dream_purge.py
backend/app/services/export_zip.py
backend/app/services/exports.py
backend/app/web/templates/delete_dream.html
backend/app/web/templates/export_error.html
backend/tests/p10_final_recipe.py
backend/tests/test_deletion_browser.py
backend/tests/test_dream_deletion.py
backend/tests/test_dream_purge.py
backend/tests/test_export_browser.py
backend/tests/test_export_zip.py
backend/tests/test_exports.py
docs/p10-phase1.md
docs/p10-phase2.md
docs/p10-phase3.md
docs/p10-phase4.md
docs/p10-final.md
scripts/dream_maintenance.py
```

### Reproduction autorisée sur données fictives

```powershell
.\.venv\Scripts\python.exe scripts/verify_p20.py --p10-final
.\.venv\Scripts\python.exe scripts/verify_p20.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
```

La recette crée et nettoie son infrastructure ; ses URL temporaires ne restent
pas ouvertes après le test. Aucun démarrage ni maintenance de l'instance
personnelle n'est autorisé par ce rapport.

Message de commit proposé :

```text
feat(p10): exporter et supprimer les reves avec purge reprenable
```

Recommandation : valider ce bilan et le périmètre Git explicite, puis seulement
autoriser l'ajout/commit. La clôture SCRUM-14 reste une action séparée soumise
à votre accord. Aucun ticket n'a été modifié et aucun commit n'a été effectué.
