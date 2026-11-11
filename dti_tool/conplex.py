"""Offline ConPLex DTI adapter using pinned upstream code and ProtBert weights."""

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

from .models import PROJECT, ToolError, cache_root, sha256

NAME = "ConPLex_v1_BindingDB"
REVISION = "ccd8c804a76dff41649e58f692293b55c8907129"
PROTBERT_REVISION = "7a894481acdc12202f0a415dd567f6cfdb698908"
PROTBERT_SHA256 = "6ea3edd26cfefc3111176100ee2a027ed510f9c86b63e5b53a2a050b59f2af9d"
CHECKPOINT_SHA256 = "c28f0e64907e2cec786f2fdefd0ee75ac991b971671a49f896611dc192e6d39c"
SOURCE_URL = "https://cb.csail.mit.edu/cb/conplex/data/models/BindingDB_ExperimentalValidModel.pt"
SOURCE_FILES = (
    "LICENSE", "conplex_dti/__init__.py", "conplex_dti/utils.py",
    "conplex_dti/model/__init__.py", "conplex_dti/model/architectures.py",
    "conplex_dti/featurizer/__init__.py", "conplex_dti/featurizer/base.py",
    "conplex_dti/featurizer/molecule.py", "conplex_dti/featurizer/protein.py",
    "conplex_dti/cli/predict.py", "conplex_dti/cli/download.py",
)
ENCODER_FILES = ("config.json", "pytorch_model.bin", "special_tokens_map.json", "tokenizer_config.json", "vocab.txt")
SPEC = {
    "backend": "conplex", "task": "DTI", "drug_encoding": "Morgan",
    "target_encoding": "ProtBert", "training_dataset": "BindingDB",
    "source_url": SOURCE_URL, "source_code": "https://github.com/samsledje/ConPLex",
    "limits": {"protein_residues": 1022}, "devices": ["cpu", "cuda"],
    "default_device": "cpu", "timeout_seconds": 900,
    "description": "Morgan + ProtBert co-embedding cosine; not a calibrated binding probability.",
}
_VERIFIED = {}


def folder():
    return cache_root() / NAME


def runtime_python():
    default = PROJECT / ".venv-conplex" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return Path(os.environ.get("DTI_CONPLEX_PYTHON", default)).resolve()


def _verified_hash(path, expected):
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, expected)
    if key not in _VERIFIED:
        actual = sha256(path)
        if actual != expected:
            raise ValueError("ConPLex artifact hash mismatch: " + str(path))
        _VERIFIED[key] = True


def check():
    root = folder()
    path = root / "manifest.json"
    if not path.is_file():
        raise ToolError("MODEL_NOT_READY", "Prepare ConPLex with scripts/setup_conplex.py or prepare-model --model ConPLex_v1_BindingDB. Prediction never downloads weights.")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        required = {"model.pt", *("source/" + name for name in SOURCE_FILES), *("prot_bert/" + name for name in ENCODER_FILES)}
        if manifest["model"] != NAME or set(manifest["files"]) != required:
            raise ValueError("Unexpected ConPLex manifest")
        if manifest["source_revision"] != REVISION or manifest["protein_encoder_revision"] != PROTBERT_REVISION:
            raise ValueError("Unsupported ConPLex/ProtBert revision")
        if manifest["files"]["prot_bert/pytorch_model.bin"] != PROTBERT_SHA256:
            raise ValueError("ProtBert must match its official published LFS SHA-256")
        if manifest["files"]["model.pt"] != CHECKPOINT_SHA256:
            raise ValueError("ConPLex must match the checkpoint downloaded from the official URL on 2026-11-11")
        for name, expected in manifest["files"].items():
            _verified_hash(root / name, expected)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolError("MODEL_INTEGRITY_ERROR", str(exc)) from exc
    if not runtime_python().is_file():
        raise ToolError("DEPENDENCY_MISSING", "ConPLex runtime is missing. Install requirements/models/conplex.txt in .venv-conplex or set DTI_CONPLEX_PYTHON.")
    return root, manifest


def _download(url, destination, max_bytes=2 * 1024 ** 3, *, allow_empty=False):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    total = 0
    try:
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ToolError("DOWNLOAD_FAILED", "ConPLex download exceeded its size limit.")
                output.write(chunk)
        if total == 0 and not allow_empty:
            raise ToolError("DOWNLOAD_FAILED", "ConPLex download was empty.")
        temporary.replace(destination)
    except OSError as exc:
        raise ToolError("DOWNLOAD_FAILED", f"Cannot download {url}: {exc}") from exc


