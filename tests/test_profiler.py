"""Offline profile contracts and boundary cases for later routing consumers."""

import json
import subprocess
import sys

import pytest

from dti_tool import profile_input
from dti_tool.core import validate_inputs
from dti_tool.models import MODEL, MODELS, PROJECT, ToolError
from dti_tool.profile_references import training_stages

SEQ = "ACDEFGHIK"


@pytest.fixture(autouse=True)
def isolated_references(monkeypatch):
    monkeypatch.delenv("DTI_PROFILE_REFERENCES", raising=False)


def test_identity_normalization_catalog_and_no_implicit_training_claim(monkeypatch, tmp_path):
    monkeypatch.setenv("DTI_MODEL_CACHE", str(tmp_path))
    monkeypatch.setattr("urllib.request.urlopen", lambda *args: pytest.fail("Network request"))
    request = json.loads((PROJECT / "examples/requests/acetazolamide-ca2.json").read_text())
    first = profile_input(request["smiles"], request["protein_sequence"])
    second = profile_input("  " + first["compound"]["identity_smiles"], request["protein_sequence"].lower() + "\n")
    assert first["pair_id"] == second["pair_id"]
    assert first["compound"]["formula"] == "C4H6N4O3S2"
    assert first["compound"]["murcko_scaffold"]
    assert first["protein"]["length"] == sum(first["protein"]["residue_counts"].values()) == 260
    assert second["original"]["protein_sequence"].endswith("\n")
    assert second["catalog"]["protein"]["matches"][0]["accession"] == "P00918"
    assert second["catalog"]["pair"]["matches"][0]["id"] == "acetazolamide-ca2"
    assert second["enrichment"]["experimental_assays_exact_pair"]["status"] == "not_queried"
    for name, item in second["models"].items():
        assert item["eligible"] and item["outputs"] == list(MODELS[name]["outputs"])
        assert item["training"]["supervised"]["overlap"]["pair"] == "unknown"
        assert item["applicability"]["ood_status"] == "not_assessed"
    fragment = profile_input(request["smiles"], request["protein_sequence"][1:])
    assert fragment["catalog"]["protein"]["status"] == fragment["catalog"]["pair"]["status"] == "no_match"


def test_representation_and_pair_identity_have_different_scopes():
    original = profile_input("C[C@H](O)F", SEQ)
    same = profile_input("F[C@@H](O)C", SEQ.lower())
    other = profile_input("C[C@@H](O)F", SEQ)
    assert original["pair_id"] == same["pair_id"] != other["pair_id"]
    assert original["models"][MODEL]["status"] == "fail"
    assert original["models"]["ConPLex_v1_BindingDB"]["status"] == "warn"
    assert profile_input("[CH3:7]CO", SEQ)["pair_id"] == profile_input("CCO", SEQ)["pair_id"]
    assert profile_input("C[NH3+]", SEQ)["pair_id"] != profile_input("CN", SEQ)["pair_id"]


@pytest.mark.parametrize("drug,sequence", [("CCO", "A" * n) for n in (800, 801, 1000, 1001, 1022, 1023)]
                         + [("C" * 129, SEQ), ("[2H]" + "C" * 128, SEQ), ("C1" + "C" * 399 + "1", SEQ)])
def test_model_checks_agree_with_prediction_and_keep_observations(drug, sequence):
    profile = profile_input(drug, sequence)
    assert profile["status"] == "success" and set(profile["models"]) == MODELS.keys()
    for name, row in profile["models"].items():
        failures = [check for check in row["checks"] if check["status"] == "fail"]
        if failures:
            with pytest.raises(ToolError) as error:
                validate_inputs(drug, sequence, name, "auto")
            assert not row["eligible"] and error.value.code == failures[0]["code"]
            assert all("observed" in check for check in failures)
        else:
            assert row["eligible"] and validate_inputs(drug, sequence, name, "auto")[0] == drug
    if drug.startswith("[2H]"):
        boltz = {c["rule"]: c for c in profile["models"]["Boltz2"]["checks"]}
        assert boltz["heavy_atoms"]["status"] == "pass"
        assert boltz["atoms_after_remove_hs"]["observed"] == 129


def test_invalid_components_are_reported_independently():
    both = profile_input("CCO.[Na+]", ">header\nAX")
    assert [e["code"] for e in both["errors"]] == ["UNSUPPORTED_MOLECULE", "UNSUPPORTED_SEQUENCE"]
    assert both["pair_id"] is None and both["models"] == {}
    one = profile_input("CCO", "AßA")
    assert one["status"] == "error" and one["compound"]["formula"] == "C2H6O"


