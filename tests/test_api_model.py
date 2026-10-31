"""API tests for /api/model/* and the value_source switch of /api/evaluate and /api/robustness."""

import json
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.application.adjustments import apply_project_params
from app.application.prediction import FEATURE_NAMES, expert_baseline
from app.data.interchange_data import INTERCHANGE_DATA, get_alternatives_for_context
from app.data.prediction_defaults import MAX_UPLOAD_BYTES, TARGETS
from app.data.uncertainty_defaults import DEFAULT_VALUE_UNCERTAINTY
from app.infrastructure.corpus import get_store, llm_extraction, reset_store
from app.infrastructure.corpus import store as store_module
from backend import model_routes
from backend.main import app
from backend.schemas import ProjectParams
from tests._evaluate_cases import CONTEXTS, PARAM_SETS

ADMIN_TOKEN = "test-admin-token-0123456789"
client = TestClient(app, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
anonymous = TestClient(app)
DEMO_CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "documents"
SYSTEM = "System (Highway + Highway)"
CSV = (b"interchange_type,aadt,num_lanes,construction_cost_mln,throughput_vph\n"
       b"Turbine,60000,3,70,8000\nDDI,40000,2,17,5600\nDiamond,30000,2,11,2600\n")
REPORT = "Interchange type: Turbine\nAADT: 60 000\nConstruction cost: $52M\n".encode()


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Never reach the Claude API from tests, whatever the developer's environment says."""
    monkeypatch.delenv("TDSS_LLM_EXTRACTION", raising=False)


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    """Corpus editing on, with the token ``client`` sends."""
    monkeypatch.setenv("TDSS_ADMIN_TOKEN", ADMIN_TOKEN)


@pytest.fixture
def corpus(tmp_path):
    """Point the API's corpus store at an empty temporary directory; restore the default after."""
    directory = tmp_path / "documents"
    directory.mkdir()
    reset_store(directory)
    yield directory
    reset_store()


@pytest.fixture
def demo_corpus(corpus):
    """The temporary corpus filled with a copy of the shipped synthetic demo documents."""
    shutil.copytree(DEMO_CORPUS, corpus, dirs_exist_ok=True)
    return corpus


def upload(name, data, **params):
    return client.post("/api/model/documents", params=params,
                       files={"file": (name, data, "application/octet-stream")})


def eval_body(context=SYSTEM, params=None, **extra):
    return {"context": context, "weights": {}, "params": params or {}, **extra}


# ---------------------------------------------------------------------------
# Status / retrain
# ---------------------------------------------------------------------------


def test_status_of_empty_corpus(corpus):
    r = client.get("/api/model/status")
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"trained_at", "train_ms", "revision", "n_records", "n_synthetic",
                         "documents", "criteria", "coefficients", "interval_level",
                         "llm_available", "pdf_available", "editing_enabled"}
    assert data["n_records"] == data["n_synthetic"] == 0 and data["documents"] == []
    assert datetime.fromisoformat(data["trained_at"]).tzinfo is not None
    assert data["train_ms"] >= 0 and data["interval_level"] == 0.9
    assert data["llm_available"] is False and isinstance(data["pdf_available"], bool)
    assert set(data["criteria"]) == set(data["coefficients"]) == set(TARGETS)
    for c in TARGETS:
        assert data["criteria"][c]["n_obs"] == 0 and data["criteria"][c]["noise_sd"] > 0
        for metric in ("loo_mape_expert", "loo_mape_model", "coverage90"):
            assert data["criteria"][c][metric] is None
        assert [row["feature"] for row in data["coefficients"][c]] == list(FEATURE_NAMES)
        assert all(row["mean"] == 0 and row["sd"] > 0 for row in data["coefficients"][c])


def test_status_of_demo_corpus(demo_corpus):
    data = client.get("/api/model/status").json()
    assert data["n_records"] == data["n_synthetic"] > 50
    names = {d["name"] for d in data["documents"]}
    assert "synthetic_precedents.csv" in names
    for doc in data["documents"]:
        assert set(doc) == {"name", "kind", "synthetic", "records", "extractor", "warnings",
                            "size_bytes"}
        assert doc["synthetic"] and doc["records"] > 0 and doc["size_bytes"] > 0
        assert doc["kind"] in ("csv", "json", "text", "pdf")
        assert doc["extractor"] == ("table" if doc["kind"] in ("csv", "json") else "rules")
    for c in TARGETS:
        m = data["criteria"][c]
        assert m["n_obs"] >= 3
        assert 0 <= m["loo_mape_expert"] and 0 <= m["loo_mape_model"]
        assert 0 <= m["coverage90"] <= 1


