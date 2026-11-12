# Diagnostic du run abda85e2b698 — Sans nouvelle recette

Le seul journal conservé est report.json : migration 0007, isolation serveur
prouvée et port 5434 exclu, attempts=0, AssertionError, nettoyage et empreintes
personnelles conformes. Aucun traceback ou statut HTTP n'avait été enregistré.

Reproduction ciblée sans DB ni GPU : Credentials refuse les deux adresses
real-owner@example.test et real-other@example.test ; l'API register retourne
422, avec dépendance DB remplacée par un double sans connexion.
Dans le lanceur lu avant correction, scripts/verify_image_real.py ligne 169,
`assert registration.status_code == 201` échoue dès le premier compte fictif.
La ligne 166 définissait ces adresses. Le diagnostic découle de la reproduction
du code et du chemin d'exécution ; le journal ancien seul ne contient pas
la ligne d'échec. Ce n'est pas un échec des migrations, du moteur GPU ou du
service de jobs : le premier compte ne passe pas la validation P03.

Correction limitée au lanceur : utiliser les deux adresses fictives sous
example.com, compatibles avec le validateur existant (aucun email envoyé).
Aucune modification du validateur d'authentification ou règle de sécurité.
Ajout de stages, statuts HTTP register/login et localisation d'exception
(nom de fichier, ligne, fonction) ; aucun corps de réponse, secret ou traceback
avec variables locales n'est enregistré.

Les contrôles URL temporaire, port 5434 interdit, data_directory, rôle/base,
stockage temporaire, environnement enfant et nettoyage sont conservés.
Le rapport du run fournit les preuves d'isolation antérieures à la migration,
temporary_resources_removed=true, new_gpu_staging_removed=true et
personal_files_unchanged=true. Aucun accès à la base personnelle n'a été
effectué pour ce diagnostic. Sans snapshot indépendant de la base personnelle,
on ne prétend pas à une comparaison exhaustive avant/après de son contenu.

Validation ciblée : 21 tests réussis sans PostgreSQL ni GPU, dont reproduction
422 pour les deux anciennes adresses, validation des nouvelles et garde-fous
d'isolation/arrêt. Ruff et git diff --check passent. Aucune recette réelle,
migration, génération, installation, téléchargement, commit, push ou action Jira.
