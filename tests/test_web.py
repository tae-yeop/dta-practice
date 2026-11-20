"""Integration checks through real HTTP handlers and prediction subprocesses."""

import json
import time

import pytest
from starlette.testclient import TestClient

from dti_tool.runs import create_run, execute_run, get_run, run_prediction, run_dir, SKILL_PATH
from dti_tool.models import sha256
from dti_web.app import create_app

PAIR = {"smiles": "CCO", "protein_sequence": "ACDEFGHIK"}


def wait_result(client, run_id):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"success", "partial", "error"}:
            return run
        time.sleep(.05)
    pytest.fail("Worker did not finish in 25 seconds")


def test_web_runs_real_tool_and_downloads_failure_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path / "empty-model-cache"))
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/status").json()["checkpoint"]["status"] == "not_ready"
        queued = client.post("/api/runs", json=PAIR)
        assert queued.status_code == 202
        run_id = queued.json()["run_id"]
        run = wait_result(client, run_id)
        assert run["result"]["error"]["code"] == "MODEL_NOT_READY"
        assert run["result"]["prediction"] is None
        assert run["request"] == PAIR
        assert [event["event"] for event in run["events"]] == [
            "request.received", "skill.loaded", "profile.completed", "tool.started", "tool.failed", "run.failed"]
        assert run["events"][1]["details"]["sha256"] == sha256(SKILL_PATH)
        result = client.get(f"/api/runs/{run_id}/download/result")
        assert result.json() == run["result"]
        events = client.get(f"/api/runs/{run_id}/download/events").text.splitlines()
        assert [json.loads(line) for line in events] == run["events"]
        saved = client.get(f"/api/runs/{run_id}/download/profile").json()
        assert run["result"]["input_profile"]["pair_id"] == saved["pair_id"]
        assert client.post("/api/profile", json=PAIR).json() == saved
        assert client.get("/api/runs").json()["runs"][0]["run_id"] == run_id
        assert client.get("/api/runs/invalid").status_code == 404
        assert client.get(f"/api/runs/{run_id}/download/request").status_code == 404
        assert client.get(f"/api/runs/{run_id}/download/..%2F..%2FREADME.md").status_code == 404


def test_agent_skill_run_appears_in_web_and_cannot_execute_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path / "empty-model-cache"))
    result = run_prediction(PAIR, source="agent", use_skill=True)
    run_id = result["trace"]["run_id"]
    with TestClient(create_app()) as client:
        record = client.get(f"/api/runs/{run_id}").json()
        assert record["source"] == "agent"
        assert record["result"] == result
    with pytest.raises(ValueError, match="already been claimed"):
        execute_run(run_id)
    assert get_run(run_id)["result"] == result


def test_direct_tool_does_not_claim_skill_use():
    result = run_prediction({"unexpected": True})
    events = get_run(result["trace"]["run_id"])["events"]
    assert "skill.loaded" not in [event["event"] for event in events]
    assert "tool.failed" in [event["event"] for event in events]


def test_local_api_rejects_cross_origin_bad_hosts_and_oversized_bodies():
    with TestClient(create_app()) as client:
        assert client.post("/api/runs", json=PAIR, headers={"Origin": "https://example.com"}).status_code == 403
        assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
        assert client.post("/api/runs", content="x").status_code == 415
        assert client.post("/api/runs", content="{", headers={"Content-Type": "application/json"}).status_code == 400
        assert client.post("/api/runs", json=[]).status_code == 400
        assert client.post("/api/runs", json={"smiles": "x" * 66000}).status_code == 413
        assert client.get("/api/runs").json() == {"runs": []}


def test_standalone_web_profile_reports_errors_without_creating_runs():
    with TestClient(create_app()) as client:
        assert client.post("/api/profile", json=PAIR).json()["models"]["Boltz2"]["eligible"]
        invalid = client.post("/api/profile", json={**PAIR, "protein_sequence": ">header"}).json()
        assert invalid["errors"][0]["field"] == "protein_sequence"
        assert client.post("/api/profile", json=[]).status_code == 400
        assert client.post("/api/profile", json={**PAIR, "smiles": "C" * 66000}).status_code == 413
        assert client.get("/api/runs").json() == {"runs": []}


def test_worker_spawn_failure_persists_terminal_error(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("test-only spawn failure")
    monkeypatch.setattr("dti_web.app.subprocess.Popen", fail)
    with TestClient(create_app()) as client:
        queued = client.post("/api/runs", json=PAIR).json()
        run = wait_result(client, queued["run_id"])
        assert run["result"]["error"]["code"] == "WORKER_FAILED"
        assert not any(event["event"] == "tool.completed" for event in run["events"])


def test_reading_trace_during_partial_utf8_append():
    run_id = create_run(PAIR)["run_id"]
    path = run_dir(run_id) / "events.jsonl"
    with path.open("ab") as handle:
        handle.write(b'{"message":"' + "예".encode("utf-8")[:2])
    record = get_run(run_id)
    assert record["status"] == "queued"
    assert len(record["events"]) == 1
