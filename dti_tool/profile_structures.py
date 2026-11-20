"""Lightweight ligand geometry and sequence-matched experimental structure references."""

from base64 import b64encode
import json

from .models import PROJECT


def ligand_structures(mol):
    from rdkit import Chem
    from rdkit.Chem import rdDistGeom
    from rdkit.Chem.Draw import rdMolDraw2D

    result = {"depiction_png": None, "conformer": {"method": "RDKit ETKDGv3", "seed": 42,
              "scope": "isolated_ligand", "coordinate_unit": "angstrom", "status": "unavailable"}}
    if mol.GetNumAtoms() <= 400:
        try:
            drawer = rdMolDraw2D.MolDraw2DCairo(500, 270)
            drawer.drawOptions().includeMetadata = False
            rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
            drawer.FinishDrawing()
            result["depiction_png"] = b64encode(drawer.GetDrawingText()).decode("ascii")
        except (RuntimeError, ValueError):
            pass
    conformer = result["conformer"]
    if mol.GetNumAtoms() > 128:
        conformer.update(status="skipped", reason="preview_atom_limit", maximum_atoms=128)
        return result
    try:
        hydrated = Chem.AddHs(mol)
        params = rdDistGeom.ETKDGv3()
        params.randomSeed = conformer["seed"]
        params.maxIterations = 12
        params.timeout = 2
        if rdDistGeom.EmbedMolecule(hydrated, params) < 0:
            conformer["reason"] = "embedding_failed"
        else:
            conformer.update(status="available", sdf=Chem.MolToMolBlock(hydrated) + "$$$$\n")
    except (RuntimeError, ValueError):
        conformer["reason"] = "embedding_failed"
    return result


def structure_catalog():
    path = PROJECT / "examples" / "structures" / "index.json"
    return json.loads(path.read_text(encoding="utf8"))


def protein_structures(protein, catalog):
    records = []
    try:
        index = structure_catalog()
    except (OSError, ValueError):
        return {"status": "failed", "records": []}
    for target in catalog.get("protein", {}).get("matches", []):
        entry = index.get(target["accession"])
        if entry and entry["sequence_sha256"] == protein["sequence_sha256"]:
            records.append({**entry, "accession": target["accession"], "kind": "experimental_target_reference",
                            "coordinate_file": "examples/structures/" + entry["pdb_id"] + ".cif.gz"})
    return {"status": "matched" if records else "no_match", "records": records}
