"""Heterogeneous output semantics and orchestration, using explicit test fixtures."""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from dti_tool.core import _validate_adapter_output, execute_tool, validate_inputs
from dti_tool.models import PROJECT, ToolError
from dti_tool.processes import device_lock, request_timeout
from dti_tool.runs import get_run, run_prediction

PAIR = {"smiles": "N[C@@H](C)C(=O)O", "protein_sequence": "ACDEFGHIK"}


def fixture_payload():
    # Test-only values. They are never used as fallback predictions.
    return {"model": {"model": "ConPLex_v1_BindingDB"}, "execution": {"device": "cpu"},
            "task": "DTI", "prediction": {"raw_value": .25, "scale": "cosine_similarity", "endpoint": None},
            "derived": None, "quality": {"warnings": []},
            "uncertainty": {"status": "not_calibrated", "interval": None}}


def test_dti_output_is_not_relabelled_as_affinity_or_probability(monkeypatch):
    devices = []
    def predict(drug, sequence, device):
        devices.append(device)
        return fixture_payload()
    monkeypatch.setattr("dti_tool.core.adapter_module", lambda model: SimpleNamespace(predict=predict))
    result = execute_tool({**PAIR, "model": "ConPLex_v1_BindingDB", "device": "auto"})
    assert result["status"] == "success", result
    assert result["task"] == "DTI" and result["prediction"] == fixture_payload()["prediction"]
    assert "binding_probability" not in result["prediction"]
    assert result["input"]["smiles_used"] == PAIR["smiles"]
    assert result["derived"] is None and result["uncertainty"]["interval"] is None
    assert devices == ["cpu"] and result["execution"]["requested_device"] == "auto"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, None, "0.5"])
def test_nonfinite_or_nonnumeric_score_cannot_be_published(value):
    payload = fixture_payload()
    payload["prediction"]["raw_value"] = value
    with pytest.raises(ToolError):
        _validate_adapter_output(payload)


@pytest.mark.parametrize("probability", [-.1, 1.1, float("nan"), True, "0.5"])
def test_invalid_boltz_probability_cannot_be_published(probability):
    payload = fixture_payload()
    payload["prediction"]["binding_probability"] = probability
    with pytest.raises(ToolError):
        _validate_adapter_output(payload)


def test_mixed_model_progress_is_written_before_next_model_starts(monkeypatch):
    from dti_tool import core
    observed = []
    def predict(smiles, protein_sequence, model, device="cpu"):
        if observed:
            events = get_run(observed[0])["events"]
            assert any(e["event"] == "model.completed" for e in events)
        else:
            from dti_tool.runs import list_runs
            observed.append(list_runs()[0]["run_id"])
        payload = fixture_payload()
        return {"status": "success", **payload, "execution": {"elapsed_seconds": .01}}
    monkeypatch.setattr(core, "_predict_dta", predict)
    result = run_prediction({**PAIR, "models": ["ConPLex_v1_BindingDB", "Boltz2"]}, use_skill=True)
    assert result["task"] == "drug_target_comparison"
    assert result["prediction"] is None and result["aggregate"] is None
    assert [e["event"] for e in get_run(result["trace"]["run_id"])["events"]] == [
        "request.received", "skill.loaded", "profile.completed", "tool.started", "model.started", "model.completed",
        "model.started", "model.completed", "tool.completed", "run.completed"]


def test_boltz_size_policy_does_not_truncate_inputs():
    with pytest.raises(ToolError, match="800 residues"):
        validate_inputs("CCO", "A" * 801, "Boltz2", "auto")
    with pytest.raises(ToolError, match="128 heavy"):
        validate_inputs("C" * 129, "ACDEFG", "Boltz2", "auto")
    assert validate_inputs("C" * 101, "A" * 1001, "ConPLex_v1_BindingDB", "cpu")[1] == "A" * 1001


def test_device_failure_reason_is_available_while_other_models_are_running(monkeypatch):
    from dti_tool import core
    from dti_tool.runs import list_runs
    message = "CUDA is unavailable in this Python environment; use device=auto or cpu."
    def predict(smiles, protein_sequence, model, device="cpu"):
        if model == "Boltz2":
            record = get_run(list_runs()[0]["run_id"])
            assert record["status"] == "running" and record["result"] is None
            failure = next(e for e in record["events"] if e["event"] == "model.failed")
            assert failure["details"]["error_code"] == "DEVICE_UNAVAILABLE"
            assert failure["details"]["error_message"] == message
        return core.error_result("DEVICE_UNAVAILABLE", message, .01)
    monkeypatch.setattr(core, "_predict_dta", predict)
    result = run_prediction({**PAIR, "models": ["ConPLex_v1_BindingDB", "Boltz2"], "device": "cuda"})
    assert result["summary"]["failed"] == 2


def test_long_models_get_budget_and_cuda_jobs_cannot_overlap(tmp_path, monkeypatch):
    assert request_timeout({"models": ["Boltz2", "ConPLex_v1_BindingDB"]}) >= 4500
    monkeypatch.setattr("dti_tool.processes.PROJECT", tmp_path)
    script = "import sys\nfrom pathlib import Path\nimport dti_tool.processes as p\np.PROJECT=Path(sys.argv[1])\nwith p.device_lock('cuda', timeout=.1): print('acquired')"
    with device_lock("cuda"):
        child = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=PROJECT, capture_output=True, text=True, timeout=10)
        assert child.returncode != 0 and "Another project prediction" in child.stderr
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=PROJECT, capture_output=True, text=True, timeout=10)
    assert child.returncode == 0 and "acquired" in child.stdout
