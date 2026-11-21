"""Durable execution records shared by the web app, CLI, Python and MCP.

Each run has one writer and its own directory. Metadata/result updates are atomic;
events are flushed JSONL records. A skill.loaded event means the wrapper really
read the skill document, not that an LLM reasoned about it.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from .models import PROJECT

SKILL_PATH = PROJECT / "skills" / "predict-dta" / "SKILL.md"
SOURCES = {"web", "agent", "cli", "python", "mcp"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def runs_root():
    return Path(os.environ.get("DTI_RUNS_DIR", PROJECT / "runs" / "predictions")).resolve()


def run_dir(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid run ID.")
    return runs_root() / run_id


def write_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def append_event(run_id, event, component, message, **details):
    record = {"timestamp": now(), "run_id": run_id, "event": event,
              "component": component, "message": message, "details": details}
    with (run_dir(run_id) / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()


def create_run(arguments, source="cli", use_skill=False, plan=None):
    if source not in SOURCES:
        raise ValueError("Unknown request source.")
    run_id = uuid.uuid4().hex
    folder = run_dir(run_id)
    folder.mkdir(parents=True)
    write_json(folder / "request.json", arguments)
    # Publish metadata last, so readers never see a half-created request.
    append_event(run_id, "request.received", source, "예측 요청을 접수했습니다.", source=source)
    if plan is not None:
        write_json(folder / "routing.json", plan)
        append_event(run_id, "route.selected", "router", plan["reason"], purpose=plan["purpose"],
                     selected_models=plan["selected_models"], budget_seconds=plan["budget_seconds"])
    metadata = {"run_id": run_id, "source": source, "status": "queued",
                "created_at": now(), "finished_at": None, "use_skill": use_skill}
    write_json(folder / "run.json", metadata)
    return metadata


def finish_run(run_id, result):
    folder = run_dir(run_id)
    result["trace"] = {"run_id": run_id, "events_path": str(folder / "events.jsonl")}
    write_json(folder / "result.json", result)
    metadata = read_json(folder / "run.json")
    metadata.update(status=result["status"], finished_at=now(),
                    error_code=result.get("error", {}).get("code"))
    append_event(run_id, {"success": "run.completed", "partial": "run.partial", "error": "run.failed"}[result["status"]],
                 "workflow", "모델별 결과를 저장했습니다." if result["status"] != "error" else "오류 결과를 저장했습니다.",
                 status=result["status"], error_code=metadata["error_code"])
    write_json(folder / "run.json", metadata)
    return result


def fail_run(run_id, code, message):
    from .core import error_result
    append_event(run_id, "worker.failed", "workflow", message, code=code)
    return finish_run(run_id, error_result(code, message))


def execute_run(run_id):
    from .core import execute_tool, error_result
    from .profiler import profile_input
    folder = run_dir(run_id)
    metadata = read_json(folder / "run.json")
    if metadata["status"] != "queued":
        raise ValueError("Run has already been claimed or finished; create a new run to retry.")
    # Exclusive claim prevents duplicate inference if a queued job is retried.
    try:
        with (folder / "claimed").open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        raise ValueError("Run has already been claimed; create a new run to retry.")
    metadata.update(status="running", started_at=now(), pid=os.getpid())
    write_json(folder / "run.json", metadata)
    try:
        if metadata["use_skill"]:
            document = SKILL_PATH.read_bytes()
            append_event(run_id, "skill.loaded", "skill", "predict-dta 스킬 문서를 읽었습니다.",
                         name="predict-dta", path=str(SKILL_PATH),
                         sha256=hashlib.sha256(document).hexdigest(),
                         meaning="Execution wrapper loaded the skill document; this is not an LLM reasoning trace.")
        arguments = read_json(folder / "request.json")
        profile = None
        if isinstance(arguments, dict) and {"smiles", "protein_sequence"} <= arguments.keys():
            profile = profile_input(arguments["smiles"], arguments["protein_sequence"])
            write_json(folder / "input-profile.json", profile)
            valid = profile["status"] == "success"
            append_event(run_id, "profile.completed" if valid else "profile.failed", "profiler",
                         "입력 프로파일을 저장했습니다." if valid else "입력 검사에서 오류를 발견했습니다.",
                         name="profile_input", pair_id=profile.get("pair_id"), artifact="input-profile.json",
                         error_code=profile.get("error", {}).get("code"))
        append_event(run_id, "tool.started", "tool", "predict_dta 도구를 호출했습니다.", name="predict_dta",
                     selection={key: arguments[key] for key in ("model", "models") if isinstance(arguments, dict) and key in arguments})
        def model_event(phase, name, result):
            details = {"model": name, "status": "running" if result is None else result["status"]}
            if result is not None:
                details.update(error_code=result.get("error", {}).get("code"),
                               error_message=result.get("error", {}).get("message"),
                               elapsed_seconds=result["execution"]["elapsed_seconds"])
            append_event(run_id, f"model.{phase}", "model", f"{name}: {phase}", **details)
        result = execute_tool(arguments, on_model_event=model_event)
        if profile is not None:
            result["input_profile"] = {"artifact": "input-profile.json", "schema_version": profile["schema_version"],
                                       "pair_id": profile.get("pair_id"), "status": profile["status"]}
        append_event(run_id, {"success": "tool.completed", "partial": "tool.partial", "error": "tool.failed"}[result["status"]], "tool",
                     "일부 모델의 예측을 완료했습니다." if result["status"] == "partial" else
                     "예측을 완료했습니다." if result["status"] == "success" else result["error"]["message"],
                     name="predict_dta", status=result["status"],
                     error_code=result.get("error", {}).get("code"),
                     elapsed_seconds=result.get("execution", {}).get("elapsed_seconds"))
    except Exception as exc:
        result = error_result("WORKFLOW_FAILED", f"{type(exc).__name__}: {exc}")
        append_event(run_id, "workflow.failed", "workflow", result["error"]["message"])
    return finish_run(run_id, result)


def run_prediction(arguments, source="cli", use_skill=False):
    return execute_run(create_run(arguments, source, use_skill)["run_id"])


def list_runs(limit=30):
    records = []
    for path in runs_root().glob("*/run.json"):
        try:
            records.append(read_json(path))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda row: row["created_at"], reverse=True)[:limit]


def get_run(run_id):
    folder = run_dir(run_id)
    metadata = read_json(folder / "run.json")
    events = []
    # A writer may be midway through a UTF-8 character. Decode only complete
    # newline-terminated records, rather than failing the whole run lookup.
    for line in (folder / "events.jsonl").read_bytes().split(b"\n")[:-1]:
        try:
            events.append(json.loads(line.decode("utf-8")))
        except (ValueError, UnicodeError):
            pass  # A reader can catch the last line before its writer flushes.
    result = read_json(folder / "result.json") if (folder / "result.json").exists() else None
    return {**metadata, "request": read_json(folder / "request.json"), "events": events, "result": result}
