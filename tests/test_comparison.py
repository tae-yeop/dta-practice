"""Model isolation, graph boundary, and comparison error contracts."""

import json
import subprocess
import sys

import pytest

from dti_tool.core import _check_graph_features, execute_tool, validate_inputs
from dti_tool.models import MODEL, MODELS, PROJECT, ToolError

MPNN = "MPNN_CNN_BindingDB"
PAIR = {"smiles": "CCO", "protein_sequence": "ACDEFGHIK"}


@pytest.mark.parametrize("smiles", ["N[C@@H](C)C(=O)O", "C" * 101, "C" * 400])
def test_graph_accepts_inputs_outside_cnn_vocabulary_and_length(smiles):
    assert validate_inputs(smiles, PAIR["protein_sequence"], MPNN, "cpu")[0] == smiles
    with pytest.raises(ToolError):
        validate_inputs(smiles, PAIR["protein_sequence"], MODEL, "cpu")


@pytest.mark.parametrize("smiles", ["C" * 401, "C1" + "C" * 399 + "1"])
def test_graph_size_limits_include_padding_slot(smiles):
    with pytest.raises(ToolError, match="400 atoms and 800"):
        validate_inputs(smiles, PAIR["protein_sequence"], MPNN, "cpu")


def test_graph_rejects_zero_fallback_and_nonfinite_features():
    import torch
    from DeepPurpose import utils
    valid = utils.smiles2mpnnfeature("CCO")
    _check_graph_features(valid, "CCO")
    invalid = [t.clone() for t in valid]
    invalid[4].zero_()
    with pytest.raises(ToolError, match="fallback/invalid"):
        _check_graph_features(invalid, "CCO")
    valid[0][0, 0] = float("nan")
    with pytest.raises(ToolError, match="fallback/invalid"):
        _check_graph_features(valid, "CCO")


@pytest.mark.parametrize("selection", [
    {"models": []}, {"models": [MODEL, MODEL]}, {"models": "CNN"},
    {"models": [MODEL], "model": MODEL}, {"models": [42]}, {"models": [None]},
])
def test_invalid_model_selection(selection):
    assert execute_tool({**PAIR, **selection})["error"]["code"] == "INVALID_ARGUMENT"


def test_comparison_is_offline_and_retains_each_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path / "empty"))
    def forbidden(*args, **kwargs):
        raise AssertionError("No downloads allowed")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    result = execute_tool({**PAIR, "models": list(MODELS)})
    assert result["status"] == "error"
    assert result["summary"] == {"succeeded": 0, "failed": len(MODELS)}
    assert result["prediction"] is None and result["aggregate"] is None
    assert [r["requested_model"] for r in result["results"]] == list(MODELS)
    assert all(r["error"]["code"] == "MODEL_NOT_READY" for r in result["results"])


def test_cli_comparison_failure_and_status_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path / "empty"))
    result = subprocess.run([sys.executable, "-m", "dti_tool", "predict", "--input", "-"],
                            input=json.dumps({**PAIR, "models": list(MODELS)}), text=True,
                            capture_output=True, cwd=PROJECT)
    assert result.returncode == 2
    assert len(json.loads(result.stdout)["results"]) == len(MODELS)
    result = subprocess.run([sys.executable, "-m", "dti_tool", "status", "--model", MPNN],
                            text=True, capture_output=True, cwd=PROJECT)
    catalog = json.loads(result.stdout)
    assert catalog["model"] == MPNN
    assert [m["model"] for m in catalog["models"]] == list(MODELS)
    assert all(m["checkpoint"]["status"] == "not_ready" for m in catalog["models"])
