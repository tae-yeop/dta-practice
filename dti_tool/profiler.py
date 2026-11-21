"""Versioned, offline observations about one input pair for routing and interpretation."""

from collections import Counter
from functools import lru_cache
import hashlib
import json

from .input_rules import input_checks, normalize_sequence, parse_ligand
from .models import MODELS, PROJECT, ToolError
from .profile_references import audit_training, lookup_evidence
from .profile_structures import ligand_structures, protein_structures
from .public_evidence import public_evidence

SCHEMA_VERSION = "1.2"


def profile_schema():
    return {"name": "profile_input", "description": "Inspect an input pair offline or explicitly refresh its public experiment and structure evidence.",
            "inputSchema": {"type": "object", "additionalProperties": False, "required": ["smiles", "protein_sequence"],
                            "properties": {"smiles": {"type": "string"}, "protein_sequence": {"type": "string"},
                                           "refresh_evidence": {"type": "boolean", "default": False}}}}


def profile_error(code, message):
    return {"tool": "profile_input", "schema_version": SCHEMA_VERSION, "status": "error",
            "error": {"code": code, "message": message}}


def execute_profile(arguments):
    if (not isinstance(arguments, dict) or not {"smiles", "protein_sequence"} <= arguments.keys()
            or arguments.keys() - {"smiles", "protein_sequence", "refresh_evidence"}
            or not isinstance(arguments.get("refresh_evidence", False), bool)):
        return profile_error("INVALID_ARGUMENT", "Supply smiles, protein_sequence and optional boolean refresh_evidence.")
    return profile_input(**arguments)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _compound(ligand):
    from rdkit import Chem
    from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
    from rdkit.Chem.Scaffolds import MurckoScaffold

    identity = ligand.identity_smiles()
    mol = Chem.MolFromSmiles(identity)
    stereo = [{"type": str(s.type), "index": s.centeredOn, "specified": str(s.specified)}
              for s in Chem.FindPotentialStereo(mol)]
    return {"smiles_used": ligand.smiles, "identity_smiles": identity, "identity_sha256": _digest(identity),
            "inchikey": Chem.MolToInchiKey(mol) or None, "formula": rdMolDescriptors.CalcMolFormula(mol),
            "smiles_characters": len(ligand.smiles), "atoms": mol.GetNumAtoms(), "heavy_atoms": mol.GetNumHeavyAtoms(),
            "bonds": mol.GetNumBonds(), "formal_charge": Chem.GetFormalCharge(mol),
            "elements": dict(Counter(a.GetSymbol() for a in mol.GetAtoms())),
            "molecular_weight_da": Descriptors.MolWt(mol), "logp": Crippen.MolLogP(mol),
            "tpsa_angstrom2": rdMolDescriptors.CalcTPSA(mol),
            "hbond_donors": Lipinski.NumHDonors(mol), "hbond_acceptors": Lipinski.NumHAcceptors(mol),
            "rotatable_bonds": Lipinski.NumRotatableBonds(mol), "rings": rdMolDescriptors.CalcNumRings(mol),
            "murcko_scaffold": MurckoScaffold.MurckoScaffoldSmiles(mol=mol) or None, "stereochemistry": stereo,
            "structures": ligand_structures(mol)}


@lru_cache(maxsize=1)
def _catalog(raw):
    data = json.loads(raw)
    compounds = [(parse_ligand(row["smiles"]).identity_smiles(), row) for row in data["compounds"].values()]
    return compounds, data["targets"].values(), data["pairs"], {
        "source": "examples/catalog.json", "retrieved_at": data["retrieved_at"],
        "sha256": hashlib.sha256(raw).hexdigest(), "purpose": data["purpose"]}


def catalog_matches(compound, sequence):
    try:
        compounds, targets, pairs, source = _catalog((PROJECT / "examples" / "catalog.json").read_bytes())
        drugs = [dict(row) for key, row in compounds if compound and key == compound["identity_smiles"]]
        proteins = [{k: v for k, v in row.items() if k != "sequence"} for row in targets if sequence == row["sequence"]]
        cids = {row["cid"] for row in drugs}
        accessions = {row["accession"] for row in proteins}
        examples = [dict(row) for row in pairs if row["cid"] in cids and row["accession"] in accessions]
        def lookup(valid, matches):
            status = "not_queried" if not valid else ("matched" if matches else "no_match")
            return {"status": status, "matches": matches}
        return {**source, "status": "queried", "compound": lookup(compound, drugs),
                "protein": lookup(sequence, proteins), "pair": lookup(compound and sequence, examples)}
    except (OSError, ValueError, KeyError, TypeError, ToolError) as exc:
        return {"status": "failed", "source": "examples/catalog.json", "reason": str(exc)}


