# P17 / SCRUM-21 — Performances et maîtrise des coûts

Campagne du **14 novembre 2026**. **Les durées ci-dessous proviennent d'essais
réellement exécutés avec des fournisseurs simulés. Elles ne mesurent aucune
inférence IA réelle. Dépenses externes de la recette : 0 €.**

## Audit : mécanismes réutilisés et complétés

Les jobs STT et image utilisent déjà PostgreSQL pour la file persistante, les
réservations/baux, les tentatives, la publication et les quotas. P17 réutilise
`Job.queued_at` et `AIExecution.admitted_at` pour la durée avant admission ; aucune
colonne, migration, file ou compteur de consommation parallèle n'est ajouté.
`ai_quota.admit()` renvoie simplement l'heure qu'il calculait déjà.

Les qualifications existantes mesurent certains temps ponctuels : par exemple
`verify_image_real.py` chronomètre un worker, les scripts de qualification image
séparent chargement et inférence, et le bridge émotion collecte durée/mémoire.
Ces mécanismes sont conservés et n'ont pas été exécutés pour P17. Ils ne
fournissaient pas un journal homogène des workers STT/image courants.

Les adaptateurs livrés sont locaux : `LocalWhisper`, `LocalStableDiffusion15` et
le runner émotion CPU. `STT_ENGINE` refuse toute valeur autre que `faster-whisper` ;
la configuration image qualifiée est locale et fixe. Les interfaces Python de
fournisseur sont injectables par du code, mais aucune URL, clé ou sélection de
fournisseur externe payant n'est exposée par la configuration actuelle. Aucun
tarif d'API n'est donc applicable à cette recette ; aucun fournisseur n'a été contacté.

## Points de mesure et signification

| Phase JSON | Point de départ → arrivée | Horloge et périmètre |
| --- | --- | --- |
| `queue` | `queued_at` → admission du quota de la réservation validée | Horloge PostgreSQL ; inclut le temps avant prise en charge et les étapes SQL jusqu'à l'admission, pas seulement une éventuelle attente inactive |
| `provider` STT | Entrée → sortie de `provider.transcribe(content)` | `perf_counter`, monotone ; aucun argument ni résultat journalisé |
| `provider` image | Entrée → sortie de `provider.generate(request)` | `perf_counter` ; validation de l'image et publication sont hors de cette sous-mesure |
| `worker` | Entrée → sortie de `run_once` | `perf_counter` ; recherche/réservation, maintenance préalable, lecture, fournisseur, validations et publication SQL/disque |

La phase fournisseur est **incluse** dans le worker. Le worker démarre avant la
réservation et chevauche donc une partie du temps `queue` : ces durées ne sont
pas des segments indépendants à additionner. Ne pas additionner leurs p95 pour
inventer un p95 de bout en bout. Les temps HTTP, TLS, navigateur, polling et
saisie humaine ne sont pas mesurés par P17.
L'instrumentation et sa destination de logs font partie du contexte d'essai ;
aucune correction théorique de leur surcoût n'est soustraite des observations.

Le délai en file est mesuré avec l'horloge murale du serveur : un recul de cette
horloge peut rendre une différence négative ; une telle différence n'est pas
journalisée. Les mesures fournisseur/worker reposent sur une horloge monotone.

## Campagne réellement effectuée

Référence : [mesures et échantillons bruts](evidence/p17/run-244b771e32f3/measurements.json)
et [180 événements JSON](evidence/p17/run-244b771e32f3/latencies.jsonl), enregistrés
le **14 novembre 2026 à 09:10:25, heure de Paris**.

Environnement : Windows AMD64, Python **3.12.14**, PostgreSQL **17.5**, SQLAlchemy
**2.0.57**, Pillow **12.3.0**, **12 processeurs logiques**, **15,77 Gio de RAM**.
Il s'agit du poste local partagé, sans isolation CPU ni contrôle de sa charge,
pas d'une machine de benchmark dédiée. Aucun GPU ni modèle n'est sollicité.

- **Deux échauffements par type**, puis **30 essais retenus par type**, en ordre
  séquentiel STT puis image. Soit 64 jobs exécutés, dont 60 mesurés ; chaque job
  est vérifié `done`, avec une tentative et un appel fournisseur.
- Entrée STT : **deux secondes de silence synthétique PCM 16 bits, mono, 16 kHz**.
  `FakeProvider` renvoie un texte fictif prédéfini ; il ne reconnaît pas la parole.
