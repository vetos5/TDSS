"""Hardening of the corpus against hostile or broken documents (security review findings).

Absurd numbers, quadratic regexes, PDF decompression bombs, oversized corpora, slow retrains
blocking readers, repeated LLM calls and leaky warnings. Everything stays offline: the LLM client
is faked and PDFs are built in memory.
"""

import os
import random
import re
import sys
import threading
import time
import zlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.application.prediction import parse_number, resolve_header, validate_record
from app.application.prediction.records import _split_qualifier
from app.application.prediction.text_extraction import _LINE_RE, match_field_line
from app.infrastructure.corpus import (
    CorpusStore,
    InvalidDocumentName,
    TrainingFailed,
    llm_extraction,
    read_document,
    read_document_bytes,
    readers,
    reset_store,
    sanitize_document_name,
)
from app.infrastructure.corpus import store as store_module
from backend.main import app

ADMIN_TOKEN = "test-admin-token-0123456789"
client = TestClient(app, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
CSV = b"type,cost\nTurbine,50\nDDI,17\n"
TINY_COST = ("type,cost\nTurbine,0." + "0" * 321 + "1\n").encode()  # 1e-322: ln underflows


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("TDSS_LLM_EXTRACTION", raising=False)
    monkeypatch.setenv("TDSS_ADMIN_TOKEN", ADMIN_TOKEN)


@pytest.fixture
def corpus(tmp_path):
    directory = tmp_path / "documents"
    directory.mkdir()
    reset_store(directory)
    yield directory
    reset_store()


def upload(name, data, **params):
    return client.post("/api/model/documents", params=params,
                       files={"file": (name, data, "application/octet-stream")})


def make_pdf(content: bytes, pages: int = 1, compress: bool = True) -> bytes:
    """A PDF whose pages all draw the same (flate-compressed) content stream."""
    stream = zlib.compress(content, 9) if compress else content
    flate = b" /Filter /FlateDecode" if compress else b""
    kids = b" ".join(f"{5 + i} 0 R".encode() for i in range(pages))
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(pages).encode() + b" >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        4: b"<< /Length " + str(len(stream)).encode() + flate + b" >>\nstream\n" + stream
           + b"\nendstream",
    }
    for i in range(pages):
        objects[5 + i] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                          b"/Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>")
    out = bytearray(b"%PDF-1.7\n")
    offsets = {}
    for n in sorted(objects):
        offsets[n] = len(out)
        out += f"{n} 0 obj\n".encode() + objects[n] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offsets[n]:010d} 00000 n \n".encode() for n in sorted(objects))
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def pdf_bomb(megabytes: int) -> bytes:
    """A few KB of PDF that inflates to *megabytes* of text-drawing operators."""
    unit = b"(" + b"A" * 58 + b") Tj\n"
    return make_pdf(b"BT /F1 12 Tf 10 10 Td\n" + unit * (megabytes * 2**20 // len(unit)) + b"ET")


def text_pdf(*lines: str) -> bytes:
    body = " ".join(f"({line}) Tj T*" for line in lines)
    return make_pdf(f"BT /F1 12 Tf 72 720 Td 16 TL {body} ET".encode(), compress=False)


# ---------------------------------------------------------------------------
# H1: numbers that break the fit, reader crashes, failed fits and uploads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [10**400, "1" * 400, float("inf"), "1" * 5000])
def test_parse_number_rejects_numbers_beyond_float(value):
    assert parse_number(value) is None


@pytest.mark.parametrize("cost", ["0." + "0" * 321 + "1", 5e-324, 1e-7, 1.7e308, 2e9])
def test_absurd_targets_are_dropped(cost):
    record, warnings = validate_record({"type": "Turbine", "cost": cost, "capacity": 6000})
    assert record is not None and "construction_cost_mln" not in record.targets
    assert any("outside 1e-06–1e+09" in w for w in warnings), warnings


POISONED = {
    "big.json": b'[{"type": "Turbine", "cost": 1' + b"0" * 400 + b"}]",
    "huge.json": b'[{"type": "Turbine", "cost": 1' + b"0" * 5000 + b"}]",
    "huge.jsonl": b'{"type": "Turbine", "cost": 1' + b"0" * 5000 + b"}\n",
    "big_aadt.jsonl": b'{"type": "Turbine", "cost": 50, "aadt": 1' + b"0" * 400 + b"}\n",
    "tiny.csv": TINY_COST,
}


@pytest.mark.parametrize("name", POISONED)
def test_poisoned_documents_cost_a_warning_not_the_model(corpus, name):
    assert upload(name, POISONED[name]).status_code == 200
    reset_store(corpus)  # a restart re-reads the file from disk
    for r in (client.get("/api/model/status"),
              client.post("/api/model/predict", json={"context": "System (Highway + Highway)"}),
              client.post("/api/model/retrain")):
        assert r.status_code == 200
    [doc] = client.get("/api/model/status").json()["documents"]
    assert doc["warnings"]


def test_a_reader_crash_costs_only_its_document(corpus, monkeypatch):
    (corpus / "good.csv").write_bytes(CSV)
    (corpus / "bad.csv").write_bytes(CSV)
    real = store_module.read_document

    def flaky(path, **kwargs):
        if path.name == "bad.csv":
            raise OverflowError(f"boom in {path}")
        return real(path, **kwargs)

    monkeypatch.setattr(store_module, "read_document", flaky)
    status = client.get("/api/model/status").json()
    docs = {d["name"]: d for d in status["documents"]}
    assert status["n_records"] == 2 and docs["good.csv"]["records"] == 2
    assert docs["bad.csv"]["warnings"] == ["could not read the document (OverflowError)"]


def test_a_failed_fit_keeps_the_previous_model(tmp_path, monkeypatch):
    (tmp_path / "a.csv").write_bytes(CSV)
    store = CorpusStore(tmp_path)
    before = store.status()
    monkeypatch.setattr(store_module, "cross_validate", lambda *a, **k: 1 / 0)
    with pytest.raises(TrainingFailed, match="ZeroDivisionError"):
        store.retrain()
    assert store.status() == before


def failing_build(monkeypatch, source=None):
    """Make every fit fail that includes a record (of document *source*, if given)."""
    real = store_module.build_training_data

    def build(records):
        if any(source is None or r.source == source for r in records):
            raise ValueError("array must not contain infs or NaNs")
        return real(records)

    monkeypatch.setattr(store_module, "build_training_data", build)


def test_a_failed_first_fit_falls_back_to_the_expert_values(tmp_path, monkeypatch):
    (tmp_path / "a.csv").write_bytes(CSV)
    store = CorpusStore(tmp_path)
    failing_build(monkeypatch)
    status = store.status()  # lazily trained: never raises
    [doc] = status["documents"]
    assert status["n_records"] == 0 and doc["records"] == 0
    assert doc["warnings"][0] == (
        "not used: the model could not be fitted on the corpus (ValueError); "
        "the expert values apply")
    assert store.predict("Turbine")["construction_cost_mln"]["predicted"] == pytest.approx(45.0)


def test_a_failed_upload_is_removed(corpus, monkeypatch):
    failing_build(monkeypatch, source="new.csv")
    (corpus / "a.csv").write_bytes(CSV)
    before = client.get("/api/model/status").json()
    r = upload("new.csv", CSV)
    assert r.status_code == 422 and "could not be fitted" in r.json()["detail"]
    assert sorted(p.name for p in corpus.iterdir()) == ["a.csv"]
    assert client.get("/api/model/status").json() == before


def test_a_failed_overwrite_puts_the_previous_file_back(corpus, monkeypatch):
    assert upload("new.csv", b"type,cost\nDDI,17\n").status_code == 200
    failing_build(monkeypatch)
    assert upload("new.csv", CSV, overwrite=True).status_code == 422
    assert (corpus / "new.csv").read_bytes() == b"type,cost\nDDI,17\n"
    assert sorted(p.name for p in corpus.iterdir()) == ["new.csv"]


# ---------------------------------------------------------------------------
# H2: regexes stay linear
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call, text", [
    (_LINE_RE.match, "Construction cost" + " " * 200_000 + "x"),
    (_LINE_RE.match, "cost (" + " " * 200_000 + "x"),
    (match_field_line, "Construction cost" + " " * 200_000 + "x"),
    (resolve_header, "(" * 200_000),
    (resolve_header, "a" + " " * 200_000 + "x)"),
    (_split_qualifier, "(" * 200_000 + ")"),
])
def test_field_parsers_are_linear(call, text):
    start = time.perf_counter()
    call(text)
    assert time.perf_counter() - start < 0.5


