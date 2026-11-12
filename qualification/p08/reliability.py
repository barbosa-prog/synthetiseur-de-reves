"""P08 2C : sélection dev séparée du test, mDeBERTa CPU exclusivement."""

import argparse
import faulthandler
import hashlib
import importlib.metadata
import itertools
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

os.environ.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")

from compare_b import score_text  # noqa: E402
from dataset import LABELS  # noqa: E402
from evaluate import metrics, predict  # noqa: E402
from reliability_data import development, final_cases  # noqa: E402

ELEMENTS = ["heureux", "stressant", "neutre", "triste", "colere", "degout", "surprise", "curiosite"]
VARIANTS = [
    ["Je ressens de la joie ou du bonheur.", "Je ressens de la peur, du stress ou de l'angoisse.",
     "Je précise que je ne ressens aucune émotion particulière.", "Je ressens de la tristesse.",
     "Je ressens de la colère.", "Je ressens du dégoût.",
     "Je ressens de la surprise ou de l'étonnement.", "Je ressens de la curiosité."],
    ["La personne qui raconte son rêve se sent heureuse.",
     "La personne qui raconte son rêve se sent effrayée ou anxieuse.",
     "La personne qui raconte son rêve décrit explicitement son indifférence émotionnelle.",
     "La personne qui raconte son rêve se sent triste ou éprouve du chagrin.",
     "La personne qui raconte son rêve est furieuse.",
     "La personne qui raconte son rêve est écœurée.",
     "La personne qui raconte son rêve est étonnée.",
     "La personne qui raconte son rêve est curieuse."],
]
GATES = ["Le récit ne précise pas ce que ressent la personne qui raconte son rêve.",
         "La personne qui raconte son rêve hésite et ne sait pas quelle émotion elle ressent.",
         "La personne ressent plusieurs émotions fortes sans émotion dominante."]
# Indices de ressenti issus des catégories métier et du DEV seulement ; pas un classifieur.
EVIDENCE = re.compile(
    r"joie|heureu|bonheur|ravi|allégresse|peur|stress|angoiss|anxieu|terrifi|paniqu|effroi|"
    r"triste|chagrin|peine|mélancoli|solitude|neutr|indifféren|sans émotion|"
    r"aucun.{0,12}(émotion|sentiment)|surpris|étonn|curio|colère|furieu|dégoût|écœur", re.I)


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def features(model, tokenizer, torch, text, variant):
    if not text.strip() or len(text) > 20000:
        return dict(invalid="invalid_text")
    ids = tokenizer.encode(text.strip(), add_special_tokens=False, verbose=False)
    if len(ids) < 5:
        return dict(invalid="insufficient_information")
    mapping = {v.lower(): int(k) for k, v in model.config.id2label.items()}
    hypotheses = VARIANTS[variant]+GATES
    chunks = []
    for offset in range(0, len(ids), 300):
        text_chunk = tokenizer.decode(ids[offset:offset+300], skip_special_tokens=True)
        values = []
        for start in range(0, len(hypotheses), 5):
            batch = hypotheses[start:start+5]
            encoded = tokenizer([text_chunk]*len(batch), batch, padding=True,
                                truncation=False, return_tensors="pt")
            if encoded["input_ids"].shape[1] > 512:
                raise RuntimeError("Paire trop longue sans troncature")
            with torch.inference_mode():
                output = model(**encoded).logits.softmax(dim=-1)[:, mapping["entailment"]]
            values.extend(output.tolist())
        chunks.append(values)
    values = [statistics.mean(chunk[i] for chunk in chunks) for i in range(len(hypotheses))]
    grouped = values[:4]+[max(values[4:8])]
    return dict(invalid=None, categories=grouped, elementary=values[:8],
                gates=values[8:], lexical_evidence=bool(EVIDENCE.search(text)), chunks=len(chunks))


def decide(raw, params):
    if raw["invalid"]:
        return None, raw["invalid"]
    if params["lexical_guard"] and not raw["lexical_evidence"]:
        return None, "no_explicit_evidence"
    for index, code in enumerate(["undetermined", "ambiguous", "multiple"]):
        if raw["gates"][index] >= params["gate_threshold"]:
            return None, code
    order = sorted(range(5), key=lambda i: raw["categories"][i], reverse=True)
    first, second = [raw["categories"][i] for i in order[:2]]
    if first < params["threshold"] or first-second < params["margin"]:
        return None, "uncertain_scores"
    return LABELS[order[0]], None


def summary(rows):
    explicit = [r for r in rows if r["group"] == "explicit"]
    emitted = [r for r in explicit if r["prediction"] is not None]
    grouped = {}
    for group in sorted({r["group"] for r in rows}-{"explicit"}):
        subset = [r for r in rows if r["group"] == group]
        grouped[group] = dict(count=len(subset), suggestions=sum(r["prediction"] is not None
                                                                  for r in subset),
                              abstention_rate=sum(r["prediction"] is None for r in subset)
                              / len(subset))
    return dict(explicit=metrics(explicit), coverage=len(emitted)/len(explicit),
                emitted_accuracy=(sum(r["prediction"] == r["expected"] for r in emitted)
                                  / len(emitted) if emitted else None), groups=grouped)


