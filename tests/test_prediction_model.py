"""Tests for the Bayesian residual-correction model and the corpus store."""

import threading

import numpy as np
import pytest
from scipy.stats import t as student_t

from app.application.adjustments import apply_project_params
from app.application.dss_engine import Alternative
from app.application.prediction import (
    FEATURE_NAMES,
    INTERCHANGE_TYPES,
    Conditions,
    ResidualModel,
    build_training_data,
    cross_validate,
    expert_baseline,
    features,
    fit_nig,
    fit_robust,
    prior_hyperparameters,
    validate_record,
)
from app.application.prediction.model import _folds
from app.data.adjustment_rules import LOOP_RAMP_ALTERNATIVES
from app.data.interchange_data import INTERCHANGE_DATA, get_alternatives_for_context
from app.data.prediction_defaults import (
    OUTLIER_WEIGHT,
    PRIOR_SIGMA0,
    PRIOR_TAU_SLOPE,
    PRIOR_TAU_TYPE,
    TARGETS,
)
from app.infrastructure.corpus import (
    CorpusStore,
    DocumentExists,
    DocumentNotFound,
    DocumentTooLarge,
    EmptyDocument,
    InvalidDocumentName,
    UnsupportedDocumentType,
    get_store,
    reset_store,
)
from app.infrastructure.corpus import store as store_module
from backend.schemas import ProjectParams
from scripts.make_synthetic_corpus import TRUE_EFFECTS, generate_rows

CONDITIONS = [
    {},
    {"aadt": 90000, "num_lanes": 3, "design_speed": 120, "terrain": "Mountainous",
     "env_sensitivity": "Critical"},
    {"aadt": 15000, "num_lanes": 1, "design_speed": 60, "terrain": "Rolling",
     "env_sensitivity": "Medium"},
    {"aadt": 45000, "num_lanes": 2, "design_speed": 130, "terrain": "Flat",
     "env_sensitivity": "High"},
]


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Never reach the Claude API from tests, whatever the developer's environment says."""
    monkeypatch.delenv("TDSS_LLM_EXTRACTION", raising=False)


def synthetic_records(n, seed):
    rows = generate_rows(n, np.random.default_rng(seed))
    records = [validate_record(row, source="synthetic_test.csv")[0] for row in rows]
    assert all(r is not None for r in records)
    return records


@pytest.fixture(scope="module")
def big_model():
    return ResidualModel.fit(synthetic_records(300, seed=1))


# ---------------------------------------------------------------------------
# Expert baseline and features
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cond", CONDITIONS)
@pytest.mark.parametrize("context", list(INTERCHANGE_DATA))
def test_baseline_equals_expert_pipeline(context, cond):
    params = ProjectParams(**cond, peak_factor=0, budget=1e9, land_limit=1e9)
    if not cond:
        params = ProjectParams(env_sensitivity="Low", peak_factor=0, budget=1e9, land_limit=1e9)
    adjusted, _ = apply_project_params(get_alternatives_for_context(context), params)
    for alt in adjusted:
        assert expert_baseline(alt.name, params) == {c: alt.raw_values[c] for c in TARGETS}


def test_reference_conditions_reproduce_the_constants():
    for alternatives in INTERCHANGE_DATA.values():
        for name, values in alternatives.items():
            expected = dict(values)
            if name in LOOP_RAMP_ALTERNATIVES:  # 100 km/h is above the 80 km/h loop threshold
                expected["safety_index"] = round(values["safety_index"] * 0.9, 2)
            assert expert_baseline(name) == expected


def test_features():
    assert len(FEATURE_NAMES) == 16
    assert FEATURE_NAMES[:8] == tuple(f"type:{t}" for t in INTERCHANGE_TYPES)
    assert FEATURE_NAMES[8:] == ("log_aadt", "lanes", "speed", "terrain:Rolling",
                                 "terrain:Mountainous", "env:Medium", "env:High", "env:Critical")
    x = features("DDI")
    assert x.tolist() == [0, 0, 0, 0, 0, 1, 0, 0] + [0] * 8
    x = dict(zip(FEATURE_NAMES, features(
        "Trumpet", {"aadt": 90000, "num_lanes": 4, "design_speed": 60, "terrain": "рівнинний",
                    "env_sensitivity": "critical"}), strict=True))
    assert x["type:Trumpet"] == 1 and x["log_aadt"] == pytest.approx(np.log(2))
    assert (x["lanes"], x["speed"], x["env:Critical"]) == (2, -2, 1)
    assert x["terrain:Rolling"] == x["terrain:Mountainous"] == 0


