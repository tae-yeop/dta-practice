"""Local, offline drug-target affinity tool."""

__version__ = "0.3.0"


def predict_dta(smiles, protein_sequence, model=None, device="cpu", models=None):
    """Return a JSON-serializable success/error envelope; never download weights."""
    from .core import predict_dta as predict
    return predict(smiles, protein_sequence, model, device, models)
