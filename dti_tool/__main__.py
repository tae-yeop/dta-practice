"""JSON CLI: python -m dti_tool {schema,status,prepare-model,predict}."""

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import sys

from .core import error_result, tool_schema
from .models import MODEL, MODELS, ToolError, check_model, model_dir, prepare_model
from .profiler import execute_profile, profile_error
from .runs import execute_run, run_prediction, SOURCES


def invoke(arguments):
    return run_prediction(arguments)


def checkpoint_status(model):
    try:
        _, manifest = check_model(model)
        checkpoint = {"status": "ready", "manifest": manifest}
    except ToolError as exc:
        checkpoint = {"status": "not_ready", "code": exc.code, "message": str(exc)}
    except ImportError as exc:
        checkpoint = {"status": "not_ready", "code": "DEPENDENCY_MISSING", "message": str(exc)}
    except OSError as exc:
        checkpoint = {"status": "not_ready", "code": "MODEL_IO_ERROR", "message": str(exc)}
    return {"model": model, **MODELS[model], "checkpoint": checkpoint, "cache_path": str(model_dir(model))}


def status(model=MODEL):
    packages = {}
    for name in ("DeepPurpose", "torch", "rdkit", "mcp"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    models = [checkpoint_status(name) for name in MODELS]
    selected = next(row for row in models if row["model"] == model)
    return {"tool": "predict_dta", "model": model, "packages": packages, "models": models,
            "checkpoint": selected["checkpoint"], "cache_path": selected["cache_path"],
            "runtime_import_check": "not_run", "live_inference_check": "not_run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="Print the tool name, description and inputSchema.")
    profile = commands.add_parser("profile", help="Inspect a pair offline without running a model.")
    profile.add_argument("--input", required=True, help="Pair or prediction request JSON path, or '-' for stdin.")
    profile.add_argument("--output", type=Path, help="Also save the profile as UTF-8 JSON.")
    status_parser = commands.add_parser("status", help="Check package versions and all checkpoint hashes.")
    status_parser.add_argument("--model", choices=list(MODELS), default=MODEL)
    prepare = commands.add_parser("prepare-model", help="Explicitly download the upstream checkpoint.")
    prepare.add_argument("--archive", type=Path, help="Import a local model bundle (DeepPurpose ZIP; other adapters may accept a prepared cache directory).")
    prepare.add_argument("--model", choices=list(MODELS), default=MODEL)
    for name in ("predict", "run"):
        predict = commands.add_parser(name, help="Offline tool execution; 'run' also records the skill document.")
        predict.add_argument("--input", required=True, help="UTF-8 JSON path, or '-' for stdin.")
        predict.add_argument("--output", type=Path, help="Also save the result as UTF-8 JSON.")
        predict.add_argument("--source", choices=sorted(SOURCES), default="cli")
    worker = commands.add_parser("execute-run", help="Internal worker: execute an already queued run once.")
    worker.add_argument("--id", required=True)
    args = parser.parse_args()
    make_error = profile_error if args.command == "profile" else error_result
    try:
        if args.command == "schema":
            result = tool_schema()
        elif args.command == "status":
            result = status(args.model)
        elif args.command == "prepare-model":
            result = {"status": "success", "model": prepare_model(args.archive, model=args.model)}
        elif args.command == "execute-run":
            result = execute_run(args.id)
        else:
            data = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
            arguments = json.loads(data)
            if args.command == "profile":
                if isinstance(arguments, dict):
                    arguments = {k: v for k, v in arguments.items() if k not in ("model", "models", "device")}
                result = execute_profile(arguments)
            else:
                result = run_prediction(arguments, source=args.source, use_skill=args.command == "run")
    except ToolError as exc:
        result = make_error(exc.code, str(exc))
    except (OSError, ValueError) as exc:
        result = make_error("INVALID_INPUT_OR_IO", str(exc))
    encoded = json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    if getattr(args, "output", None):
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        except OSError as exc:
            result = make_error("OUTPUT_WRITE_FAILED", str(exc))
            encoded = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
    sys.stdout.write(encoded)
    return {"error": 2, "partial": 3}.get(result.get("status"), 0)


if __name__ == "__main__":
    raise SystemExit(main())
