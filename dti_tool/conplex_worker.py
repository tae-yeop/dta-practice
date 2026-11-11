"""ConPLex worker; local pinned code and weights only. No network operations."""

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    started = time.perf_counter()
    import numpy as np
    import torch
    import transformers
    from rdkit import Chem
    from importlib.metadata import version
    from transformers import AutoTokenizer, BertConfig, BertModel

    root = Path(request["model_dir"]).resolve()
    sys.path.insert(0, str(root / "source"))
    from conplex_dti.model.architectures import SimpleCoembeddingNoSigmoid
    from conplex_dti.featurizer import MorganFeaturizer

    sequence, drug, device = request["protein_sequence"], request["smiles"], request["device"]
    if not sequence or len(sequence) > 1022 or set(sequence) - set("ACDEFGHIKLMNPQRSTVWY"):
        raise ValueError("Sequence must contain 1..1022 canonical amino acids. Silent truncation is disabled.")
    if device == "cuda" and not torch.cuda.is_available():
        message = ("CUDA is unavailable in the ConPLex Python environment; "
                   "use device=auto or cpu, or install a compatible CUDA PyTorch build in that environment.")
        Path(request["output"]).write_text(json.dumps({"error": {
            "code": "DEVICE_UNAVAILABLE", "message": message}}, indent=2), encoding="utf-8")
        raise SystemExit(message)
    molecule = Chem.MolFromSmiles(drug)
    if molecule is None or molecule.GetNumAtoms() == 0 or len(Chem.GetMolFrags(molecule)) != 1:
        raise ValueError("ConPLex requires one valid connected molecule.")
    torch.set_num_threads(4)
    torch.manual_seed(61998)
    np.random.seed(61998)

    tokenizer = AutoTokenizer.from_pretrained(root / "prot_bert", do_lower_case=False, local_files_only=True)
    tokens = tokenizer(" ".join(sequence), return_tensors="pt", truncation=False).to(device)
    if tokens["input_ids"].shape[1] != len(sequence) + 2 or torch.any(tokens["input_ids"] == tokenizer.unk_token_id):
        raise ValueError("ProtBert tokenization did not preserve the complete sequence.")
    config = BertConfig.from_pretrained(root / "prot_bert", local_files_only=True)
    # Original checkpoint includes the MLM/NSP training heads. They do not
    # participate in feature extraction. Every encoder tensor loads strictly;
    # an unused pooler is deliberately not instantiated.
    encoder = BertModel(config, add_pooling_layer=False)
    state = torch.load(root / "prot_bert" / "pytorch_model.bin", map_location="cpu", weights_only=True)
    encoder_state = {key.removeprefix("bert."): value for key, value in state.items()
                     if key.startswith("bert.") and not key.startswith("bert.pooler.")}
    encoder.load_state_dict(encoder_state, strict=True)
    del state, encoder_state
    encoder.eval().to(device)
    with torch.inference_mode():
        hidden = encoder(**tokens).last_hidden_state
        protein = hidden[:, 1:len(sequence) + 1].mean(1).float()
    del encoder, hidden
    if device == "cuda":
        torch.cuda.empty_cache()
    if protein.shape != (1, 1024) or not torch.isfinite(protein).all():
        raise ValueError("ProtBert embedding is invalid.")
    feature = MorganFeaturizer(save_dir=Path(request["output"]).parent)(drug).reshape(1, -1).to(device)
    if feature.shape != (1, 2048) or not torch.isfinite(feature).all() or not torch.count_nonzero(feature):
        raise ValueError("Morgan encoding returned invalid or fallback features.")
    model = SimpleCoembeddingNoSigmoid(2048, 1024, 1024)
    model.load_state_dict(torch.load(root / "model.pt", map_location="cpu", weights_only=True), strict=True)
    model.eval().to(device)
    with torch.inference_mode():
        score = float(model(feature, protein).item())
    result = {"score": score, "execution": {"python": platform.python_version(), "torch": torch.__version__,
              "transformers": transformers.__version__, "numpy": np.__version__, "rdkit": version("rdkit"),
              "device": device, "seed": 61998, "cpu_threads": 4,
              "worker_elapsed_seconds": round(time.perf_counter() - started, 4)}}
    Path(request["output"]).write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
