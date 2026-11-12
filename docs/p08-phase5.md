# P08 — Phase 5 : interface de suggestion et de choix explicite

## Livraison

Page privée /reves/{id}/emotion, accessible par le lien Émotion dans le détail
P09. Elle présente le récit actuel et sa version, l'émotion retenue et son
origine (manuel, suggestion acceptée, valeur historique inconnue, retrait ou
absence de choix), puis la suggestion expérimentale séparément.

La correction et le retrait sont toujours disponibles, y compris sans récit
ou moteur. Une suggestion nécessite un clic explicite ; aucune consultation,
actualisation ou correction P06 ne crée un job. Une abstention n'est jamais
convertie en neutre/autre et son bouton d'acceptation reste désactivé.
Le sélecteur manuel n'est jamais rempli automatiquement par une suggestion.
Les erreurs ne modifient pas la valeur retenue.

Avertissement présent sur toutes les pages et réponses d'erreur HTML :

> Cette suggestion automatique est indicative et peut être incorrecte. Elle ne constitue ni un diagnostic ni un avis médical. Vous pouvez la modifier.

Le moteur est explicitement présenté comme expérimental et potentiellement
inexact. La page n'attribue aucune confiance médicale aux résultats. Cette
livraison ne modifie pas les limites de qualité constatées en phase 2C.

## Routes et services

| Méthode | Route | Effet |
|---|---|---|
| GET | /reves/{id}/emotion | Rendu HTML protégé |
| GET | /reves/{id}/emotion/statut | Suivi sans lancement d'IA |
| POST | /reves/{id}/emotion/suggerer | Demande explicite, moteur disponible requis |
| POST | /reves/{id}/emotion/choisir | Choix manuel parmi les cinq catégories |
| POST | /reves/{id}/emotion/accepter | Acceptation d'une suggestion courante non abstention |
| POST | /reves/{id}/emotion/retirer | Retrait explicite, NULL protégé |

La couche web appelle les services PostgreSQL P08 communs aux API Bearer.
Les routes API existantes ne deviennent pas des routes cookies et aucun
Bearer n'est exposé à JavaScript. Les formulaires utilisent BrowserSession,
editor_form et les protections CSRF P20 : origine HTTPS stricte, cookie secret
HttpOnly et preuve liée à la session, champs bornés, doublons/inconnus refusés.
Même 404 pour rêve absent, supprimé ou appartenant à un autre utilisateur ;
session absente/expirée redirigée vers la connexion. Aucun user_id accepté.
Toutes ces routes bénéficient de Cache-Control no-store/CSP existants.

