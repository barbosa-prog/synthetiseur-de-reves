"""Qualification 2C, réutilisation du seul surveillant CPU."""

import argparse
import os
from pathlib import Path

from watch import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["dev", "test"], required=True)
    stage = parser.parse_args().stage
    root = Path(os.environ["LOCALAPPDATA"])/"SynthetiseurDeReves/qualification/p08c"/stage
    raise SystemExit(main(root=root, script=Path(__file__).with_name("reliability.py"),
                          arguments=["--stage", stage]))
