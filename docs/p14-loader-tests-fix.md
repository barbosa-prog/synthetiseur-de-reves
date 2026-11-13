# P14 — Deuxième échec GitHub : tests de chargeurs simulés

Base publiée : `f93279c`. Le démarrage PostgreSQL est confirmé sur GitHub ; le
correctif ACL n'est pas modifié. Cette correction ne touche aucun moteur de
production, contrôle de version, limite mémoire, garde réseau ou contrôle P14.

## 1. STT : dépendance de test implicite

`stt_provider.main()` effectue les opérations dans cet ordre :

1. Garde mémoire (simulée dans le test).
2. Import de `faster_whisper` (remplacé par un faux module).
3. Import de `backend.app.stt_audio` : ce module importe PyAV **et NumPy**.
4. Appel de `WhisperModel`, remplacé par le faux chargeur instrumenté.

Le venv local contient NumPy 2.5.4, mais `requirements-dev.txt` ne le déclarait
pas. PyAV ne le demande pas dans ses dépendances par défaut ; les dépendances
de développement installées sur un runner neuf ne le garantissent donc pas.
Une erreur d'import du décodeur est masquée par la réponse générique sûre
`provider_failed`. Le faux chargeur n'est jamais appelé : `captured` reste vide.
Cette sortie correspond exactement à l'échec observé.

Correction : ajouter **`numpy==2.5.4` aux dépendances de développement**, sans
installer Whisper ni ses poids. Les tests du décodeur importent maintenant NumPy
normalement : un environnement incomplet échoue clairement à la collecte, au
lieu de passer par `importorskip`. Les assertions du test du chargeur sont
inchangées : un appel au faux chargeur, local uniquement, sortie générique et
aucun marqueur privé.

Un nouveau test reproduit l'import manquant avec un import simulé, sans supprimer
NumPy du PC. Il confirme que le chargeur ne doit pas être appelé dans ce cas et
que l'exception fictive n'est pas exposée.

## 2. Émotion : précondition Python non simulée

Le sous-processus émotion vérifie la version exacte de Python et les versions
des dépendances **avant** l'existence du répertoire du modèle. Les paramètres
qualifiés demandent Python `3.12.14`. Le workflow demande `3.12`, sans fixer le
correctif : une autre version 3.12 peut être choisie par setup-python.

Le test simulait les versions des paquets, mais pas `platform.python_version()`.
Il atteignait donc `model_unavailable` sur le PC en 3.12.14 et s'arrêtait avant
ce contrôle sur un environnement différent, avec `configuration`.
La version exacte du runner n'est pas fournie dans l'extrait utilisateur ; la
précondition et le résultat sont reproduits par simulation sans environnement IA.

Correction : dans le seul test ciblant le modèle absent, simuler aussi la version
Python qualifiée. L'assertion reste `{"error": "model_unavailable"}`. La version
qualifiée n'est pas assouplie dans le code de production et le workflow n'est pas
artificiellement figé sur le correctif du venv IA pour masquer le défaut du test.

Deux nouveaux cas prouvent séparément qu'une mauvaise version Python ou une
dépendance non qualifiée retourne toujours `configuration`, avant toute lecture
du modèle. Les gardes d'import IA et de réseau des tests restent actifs.

## Périmètre de modification

- `requirements-dev.txt` : NumPy explicite, version déjà utilisée localement.
- `backend/tests/test_stt_audio.py` : dépendance obligatoire, plus de skip silencieux.
- `backend/tests/test_p12_final_security.py` : mock Python manquant et trois cas
  de non-régression (import NumPy absent, version Python et dépendance invalides).
- Ce rapport.

Aucun changement de `stt_provider.py`, `emotion_cpu_child.py`, de leur politique
locale, du workflow, de l'authentification ou des bases autorisées. Aucune donnée
personnelle utilisée ; aucun moteur téléchargé ou exécuté.

## Validation

Commande CI conservée :

```powershell
.\.venv\Scripts\python.exe scripts\verify_image_jobs.py --business-coverage
```

La campagne locale utilise `CI=true` dans un processus dédié, le manifeste P14
et un cluster PostgreSQL neuf. Elle ne prouve pas une exécution réussie sur
GitHub. Le prochain commit/push et le prochain run distant restent à effectuer
par le propriétaire ; vérifier ensuite les deux tests et le seuil de couverture.

### R?sultats locaux apr?s correction

- Campagne cibl?e (s?curit? P12, d?codage audio, fournisseur STT), avec
  `CI=true` et environnement nettoy? : **32 tests r?ussis** en 2,39 s.
- Campagne compl?te `--business-coverage`, ?galement avec `CI=true`, cluster
  PostgreSQL temporaire et protections P14 : **903 r?ussis, 15 d?s?lectionn?s**
  en 422,12 s. Les tests navigateur et de qualification r?elle sont hors de
  cette campagne ; aucun moteur IA r?el n'a ?t? ex?cut?.
- Couverture backend combin?e : **89,26 %**.
- P?rim?tre m?tier : instructions **87,02 %**, branches **79,36 %**, combin?e
  **84,82 %** ; seuil combin? de **80 % valid?**.
- Ruff, compilation Python, `pip check` et `git diff --check` : r?ussis.
- Roue `numpy-2.5.4-cp312-cp312-win_amd64.whl` disponible et t?l?charg?e dans
  un r?pertoire jetable, ensuite supprim? ; aucune installation IA.
- CSS ind?pendant pr?serv? (empreinte SHA-256 inchang?e).

Ces v?rifications utilisent le venv local existant, pas une installation neuve
sur Windows Server 2025. Le correctif reste ? confirmer sur GitHub Actions.