- Entrée image : récit et description fictifs. `FakeEngine` crée réellement un
  **PNG violet 512 × 512** avec Pillow ; il n'effectue aucune diffusion.
- Stockage privé, réservations, transactions, validations et publication sont
  réels, dans un nouveau schéma d'une base temporaire autorisée P14.
- Un compte fictif par paire STT/image : **deux admissions par compte**, sous le
  quota central inchangé de 20. Ces sujets d'essai indépendants servent à la
  répétition statistique ; ils ne constituent pas une recommandation de contourner
  le quota d'un compte de démonstration. Ni quota augmenté ni admission effacée.
- Aucune pause artificielle n'est insérée. La préparation des comptes, rêves et
  fichiers d'entrée est hors des chronomètres worker/fournisseur. Chaque mise en
  file est suivie immédiatement de son worker : ce n'est pas un test de charge
  concurrente ni de saturation de file.

### Résultats de référence — millisecondes

| Traitement | Phase | n | p50 mesuré | p95 mesuré | Maximum observé |
| --- | --- | ---: | ---: | ---: | ---: |
| STT simulé | File/admission | 30 | 13,278000 | 16,886750 | 18,020000 |
| STT simulé | Fournisseur seul | 30 | 0,004800 | 0,007620 | 0,008300 |
| STT simulé | Worker complet | 30 | 30,606750 | 34,741400 | 38,211200 |
| Image simulée | File/admission | 30 | 14,491500 | 18,050950 | 60,034000 |
| Image simulée | Fournisseur seul | 30 | 2,028300 | 2,210795 | 2,726800 |
| Image simulée | Worker complet | 30 | 61,807850 | 76,389385 | 110,004800 |

Les valeurs extrêmes restent dans les échantillons ; seules les deux itérations
d'échauffement annoncées sont exclues. La précision affichée du calcul ne garantit
pas une précision physique équivalente. Le STT fictif est presque immédiat :
quelques microsecondes ne permettent aucune conclusion sur Whisper, la durée
audio acceptable ou un facteur de temps réel d'un modèle.

### Méthode statistique

Quantiles empiriques **R7, interpolation linéaire**, implémentés sans NumPy dans
`scripts/performance_stats.py`. Pour les valeurs triées `x[0] ... x[n-1]`, poser
`h = (n - 1) × p`, `i = floor(h)`, `j = ceil(h)`, puis
`Q(p) = x[i] + (x[j] - x[i]) × (h - i)`, avec `p = 0,50` ou `0,95`.
Exemple testé : `[1, 2, 3, 4]` donne p50 = 2,5 et p95 = 3,85.

Les listes vides, valeurs négatives, non numériques, booléens, NaN et infinis
sont refusés ; aucune valeur invalide n'est supprimée silencieusement. Les
statistiques sont calculées sur les durées réellement enregistrées en ms.
Un échec de job ou une mesure manquante fait échouer la campagne, sans produire
un rapport de succès en omettant l'essai. Avec n = 30, le p95 reste une description
empirique de ce petit échantillon, pas un engagement de service ni une estimation
fiable du temps d'un modèle réel.

## Journalisation sans contenu sensible

`backend/app/latency.py` centralise les chronomètres. Le filtre existant
`safe_logging.py` n'autorise pour ces événements que les cinq champs suivants :

```json
{"event":"job_latency","kind":"stt","phase":"worker","duration_ms":35.0114,"outcome":"handled"}
```

`kind`, `phase` et `outcome` appartiennent à des listes fermées ; la durée est
finie, positive ou nulle et bornée à 24 heures. Toute clé supplémentaire ou
valeur non autorisée est remplacée par `diagnostic_redacted`. Aucun audio,
transcription, prompt, modèle de requête, identifiant de compte/rêve/job,
chemin, email, token, exception libre ou secret n'est passé au logger.
La chaîne JSON sort sans préfixe contenant un PID via le formateur sécurisé.

- `queue/admitted` n'est émis qu'après commit de la réservation et de son quota.
- `provider/returned` indique un retour de la méthode ; il ne prouve pas que le
  résultat a ensuite passé les validations ou été publié.
- `provider/raised` et `interrupted` ne contiennent pas le texte de l'exception.
- `worker/handled` signifie qu'un job a été pris en charge, **pas nécessairement
  réussi** : son état métier reste dans PostgreSQL. La campagne le contrôle
  séparément. Un worker sans travail n'émet pas de mesure, pour éviter le bruit.
