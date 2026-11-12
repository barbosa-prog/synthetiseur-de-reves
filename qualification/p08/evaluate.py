"""Évaluation CPU hors ligne ; paramètres choisis UNIQUEMENT sur les cas dev."""

import hashlib
import importlib.metadata
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")

from dataset import LABELS, cases  # noqa: E402

HYPOTHESES = [
    ["Ce récit exprime de la joie et du bonheur.", "Ce récit exprime de la peur et du stress.",
     "Ce récit exprime une absence d'émotion particulière.", "Ce récit exprime de la tristesse.",
     "Ce récit exprime une autre émotion : surprise, curiosité, colère ou dégoût."],
    ["La personne se sent heureuse.", "La personne se sent stressée ou effrayée.",
     "La personne se sent neutre, sans émotion particulière.", "La personne se sent triste.",
     "La personne ressent surtout de la surprise, de la curiosité, de la colère ou du dégoût."],
]


def predict(scores, threshold, margin):
    if scores is None:
        return None
    ranked = sorted(range(5), key=lambda i: scores[i], reverse=True)
    if scores[ranked[0]] < threshold or scores[ranked[0]]-scores[ranked[1]] < margin:
        return None
    return LABELS[ranked[0]]


def metrics(rows):
    matrix = {gold: {pred: 0 for pred in LABELS+["abstention"]} for gold in LABELS}
    for row in rows:
        matrix[row["expected"]][row["prediction"] or "abstention"] += 1
    per_class = {}
    for label in LABELS:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted = sum(matrix[gold][label] for gold in LABELS)
        precision, recall = tp/predicted if predicted else 0, tp/support if support else 0
        f1 = 2*precision*recall/(precision+recall) if precision+recall else 0
        per_class[label] = dict(precision=precision, recall=recall, f1=f1, support=support)
    return dict(matrix=matrix, per_class=per_class,
                macro_f1=statistics.mean(item["f1"] for item in per_class.values()),
                accuracy=sum(r["prediction"] == r["expected"] for r in rows)/len(rows),
                abstention_rate=sum(r["prediction"] is None for r in rows)/len(rows))


