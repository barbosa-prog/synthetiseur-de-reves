"""Un seul modèle CPU par processus ; même surveillant et limites qu'en phase 2."""

import argparse
import os
from pathlib import Path

from watch import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=["deberta", "minilm"], required=True)
    candidate = parser.parse_args().candidate
    root = Path(os.environ["LOCALAPPDATA"])/"SynthetiseurDeReves/qualification/p08b"/candidate
    raise SystemExit(main(root=root, script=Path(__file__).with_name("compare_b.py"),
                          arguments=["--candidate", candidate]))
