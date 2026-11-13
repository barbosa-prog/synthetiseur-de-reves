"""Résumé CI sans logs, identifiants PostgreSQL ni données de tests."""

import argparse
import json
import os
import re
from pathlib import Path
from xml.etree import ElementTree


def render(directory, commit):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Identifiant de commit invalide")
    business = json.loads((directory / "business.json").read_text(encoding="utf-8"))
    backend = json.loads((directory / "backend.json").read_text(encoding="utf-8"))
    suites = ElementTree.parse(directory / "tests.xml").getroot()
    counts = {key: sum(int(s.get(key, 0)) for s in suites.iter("testsuite"))
              for key in ("tests", "failures", "errors", "skipped")}
    if not counts["tests"] or any(counts[key] for key in ("failures", "errors", "skipped")):
        raise ValueError("La campagne obligatoire n'est pas entièrement réussie")
    if (not business["passed"] or business["threshold"] < 80
            or business["totals"]["combined_percent"] < 80
            or not backend["meta"]["branch_coverage"]):
        raise ValueError("Seuil métier ou branches non validés")
    summary = {"commit": commit, "tests": counts, "business": business["totals"],
               "backend": backend["totals"], "threshold": business["threshold"],
               "browser": "Étape Chrome séparée ; consulter son résultat dans le job"}
    (directory / "ci-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    markdown = (f"## P14 — commit `{commit}`\n\n"
                f"Tests obligatoires : **{counts['tests']}**, aucun échec ni ignoré.\n\n"
                f"Couverture métier combinée : **{business['totals']['combined_percent']:.2f} %** "
                f"(seuil {business['threshold']:.0f} %).\n\n"
                f"Backend combiné : **{backend['totals']['percent_covered']:.2f} %**.\n\n"
                "Navigateur : étape séparée du même job, sans modèle IA.\n")
    (directory / "ci-summary.md").write_text(markdown, encoding="utf-8")
    return markdown


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("tmp/p14-coverage"))
    args = parser.parse_args()
    try:
        markdown = render(args.directory, os.environ.get("GITHUB_SHA", ""))
        if os.getenv("GITHUB_STEP_SUMMARY"):
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
                stream.write(markdown)
    except (OSError, ValueError, KeyError, ElementTree.ParseError):
        print("Résumé CI indisponible ou contrôles non validés.")
        return 1
    print("Résumé associé au commit généré ; aucun détail privé exporté.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
