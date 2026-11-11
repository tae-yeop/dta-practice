"""Loopback-only web UI over the same recorded tool used by agents."""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import subprocess
import sys

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from dti_tool.__main__ import status
from dti_tool.models import PROJECT
from dti_tool.processes import process_options, request_timeout, terminate_process_tree
from dti_tool.runs import create_run, fail_run, get_run, list_runs, run_dir
from dti_web.examples import load_examples

STATIC = Path(__file__).parent / "static"


async def run_worker(run_id, semaphore):
    process = None
    timeout = 180
    try:
        async with semaphore:
            folder = run_dir(run_id)
            timeout = request_timeout(get_run(run_id)["request"])
            with (folder / "worker.stdout.log").open("wb") as stdout, (folder / "worker.stderr.log").open("wb") as stderr:
                process = subprocess.Popen(
                    [sys.executable, "-m", "dti_tool", "execute-run", "--id", run_id],
                    cwd=PROJECT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    **process_options(),
                )
                await asyncio.to_thread(process.wait, timeout=timeout)
            if get_run(run_id)["status"] not in {"success", "partial", "error"}:
                fail_run(run_id, "WORKER_FAILED", "Prediction worker exited without a result. See worker.stderr.log.")
    except (Exception, asyncio.CancelledError) as exc:
        if process is not None and process.poll() is None:
            await asyncio.to_thread(terminate_process_tree, process)
        if isinstance(exc, subprocess.TimeoutExpired):
            code, message = "INFERENCE_TIMEOUT", f"Inference exceeded the selected models' {timeout}-second budget."
        elif isinstance(exc, asyncio.CancelledError):
            code, message = "SERVER_STOPPED", "The web server stopped before this run completed."
        else:
            code, message = "WORKER_FAILED", str(exc)
        fail_run(run_id, code, message)
        if isinstance(exc, asyncio.CancelledError):
            raise


@asynccontextmanager
async def lifespan(app):
    app.state.tasks = set()
    app.state.semaphore = asyncio.Semaphore(1)
    yield
    tasks = list(app.state.tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


class LocalRequests(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"error": "Cross-origin requests are not allowed."}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return JSONResponse({"error": "Use application/json."}, status_code=415)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response


async def index(request):
    return FileResponse(STATIC / "index.html")


async def examples(request):
    return JSONResponse(await asyncio.to_thread(load_examples))


async def health(request):
    state = await asyncio.to_thread(status)
    return JSONResponse({**state, "skill": "predict-dta", "mode": "local_tool_workflow"})


async def history(request):
    if request.method == "GET":
        return JSONResponse({"runs": await asyncio.to_thread(list_runs)})
    if len(request.app.state.tasks) >= 8:
        return JSONResponse({"error": "실행 대기열이 가득 찼습니다. 잠시 후 다시 시도하세요."}, status_code=429)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            return JSONResponse({"error": "요청이 너무 큽니다. 최대 64 KiB입니다."}, status_code=413)
    try:
        arguments = json.loads(body)
        if not isinstance(arguments, dict):
            raise ValueError("입력은 JSON 객체여야 합니다.")
        metadata = await asyncio.to_thread(create_run, arguments, "web", True)
    except (ValueError, UnicodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    task = asyncio.create_task(run_worker(metadata["run_id"], request.app.state.semaphore))
    request.app.state.tasks.add(task)
    task.add_done_callback(request.app.state.tasks.discard)
    return JSONResponse(metadata, status_code=202)


async def detail(request):
    try:
        record = await asyncio.to_thread(get_run, request.path_params["run_id"])
    except (OSError, ValueError):
        return JSONResponse({"error": "실행 기록을 찾을 수 없습니다."}, status_code=404)
    return JSONResponse(record)


async def download(request):
    kind = request.path_params["kind"]
    files = {"result": ("result.json", "application/json"), "events": ("events.jsonl", "application/x-ndjson")}
    try:
        name, media_type = files[kind]
        path = run_dir(request.path_params["run_id"]) / name
        if not path.is_file():
            raise ValueError()
    except (KeyError, ValueError):
        return JSONResponse({"error": "다운로드할 파일이 없습니다."}, status_code=404)
    return FileResponse(path, media_type=media_type, filename=f"{request.path_params['run_id']}-{name}")


def create_app():
    app = Starlette(lifespan=lifespan, routes=[
        Route("/", index), Route("/api/status", health), Route("/api/examples", examples),
        Route("/api/runs", history, methods=["GET", "POST"]),
        Route("/api/runs/{run_id}", detail),
        Route("/api/runs/{run_id}/download/{kind}", download),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])
    app.add_middleware(LocalRequests)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    return app


app = create_app()
