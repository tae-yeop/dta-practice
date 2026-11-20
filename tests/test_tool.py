"""Contract tests. Synthetic weights test plumbing, never biological accuracy."""

import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import zipfile

import pytest

from dti_tool import predict_dta
from dti_tool.__main__ import invoke
from dti_tool.core import _PrimitiveConfigUnpickler, validate_inputs
from dti_tool.models import MODEL, MODELS, DEEPPURPOSE_MODELS, PROJECT, ToolError, check_model, prepare_model, sha256

SEQ = "MKTAYIAKQRQISFVKSHFSRQDILDLWIYHTQGYFPQ"
DRUG = "CC(=O)Oc1ccccc1C(=O)O"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path / "cache"))


@pytest.mark.parametrize("args,code", [
    ({"smiles": "invalid", "protein_sequence": SEQ}, "INVALID_SMILES"),
    ({"smiles": "C" * 101, "protein_sequence": SEQ}, "INPUT_TOO_LONG"),
    ({"smiles": DRUG, "protein_sequence": "A" * 1001}, "INPUT_TOO_LONG"),
    ({"smiles": DRUG, "protein_sequence": ">header\n" + SEQ}, "UNSUPPORTED_SEQUENCE"),
    ({"smiles": DRUG, "protein_sequence": "AXA"}, "UNSUPPORTED_SEQUENCE"),
    ({"smiles": "CCO.[Na+]", "protein_sequence": SEQ}, "UNSUPPORTED_MOLECULE"),
    ({"smiles": "*CC", "protein_sequence": SEQ}, "UNSUPPORTED_MOLECULE"),
    ({"smiles": "N[C@@H](C)C(=O)O", "protein_sequence": SEQ}, "UNSUPPORTED_SMILES_TOKEN"),
    ({"smiles": 12, "protein_sequence": SEQ}, "INVALID_ARGUMENT"),
    ({"smiles": DRUG, "protein_sequence": SEQ, "model": "Boltz-2"}, "UNSUPPORTED_MODEL"),
    ({"smiles": DRUG, "protein_sequence": SEQ, "extra": True}, "INVALID_ARGUMENT"),
    ({"smiles": DRUG}, "INVALID_ARGUMENT"),
    ([DRUG, SEQ], "INVALID_ARGUMENT"),
])
def test_bad_inputs_never_produce_predictions(args, code):
    result = invoke(args)
    assert result["status"] == "error"
    assert result["prediction"] is None
    assert result["error"]["code"] == code


def test_normalization_retains_smiles_representation():
    drug, sequence, canonical = validate_inputs(" " + DRUG + " ", SEQ.lower() + "\n", MODEL, "cpu")
    assert drug == DRUG
    assert sequence == SEQ
    assert canonical


def test_missing_checkpoint_fails_without_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Inference must never initiate a download")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    result = predict_dta(DRUG, SEQ)
    assert result["error"]["code"] == "MODEL_NOT_READY"
    assert result["prediction"] is None


def test_cli_json_and_nonzero_exit_for_error(tmp_path):
    completed = subprocess.run([sys.executable, "-m", "dti_tool", "predict", "--input", "-",
                                "--output", str(tmp_path / "result.json")],
                               input=json.dumps({"smiles": DRUG, "protein_sequence": SEQ}),
                               text=True, capture_output=True, cwd=PROJECT)
    result = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert result == json.loads((tmp_path / "result.json").read_text())
    assert result["error"]["code"] == "MODEL_NOT_READY"


def test_archive_uses_only_expected_members_and_detects_tampering(tmp_path):
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nested/config.pkl", pickle.dumps({"binary": False}))
        bundle.writestr("nested/model.pt", b"not-a-model-test-only")
        bundle.writestr("../unexpected.txt", "must not be extracted")
    manifest = prepare_model(archive)
    folder, loaded = check_model()
    assert loaded == manifest
    assert manifest["acquisition"] == "local_archive"
    assert not (folder.parent / "unexpected.txt").exists()
    (folder / "model.pt").write_bytes(b"changed")
    with pytest.raises(ToolError, match="hash mismatch"):
        check_model()


