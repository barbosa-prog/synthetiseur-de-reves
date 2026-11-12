# P09 / SCRUM-13 — Phase 1 : historique PostgreSQL et API

## Périmètre

Service `list_dreams(db, user_id, HistoryQuery)` réutilisable par une future
page HTML, et GET `/api/v1/dreams` avec Bearer obligatoire. Aucune interface,
classification P08, modification d'émotion, jointure obligatoire aux médias,
migration, génération ou modification du comportement P04/P05/P06/P07.

Le propriétaire provient exclusivement de CurrentUser ; le client ne peut
pas fournir user_id. Rêves supprimés logiquement exclus. Brouillons et rêves
sans récit ou sans média inclus. Tri `created_at DESC, id DESC` pour départager
les créations simultanées. Les dates de correction ne changent pas cet ordre.

## Contrat

| Paramètre | Défaut | Limites |
| --- | --- | --- |
| page | 1 | entier de 1 à 10000 |
| page_size | 12 | entier de 1 à 50 |
| emotion | absent : toutes | heureux, stressant, neutre, triste, autre, non_renseignee |

`emotion=non_renseignee` correspond uniquement à `IS NULL`. `neutre` reste
une valeur distincte ; aucun remplacement automatique d'une émotion absente.
Les chaînes "NULL", "null", une émotion vide ou inconnue sont invalides.
Les valeurs non entières, hors bornes et les paramètres inconnus donnent 422.
Une page au-delà de la dernière retourne items=[] et conserve le total.
Un historique vide a total=0 et total_pages=0. Pas de redirection implicite.

Exemples de requêtes, avec Authorization: Bearer fourni dans l'en-tête :

```text
GET /api/v1/dreams
GET /api/v1/dreams?page=2&page_size=12
GET /api/v1/dreams?emotion=neutre
GET /api/v1/dreams?emotion=non_renseignee
```

La réponse contient items, page, page_size, emotion, total, total_pages,
has_next et has_previous. Chaque élément contient id, created_at, status,
emotion, text_version, text_updated_at, has_transcript et un extrait du récit
de 200 caractères maximum (null si aucun récit). Aucun chemin, clé de stockage,
propriétaire tiers, jeton, snapshot IA ou fichier n'est renvoyé.
Les extraits restent des données privées du compte authentifié. Réponses
collection protégées par Cache-Control: no-store et Pragma: no-cache.

## Cohérence et performance

Une seule instruction PostgreSQL combine total et page (CTE + jointure externe)
pour un snapshot cohérent même si la page est vide. Les mêmes prédicats de
propriété/suppression/émotion s'appliquent aux deux CTE. Aucun FOR UPDATE,
lecture/chargement de média, appel IA ou écriture en base dans le service.
L'index propriétaire/date existant est conservé : aucune nouvelle migration
n'est nécessaire. Pas de table d'historique parallèle aux rêves existants.

La pagination par numéro reste sensible aux insertions entre deux requêtes :
le tri est déterministe, mais un nouveau rêve peut décaler une page ultérieure.
Une pagination par curseur pourrait être étudiée si l'usage le justifie.

## Vérifications

Tests unitaires des paramètres/contrats et PostgreSQL réel temporaire pour
deux comptes, rêves supprimés et incomplets, égalités de dates, pagination,
chaque émotion/NULL, reconnexion, accès anonymes, mauvais jetons, révocation,
cookie ne remplaçant pas Bearer et absence de modification des émotions.
Le test de confidentialité vérifie la projection ; le test SQL vérifie une
seule requête d'historique et l'absence de jointure aux médias/verrou de ligne.

L'ancien test P01 qui attendait 404 pour /api/v1/dreams utilise désormais une
route réellement inexistante. La nouvelle route est testée à 401 sans Bearer.
Le middleware ajoute no-store pour la collection exacte, les détails ayant
déjà cette protection. Aucun autre parcours utilisateur n'est modifié.

Commandes Windows :

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_history_rules.py backend/tests/test_api.py -q
.\.venv\Scripts\python.exe -m ruff check backend scripts/verify_p20.py
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --history-only
.\.venv\Scripts\python.exe scripts/verify_p20.py
```

La recette complète crée ses propres PostgreSQL/HTTPS temporaires, utilise
des moteurs fictifs, vérifie aussi l'historique par HTTP avant/après redémarrage
de ces seuls serveurs et les nettoie. Ne pas remplacer son environnement par
la base personnelle. Aucune génération réelle pendant ces tests.

La recette ciblée réutilise le lanceur PostgreSQL existant avec --history-only,
sans changer sa sélection P07 par défaut. Résultat ciblé après correction :
27 tests réussis, aucun ignoré, 4,77 s. La première campagne complète avait
355 succès et 9 échecs P09 dus à une clause ON Python True, remplacée par
l'expression SQLAlchemy true(). Les limites et contrôles n'ont pas été réduits.

Campagne finale complète : **365 tests réussis, aucun ignoré, 204,80 s**,
couverture backend **89,42 %**, service et schémas P09 **100 %**.
La réponse HTTP d'historique est identique avant/après redémarrage effectif
de PostgreSQL/Uvicorn temporaires. Non-régression P03 à P07 et parcours Chrome
existants réussis, ainsi que relecture P04/P19 après redémarrage et purge P19.
Serveurs temporaires arrêtés. Ruff et git diff --check réussis ; seuls
avertissements Git habituels de conversion LF/CRLF sous Windows.
Aucun modèle, émotion existante, migration personnelle ou fichier .env modifié.
Aucune nouvelle migration : tête Alembic 0007 inchangée.

## Avant phase 2

Valider les bornes, le nom de filtre non_renseignee et les métadonnées de page.
La page « Mes rêves », le détail récapitulatif et les liens P06/P07 restent à
développer. Les images courantes devront respecter les versions P07 et être
récupérées sans requête/verrou par carte. P08 reste indépendant : les valeurs
fictives de tests ne constituent pas une classification automatique.
