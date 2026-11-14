# P18 / SCRUM-22 — Faisabilité audio US10

**Décision du 14 novembre 2026 : reporter l'implémentation**, conformément au
périmètre retenu. L'étude suffit pour cette option ; la démonstration principale
P16 reste inchangée. Aucun lecteur, fournisseur, modèle ou dépendance n'est ajouté.

## Audit du dépôt : ce qui existe réellement

- FastAPI sert les pages Jinja2 et les médias privés ; le frontend utilise déjà
  `<audio controls preload="metadata">` pour préécouter et relire l'audio du rêve
  (`audio.html`, `audio_ready.html`, `transcript.html`). Aucun `autoplay` n'y figure.
- `audio.js` gère MediaRecorder, import, prévisualisation et nettoyage du lecteur.
  Les lectures dans les tests Chrome sont déclenchées explicitement. Les recettes
  P16 existantes vérifient la relecture : **ce constat ne prouve pas une piste
  d'ambiance ou une TTS**, qui ne sont pas implémentées.
- Aucun usage de `speechSynthesis`, adaptateur TTS ou dépendance Piper n'a été
  trouvé dans le code applicatif et les dépendances déclarées. La valeur `tts`
  acceptée par le modèle SQL `Job` est préparatoire : le contrat P11 `Kind` et
  les admissions de quota ne couvrent que STT, image et émotion.
- Le README relate la préparation ponctuelle d'un WAV fictif avec une voix
  Windows pour P05. Cet essai historique ne livre pas un service TTS US10 et
  n'est pas réexécuté ou présenté comme une validation P18.
- La CSP autorise les médias de même origine et les blobs, pas une piste distante
  arbitraire. Les contenus privés suivent l'authentification, `no-store` et les
  règles de retrait/purge. Une nouvelle sortie TTS devrait s'intégrer à ces règles,
  aux versions du récit, aux budgets et aux exports, sans assouplir la sécurité.

Audit en lecture seule du code et des tests. **Aucune lecture sonore ou synthèse
n'a été exécutée pour P18**, aucun navigateur ou serveur n'a été lancé, et aucune
connexion PostgreSQL n'était nécessaire. Les validations antérieures P16/P17 ne
sont pas revendiquées comme de nouveaux essais P18.

## Comparaison des approches envisagées

Les sources officielles ci-dessous ont été consultées le **14 novembre 2026**.
Ce sont des possibilités documentées, pas des prototypes validés dans ce projet.

| Approche | Intégration et dépendances envisagées | Licence / droits | Coûts et confidentialité | Avis |
| --- | --- | --- | --- | --- |
| Courte piste locale, sans voix | Fichier sélectionné puis servi par FastAPI, lecteur HTML natif ; pas de bibliothèque supplémentaire prévue | Préférer un enregistrement identifié CC0 ; CC BY 4.0 possible avec attribution et obligations vérifiées. Aucune piste précise n'est sélectionnée ou juridiquement validée ici | Estimation : 0 € de frais d'API à la lecture et acquisition à 0 € seulement si l'actif choisi l'autorise. Stockage, électricité et travail non nuls. Aucun récit à transmettre ; éviter tout hébergement/CDN tiers | Premier candidat lors d'une reprise |
| TTS du navigateur / système | Web Speech API, voix française disponible ; pas de paquet Python requis en principe | Les conditions de la voix et du système restent à vérifier ; l'API web ne concède pas les droits de redistribution d'un enregistrement | Pas de facturation API introduite par l'application dans le scénario local envisagé ; disponibilité et licence non garanties. Une voix peut être distante : ne pas supposer que le texte reste sur le poste | Plus légère qu'un moteur embarqué, mais peu reproductible sans qualification du poste |
| TTS locale Piper | Moteur Python/ONNX et voix française qualifiée ; nouveaux fichiers de modèles, tests, limites de ressources et maintenance | Moteur actuel `OHF-Voice/piper1-gpl` : GPL-3.0-or-later ; licences des voix à examiner séparément, modèle par modèle | Estimation : 0 € de frais d'API pour une exécution réellement hors ligne ; RAM/CPU, installation et travail à prévoir. Texte et WAV restent locaux seulement si l'intégration est vérifiée hors ligne | Trop de dépendances et de qualification pour la clôture de démonstration |
| TTS externe, exemple Azure Speech | Adaptateur serveur, secret serveur, réseau, gestion des erreurs et du budget ; aucun appel depuis le navigateur avec une clé | Conditions du service et droits d'utilisation des sorties à examiner pour l'offre exacte ; aucune licence CC supposée | Facturation variable ; texte confié à un tiers, examen contractuel et de la région de traitement requis. Aucun compte, ressource ou appel créé ici | Non retenue pour une démonstration locale à budget externe nul |

