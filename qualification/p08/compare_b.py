"""Comparaison CPU à protocole MiniLM figé ; aucun réglage ni entraînement."""

import argparse
import faulthandler
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

from confirmation import confirmation_cases  # noqa: E402
from dataset import cases  # noqa: E402
from evaluate import metrics, predict  # noqa: E402


def score_text(model, tokenizer, torch, text, parameters):
    if not isinstance(text, str) or not text.strip() or len(text) > parameters["max_characters"]:
        return None, 0, "invalid_text"
    ids = tokenizer.encode(text.strip(), add_special_tokens=False, verbose=False)
    if len(ids) < parameters["min_tokens"]:
        return None, 0, "insufficient_information"
    size = parameters["chunk_tokens"]
    chunks = [ids[offset:offset+size] for offset in range(0, len(ids), size)]
    scores = []
    entailment = {name.lower(): int(index)
                  for index, name in model.config.id2label.items()}["entailment"]
    for chunk in chunks:
        premise = tokenizer.decode(chunk, skip_special_tokens=True)
        encoded = tokenizer([premise]*5, parameters["hypotheses"], padding=True,
                            truncation=False, return_tensors="pt")
        if encoded["input_ids"].shape[1] > 512:
            raise RuntimeError("Paire trop longue, aucune troncature autorisée")
        with torch.inference_mode():
            values = model(**encoded).logits[:, entailment].softmax(dim=0).tolist()
        scores.append(values)
    return [statistics.mean(s[i] for s in scores) for i in range(5)], len(chunks), None


def summarize(rows):
    explicit = [r for r in rows if r["group"] == "explicit"]
    groups = {}
    for group in sorted({r["group"] for r in rows}-{"explicit"}):
        selected = [r for r in rows if r["group"] == group]
        groups[group] = dict(count=len(selected),
                            abstention_rate=sum(r["prediction"] is None for r in selected)
                            / len(selected),
                            incompatible=[r["id"] for r in selected
                                if r["prediction"] is not None
                                and r["prediction"] not in r["acceptable"]])
    return dict(explicit=metrics(explicit), groups=groups)


def main():
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=["deberta", "minilm"], required=True)
    args = parser.parse_args()
    source = Path(__file__).parent
    local = Path(os.environ["LOCALAPPDATA"])/"SynthetiseurDeReves/qualification"
    root = local/"p08b"/args.candidate
    model_root = local/("p08b" if args.candidate == "deberta" else "p08")/"model"
    baseline = json.loads((source/"results.json").read_text(encoding="utf-8"))
    parameters = baseline["parameters"]
    torch.set_num_threads(parameters["threads"])
    torch.set_num_interop_threads(1)
    torch.manual_seed(parameters["seed"])
    torch.use_deterministic_algorithms(True)
    assert torch.version.cuda is None
    print("loading_cpu", args.candidate, flush=True)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_root, local_files_only=True,
                                              trust_remote_code=False, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_root, local_files_only=True, trust_remote_code=False, use_safetensors=True,
        dtype=torch.float32).to("cpu").eval()
    load_seconds = time.perf_counter()-started
    assert all(p.device.type == "cpu" and p.dtype == torch.float32 for p in model.parameters())
    print("loaded_cpu", round(load_seconds, 3), flush=True)
    rows = []
    old = [r for r in cases() if r["split"] != "dev"]
    for corpus, dataset in [("reused", old), ("confirmation", confirmation_cases())]:
        for case in dataset:
            started = time.perf_counter()
            scores, chunks, reason = score_text(model, tokenizer, torch, case["text"], parameters)
            label = predict(scores, parameters["threshold"], parameters["margin"])
            row = {**case, "corpus": corpus, "scores": scores, "chunks": chunks,
                   "prediction": label,
                   "reason": reason or ("ambiguous" if label is None else None),
                   "seconds": time.perf_counter()-started}
            rows.append(row)
            print(corpus, case["id"], label or "abstention", flush=True)
    latencies = [r["seconds"] for r in rows if r["group"] == "explicit"]
    report = dict(candidate=args.candidate, parameters=parameters, adapted=False,
                  model=json.loads((model_root/"manifest.json").read_text(encoding="utf-8")),
                  dependencies={d: importlib.metadata.version(d) for d in
                                ["torch", "transformers", "tokenizers", "safetensors", "psutil"]},
                  python=sys.version, torch_cuda=torch.version.cuda,
                  model_class=type(model).__name__, tokenizer_class=type(tokenizer).__name__,
                  tokenizer_max=tokenizer.model_max_length,
                  model_max_positions=model.config.max_position_embeddings,
                  id2label=model.config.id2label, load_seconds=load_seconds,
                  latency_median=statistics.median(latencies), latency_max=max(latencies),
                  corpus_hashes={name: hashlib.sha256((source/name).read_bytes()).hexdigest()
                                 for name in ["dataset.py", "confirmation.py", "results.json"]},
                  summaries={corpus: summarize([r for r in rows if r["corpus"] == corpus])
                             for corpus in ["reused", "confirmation"]}, rows=rows)
    (root/"results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
    print("evaluation_complete", flush=True)


if __name__ == "__main__":
    faulthandler.enable()
    main()
