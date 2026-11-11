# DTI agent project

For requests to predict affinity from a small-molecule SMILES and protein sequence,
read and use `skills/predict-dta/SKILL.md`. The executable tool is `predict_dta`.
This project-local skill is routed through this file; it does not depend on a
globally installed skill or an already registered MCP server.

Keep model execution in `dti_tool`, and agent decision/interpretation guidance in
the skill. Add models only when requested. Keep raw predictions, endpoint
semantics, and calibration status distinct. Do not replace missing checkpoints
with randomly initialized weights or substitute mock results for predictions.

Use the project `.venv` for inference and `requirements/runtime.txt` for its
dependencies. Runtime downloads are an explicit setup command; prediction is
offline. Run `python -m pytest` after changing inference behavior.