- Une erreur de destination de logs ne transforme pas le résultat du worker
  et ne rejoue pas une exécution. Les exceptions et interruptions métier restent
  propagées selon le comportement existant.

Les événements sont émis au niveau WARNING pour rester visibles avec la
configuration actuelle des workers, y compris lors d'une réussite ; ce niveau
ne signifie donc pas à lui seul une erreur métier. Le runtime n'ajoute ni fichier
de logs permanent ni endpoint public de métriques. La recette sauvegarde seulement
les 180 événements des essais retenus, soit trois phases × deux types × 30 essais.
La destination/rotation de journaux d'une installation persistante relève de son
exploitant ; la publication CI est limitée à sept jours.

## Limites de consommation et coûts

| Protection existante, conservée | Limite / comportement |
| --- | --- |
| Quota PostgreSQL central | **20 admissions par compte sur 24 heures glissantes**, STT + image + émotion cumulés ; valeur issue de la migration 0010 |
| Admission atomique | Même transaction que `queued → running` ; verrou par compte et politique partagée, isolation READ COMMITTED requise ; dépassement **429** avec `Retry-After`, politique absente/invalide : refus sûr |
| Budget d'un cycle | **Trois exécutions maximum**, dont **deux relances manuelles maximum** ; confirmation explicite, déduplication des entrées, pas de calcul automatique déclenché par GET/polling |
| Job actif | Au plus un job `queued/running` par rêve et type ; conservation des admissions lors d'une suppression pour ne pas réinitialiser le quota |
| Audio | **15 Mio**, **8 minutes** maximum ; mono 16 kHz conservé ; contrôle de format et de taille |
| STT local | Timeout configuré **600 s par défaut**, validé entre **30 et 1800 s** ; garde mémoire de **3072 Mio** et refus si mémoire inconnue ; timeout du processus borné |
| Image locale qualifiée | **512 × 512**, **20 étapes**, timeout de configuration **120 s**, résultat **8 Mio maximum**, filtre de sécurité et verrou GPU ; le superviseur parent dispose d'une marge technique distincte |
| File | Échéance par défaut **1800 s**, vérifiée par les règles/maintenance ; un job en file non admis ne consomme pas une admission |
| Dépense fournisseur externe de cette recette | **0 €**, aucun fournisseur externe implémenté/sélectionné, aucun appel payant, réseau externe interdit dans les tests |

Une admission consommée reste comptée en cas d'échec ; une relance constitue une
nouvelle admission. Le préfiltre de file peut différer un compte épuisé sans
appeler son fournisseur, tandis que les demandes/admissions explicites refusent
le dépassement. Les tests existants de concurrence, rollback, budget partagé,
expiration de fenêtre et suppression/purge sont réexécutés avec la suite complète.
Le nouveau test vérifie aussi qu'un refus 429 n'émet aucune fausse admission.

Le quota est configurable centralement par l'outil administratif existant
`scripts/ai_quota.py`, avec confirmation de base pour une application. P17 ne
modifie pas sa valeur et ne fournit aucune commande visant une base personnelle.
Ce quota est **par compte**, pas un plafond global de capacité de la machine ni
une protection complète contre la création de multiples comptes. Il ne doit pas
être interprété comme un budget monétaire global.

**Hypothèses tarifaires :** aucun prix par token, minute ou image n'est appliqué
car aucun service externe n'est utilisé. Il ne s'agit pas d'une estimation de
gratuité d'une API tierce. Les coûts d'électricité, matériel, stockage local et
éventuelle exécution GitHub ne sont pas mesurés et ne sont pas déclarés nuls.
Le budget externe de démonstration de **0 €** est possible avec cette chaîne
locale/simulée. Si un adaptateur distant est ajouté ultérieurement par du code,
le quota actuel seul ne constituera pas un plafond monétaire : il faudra un
budget explicite (refus par défaut à 0), des réservations atomiques de coût,
des limites par requête et une politique tarifaire validée avant son activation.
Aucun adaptateur ni tarif fictif n'est ajouté pour ce besoin futur.

## Commandes de reproduction et preuves

Depuis la racine, après l'installation P15 du venv et des binaires PostgreSQL 17 :