def prepare(archive=None, *, protbert_dir=None):
    """Explicit setup only. archive may name the official .pt; encoder reuse is opt-in."""
    root = folder()
    if (root / "manifest.json").is_file():
        return check()[1]
    root.mkdir(parents=True, exist_ok=True)
    if archive:
        source = Path(archive).resolve()
        if not source.is_file():
            raise ToolError("INVALID_ARCHIVE", "ConPLex --archive expects an official projection checkpoint .pt file.")
        if source != (root / "model.pt").resolve():
            shutil.copyfile(source, root / "model.pt")
    else:
        _download(SOURCE_URL, root / "model.pt", 128 * 1024 ** 2)
    if sha256(root / "model.pt") != CHECKPOINT_SHA256:
        raise ToolError("MODEL_INTEGRITY_ERROR", "ConPLex projection checkpoint differs from the verified official checkpoint.")
    for name in SOURCE_FILES:
        _download(f"https://raw.githubusercontent.com/samsledje/ConPLex/{REVISION}/{name}", root / "source" / name, 2 * 1024 ** 2,
                  allow_empty=name.endswith("/__init__.py"))
    for name in ENCODER_FILES:
        target = root / "prot_bert" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if protbert_dir and name == "pytorch_model.bin":
            source = Path(protbert_dir).resolve() / name
            if sha256(source) != PROTBERT_SHA256:
                raise ToolError("MODEL_INTEGRITY_ERROR", "Provided ProtBert weights do not match the official LFS SHA-256.")
            if source != target.resolve():
                shutil.copyfile(source, target)
        else:
            _download(f"https://huggingface.co/Rostlab/prot_bert/resolve/{PROTBERT_REVISION}/{name}", target)
    if sha256(root / "prot_bert/pytorch_model.bin") != PROTBERT_SHA256:
        raise ToolError("MODEL_INTEGRITY_ERROR", "Downloaded ProtBert weights differ from the official LFS SHA-256.")
    paths = ["model.pt", *("source/" + name for name in SOURCE_FILES), *("prot_bert/" + name for name in ENCODER_FILES)]
    manifest = {
        "model": NAME, "source_url": SOURCE_URL, "source_revision": REVISION,
        "source_mapping": f"https://github.com/samsledje/ConPLex/blob/{REVISION}/conplex_dti/cli/download.py",
        "protein_encoder": "Rostlab/prot_bert", "protein_encoder_revision": PROTBERT_REVISION,
        "protein_encoder_url": f"https://huggingface.co/Rostlab/prot_bert/tree/{PROTBERT_REVISION}",
        "acquisition": "local_checkpoint" if archive else "official_url",
        "encoder_acquisition": "verified_local_weights_official_configs" if protbert_dir else "official_url",
        "files": {name: sha256(root / name) for name in paths},
        "integrity_policy": "sha256_pinned_at_setup; ProtBert additionally matches publisher LFS SHA256; not a digital signature",
    }
    temporary = root / "manifest.json.part"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(root / "manifest.json")
    return check()[1]


def predict(drug, sequence, device="cpu"):
    """Run only verified local artifacts in an isolated Python environment."""
    started = time.perf_counter()
    root, manifest = check()
    if not sequence or len(sequence) > 1022 or set(sequence) - set("ACDEFGHIKLMNPQRSTVWY"):
        raise ToolError("UNSUPPORTED_SEQUENCE", "ConPLex requires 1..1022 canonical amino acids; no truncation.")
    if device not in {"cpu", "cuda"}:
        raise ToolError("INVALID_ARGUMENT", "ConPLex device must be cpu or cuda.")
    work = PROJECT / "runs" / "conplex" / uuid.uuid4().hex
    work.mkdir(parents=True)
    request = {"smiles": drug, "protein_sequence": sequence, "device": device,
               "model_dir": str(root), "output": str(work / "output.json")}
    (work / "request.json").write_text(json.dumps(request), encoding="utf-8")
    command = [str(runtime_python()), str(PROJECT / "dti_tool" / "conplex_worker.py"), "--request", str(work / "request.json")]
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
           "PYTHONIOENCODING": "utf-8", "TOKENIZERS_PARALLELISM": "false"}
    with (work / "stdout.log").open("wb") as stdout, (work / "stderr.log").open("wb") as stderr:
        try:
            completed = subprocess.run(command, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, timeout=SPEC["timeout_seconds"],
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired as exc:
            raise ToolError("INFERENCE_TIMEOUT", f"ConPLex exceeded {SPEC['timeout_seconds']} seconds. Logs: {work}") from exc
    result = json.loads((work / "output.json").read_text(encoding="utf-8")) if (work / "output.json").is_file() else {}
    if result.get("error", {}).get("code") == "DEVICE_UNAVAILABLE":
        raise ToolError("DEVICE_UNAVAILABLE", f"{result['error']['message']} Logs: {work}")
    if completed.returncode != 0 or not result:
        tail = (work / "stderr.log").read_text(encoding="utf-8", errors="replace")[-1500:]
        raise ToolError("INFERENCE_FAILED", f"ConPLex worker failed. Logs: {work}\n{tail}")
    value = result["score"]
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not -1.000001 <= value <= 1.000001:
        raise ToolError("INVALID_MODEL_OUTPUT", "ConPLex must return one finite cosine score.")
    provenance = {**manifest, "drug_encoding": "Morgan", "target_encoding": "ProtBert", "training_dataset": "BindingDB",
                  "input_limits": SPEC["limits"], "adapter_sha256": sha256(Path(__file__)),
                  "worker_sha256": sha256(PROJECT / "dti_tool" / "conplex_worker.py")}
    return {
        "task": "DTI", "model": provenance,
        "prediction": {"raw_value": float(value), "endpoint": "interaction_score", "scale": "cosine_similarity",
                       "higher_is_stronger": True, "interpretation_status": "upstream_dti_score_not_calibrated_probability"},
        "derived": None, "uncertainty": {"status": "not_calibrated", "method": None, "interval": None},
        "quality": {"ood_status": "not_assessed", "warnings": [
            "ConPLex returns a co-embedding cosine interaction score, not affinity or a calibrated binding probability.",
            "Upstream Morgan fingerprints use radius=2, 2048 bits and useChirality=False; stereoisomers can share identical drug features.",
            "ProtBert residue embeddings are mean-pooled with CLS/SEP excluded; no input truncation is performed."]},
        "execution": {**result["execution"], "elapsed_seconds": round(time.perf_counter() - started, 4),
                      "runtime_python": str(runtime_python()), "offline": True},
        "artifacts": {"worker_directory": str(work), "stdout": str(work / "stdout.log"), "stderr": str(work / "stderr.log")},
    }
