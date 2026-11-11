"""Validation, DeepPurpose inference, and the public result contract."""

from contextlib import redirect_stdout
import hashlib
from importlib.metadata import version
import json
import math
import pickle
import platform
import sys
import threading
import time

from . import __version__
from .models import MODEL, MODELS, ToolError, adapter_module, check_model, model_spec, sha256
from .processes import device_lock

AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
# DeepPurpose 0.1.5 CNN vocabulary, excluding its '?' padding/unknown token.
SMILES_CHARS = frozenset("#%)(+-.1032547698=ACBEDGFIHKMLONPSRUTWVY[Z]_acbedgfihmlonsruty")
_INFERENCE_LOCK = threading.Lock()


def tool_schema():
    return {
        "name": "predict_dta",
        "description": "Predict one SMILES/protein pair with local CNN/MPNN DTA, ConPLex DTI, or Boltz-2 structure/affinity models. Select model or models for sequential comparison. Offline inference; distinct output scales, no aggregate or conformal interval.",
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["smiles", "protein_sequence"],
            "properties": {
                "smiles": {"type": "string", "minLength": 1, "description": "One connected molecule. Model-specific size and vocabulary limits apply; no salt stripping or stereochemistry removal."},
                "protein_sequence": {"type": "string", "minLength": 1, "description": "Plain single-chain sequence, 20 canonical amino acids. Local adapter caps: CNN/MPNN 1000, ConPLex 1022, Boltz-2 800 residues; no automatic truncation."},
                "model": {"type": "string", "enum": list(MODELS), "default": MODEL},
                "models": {"type": "array", "items": {"type": "string", "enum": list(MODELS)},
                           "minItems": 1, "maxItems": len(MODELS), "uniqueItems": True,
                           "description": "Compare selected models sequentially; mutually exclusive with model. Each result retains its own status."},
                "device": {"type": "string", "enum": ["cpu", "cuda", "auto"], "default": "cpu",
                           "description": "auto uses each adapter's default (Boltz-2 CUDA, others CPU). Explicit cpu/cuda is never silently changed."},
            },
        },
    }


def error_result(code, message, elapsed=0):
    return {"schema_version": "1.0", "tool": "predict_dta", "status": "error",
            "prediction": None, "error": {"code": code, "message": message},
            "execution": {"elapsed_seconds": round(elapsed, 4)}}


def validate_inputs(smiles, protein_sequence, model, device):
    spec = model_spec(model)
    if not isinstance(device, str) or device not in {"cpu", "cuda", "auto"}:
        raise ToolError("INVALID_ARGUMENT", "device must be cpu, cuda or auto.")
    if not isinstance(smiles, str) or not isinstance(protein_sequence, str):
        raise ToolError("INVALID_ARGUMENT", "smiles and protein_sequence must be strings.")
    drug = smiles.strip()
    sequence = "".join(protein_sequence.split()).upper()
    if not drug or not sequence:
        raise ToolError("INVALID_ARGUMENT", "Both SMILES and protein sequence are required.")
    sequence_limit = spec["limits"]["protein_residues"]
    if len(sequence) > sequence_limit:
        raise ToolError("INPUT_TOO_LONG", f"{model} adapter limit: {sequence_limit} residues. No automatic truncation is performed.")
    if spec["drug_encoding"] == "CNN" and len(drug) > 100:
        raise ToolError("INPUT_TOO_LONG", "Drug CNN limit: 100 SMILES characters. No automatic truncation is performed.")
    if set(sequence) - AMINO_ACIDS:
        raise ToolError("UNSUPPORTED_SEQUENCE", "Use a plain sequence of the 20 canonical amino acids; do not include a FASTA header or ambiguous residues.")
    from rdkit import Chem
    from rdkit import rdBase
    with rdBase.BlockLogs():
        molecule = Chem.MolFromSmiles(drug)
    if molecule is None or molecule.GetNumAtoms() == 0:
        raise ToolError("INVALID_SMILES", "RDKit could not parse and sanitize this SMILES.")
    if len(Chem.GetMolFrags(molecule)) != 1 or any(atom.GetAtomicNum() == 0 for atom in molecule.GetAtoms()):
        raise ToolError("UNSUPPORTED_MOLECULE", "This first tool supports a single connected molecule without wildcard atoms. Salt stripping is not automatic.")
    if "heavy_atoms" in spec["limits"] and molecule.GetNumHeavyAtoms() > spec["limits"]["heavy_atoms"]:
        raise ToolError("INPUT_TOO_LONG", f"{model} accepts at most {spec['limits']['heavy_atoms']} heavy ligand atoms.")
    if spec["drug_encoding"] == "CNN" and set(drug) - SMILES_CHARS:
        raise ToolError("UNSUPPORTED_SMILES_TOKEN", "The SMILES contains characters unsupported by this checkpoint's CNN vocabulary.")
    if spec["drug_encoding"] == "MPNN":
        limits = spec["limits"]
        if molecule.GetNumAtoms() > limits["atoms"] or 2 * molecule.GetNumBonds() + 1 > limits["directed_bond_slots"]:
            raise ToolError("INPUT_TOO_LONG", "MPNN limits: 400 atoms and 800 directed bond slots (2 per bond + 1 padding). No truncation is performed.")
        if any(atom.GetDegree() > limits["neighbors"] for atom in molecule.GetAtoms()):
            raise ToolError("UNSUPPORTED_MOLECULE", "MPNN supports at most 6 neighbors per atom.")
    return drug, sequence, Chem.MolToSmiles(molecule, isomericSmiles=True)


