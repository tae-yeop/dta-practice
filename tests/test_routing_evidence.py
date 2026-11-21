import json

from starlette.testclient import TestClient

from dti_tool import profile_input, route_models
from dti_tool.models import MODEL, MODELS, PROJECT
from dti_tool import public_evidence as evidence
from dti_web.app import create_app


def aspirin():
    request = json.loads((PROJECT / "examples/requests/aspirin-cox2.json").read_bytes())
    return {k: request[k] for k in ("smiles", "protein_sequence")}


def test_evidence_identity_qualifiers_and_offline_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_EVIDENCE_CACHE", str(tmp_path))
    def read(url, *, tabular=False):
        if "assaysummary" in url:
            row = {"AID":"17", "SID":"123", "CID":"2244", "Target Accession":"P35354",
                   "Assay Name":"Human COX-2 inhibition", "Activity Name":"IC50", "Activity Value [uM]":"5"}
            return [row, {**row, "SID":"987", "Target Accession":"P23219"}]
        if "aid/17" in url:
            return [{"PUBCHEM_CID":"2244", "PUBCHEM_SID":"123", "Standard Type":"IC50",
                     "Standard Value":"5", "Standard Units":"uM", "Standard Relation":">"}]
        if url.startswith(evidence.RCSB):
            return {"result_set":[{"identifier":"TEST"}]}
        return {"P35354":{"sequence":aspirin()["protein_sequence"], "data":[{"accession":"OTHER", "residues":[]},
            {"accession":"TEST","residues":[{"interactingPDBEntries":[{"pdbId":"1abc","chainIds":"A"}]}]}]}}
    monkeypatch.setattr(evidence, "_read", read)
    p = profile_input(**aspirin(), refresh_evidence=True)
    records = p["public_evidence"]["assays"]["records"]
    assert len(records) == 1 and records[0]["relation"] == ">"
    ready = dict.fromkeys(MODELS, "ready")
    plan = route_models(p, "measurements", endpoint="IC50", readiness=ready)
    assert plan["measurements"] == records and plan["selected_models"] == []
    assert route_models(p, "measurements", endpoint="Kd", readiness=ready)["action"] == "insufficient_evidence"
    records[0]["target_context"] = "organism_requires_review"
    review = route_models(p, "measurements", readiness=ready)
    assert review["action"] == "review_assays" and not review["measurements"]
    records[0]["target_context"] = "species_supported"
    assert route_models(p, "pose", readiness=ready)["structure_matches"][0]["chain"] == "A"
    def offline(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr(evidence, "_read", offline)
    assert profile_input(**aspirin())["public_evidence"] == p["public_evidence"]
    saved = profile_input(**aspirin(), refresh_evidence=True)["public_evidence"]["assays"]
    assert saved["records"] == records and saved["refresh_error"] == "offline"
    assert profile_input(**aspirin())["public_evidence"]["assays"] == saved
    assert evidence._assay_context("human A2A receptor", "Homo sapiens") == "species_supported"
    assert evidence._assay_context("bovine receptor", "Homo sapiens") == "organism_requires_review"


def test_route_budget_input_checkpoint_and_unsupported_goals(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_EVIDENCE_CACHE", str(tmp_path))
    p = profile_input(**aspirin())
    ready = dict.fromkeys(MODELS, "ready")
    assert route_models(p, "ranking", 180, readiness=ready)["selected_models"] == [MODEL]
    assert route_models(p, "ranking", 179, readiness=ready)["action"] == "no_candidate"
    assert route_models(p, "interaction", readiness=ready)["selected_models"] == ["ConPLex_v1_BindingDB"]
    assert route_models(p, "pose", readiness=ready)["action"] == "lookup_evidence"
    p["public_evidence"]["structures"]["status"] = "no_match"
    assert route_models(p, "pose", readiness=ready)["selected_models"] == ["Boltz2"]
    p["models"]["Boltz2"]["eligible"] = False
    assert route_models(p, "ic50_prediction", readiness=ready)["action"] == "no_candidate"
    assert route_models(p, "ranking", readiness={})["action"] == "no_candidate"
    assert route_models(p, "ranking", endpoint="IC50", readiness=ready)["status"] == "error"


def test_web_plan_reuses_profile_and_declines_obsolete_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_EVIDENCE_CACHE", str(tmp_path))
    with TestClient(create_app()) as client:
        args = aspirin()
        profile = client.post("/api/profile", json=args)
        token = profile.headers["x-profile-token"]
        def unexpected(*args, **kwargs):
            raise AssertionError("Cached input should be reused")
        monkeypatch.setattr("dti_tool.profiler.execute_profile", unexpected)
        plan = client.post("/api/route", json={**args, "purpose":"measurements"}, headers={"X-Profile-Token":token}).json()
        assert plan["action"] == "lookup_evidence"
        assert client.post("/api/runs", json=args, headers={"X-Route-Token":"expired"}).status_code == 409
        assert not client.get("/api/runs").json()["runs"]
