"""Nouveau corpus fictif annoté avant inférence, jamais utilisé pour régler.

Trois récits par classe et cinq cas sans émotion déterminable. Ces annotations
ne sont pas une vérité psychologique ; elles restent une référence de test.
"""

TEXTS = {
    "heureux": [
        "Je recevais les clés de mon atelier et je sautais de joie avec ma sœur.",
        "Nous chantions sur un bateau ; je savourais un bonheur intense.",
        "Je réussissais à guérir un oiseau blessé et me sentais ravi, sans aucune inquiétude.",
    ],
    "stressant": [
        "Je devais traverser un pont qui craquait ; j'étais affolé, persuadé de mourir.",
        "L'ascenseur restait coincé entre deux étages et une angoisse incontrôlable m'envahissait.",
        "Une alarme sonnait dans l'école ; je paniquais en cherchant mes chaussures pour fuir.",
    ],
    "neutre": [
        "Je recopiais des numéros de téléphone, en restant totalement indifférent.",
        "Je mettais une tasse dans le placard, sans ressentir d'émotion.",
        "Je changeais de wagon sans aucune réaction particulière, ni agréable ni désagréable.",
    ],
    "triste": [
        "Je retrouvais mon vieux vélo cassé et ressentais un grand chagrin en pensant à mon père.",
        "Mon meilleur ami m'oubliait et je pleurais doucement, le cœur lourd de tristesse.",
        "Je quittais mon village pour toujours, accablé de peine à l'idée de ne jamais revenir.",
    ],
    "autre": [
        "Un rideau révélait une ville miniature ; je ressentais uniquement de l'étonnement.",
        "Je voyais quelqu'un détruire mon travail et j'éprouvais une vive colère, pas de peur.",
        "En découvrant une matière visqueuse dans mon repas, mon sentiment était le dégoût.",
    ],
}
UNDETERMINED = [
    "Un train bleu longeait la mer avant de disparaître derrière une colline.",
    "J'apercevais trois fenêtres éclairées ; je ne me rappelle pas mon ressenti.",
    "Le ciel changeait de couleur et une silhouette ouvrait un parapluie.",
    "Mon rêve montre une fontaine carrée au milieu d'une place pavée.",
    "Je tenais une clé dans la main ; aucune information sur mon émotion ne me revient.",
]
INVALID = ["", " \t\n", "Je…", "Un lit.", "x"*20001]


def confirmation_cases():
    rows = [dict(id=f"new-{label}-{i+1}", group="explicit", expected=label,
                 acceptable=[label], text=text, split="confirmation")
            for label, texts in TEXTS.items() for i, text in enumerate(texts)]
    rows += [dict(id=f"new-unknown-{i+1}", group="undetermined", expected=None,
                  acceptable=[], text=text, split="confirmation")
             for i, text in enumerate(UNDETERMINED)]
    rows += [dict(id=f"new-invalid-{i+1}", group="incomplete", expected=None,
                  acceptable=[], text=text, split="confirmation")
             for i, text in enumerate(INVALID)]
    return rows
