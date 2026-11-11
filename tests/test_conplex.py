"""ConPLex integrity boundaries and opt-in real pretrained inference."""

import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dti_tool import conplex
from dti_tool.models import PROJECT, ToolError


def test_conplex_missing_weights_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("Inference must never download")
    monkeypatch.setattr(conplex.urllib.request, "urlopen", forbidden)
    with pytest.raises(ToolError) as error:
        conplex.predict("CCO", "ACDEFGHIK", "cpu")
    assert error.value.code == "MODEL_NOT_READY"


def test_conplex_rejects_manifest_paths_outside_artifact_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path))
    root = tmp_path / conplex.NAME
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"model": conplex.NAME, "files": {"../outside": "x"}}))
    with pytest.raises(ToolError) as error:
        conplex.check()
    assert error.value.code == "MODEL_INTEGRITY_ERROR"


def test_conplex_cached_hash_is_rechecked_after_file_changes(tmp_path):
    path = tmp_path / "weights"
    path.write_bytes(b"verified")
    expected = conplex.sha256(path)
    conplex._verified_hash(path, expected)
    path.write_bytes(b"modified checkpoint")
    with pytest.raises(ValueError, match="hash mismatch"):
        conplex._verified_hash(path, expected)


def test_conplex_propagates_device_error_from_isolated_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(conplex, "PROJECT", tmp_path)
    monkeypatch.setattr(conplex, "check", lambda: (tmp_path, {}))
    def fail_device(command, **kwargs):
        request = json.loads(Path(command[-1]).read_text())
        Path(request["output"]).write_text(json.dumps({"error": {
            "code": "DEVICE_UNAVAILABLE", "message": "CUDA is unavailable in the ConPLex Python environment."}}))
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(conplex.subprocess, "run", fail_device)
    with pytest.raises(ToolError) as error:
        conplex.predict("CCO", "ACDEFGHIK", "cuda")
    assert error.value.code == "DEVICE_UNAVAILABLE"
    assert "ConPLex Python environment" in str(error.value)


@pytest.mark.skipif(os.environ.get("DTI_RUN_CONPLEX_LIVE") != "1", reason="Opt-in actual ConPLex+ProtBert inference")
def test_conplex_official_cpu_prediction(monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(PROJECT / ".model-cache"))
    example = json.loads((PROJECT / "examples" / "requests" / "trimethoprim-ecoli-dhfr.json").read_text())
    result = conplex.predict(example["smiles"], example["protein_sequence"], "cpu")
    assert result["task"] == "DTI"
    assert result["prediction"]["scale"] == "cosine_similarity"
    assert math.isfinite(result["prediction"]["raw_value"])
    assert 0 <= result["prediction"]["raw_value"] <= 1
    assert result["derived"] is None
    assert result["uncertainty"]["interval"] is None
    assert result["execution"]["offline"] is True
    assert result["model"]["files"]["prot_bert/pytorch_model.bin"] == conplex.PROTBERT_SHA256
