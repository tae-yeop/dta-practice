"""Boltz-2 unit fixtures validate contracts, never model performance."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from dti_tool import boltz2
from dti_tool.models import ToolError


def test_boltz_missing_assets_never_trigger_download(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path))
    monkeypatch.setattr(boltz2.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Unexpected download"))
    with pytest.raises(ToolError) as failure:
        boltz2.check()
    assert failure.value.code == "MODEL_NOT_READY"


def test_boltz_pinned_manifest_and_canonical_tampering(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path))
    root = tmp_path / "Boltz2"
    (root / "mols").mkdir(parents=True)
    assets = {}
    for index, name in enumerate(boltz2.ASSETS):
        data = ("unit-fixture-" + str(index)).encode()
        (root / name).write_bytes(data)
        assets[name] = (len(data), hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(boltz2, "ASSETS", assets)
    molecules = {}
    for name in boltz2.CANONICAL:
        data = ("unit-ccd-" + name).encode()
        (root / "mols" / (name + ".pkl")).write_bytes(data)
        molecules[name + ".pkl"] = hashlib.sha256(data).hexdigest()
    interpreter = tmp_path / "python-fixture"
    interpreter.write_text("Not executable; check() only inspects readiness")
    monkeypatch.setattr(boltz2, "runtime_python", lambda: interpreter)
    manifest = {"model": "Boltz2", "revision": boltz2.HF_REVISION,
                "files": {name: item[1] for name, item in assets.items()}, "canonical_molecules": molecules}
    (root / "manifest.json").write_text(json.dumps(manifest))
    assert boltz2.check()[1] == manifest
    (root / "mols" / "ALA.pkl").write_text("changed")
    with pytest.raises(ToolError) as failure:
        boltz2.check()
    assert failure.value.code == "MODEL_INTEGRITY_ERROR"


def test_boltz_input_preserves_stereochemistry_and_forces_offline_single_sequence():
    drug = "N[C@@H](C)C(=O)O"
    data = boltz2.make_input(drug, "ACDEFGHIK")
    assert data["sequences"][1]["ligand"]["smiles"] == drug
    assert data["sequences"][0]["protein"]["msa"] == "empty"
    assert data["properties"][0]["affinity"]["binder"] == "L"


def test_boltz_input_bounds_do_not_truncate():
    assert boltz2.validate("C" * 128, "A" * 800) == 128
    for drug, sequence in [("C" * 129, "A" * 800), ("CC", "A" * 801)]:
        with pytest.raises(ToolError) as failure:
            boltz2.validate(drug, sequence)
        assert failure.value.code == "INPUT_TOO_LONG"


@pytest.fixture
def output_fixture(tmp_path):
    (tmp_path / "affinity_input.json").write_text(json.dumps({"affinity_pred_value": -1.25, "affinity_probability_binary": 0.8}))
    (tmp_path / "confidence_input_model_0.json").write_text(json.dumps({"confidence_score": 0.7, "iptm": 0.6}))
    (tmp_path / "input_model_0.cif").write_text("data_unit_test_fixture\n")
    return tmp_path


def test_boltz_output_heads_and_confidence_have_separate_semantics(output_fixture):
    result = boltz2.parse_outputs(output_fixture, 57)
    assert result["prediction"]["scale"] == "log10_IC50_uM"
    assert result["prediction"]["endpoint"] == "IC50"
    assert result["prediction"]["higher_is_stronger"] is False
    assert result["prediction"]["binding_probability"] == 0.8
    assert result["quality"]["structure_confidence"]["confidence_score"] == 0.7
    assert any("56 atoms" in message for message in result["quality"]["warnings"])
    assert result["derived"] is None and result["uncertainty"]["interval"] is None


@pytest.mark.parametrize("value,probability", [(float("nan"), 0.5), (1.0, 1.1), (True, 0.5), (1.0, "0.5")])
def test_boltz_rejects_invalid_affinity_and_probabilities(output_fixture, value, probability):
    (output_fixture / "affinity_input.json").write_text(json.dumps({"affinity_pred_value": value, "affinity_probability_binary": probability}))
    with pytest.raises(ToolError) as failure:
        boltz2.parse_outputs(output_fixture, 20)
    assert failure.value.code == "INVALID_MODEL_OUTPUT"


def test_boltz_requires_structure_artifact(output_fixture):
    (output_fixture / "input_model_0.cif").unlink()
    with pytest.raises(ToolError):
        boltz2.parse_outputs(output_fixture, 20)


@pytest.mark.skipif(os.environ.get("DTI_RUN_BOLTZ_LIVE") != "1", reason="Expensive opt-in real Boltz-2 GPU inference")
def test_live_boltz2_dhfr(monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(boltz2.PROJECT / ".model-cache"))
    arguments = json.loads((boltz2.PROJECT / "examples/requests/trimethoprim-ecoli-dhfr.json").read_text())
    result = boltz2.predict(arguments["smiles"], arguments["protein_sequence"], "cuda")
    assert result["prediction"]["binding_probability"] >= 0
    assert result["execution"]["offline"] is True
    assert result["model"]["files"]["boltz2_aff.ckpt"] == boltz2.ASSETS["boltz2_aff.ckpt"][1]
    assert Path(result["artifacts"]["complex_cif"]).is_file()
