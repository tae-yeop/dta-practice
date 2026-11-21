---
name: predict-dta
description: Run the local predict_dta tool for SMILES plus protein sequence using DTA, ConPLex DTI, or Boltz-2 structure and affinity models; report actual results and execution logs. Use for model predictions, not experimental affinity lookup.
---

# Predict DTA and DTI

The project root is two directories above this skill. Keep computation in the
`predict_dta` tool and use its returned evidence for interpretation.

For pre-inference questions, call `profile_input` with only `smiles` and
`protein_sequence` or run `python -m dti_tool profile --input request.json`
in the project environment. Each prediction run also saves the profile beside
its result. Use the model's observed checks, warnings and output endpoint with
the user's requested task. Training matches are scoped to the named checkpoint,
stage and manifest. Preserve unknown overlap and unassessed OOD in your answer.

For model choice call `route_models` (CLI: `route --input request.json`) with the
pair, purpose and optional budget_seconds. Use `measurements` plus optional
endpoint for reported assays, `pose` for structural evidence, `ranking` for
screening, `interaction` for an interaction score or `ic50_prediction` for
predicted IC50. Read the returned action and candidate reasons before running
a model. With public lookup requested, call `profile_input` with
`refresh_evidence: true` first. Preserve assay qualifiers, experiment context,
lookup coverage and uncertainty about the experimental construct.

| Model ID | Output | Execution |
| --- | --- | --- |
| `CNN_CNN_BindingDB` | Raw log-affinity; exact endpoint unverified | CPU default, SMILES ≤100 characters |
| `MPNN_CNN_BindingDB` | Raw log-affinity; exact endpoint unverified | CPU default, drug 2D graph |
| `ConPLex_v1_BindingDB` | Cosine interaction score, not binding probability | CPU default, Morgan + ProtBert |
| `Boltz2` | Predicted log10(IC50 in µM), separate binder probability and complex structure | CUDA default, local single-sequence mode |

Use `model` for one model or `models` for a requested comparison, never both.
Omitting both preserves the original CNN default. Do not silently add Boltz-2
to a cheap comparison: it predicts a complex and can take substantially longer.
`device: "auto"` uses each model's default above. Explicit `cpu` or `cuda` is
preserved; an unavailable device returns an error. Comparisons and CUDA jobs
are serialized to avoid loading multiple GPU models at once.

If a connected MCP server exposes `predict_dta`, call it with the actual inputs.
Otherwise write UTF-8 JSON and run the project-local CLI:

```json
{"smiles": "USER_SMILES", "protein_sequence": "USER_SEQUENCE", "model": "Boltz2", "device": "auto"}
```

```powershell
.venv\Scripts\python.exe -m dti_tool run --source agent --input runs/request.json --output runs/result.json
```

For a comparison replace `model` with, for example,
`"models": ["CNN_CNN_BindingDB", "MPNN_CNN_BindingDB", "ConPLex_v1_BindingDB"]`.
Use `.venv/bin/python` on Unix. `python -m dti_tool schema` gives the current
contract; `status` reports prepared artifacts and local runtime availability.

`run` loads this document, records its SHA-256, executes the tool, and writes
`runs/predictions/<run_id>/{request,result,run}.json` and `events.jsonl`.
Report `trace.run_id` or link its result and logs. The web UI at
`http://127.0.0.1:8765` shares this history. MCP records the same workflow.
Direct `predict` and Python calls record tool events only. `skill.loaded`
records a document load, not LLM reasoning; the web button runs a fixed local
workflow, while the requesting agent interprets these instructions.

Use one connected molecule and one plain sequence of canonical amino acids.
Whitespace/case normalization is recorded. Do not strip salts, stereochemistry,
choose a domain, or truncate an input silently. CNN/MPNN accept ≤1000 residues;
ConPLex's local cap is 1022; Boltz-2's local resource cap is 800. MPNN accepts
≤400 atoms, ≤800 directed bond slots including padding, ≤6 neighbors per atom.
Boltz-2 checks ≤128 ligand atoms after RDKit RemoveHs. These limits do not imply
that every accepted case fits the available GPU memory.

Boltz-2 currently uses `msa: empty`. Report this limitation and preserve
`quality.msa_mode`; neither MSA generation nor input upload is automatic.
Read [Boltz-2 setup and interpretation](../../docs/boltz2.md) for that model,
or [ConPLex setup and interpretation](../../docs/conplex.md) for ConPLex.
Known-pair workflow examples are in [the example catalog](../../examples/README.md);
they are not independent evaluation or calibration data.

Prediction is offline. For `MODEL_NOT_READY` or missing dependencies, read the
applicable setup instructions. Downloads happen only during explicit setup
(`prepare-model` / the adapter setup script), never as prediction fallback.
Missing weights, incomplete loading, or an unsupported input must return an
error, not a number from random or substituted parameters.

Single results use `status=success|error`. Comparisons store each complete
result in `results`, with `status=success|partial|error` and CLI exit codes
0/3/2. Report individual failures as well as successful models. Model events
are emitted as each selected model starts and finishes. A queued/running job
or a successful setup is not a completed prediction.

Report the model, raw value, scale, endpoint interpretation, warnings, and
calibration status. CNN/MPNN scores must not be relabelled pKd, IC50, nM or
probabilities. ConPLex's cosine score is not affinity or a probability; its
Morgan features do not distinguish stereoisomers. Boltz-2's documented IC50
scale is not Kd, and its binder probability is not locally validated calibration.
Structure confidence (pLDDT/ipTM etc.) is not an affinity confidence interval.
Preserve raw outputs; do not average unlike scores or invent an aggregate.
All current adapters have `uncertainty.status=not_calibrated`: no conformal
interval or DTI label should be invented. Actual execution success and
repeatability do not establish biological accuracy.