def test_conditions_from_project_params():
    cond = Conditions.of(ProjectParams(aadt=60000, num_lanes=3, terrain="Rolling"))
    assert cond == Conditions(aadt=60000, num_lanes=3, design_speed=100, terrain="Rolling",
                              env_sensitivity="Medium")
    assert Conditions.of(None) == Conditions.of({}) == Conditions()


# ---------------------------------------------------------------------------
# Empty corpus = expert values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cond", CONDITIONS)
def test_no_records_reproduces_expert_values_exactly(cond):
    model = ResidualModel.fit([])
    for name in INTERCHANGE_TYPES:
        prediction = model.predict(name, cond)
        baseline = expert_baseline(name, cond)
        for criterion in TARGETS:
            p = prediction[criterion]
            assert p["predicted"] == p["expert"] == baseline[criterion]
            assert p["low"] < p["predicted"] or criterion == "safety_index"
            assert p["high"] >= p["predicted"]
        raw = INTERCHANGE_DATA[next(c for c in INTERCHANGE_DATA if name in INTERCHANGE_DATA[c])]
        assert model.correct_values(name, raw[name], cond) == raw[name]
        assert {c.factor for c in model.corrections(name, cond).values()} == {1.0}


def test_prior_coefficients_and_noise():
    model = ResidualModel.fit([])
    for criterion, coefs in model.coefficients().items():
        assert [c["feature"] for c in coefs] == list(FEATURE_NAMES)
        assert all(c["mean"] == 0 for c in coefs)
        sds = [c["sd"] for c in coefs]
        assert sds == pytest.approx([PRIOR_TAU_TYPE] * 8 + [PRIOR_TAU_SLOPE] * 8)
        assert model.noise_sd(criterion) == pytest.approx(PRIOR_SIGMA0[criterion])
        assert model.n_obs(criterion) == 0


# ---------------------------------------------------------------------------
# Posterior
# ---------------------------------------------------------------------------


def test_nig_posterior_matches_direct_numpy():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(6, 3))
    r = rng.normal(size=6)
    v0 = np.array([0.5, 2.0, 1.5])
    a0, b0 = 3.0, 0.08
    post = fit_nig(X, r, v0, a0, b0)

    Vn = np.linalg.inv(np.linalg.inv(np.diag(v0)) + X.T @ X)
    mn = Vn @ X.T @ r
    an = a0 + 6 / 2
    bn = b0 + 0.5 * (r @ r - mn @ np.linalg.inv(Vn) @ mn)
    assert post.mean == pytest.approx(mn)
    assert post.scale == pytest.approx(Vn)
    assert (post.a, post.n) == (an, 6)
    assert post.b == pytest.approx(bn)

    x_new = np.array([[0.3, -1.0, 2.0]])
    mu, s = post.predictive(x_new)
    assert mu[0] == pytest.approx(x_new[0] @ mn)
    assert s[0] == pytest.approx(np.sqrt(bn / an * (1 + x_new[0] @ Vn @ x_new[0])))
    assert post.df == 2 * an
    assert post.coef_sd == pytest.approx(np.sqrt(np.diag(Vn) * bn / (an - 1)))


def test_robust_fit_of_an_empty_corpus_is_the_prior():
    v0, a0, b0 = prior_hyperparameters("construction_cost_mln")
    post = fit_robust(np.zeros((0, len(v0))), np.zeros(0), v0, a0, b0)
    assert post.n == 0 and np.all(post.mean == 0)
    assert post.predictive_df == min(2 * a0, post.nu)


def test_robust_fit_downweights_a_unit_mistake():
    records = synthetic_records(60, seed=3)
    clean = ResidualModel.fit(records)
    (bad, _) = validate_record({"type": "Turbine", "cost": 450}, source="typo.csv")  # ×10 typo
    robust = ResidualModel.fit([*records, bad])
    rows = build_training_data([*records, bad])["construction_cost_mln"]
    v0, a0, b0 = prior_hyperparameters("construction_cost_mln")
    gaussian = fit_nig(rows.X, rows.r, v0, a0, b0)

    weights = robust.posteriors["construction_cost_mln"].weights
    assert weights[-1] < OUTLIER_WEIGHT
    assert np.median(weights[:-1]) > 0.9
    x = features("Turbine")
    clean_mu = (clean.posteriors["construction_cost_mln"].mean @ x)
    robust_mu = (robust.posteriors["construction_cost_mln"].mean @ x)
    assert abs(robust_mu - clean_mu) < 0.25 * abs(gaussian.mean @ x - clean_mu)


