"""P14 : périmètre métier explicite et couverture des corps de fonctions."""

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIMUM = 80.0
EXTRA_MODULES = {
    "auth.py", "security.py", "auth_schemas.py", "audio_types.py", "export_contract.py",
    "history_schemas.py", "transcript_schemas.py", "stt_audio.py", "audio_worker.py",
    "stt_provider.py", "image_provider.py", "emotion_provider.py", "stt_worker.py",
    "image_worker.py", "emotion_worker.py", "image_runner.py", "emotion_runner.py",
    "emotion_config.py", "job_config.py", "storage/local.py",
}


def business_files(root=ROOT):
    app = root / "backend/app"
    selected = set(app.glob("services/**/*.py")) | set(app.glob("*_rules.py"))
    selected |= {app / name for name in EXTRA_MODULES}
    return sorted(path.relative_to(root).as_posix() for path in selected)


def summarize(covered, missing, branches, missing_branches):
    lines = len(covered) + len(missing)
    arcs = len(branches) + len(missing_branches)
    total = lines + arcs
    return {
        "covered_statements": len(covered), "statements": lines,
        "covered_branches": len(branches), "branches": arcs,
        "statement_percent": 100 * len(covered) / lines if lines else None,
        "branch_percent": 100 * len(branches) / arcs if arcs else None,
        "combined_percent": 100 * (len(covered) + len(branches)) / total if total else None,
    }


def evaluate(report, root=ROOT, threshold=MINIMUM):
    if not MINIMUM <= threshold <= 100:
        raise ValueError("Le seuil métier doit être compris entre 80 et 100")
    if report.get("meta", {}).get("branch_coverage") is not True:
        raise ValueError("Rapport sans mesure des branches : validation refusée")
    measured = {Path(name).as_posix(): value for name, value in report["files"].items()}
    results, covered, missing, branches, missed_branches = {}, set(), set(), set(), set()
    for name in business_files(root):
        data = measured.get(name)
        if data is None:
            raise ValueError("Module métier absent du rapport : " + name)
        tree = ast.parse((root / name).read_text(encoding="utf-8-sig"))
        body_lines = set()
        scopes = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = set(range(node.body[0].lineno, node.end_lineno + 1))
                body_lines.update(lines)
                scopes.append((f"{node.name}:{node.lineno}", lines))
        executed = set(data["executed_lines"]) & body_lines
        absent = set(data["missing_lines"]) & body_lines
        # Les lignes exclues par coverage (interfaces Protocol) ne sont pas réintégrées.
        executed -= set(data.get("excluded_lines", []))
        arcs = {tuple(arc) for arc in data["executed_branches"] if arc[0] in body_lines}
        missed = {tuple(arc) for arc in data["missing_branches"] if arc[0] in body_lines}
        results[name] = summarize(executed, absent, arcs, missed)
        results[name]["functions"] = {
            label: summarize(executed & lines, absent & lines,
                             {arc for arc in arcs if arc[0] in lines},
                             {arc for arc in missed if arc[0] in lines})
            for label, lines in scopes
        }
        covered.update((name, line) for line in executed)
        missing.update((name, line) for line in absent)
        branches.update((name, arc) for arc in arcs)
        missed_branches.update((name, arc) for arc in missed)
    totals = summarize(covered, missing, branches, missed_branches)
    if totals["combined_percent"] is None or not totals["branches"]:
        raise ValueError("Périmètre métier vide ou branches absentes")
    return {"scope": "function_bodies", "scope_version": 1,
            "measurement_meta": report["meta"], "threshold": threshold, "totals": totals,
            "passed": totals["combined_percent"] >= threshold, "files": results,
            "backend_totals": report["totals"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--threshold", type=float, default=MINIMUM)
    args = parser.parse_args(argv)
    try:
        result = evaluate(json.loads(args.report.read_text(encoding="utf-8")),
                          threshold=args.threshold)
    except (ValueError, KeyError, OSError, SyntaxError):
        print("Couverture métier invalide ou incomplète : contrôle échoué.")
        return 2
    if args.output:
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    totals = result["totals"]
    print(f"Métier : instructions {totals['statement_percent']:.2f} % ; "
          f"branches {totals['branch_percent']:.2f} % ; "
          f"combiné {totals['combined_percent']:.2f} % ; seuil {args.threshold:.2f} %")
    print("Seuil métier :", "VALIDÉ" if result["passed"] else "ÉCHEC")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