def test_revision_changes_on_every_refit_even_within_a_second(corpus):
    first = client.post("/api/model/retrain").json()
    second = upload("projects.csv", CSV).json()
    third = client.post("/api/model/retrain").json()
    assert first["revision"] < second["revision"] < third["revision"]
    assert client.get("/api/model/status").json()["revision"] == third["revision"]


def test_retrain_picks_up_documents_added_on_disk(corpus):
    assert client.get("/api/model/status").json()["n_records"] == 0
    (corpus / "projects.csv").write_bytes(CSV)
    assert client.get("/api/model/status").json()["n_records"] == 0   # still the cached fit
    r = client.post("/api/model/retrain")
    assert r.status_code == 200
    assert r.json()["n_records"] == 3
    assert client.get("/api/model/status").json()["n_records"] == 3


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def test_upload_overwrite_and_delete(corpus):
    r = upload("projects.csv", CSV)
    assert r.status_code == 200
    data = r.json()
    assert data["n_records"] == 3 and data["n_synthetic"] == 0
    [doc] = data["documents"]
    assert doc == {"name": "projects.csv", "kind": "csv", "synthetic": False, "records": 3,
                   "extractor": "table", "warnings": doc["warnings"], "size_bytes": len(CSV)}
    assert (corpus / "projects.csv").read_bytes() == CSV

    r = upload("projects.csv", CSV)
    assert r.status_code == 409 and "already exists" in r.json()["detail"]

    one_row = b"\n".join(CSV.splitlines()[:2]) + b"\n"
    r = upload("projects.csv", one_row, overwrite=True)
    assert r.status_code == 200 and r.json()["n_records"] == 1

    r = client.delete("/api/model/documents/projects.csv")
    assert r.status_code == 200
    assert r.json()["n_records"] == 0 and r.json()["documents"] == []
    assert not (corpus / "projects.csv").exists()
    assert client.delete("/api/model/documents/projects.csv").status_code == 404


def test_upload_text_report_and_synthetic_flag(corpus):
    data = upload("synthetic_turbine.md", REPORT).json()
    [doc] = data["documents"]
    assert doc["kind"] == "text" and doc["extractor"] == "rules" and doc["records"] == 1
    assert doc["synthetic"] and data["n_synthetic"] == 1
    assert any("imputed" in w or "reference" in w for w in doc["warnings"])


def test_upload_json_document(corpus):
    records = [{"type": "SPUI", "cost": 21, "aadt": 50000},
               {"type": "DDI", "land_area_hectares": 6.1}]
    data = upload("p.json", json.dumps({"records": records}).encode()).json()
    assert data["documents"][0]["kind"] == "json" and data["n_records"] == 2


@pytest.mark.parametrize(
    "name",
    ["../evil.csv", "a/b.csv", "..\\evil.csv", "notes.docx", "archive.zip", ".hidden.csv",
     "no_extension"],
)
def test_upload_rejects_bad_names(corpus, name):
    r = upload(name, CSV)
    assert r.status_code == 400
    assert list(corpus.iterdir()) == []
    assert not (corpus.parent / "evil.csv").exists()


def test_upload_rejects_empty_file(corpus):
    r = upload("empty.csv", b"")
    assert r.status_code == 400 and "empty" in r.json()["detail"]


def test_upload_rejects_files_over_the_limit(corpus):
    r = upload("big.csv", b"x" * (MAX_UPLOAD_BYTES + 1))
    assert r.status_code == 413
    assert list(corpus.iterdir()) == []


def test_upload_limit_boundary(corpus, monkeypatch):
    monkeypatch.setattr(model_routes, "MAX_UPLOAD_BYTES", len(CSV))
    monkeypatch.setattr(store_module, "MAX_UPLOAD_BYTES", len(CSV))
    assert upload("exact.csv", CSV).status_code == 200
    assert upload("over.csv", CSV + b"\n").status_code == 413


@pytest.mark.parametrize("path", ["..%2Fsecret.csv", "a%2Fb.csv", "%2E%2E", "a%5Cb.csv"])
def test_delete_rejects_unsafe_names(corpus, path):
    secret = corpus.parent / "secret.csv"
    secret.write_bytes(CSV)
    r = client.delete(f"/api/model/documents/{path}")
    assert r.status_code == 400
    assert secret.exists()