def test_prediction_is_baseline_times_exp_mu_with_t_interval():
    record, _ = validate_record({"type": "Turbine", "cost": 60, "aadt": 60000, "lanes": 3})
    model = ResidualModel.fit([record])
    cond = {"aadt": 60000, "num_lanes": 3}
    post = model.posteriors["construction_cost_mln"]
    mu, s = post.predictive(features("Turbine", cond))
    q = student_t.ppf(0.95, post.predictive_df)
    p = model.predict("Turbine", cond)["construction_cost_mln"]
    assert p["expert"] == 45.0
    assert p["predicted"] == pytest.approx(45.0 * np.exp(mu[0]))
    assert p["low"] == pytest.approx(45.0 * np.exp(mu[0] - q * s[0]))
    assert p["high"] == pytest.approx(45.0 * np.exp(mu[0] + q * s[0]))
    assert 45.0 < p["predicted"] < 60.0  # shrunk towards the expert value


def test_records_only_inform_their_own_targets():
    records = [
        validate_record({"type": "Diamond", "cost": 12})[0],
        validate_record({"type": "Diamond", "cost": 13, "capacity": 2600})[0],
        validate_record({"type": "SPUI", "safety_index": 7.5})[0],
    ]
    model = ResidualModel.fit(records)
    assert {c: model.n_obs(c) for c in TARGETS} == {
        "construction_cost_mln": 2, "land_area_hectares": 0, "throughput_vph": 1,
        "safety_index": 1}
    land = model.predict("Diamond")["land_area_hectares"]
    assert land["predicted"] == land["expert"]
    assert (model.n_records, model.n_synthetic) == (3, 0)


def test_recovers_known_effects(big_model):
    coefs = {c: {e["feature"]: e["mean"] for e in big_model.coefficients()[c]} for c in TARGETS}
    tolerance = {"lanes": 0.04, "log_aadt": 0.06, "speed": 0.03,
                 "type:Turbine": 0.12, "type:DDI": 0.12}
    for criterion, effects in TRUE_EFFECTS.items():
        for feature, true_value in effects.items():
            assert coefs[criterion][feature] == pytest.approx(true_value, abs=tolerance[feature])
    assert coefs["construction_cost_mln"]["lanes"] == pytest.approx(0.12, abs=0.04)
    # features without a planted effect stay near zero
    assert abs(coefs["land_area_hectares"]["log_aadt"]) < 0.06
    assert abs(coefs["throughput_vph"]["type:Turbine"]) < 0.1
    for criterion in TARGETS:
        assert big_model.noise_sd(criterion) == pytest.approx(PRIOR_SIGMA0[criterion], rel=0.25)


def test_intervals_shrink_as_data_grow():
    cond = {"aadt": 60000, "num_lanes": 3, "design_speed": 110}
    x = features("Turbine", cond)
    widths, parameter_var = [], []
    for n in (0, 16, 80, 400):
        model = ResidualModel.fit(synthetic_records(n, seed=5))
        p = model.predict("Turbine", cond)["throughput_vph"]
        widths.append(np.log(p["high"] / p["low"]))
        parameter_var.append(x @ model.posteriors["throughput_vph"].scale @ x)
    # the parameter (epistemic) part shrinks monotonically ...
    assert parameter_var == sorted(parameter_var, reverse=True)
    assert parameter_var[-1] < parameter_var[0] / 20
    assert widths[:3] == sorted(widths[:3], reverse=True)
    # ... while the interval approaches the irreducible noise floor 2 · z95 · σ.
    assert widths[-1] == pytest.approx(2 * 1.645 * PRIOR_SIGMA0["throughput_vph"], rel=0.15)
    assert widths[-1] < widths[0] / 3


