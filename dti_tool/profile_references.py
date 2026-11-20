"""Local checkpoint-specific training references. No registry lookups over the network."""

import hashlib
import json
import os
from pathlib import Path

from .input_rules import normalize_sequence, parse_ligand
from .models import PROJECT, ToolError


# Each optional evidence set is looked up by the exact normalized subject.
EVIDENCE_KEYS = {"protein_family_domains_isoforms": "sequence_sha256", "structures_pockets_ligands": "sequence_sha256",
                 "experimental_assays_exact_pair": "pair_id", "experimental_assays_similar_pairs": "pair_id"}


def lookup_evidence(pair_id, sequence_sha256):
    root = os.environ.get("DTI_PROFILE_REFERENCES")
    results = {}
    for kind, key in EVIDENCE_KEYS.items():
        subject = sequence_sha256 if key == "sequence_sha256" else pair_id
        report = {"status": "not_queried", "reason": "reference_unavailable" if subject else "invalid_subject",
                  "source": None, "records": []}
        results[kind] = report
        if not subject or not root:
            continue
        try:
            raw = (Path(root) / "evidence" / (kind + ".json")).read_bytes()
            data = json.loads(raw)
            if data["schema_version"] != "1.0" or data["kind"] != kind:
                raise ValueError("Evidence version or kind differs.")
            if not all(isinstance(data[k], str) and data[k].strip() for k in ("source", "version")):
                raise ValueError("Expected an evidence source and version.")
            report.update(source=data["source"], version=data["version"], sha256=hashlib.sha256(raw).hexdigest())
            if data.get("availability") == "unpublished":
                report.update(status="unpublished", reason="declared_by_source")
                continue
            if not isinstance(data["records"], list):
                raise ValueError("Expected a list of evidence records.")
            matches = []
            for record in data["records"]:
                if not isinstance(record, dict) or not record.get("reference_id") or key not in record:
                    raise ValueError(f"Every record needs a reference_id and {key}.")
                if record[key] == subject:
                    matches.append(record)
            report.update(status="matched" if matches else "no_match", reason=None, records=matches)
        except FileNotFoundError:
            continue
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report.update(status="failed", reason=str(exc))
    return results


def training_stages(model):
    if model == "ConPLex_v1_BindingDB":
        from .conplex import CHECKPOINT_SHA256, PROTBERT_SHA256
        return {"supervised": CHECKPOINT_SHA256, "protein_pretraining": PROTBERT_SHA256}
    if model == "Boltz2":
        from .boltz2 import ASSETS
        return {"supervised": ASSETS["boltz2_aff.ckpt"][1], "structure_training": ASSETS["boltz2_conf.ckpt"][1]}
    provider_file = {"CNN_CNN_BindingDB": "cnn", "MPNN_CNN_BindingDB": "mpnn"}[model]
    path = PROJECT / "docs" / f"checkpoint-{provider_file}-bindingdb.json"
    return {"supervised": json.loads(path.read_text(encoding="utf-8"))["files_sha256"]["model.pt"]}


def _protein_neighbor(query, reference, aligner):
    alignments = aligner.align(query, reference)
    try:
        alignment = next(iter(alignments))
    except StopIteration:
        return {"alignment_score": 0, "identity": None, "query_coverage": 0, "reference_coverage": 0}
    paired = int(sum(end - start for start, end in alignment.aligned[0]))
    return {"alignment_score": alignment.score, "identity": alignment.counts().identities / alignment.shape[1],
            "query_coverage": paired / len(query), "reference_coverage": paired / len(reference)}