```powershell
# Facultatif si les binaires ne sont pas au chemin standard :
# $env:P20_POSTGRES_BIN = 'C:\chemin\PostgreSQL\17\bin'
.\.venv\Scripts\python.exe scripts\verify_image_jobs.py --p17-performance
Get-ChildItem -LiteralPath docs/evidence/p17 -Filter measurements.json -Recurse
```

Cette option doit être utilisée seule. Elle crée un cluster PostgreSQL jetable,
sa base `p07_validation`, ses rôles/ports aléatoires, le manifeste d'autorisation
P14 et un schéma migré de test. Elle neutralise le `.env` personnel et les
configurations héritées, refuse les connexions externes et les imports de modèles
réels, puis arrête son PostgreSQL et retire ses ressources temporaires.
Les entrées et résultats métier sont détruits ; seuls `measurements.json` et
`latencies.jsonl` sans contenu subsistent dans un nouveau dossier `run-*`.

Aucun transport HTTP n'est nécessaire à cette mesure interne des workers.
HTTPS, origine, CSRF et cookies de production restent inchangés. La non-régression
P16 utilise uniquement l'exception de certificat de contexte de test P14 déjà
autorisée, sans prétendre valider la confiance TLS.

Avec `CI=true`, les deux rapports vont dans `tmp/p17-performance/run-*`. Le
workflow conserve P14/P15/P16, ajoute une campagne P17 obligatoire et publie
uniquement ces deux noms de fichiers, pendant sept jours et après succès du job.
Il n'impose pas de seuil de latence dépendant de la vitesse du runner. La recette
de mesure est sélectionnée explicitement ; les tests unitaires et d'intégration
P17 font partie de la suite habituelle. Aucun workflow distant n'est déclenché ici.

## Tests et limites de validation

Commandes utilisées :

```powershell
.\.venv\Scripts\python.exe scripts\verify_image_jobs.py --business-coverage
.\.venv\Scripts\python.exe scripts\verify_p20.py --p16-demo
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe -m pip check
```

| Vérification | Résultat réellement observé |
| --- | --- |
| Campagne P17 de référence | **1 passed**, 5,92 s ; 30 échantillons par type/phase après échauffements |
| Campagne P17 avec `CI=true` | **1 passed**, 8,11 s ; emplacement CI exercé, campagne distincte sous charge des autres vérifications |
| Tests latences, confidentialité des logs et contrats CI | **36 passed**, 2,96 s |
| Non-régression P16 continue | **1 passed**, 18,52 s, contrôles historiques de redémarrage et nettoyage du lanceur réussis |
| Suite complète après correction de fixture | **946 passed, 15 deselected**, 426,07 s |
| Couverture métier combinée / backend instrumenté | **84,96 % / 89,44 %** ; seuil métier de 80 % validé |
| Recalcul indépendant des six distributions | p50/p95 concordants avec `statistics.quantiles(..., method="inclusive")` ; 180 événements correspondant exactement aux échantillons publiés |
| Ruff, compilation, `pip check` | Réussis |

La première suite complète a donné **1 failed, 945 passed, 15 deselected** en
456,42 s : le nouveau test de quota essayait une image sur une ancienne version
du récit après STT, ce qui déclenchait légitimement un conflit 409 avant le quota.
Sa fixture utilise désormais une entrée image nouvelle et valide ; l'assertion
429 est conservée. Aucun comportement de production ni contrôle de version n'a
été affaibli pour corriger ce test. La suite finale ci-dessus passe après correction,
sans échec ni test ignoré. Les 15 désélections sont les navigateurs et la
qualification IA hors de cette campagne ; le scénario P16 est exécuté séparément.

Les tests P17 couvrent les quantiles connus, les données invalides, le filtrage
des champs/valeurs de logs, l'absence de contenu d'exception, les interruptions,
la panne de destination de logs, l'absence de bruit sans travail, les résultats
succès/échec des deux fournisseurs, le refus du moteur STT externe et le refus
de quota sans fausse mesure d'admission.

Non mesurés : modèles réels, téléchargement/chargement des poids, GPU, audio
parlé, qualité STT/image, latence utilisateur ou HTTP, saturation, charge
concurrente et seconde machine. Aucune estimation de ces performances n'est
substituée aux mesures manquantes. Les chiffres ne sont pas transposables à
une vraie inférence ni à une API payante. Aucun secret, base personnelle, Jira,
commit ou push n'a été utilisé/modifié par cette recette.