def test_pickle_config_cannot_resolve_python_globals(tmp_path):
    path = tmp_path / "config.pkl"
    path.write_bytes(pickle.dumps(Path))
    with path.open("rb") as handle, pytest.raises(ToolError, match="Non-primitive"):
        _PrimitiveConfigUnpickler(handle).load()


def test_interrupted_checkpoint_copy_can_be_retried(tmp_path, monkeypatch):
    from dti_tool import models
    archive = tmp_path / "copy-test.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("config.pkl", pickle.dumps({"binary": False}))
        bundle.writestr("model.pt", b"setup-fixture-only")
    original = models.shutil.copyfile
    def interrupted(source, destination):
        if Path(destination).name == "model.pt" and Path(destination).parent.name.startswith(".prepare-"):
            raise OSError("test-only interrupted copy")
        return original(source, destination)
    with monkeypatch.context() as patch:
        patch.setattr(models.shutil, "copyfile", interrupted)
        with pytest.raises(OSError, match="interrupted copy"):
            prepare_model(archive)
    assert not models.model_dir().exists()
    manifest = prepare_model(archive)
    assert check_model()[1] == manifest


@pytest.mark.parametrize("model", list(DEEPPURPOSE_MODELS))
def test_full_adapter_loads_exact_synthetic_weights(tmp_path, model):
    """Known constant checkpoint: proves actual state loading, not model accuracy."""
    import torch
    from DeepPurpose import DTI, utils
    config = utils.generate_config(drug_encoding=MODELS[model]["drug_encoding"], target_encoding="CNN",
                                   cls_hidden_dims=[8], hidden_dim_drug=8, hidden_dim_protein=8,
                                   result_folder=str(tmp_path), batch_size=1)
    config["binary"] = False
    net = DTI.model_initialize(**config)
    state = net.model.state_dict()
    for tensor in state.values():
        tensor.zero_()
    state["predictor.1.bias"].fill_(7.25)
    torch.save(state, tmp_path / "model.pt")
    (tmp_path / "config.pkl").write_bytes(pickle.dumps(config))
    with zipfile.ZipFile(tmp_path / "synthetic.zip", "w") as bundle:
        bundle.write(tmp_path / "model.pt", "test/model.pt")
        bundle.write(tmp_path / "config.pkl", "test/config.pkl")
    prepare_model(tmp_path / "synthetic.zip", model=model)
    first = predict_dta(DRUG, SEQ, model=model)
    assert first["status"] == "success", first
    assert first["prediction"]["raw_value"] == pytest.approx(7.25)
    assert first["derived"] is None
    assert first["uncertainty"]["interval"] is None
    assert first["input"]["truncated"] is False
    second = predict_dta(DRUG, SEQ, model=model)
    assert second["prediction"] == first["prediction"]
    assert first["model"]["files"]["model.pt"] == sha256(tmp_path / "model.pt")

    # The same isolated synthetic checkpoint also exercises the complete web
    # worker/result/trace path. It never enters the user's model cache/history.
    from starlette.testclient import TestClient
    from dti_web.app import create_app
    import time
    with TestClient(create_app()) as client:
        queued = client.post("/api/runs", json={"smiles": DRUG, "protein_sequence": SEQ, "model": model}).json()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            record = client.get("/api/runs/" + queued["run_id"]).json()
            if record["status"] in {"success", "error"}:
                break
            time.sleep(.1)
        assert record["status"] == "success", record
        assert record["result"]["prediction"]["raw_value"] == pytest.approx(7.25)
        assert record["result"]["uncertainty"]["interval"] is None
        assert [event["event"] for event in record["events"]] == [
            "request.received", "skill.loaded", "profile.completed", "tool.started", "tool.completed", "run.completed"]

        # One installed model must not hide the failure of the other.
        queued = client.post("/api/runs", json={"smiles": DRUG, "protein_sequence": SEQ, "models": list(DEEPPURPOSE_MODELS)}).json()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            record = client.get("/api/runs/" + queued["run_id"]).json()
            if record["status"] in {"success", "partial", "error"}:
                break
            time.sleep(.1)
        assert record["status"] == "partial", record
        assert record["result"]["aggregate"] is None
        assert record["result"]["summary"] == {"succeeded": 1, "failed": 1}
        assert [r["requested_model"] for r in record["result"]["results"]] == list(DEEPPURPOSE_MODELS)
        assert [e["event"] for e in record["events"]][-2:] == ["tool.partial", "run.partial"]
        assert sum(e["event"] == "model.failed" for e in record["events"]) == 1

    if model == "MPNN_CNN_BindingDB":
        # The installed adapter must force CPU even when upstream's global says CUDA.
        from DeepPurpose import encoders
        previous = encoders.device
        encoders.device = torch.device("cuda")
        try:
            assert predict_dta(DRUG, SEQ, model=model)["status"] == "success"
            assert str(encoders.device) == "cuda"
        finally:
            encoders.device = previous

        # Both official architectures, fixed test weights, separate caches.
        cnn_config = utils.generate_config(drug_encoding="CNN", target_encoding="CNN",
                                           cls_hidden_dims=[8], hidden_dim_drug=8, hidden_dim_protein=8,
                                           result_folder=str(tmp_path), batch_size=1)
        cnn_config["binary"] = False
        cnn = DTI.model_initialize(**cnn_config)
        cnn_state = cnn.model.state_dict()
        for tensor in cnn_state.values():
            tensor.zero_()
        cnn_state["predictor.1.bias"].fill_(5.5)
        torch.save(cnn_state, tmp_path / "cnn.pt")
        (tmp_path / "cnn.pkl").write_bytes(pickle.dumps(cnn_config))
        with zipfile.ZipFile(tmp_path / "cnn.zip", "w") as bundle:
            bundle.write(tmp_path / "cnn.pt", "model.pt")
            bundle.write(tmp_path / "cnn.pkl", "config.pkl")
        prepare_model(tmp_path / "cnn.zip", model=MODEL)
        comparison = predict_dta(DRUG, SEQ, models=list(DEEPPURPOSE_MODELS))
        assert comparison["status"] == "success", comparison
        assert comparison["prediction"] is None and comparison["aggregate"] is None
        assert [r["prediction"]["raw_value"] for r in comparison["results"]] == [5.5, 7.25]
        assert len({r["model"]["files"]["model.pt"] for r in comparison["results"]}) == 2

        # CLI uses a distinct nonzero exit code for partial success.
        completed = subprocess.run([sys.executable, "-m", "dti_tool", "predict", "--input", "-"],
                                   input=json.dumps({"smiles": "N[C@@H](C)C(=O)O", "protein_sequence": SEQ,
                                                     "models": list(DEEPPURPOSE_MODELS)}), text=True, capture_output=True, cwd=PROJECT)
        assert completed.returncode == 3, completed.stdout
        assert json.loads(completed.stdout)["status"] == "partial"

    # Missing tensors must fail instead of leaving initialized parameters in use.
    del state["predictor.1.bias"]
    folder, manifest = check_model(model)
    torch.save(state, folder / "model.pt")
    manifest["files"]["model.pt"] = sha256(folder / "model.pt")
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    failed = predict_dta(DRUG, SEQ, model=model)
    assert failed["status"] == "error" and failed["prediction"] is None


@pytest.mark.skipif(os.environ.get("DTI_RUN_LIVE") != "1", reason="Requires official pretrained checkpoint; opt in with DTI_RUN_LIVE=1")
@pytest.mark.parametrize("model", list(DEEPPURPOSE_MODELS))
def test_live_pretrained_prediction(monkeypatch, model):
    monkeypatch.setenv("DTI_MODEL_CACHE", os.environ.get("DTI_LIVE_MODEL_CACHE", str(PROJECT / ".model-cache")))
    first = predict_dta(DRUG, SEQ, model=model)
    assert first["status"] == "success", first
    identity_file = "checkpoint-cnn-bindingdb.json" if model == MODEL else "checkpoint-mpnn-bindingdb.json"
    identity = json.loads((PROJECT / "docs" / identity_file).read_text())
    assert first["model"]["files"] == identity["files_sha256"], "Live inference must use the exact verified official checkpoint."
    assert first["model"]["archive_sha256"] == identity["archive_sha256"]
    second = predict_dta(DRUG, SEQ, model=model)
    assert first["prediction"]["raw_value"] == pytest.approx(second["prediction"]["raw_value"], abs=1e-6)