def test_out_of_sample_coverage_is_close_to_nominal(big_model):
    test = synthetic_records(400, seed=99)
    inside, total = 0, 0
    for record in test:
        prediction = big_model.predict(record.interchange_type, record.conditions)
        for criterion, observed in record.targets.items():
            p = prediction[criterion]
            inside += p["low"] <= observed <= p["high"]
            total += 1
    assert 0.84 <= inside / total <= 0.96


def test_model_beats_expert_where_effects_exist():
    metrics = cross_validate(synthetic_records(120, seed=3))
    for criterion in ("construction_cost_mln", "throughput_vph"):
        m = metrics[criterion]
        assert m["loo_mape_model"] < m["loo_mape_expert"]
        assert 0.75 <= m["coverage90"] <= 1.0


def test_safety_is_clamped_to_scale():
    high = [validate_record({"type": "Stack (4-Level)", "safety_index": 10, "aadt": 45000})[0]
            for _ in range(6)]
    low = [validate_record({"type": "Cloverleaf", "safety_index": 1.0, "speed": 130})[0]
           for _ in range(6)]
    model = ResidualModel.fit(high + low)
    stack = model.predict("Stack (4-Level)", {"design_speed": 60})["safety_index"]
    assert stack["predicted"] <= 10 and stack["high"] == 10
    clover = model.predict("Cloverleaf", {"design_speed": 140})["safety_index"]
    assert clover["low"] == 1 and clover["predicted"] >= 1
    values = model.correct_values("Stack (4-Level)", {"safety_index": 9.0}, {"design_speed": 60})
    assert values["safety_index"] <= 10


def test_correction_and_value_ranges(big_model):
    params = ProjectParams(aadt=70000, num_lanes=3, terrain="Rolling")
    raw = INTERCHANGE_DATA["System (Highway + Highway)"]["Turbine"]
    corrected = big_model.correct_values("Turbine", raw, params)
    adjusted, _ = apply_project_params(
        [Alternative(name="Turbine", raw_values=corrected)],
        params.model_copy(update={"peak_factor": 0, "budget": 1e9, "land_limit": 1e9}),
    )
    prediction = big_model.predict("Turbine", params)
    for criterion in TARGETS:
        # correcting the constants, then running the expert rules ≈ the model prediction
        assert adjusted[0].raw_values[criterion] == pytest.approx(
            prediction[criterion]["predicted"], rel=0.01)
    corrections = big_model.corrections("Turbine", params)
    assert corrections["construction_cost_mln"].factor > 1.3  # lanes + AADT + Turbine effects
    ranges = big_model.value_ranges(INTERCHANGE_DATA["System (Highway + Highway)"], params)
    for criterion, (low, high) in ranges.items():
        assert 0 < low < 1 < high <= 10
        assert low == pytest.approx(min(
            big_model.corrections(t, params)[criterion].low_ratio
            for t in INTERCHANGE_DATA["System (Highway + Highway)"]))


# ---------------------------------------------------------------------------
# Cross-validation
# ---------------------------------------------------------------------------


def test_cross_validation_shape_and_nulls():
    records = [validate_record({"type": "Diamond", "cost": c, "capacity": 2500})[0]
               for c in (9.5, 10.5, 11.0)]
    records.append(validate_record({"type": "DDI", "land_area_hectares": 6.5})[0])
    metrics = cross_validate(records)
    assert set(metrics) == set(TARGETS)
    for m in metrics.values():
        assert set(m) == {"n_obs", "loo_mape_expert", "loo_mape_model", "coverage90"}
    assert metrics["construction_cost_mln"]["n_obs"] == 3
    assert metrics["construction_cost_mln"]["loo_mape_expert"] == pytest.approx(
        np.mean([0.5 / 9.5, 0.5 / 10.5, 1.0 / 11.0]))
    assert 0 <= metrics["construction_cost_mln"]["coverage90"] <= 1
    assert metrics["throughput_vph"]["loo_mape_expert"] == 0.0
    for criterion in ("land_area_hectares", "safety_index"):
        assert metrics[criterion]["loo_mape_model"] is None
        assert metrics[criterion]["coverage90"] is None
    assert cross_validate(build_training_data(records)) == metrics


def test_folds_switch_to_k_fold_above_200():
    assert [f.tolist() for f in _folds(3)] == [[0], [1], [2]]
    assert len(_folds(200)) == 200
    folds = _folds(250)
    assert len(folds) == 10
    assert sorted(np.concatenate(folds).tolist()) == list(range(250))


