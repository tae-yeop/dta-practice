"""Explicit public reference lookup with offline, pair-specific snapshots."""

import csv
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import urlencode

from .models import PROJECT

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PDBE = "https://www.ebi.ac.uk/pdbe/graph-api/uniprot/ligand_sites"
RCSB = "https://search.rcsb.org/rcsbsearch/v2/query"
MAX_ASSAYS = 8


def _read(url, *, tabular=False):
    import requests
    with requests.get(url, stream=True, timeout=(5, 12), headers={"User-Agent": "DTI-Lab/1.0"}) as response:
        if response.status_code == 404 and (url.startswith(PDBE) or b"PUGREST.NotFound" in response.raw.read(4096, decode_content=True)):
            return [] if tabular else {}
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("Public response exceeded 16 MiB.")
    if tabular:
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    return json.loads(raw) if raw.strip() else {}


def _identity(profile):
    compound, protein = profile["compound"], profile["protein"]
    drugs = profile["catalog"].get("compound", {}).get("matches", [])
    targets = profile["catalog"].get("protein", {}).get("matches", [])
    cid = drugs[0]["cid"] if len(drugs) == 1 else None
    accession = targets[0]["accession"] if len(targets) == 1 else None
    organism = targets[0].get("organism") if len(targets) == 1 else None
    if not accession:
        sequence = protein["sequence_used"]
        digest = hashlib.md5(sequence.encode()).hexdigest()
        url = "https://rest.uniprot.org/uniparc/search?" + urlencode({"query": "checksum:" + digest, "size": 2})
        candidates = {a for row in _read(url)["results"] if row["sequence"]["value"] == sequence
                      for a in row.get("uniProtKBAccessions", []) if "." not in a}
        if len(candidates) == 1:
            record = _read(f"https://rest.uniprot.org/uniprotkb/{candidates.pop()}.json")
            if record.get("sequence", {}).get("value") == sequence:
                accession = record["primaryAccession"]
                organism = record.get("organism", {}).get("scientificName")
    return cid, accession, organism


def _cid(compound):
    from .input_rules import parse_ligand
    from .models import ToolError
    key = compound.get("inchikey")
    if not key:
        return None
    data = _read(f"{PUG}/compound/inchikey/{key}/property/InChIKey,SMILES/JSON")
    for row in data.get("PropertyTable", {}).get("Properties", []):
        try:
            if row.get("InChIKey") == key and parse_ligand(row["SMILES"]).identity_smiles() == compound["identity_smiles"]:
                return row["CID"]
        except ToolError:
            continue
    return None


def _assay_context(name, organism):
    text = (name or "").lower()
    changes = re.findall(r"\b([acdefghiklmnpqrstvwy])\d{1,4}([acdefghiklmnpqrstvwy])\b", text)
    if re.search(r"mutant|mutated|variant", text) or any(before != after for before, after in changes):
        return "variant_mentioned"
    species = {"homo sapiens": ("human", "homo sapiens"), "mus musculus": ("mouse", "murine", "mus musculus"),
               "bos taurus": ("bovine", "bos taurus"), "rattus norvegicus": ("rat", "rattus norvegicus"),
               "escherichia coli": ("escherichia coli", "e. coli")}
    mentioned = {key for key, names in species.items() if any(re.search(r"\b" + re.escape(n) + r"\b", text) for n in names)}
    expected = next((key for key in species if (organism or "").lower().startswith(key)), None)
    if expected and mentioned - {expected}:
        return "organism_requires_review"
    scientific = (organism or "").lower()
    if (expected and expected in mentioned) or (scientific and scientific in text):
        return "species_supported"
    return "accession_only"


def _assays(profile, cid, accession, organism):
    if accession and not cid:
        cid = _cid(profile["compound"])
    if not cid or not accession:
        return {"status": "unresolved", "records": [], "cid": cid, "accession": accession}
    url = f"{PUG}/compound/cid/{cid}/assaysummary/CSV"
    summary = _read(url, tabular=True)
    targets_by_sample = defaultdict(set)
    rows = []
    for r in summary:
        targets_by_sample[r["AID"], r["SID"]].add(r.get("Target Accession"))
        if r["CID"] == str(cid) and r.get("Target Accession") == accession:
            rows.append(r)
    # Inspect original result tables to retain qualifiers and SID, including '>' / '<'.
    rows.sort(key=lambda r: not bool(r.get("Activity Value [uM]")))
    assays = defaultdict(list)
    for row in rows:
        assays[row["AID"]].append(row)
    records = []
    for index, (aid, samples) in enumerate(assays.items()):
        source = f"{PUG}/assay/aid/{int(aid)}/CSV?cid={int(cid)}"
        details = _read(source, tabular=True) if index < MAX_ASSAYS else []
        for row in samples:
            record = {"aid": aid, "cid": cid, "sid": row["SID"], "accession": accession,
                      "assay": row.get("Assay Name"), "outcome": row.get("Activity Outcome"),
                      "pmid": row.get("PubMed ID"), "source_url": source,
                      "match": "compound_target_accession", "construct": "not_verified",
                      "target_context": _assay_context(row.get("Assay Name"), organism)}
            row_targets = targets_by_sample[aid, row["SID"]]
            found = False
            for raw in details if len(row_targets) == 1 and not row.get("Panel Member ID") else ():
                if (raw.get("PUBCHEM_CID"), raw.get("PUBCHEM_SID")) != (str(cid), row["SID"]):
                    continue
                endpoint = raw.get("Standard Type")
                if endpoint != row.get("Activity Name") or not endpoint or not raw.get("Standard Value") or not raw.get("Standard Units"):
                    continue
                try:
                    value = float(raw["Standard Value"])
                except ValueError:
                    continue
                if math.isfinite(value):
                    found = True
                    records.append({**record, "kind": "quantitative", "endpoint": endpoint,
                                    "value": value, "unit": raw["Standard Units"], "relation": raw.get("Standard Relation"),
                                    "validity_comment": raw.get("Data Validity Comment")})
            if not found:
                kind = "summary_measurement" if row.get("Activity Value [uM]") else "reported_activity"
                records.append({**record, "kind": kind, "endpoint": row.get("Activity Name"),
                                "summary_value_um": row.get("Activity Value [uM]") or None})
    records = list({json.dumps(r, sort_keys=True): r for r in records}.values())
    return {"status": "matched" if records else "no_match", "cid": cid, "accession": accession,
            "source_url": url, "matched_assays": len(assays), "reviewed_assays": min(len(assays), MAX_ASSAYS),
            "records": records}


