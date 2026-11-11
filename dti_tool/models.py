"""Curated checkpoints, explicit setup, and verified local artifacts."""

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import uuid
import zipfile

MODEL = "CNN_CNN_BindingDB"
PROJECT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://dataverse.harvard.edu/api/access/datafile/4159715"
SOURCE_CODE = "https://github.com/kexinhuang12345/DeepPurpose/blob/master/DeepPurpose/utils.py"
MODELS = {
    MODEL: {"provider": "deeppurpose", "display_name": "CNN · 서열 DTA", "task": "DTA",
            "default_device": "cpu", "timeout_seconds": 180,
            "description": "SMILES와 단백질 서열의 CNN 회귀 점수",
            "drug_encoding": "CNN", "target_encoding": "CNN", "source_url": SOURCE_URL,
            "training_dataset": "BindingDB", "limits": {"smiles_characters": 100, "protein_residues": 1000}},
    "MPNN_CNN_BindingDB": {
        "provider": "deeppurpose", "display_name": "MPNN · 약물 그래프 DTA", "task": "DTA",
        "default_device": "cpu", "timeout_seconds": 180,
        "description": "약물 2D 그래프와 단백질 CNN 회귀 점수",
        "drug_encoding": "MPNN", "target_encoding": "CNN",
        "source_url": "https://dataverse.harvard.edu/api/access/datafile/4204178",
        "training_dataset": "BindingDB",
        # DeepPurpose 0.1.5: MAX_ATOM=400, MAX_BOND=800 (2 per bond + padding).
        "limits": {"atoms": 400, "directed_bond_slots": 800, "neighbors": 6, "protein_residues": 1000},
    },
    "ConPLex_v1_BindingDB": {
        "provider": "conplex", "display_name": "ConPLex · DTI", "task": "DTI",
        "default_device": "cpu", "timeout_seconds": 900,
        "description": "Morgan fingerprint + ProtBert 상호작용 점수; 확률 아님",
        "drug_encoding": "Morgan", "target_encoding": "ProtBert",
        "source_url": "https://github.com/samsledje/ConPLex",
        "setup_command": ".venv\\Scripts\\python.exe scripts/setup_conplex.py",
        "training_dataset": "BindingDB", "limits": {"protein_residues": 1022},
    },
    "Boltz2": {
        "provider": "boltz2", "display_name": "Boltz-2 · 구조 + affinity", "task": "DTA_DTI_structure",
        "default_device": "cuda", "timeout_seconds": 3600,
        "description": "복합체 구조 예측과 affinity·binder probability; MSA 없는 로컬 실행",
        "drug_encoding": "3D_complex", "target_encoding": "3D_complex",
        "source_url": "https://github.com/jwohlwend/boltz",
        "setup_command": ".venv\\Scripts\\python.exe scripts/setup_boltz2.py",
        "training_dataset": "Boltz-2 upstream datasets",
        "limits": {"protein_residues": 800, "heavy_atoms": 128},
    },
}
DEEPPURPOSE_MODELS = tuple(name for name, spec in MODELS.items() if spec["provider"] == "deeppurpose")


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_root():
    return Path(os.environ.get("DTI_MODEL_CACHE", PROJECT / ".model-cache")).resolve()


def model_spec(model=MODEL):
    if not isinstance(model, str) or model not in MODELS:
        raise ToolError("UNSUPPORTED_MODEL", "Supported models: " + ", ".join(MODELS))
    return MODELS[model]


def model_dir(model=MODEL):
    spec = model_spec(model)
    root = cache_root()
    if spec["provider"] == "deeppurpose":
        current = root / "deeppurpose" / model
        if current.is_dir():
            return current
        # Preserve readable legacy caches. A directory created by a different
        # sandbox account can retain private temporary-directory ACLs; explicit
        # setup can import the official ZIP into the inherited-access layout.
        legacy = root / model
        try:
            if (legacy / "manifest.json").is_file():
                return legacy
        except PermissionError:
            pass
        return current
    return root / model


