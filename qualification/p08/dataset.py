"""40 récits fictifs, annotations humaines proposées AVANT toute inférence.

Les 10 cas dev règlent seulement les hypothèses/seuils ; les 15 cas test sont
évalués une fois après gel. Ambigus et invalides ne règlent aucun paramètre.
"""

LABELS = ["heureux", "stressant", "neutre", "triste", "autre"]
EXPLICIT = {
    "heureux": [
        "Je retrouvais mon frère et je débordais de joie en le serrant dans mes bras.",
        "Je dansais avec mes amis, heureux de partager cette fête merveilleuse.",
        "Mon chien revenait enfin et je riais de bonheur en jouant avec lui.",
        "Je gagnais un concours et ressentais une immense joie entouré de mes proches.",
        "Je volais au-dessus des champs, comblé et joyeux, un sourire aux lèvres.",
    ],
    "stressant": [
        "Quelqu'un me poursuivait dans un tunnel et j'étais terrifié, le cœur battant.",
        "Je ratais mon examen, pris de panique et incapable de respirer calmement.",
        "Les murs se refermaient et je cherchais désespérément une sortie, angoissé.",
        "Je perdais mon enfant dans la foule et une peur intense me paralysait.",
        "Un incendie approchait ; je tremblais de terreur sans pouvoir m'enfuir.",
    ],
    "neutre": [
        "Je classais des papiers sur une table, sans émotion particulière.",
        "Je regardais une horloge puis une porte ; je me sentais indifférent.",
        "Je prenais le bus comme chaque jour, sans joie, peur ni tristesse.",
        "Je comptais des carreaux ; cette activité me laissait totalement neutre.",
        "Je rangeais des chaussettes, sans ressentir quoi que ce soit de spécial.",
    ],
    "triste": [
        "Je disais adieu à mon ami pour toujours et pleurais de chagrin.",
        "Ma maison était vide ; je ressentais une profonde tristesse et solitude.",
        "Je retrouvais une lettre d'un proche disparu et sanglotais, accablé de peine.",
        "Personne ne venait à mon anniversaire et je me sentais abandonné et triste.",
        "Je voyais mon jardin détruit et pleurais la perte de mes souvenirs.",
    ],
    "autre": [
        "Un escalier devenait un poisson ; je ressentais surtout de la surprise.",
        "J'observais une machine inconnue avec curiosité, ni heureux, triste ou effrayé.",
        "On m'accusait injustement et je bouillonnais de colère, sans peur ni chagrin.",
        "Une odeur infecte envahissait la cuisine et je ressentais du dégoût.",
        "Un visage changeait sans cesse ; mon sentiment dominant était l'étonnement.",
    ],
}
AMBIGUOUS = [
    ("J'étais poursuivi puis sauvé ; la peur et la joie se mélangeaient.",
     ["stressant", "heureux"]),
    ("Je souriais en retrouvant un souvenir, mais je pleurais aussi son absence.",
     ["heureux", "triste"]),
    ("Une forêt violette s'étendait devant moi.", []),
    ("Une lune énorme flottait dans ma chambre ; je ne sais plus ce que je ressentais.", []),
    ("Je n'avais pas peur, contrairement aux autres qui criaient.", ["neutre", "autre"]),
    ("La fête était magnifique mais je craignais qu'elle s'arrête.", ["heureux", "stressant"]),
    ("Tout le monde riait pendant que je restais seul avec mon chagrin.", ["triste"]),
    ("Un monstre me servait gentiment du thé et je trouvais cela amusant.", ["heureux", "autre"]),
    ("Je tombais sans fin, peut-être avec plaisir, peut-être avec peur.", ["heureux", "stressant"]),
    ("Je marchais dans une rue et regardais les vitrines.", []),
]
INCOMPLETE = ["", " \n\t", "Je…", "Une porte.", "x" * 20001]


def cases():
    result = []
    for label, texts in EXPLICIT.items():
        for index, text in enumerate(texts):
            result.append(dict(id=f"{label}-{index+1}", group="explicit",
                               split="dev" if index < 2 else "test", text=text,
                               expected=label, acceptable=[label]))
    for index, (text, acceptable) in enumerate(AMBIGUOUS):
        result.append(dict(id=f"ambiguous-{index+1}", group="ambiguous", split="test",
                           text=text, expected=None, acceptable=acceptable))
    for index, text in enumerate(INCOMPLETE):
        result.append(dict(id=f"incomplete-{index+1}", group="incomplete", split="test",
                           text=text, expected=None, acceptable=[]))
    return result