def test_delete_missing_document(corpus):
    r = client.delete("/api/model/documents/missing.csv")
    assert r.status_code == 404 and "not found" in r.json()["detail"]


class _FakeMessages:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        block = SimpleNamespace(type="text", text=json.dumps(self.payload))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


def test_llm_fallback_through_the_api_with_a_mocked_client(corpus, monkeypatch):
    record = {"name": "Prose trumpet", "interchange_type": "Trumpet", "aadt": 30000,
              "num_lanes": None, "design_speed": None, "terrain": None, "env_sensitivity": None,
              "construction_cost_mln": 13.0, "land_area_hectares": None,
              "throughput_vph": None, "safety_index": None, "year": 2019, "country": None}
    messages = _FakeMessages({"records": [record]})
    monkeypatch.setattr(store_module, "llm_available", lambda: True)
    monkeypatch.setattr(llm_extraction, "_default_client",
                        lambda: SimpleNamespace(messages=messages))
    monkeypatch.setattr(llm_extraction, "_cache", {})

    data = upload("prose.txt", b"A trumpet that cost thirteen million dollars in 2019.").json()
    [doc] = data["documents"]
    assert doc["extractor"] == "llm" and doc["records"] == 1
    assert data["llm_available"] is True and data["n_records"] == 1
    [call] = messages.calls
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "thirteen million" in call["messages"][0]["content"]

    # The rules come first: a document they can read never reaches the LLM.
    data = upload("report.md", REPORT).json()
    assert {d["name"]: d["extractor"] for d in data["documents"]}["report.md"] == "rules"
    assert len(messages.calls) == 1   # prose.txt answered from the in-memory cache


# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------


def test_predict_unknown_context(corpus):
    r = client.post("/api/model/predict", json={"context": "Nowhere", "params": {}})
    assert r.status_code == 404


def test_predict_rejects_non_positive_aadt(corpus):
    r = client.post("/api/model/predict", json={"context": SYSTEM, "params": {"aadt": 0}})
    assert r.status_code == 422


@pytest.mark.parametrize("context", CONTEXTS)
@pytest.mark.parametrize("pname", list(PARAM_SETS))
def test_predict_on_empty_corpus_returns_the_expert_values(corpus, context, pname):
    params = PARAM_SETS[pname]
    r = client.post("/api/model/predict", json={"context": context, "params": params})
    assert r.status_code == 200
    data = r.json()
    assert data["context"] == context and data["n_records"] == 0
    assert data["interval_level"] == 0.9
    assert [a["name"] for a in data["alternatives"]] == list(INTERCHANGE_DATA[context])
    for alt in data["alternatives"]:
        baseline = expert_baseline(alt["name"], ProjectParams(**params))
        assert set(alt["values"]) == set(TARGETS)
        for c, v in alt["values"].items():
            assert v["expert"] == v["predicted"] == baseline[c]
            assert v["low"] < v["predicted"] and (v["high"] > v["predicted"] or v["high"] == 10)


def test_predict_with_documents_corrects_the_expert_values(demo_corpus):
    params = {"aadt": 90000, "num_lanes": 3, "terrain": "Rolling"}
    data = client.post("/api/model/predict", json={"context": SYSTEM, "params": params}).json()
    assert data["n_records"] > 50
    model = get_store().model
    changed = 0
    for alt in data["alternatives"]:
        assert alt["values"] == model.predict(alt["name"], ProjectParams(**params))
        for c, v in alt["values"].items():
            assert v["low"] <= v["predicted"] <= v["high"]
            changed += v["predicted"] != v["expert"]
            if c == "safety_index":
                assert 1 <= v["low"] and v["high"] <= 10
    assert changed > 0


# ---------------------------------------------------------------------------
# Evaluate with value_source
# ---------------------------------------------------------------------------


def _without(data, *keys):
    return {k: v for k, v in data.items() if k not in keys}


def test_value_source_defaults_to_expert_and_never_touches_the_corpus(corpus, monkeypatch):
    def boom():
        raise AssertionError("the expert path must not train the model")

    monkeypatch.setattr(get_store(), "retrain", boom)
    data = client.post("/api/evaluate", json=eval_body()).json()
    assert data["value_source"] == "expert"
    assert all(n["kind"] != "model" for n in data["adjustments"])
    explicit = client.post("/api/evaluate", json=eval_body(value_source="expert")).json()
    assert explicit == data