def adapter_module(model):
    """Load heavyweight adapter integration only when explicitly selected."""
    provider = model_spec(model)["provider"]
    if provider == "deeppurpose":
        return None
    return importlib.import_module(f"dti_tool.{provider}")


def check_model(model=MODEL):
    if model_spec(model)["provider"] != "deeppurpose":
        return adapter_module(model).check()
    folder = model_dir(model)
    if not (folder / "manifest.json").is_file():
        raise ToolError("MODEL_NOT_READY", f"Run `python -m dti_tool prepare-model --model {model}` first. Prediction never downloads weights.")
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if manifest["model"] != model or set(manifest["files"]) != {"config.pkl", "model.pt"}:
            raise ValueError("Unexpected checkpoint manifest")
        for name, expected in manifest["files"].items():
            if not (folder / name).is_file() or sha256(folder / name) != expected:
                raise ValueError(f"Checkpoint hash mismatch: {name}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolError("MODEL_INTEGRITY_ERROR", str(exc)) from exc
    return folder, manifest


def prepare_model(archive=None, model=MODEL):
    """Download the upstream archive or import an explicitly supplied local ZIP.

    Hashes pin the bytes acquired at setup; they are not publisher signatures.
    Only the two expected files are copied, without extracting arbitrary paths.
    """
    spec = model_spec(model)
    if spec["provider"] != "deeppurpose":
        return adapter_module(model).prepare(archive=archive)
    if model_dir(model).exists():
        _, manifest = check_model(model)
        return manifest
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=root) as temporary:
        staging = Path(temporary)
        archive_path = Path(archive).resolve() if archive else staging / "checkpoint.zip"
        if not archive:
            try:
                with urllib.request.urlopen(spec["source_url"], timeout=60) as response, archive_path.open("wb") as output:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 1024 ** 3:
                            raise ToolError("DOWNLOAD_FAILED", "Checkpoint archive exceeded 1 GiB.")
                        output.write(chunk)
            except OSError as exc:
                raise ToolError("DOWNLOAD_FAILED", f"Cannot download official checkpoint: {exc}") from exc
        prepared = staging / "ready"
        prepared.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as bundle:
                for name in ("config.pkl", "model.pt"):
                    matches = [item for item in bundle.infolist() if not item.is_dir() and Path(item.filename).name == name]
                    if len(matches) != 1 or matches[0].file_size > 1024 ** 3:
                        raise ToolError("INVALID_ARCHIVE", f"Expected exactly one reasonably sized {name}.")
                    with bundle.open(matches[0]) as source, (prepared / name).open("wb") as destination:
                        shutil.copyfileobj(source, destination)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise ToolError("INVALID_ARCHIVE", str(exc)) from exc
        manifest = {
            "model": model,
            "source_url": spec["source_url"],
            "source_mapping": SOURCE_CODE,
            "acquisition": "local_archive" if archive else "official_url",
            "archive_sha256": sha256(archive_path),
            "files": {name: sha256(prepared / name) for name in ("config.pkl", "model.pt")},
            "integrity_policy": "sha256_pinned_at_setup_not_publisher_signature",
        }
        (prepared / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        destination = model_dir(model)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # A regular sibling inherits cache permissions, unlike a private
        # TemporaryDirectory on Windows. Publish only after all copies succeed.
        publishing = destination.parent / (".prepare-" + uuid.uuid4().hex)
        if not publishing.resolve().is_relative_to(root.resolve()):
            raise ToolError("INVALID_CACHE_PATH", "Checkpoint staging escaped the selected cache root.")
        publishing.mkdir()
        try:
            for name in ("config.pkl", "model.pt", "manifest.json"):
                shutil.copyfile(prepared / name, publishing / name)
            publishing.rename(destination)
        finally:
            if publishing.exists():
                for name in ("config.pkl", "model.pt", "manifest.json"):
                    (publishing / name).unlink(missing_ok=True)
                publishing.rmdir()
    return manifest
