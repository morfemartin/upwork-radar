from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar.config import load_config
from radar.ingest import ingest_dir

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def cfg():
    return load_config(ROOT / "examples" / "config")


@pytest.fixture(scope="session")
def jobs():
    return {j.id: j for j in ingest_dir(ROOT / "tests" / "fixtures" / "raw")}


@pytest.fixture
def now():
    return NOW