class _PrimitiveConfigUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise ToolError("UNSUPPORTED_CHECKPOINT_CONFIG", f"Non-primitive pickle content is not accepted: {module}.{name}")


def _check_graph_features(features, drug):
    """Reject upstream zero-vector fallback before it can reach the network."""
    import torch
    from rdkit import Chem
    molecule = Chem.MolFromSmiles(drug)
    expected = [molecule.GetNumAtoms(), 2 * molecule.GetNumBonds() + 1]
    shapes = [(400, 39), (800, 50), (400, 6), (800, 6), (1, 2)]
    if (not isinstance(features, (list, tuple)) or len(features) != 5
            or any(not isinstance(t, torch.Tensor) or tuple(t.shape) != shape or not torch.isfinite(t).all()
                   for t, shape in zip(features, shapes))
            or features[4].flatten().tolist() != expected
            or not features[0][:expected[0]].abs().sum()):
        raise ToolError("GRAPH_ENCODING_FAILED", "MPNN graph encoding failed or returned fallback/invalid features; prediction was stopped.")


def _run_model(drug, sequence, device, model=MODEL):
    spec = model_spec(model)
    folder, manifest = check_model(model)
    import numpy as np
    import torch
    from DeepPurpose import DTI, utils, encoders, chemutils

    if version("DeepPurpose") != "0.1.5":
        raise ToolError("UNSUPPORTED_RUNTIME", "This adapter is validated against DeepPurpose 0.1.5.")
    if (utils.MAX_SEQ_DRUG, utils.MAX_SEQ_PROTEIN) != (100, 1000):
        raise ToolError("UNSUPPORTED_RUNTIME", "Upstream CNN input limits have changed.")
    if spec["drug_encoding"] == "MPNN" and (utils.MAX_ATOM, utils.MAX_BOND, chemutils.MAX_NB) != (400, 800, 6):
        raise ToolError("UNSUPPORTED_RUNTIME", "Expected DeepPurpose 0.1.5 MPNN limits: 400 atoms, 800 bond slots, 6 neighbors.")
    if device == "cuda" and not torch.cuda.is_available():
        raise ToolError("DEVICE_UNAVAILABLE", "CUDA is unavailable in this Python environment; use device=auto or cpu, or install a compatible CUDA PyTorch build.")
    with (folder / "config.pkl").open("rb") as handle:
        config = _PrimitiveConfigUnpickler(handle).load()
    if not isinstance(config, dict) or config.get("drug_encoding") != spec["drug_encoding"] or config.get("target_encoding") != spec["target_encoding"] or config.get("binary") is not False:
        raise ToolError("UNSUPPORTED_CHECKPOINT_CONFIG", f"Expected a {spec['drug_encoding']}/CNN regression checkpoint with binary=False.")
    # Build the original architecture, but bypass upstream unsafe/default loading
    # and multiprocessing. Every parameter must be provided by the checkpoint.
    config.update(batch_size=1, num_workers=0, result_folder=str(folder))
    net = DTI.model_initialize(**config)
    state = torch.load(folder / "model.pt", map_location="cpu", weights_only=True)
    if state and all(key.startswith("module.") for key in state):
        state = {key[7:]: value for key, value in state.items()}
    net.model.load_state_dict(state, strict=True)
    net.binary = False
    net.device = torch.device(device)
    net.model.to(net.device).eval()
    np.random.seed(42)
    torch.manual_seed(42)
    data = utils.data_process(X_drug=[drug], X_target=[sequence], y=[0.0],
                              drug_encoding=spec["drug_encoding"], target_encoding="CNN", split_method="no_split")
    if spec["drug_encoding"] == "MPNN":
        _check_graph_features(data.iloc[0]["drug_encoding"], drug)
    # MPNN.forward uses the upstream module global, independent of net.device.
    # Caller holds _INFERENCE_LOCK; restore the global even on failure.
    previous_device = encoders.device
    try:
        encoders.device = net.device
        with torch.inference_mode():
            values = net.predict(data)
    finally:
        encoders.device = previous_device
    if len(values) != 1 or not math.isfinite(float(values[0])):
        raise ToolError("INVALID_MODEL_OUTPUT", "Expected one finite prediction.")
    provenance = dict(manifest)
    provenance["deeppurpose_version"] = version("DeepPurpose")
    provenance["adapter_version"] = __version__
    provenance["installed_code_sha256"] = {"DTI.py": sha256(DTI.__file__), "utils.py": sha256(utils.__file__),
                                           "encoders.py": sha256(encoders.__file__), "chemutils.py": sha256(chemutils.__file__)}
    provenance.update(drug_encoding=spec["drug_encoding"], target_encoding=spec["target_encoding"],
                      training_dataset=spec["training_dataset"], input_limits=spec["limits"])
    return float(values[0]), provenance, {"python": platform.python_version(), "torch": torch.__version__,
                                        "rdkit": version("rdkit"), "numpy": np.__version__,
                                        "device": device, "seed": 42}


