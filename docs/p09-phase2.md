# P09 — Phase 2 : Mes rêves et détail privé

## Pages livrées

- `/mes-reves` : session P20 obligatoire, 12 rêves par page, tri de la phase 1,
  filtre Toutes/Heureux/Stressant/Neutre/Triste/Autre/Non renseignée.
- `/reves/{id}` : date, état enregistré, émotion et récit courant, liens vers
  P04/P05 si audio disponible, P06 même sans récit, P07 même sans image.
- Navigation « Mes rêves » et accueil actualisé : audio, transcription,
  illustration et historique disponibles ; suggestion émotionnelle P08 à venir.

Le service PostgreSQL de phase 1 est appelé directement. Aucun tri, filtrage,
comptage ou parcours de média par carte n'est réimplémenté. La page ne charge
aucun fichier image pour construire la liste ; les rêves incomplets restent
présents. L'émotion NULL est « Non renseignée », jamais « Neutre ».

Les liens précédent/suivant conservent emotion, y compris non_renseignee.
Le formulaire de filtre remet la page à 1 ; Toutes envoie une chaîne vide,
normalisée à None uniquement dans le contrat HTML. Le contrat API reste inchangé.
Les paramètres inconnus, user_id, pages invalides ou page_size différent de 12
donnent 422. Une page hors résultats propose un retour à la première page,
sans redirection silencieuse. Les dates/heures sont explicitement affichées UTC.

## Images et sécurité

Le détail utilise le contrôle P07 `current_image` : récit et description
aux versions attendues, job terminé, média prêt et non expiré. Aucun ancien
résultat pris simplement parce qu'une image existe. La source HTML est la
route cookie privée P19 `/web/media/{id}/content`, jamais un fichier local.

Un suivi GET toutes les deux secondes, suspendu en onglet masqué, confirme
l'image courante et la masque si la version change. La validité est contrôlée
au rendu serveur puis au prochain suivi, sans garantie de notification instantanée
entre deux requêtes. En cas d'erreur de suivi, l'image est masquée.
Les GET ne lancent ni transcription ni génération. Les traitements restent
des actions explicites sur les pages existantes P05/P07.

Propriétaire obtenu de la session serveur. Même 404 pour rêve absent, supprimé
ou autre compte. Sessions expirées renvoyées vers la connexion. HTTPS strict,
Cache-Control no-store, CSP et mécanismes d'expiration P20 réutilisés.
Échappement Jinja pour récits/extraits, textContent côté JS, aucun token
d'authentification dans le DOM ou stockage navigateur. Le filtre GET n'inclut
pas de secret CSRF (aucune mutation). Émotions existantes jamais modifiées.

## Tests et vérification Windows

```powershell
.\.venv\Scripts\python.exe scripts/verify_image_jobs.py --history-only
.\.venv\Scripts\python.exe scripts/verify_p20.py
.\.venv\Scripts\python.exe -m ruff check backend scripts/verify_p20.py scripts/verify_image_jobs.py
Push-Location frontend
npm run build
Pop-Location
```

La recette ciblée inclut désormais les pages HTML P09 : 46 tests réussis
sur PostgreSQL temporaire, aucun moteur IA. Le client HTML utilise explicitement
HTTPS localhost:8443 ; sa première version HTTP a été corrigée après refus 400,
sans assouplir l'origine stricte. La campagne complète initiale avait 366 succès
et ces 19 échecs de configuration de test, avant correction.
Le délai maximal de la campagne de tests est porté de 300 à 600 s pour le
volume croissant de tests ; aucun délai GPU ou seuil mémoire n'est modifié.

Campagne finale : **385 tests réussis en 225,00 s**, couverture **89,61 %**
(seuil 80 %). Aucun échec ni test ignoré dans cette campagne. L'historique
HTTP est identique après redémarrage réel de PostgreSQL et Uvicorn ; les
contrôles de persistance audio P04 et de lecture/purge privée P19 passent.
Les serveurs temporaires sont arrêtés en fin de recette. Ruff, compilation
Tailwind locale, syntaxe JavaScript et contrôle des espaces Git passent.

Tests HTML : plusieurs comptes, tri à date égale, pages 1/2/3 et hors résultats,
chaque filtre, NULL distinct, filtre conservé, paramètres interdits, XSS échappé,
accès anonymes/intercomptes, détails incomplets/supprimés et invalidation d'image
après changement de récit ou de description. Images issues du faux moteur.
Chrome réel : création du compte, vide initial, navigation depuis l'accueil,
pagination filtrée, détail/P06, consultation PNG synthétique, invalidation en
direct et contrôles mobile/tablette. Le menu se replie sous 1024 px.
Captures dans tmp/p09-screenshots ; aucune image privée réelle dans Git.

## Vérification manuelle dans Chrome

Après validation de cette phase, sur votre serveur HTTPS existant :

1. Se connecter, ouvrir « Mes rêves » dans la navigation ou l'accueil.
2. Vérifier ordre, états, extraits et présence des rêves incomplets.
3. Tester chaque émotion ; Non renseignée doit exclure les rêves Neutres.
4. Si plusieurs pages existent, changer de page et vérifier le filtre conservé.
5. Ouvrir un rêve, vérifier récit et liens P04/P05/P06/P07 disponibles.
6. Si une image existe, modifier explicitement le récit dans un autre onglet :
   elle doit disparaître de l'image actuelle au prochain suivi ou rechargement.
7. Tester une fenêtre étroite, le menu et l'absence de débordement horizontal.

Aucune migration supplémentaire n'est nécessaire : le schéma reste en 0007.
Ne pas lancer les workers IA pour une simple consultation. Les recettes de
cette phase n'utilisent pas la base personnelle et nettoient leurs services.
Pas de détection P08, filtre de date, statistiques ou dashboard supplémentaire.
Aucun commit, push ou changement Jira. Phase 3 soumise à validation utilisateur.
