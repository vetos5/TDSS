"""Regenerate tests/snapshots/evaluate_v4.json (run only to deliberately accept new output)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from tests._evaluate_cases import cases

client = TestClient(app)
out = {}
for key, body in cases():
    r = client.post("/api/evaluate", json=body)
    out[key] = {"status": r.status_code, "body": r.json()}
Path(__file__).with_name("snapshots").joinpath("evaluate_v4.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True)
)
print(len(out), "cases")