def _model_profile(model, ligand, sequence, stereo):
    spec = MODELS[model]
    checks = input_checks(ligand, sequence, model)
    warnings = []
    if spec["provider"] == "conplex" and stereo:
        warnings.append({"rule": "chirality_blind_fingerprint", "observed": len(stereo),
                         "description": "The ligand has potential stereochemistry. This Morgan encoder ignores chirality."})
    if spec["provider"] == "boltz2":
        atoms = next(check["observed"] for check in checks if check["rule"] == "atoms_after_remove_hs")
        recommended = spec["limits"]["recommended_ligand_atoms"]
        if atoms > recommended:
            warnings.append({"rule": "recommended_ligand_atoms", "observed": atoms, "maximum": recommended,
                             "description": "The ligand exceeds the adapter's recommended training range."})
    failed = any(check["status"] == "fail" for check in checks)
    return {"task": spec["task"], "outputs": [dict(output) for output in spec["outputs"]],
            "eligible": not failed, "status": "fail" if failed else ("warn" if warnings else "pass"),
            "checks": checks, "warnings": warnings, "training_dataset": spec["training_dataset"],
            "training": audit_training(model, ligand, sequence),
            "applicability": {"ood_status": "not_assessed", "reason": "validated_model_specific_criteria_unavailable"}}


def profile_input(smiles, protein_sequence, refresh_evidence=False):
    """Profile both components independently, then evaluate every registered model."""
    if not isinstance(refresh_evidence, bool):
        return profile_error("INVALID_ARGUMENT", "refresh_evidence must be a boolean.")
    try:
        result = _profile_pair(smiles, protein_sequence)
        if result.get("pair_id"):
            result["public_evidence"] = public_evidence(result, refresh_evidence)
        return result
    except ImportError as exc:
        return profile_error("DEPENDENCY_MISSING", str(exc))
    except (OSError, RuntimeError, ValueError, OverflowError) as exc:
        return profile_error("PROFILE_FAILED", str(exc))


def _profile_pair(smiles, protein_sequence):
    from rdkit import rdBase

    errors = []
    ligand = sequence = compound = protein = None
    try:
        ligand = parse_ligand(smiles)
        compound = _compound(ligand)
    except ToolError as exc:
        errors.append({"field": "smiles", "code": exc.code, "message": str(exc)})
    try:
        sequence = normalize_sequence(protein_sequence)
        protein = {"sequence_used": sequence, "length": len(sequence), "sequence_sha256": _digest(sequence),
                   "residue_counts": dict(sorted(Counter(sequence).items()))}
    except ToolError as exc:
        errors.append({"field": "protein_sequence", "code": exc.code, "message": str(exc)})
    result = {"tool": "profile_input", "schema_version": SCHEMA_VERSION, "status": "success", "errors": errors,
              "original": {"smiles": smiles, "protein_sequence": protein_sequence}, "compound": compound, "protein": protein,
              "provenance": {"rdkit_version": rdBase.rdkitVersion, "normalization": ["trim_smiles", "remove_sequence_whitespace", "uppercase_sequence"],
                             "identity": "canonical isomeric SMILES including enhanced stereo, atom maps removed, full normalized sequence"},
              "pair_id": None, "catalog": catalog_matches(compound, sequence), "models": {}}
    if compound and protein:
        result["pair_id"] = _digest(json.dumps([compound["identity_smiles"], sequence], separators=(",", ":")))
    if protein:
        protein["reference_structures"] = protein_structures(protein, result["catalog"])
    result["enrichment"] = lookup_evidence(result["pair_id"], protein and protein["sequence_sha256"])
    if errors:
        result.update(status="error", error=errors[0])
        return result
    result["models"] = {model: _model_profile(model, ligand, sequence, compound["stereochemistry"]) for model in MODELS}
    return result
