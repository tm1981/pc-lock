import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def app_dir(tmp_path, monkeypatch):
    """Every test gets its own data folder: real config/schedule are never touched."""
    monkeypatch.setenv('PCLOCK_APP_DIR', str(tmp_path))
    return tmp_path
