"""Input rules shared by the offline profiler and prediction adapters."""

from dataclasses import dataclass

from .models import ToolError, model_spec

AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
# DeepPurpose 0.1.5 CNN vocabulary, excluding the padding/unknown token.
SMILES_CHARS = frozenset("#%)(+-.1032547698=ACBEDGFIHKMLONPSRUTWVY[Z]_acbedgfihmlonsruty")


def normalize_sequence(value):
    if not isinstance(value, str) or not value.strip():
        raise ToolError("INVALID_ARGUMENT", "A nonempty protein sequence is required.")
    compact = "".join(value.split())
    sequence = compact.upper()
    if not compact.isascii() or set(sequence) - AMINO_ACIDS:
        raise ToolError("UNSUPPORTED_SEQUENCE", "Use a plain sequence of the 20 canonical amino acids without a FASTA header.")
    return sequence


@dataclass
class Ligand:
    smiles: str
    mol: object
    canonical: str

    def identity_smiles(self):
        from rdkit import Chem

        identity = Chem.Mol(self.mol)
        for atom in identity.GetAtoms():
            atom.SetAtomMapNum(0)
        return Chem.MolToCXSmiles(identity, Chem.SmilesWriteParams(), Chem.CXSmilesFields.CX_ENHANCEDSTEREO)


def parse_ligand(value):
    from rdkit import Chem, rdBase

    if not isinstance(value, str) or not value.strip():
        raise ToolError("INVALID_ARGUMENT", "A nonempty SMILES string is required.")
    smiles = value.strip()
    params = Chem.SmilesParserParams()
    params.parseName = False
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles, params)
    if mol is None or not mol.GetNumAtoms():
        raise ToolError("INVALID_SMILES", "RDKit could not parse and sanitize this SMILES.")
    if len(Chem.GetMolFrags(mol)) != 1 or any(a.GetAtomicNum() == 0 for a in mol.GetAtoms()):
        raise ToolError("UNSUPPORTED_MOLECULE", "Use one connected molecule without wildcard atoms. Salt stripping is not automatic.")
    return Ligand(smiles, mol, Chem.MolToSmiles(mol, isomericSmiles=True))


def input_checks(ligand, sequence, model):
    """Emit every applicable hard rule with the actual encoder input as observed."""
    from rdkit import Chem

    spec = model_spec(model)
    limits = spec["limits"]
    mol = ligand.mol
    checks = []

    def maximum(rule, observed, limit, message, code="INPUT_TOO_LONG"):
        checks.append({"rule": rule, "observed": observed, "maximum": limit,
                       "status": "pass" if observed <= limit else "fail",
                       "code": None if observed <= limit else code, "description": message})

    maximum("protein_residues", len(sequence), limits["protein_residues"],
            f"{model} accepts at most {limits['protein_residues']} residues.")
    if spec["drug_encoding"] == "CNN":
        maximum("smiles_characters", len(ligand.smiles), limits["smiles_characters"],
                f"Drug CNN limit: {limits['smiles_characters']} SMILES characters.")
        unknown = sorted(set(ligand.smiles) - SMILES_CHARS)
        checks.append({"rule": "unsupported_smiles_tokens", "observed": unknown, "allowed": [],
                       "status": "fail" if unknown else "pass", "code": "UNSUPPORTED_SMILES_TOKEN" if unknown else None,
                       "description": "The CNN vocabulary requires every character in the supplied SMILES to be supported."})
    if spec["drug_encoding"] == "MPNN":
        message = f"MPNN limits: {limits['atoms']} atoms and {limits['directed_bond_slots']} directed bond slots (2 per bond + 1 padding)."
        maximum("atoms", mol.GetNumAtoms(), limits["atoms"], message)
        maximum("directed_bond_slots", 2 * mol.GetNumBonds() + 1, limits["directed_bond_slots"], message)
        maximum("neighbors", max(a.GetDegree() for a in mol.GetAtoms()), limits["neighbors"],
                f"MPNN supports at most {limits['neighbors']} neighbors per atom.", "UNSUPPORTED_MOLECULE")
    if spec["provider"] == "boltz2":
        maximum("heavy_atoms", mol.GetNumHeavyAtoms(), limits["heavy_atoms"],
                f"{model} accepts at most {limits['heavy_atoms']} heavy ligand atoms.")
        maximum("atoms_after_remove_hs", Chem.RemoveHs(mol).GetNumAtoms(), limits["ligand_atoms"],
                f"Boltz-2 accepts at most {limits['ligand_atoms']} ligand atoms after RDKit RemoveHs.")
    return checks


def require_compatible(checks):
    for check in checks:
        if check["status"] == "fail":
            raise ToolError(check["code"], check["description"])
