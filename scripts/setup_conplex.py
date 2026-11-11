"""Explicit ConPLex setup. Install requirements/models/conplex.txt into .venv-conplex first."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dti_tool.conplex import prepare

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--archive", type=Path, help="Official ConPLex .pt checkpoint already downloaded.")
parser.add_argument("--local-protbert", type=Path, help="Reuse only pytorch_model.bin after official LFS SHA-256 verification.")
args = parser.parse_args()
print(json.dumps(prepare(args.archive, protbert_dir=args.local_protbert), indent=2))
