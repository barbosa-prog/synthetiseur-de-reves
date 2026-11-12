# P08 — Validation technique finale (12 novembre 2026)

## Critères SCRUM-12

Le contrat et l'interface autorisent heureux, stressant, neutre, triste, autre.
Le parcours réel Chrome a été validé par l'utilisateur : suggestion Heureux,
choix inchangé avant acceptation, acceptation explicite, correction Triste,
filtre P09, retrait, abstention et choix conservé après désactivation/redémarrage.
La correction manuelle et le retrait restent disponibles sans moteur IA.
L'avertissement permanent est : « Cette suggestion automatique est indicative
et peut être incorrecte. Elle ne constitue ni un diagnostic ni un avis médical.
Vous pouvez la modifier. »

Les trois fonctionnalités sont présentes. La fiabilité sur les cinq classes
n'est pas démontrée : le périmètre accepté est une aide facultative expérimentale,
sans attribution automatique. La clôture doit conserver explicitement cette réserve.

## Résultats exécutés pendant cette validation

- Suite complète `python scripts/verify_p20.py` : 472 réussis, 1 ignoré,
  263,14 s ; couverture backend 88,74 % pour un seuil de 80 %.
  Seul ignoré : test réel opt-in, conformément à l'interdiction de nouvelle inférence.
- Chrome avec faux moteur : `python scripts/verify_p20.py --browser-only
  --emotion-web-test` : 7 réussis en 52,79 s ; bureau et mobile, sans modèle.
- Qualification unitaire `python -m pytest qualification/p08 -q
  -p no:cacheprovider --basetemp tmp/p08-final-unit` : 13 réussis en 0,09 s.
- Ruff `python -m ruff check backend scripts qualification/p08` : réussi.
- Syntaxe `node --check` sur tous les JavaScript publics : réussie.
- Tailwind 4.3.0 : compilation locale réussie en 192 ms vers
  tmp/p08-final-tailwind.css ; aucun remplacement du CSS public.
- `git diff --check` : réussi ; avertissements LF/CRLF seulement.

Le premier essai Node était bloqué par les permissions du bac à sable (EPERM).
La vérification autorisée hors de cette restriction réussit sans installation.
Les deux recettes PostgreSQL/HTTPS ont arrêté leurs services et supprimé leurs
dossiers temporaires. Aucun processus temporaire ou worker émotion ne subsiste.
Les recettes confirment aussi la persistance P09 et la lecture audio P04/P19
après redémarrage réel des services temporaires, puis la purge contrôlée P19.

## Sécurité, compatibilité et état personnel

Tests réussis : authentification, isolation intercomptes, CSRF, échappement HTML,
versions P06, résultats périmés, baux, jetons de réservation, concurrence,
annulation, acceptation, retrait et absence d'UPDATE dreams depuis le worker.
Compatibilité P06/P07/P09/P19/P20 couverte par la suite complète.
La publication utilise update_choice=False ; une abstention ou une panne ne
modifie jamais dreams.emotion. Toute attribution est explicitement acceptée
ou saisie manuellement. Un résultat tardif ne remplace pas un choix explicite.

Contrôle personnel uniquement READ ONLY : dreams_local, 127.0.0.1:5434,
révision 0008, zéro job émotion actif. Configuration contrôlée désactivée ;
l'utilisateur a confirmé le redémarrage personnel avec EMOTION_ENABLED=0.
Valeur par défaut 0 ; le worker exige une activation et DATABASE_URL explicites.
Aucune migration personnelle ni modification de donnée pendant cette validation.

## Limites documentées

La référence mDeBERTa 2B avait macro-F1 0,606 et exactitude 60 %, mais rappel
autre nul et suggestions injustifiées. La politique prudente 2C couvre seulement
18 % des exemples explicites : macro-F1 0,277, rappel neutre/autre nul.
Neuf suggestions correctes observées ne garantissent aucune précision future.
Les abstentions ne sont jamais comptées comme des classifications correctes.
Corpus fictifs limités ; aucune portée médicale. Le moteur reste expérimental,
facultatif, désactivé par défaut et soumis à confirmation humaine.