def write_index(tmp_path, monkeypatch, **fields):
    monkeypatch.setenv("DTI_PROFILE_REFERENCES", str(tmp_path))
    path = tmp_path / MODEL / "supervised.json"
    path.parent.mkdir(exist_ok=True)
    data = {"schema_version": "1.0", "model": MODEL, "stage": "supervised",
            "checkpoint_sha256": training_stages(MODEL)["supervised"], "source": "test fixture",
            "version": "1", "coverage": "complete", "unit": "pair",
            "entries": [{"id": "a", "smiles": "CCO", "protein_sequence": SEQ},
                        {"id": "b", "smiles": "c1ccccc1", "protein_sequence": "WWWWW"}]}
    path.write_text(json.dumps({**data, **fields}))


@pytest.mark.parametrize("drug,seq,context", [("OCC", SEQ, "seen_pair"), ("CCO", "WWWWW", "new_pair"),
                                               ("CCN", SEQ, "cold_compound"), ("CCO", SEQ[1:], "cold_protein"),
                                               ("CCN", SEQ[1:], "cold_both")])
def test_checkpoint_overlap_and_true_neighbor_records(tmp_path, monkeypatch, drug, seq, context):
    write_index(tmp_path, monkeypatch)
    stage = profile_input(drug, seq)["models"][MODEL]["training"]["supervised"]
    assert stage["pair_context"] == context and stage["entries_checked"] == 2
    assert stage["nearest_compound"]["id"] == "a" and stage["manifest_sha256"]
    if seq == SEQ[1:]:
        best = stage["nearest_protein"]
        assert best["id"] == "a" and best["identity"] == best["query_coverage"] == 1
        assert best["reference_coverage"] == pytest.approx(8/9)
    if context == "new_pair":
        assert stage["nearest_compound"]["id"] != stage["nearest_protein"]["id"]
        assert stage["matching_entries"]["pair"] == []


def test_partial_index_and_rejected_manifest_never_imply_novelty(tmp_path, monkeypatch):
    write_index(tmp_path, monkeypatch, coverage="partial")
    stage = profile_input("CCN", SEQ)["models"][MODEL]["training"]["supervised"]
    assert stage["overlap"] == {"compound": "unknown", "protein": "seen", "pair": "unknown"}
    write_index(tmp_path, monkeypatch, checkpoint_sha256="stale")
    stage = profile_input("CCO", SEQ)["models"][MODEL]["training"]["supervised"]
    assert stage["lookup_status"] == "failed" and stage["pair_context"] == "unknown"
    write_index(tmp_path, monkeypatch, availability="unpublished")
    assert profile_input("CCO", SEQ)["models"][MODEL]["training"]["supervised"]["lookup_status"] == "unpublished"


def test_enrichment_provenance_and_no_match_are_scoped_to_source(tmp_path, monkeypatch):
    profile = profile_input("CCO", SEQ)
    root = tmp_path / "evidence"
    root.mkdir()
    kind = "experimental_assays_exact_pair"
    data = {"schema_version": "1.0", "kind": kind, "source": "fixture", "version": "1",
            "records": [{"reference_id": "test-record", "pair_id": profile["pair_id"],
                         "endpoint": "Ki", "relation": "<", "value": 10, "unit": "nM"}]}
    path = root / (kind + ".json")
    path.write_text(json.dumps(data))
    monkeypatch.setenv("DTI_PROFILE_REFERENCES", str(tmp_path))
    matched = profile_input("OCC", SEQ)["enrichment"][kind]
    assert matched["status"] == "matched" and matched["records"] == data["records"] and matched["sha256"]
    assert profile_input("CCN", SEQ)["enrichment"][kind]["status"] == "no_match"
    path.write_text("{")
    assert profile_input("CCO", SEQ)["enrichment"][kind]["status"] == "failed"


def test_cli_profile_without_model_imports_or_run(tmp_path):
    out = tmp_path / "profile.json"
    process = subprocess.run([sys.executable, "-m", "dti_tool", "profile", "--input", "examples/request.json",
                              "--output", str(out)], cwd=PROJECT, capture_output=True, check=True)
    assert json.loads(out.read_bytes()) == json.loads(process.stdout)
    program = ("import sys; from dti_tool import profile_input; assert profile_input('CCO', 'ACDE')['models']; "
               "assert not {'torch','DeepPurpose','transformers'} & set(sys.modules)")
    subprocess.run([sys.executable, "-c", program], cwd=PROJECT, check=True)