def test_header_split_matches_the_regex_it_replaces():
    regex = re.compile(r"^(?P<key>.*?)\s*\((?P<unit>[^)]*)\)\s*$")
    rng = random.Random(7)
    alphabet = ["a", "b", " ", "(", ")", "\n", "\t", " "]
    for _ in range(20_000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 9)))
        match = regex.match(text)
        assert _split_qualifier(text) == (match and (match["key"], match["unit"])), repr(text)


def test_long_lines_are_never_fields():
    assert match_field_line("Construction cost: " + "4" * 600) is None
    assert resolve_header("Construction cost (" + "M USD " * 100 + ")") == (None, "")
    assert match_field_line("Construction cost (M USD): 48.5") == (
        "construction_cost_mln", "48.5", "(M USD)")


def test_a_slow_text_upload_no_longer_stalls():
    data = ("Construction cost" + " " * 1_000_000 + "x\n" + "Type: Diamond\nCost: 9\n").encode()
    start = time.perf_counter()
    result = read_document_bytes("slow.txt", data)
    assert time.perf_counter() - start < 1.0 and len(result.records) == 1


# ---------------------------------------------------------------------------
# H3: PDFs are parsed in a child process with a timeout and caps
# ---------------------------------------------------------------------------


def test_pdf_text_from_the_child_process():
    pytest.importorskip("pypdf")
    result = read_document_bytes("r.pdf", text_pdf("Interchange type: DDI", "Cost: $16.2M"))
    assert result.extractor == "rules"
    assert [r.targets for r in result.records] == [{"construction_cost_mln": 16.2}]


