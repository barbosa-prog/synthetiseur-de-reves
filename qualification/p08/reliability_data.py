"""P08 2C : corpus fictifs distincts, figés avant toute inférence.

Dev : seuls dix cas dev initiaux + nouveaux cas dédiés. Aucun ancien cas test.
Test : 50 explicites, 12 indéterminables, 8 ambigus, 8 multi-émotions, 5 invalides.
"""

from dataset import cases

DEV_EXTRA = {
    "heureux": ["Je me sentais ravi de présenter mon gâteau à mes voisins.",
                "Je recevais une bonne nouvelle et débordais d'allégresse."],
    "stressant": ["Je tremblais d'effroi en entendant la porte céder.",
                  "J'étais anxieux car je ne retrouvais pas la sortie du métro."],
    "neutre": ["Je vérifiais une liste sans éprouver le moindre sentiment.",
               "Je déplaçais une boîte en restant parfaitement indifférent."],
    "triste": ["Je pleurais de peine en voyant ma grand-mère s'éloigner.",
               "Je restais seul, rempli de mélancolie et de chagrin."],
    "autre": ["Je ressentais du dégoût devant ces déchets gluants.",
              "J'étais furieux contre celui qui avait saccagé mon tableau."],
}
DEV_NEGATIVE = {
    "undetermined": [
        "Des nuages passaient au-dessus d'une tour rouge.",
        "J'entrais dans une boulangerie où trois pains étaient exposés.",
        "Je portais un sac et une casquette sur un quai.",
        "Je ne me souviens pas de mon émotion dans cette scène.",
        "Le récit ne précise pas du tout ce que je ressentais.",
        "Des personnes semblaient tristes mais mon ressenti est inconnu.",
        "Les gens riaient sur le trottoir ; je n'ai aucun souvenir de mon sentiment.",
        "Je notais seulement des portes et des couleurs dans mon rêve.",
    ],
    "ambiguous": ["Je ne savais pas si je riais de joie ou de nervosité.",
                  "Mon émotion était floue, impossible à nommer.",
                  "J'avais peut-être de la colère, ou peut-être de la tristesse.",
                  "Je ne peux pas dire si j'étais content ou terrifié."],
    "multiple": ["Je ressentais en même temps autant de joie que de peur.",
                 "J'étais simultanément triste et furieux, sans émotion dominante.",
                 "La joie et le chagrin m'envahissaient à parts égales.",
                 "Je ressentais une forte peur et un vif dégoût en même temps."],
}
TEST_EXPLICIT = {
    "heureux": [
        "Je fêtais mes retrouvailles avec ma cousine, rempli de joie.",
        "J'accueillais des chatons et ressentais un bonheur profond.",
        "La musique me faisait danser, j'étais vraiment heureux.",
        "Je terminais ma construction et me sentais très satisfait et joyeux.",
        "Un ami me faisait un cadeau ; j'étais enchanté et rayonnant de bonheur.",
        "Je riais avec mon équipe, emporté par une joie immense.",
        "Je regardais le lever du jour, comblé de bonheur.",
        "Je savourais la réussite de mon spectacle, fou de joie.",
        "Je retrouvais ma peluche et je me sentais ravi.",
        "Je courais dans le verger en éprouvant une grande allégresse.",
    ],
    "stressant": [
        "Un loup avançait vers moi et je ressentais une peur terrible.",
        "Je redoutais l'arrivée du contrôleur ; j'étais très anxieux.",
        "Je n'arrivais pas à appeler à l'aide et j'étais paniqué.",
        "Les marches s'écroulaient et je tremblais de terreur.",
        "Mon avion plongeait et j'étais mort de peur.",
        "Je devais parler devant mille personnes, submergé d'angoisse.",
        "Une ombre grattait au carreau et je me sentais terrifié.",
        "L'eau montait autour de moi ; la panique me paralysait.",
        "Je cherchais mon passeport, stressé à l'idée de manquer mon départ.",
        "Je craignais le chien qui aboyait et j'étais effrayé.",
    ],
    "neutre": [
        "Je triais des boutons, sans éprouver d'émotion particulière.",
        "Je lisais un horaire ; je me sentais émotionnellement neutre.",
        "Je traversais un couloir sans joie, sans peine et sans peur.",
        "Je posais une règle sur le bureau en restant indifférent.",
        "Je comptais des poteaux et ne ressentais rien de spécial.",
        "Je regardais le plafond avec une totale indifférence.",
        "Je changeais une ampoule, sans aucune réaction émotionnelle.",
        "Je remplissais un formulaire ; mes sentiments restaient neutres.",
        "Je recopiais une adresse sans émotion ni intérêt particulier.",
        "J'attendais mon tour sans impatience, sans joie et sans inquiétude.",
    ],
    "triste": [
        "Je perdais mon album de famille et pleurais de tristesse.",
        "Mes voisins m'oubliaient ; je me sentais seul et profondément triste.",
        "Je voyais ma sœur partir et ressentais une grande peine.",
        "Je cherchais ma maison disparue, accablé de chagrin.",
        "Je lisais une lettre d'adieu et mes larmes coulaient de tristesse.",
        "Un ami refusait de me reconnaître, ce qui me rendait malheureux.",
        "Je retrouvais le panier vide de mon chat disparu et sanglotais.",
        "Je disais adieu à mes camarades, le cœur rempli de chagrin.",
        "Je n'avais plus personne à qui parler et ressentais une immense solitude.",
        "Ma fleur préférée se fanait ; j'étais triste et abattu.",
    ],
    "autre": [
        "Je découvrais un piano minuscule ; ma seule émotion était la surprise.",
        "Une pomme chantait et j'étais stupéfait, sans joie ni peur.",
        "Une étoile entrait dans ma poche et je ressentais de l'étonnement.",
        "Une invention étrange éveillait en moi une grande curiosité.",
        "Je voulais comprendre cette énigme et me sentais curieux, pas inquiet.",
        "Quelqu'un déchirait mon dessin et j'étais en colère.",
        "On m'avait volé ma médaille et j'éprouvais une fureur intense.",
        "Je protestais contre une injustice, furieux plutôt que triste.",
        "Je goûtais un aliment pourri et ressentais un profond dégoût.",
        "Des vers couvraient mon assiette ; j'étais écœuré, sans peur.",
    ],
}
TEST_NEGATIVE = {
    "undetermined": [
        "Une valise verte se trouvait sous une table en métal.",
        "Je longeais un mur couvert d'affiches et tournais à gauche.",
        "Des oiseaux passaient devant un phare au bord d'une route.",
        "J'ouvrais un livre dont les pages montraient des rectangles.",
        "Une lampe éclairait le tapis, puis la scène changeait.",
        "Je tenais un billet de train mais mon ressenti n'est pas connu.",
        "La scène montrait un théâtre ; j'ai oublié ce que je ressentais.",
        "Je voyais une montagne, sans pouvoir dire quelle était mon émotion.",
        "Un enfant était heureux ; le rêve ne dit pas comment moi je me sentais.",
        "Une femme semblait effrayée, mais mon propre sentiment reste inconnu.",
        "Je notais le mot tristesse sur un panneau, sans souvenir de mon ressenti.",
        "Je racontais seulement les événements ; aucune information sur mes émotions.",
    ],
    "ambiguous": [
        "Mon sourire pouvait cacher de la joie ou de l'angoisse, je ne sais pas.",
        "Je me sentais bizarre et je ne peux préciser mon émotion.",
        "Je crois que j'étais triste, ou simplement fatigué, sans certitude.",
        "Je ne savais pas si ce tremblement venait de peur ou d'excitation.",
        "Mon émotion était incertaine, entre curiosité et inquiétude.",
        "Je ne suis pas sûr d'avoir ressenti du bonheur plutôt que de la surprise.",
        "Ma réaction est confuse ; je ne sais pas si j'étais neutre ou triste.",
        "Je me rappelle une émotion, mais impossible de dire laquelle.",
    ],
    "multiple": [
        "Je ressentais simultanément de la joie et de la tristesse, "
        "aussi fortes l'une que l'autre.",
        "La peur et la colère étaient toutes deux très présentes, aucune ne dominait.",
        "J'éprouvais autant de bonheur que d'angoisse au même instant.",
        "J'étais à la fois dégoûté et triste, sans sentiment principal.",
        "Une surprise intense se mêlait à une peur aussi intense.",
        "Je riais de bonheur et pleurais de chagrin, avec la même intensité.",
        "Je me sentais furieux et heureux à parts égales.",
        "Je ressentais deux émotions dominantes opposées : joie et tristesse.",
    ],
    "invalid": ["", " \t\n", "Moi…", "Un banc.", "x"*20001],
}


def make_rows(mapping, prefix, explicit):
    return [dict(id=f"{prefix}-{group}-{i+1}", group="explicit" if explicit else group,
                 expected=group if explicit else None, text=text)
            for group, texts in mapping.items() for i, text in enumerate(texts)]


def development():
    old = [{"id": "dev-old-"+r["id"], "group": "explicit", "expected": r["expected"],
            "text": r["text"]} for r in cases() if r["split"] == "dev"]
    return old+make_rows(DEV_EXTRA, "dev", True)+make_rows(DEV_NEGATIVE, "dev", False)


def final_cases():
    return make_rows(TEST_EXPLICIT, "final", True)+make_rows(TEST_NEGATIVE, "final", False)
