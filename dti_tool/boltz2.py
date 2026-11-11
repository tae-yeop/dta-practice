"""Offline, isolated Boltz-2 affinity inference with pinned official artifacts."""

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import urllib.request
import uuid

from .models import PROJECT, ToolError, cache_root, sha256

MODEL = "Boltz2"
VERSION = "2.2.1"
HF_REVISION = "6fdef46d763fee7fbb83ca5501ccceff43b85607"
SOURCE = "https://github.com/jwohlwend/boltz"
DOCS = SOURCE + "/blob/main/docs/prediction.md"
ASSETS = {
    "boltz2_conf.ckpt": (2286561469, "090e82ac8c92f5e943fa1b39e7410a44027bea7243c0bbb3caa67a77fc1428e1"),
    "boltz2_aff.ckpt": (2062139170, "dcc5cd3722b1c9eaa34267e4ae32f55cbbf1963f4c19319381ccfa30fdd2ca9e"),
    "mols.tar": (1855662080, "39e076d96dbec6b4e86982bbda16f3a53a2a60c9bdc17828d88f6f9a0c7d1fd7"),
}
CANONICAL = "ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL UNK".split()
SPEC = {
    "backend": "boltz2", "drug_encoding": "3D_ligand", "target_encoding": "cofolding_single_sequence",
    "source_url": "https://huggingface.co/boltz-community/boltz-2/tree/" + HF_REVISION,
    "training_dataset": "Boltz-2 structure and affinity training collections; see upstream paper",
    "task": "DTA_DTI", "default_device": "cuda", "timeout_seconds": 3600,
    "limits": {"protein_residues": 800, "ligand_atoms": 128, "recommended_ligand_atoms": 56},
    "limits_note": "Protein limit is local resource policy; ligand counts follow RDKit RemoveHs. No truncation.",
    "setup_command": ".venv\\Scripts\\python.exe scripts/setup_boltz2.py",
}
PARAMETERS = {"recycling_steps": 3, "sampling_steps": 200, "diffusion_samples": 1,
              "sampling_steps_affinity": 200, "diffusion_samples_affinity": 5,
              "max_parallel_samples": 1, "seed": 42, "no_kernels": True,
              "msa_mode": "single_sequence", "affinity_mw_correction": False}
_HASH_CACHE = {}


def folder():
    return cache_root() / MODEL


def runtime_python():
    default = PROJECT / ".venv-boltz2" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return Path(os.environ.get("DTI_BOLTZ_PYTHON", default)).resolve()


def _fingerprint(path):
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if key not in _HASH_CACHE:
        _HASH_CACHE[key] = sha256(path)
    return _HASH_CACHE[key]


def _verify_asset(path, name):
    size, digest = ASSETS[name]
    if not path.is_file() or path.stat().st_size != size or _fingerprint(path) != digest:
        raise ToolError("MODEL_INTEGRITY_ERROR", f"Boltz-2 official artifact mismatch: {name}")


def check():
    root = folder()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ToolError("MODEL_NOT_READY", "Prepare Boltz-2 runtime and assets: .venv\\Scripts\\python.exe scripts/setup_boltz2.py")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["model"] != MODEL or manifest["revision"] != HF_REVISION:
            raise ValueError("Unexpected Boltz-2 manifest identity")
        if manifest["files"] != {name: value[1] for name, value in ASSETS.items()}:
            raise ValueError("Unexpected Boltz-2 artifact hashes")
        for name in ASSETS:
            _verify_asset(root / name, name)
        if set(manifest["canonical_molecules"]) != {name + ".pkl" for name in CANONICAL}:
            raise ValueError("Missing canonical CCD component identities")
        for name, digest in manifest["canonical_molecules"].items():
            path = root / "mols" / name
            if not path.is_file() or _fingerprint(path) != digest:
                raise ValueError("Canonical CCD component mismatch: " + name)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolError("MODEL_INTEGRITY_ERROR", str(exc)) from exc
    if not runtime_python().is_file():
        raise ToolError("DEPENDENCY_MISSING", "Boltz-2 Python environment missing. Follow docs/boltz2.md or set DTI_BOLTZ_PYTHON.")
    return root, manifest


def _environment():
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "WANDB_MODE": "disabled",
            "HF_HUB_DISABLE_TELEMETRY": "1", "OMP_NUM_THREADS": "4"}


