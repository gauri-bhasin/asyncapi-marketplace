import os
import sys
from pathlib import Path

import pytest

os.environ["SKIP_DB_INIT"] = "1"
sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.timeout(10)
def test_health_integration() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "db" in body
    assert "broker" in body
    assert "chroma" in body