Couvertures spécifiques : emotion_runner 39 %, emotion_worker 49 % ; certains
chemins système réels ne sont pas exercés par cette campagne sans modèle.
Les essais réels antérieurs sont des preuves distinctes, non relancées ici.
Le downgrade 0008 refuse les nouvelles données P08 : ce n'est pas une méthode
de retour arrière après utilisation. Conserver la sauvegarde vérifiée.

## Git et liste exacte proposée

Aucun ajout à l'index, commit, push ou changement Jira.
La modification préexistante frontend/styles/app.css (767 → 1023 px) est
préservée et exclue de P08. Le CSS public compilé est inchangé.
Le contrôle des candidats ne détecte aucun modèle, venv, média, sauvegarde,
secret ou temporaire. Les JSON de qualification contiennent des mesures et
résultats sur récits fictifs ; ils servent à la traçabilité. Le scan de motifs
ne constitue pas une garantie absolue d'absence de secrets.
.env, .venv et tmp sont ignorés ; modèles et sauvegardes restent hors dépôt.

Fichiers proposés pour P08 (aucun ajout exécuté) :

- `backend/app/auth_schemas.py`
- `backend/app/dream_routes.py`
- `backend/app/emotion_config.py`
- `backend/app/emotion_provider.py`
- `backend/app/emotion_routes.py`
- `backend/app/emotion_rules.py`
- `backend/app/emotion_runner.py`
- `backend/app/emotion_web.py`
- `backend/app/emotion_worker.py`
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/services/emotions.py`
- `backend/app/services/transcripts.py`
- `backend/app/web/static/js/emotion.js`
- `backend/app/web/templates/dream_detail.html`
- `backend/app/web/templates/emotion.html`
- `backend/migrations/versions/0008_emotion_suggestions.py`
- `backend/tests/test_emotion_bridge.py`
- `backend/tests/test_emotion_browser.py`
- `backend/tests/test_emotion_contract.py`
- `backend/tests/test_emotion_postgresql.py`
- `backend/tests/test_emotion_real.py`
- `backend/tests/test_emotion_web.py`
- `backend/tests/test_emotion_worker.py`
- `backend/tests/test_image_jobs.py`
- `backend/tests/test_postgresql.py`
- `docs/p08-final.md`
- `docs/p08-phase1.md`
- `docs/p08-phase2.md`
- `docs/p08-phase2b.md`
- `docs/p08-phase2c.md`
- `docs/p08-phase3.md`
- `docs/p08-phase4.md`
- `docs/p08-phase5.md`
- `qualification/p08/compare_b.py`
- `qualification/p08/confirmation.py`
- `qualification/p08/dataset.py`
- `qualification/p08/download.py`
- `qualification/p08/download_b.py`
- `qualification/p08/evaluate.py`
- `qualification/p08/memory-b-deberta.json`
- `qualification/p08/memory-b-minilm.json`
- `qualification/p08/memory-c-dev.json`
- `qualification/p08/memory-c-test.json`
- `qualification/p08/memory.json`
- `qualification/p08/protocol-c-before-test.json`
- `qualification/p08/reliability.py`
- `qualification/p08/reliability_data.py`
- `qualification/p08/reliability_protocol.json`
- `qualification/p08/report_b.py`
- `qualification/p08/report_c.py`
- `qualification/p08/requirements-lock.txt`
- `qualification/p08/requirements.txt`
- `qualification/p08/results-b-deberta.json`
- `qualification/p08/results-b-minilm.json`
- `qualification/p08/results-c-dev.json`
- `qualification/p08/results-c-test.json`
- `qualification/p08/results.json`
- `qualification/p08/test_comparison.py`
- `qualification/p08/test_protocol.py`
- `qualification/p08/test_reliability.py`
- `qualification/p08/watch.py`
- `qualification/p08/watch_b.py`
- `qualification/p08/watch_c.py`
- `scripts/emotion_cpu_bridge.py`
- `scripts/emotion_cpu_child.py`
- `scripts/verify_image_jobs.py`
- `scripts/verify_p20.py`
