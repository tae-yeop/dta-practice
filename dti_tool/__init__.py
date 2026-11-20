"""Local, offline drug-target affinity tool."""

__version__ = "0.3.0"


def profile_input(smiles, protein_sequence):
    """Inspect input identity and per-model eligibility offline, without loading weights."""
    from .profiler import profile_input as profile
    return profile(smiles, protein_sequence)


def predict_dta(smiles, protein_sequence, model=None, device="cpu", models=None):
    """Return a JSON-serializable success/error envelope; never download weights."""
    from .core import predict_dta as predict
    return predict(smiles, protein_sequence, model, device, models)
