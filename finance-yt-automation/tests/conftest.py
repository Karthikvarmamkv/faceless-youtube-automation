import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finance_channel.config import Config  # noqa: E402


@pytest.fixture
def config(tmp_path):
    cfg = Config.load(ROOT / "config.example.yaml")
    cfg._data["workdir"] = str(tmp_path / "data")
    return cfg
