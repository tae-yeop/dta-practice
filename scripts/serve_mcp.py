"""Expose predict_dta over MCP stdio; run inference in its isolated environment."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from dti_tool.core import error_result, tool_schema
from dti_tool.profiler import profile_error, profile_schema
from dti_tool.router import route_schema, route_error
from dti_tool.runs import create_run, fail_run
from dti_tool.processes import process_options, request_timeout, terminate_process_tree
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

server = Server("dti-agent")
worker_lock = asyncio.Lock()
DEFAULT_PYTHON = PROJECT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_worker(arguments):
    python = os.environ.get("DTI_INFERENCE_PYTHON", str(DEFAULT_PYTHON))
    run_id = create_run(arguments, source="mcp", use_skill=True)["run_id"]
    process = None
    timeout = request_timeout(arguments)
    try:
        process = subprocess.Popen(
            [python, "-m", "dti_tool", "execute-run", "--id", run_id],
            cwd=PROJECT, text=True, stdin=subprocess.DEVNULL,
            encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **process_options(),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        stdout, stderr = process.communicate(timeout=timeout)
        if stderr:
            print(stderr, file=sys.stderr, end="")
        result = json.loads(stdout)
        if result.get("status") not in {"success", "partial", "error"}:
            raise ValueError("Worker returned an invalid envelope.")
        if process.returncode != {"success": 0, "partial": 3, "error": 2}[result["status"]]:
            raise ValueError("Worker failed without an error envelope.")
        return result
    except subprocess.TimeoutExpired:
        if process is not None:
            terminate_process_tree(process)
        return fail_run(run_id, "INFERENCE_TIMEOUT", f"Inference exceeded the selected models' {timeout}-second budget.")
    except (OSError, ValueError, AttributeError) as exc:
        return fail_run(run_id, "WORKER_FAILED", str(exc))


@server.list_tools()
async def list_tools():
    return [Tool(**schema(), annotations=ToolAnnotations(readOnlyHint=schema is route_schema, destructiveHint=False,
                                                         openWorldHint=schema is profile_schema))
            for schema in (tool_schema, profile_schema, route_schema)]


def observation_worker(name, arguments):
    schema = (profile_schema if name == "profile_input" else route_schema)()["inputSchema"]
    if (not isinstance(arguments, dict) or not set(schema["required"]) <= arguments.keys()
            or arguments.keys() - schema["properties"].keys()):
        return profile_error("INVALID_ARGUMENT", "Invalid profile fields.") if name == "profile_input" else route_error("Invalid route fields.")
    python = os.environ.get("DTI_INFERENCE_PYTHON", str(DEFAULT_PYTHON))
    try:
        command = "profile" if name == "profile_input" else "route"
        worker = subprocess.run([python, "-m", "dti_tool", command, "--input", "-"], cwd=PROJECT,
                                input=json.dumps(arguments), text=True, encoding="utf-8", capture_output=True,
                                timeout=180, **process_options())
        result = json.loads(worker.stdout)
        if worker.returncode != {"success": 0, "error": 2}[result["status"]] or result["tool"] != name:
            raise ValueError("Unexpected profile worker response.")
        return result
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
        return profile_error("PROFILE_WORKER_FAILED", str(exc)) if name == "profile_input" else route_error(str(exc))


@server.call_tool(validate_input=False)
async def call_tool(name, arguments):
    # The CLI applies the same validation and JSON error envelope for all clients.
    if name in ("profile_input", "route_models"):
        result = await asyncio.to_thread(observation_worker, name, arguments)
    elif name != "predict_dta":
        result = error_result("UNKNOWN_TOOL", f"Unknown tool: {name}")
    else:
        async with worker_lock:
            result = await asyncio.to_thread(run_worker, arguments)
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))],
                          structuredContent=result, isError=result["status"] == "error")


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