def _predict_dta(smiles, protein_sequence, model=MODEL, device="cpu"):
    started = time.perf_counter()
    try:
        # Upstream print() output must not contaminate the JSON stdout contract.
        with _INFERENCE_LOCK, redirect_stdout(sys.stderr):
            drug, sequence, canonical = validate_inputs(smiles, protein_sequence, model, device)
            actual_device = model_spec(model)["default_device"] if device == "auto" else device
            adapter = adapter_module(model)
            with device_lock(actual_device):
                if adapter is None:
                    value, provenance, execution = _run_model(drug, sequence, actual_device, model)
                    payload = None
                else:
                    payload = adapter.predict(drug, sequence, actual_device)
                    _validate_adapter_output(payload)
                    provenance, execution = payload["model"], payload["execution"]
        input_hash = hashlib.sha256(json.dumps([drug, sequence], separators=(",", ":")).encode()).hexdigest()
        execution["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        execution["requested_device"] = device
        result = {
            "schema_version": "1.0", "tool": "predict_dta", "status": "success", "task": "DTA",
            "input": {"smiles_original": smiles, "protein_sequence_original": protein_sequence,
                      "smiles_used": drug, "protein_sequence_used": sequence,
                      "canonical_smiles_for_identity_only": canonical, "sha256": input_hash,
                      "protein_length": len(sequence), "truncated": False,
                      "normalization": "trim_smiles; remove_sequence_whitespace; uppercase_sequence"},
            "model": provenance,
            "prediction": {"raw_value": value if payload is None else None, "endpoint": None, "scale": "upstream_log_affinity",
                           "higher_is_stronger": True, "interpretation_status": "checkpoint_endpoint_unverified"},
            "derived": None,
            "uncertainty": {"status": "not_calibrated", "method": None, "interval": None},
            "quality": {"ood_status": "not_assessed", "warnings": [
                "The exact checkpoint endpoint has not been independently verified; no Kd/IC50/nM conversion is made.",
                "This is a DTA regression score, not a DTI probability or experimental measurement."]},
            "execution": execution,
        }
        if payload is not None:
            for key in ("task", "prediction", "derived", "uncertainty", "quality"):
                result[key] = payload[key]
            if "artifacts" in payload:
                result["artifacts"] = payload["artifacts"]
        return result
    except ToolError as exc:
        return error_result(exc.code, str(exc), time.perf_counter() - started)
    except ImportError as exc:
        return error_result("DEPENDENCY_MISSING", str(exc), time.perf_counter() - started)
    except Exception as exc:
        return error_result("INFERENCE_FAILED", f"{type(exc).__name__}: {exc}", time.perf_counter() - started)


def _validate_adapter_output(payload):
    """Reject malformed external outputs instead of publishing a partial score."""
    required = {"model", "execution", "task", "prediction", "derived", "uncertainty", "quality"}
    if not isinstance(payload, dict) or not required <= payload.keys():
        raise ToolError("INVALID_MODEL_OUTPUT", "Adapter did not return the complete result contract.")
    prediction = payload["prediction"]
    if not isinstance(prediction, dict):
        raise ToolError("INVALID_MODEL_OUTPUT", "Adapter prediction must be an object.")
    score = prediction.get("raw_value")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
        raise ToolError("INVALID_MODEL_OUTPUT", "Expected one finite real-valued model score.")
    probability = prediction.get("binding_probability")
    if probability is not None and (isinstance(probability, bool) or not isinstance(probability, (int, float))
                                    or not math.isfinite(probability) or not 0 <= probability <= 1):
        raise ToolError("INVALID_MODEL_OUTPUT", "Binder probability must be finite and between zero and one.")


def execute_tool(arguments, on_model_event=None):
    """Internal untraced entrypoint; all public calls are recorded by runs.py."""
    if not isinstance(arguments, dict):
        return error_result("INVALID_ARGUMENT", "Input JSON must be an object.")
    properties = tool_schema()["inputSchema"]["properties"]
    if set(arguments) - properties.keys():
        return error_result("INVALID_ARGUMENT", "Unknown fields: " + ", ".join(sorted(set(arguments) - properties.keys())))
    if not {"smiles", "protein_sequence"} <= arguments.keys():
        return error_result("INVALID_ARGUMENT", "smiles and protein_sequence are required.")
    if "models" not in arguments:
        result = _predict_dta(**arguments)
        result["requested_model"] = arguments.get("model", MODEL)
        return result
    models = arguments["models"]
    if ("model" in arguments or not isinstance(models, list) or not 1 <= len(models) <= len(MODELS)
            or any(not isinstance(name, str) for name in models) or len(set(models)) != len(models)):
        return error_result("INVALID_ARGUMENT", "Use either model or a nonempty unique models list, never both.")
    if any(name not in MODELS for name in models):
        return error_result("UNSUPPORTED_MODEL", "Supported models: " + ", ".join(MODELS))
    started = time.perf_counter()
    pair = {key: value for key, value in arguments.items() if key != "models"}
    results = []
    for name in models:
        if on_model_event:
            on_model_event("started", name, None)
        result = _predict_dta(**pair, model=name)
        result["requested_model"] = name
        results.append(result)
        if on_model_event:
            on_model_event("completed" if result["status"] == "success" else "failed", name, result)
    succeeded = sum(result["status"] == "success" for result in results)
    status = "success" if succeeded == len(results) else "partial" if succeeded else "error"
    task = "DTA_comparison" if all(model_spec(name)["task"] == "DTA" for name in models) else "drug_target_comparison"
    report = {"schema_version": "1.1", "tool": "predict_dta", "task": task, "status": status,
              "requested_models": models, "results": results, "prediction": None, "aggregate": None,
              "summary": {"succeeded": succeeded, "failed": len(results) - succeeded},
              "execution": {"elapsed_seconds": round(time.perf_counter() - started, 4)},
              "warnings": ["Model outputs are separate, uncalibrated evidence; no average, probability or interval is computed."]}
    if status == "error":
        report["error"] = {"code": "ALL_MODELS_FAILED", "message": "All selected models failed. Inspect each result."}
    return report


def predict_dta(smiles, protein_sequence, model=None, device="cpu", models=None):
    from .runs import run_prediction
    arguments = {"smiles": smiles, "protein_sequence": protein_sequence, "device": device}
    if model is not None:
        arguments["model"] = model
    if models is not None:
        arguments["models"] = models
    return run_prediction(arguments, source="python")