Les mutations portent un jeton métier version_du_récit:révision_du_choix
(pas un jeton d'authentification), vérifié sous verrou du rêve. Cela couvre
aussi le premier formulaire ouvert avant qu'une métadonnée émotion ne soit
encore persistée : une correction P06 entre lecture et envoi est refusée.
Les UUID de suggestion restent vérifiés par le service, jamais considérés
comme une autorisation. Aucune configuration privée ni chemin n'est retourné.
Les récits sont échappés par Jinja et les mises à jour utilisent textContent.

## Suivi et conflits

En attente, en cours, terminé, abstention, erreur, résultat dépassé et aucune
demande ont des messages distincts. Une demande reste en attente si le worker
est arrêté ; FastAPI ne le démarre jamais. Le bouton de demande est bloqué
si moteur désactivé, récit absent ou job actif incompatible ; le serveur
revérifie toujours ces conditions.

Le GET de suivi est fait toutes les deux secondes lorsque l'onglet est visible.
La publication normale du job affiché peut avancer la révision d'une unité
et rendre l'acceptation disponible sans rechargement. Une révision concurrente
inattendue ou une correction du récit masque la suggestion, bloque les anciens
formulaires et invite à recharger. Une panne du suivi masque également la
suggestion, au lieu de la laisser présentée comme actuelle.
Ce mécanisme n'est pas une notification instantanée entre deux requêtes ;
la garde transactionnelle serveur refuse encore un envoi avant le prochain poll.
Le choix en cours dans le sélecteur manuel n'est pas remplacé par le polling.

La valeur conservée peut être liée à une ancienne version du récit : c'est
indiqué sans la supprimer. Une suggestion, elle, n'est affichée que si les
contrôles P08 de version/propriétaire la confirment toujours actuelle.
P09 continue de filtrer dreams.emotion exclusivement : choisir/accepter le
modifie, retirer donne non_renseignee, suggérer seul ne change aucun filtre.

## Fichiers de cette phase

Créés : backend/app/emotion_web.py ; web/templates/emotion.html ;
web/static/js/emotion.js ; tests/test_emotion_web.py ;
tests/test_emotion_browser.py ; docs/p08-phase5.md.

Modifiés : backend/app/main.py (routeur),
backend/app/web/templates/dream_detail.html (lien),
scripts/verify_image_jobs.py (sélection des tests HTML ciblés),
scripts/verify_p20.py (option de disponibilité simulée en recette).
Les fichiers P08 des phases antérieures restent présents dans git status ;
ils ne sont pas tous nouveaux dans cette phase. Aucun changement dans les
modèles, migrations, services IA, workers ou dépendances de cette phase.
Le CSS source local préexistant est préservé ; les classes Tailwind existantes
suffisent. La compilation locale ne produit ici aucun nouveau diff CSS.

## Tests réels de cette phase (sans IA réelle)

Commandes Windows depuis la racine :

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --emotion-only
.\.venv\Scripts\python.exe scripts/verify_p20.py --emotion-web-test
# Chrome en mode désactivé, toujours sur une autre base jetable :
.\.venv\Scripts\python.exe scripts/verify_p20.py --browser-only
.\.venv\Scripts\python.exe -m ruff check backend scripts
Push-Location frontend
npm run build
node --check ../backend/app/web/static/js/emotion.js
Pop-Location
```

--emotion-web-test rend le seul serveur de recette temporaire disponible
pour les clics de suggestion. Aucun worker CPU, mDeBERTa, Whisper ou Stable
Diffusion n'est démarré : les tests réservent et terminent les jobs avec le
faux fournisseur déterministe. Les variables ne modifient ni .env ni le
serveur personnel. Le test réel opt-in demeure ignoré dans cette campagne.

Les tests couvrent plusieurs comptes, anonymat, CSRF manquant/incorrect,
origines, saisie/retrait/acceptation, moteur désactivé, rêves incomplets et
historiques, XSS, avertissement exact, états/erreurs/abstention, concurrence,
correction du récit, ancien formulaire, lien P09 et filtre NULL distinct.
Le parcours Chrome reproduit demande/état running/résultat/acceptation/retrait/
abstention/invalidation avec des données fictives. Vue desktop et largeur
390 px sans débordement ; captures dans tmp/p08-web-screenshots, ignorées Git.

Première campagne ciblée : quatre échecs du helper de test CSRF, qui cherchait
une révision émotionnelle sur l'accueil ; corrigé sans changer la sécurité.
Campagne ciblée après contrôle récit/choix : 102 réussis en 34,03 s.
Campagne complète finale : **472 réussis, 1 ignoré en 273,08 s**, couverture
backend **88,74 %**, supérieure au seuil de 80 %. Le seul ignoré est le test
réel opt-in : aucune inférence réelle n'a été lancée pendant cette phase.
La première campagne complète intermédiaire passait déjà 471 tests avant le
dernier cas d'ancien formulaire sur un rêve sans métadonnée persistée.

Recette Chrome supplémentaire, moteur désactivé : **7 tests navigateur
réussis en 44,63 s** (466 autres tests désélectionnés volontairement).
Historique P09 identique après redémarrage effectif des PostgreSQL/Uvicorn
temporaires ; audio P04 et média P19 relus après redémarrage, purge P19 vérifiée.
Les services temporaires sont arrêtés. Ruff, compilation Tailwind locale,
syntaxe JavaScript et git diff --check passent ; avertissements Git LF/CRLF seuls.

## Validation manuelle Chrome et migration personnelle

Ne pas utiliser cette version P08 sur votre base personnelle restée en 0007.
Aucune migration personnelle n'a été appliquée. Le parcours a été vérifié
automatiquement dans Chrome sur PostgreSQL jetable ; une vérification manuelle
doit utiliser une instance de recette explicitement isolée, ou attendre une
autorisation de migration personnelle distincte. Les lanceurs de tests ferment
leurs serveurs en fin de recette ; leurs URL ne restent pas disponibles.

Sur l'instance autorisée au schéma 0008 :

1. Se connecter avec un compte de recette ; Mes rêves → ouvrir un rêve → Émotion.
2. Vérifier récit/version, avertissement exact et séparation des deux valeurs.
3. Moteur désactivé : choisir Triste puis enregistrer ; vérifier l'origine
   Choix manuel et le filtre Triste dans Mes rêves.
4. Retirer le choix ; vérifier Non renseignée et le filtre correspondant.
5. Sur une recette à fournisseur simulé explicitement disponible : demander
   une suggestion, suivre les états, vérifier que le choix ne change pas,
   puis accepter explicitement. Tester aussi une abstention non acceptable.
6. Modifier le récit dans un autre onglet ; la suggestion doit disparaître au
   suivi et un ancien formulaire doit être refusé. Le choix explicite est conservé.
7. Tester un autre compte et une largeur mobile ; aucun rêve étranger accessible.

Avant d'autoriser la migration personnelle :

- Valider cette phase et les recettes temporaires, le caractère expérimental
  et la politique sans attribution automatique.
- Confirmer séparément la révision personnelle actuelle (attendue 0007),
  préparer une sauvegarde PostgreSQL protégée et une procédure de restauration.
- Relire 0008 et ses contrôles de préservation legacy/NULL ; son downgrade
  refuse les données P08 nouvelles, il ne remplace pas une sauvegarde.
- Vérifier la configuration du futur serveur/worker et garder EMOTION_ENABLED
  désactivé pour la première vérification manuelle. Le choix manuel n'a besoin
  d'aucun modèle ; tout essai réel ultérieur exige une autorisation explicite.
- Demander l'accord de migration : aucune commande upgrade personnelle exécutée
  et aucun accès à la base personnelle effectué dans cette phase.

Limites : l'interface ne résout pas les défauts de qualité du moteur ; les
demandes attendent un worker absent et l'annulation reste accessible par l'API
P08 existante, sans nouveau bouton d'annulation dans cette livraison.
Aucun commit, push ou changement Jira. Phase 6 soumise à validation.
