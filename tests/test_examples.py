"""Check scientific input identity, UI delivery and real pretrained examples."""

import json
import os

import pytest
from rdkit import Chem
from starlette.testclient import TestClient

from dti_tool.core import validate_inputs
from dti_tool.models import MODEL, DEEPPURPOSE_MODELS, PROJECT
from dti_tool.runs import run_prediction
from dti_web.app import create_app
from dti_web.examples import load_examples

EXAMPLES = load_examples()["examples"]


def test_catalog_is_available_offline_and_does_not_include_reference_scores():
    with TestClient(create_app()) as client:
        response = client.get("/api/examples")
        assert response.status_code == 200
        data = response.json()
    assert len(data["examples"]) == 12
    assert len({example["id"] for example in data["examples"]}) == 12
    for example in data["examples"]:
        assert example["reference_affinity"] is None
        assert example["target"]["sequence_scope"] == "full_length_canonical"
        assert example["evidence_url"].startswith("https://")


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda row: row["id"])
def test_examples_preserve_compound_identity_and_fit_model(example):
    arguments = example["input"]
    drug, sequence, _ = validate_inputs(arguments["smiles"], arguments["protein_sequence"], MODEL, "cpu")
    assert Chem.MolToInchiKey(Chem.MolFromSmiles(drug)) == example["compound"]["inchikey"]
    assert len(sequence) == example["target"]["sequence_length"]
    request = json.loads((PROJECT / "examples" / "requests" / (example["id"] + ".json")).read_text())
    assert request == arguments


@pytest.mark.skipif(os.environ.get("DTI_RUN_LIVE") != "1", reason="Opt-in official pretrained checkpoint test")
@pytest.mark.parametrize("example", EXAMPLES, ids=lambda row: row["id"])
@pytest.mark.parametrize("model", list(DEEPPURPOSE_MODELS))
def test_live_pretrained_examples(example, model, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(PROJECT / ".model-cache"))
    result = run_prediction({**example["input"], "model": model}, source="cli", use_skill=True)
    identity_file = "checkpoint-cnn-bindingdb.json" if model == MODEL else "checkpoint-mpnn-bindingdb.json"
    identity = json.loads((PROJECT / "docs" / identity_file).read_text())
    assert result["status"] == "success", result
    assert result["model"]["files"] == identity["files_sha256"]
    assert result["prediction"]["raw_value"] is not None
    assert result["input"]["truncated"] is False
    assert result["uncertainty"]["interval"] is None
