"""Seul second candidat autorisé ; répertoire distinct de MiniLM."""

import os
from pathlib import Path

from download import main

if __name__ == "__main__":
    main(root=Path(os.environ["LOCALAPPDATA"])/"SynthetiseurDeReves/qualification/p08b/model",
         repo="MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
         revision="8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c",
         files=["README.md", "config.json", "tokenizer.json", "tokenizer_config.json",
                "special_tokens_map.json", "added_tokens.json", "model.safetensors"])
