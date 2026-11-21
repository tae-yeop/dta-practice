"""Loopback-only web UI over the same recorded tool used by agents."""

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from dti_tool.__main__ import status
from dti_tool.models import PROJECT
from dti_tool.profiler import execute_profile
from dti_tool.router import execute_route
from dti_tool.profile_structures import structure_catalog
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


async def request_object(request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            return JSONResponse({"error": "요청이 너무 큽니다. 최대 64 KiB입니다."}, status_code=413)
    try:
        arguments = json.loads(body)
        if not isinstance(arguments, dict):
            raise ValueError("입력은 JSON 객체여야 합니다.")
        return arguments
    except (ValueError, UnicodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def profile(request):
    arguments = await request_object(request)
    if isinstance(arguments, JSONResponse):
        return arguments
    result = await asyncio.to_thread(execute_profile, arguments)
    response = JSONResponse(result)
    if result.get("status") == "success":
        response.headers["X-Profile-Token"] = remember(request.app.state.profiles, result)
    return response


def remember(cache, value):
    token = uuid4().hex
    cache[token] = value
    if len(cache) > 32:
        cache.popitem(last=False)
    return token


async def model_route(request):
    arguments = await request_object(request)
    if isinstance(arguments, JSONResponse):
        return arguments
    saved = request.app.state.profiles.get(request.headers.get("x-profile-token"))
    pair = {k: arguments.get(k) for k in ("smiles", "protein_sequence")}
    profile = saved if saved and saved.get("original") == pair else None
    plan = await asyncio.to_thread(execute_route, arguments, profile)
    response = JSONResponse(plan)
    if plan.get("action") == "execute":
        response.headers["X-Route-Token"] = remember(request.app.state.plans, (pair, plan))
    return response


async def history(request):
    if request.method == "GET":
        return JSONResponse({"runs": await asyncio.to_thread(list_runs)})
    if len(request.app.state.tasks) >= 8:
        return JSONResponse({"error": "실행 대기열이 가득 찼습니다. 잠시 후 다시 시도하세요."}, status_code=429)
    arguments = await request_object(request)
    if isinstance(arguments, JSONResponse):
        return arguments
    plan = None
    if "x-route-token" in request.headers:
        saved = request.app.state.plans.get(request.headers["x-route-token"])
        models = arguments.get("models", [arguments.get("model")])
        if (not saved or saved[0] != {k: arguments.get(k) for k in ("smiles", "protein_sequence")}
                or models != saved[1]["selected_models"]):
            return JSONResponse({"error": "입력과 추천 계획을 다시 확인하세요."}, status_code=409)
        plan = saved[1]
    metadata = await asyncio.to_thread(create_run, arguments, "web", True, plan)
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
    files = {"result": ("result.json", "application/json"), "events": ("events.jsonl", "application/x-ndjson"),
             "profile": ("input-profile.json", "application/json"), "route": ("routing.json", "application/json")}
    try:
        name, media_type = files[kind]
        path = run_dir(request.path_params["run_id"]) / name
        if not path.is_file():
            raise ValueError()
    except (KeyError, ValueError):
        return JSONResponse({"error": "다운로드할 파일이 없습니다."}, status_code=404)
    return FileResponse(path, media_type=media_type, filename=f"{request.path_params['run_id']}-{name}")


async def reference_structure(request):
    pdb = request.path_params["pdb"]
    if pdb not in {entry["pdb_id"] for entry in structure_catalog().values()}:
        return JSONResponse({"error": "등록된 실험 구조가 없습니다."}, status_code=404)
    path = PROJECT / "examples" / "structures" / (pdb + ".cif.gz")
    if not path.is_file():
        return JSONResponse({"error": "좌표 파일이 없습니다."}, status_code=404)
    return FileResponse(path, media_type="chemical/x-cif", headers={"Content-Encoding": "gzip"}, filename=pdb + ".cif")


def complex_path(run_id):
    result = json.loads((run_dir(run_id) / "result.json").read_bytes())
    root = Path(os.environ.get("DTI_BOLTZ_RUNS_DIR", PROJECT / "runs" / "boltz2-jobs")).resolve()
    for item in result.get("results", [result]):
        if item.get("status") != "success" or item.get("requested_model") != "Boltz2":
            continue
        raw_path = item.get("artifacts", {}).get("complex_cif")
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        parts = path.relative_to(root).parts
        if (len(parts) == 5 and re.fullmatch("[a-f0-9]{32}", parts[0])
                and parts[1:] == ("boltz_results_input", "predictions", "input", "input_model_0.cif")
                and path.is_file()):
            return path
    raise ValueError("No saved complex")


async def predicted_complex(request):
    try:
        path = await asyncio.to_thread(complex_path, request.path_params["run_id"])
    except (OSError, ValueError):
        return JSONResponse({"error": "이 실행의 복합체 좌표 파일을 찾을 수 없습니다."}, status_code=404)
    return FileResponse(path, media_type="chemical/x-cif", filename="boltz2-complex.cif")


def create_app():
    app = Starlette(lifespan=lifespan, routes=[
        Route("/", index), Route("/api/status", health), Route("/api/examples", examples),
        Route("/api/profile", profile, methods=["POST"]),
        Route("/api/route", model_route, methods=["POST"]),
        Route("/api/structures/{pdb}.cif", reference_structure),
        Route("/api/runs/{run_id}/complex.cif", predicted_complex),
        Route("/api/runs", history, methods=["GET", "POST"]),
        Route("/api/runs/{run_id}", detail),
        Route("/api/runs/{run_id}/download/{kind}", download),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])
    app.state.profiles = OrderedDict()
    app.state.plans = OrderedDict()
    app.add_middleware(LocalRequests)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    return app


app = create_app()