def _search(data, ligand, sequence):
    from Bio.Align import PairwiseAligner
    from rdkit import DataStructs
    from rdkit.Chem import rdFingerprintGenerator
    from rdkit.Chem.Scaffolds import MurckoScaffold

    unit, coverage = data["unit"], data["coverage"]
    if unit not in ("compound", "protein", "pair") or coverage not in ("partial", "complete"):
        raise ValueError("Expected a compound, protein or pair index with explicit partial/complete coverage.")
    entries = data["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Expected a nonempty list of training entries.")
    fingerprint = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048, includeChirality=True)
    query_fp = fingerprint.GetFingerprint(ligand.mol)
    identity = ligand.identity_smiles()
    scaffold = MurckoScaffold.MurckoScaffoldSmiles(smiles=identity)
    aligner = PairwiseAligner(mode="local", match_score=2, mismatch_score=-1, open_gap_score=-5, extend_gap_score=-1)
    overlap = dict.fromkeys(("compound", "protein", "pair"), "unknown")
    for axis in overlap:
        if coverage == "complete" and (unit == "pair" or unit == axis):
            overlap[axis] = "not_seen"
    hits = {axis: [] for axis in overlap}
    compounds, proteins = {}, {}
    nearest_compound = nearest_protein = None
    scaffold_seen = False
    ids = set()
    for entry in entries:
        ref_id = entry["id"]
        if not isinstance(ref_id, str) or not ref_id.strip() or ref_id in ids:
            raise ValueError("Every training entry needs a unique nonempty ID.")
        ids.add(ref_id)
        metrics = {"id": ref_id}
        compound_match = protein_match = False
        if unit in ("compound", "pair"):
            smiles = entry["smiles"]
            if smiles not in compounds:
                ref = parse_ligand(smiles)
                ref_key = ref.identity_smiles()
                compounds[smiles] = (ref_key, MurckoScaffold.MurckoScaffoldSmiles(smiles=ref_key),
                                     DataStructs.TanimotoSimilarity(query_fp, fingerprint.GetFingerprint(ref.mol)))
            key, ref_scaffold, metrics["tanimoto"] = compounds[smiles]
            compound_match = key == identity
            scaffold_seen |= bool(scaffold and scaffold == ref_scaffold)
        if unit in ("protein", "pair"):
            ref_seq = normalize_sequence(entry["protein_sequence"])
            if ref_seq not in proteins:
                proteins[ref_seq] = _protein_neighbor(sequence, ref_seq, aligner)
            metrics.update(proteins[ref_seq])
            protein_match = sequence == ref_seq
        for axis, matched in (("compound", compound_match), ("protein", protein_match), ("pair", compound_match and protein_match)):
            if matched:
                hits[axis].append(ref_id)
                overlap[axis] = "seen"
        if "tanimoto" in metrics and (nearest_compound is None or metrics["tanimoto"] > nearest_compound["tanimoto"]):
            nearest_compound = metrics
        if "alignment_score" in metrics and (nearest_protein is None or metrics["alignment_score"] > nearest_protein["alignment_score"]):
            nearest_protein = metrics
    context = "unknown"
    if overlap["pair"] == "seen":
        context = "seen_pair"
    elif unit == "pair" and coverage == "complete":
        context = {("seen", "seen"): "new_pair", ("not_seen", "seen"): "cold_compound",
                   ("seen", "not_seen"): "cold_protein", ("not_seen", "not_seen"): "cold_both"}[
                       overlap["compound"], overlap["protein"]]
    scaffold_status = "unknown"
    if nearest_compound and scaffold:
        scaffold_status = "seen" if scaffold_seen else ("not_seen" if coverage == "complete" else "unknown")
    return {"overlap": overlap, "matching_entries": hits, "pair_context": context, "scaffold_overlap": scaffold_status,
            "nearest_compound": nearest_compound, "nearest_protein": nearest_protein,
            "methods": {"compound": "Morgan radius 2, 2048 bits, chirality enabled, Tanimoto",
                        "scaffold": "Bemis-Murcko, chirality excluded, empty scaffold unassessed",
                        "protein": "local alignment (+2/-1, gap open -5, extend -1), ranked by score; identity per alignment column, coverage by paired residues"},
            "entries_checked": len(entries)}


def audit_training(model, ligand, sequence):
    root = os.environ.get("DTI_PROFILE_REFERENCES")
    stages = {}
    for stage, digest in training_stages(model).items():
        report = {"checkpoint_sha256": digest, "lookup_status": "not_queried",
                  "reason": "training_manifest_unavailable", "overlap": dict.fromkeys(("compound", "protein", "pair"), "unknown"),
                  "pair_context": "unknown", "nearest_compound": None, "nearest_protein": None, "source": None}
        stages[stage] = report
        if not root:
            continue
        path = Path(root) / model / (stage + ".json")
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
            if (data["schema_version"], data["model"], data["stage"], data["checkpoint_sha256"]) != ("1.0", model, stage, digest):
                raise ValueError("Manifest version, model, stage or checkpoint identity differs.")
            if not all(isinstance(data[k], str) and data[k].strip() for k in ("source", "version")):
                raise ValueError("Expected a training source and version.")
            report.update(source=data["source"], version=data["version"], manifest_sha256=hashlib.sha256(raw).hexdigest())
            if data.get("availability") == "unpublished":
                report.update(lookup_status="unpublished", reason="declared_by_source")
            else:
                result = _search(data, ligand, sequence)
                report.update(result, lookup_status="queried", reason=None, unit=data["unit"], coverage=data["coverage"])
        except FileNotFoundError:
            continue
        except (ValueError, OSError, KeyError, TypeError, ToolError, ImportError) as exc:
            report.update(lookup_status="failed", reason=str(exc))
    return stages