Pour le navigateur, le brouillon de spécification décrit `localService`, qui
distingue les services locaux des services distants. Une éventuelle intégration
devrait sélectionner explicitement une voix locale française et **refuser sans
bascule cloud** si elle manque, puis vérifier le fonctionnement sans réseau sur
le poste cible. Aucune liste de voix installées ni garantie de français hors
ligne n'a été vérifiée ici. Il ne faudrait pas déduire de la CSP du site que
la TTS du système est hors ligne. Référence : [Web Speech API](https://webaudio.github.io/web-speech-api/#speechsynthesisvoice).

Pour Piper, la licence du moteur n'est pas une licence globale des voix. La
documentation demande d'examiner le `MODEL_CARD` de chaque voix et sa provenance.
Les obligations de distribution du moteur, des dépendances et des modèles doivent
être étudiées avant un empaquetage ; lancer un processus séparé n'est pas présenté
comme une exemption automatique. Aucun modèle n'a été choisi, téléchargé ou
testé. Références : [licences du projet](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/LICENSING.md)
et [licence du moteur](https://github.com/OHF-Voice/piper1-gpl/blob/main/COPYING).

Pour Azure, la documentation distingue synthèse temps réel et traitements par
lots : elle annonce ne pas conserver le texte et la sortie audio du temps réel,
alors que certains traitements par lots stockent leurs données. Cela ne signifie
pas absence de transmission ni approbation pour des récits personnels. Une offre
exacte, ses contrats et ses traitements devraient être revus avant activation.
Aucune voix clonée ou personnalisée n'est envisagée. Références : [fonctionnement](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech)
et [confidentialité du service](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/speech-service/text-to-speech/data-privacy-security).

## Droits sur une piste : « gratuit » ne suffit pas

Une absence de prix n'autorise pas automatiquement la copie dans le dépôt, la
diffusion pendant une soutenance ou l'inclusion dans une vidéo. Examiner séparément
la composition, l'enregistrement, les interprètes, les éventuels samples et
l'autorisation d'une association à une vidéo. Repères du CPI :
[droits de l'auteur, L122-4](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006278911),
[artistes-interprètes, chapitre L212](https://www.legifrance.gouv.fr/codes/id/LEGISCTA000006161643/)
et [producteurs de phonogrammes, L213-1](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006279050).
Ne pas supposer que le contexte pédagogique ou non commercial règle tous les droits.

- **CC0** : renonciation aux droits couverts dans la mesure permise par le droit
  applicable ; ce n'est pas une garantie sur les droits de tiers, marques ou
  droits à l'image/vie privée. Conserver la provenance même sans attribution
  imposée. [Texte juridique CC0](https://creativecommons.org/publicdomain/zero/1.0/legalcode.fr).
- **CC BY 4.0** : prévoir les crédits, le lien de licence et la mention des
  modifications, notamment pour les copies diffusées. Le périmètre exact de la
  licence et les autres droits restent à vérifier. [Texte juridique CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode.fr).
- Écarter pour une reprise rapide les mentions vagues « free download » ou
  « royalty-free » sans conditions complètes. Une licence NC, ND ou SA appelle
  une analyse de l'usage prévu, des adaptations et de la redistribution ; ne pas
  la déclarer compatible par défaut.

Avant de retenir un fichier : consigner titre, auteur/producteur, URL d'origine,
licence et version, date de vérification, preuve des conditions, attribution et
usages autorisés (application, dépôt, soutenance, vidéo, diffusion en ligne).
**Aucun actif musical n'est actuellement approuvé par cette étude.** Les références
de licence sont vérifiées, pas les droits d'un fichier particulier. Cette analyse
de cadrage ne constitue pas une autorisation juridique d'exploitation.

## Contrôles utilisateur à exiger si l'option est reprise

Lecture explicite, pause/reprise, **arrêt avec retour au début**, volume et muet,
état visible et commandes accessibles au clavier. Pas d'autoplay, de lancement
à l'ouverture d'un rêve ni de son après navigation/déconnexion/suppression. Une
seule source sonore à la fois, indépendante de l'audio enregistré ; pas de mixage
ou de modification du récit/audio d'origine. Tester aussi le volume sur le mobile
cible, où le navigateur peut déléguer certains réglages au système.

Un lecteur natif est un point de départ, pas la preuve que tous ces contrôles
sont déjà livrés. L'arrêt pourrait utiliser pause puis remise à zéro ; une TTS
aurait besoin d'annulation de sa file et de tests pause/reprise. Le texte à lire
devrait être présenté et validé avant synthèse, avec une longueur maximale et
sans cache global partagé entre utilisateurs. Pour un fournisseur payant,
arrêter la lecture ne garantit pas l'annulation d'une synthèse déjà facturée.
Références techniques : [médias HTML](https://html.spec.whatwg.org/multipage/media.html#media-elements)
et [contrôles SpeechSynthesis](https://webaudio.github.io/web-speech-api/).

## Estimations et décision

**Dépense de cette étude : 0 € de services externes.** Seules des pages publiques
de documentation ont été consultées, sans appel de synthèse ni ressource cloud.
Les frais de matériel, d'électricité et de travail ne sont pas mesurés ni déclarés nuls.

Ordres de grandeur de travail **estimés, non mesurés, non contractuels** pour une
reprise ciblée avec recette : piste locale 0,5 à 1,5 jour ; TTS navigateur 1 à 3 jours ;
Piper 2 à 5 jours ; adaptateur externe 2 à 4 jours, hors délai de revue des droits
et de confidentialité. Ces fourchettes devront être réévaluées sur le périmètre exact.

Pour une offre facturée au caractère, exemple **purement arithmétique** : dix
lectures de 1 000 caractères facturables représenteraient 10 000 caractères,
soit `0,01 × P` si `P` est le prix vérifié d'un million de caractères pour l'offre
choisie, hors taxes et frais annexes. Aucun prix régional exploitable n'a été
extrait de la page dynamique consultée ; aucun montant fournisseur ni palier
gratuit garanti n'est donc annoncé. [Tarification officielle Azure Speech](https://azure.microsoft.com/en-us/pricing/details/speech/).
Une éventuelle API devrait rester désactivée avec budget 0 par défaut, puis avoir
un plafond monétaire atomique et un plafond de texte avant tout appel. Le quota
P17 actuel ne couvre pas automatiquement une nouvelle TTS et n'est pas un budget en euros.

**Report motivé :** le bénéfice sonore est secondaire face au parcours P16 déjà
validé. Aucun enregistrement ou modèle n'a ses droits qualifiés, aucune TTS n'est
testée, et une intégration ajouterait des cas d'accessibilité, de consommation,
de confidentialité et de purge. Ne pas introduire ces risques en fin de projet.
Le choix de report satisfait l'option documentaire P18 et ne bloque aucune étape principale.

Si US10 devient prioritaire, commencer par une courte piste locale CC0 dont tous
les droits et usages sont vérifiés. Avant livraison : actif approuvé et notices,
contrôles utilisateur testés sans autoplay, absence de transfert tiers, comportement
en cas d'absence du fichier, test de soutenance et de vidéo, non-régression P16.
Une TTS nécessiterait en plus qualification de la voix, tests hors ligne ou revue
du fournisseur, plafonds, intégration au cycle de vie et absence de contenu sensible
dans les journaux. Ce sont des conditions futures, **pas des fonctionnalités livrées**.

## Vérification documentaire

Livraison limitée à ce document et au lien README. Aucun code de production,
test, dépendance, modèle, média ou configuration n'est modifié. Les liens internes,
la cohérence des constats avec les sources et `git diff --check` ont été contrôlés.
Le lien README résout le fichier créé ; lecture UTF-8 et structure documentaire
vérifiées ; `git diff --check` termine avec le code 0.
Aucun pytest, benchmark, navigateur ou accès base n'est nécessaire à cette étude
et aucun nouveau résultat fonctionnel n'est revendiqué. Les pages de référence
sont datées ci-dessus ; leurs conditions devront être revérifiées lors d'une reprise.