def test_k_fold_metrics_on_large_corpus():
    metrics = cross_validate(synthetic_records(260, seed=8))
    m = metrics["throughput_vph"]
    assert m["n_obs"] > 200 and m["loo_mape_model"] < m["loo_mape_expert"]


# ---------------------------------------------------------------------------
# Corpus store
# ---------------------------------------------------------------------------

CSV = (b"interchange_type,aadt,num_lanes,construction_cost_mln,throughput_vph\n"
       b"Turbine,60000,3,70,8000\nDDI,40000,2,17,5600\nDiamond,30000,2,11,2600\n")


@pytest.fixture
def store(tmp_path):
    return CorpusStore(tmp_path / "docs")


def test_empty_store_status(store):
    status = store.status()
    assert set(status) == {"trained_at", "train_ms", "revision", "n_records", "n_synthetic",
                           "documents", "criteria", "coefficients", "interval_level",
                           "llm_available", "pdf_available"}
    assert (status["n_records"], status["n_synthetic"], status["documents"]) == (0, 0, [])
    assert status["trained_at"].endswith("+00:00") and status["train_ms"] >= 0
    assert status["interval_level"] == 0.9
    for criterion in TARGETS:
        assert status["criteria"][criterion] == {
            "n_obs": 0, "noise_sd": pytest.approx(PRIOR_SIGMA0[criterion]),
            "loo_mape_expert": None, "loo_mape_model": None, "coverage90": None}
        assert len(status["coefficients"][criterion]) == 16
    assert store.predict("Diamond")["construction_cost_mln"]["predicted"] == 10.0


def test_store_upload_retrain_and_delete(store):
    status = store.save_document("projects.csv", CSV)
    assert status["n_records"] == 3
    (doc,) = status["documents"]
    assert doc == {"name": "projects.csv", "kind": "csv", "synthetic": False, "records": 3,
                   "extractor": "table", "warnings": doc["warnings"], "size_bytes": len(CSV)}
    assert status["criteria"]["construction_cost_mln"]["n_obs"] == 3
    assert store.model.predict("Turbine", {"aadt": 60000, "num_lanes": 3})[
        "construction_cost_mln"]["predicted"] > 45.0

    with pytest.raises(DocumentExists) as exc:
        store.save_document("projects.csv", CSV)
    assert exc.value.status_code == 409
    store.save_document("synthetic_more.md", b"Type: SPUI\nCost: $21M", overwrite=False)
    status = store.save_document("projects.csv", CSV.splitlines(True)[0] + CSV.splitlines(True)[1],
                                 overwrite=True)
    assert (status["n_records"], status["n_synthetic"]) == (2, 1)
    assert [d["name"] for d in status["documents"]] == ["projects.csv", "synthetic_more.md"]

    status = store.delete_document("projects.csv")
    assert status["n_records"] == 1
    with pytest.raises(DocumentNotFound) as exc:
        store.delete_document("projects.csv")
    assert exc.value.status_code == 404
    assert not list(store.directory.glob(".*"))  # no partial files left behind


@pytest.mark.parametrize("name, error", [
    ("../evil.csv", InvalidDocumentName), ("a/b.csv", InvalidDocumentName),
    ("a\\b.csv", InvalidDocumentName), ("..", InvalidDocumentName),
    (".hidden.csv", InvalidDocumentName), ("", InvalidDocumentName),
    ("x\x00.csv", InvalidDocumentName), ("C:evil.csv", InvalidDocumentName),
    ("report.exe", UnsupportedDocumentType), ("noext", UnsupportedDocumentType),
])
def test_store_rejects_bad_names(store, name, error):
    with pytest.raises(error) as exc:
        store.save_document(name, CSV)
    assert exc.value.status_code == 400
    assert not store.directory.exists() or not any(store.directory.iterdir())