def main():
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(42)
    torch.use_deterministic_algorithms(True)
    root = Path(os.environ["LOCALAPPDATA"])/"SynthetiseurDeReves/qualification/p08"
    model_root = root/"model"
    start = time.perf_counter()
    print("loading_cpu", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_root, local_files_only=True,
                                              trust_remote_code=False, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_root, local_files_only=True, trust_remote_code=False, use_safetensors=True,
        torch_dtype=torch.float32).to("cpu").eval()
    load_seconds = time.perf_counter()-start
    assert torch.version.cuda is None
    assert all(p.device.type == "cpu" for p in model.parameters())
    label_map = {name.lower(): int(index) for index, name in model.config.id2label.items()}
    entailment = label_map["entailment"]
    print("loaded_cpu", round(load_seconds, 3), flush=True)
    data = cases()

    def score(text, hypotheses):
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            return None, 0, "invalid_text"
        ids = tokenizer.encode(text.strip(), add_special_tokens=False)
        if len(ids) < 5:
            return None, 0, "insufficient_information"
        # 300 tokens par fragment, sans troncature ; tous les fragments sont analysés.
        chunks = [ids[offset:offset+300] for offset in range(0, len(ids), 300)]
        scores = []
        for chunk in chunks:
            premise = tokenizer.decode(chunk, skip_special_tokens=True)
            encoded = tokenizer([premise]*5, hypotheses, padding=True, truncation=False,
                                return_tensors="pt")
            if encoded["input_ids"].shape[1] > 512:
                raise RuntimeError("Paire au-delà de 512 tokens, aucune troncature autorisée")
            with torch.inference_mode():
                # Même compétition entre les cinq hypothèses que le zero-shot single-label.
                values = model(**encoded).logits[:, entailment].softmax(dim=0).tolist()
            scores.append(values)
        return [statistics.mean(s[i] for s in scores) for i in range(5)], len(chunks), None

    if "--frozen" in sys.argv:
        frozen = json.loads((root/"frozen-parameters.json").read_text(encoding="utf-8"))
        candidates = json.loads((root/"results.json").read_text(encoding="utf-8"))["dev_candidates"]
        best = frozen
    else:
        dev = [row for row in data if row["split"] == "dev"]
        candidates = []
        for variant, hypotheses in enumerate(HYPOTHESES):
            scored = [{**row, "scores": score(row["text"], hypotheses)[0]} for row in dev]
            for threshold in [0.35, 0.45, 0.55]:
                for margin in [0.05, 0.15, 0.25]:
                    rows = [{**row, "prediction": predict(row["scores"], threshold, margin)}
                            for row in scored]
                    candidates.append(dict(variant=variant, threshold=threshold, margin=margin,
                                           metrics=metrics(rows)))
        # Égalité : variante initiale, seuil puis marge les plus faibles (ordre fixé).
        best = max(candidates, key=lambda item: item["metrics"]["macro_f1"])
        frozen = {**best, "hypotheses": HYPOTHESES[best["variant"]], "chunk_tokens": 300,
                  "max_characters": 20000, "min_tokens": 5, "aggregation": "mean",
                  "seed": 42, "threads": 2}
        (root/"frozen-parameters.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    print("parameters_frozen_before_test", flush=True)
    rows = []
    for row in data:
        if row["split"] == "dev":
            continue
        began = time.perf_counter()
        scores, chunks, reason = score(row["text"], frozen["hypotheses"])
        prediction = predict(scores, best["threshold"], best["margin"])
        rows.append({**row, "scores": scores, "prediction": prediction, "chunks": chunks,
                     "reason": reason or ("ambiguous" if prediction is None else None),
                     "seconds": time.perf_counter()-began})
        print(row["id"], prediction or "abstention", flush=True)
    explicit = [row for row in rows if row["group"] == "explicit"]
    groups = {}
    for group in ["ambiguous", "incomplete"]:
        selected = [row for row in rows if row["group"] == group]
        groups[group] = dict(count=len(selected),
                            abstention_rate=sum(r["prediction"] is None for r in selected)
                            / len(selected),
                            incompatible_suggestions=[r["id"] for r in selected
                                if r["prediction"] is not None
                                and r["prediction"] not in r["acceptable"]])
    long_text = "Je rangeais des livres sans émotion particulière. "*220
    began = time.perf_counter()
    long_scores, long_chunks, long_reason = score(long_text, frozen["hypotheses"])
    long_check = dict(characters=len(long_text), chunks=long_chunks, reason=long_reason,
                      prediction=predict(long_scores, best["threshold"], best["margin"]),
                      seconds=time.perf_counter()-began)
    # Long_check est un contrôle technique synthétique hors des 40 cas annotés.
    report = dict(model=json.loads((model_root/"manifest.json").read_text()),
                  dependencies={d: importlib.metadata.version(d) for d in
                                ["torch", "transformers", "tokenizers", "safetensors", "psutil"]},
                  python=__import__("sys").version, torch_cuda=torch.version.cuda,
                  tokenizer_class=type(tokenizer).__name__,
                  tokenizer_max=tokenizer.model_max_length,
                  model_max_positions=model.config.max_position_embeddings,
                  id2label=model.config.id2label,
                  dataset_sha256=hashlib.sha256(Path(__file__).with_name("dataset.py")
                                                .read_bytes()).hexdigest(),
                  parameters=frozen, dev_candidates=candidates, final=metrics(explicit),
                  groups=groups, rows=rows, long_check=long_check, load_seconds=load_seconds,
                  latency_median=statistics.median(r["seconds"] for r in explicit),
                  latency_max=max(r["seconds"] for r in explicit))
    (root/"results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    print("evaluation_complete", flush=True)


if __name__ == "__main__":
    import faulthandler
    faulthandler.enable()
    main()