def probe_runtime():
    interpreter = runtime_python()
    if not interpreter.is_file():
        raise ToolError("DEPENDENCY_MISSING", "Create .venv-boltz2 using requirements-boltz2.txt; see docs/boltz2.md.")
    command = [str(interpreter), str(PROJECT / "dti_tool" / "boltz2_worker.py"), "--probe"]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120,
                               env=_environment(), creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if completed.returncode:
        raise ToolError("UNSUPPORTED_RUNTIME", "Boltz-2 runtime probe failed: " + completed.stderr[-1500:])
    try:
        runtime = json.loads(completed.stdout)
    except ValueError as exc:
        raise ToolError("UNSUPPORTED_RUNTIME", "Boltz-2 runtime returned invalid probe JSON.") from exc
    if runtime.get("boltz") != VERSION:
        raise ToolError("UNSUPPORTED_RUNTIME", f"Boltz-2 adapter requires boltz=={VERSION}.")
    return runtime


def prepare(archive=None):
    """Explicit download or import of a directory with the three official assets."""
    root = folder()
    if (root / "manifest.json").exists():
        return check()[1]
    runtime = probe_runtime()
    root.mkdir(parents=True, exist_ok=True)
    source = Path(archive).resolve() if archive else None
    if source is not None and not source.is_dir():
        raise ToolError("INVALID_ARCHIVE", "Boltz-2 --archive expects a directory containing boltz2_conf.ckpt, boltz2_aff.ckpt and mols.tar.")
    for name in ASSETS:
        target = root / name
        if target.exists():
            _verify_asset(target, name)
            continue
        partial = root / (name + ".partial")
        if source:
            _verify_asset(source / name, name)
            shutil.copyfile(source / name, partial)
        else:
            url = f"https://huggingface.co/boltz-community/boltz-2/resolve/{HF_REVISION}/{name}"
            try:
                with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as destination:
                    shutil.copyfileobj(response, destination, 1024 * 1024)
            except OSError as exc:
                raise ToolError("DOWNLOAD_FAILED", f"Boltz-2 asset {name}: {exc}") from exc
        _verify_asset(partial, name)
        partial.replace(target)
    # Scope is standard protein residues + an input SMILES ligand. Extract only
    # the 21 canonical components actually loaded by upstream load_canonicals().
    # This also avoids Windows reserved CCD filenames such as AUX.pkl.
    molecules = root / "mols"
    molecules.mkdir(exist_ok=True)
    wanted = {f"mols/{name}.pkl" for name in CANONICAL}
    found = set()
    with tarfile.open(root / "mols.tar") as bundle:
        for member in bundle:
            if member.name not in wanted:
                continue
            if not member.isfile() or member.size > 16 * 1024 * 1024 or member.name in found:
                raise ToolError("INVALID_ARCHIVE", "Unexpected canonical CCD archive entry: " + member.name)
            with bundle.extractfile(member) as src, (molecules / Path(member.name).name).open("wb") as dst:
                shutil.copyfileobj(src, dst)
            found.add(member.name)
    if found != wanted:
        raise ToolError("INVALID_ARCHIVE", "Official CCD archive lacks required canonical amino acids.")
    manifest = {"model": MODEL, "boltz_version": VERSION, "source_url": SPEC["source_url"],
                "source_mapping": SOURCE + "/blob/main/src/boltz/main.py", "revision": HF_REVISION,
                "acquisition": "local_directory" if source else "official_url",
                "files": {name: value[1] for name, value in ASSETS.items()},
                "file_sizes": {name: value[0] for name, value in ASSETS.items()},
                "canonical_molecules": {name + ".pkl": sha256(molecules / (name + ".pkl")) for name in CANONICAL},
                "ccd_scope": "21 upstream canonical amino acids; other CCD inputs are not accepted",
                "integrity_policy": "sha256_pinned_to_official_huggingface_lfs_metadata",
                "runtime_at_setup": runtime}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate(drug, sequence):
    from rdkit import Chem
    if len(sequence) > SPEC["limits"]["protein_residues"]:
        raise ToolError("INPUT_TOO_LONG", "Boltz-2 local resource policy limits protein length to 800 residues. No truncation.")
    mol = Chem.MolFromSmiles(drug)
    if mol is None:
        raise ToolError("INVALID_SMILES", "RDKit could not parse the Boltz-2 ligand.")
    atoms = Chem.RemoveHs(mol).GetNumAtoms()
    if atoms > 128:
        raise ToolError("INPUT_TOO_LONG", "Boltz-2 affinity supports at most 128 atoms counted after RDKit RemoveHs.")
    return atoms


def make_input(drug, sequence):
    return {"version": 1, "sequences": [
        {"protein": {"id": "A", "sequence": sequence, "msa": "empty"}},
        {"ligand": {"id": "L", "smiles": drug}}], "properties": [{"affinity": {"binder": "L"}}]}


