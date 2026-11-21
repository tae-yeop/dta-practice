"""Keep test artifacts in the writable project, without shared temp cleanup."""

from pathlib import Path
import tempfile
import pytest


@pytest.fixture(autouse=True)
def isolated_run_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DTI_RUNS_DIR", str(tmp_path / "predictions"))
    monkeypatch.setenv("DTI_EVIDENCE_CACHE", str(tmp_path / "public-evidence"))


def pytest_configure(config):
    if config.option.basetemp is None:
        root = Path(__file__).resolve().parents[1] / "runs" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = tempfile.mkdtemp(prefix="pytest-", dir=root)