def test_pdf_bomb_is_killed_after_the_timeout(monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(readers, "PDF_TIMEOUT_S", 1.0)
    start = time.perf_counter()
    result = read_document_bytes("bomb.pdf", pdf_bomb(8))
    assert time.perf_counter() - start < 5
    assert result.records == [] and result.warnings[0] == "could not read PDF: gave up after 1 s"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="RLIMIT_AS is enforced on Linux")
def test_pdf_bomb_hits_the_memory_limit(monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(readers, "PDF_MEMORY_BYTES", 64 * 2**20)
    monkeypatch.setattr(readers, "PDF_TIMEOUT_S", 15.0)
    start = time.perf_counter()
    result = read_document_bytes("bomb.pdf", pdf_bomb(8))
    assert time.perf_counter() - start < 10
    [warning, *_] = result.warnings
    assert warning.startswith("could not read PDF") and "gave up" not in warning


def test_pdf_page_and_text_caps(monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(readers, "PDF_MAX_PAGES", 1)
    result = read_document_bytes("two.pdf", make_pdf(b"BT /F1 12 Tf (x) Tj ET", pages=2))
    assert "PDF has 2 pages — only the first 1 were read" in result.warnings
    monkeypatch.setattr(readers, "PDF_MAX_TEXT_CHARS", 10)
    result = read_document_bytes("long.pdf", text_pdf("Interchange type: DDI", "Cost: 16"))
    assert "PDF text cut at 10 characters" in result.warnings


def test_the_pdf_child_gets_no_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    env = readers._pdf_child_env()
    assert "ANTHROPIC_API_KEY" not in env and "TDSS_ADMIN_TOKEN" not in env


def test_unchanged_documents_are_not_parsed_again(tmp_path, monkeypatch):
    (tmp_path / "a.csv").write_bytes(CSV)
    store = CorpusStore(tmp_path)
    calls = []
    real = store_module.read_document
    monkeypatch.setattr(store_module, "read_document",
                        lambda path, **kw: calls.append(path.name) or real(path, **kw))
    first = store.retrain()
    second = store.retrain()
    assert calls == ["a.csv"] and first["documents"] == second["documents"]
    os.utime(tmp_path / "a.csv", ns=(1, 1))  # a changed file is read again
    store.retrain()
    assert calls == ["a.csv", "a.csv"]


# ---------------------------------------------------------------------------
# M4: readers never wait for a retrain
# ---------------------------------------------------------------------------


def test_readers_do_not_wait_for_a_slow_retrain(tmp_path, monkeypatch):
    (tmp_path / "a.csv").write_bytes(CSV)
    store = CorpusStore(tmp_path)
    before = store.status()["revision"]
    entered, release = threading.Event(), threading.Event()
    real = store_module.read_document

    def slow(path, **kwargs):
        entered.set()
        release.wait(10)
        return real(path, **kwargs)

    monkeypatch.setattr(store_module, "read_document", slow)
    (tmp_path / "b.csv").write_bytes(CSV)  # not in the parse cache yet
    worker = threading.Thread(target=store.retrain)
    worker.start()
    try:
        assert entered.wait(5)
        start = time.perf_counter()
        assert store.status()["revision"] == before
        store.predict("Turbine")
        assert time.perf_counter() - start < 1
    finally:
        release.set()
        worker.join(10)
    assert store.status()["revision"] > before and store.status()["n_records"] == 4


# ---------------------------------------------------------------------------
# M5: corpus caps
# ---------------------------------------------------------------------------


def test_upload_caps_on_documents_and_bytes(corpus, monkeypatch):
    monkeypatch.setattr(store_module, "MAX_DOCUMENTS", 2)
    assert upload("a.csv", CSV).status_code == 200
    assert upload("b.csv", CSV).status_code == 200
    r = upload("c.csv", CSV)
    assert r.status_code == 413 and "documents" in r.json()["detail"]
    assert upload("b.csv", CSV, overwrite=True).status_code == 200  # replacing is fine
    monkeypatch.setattr(store_module, "MAX_DOCUMENTS", 10)
    monkeypatch.setattr(store_module, "MAX_CORPUS_BYTES", 3 * len(CSV) - 1)
    r = upload("c.csv", CSV)
    assert r.status_code == 413 and "MB" in r.json()["detail"]
    assert sorted(p.name for p in corpus.iterdir()) == ["a.csv", "b.csv"]


def test_upload_cap_on_records(corpus, monkeypatch):
    monkeypatch.setattr(readers, "MAX_RECORDS_PER_DOCUMENT", 2)
    monkeypatch.setattr(store_module, "MAX_RECORDS_PER_DOCUMENT", 2)
    assert upload("ok.csv", CSV).status_code == 200
    r = upload("rows.csv", CSV + b"Diamond,9\n")
    assert r.status_code == 413 and "more than 2 records" in r.json()["detail"]
    assert not (corpus / "rows.csv").exists()


@pytest.mark.parametrize("name, data", [
    ("rows.csv", CSV + b"Diamond,9\n"),
    ("items.json", b'[{"type": "DDI", "cost": 17}, 1, 2, {"type": "DDI", "cost": 18}]'),
    ("lines.jsonl", b'{"type": "DDI", "cost": 17}\nnope\n{"type": "DDI", "cost": 18}\n'),
    ("blocks.txt", b"Type: DDI\nCost: 17\n---\nCost: 1\n---\nType: DDI\nCost: 18\n"),
])
def test_reading_stops_at_the_record_cap(monkeypatch, name, data):
    monkeypatch.setattr(readers, "MAX_RECORDS_PER_DOCUMENT", 2)
    result = read_document_bytes(name, data)
    assert result.truncated and len(result.records) == 1 + name.startswith("rows")
    assert result.warnings[0] == "more than 2 records — only the first 2 were read"


def test_files_past_the_corpus_caps_are_listed_but_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "MAX_DOCUMENTS", 2)
    monkeypatch.setattr(store_module, "MAX_UPLOAD_BYTES", 100)
    for name in ("a.csv", "b.csv", "c.csv"):
        (tmp_path / name).write_bytes(CSV)
    (tmp_path / "0_big.csv").write_bytes(CSV + b"Diamond,9\n" * 20)
    status = CorpusStore(tmp_path).status()
    docs = {d["name"]: d for d in status["documents"]}
    assert status["n_records"] == 4 and docs["c.csv"]["records"] == 0
    assert docs["c.csv"]["warnings"] == ["not read: the corpus limit of 2 documents is reached"]
    assert docs["0_big.csv"]["warnings"][0].startswith("not read: larger than")


def test_warnings_are_capped_and_shortened():
    rows = f"Turbine,{'x' * 2000}\n" * 30  # two warnings per row, one quoting the cell
    report = read_document_bytes("w.csv", ("type,cost\n" + rows).encode()).report()
    assert len(report["warnings"]) == 21 and report["warnings"][-1] == "+41 more warnings"
    assert all(len(w) <= 300 for w in report["warnings"])
    assert report["warnings"][0].endswith("…")


def test_a_failed_write_leaves_no_partial_file(corpus, monkeypatch):
    def full_disk(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(store_module.os, "replace", full_disk)
    with pytest.raises(OSError):
        store_module.get_store().save_document("a.csv", CSV)
    assert list(corpus.iterdir()) == []


# ---------------------------------------------------------------------------
# M6: LLM failures are cached, the text sent is capped
# ---------------------------------------------------------------------------


class _RateLimited(Exception):
    pass


class _Messages:
    def __init__(self, stop_reason="end_turn", error=None):
        self.stop_reason, self.error, self.calls = stop_reason, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        block = SimpleNamespace(type="text", text='{"records": []}')
        return SimpleNamespace(stop_reason=self.stop_reason, content=[block])


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(llm_extraction, "_cache", {})
    never = llm_extraction._Never
    monkeypatch.setattr(llm_extraction, "_sdk_errors",
                        lambda: llm_extraction._SdkErrors(_RateLimited, never, never))

    def use(messages):
        monkeypatch.setattr(llm_extraction, "_default_client",
                            lambda: SimpleNamespace(messages=messages))
        return messages

    return use


def test_llm_failures_are_cached_but_rate_limits_are_retried(llm):
    refusing = llm(_Messages(stop_reason="refusal"))
    for _ in range(2):
        records, warnings = llm_extraction.extract_records_with_llm("prose", "a.txt")
        assert records == [] and "declined" in warnings[0]
    assert len(refusing.calls) == 1

    limited = llm(_Messages(error=_RateLimited()))
    for _ in range(2):
        assert "rate limited" in llm_extraction.extract_records_with_llm("other", "b.txt")[1][0]
    assert len(limited.calls) == 2


def test_llm_text_is_capped(llm, monkeypatch):
    monkeypatch.setattr(llm_extraction, "MAX_TEXT_CHARS", 50)
    messages = llm(_Messages())
    _, warnings = llm_extraction.extract_records_with_llm("x" * 51 + "TAIL", "a.txt")
    assert "TAIL" not in messages.calls[0]["messages"][0]["content"]
    assert warnings == ["only the first 50 characters of the text were sent"]


# ---------------------------------------------------------------------------
# Low: warnings without paths, safe document names
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root reads anything")
def test_unreadable_file_warning_names_no_path(tmp_path):
    path = tmp_path / "locked.csv"
    path.write_bytes(CSV)
    path.chmod(0)
    try:
        [warning] = read_document(path).warnings
    finally:
        path.chmod(0o644)
    assert warning == "could not read file: Permission denied" and str(tmp_path) not in warning


@pytest.mark.parametrize("name", [
    "‮csv.txt", "report​.csv", "a\u0085b.csv", "\ud800.csv", "я" * 99 + ".csv",
])
def test_names_with_format_characters_or_too_many_bytes_are_rejected(name):
    with pytest.raises(InvalidDocumentName):
        sanitize_document_name(name)


def test_names_up_to_200_utf8_bytes_are_accepted():
    name = "я" * 98 + ".csv"  # 196 + 4 bytes
    assert sanitize_document_name(name) == name