def _structures(profile, accession):
    key = profile["compound"].get("inchikey")
    if not accession or not key:
        return {"status": "unresolved", "records": []}
    query = {"query": {"type": "terminal", "service": "text_chem", "parameters": {
        "attribute": "rcsb_chem_comp_descriptor.InChIKey", "operator": "exact_match", "value": key}},
        "return_type": "mol_definition", "request_options": {"return_all_hits": True}}
    ligand_url = RCSB + "?" + urlencode({"json": json.dumps(query, separators=(",", ":"))})
    codes = {r["identifier"] for r in _read(ligand_url).get("result_set", [])}
    source = f"{PDBE}/{accession}"
    records = {}
    if codes:
        target = _read(source).get(accession, {})
        if target and target["sequence"] != profile["protein"]["sequence_used"]:
            return {"status": "unresolved", "reason": "sequence_mismatch", "source_url": source, "records": []}
        for ligand in target.get("data", []):
            ccd = ligand["accession"]
            if ccd not in codes:
                continue
            for site in ligand.get("residues", []):
                for entry in site.get("interactingPDBEntries", []):
                    pdb = entry["pdbId"].upper()
                    chains = entry["chainIds"]
                    chains = chains.split(",") if isinstance(chains, str) else chains
                    for chain in chains:
                        chain = chain.strip()
                        records[pdb, chain, ccd] = {"pdb_id": pdb, "chain": chain, "ccd": ccd, "accession": accession,
                            "match": "ligand_contact_on_mapped_target", "construct": "not_verified",
                            "source_url": f"https://www.rcsb.org/structure/{pdb}"}
    return {"status": "matched" if records else "no_match", "records": list(records.values()),
            "accession": accession, "ccd_matches": sorted(codes), "component_query": ligand_url, "source_url": source}


def _snapshot(path, pair_id):
    try:
        record = json.loads(path.read_bytes())
        if record["pair_id"] != pair_id or not isinstance(record["records"], list):
            raise ValueError("Evidence snapshot identity differs.")
        return record
    except FileNotFoundError:
        return {"status": "not_queried", "records": []}
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return {"status": "failed", "reason": str(exc), "records": []}


def public_evidence(profile, refresh=False):
    from .runs import write_json
    root = Path(os.environ.get("DTI_EVIDENCE_CACHE", PROJECT / "runs" / "public-evidence"))
    result = {}
    identity_error = None
    cid = accession = organism = None
    if refresh:
        try:
            cid, accession, organism = _identity(profile)
        except (OSError, ValueError, KeyError) as exc:
            identity_error = str(exc)
    lookups = {"assays": lambda: _assays(profile, cid, accession, organism),
               "structures": lambda: _structures(profile, accession)}
    for name, lookup in lookups.items():
        path = root / profile["pair_id"] / (name + ".json")
        failure_path = path.with_suffix(".failure.json")
        report = _snapshot(path, profile["pair_id"])
        failure = _snapshot(failure_path, profile["pair_id"])
        if refresh:
            try:
                if identity_error:
                    raise ValueError(identity_error)
                report = {**lookup(), "pair_id": profile["pair_id"], "retrieved_at": datetime.now(timezone.utc).isoformat()}
                destination, payload = path, report
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failure = {"status": "failed", "reason": str(exc), "records": [], "pair_id": profile["pair_id"],
                           "attempted_at": datetime.now(timezone.utc).isoformat()}
                destination, payload = failure_path, failure
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                write_json(destination, payload)
            except OSError as exc:
                payload["cache_error"] = str(exc)
        if failure.get("attempted_at", "") > report.get("retrieved_at", ""):
            report = ({**report, "refresh_error": failure["reason"], "attempted_at": failure["attempted_at"]}
                      if report.get("retrieved_at") else failure)
        result[name] = report
    return result
