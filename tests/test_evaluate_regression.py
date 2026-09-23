"""The v4 /api/evaluate contract must not change as the engine is extended.

Every field present in the recorded v4 snapshot must come back identical; new fields may be added.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from tests._evaluate_cases import cases

SNAPSHOT = json.loads(
    (Path(__file__).parent / "snapshots" / "evaluate_v4.json").read_text()
)
client = TestClient(app)


def _assert_superset(expected, actual, path="$"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        for k, v in expected.items():
            assert k in actual, f"{path}.{k} missing"
            _assert_superset(v, actual[k], f"{path}.{k}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            _assert_superset(e, a, f"{path}[{i}]")
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=1e-9), path
    else:
        assert actual == expected, path


CASES = list(cases())


@pytest.mark.parametrize(("key", "body"), CASES, ids=[key for key, _ in CASES])
def test_evaluate_matches_v4_snapshot(key, body):
    r = client.post("/api/evaluate", json=body)
    expected = SNAPSHOT[key]
    assert r.status_code == expected["status"]
    _assert_superset(expected["body"], r.json())