def test_unknown_value_source_is_rejected():
    assert client.post("/api/evaluate", json=eval_body(value_source="oracle")).status_code == 422


@pytest.mark.parametrize("context", CONTEXTS)
@pytest.mark.parametrize("pname", list(PARAM_SETS))
def test_model_on_empty_corpus_evaluates_like_expert(corpus, context, pname):
    body = eval_body(context, PARAM_SETS[pname], methods=["wsm", "topsis", "vikor"])
    expert = client.post("/api/evaluate", json=body)
    model = client.post("/api/evaluate", json={**body, "value_source": "model"})
    assert model.status_code == expert.status_code
    if expert.status_code != 200:
        return
    e, m = expert.json(), model.json()
    assert m["value_source"] == "model"
    assert _without(m, "value_source", "adjustments") == _without(e, "value_source", "adjustments")
    note, *rest = m["adjustments"]
    assert note["kind"] == "model" and "no training records" in note["message"]
    assert rest == e["adjustments"]


def test_model_values_differ_from_expert_when_documents_exist(demo_corpus):
    params = {"aadt": 90000, "num_lanes": 3, "terrain": "Rolling", "budget": 500,
              "land_limit": 200}
    expert = client.post("/api/evaluate", json=eval_body(params=params)).json()
    model = client.post("/api/evaluate",
                        json=eval_body(params=params, value_source="model")).json()
    assert model["value_source"] == "model"
    raw = lambda d: {r["alternative_name"]: r["raw_values"] for r in d["results"]}  # noqa: E731
    assert raw(model) != raw(expert)
    n = client.get("/api/model/status").json()["n_records"]
    note = model["adjustments"][0]
    assert note["kind"] == "model"
    assert f"{n} project records (all synthetic demo data)" in note["message"]


def test_model_correction_runs_before_the_site_rules(demo_corpus):
    params = ProjectParams(aadt=110000, peak_factor=12, num_lanes=1, design_speed=120,
                           terrain="Mountainous", env_sensitivity="High",
                           budget=1000, land_limit=1000)
    data = client.post("/api/evaluate", json=eval_body(
        params=params.model_dump(), value_source="model")).json()
    model = get_store().model

    def corrected_constants(alt):
        values = model.correct_values(alt.name, alt.raw_values, params)
        return {c: round(v, 0 if c == "throughput_vph" else 2) for c, v in values.items()}

    corrected = [replace(alt, raw_values=corrected_constants(alt))
                 for alt in get_alternatives_for_context(SYSTEM)]
    expected, _ = apply_project_params(corrected, params)
    got = {r["alternative_name"]: r["raw_values"] for r in data["results"]}
    assert got == {a.name: a.raw_values for a in expected}
    kinds = [n["kind"] for n in data["adjustments"]]
    assert kinds[0] == "model" and "terrain" in kinds and "traffic_demand" in kinds


def test_model_values_go_through_the_feasibility_filter(demo_corpus):
    params = {"budget": 60.0, "land_limit": 25.0}
    data = client.post("/api/evaluate", json=eval_body(params=params, value_source="model"))
    assert data.status_code == 200
    for r in data.json()["results"]:
        assert r["raw_values"]["construction_cost_mln"] <= 60.0
        assert r["raw_values"]["land_area_hectares"] <= 25.0


def test_evaluate_with_model_rejects_non_positive_aadt(corpus):
    r = client.post("/api/evaluate", json=eval_body(params={"aadt": 0}, value_source="model"))
    assert r.status_code == 422
    assert client.post("/api/evaluate", json=eval_body(params={"aadt": 0})).status_code == 200


# ---------------------------------------------------------------------------
# Robustness with value_source
# ---------------------------------------------------------------------------


