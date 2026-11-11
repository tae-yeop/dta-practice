"""Offline, sourced example pairs shared by the UI and agent request files."""

import json
from dti_tool.models import PROJECT


def load_examples():
    catalog = json.loads((PROJECT / "examples" / "catalog.json").read_text(encoding="utf-8"))
    examples = []
    for pair in catalog["pairs"]:
        compound = catalog["compounds"][str(pair["cid"])]
        target = catalog["targets"][pair["accession"]]
        examples.append({
            **pair,
            "label": f"{compound['name']} → {target['name']}",
            "compound": compound,
            "target": {key: value for key, value in target.items() if key != "sequence"},
            "input": {"smiles": compound["smiles"], "protein_sequence": target["sequence"], "device": "cpu"},
        })
    return {"schema_version": catalog["schema_version"], "retrieved_at": catalog["retrieved_at"],
            "description": catalog["description"], "examples": examples}
