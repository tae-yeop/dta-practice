import base64
import gzip
import hashlib
import json
from io import StringIO

import pytest
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from rdkit import Chem
from starlette.testclient import TestClient

from dti_tool import profile_input
from dti_tool.models import PROJECT
from dti_tool.profile_structures import structure_catalog
from dti_tool.runs import create_run, run_dir
from dti_web.app import create_app


def test_ligand_geometry_has_real_repeatable_coordinates_and_preserves_chirality():
    smiles = "C[C@@H](O)F"
    def geometry():
        return profile_input(smiles, "ACDE")["compound"]["structures"]
    first = geometry()
    assert base64.b64decode(first["depiction_png"]).startswith(b"\x89PNG")
    assert first == geometry()
    block = first["conformer"]["sdf"]
    mol = Chem.MolFromMolBlock(block)
    assert mol.GetConformer().Is3D() and mol.GetConformer().GetPositions().std() > 0
    Chem.AssignStereochemistryFrom3D(mol)
    assert Chem.MolToSmiles(mol) == Chem.MolToSmiles(Chem.MolFromSmiles(smiles))


def test_structure_fallback_preserves_profile(monkeypatch):
    from rdkit.Chem import rdDistGeom
    monkeypatch.setattr(rdDistGeom, "EmbedMolecule", lambda *_: -1)
    profile = profile_input("CCO", "ACDE")
    structures = profile["compound"]["structures"]
    assert profile["status"] == "success" and structures["depiction_png"]
    assert structures["conformer"]["reason"] == "embedding_failed" and "sdf" not in structures["conformer"]
    assert profile["protein"]["reference_structures"] == {"status": "no_match", "records": []}
    large = profile_input("C"*129, "ACDE")
    assert large["compound"]["structures"]["conformer"]["status"] == "skipped" and large["models"]


def test_bundled_reference_coordinates_match_catalog_and_http():
    catalog = json.loads((PROJECT / "examples/catalog.json").read_bytes())
    index = structure_catalog()
    assert index.keys() == catalog["targets"].keys()
    with TestClient(create_app()) as client:
        for accession, ref in index.items():
            protein = catalog["targets"][accession]
            profile = profile_input("CCO", protein["sequence"])
            saved = profile["protein"]["reference_structures"]["records"][0]
            assert saved["sequence_sha256"] == profile["protein"]["sequence_sha256"] and saved["accession"] == accession
            cif = gzip.decompress((PROJECT / saved["coordinate_file"]).read_bytes())
            assert hashlib.sha256(cif).hexdigest() == saved["cif_sha256"]
            data = MMCIF2Dict(StringIO(cif.decode()))
            assert data["_entry.id"] == [ref["pdb_id"]] and ref["chain"] in data["_atom_site.auth_asym_id"]
            response = client.get("/api/structures/" + ref["pdb_id"] + ".cif")
            assert response.status_code == 200 and response.content == cif
        assert client.get("/api/structures/XXXX.cif").status_code == 404
        fragment = profile_input("CCO", protein["sequence"][:-1])
        assert fragment["protein"]["reference_structures"]["status"] == "no_match"


@pytest.mark.parametrize("comparison", [True, False])
def test_complex_download_uses_only_successful_run_artifact(tmp_path, monkeypatch, comparison):
    root = tmp_path / "jobs"
    monkeypatch.setenv("DTI_BOLTZ_RUNS_DIR", str(root))
    run_id = create_run({"smiles": "CCO", "protein_sequence": "ACDE"})["run_id"]
    result_path = run_dir(run_id) / "result.json"
    coordinate = root / ("a"*32) / "boltz_results_input" / "predictions" / "input" / "input_model_0.cif"
    coordinate.parent.mkdir(parents=True)
    coordinate.write_bytes(b"data_test")
    item = {"requested_model": "Boltz2", "status": "success", "artifacts": {"complex_cif": str(coordinate)}}
    def publish():
        result_path.write_text(json.dumps({"results": [item]} if comparison else item))
    url = f"/api/runs/{run_id}/complex.cif"
    with TestClient(create_app()) as client:
        assert client.get(url).status_code == 404
        publish()
        assert client.get(url).content == b"data_test"
        item["status"] = "error"
        publish()
        assert client.get(url).status_code == 404
        item.update(status="success", artifacts={"complex_cif": str(result_path)})
        publish()
        assert client.get(url).status_code == 404