def robustness(params=None, values=None, **extra):
    body = eval_body(params=params, methods=["wsm"],
                     uncertainty={"iterations": 100, "values": values or {}}, **extra)
    r = client.post("/api/robustness", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _defaults():
    return {c: {"low": lo, "high": hi, "distribution": dist}
            for c, (lo, hi, dist) in DEFAULT_VALUE_UNCERTAINTY.items()}


def test_robustness_expert_keeps_the_default_ranges(corpus):
    data = robustness()
    assert data["value_source"] == "expert"
    assert data["value_uncertainty"] == _defaults()


def test_robustness_with_model_uses_and_reports_model_ranges(demo_corpus):
    params = {"aadt": 70000, "terrain": "Rolling"}
    data = robustness(params, value_source="model")
    assert data["value_source"] == "model"
    expected = get_store().model.value_ranges(data["alternatives"], ProjectParams(**params))
    assert set(data["value_uncertainty"]) == set(TARGETS)
    for c, (low, high) in expected.items():
        used = data["value_uncertainty"][c]
        assert used["distribution"] == "triangular"
        assert (used["low"], used["high"]) == pytest.approx((low, high))
        assert 0 < used["low"] <= 1 <= used["high"] <= 10
    assert data["value_uncertainty"] != _defaults()
    model_notes = [n["message"] for n in data["adjustments"] if n["kind"] == "model"]
    assert len(model_notes) == 2 and "90 % prediction intervals" in model_notes[1]


def test_robustness_overrides_beat_model_ranges(demo_corpus):
    override = {"low": 0.9, "high": 1.3, "distribution": "uniform"}
    data = robustness(values={"construction_cost_mln": override}, value_source="model")
    assert data["value_uncertainty"]["construction_cost_mln"] == override
    expected = get_store().model.value_ranges(data["alternatives"], ProjectParams())
    low, high = expected["safety_index"]
    assert data["value_uncertainty"]["safety_index"]["low"] == pytest.approx(low)
    note = data["adjustments"][-1]
    assert note["kind"] == "model" and "Safety Index" in note["message"]
    assert "Construction Cost" not in note["message"]


def test_robustness_with_model_on_empty_corpus_keeps_the_default_ranges(corpus):
    # Without observations the model interval is only the prior: robustness must then match the
    # expert mode exactly, like the evaluated values do.
    data = robustness(value_source="model")
    assert data["value_uncertainty"] == _defaults()
    assert [n["kind"] for n in data["adjustments"]].count("model") == 1


def test_robustness_takes_model_ranges_only_for_observed_criteria(corpus):
    upload("costs.csv", b"interchange_type,aadt,construction_cost_mln\n"
                        b"Turbine,60000,52\nStack (4-Level),80000,95\nCloverleaf,30000,16\n")
    data = robustness(value_source="model")
    defaults = _defaults()
    assert data["value_uncertainty"]["construction_cost_mln"] != defaults["construction_cost_mln"]
    for c in ("land_area_hectares", "throughput_vph", "safety_index"):
        assert data["value_uncertainty"][c] == defaults[c]
    note = data["adjustments"][-1]
    assert note["kind"] == "model" and "Construction Cost" in note["message"]
    assert "Land Area" not in note["message"]


# ---------------------------------------------------------------------------
# Admin token
# ---------------------------------------------------------------------------


WRITES = [
    ("post", "/api/model/retrain", {}),
    ("post", "/api/model/documents", {"files": {"file": ("x.csv", CSV, "text/csv")}}),
    ("delete", "/api/model/documents/projects.csv", {}),
    ("get", "/api/model/auth", {}),
]


@pytest.mark.parametrize("method,url,kwargs", WRITES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-token-0123456789"},
                                     {"Authorization": ADMIN_TOKEN}])
def test_writes_need_the_admin_token(corpus, method, url, kwargs, headers):
    (corpus / "projects.csv").write_bytes(CSV)
    r = getattr(anonymous, method)(url, headers=headers, **kwargs)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert (corpus / "projects.csv").exists() and not (corpus / "x.csv").exists()


@pytest.mark.parametrize("token", [None, "", "short"])
@pytest.mark.parametrize("method,url,kwargs", WRITES)
def test_writes_are_disabled_without_a_server_token(corpus, monkeypatch, method, url, kwargs,
                                                    token):
    if token is None:
        monkeypatch.delenv("TDSS_ADMIN_TOKEN")
    else:
        monkeypatch.setenv("TDSS_ADMIN_TOKEN", token)
    r = getattr(client, method)(url, **kwargs)
    assert r.status_code == 403
    assert client.get("/api/model/status").json()["editing_enabled"] is False


def test_reads_stay_public_and_report_editing(corpus):
    assert anonymous.get("/api/model/auth").status_code == 401
    assert client.get("/api/model/auth").status_code == 204
    status = anonymous.get("/api/model/status")
    assert status.status_code == 200 and status.json()["editing_enabled"] is True
    r = anonymous.post("/api/model/predict", json={"context": SYSTEM})
    assert r.status_code == 200