def select_parameters(scored):
    experiments = []
    for variant, threshold, margin, gate, lexical in itertools.product(
            range(2), [0.45, 0.60, 0.75, 0.85], [0.05, 0.15, 0.25], [0.4, 0.6, 0.8], [False, True]):
        params = dict(variant=variant, threshold=threshold, margin=margin,
                      gate_threshold=gate, lexical_guard=lexical)
        rows = [{**row, "prediction": decide(row["features"][variant], params)[0]}
                for row in scored]
        result = summary(rows)
        unsafe = sum(g["suggestions"] for g in result["groups"].values())
        experiments.append(dict(parameters=params, macro_f1=result["explicit"]["macro_f1"],
                                unsafe=unsafe, coverage=result["coverage"],
                                emitted_accuracy=result["emitted_accuracy"]))
    # Objectif préfixé : zéro suggestion sur les négatifs DEV, puis meilleur macro-F1.
    eligible = [e for e in experiments if e["unsafe"] == 0]
    pool = eligible or experiments
    best = max(pool, key=lambda e: (-e["unsafe"], e["macro_f1"]))
    return best, experiments


def main():
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["dev", "test"], required=True)
    stage = parser.parse_args().stage
    source = Path(__file__).parent
    root = Path(os.environ["LOCALAPPDATA"])/"SynthetiseurDeReves/qualification/p08c"
    model_root = root.parent/"p08b/model"
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(42)
    torch.use_deterministic_algorithms(True)
    assert torch.version.cuda is None
    start = time.perf_counter()
    print("loading_cpu", stage, flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_root, local_files_only=True,
                                              trust_remote_code=False, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_root, local_files_only=True, trust_remote_code=False, use_safetensors=True,
        dtype=torch.float32).to("cpu").eval()
    load_seconds = time.perf_counter()-start
    assert all(p.device.type == "cpu" for p in model.parameters())
    print("loaded_cpu", load_seconds, flush=True)
    hashes = {name: fingerprint(source/name) for name in ["reliability_data.py", "reliability.py"]}
    common = dict(hashes=hashes, model=json.loads((model_root/"manifest.json").read_text()),
                  load_seconds=load_seconds, cuda=torch.version.cuda, python=sys.version,
                  dependencies={d: importlib.metadata.version(d) for d in
                                ["torch", "transformers", "tokenizers", "safetensors", "psutil"]})
    if stage == "dev":
        scored = []
        for case in development():
            raw = [features(model, tokenizer, torch, case["text"], variant) for variant in range(2)]
            scored.append({**case, "features": raw})
            print("dev", case["id"], flush=True)
        best, experiments = select_parameters(scored)
        frozen = dict(parameters=best["parameters"], hashes=hashes,
                      rule="minimize negative DEV suggestions then maximize explicit macro-F1")
        (root/"frozen.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
        report = dict(**common, best=best, experiments=experiments, rows=scored)
    else:
        frozen = json.loads((root/"frozen.json").read_text())
        if frozen["hashes"] != hashes:
            raise RuntimeError("Code ou corpus modifié depuis le gel DEV")
        baseline = json.loads((source/"results.json").read_text(encoding="utf-8"))["parameters"]
        rows = []
        for index, case in enumerate(final_cases()):
            outputs = {}
            for method in (["baseline", "candidate"] if index % 2 == 0
                           else ["candidate", "baseline"]):
                start = time.perf_counter()
                if method == "baseline":
                    scores, chunks, reason = score_text(model, tokenizer, torch,
                                                       case["text"], baseline)
                    label = predict(scores, baseline["threshold"], baseline["margin"])
                    raw = dict(scores=scores, chunks=chunks)
                    reason = reason or ("uncertain_scores" if label is None else None)
                else:
                    raw = features(model, tokenizer, torch, case["text"],
                                   frozen["parameters"]["variant"])
                    label, reason = decide(raw, frozen["parameters"])
                outputs[method] = dict(prediction=label, reason=reason, raw=raw,
                                       seconds=time.perf_counter()-start)
            rows.append({**case, "outputs": outputs})
            print("test", case["id"], {m: v["prediction"] for m, v in outputs.items()}, flush=True)
        summaries = {method: summary([{**r, **r["outputs"][method]} for r in rows])
                     for method in ["baseline", "candidate"]}
        report = dict(**common, frozen=frozen, baseline_parameters=baseline,
                      summaries=summaries, rows=rows,
                      latencies={method: dict(
                          median=statistics.median(r["outputs"][method]["seconds"] for r in rows
                                                   if r["group"] == "explicit"),
                          maximum=max(r["outputs"][method]["seconds"] for r in rows
                                      if r["group"] == "explicit"))
                          for method in ["baseline", "candidate"]})
    (root/stage/"results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print("stage_complete", stage, flush=True)


if __name__ == "__main__":
    faulthandler.enable()
    main()