def test_store_rejects_empty_and_oversized(store, monkeypatch):
    with pytest.raises(EmptyDocument):
        store.save_document("x.csv", b"")
    monkeypatch.setattr(store_module, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(DocumentTooLarge) as exc:
        store.save_document("x.csv", CSV)
    assert exc.value.status_code == 413


@pytest.mark.parametrize("name", ["../x.csv", "a/b.csv", ".."])
def test_store_delete_rejects_unsafe_names(store, name):
    with pytest.raises(InvalidDocumentName):
        store.delete_document(name)


def test_store_warns_about_implausible_values(store):
    status = store.save_document("units.csv", b"type,cost,land_area_hectares\nDiamond,950,5.2\n")
    (doc,) = status["documents"]
    assert doc["records"] == 1
    assert doc["warnings"][-1] == (
        "units row 2: construction_cost_mln 950 is 95× the expert value 10 — check the units")


def test_store_warns_about_downweighted_records(store):
    rows = generate_rows(40, np.random.default_rng(5))
    header = ",".join(rows[0])
    lines = [header, *(",".join(str(row[k]) for k in rows[0]) for row in rows)]
    store.save_document("clean.csv", "\n".join(lines).encode())
    status = store.save_document("typo.csv", b"type,cost\nTurbine,450\n")
    typo = next(d for d in status["documents"] if d["name"] == "typo.csv")
    assert any("downweighted" in w for w in typo["warnings"])
    clean = next(d for d in status["documents"] if d["name"] == "clean.csv")
    assert not any("downweighted" in w for w in clean["warnings"])


def test_store_survives_malformed_documents(store):
    store.directory.mkdir(parents=True)
    (store.directory / "deep.json").write_text("[" * 100_000 + "]" * 100_000)
    (store.directory / "p.csv").write_bytes(CSV)
    status = store.retrain()
    deep = next(d for d in status["documents"] if d["name"] == "deep.json")
    assert deep["records"] == 0 and deep["warnings"][0].startswith("could not parse JSON")
    assert status["n_records"] == 3


def test_store_ignores_foreign_and_hidden_files(store):
    store.directory.mkdir(parents=True)
    (store.directory / "notes.docx").write_bytes(b"PK")
    (store.directory / ".DS_Store").write_bytes(b"\0")
    (store.directory / "p.csv").write_bytes(CSV)
    status = store.retrain()
    assert [d["name"] for d in status["documents"]] == ["p.csv"]


def test_store_trains_lazily_and_once(store, monkeypatch):
    calls = []
    original = store.retrain
    monkeypatch.setattr(store, "retrain", lambda: calls.append(1) or original())
    assert store.model.n_records == 0
    store.status()
    store.predict("SPUI")
    assert calls == [1]


def test_concurrent_retrains_are_safe(store):
    store.save_document("p.csv", CSV)
    errors = []

    def work():
        try:
            for _ in range(5):
                assert store.retrain()["n_records"] == 3
                assert store.status()["n_records"] == 3
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_store_uses_llm_fallback_when_enabled(store, monkeypatch):
    monkeypatch.setattr(store_module, "llm_available", lambda: True)
    monkeypatch.setattr(store_module, "extract_records_with_llm", lambda text, name: (
        [{"interchange_type": "Trumpet", "construction_cost_mln": 13.0}], []))
    status = store.save_document("prose.txt", b"A trumpet that cost thirteen million dollars.")
    (doc,) = status["documents"]
    assert (doc["extractor"], doc["records"]) == ("llm", 1)
    assert status["llm_available"] is True


def test_singleton_and_env_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("TDSS_CORPUS_DIR", str(tmp_path))
    try:
        store = reset_store()
        assert store.directory == tmp_path and get_store() is store
        assert reset_store(tmp_path / "other").directory == tmp_path / "other"
        assert get_store().directory == tmp_path / "other"
    finally:
        monkeypatch.delenv("TDSS_CORPUS_DIR")
        reset_store()
    assert get_store().directory == store_module.DEFAULT_CORPUS_DIR


def test_shipped_demo_corpus_reads_cleanly():
    status = CorpusStore(store_module.DEFAULT_CORPUS_DIR).status()
    assert status["n_records"] == status["n_synthetic"] == 64
    names = {d["name"]: d for d in status["documents"]}
    assert set(names) == {"synthetic_precedents.csv", "synthetic_report_diamond_en.md",
                          "synthetic_report_trumpet_uk.md", "synthetic_report_turbine_en.md"}
    assert all(d["warnings"] == [] and d["synthetic"] for d in names.values())
    assert names["synthetic_report_diamond_en.md"]["records"] == 2
    assert status["criteria"]["construction_cost_mln"]["loo_mape_model"] is not None