def _kill_tree(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def parse_outputs(output, atom_count):
    raw_path = output / "affinity_input.json"
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        value, probability = raw["affinity_pred_value"], raw["affinity_probability_binary"]
        if (isinstance(value, bool) or isinstance(probability, bool)
                or not isinstance(value, (float, int)) or not isinstance(probability, (float, int))
                or not math.isfinite(value) or not math.isfinite(probability) or not 0 <= probability <= 1):
            raise ValueError("Expected finite affinity and probability in [0,1]")
        confidence = json.loads((output / "confidence_input_model_0.json").read_text(encoding="utf-8"))
        cif = output / "input_model_0.cif"
        if not cif.is_file() or cif.stat().st_size == 0:
            raise ValueError("Predicted complex is missing")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolError("INVALID_MODEL_OUTPUT", f"Boltz-2 output invalid: {exc}") from exc
    warnings = ["Single-sequence mode (msa: empty) can reduce accuracy; no MSA server was contacted.",
                "Binding probability is an upstream classifier output, not locally calibrated evidence of binding.",
                "Structure confidence is separate from binding probability and affinity uncertainty.",
                "The affinity value is predicted log10(IC50 in micromolar), not an experimental measurement or Kd."]
    if atom_count > 56:
        warnings.append("Ligand exceeds the upstream recommended training range of 56 atoms.")
    return {"task": "DTA_DTI", "prediction": {"raw_value": value, "endpoint": "IC50",
                "scale": "log10_IC50_uM", "higher_is_stronger": False,
                "interpretation_status": "upstream_documented_scale", "binding_probability": probability,
                "binding_probability_calibration": "not_assessed", "upstream_outputs": raw},
            "derived": None, "uncertainty": {"status": "not_calibrated", "method": None, "interval": None},
            "quality": {"ood_status": "not_assessed", "msa_mode": "single_sequence",
                        "structure_confidence": confidence, "ligand_atoms": atom_count, "warnings": warnings},
            "artifacts": {"complex_cif": str(cif), "affinity_json": str(raw_path),
                          "confidence_json": str(output / "confidence_input_model_0.json")}}


def predict(drug, sequence, device):
    atom_count = validate(drug, sequence)
    root, manifest = check()
    runtime = probe_runtime()
    if device == "cuda" and not runtime["cuda_available"]:
        raise ToolError("DEVICE_UNAVAILABLE", "CUDA unavailable in the isolated Boltz-2 runtime. Choose cpu or install CUDA PyTorch.")
    if device not in {"cpu", "cuda"}:
        raise ToolError("INVALID_ARGUMENT", "Boltz-2 device must be cpu or cuda.")
    run_root = Path(os.environ.get("DTI_BOLTZ_RUNS_DIR", PROJECT / "runs" / "boltz2-jobs")).resolve()
    job = run_root / uuid.uuid4().hex
    job.mkdir(parents=True)
    (job / "input.yaml").write_text(json.dumps(make_input(drug, sequence), indent=2), encoding="utf-8")
    request = {"input": str(job / "input.yaml"), "output": str(job), "cache": str(root),
               "device": device, "parameters": PARAMETERS}
    (job / "worker-request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    command = [str(runtime_python()), str(PROJECT / "dti_tool" / "boltz2_worker.py"), str(job / "worker-request.json")]
    started = time.perf_counter()
    with (job / "inference.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, env=_environment(),
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                   start_new_session=os.name != "nt")
        try:
            code = process.wait(timeout=SPEC["timeout_seconds"])
        except subprocess.TimeoutExpired as exc:
            _kill_tree(process)
            raise ToolError("INFERENCE_TIMEOUT", f"Boltz-2 exceeded {SPEC['timeout_seconds']} seconds. Log: {job / 'inference.log'}") from exc
    if code:
        raise ToolError("INFERENCE_FAILED", f"Boltz-2 worker exited with code {code}. Log: {job / 'inference.log'}")
    output = job / "boltz_results_input" / "predictions" / "input"
    result = parse_outputs(output, atom_count)
    result["model"] = {**manifest, "runtime": runtime, "parameters": PARAMETERS, "input_limits": SPEC["limits"],
                       "adapter_sha256": sha256(Path(__file__)),
                       "worker_sha256": sha256(PROJECT / "dti_tool" / "boltz2_worker.py")}
    result["execution"] = {**runtime, "device": device, "seed": 42, "elapsed_seconds": round(time.perf_counter() - started, 4),
                           "offline": True, "python_executable": str(runtime_python()),
                           "job_path": str(job), "log_path": str(job / "inference.log")}
    (job / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result
