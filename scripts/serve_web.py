"""Start the local workbench: python scripts/serve_web.py [--port 8765]."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run("dti_web.app:app", host="127.0.0.1", port=args.port, log_level="info")
