"""Tests for record validation, rule-based text extraction, document readers and LLM fallback."""

import json
from types import SimpleNamespace

import pytest

from app.application.prediction import (
    INTERCHANGE_TYPES,
    extract_records_from_text,
    normalise_fields,
    parse_field_value,
    parse_number,
    resolve_env_sensitivity,
    resolve_interchange_type,
    resolve_terrain,
    validate_record,
)
from app.infrastructure.corpus import llm_extraction, read_document_bytes, readers

EN_REPORT = """\
SYNTHETIC EXAMPLE — not a real project
# Completion summary

Project: Ring road junction
Interchange type: Turbine
Year: 2021
Country: Poland
Traffic (AADT): 68,000 veh/day
Lanes per direction: 3
Design speed: 110 km/h
Terrain: Rolling
Environmental sensitivity: Medium
Construction cost: $78.4M
Land area: 29.6 ha
Capacity: 8,050 veh/h
Safety index: 7.9

The cost overrun came mainly from the third lane on every ramp.
"""

UK_REPORT = """\
Проєкт: Під'їзд до логістичного центру
Тип розв'язки: Труба
Рік: 2019
Країна: Україна
Інтенсивність: 31 000 авт/добу
Кількість смуг: 2
Розрахункова швидкість: 90 км/год
Рельєф: горбистий
Екологічна чутливість: висока
Вартість будівництва: 15,1 млн дол. США
Площа відведення: 128 000 м²
Пропускна здатність: 3 450 авт/год
Індекс безпеки: 6,7
"""


def only(text):
    records, warnings = extract_records_from_text(text)
    assert len(records) == 1, (records, warnings)
    return records[0], warnings


# ---------------------------------------------------------------------------
# Text documents
# ---------------------------------------------------------------------------


def test_english_report():
    fields, warnings = only(EN_REPORT)
    assert warnings == []
    assert fields == {
        "name": "Ring road junction", "interchange_type": "Turbine", "year": 2021,
        "country": "Poland", "aadt": 68000, "num_lanes": 3, "design_speed": 110,
        "terrain": "Rolling", "env_sensitivity": "Medium", "construction_cost_mln": 78.4,
        "land_area_hectares": 29.6, "throughput_vph": 8050, "safety_index": 7.9,
    }
    record, record_warnings = validate_record(fields, source="ring.md")
    assert record_warnings == [] and record.interchange_type == "Turbine"
    assert record.context == "System (Highway + Highway)"
    assert record.synthetic is False and record.imputed == ()


def test_ukrainian_report():
    fields, warnings = only(UK_REPORT)
    assert warnings == []
    record, record_warnings = validate_record(fields, source="trumpet.md")
    assert record_warnings == []
    assert (record.interchange_type, record.terrain, record.env_sensitivity) == (
        "Trumpet", "Rolling", "High")
    assert (record.aadt, record.num_lanes, record.design_speed) == (31000, 2, 90.0)
    assert record.targets == pytest.approx({
        "construction_cost_mln": 15.1, "land_area_hectares": 12.8,
        "throughput_vph": 3450, "safety_index": 6.7,
    })
    assert record.name == "Під'їзд до логістичного центру" and record.year == 2019


@pytest.mark.parametrize("separator", [":", "=", "—", "–", " -", ":  "])
def test_key_value_separators(separator):
    fields, _ = only(f"Interchange type{separator} DDI\nCapacity{separator} 5,600 vph")
    assert fields == {"interchange_type": "DDI", "throughput_vph": 5600}


def test_markdown_bullets_bold_and_tables():
    text = (
        "- **Interchange type:** SPUI\n"
        "* __Construction cost__: USD 21 million\n"
        "| Land area | 4.4 ha |\n"
        "| Field | Value |\n"
        "1. Safety index: 7,5\n"
    )
    fields, _ = only(text)
    assert fields == {"interchange_type": "SPUI", "construction_cost_mln": 21,
                      "land_area_hectares": 4.4, "safety_index": 7.5}


def test_prose_and_lookalike_keys_are_ignored():
    text = (
        "Type-specific notes: nothing\n"
        "Cost overrun: 20 %\n"
        "Interchange type: Diamond\n"
        "Costs were high.\n"
        "Construction cost (M USD): 11.2\n"
    )
    fields, _ = only(text)
    assert fields == {"interchange_type": "Diamond", "construction_cost_mln": 11.2}


def test_first_value_of_a_field_wins():
    fields, _ = only("Type: Trumpet\nCapacity: 3,600 veh/h\nCapacity: 9,999 veh/h")
    assert fields["throughput_vph"] == 3600


def test_multiple_records_separated_by_dashes():
    text = "Type: Diamond\nCost: $10M\n---\n\nType: DDI\nCost: $18M\n-----\nType: SPUI\nCost: $20M"
    records, warnings = extract_records_from_text(text)
    assert warnings == []
    assert [r["interchange_type"] for r in records] == ["Diamond", "DDI", "SPUI"]
    assert [r["construction_cost_mln"] for r in records] == [10, 18, 20]


def test_block_without_type_yields_warning_not_record():
    records, warnings = extract_records_from_text(
        "Intro prose only\n---\nProject: X\nCost: 12\n---\nType: Trumpet\nCost: 12")
    assert [r["interchange_type"] for r in records] == ["Trumpet"]
    assert warnings == ["block 2: no interchange type found — block skipped"]


def test_unknown_type_is_rejected_by_validation():
    fields, _ = only("Type: Roundabout\nCost: $5M")
    record, warnings = validate_record(fields)
    assert record is None
    assert warnings == ["unknown interchange type 'Roundabout' — record skipped"]


def test_text_with_no_fields():
    assert extract_records_from_text("Just a paragraph.\n\nAnd another one.") == ([], [])


# ---------------------------------------------------------------------------
# Numbers and units
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("52,000", 52000), ("48,5", 48.5), ("48.5", 48.5), ("52 000", 52000),
    ("52 000", 52000), ("52 000", 52000), ("52 000", 52000), ("1'250'000", 1250000),
    ("1,250.5", 1250.5), ("$48,500,000", 48500000), ("about 7 lanes", 7), ("-5", -5),
    ("12,34", 12.34), ("2019", 2019),
])
def test_parse_number(text, expected):
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [None, "", "n/a", "abc", True, float("nan")])
def test_parse_number_rejects(text):
    assert parse_number(text) is None


@pytest.mark.parametrize("text", [
    "$48.5M", "48.5 M USD", "USD 48.5 million", "48,5 млн дол.", "48,5 млн USD", "$48,500,000",
    "48.5", "48 500 000 USD", "$48,500k", "US$ 48.5 mln", "0.0485 bn USD",
])
def test_cost_formats_in_million_usd(text):
    value, warning = parse_field_value("construction_cost_mln", text)
    assert warning is None and value == pytest.approx(48.5)


@pytest.mark.parametrize("text, code", [
    ("1 200 млн грн", "UAH"), ("UAH 1,200 million", "UAH"), ("₴1.2 bn", "UAH"),
    ("€40M", "EUR"), ("EUR 40 million", "EUR"), ("40 млн євро", "EUR"), ("£30M", "GBP"),
])
def test_foreign_currency_is_skipped_with_warning(text, code):
    value, warning = parse_field_value("construction_cost_mln", text)
    assert value is None
    assert f"currency {code} not supported (USD only)" in warning


def test_currency_rejection_inside_a_document():
    fields, warnings = only("Тип розв'язки: ромб\nВартість будівництва: 300 млн грн\nПлоща: 5 га")
    assert "construction_cost_mln" not in fields and fields["land_area_hectares"] == 5
    assert len(warnings) == 1 and "currency UAH not supported (USD only)" in warnings[0]


def test_unit_in_key_qualifier():
    fields, _ = only("Type: SPUI\nConstruction cost (EUR): 20\nLand area (m²): 40 000\n"
                     "AADT (2019): 52 000")
    assert "construction_cost_mln" not in fields
    assert fields["land_area_hectares"] == pytest.approx(4.0)
    assert fields["aadt"] == 52000  # the year in the qualifier is not the value


@pytest.mark.parametrize("field, text, expected", [
    ("land_area_hectares", "12.5 ha", 12.5),
    ("land_area_hectares", "12,5 га", 12.5),
    ("land_area_hectares", "12.5 hectares", 12.5),
    ("land_area_hectares", "125 000 m²", 12.5),
    ("land_area_hectares", "125000 m2", 12.5),
    ("land_area_hectares", "125 000 м2", 12.5),
    ("land_area_hectares", "125 000 кв. м", 12.5),
    ("throughput_vph", "6,800 veh/h", 6800),
    ("throughput_vph", "6800 vph", 6800),
    ("throughput_vph", "6 800 авт/год", 6800),
    ("aadt", "52k veh/day", 52000),
    ("aadt", "52 тис. авт/добу", 52000),
    ("design_speed", "100 km/h", 100),
    ("design_speed", "90 км/год", 90),
    ("num_lanes", "3 lanes", 3),
    ("safety_index", "8.5/10", 8.5),
    ("year", "opened in 2019", 2019),
])
def test_units(field, text, expected):
    value, warning = parse_field_value(field, text)
    assert warning is None and value == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Synonyms and validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("cloverleaf", "Cloverleaf"), ("Clover Leaf", "Cloverleaf"), ("конюшина", "Cloverleaf"),
    ("конюшинний лист", "Cloverleaf"), ("TURBINE", "Turbine"), ("турбіна", "Turbine"),
    ("stack", "Stack (4-Level)"), ("4-level", "Stack (4-Level)"),
    ("four-level", "Stack (4-Level)"), ("чотирирівнева", "Stack (4-Level)"),
    ("Stack (4-Level)", "Stack (4-Level)"), ("diamond", "Diamond"), ("ромб", "Diamond"),
    ("ромбоподібна", "Diamond"), ("spui", "SPUI"), ("single point", "SPUI"),
    ("Single Point Urban Interchange", "SPUI"), ("одноточкова", "SPUI"), ("ddi", "DDI"),
    ("diverging diamond", "DDI"), ("розбіжний ромб", "DDI"), ("trumpet", "Trumpet"),
    ("труба", "Trumpet"), ("Directional T", "Directional T"), ("directional-t", "Directional T"),
    ("напрямна т", "Directional T"), ("Напрямна T", "Directional T"),
    ("Turbine interchange", "Turbine"), ("розв'язка типу труба", "Trumpet"),
])
def test_interchange_type_synonyms(text, expected):
    assert resolve_interchange_type(text) == expected


def test_every_canonical_type_resolves_to_itself():
    assert [resolve_interchange_type(t) for t in INTERCHANGE_TYPES] == list(INTERCHANGE_TYPES)
    assert resolve_interchange_type("roundabout") is None


@pytest.mark.parametrize("text, expected", [
    ("flat", "Flat"), ("рівнинний", "Flat"), ("Rolling", "Rolling"), ("горбистий", "Rolling"),
    ("mountainous", "Mountainous"), ("гірський", "Mountainous"),
])
def test_terrain_synonyms(text, expected):
    assert resolve_terrain(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("low", "Low"), ("низька", "Low"), ("Medium", "Medium"), ("середня", "Medium"),
    ("HIGH", "High"), ("висока", "High"), ("critical", "Critical"), ("критична", "Critical"),
])
def test_env_synonyms(text, expected):
    assert resolve_env_sensitivity(text) == expected


def test_missing_conditions_are_imputed_with_named_warnings():
    record, warnings = validate_record({"type": "DDI", "throughput_vph": 5600})
    assert (record.aadt, record.num_lanes, record.design_speed, record.terrain,
            record.env_sensitivity) == (45000, 2, 100.0, "Flat", "Low")
    assert record.imputed == ("aadt", "num_lanes", "design_speed", "terrain", "env_sensitivity")
    assert warnings == [
        "aadt missing — reference value 45000 imputed",
        "num_lanes missing — reference value 2 imputed",
        "design_speed missing — reference value 100 imputed",
        "terrain missing — reference value Flat imputed",
        "env_sensitivity missing — reference value Low imputed",
    ]


@pytest.mark.parametrize("field, value, fragment", [
    ("aadt", -10, "aadt -10 must be > 0"),
    ("num_lanes", 9, "num_lanes 9 outside 1–6"),
    ("num_lanes", 2.5, "num_lanes 2.5 is not a whole number"),
    ("design_speed", 200, "design_speed 200 outside 40–140 km/h"),
    ("terrain", "swamp", "terrain 'swamp' not recognised"),
    ("env_sensitivity", "extreme", "env_sensitivity 'extreme' not recognised"),
])
def test_invalid_conditions_are_imputed(field, value, fragment):
    record, warnings = validate_record({"type": "Diamond", "cost": 10, field: value})
    assert record is not None and field in record.imputed
    assert any(w.startswith(fragment) for w in warnings), warnings


@pytest.mark.parametrize("field, value", [
    ("construction_cost_mln", 0), ("land_area_hectares", -3), ("throughput_vph", "lots"),
    ("safety_index", 11), ("safety_index", 0.5),
])
def test_invalid_targets_are_dropped(field, value):
    record, warnings = validate_record({"type": "Diamond", "cost": 10, field: value}
                                       if field != "construction_cost_mln"
                                       else {"type": "Diamond", "capacity": 2500, field: value})
    assert record is not None and field not in record.targets
    assert any(w.startswith(field) and w.endswith("ignored") for w in warnings)


def test_record_without_valid_targets_is_rejected():
    record, warnings = validate_record({"type": "Diamond", "aadt": 30000, "safety_index": 12})
    assert record is None
    assert warnings[-1].startswith("no valid target values")
    assert validate_record({"aadt": 30000, "cost": 4})[0] is None


def test_synonym_keys_and_metadata():
    record, _ = validate_record({
        "Тип розв'язки": "турбіна", "Вартість будівництва": "52,5", "рік": "2017",
        "країна": "Україна", "назва": "Тест", "Синтетичний": "так",
    }, source="real.csv")
    assert record.interchange_type == "Turbine"
    assert record.targets == {"construction_cost_mln": 52.5}
    assert (record.year, record.country, record.name, record.synthetic) == (
        2017, "Україна", "Тест", True)


@pytest.mark.parametrize("source, flag, expected", [
    ("synthetic_demo.csv", None, True), ("Synthetic_Demo.md", "no", True),
    ("real.csv", None, False), ("real.csv", "yes", True), ("real.csv", "false", False),
    ("data/synthetic_x.json", None, True), ("not_synthetic_x.json", None, False),
])
def test_synthetic_flag(source, flag, expected):
    raw = {"type": "Diamond", "cost": 10}
    if flag is not None:
        raw["synthetic"] = flag
    record, _ = validate_record(raw, source=source)
    assert record.synthetic is expected


def test_normalise_fields_parses_units_and_drops_unknown_keys():
    fields, warnings = normalise_fields({
        "Interchange type": "DDI", "Land area (m²)": "60 000", "Cost": "€9M", "colour": "red",
    })
    assert fields == {"interchange_type": "DDI", "land_area_hectares": pytest.approx(6.0)}
    assert len(warnings) == 1 and "currency EUR" in warnings[0]


# ---------------------------------------------------------------------------
# Document readers
# ---------------------------------------------------------------------------


def read(name, content):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return read_document_bytes(name, data)


def test_text_document():
    result = read("ring.md", EN_REPORT)
    assert (result.kind, result.extractor, len(result.records)) == ("text", "rules", 1)
    assert result.warnings == [] and result.records[0].name == "Ring road junction"
    report = result.report()
    assert report == {"name": "ring.md", "kind": "text", "synthetic": False, "records": 1,
                      "extractor": "rules", "warnings": [], "size_bytes": len(EN_REPORT.encode())}


def test_text_document_with_several_records_labels_warnings():
    result = read("two.txt", "Type: Diamond\nCost: $10M\n---\nType: Diamond\nCapacity: 2,500")
    assert len(result.records) == 2
    assert result.records[0].name == "two record 1"
    assert result.warnings[0] == "record 1: aadt missing — reference value 45000 imputed"


def test_empty_text_document_reports_no_records():
    result = read("notes.txt", "nothing useful here")
    assert (result.extractor, result.records) == ("none", [])
    assert result.warnings == ["no project records found"]


CSV_HEADER = ("name,interchange_type,year,country,aadt,num_lanes,design_speed,terrain,"
              "env_sensitivity,construction_cost_mln,land_area_hectares,throughput_vph,"
              "safety_index,synthetic")


def test_csv_canonical_headers():
    csv_text = (CSV_HEADER + "\n"
                "A,Turbine,2020,Poland,60000,3,110,Rolling,Medium,70.5,28,8000,7.8,false\n"
                "\n"
                "B,DDI,2019,USA,41000,2,80,Flat,Low,,6.1,,9.0,false\n")
    result = read("projects.csv", csv_text)
    assert (result.kind, result.extractor, result.warnings) == ("csv", "table", [])
    a, b = result.records
    assert a.targets == {"construction_cost_mln": 70.5, "land_area_hectares": 28,
                         "throughput_vph": 8000, "safety_index": 7.8}
    assert b.targets == {"land_area_hectares": 6.1, "safety_index": 9.0}
    assert (a.name, b.country, a.synthetic) == ("A", "USA", False)


def test_csv_synonym_headers_semicolons_and_units():
    csv_text = ("Тип розв'язки;Інтенсивність;Кількість смуг;Рельєф;Вартість будівництва;"
                "Площа відведення (м²);Пропускна здатність;Колір\n"
                "ромб;24 500;2;рівнинний;10,6 млн дол.;56 000;2 450;синій\n"
                "труба;31 000;2;горбистий;300 млн грн;130 000;3 450;червоний\n")
    result = read("uk.csv", csv_text)
    assert result.warnings[0] == "unknown columns ignored: Колір"
    diamond, trumpet = result.records
    assert diamond.interchange_type == "Diamond" and diamond.aadt == 24500
    assert diamond.targets == pytest.approx(
        {"construction_cost_mln": 10.6, "land_area_hectares": 5.6, "throughput_vph": 2450})
    assert "construction_cost_mln" not in trumpet.targets
    assert any(w.startswith("row 3: ") and "currency UAH" in w for w in result.warnings)


def test_csv_row_warnings_carry_row_numbers():
    csv_text = "type,cost,aadt\nDiamond,10,30000\nRoundabout,5,20000\nDDI,,\n"
    result = read("rows.csv", csv_text)
    assert len(result.records) == 1
    assert "row 3: unknown interchange type 'Roundabout' — record skipped" in result.warnings
    assert any(w.startswith("row 4: no valid target values") for w in result.warnings)
    assert result.records[0].name == "rows row 2"


def test_csv_without_type_column():
    result = read("bad.csv", "cost,aadt\n10,30000\n")
    assert result.records == [] and "no interchange type column" in result.warnings


def test_csv_in_windows_1251_is_decoded():
    data = "тип;вартість\nромб;10\n".encode("cp1251")
    result = read("legacy.csv", data)
    assert len(result.records) == 1 and result.records[0].interchange_type == "Diamond"
    assert result.warnings[0] == "not valid UTF-8 — decoded as Windows-1251"


@pytest.mark.parametrize("payload", [
    [{"interchange_type": "SPUI", "construction_cost_mln": 21, "aadt": 50000}],
    {"records": [{"type": "spui", "cost": "$21M", "aadt": "50,000"}]},
])
def test_json_list_and_records_object(payload):
    result = read("p.json", json.dumps(payload))
    assert (result.kind, result.extractor) == ("json", "table")
    (record,) = result.records
    assert (record.interchange_type, record.aadt) == ("SPUI", 50000)
    assert record.targets == {"construction_cost_mln": 21}


def test_json_bad_shapes():
    assert "invalid JSON" in read("x.json", "{oops").warnings[0]
    assert read("x.json", '{"a": 1}').warnings[0].startswith("expected a list of records")
    result = read("x.json", '[1, {"type": "Diamond", "cost": 9}]')
    assert len(result.records) == 1 and result.warnings[0] == "record 1: not an object — skipped"


def test_jsonl():
    lines = '{"type": "Trumpet", "cost": 12}\nnot json\n\n{"type": "DDI", "capacity": 5500}\n'
    result = read("p.jsonl", lines)
    assert (result.kind, len(result.records)) == ("json", 2)
    assert result.warnings[0].startswith("line 2: invalid JSON")
    assert result.records[1].name == "p line 4"


def test_synthetic_flag_from_filename():
    result = read("synthetic_demo.csv", "type,cost\nDiamond,10\n")
    assert result.synthetic and result.records[0].synthetic
    assert result.report()["synthetic"] is True
    plain = read("demo.csv", "type,cost,synthetic\nDiamond,10,no\nDDI,18,yes\n")
    assert [r.synthetic for r in plain.records] == [False, True] and plain.synthetic


def test_unsupported_extension():
    result = read("x.docx", b"PK")
    assert result.records == [] and result.warnings[0].startswith("unsupported file type")


def _make_pdf(lines):
    """Minimal single-page PDF with a Helvetica text layer (ASCII only)."""
    content = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return out


def test_pdf_document():
    pytest.importorskip("pypdf")
    pdf = _make_pdf(["Interchange type: DDI", "AADT: 41,000 veh/day",
                     "Construction cost: $16.2M", "Capacity: 5,600 veh/h"])
    result = read("report.pdf", pdf)
    assert (result.kind, result.extractor) == ("pdf", "rules")
    (record,) = result.records
    assert record.targets == {"construction_cost_mln": 16.2, "throughput_vph": 5600}


def test_corrupt_pdf():
    pytest.importorskip("pypdf")
    result = read("broken.pdf", b"%PDF-1.4 not really")
    assert result.records == [] and result.warnings[0].startswith("could not read PDF")


def test_pdf_without_pypdf(monkeypatch):
    monkeypatch.setattr(readers, "pdf_available", lambda: False)
    result = read("report.pdf", b"%PDF-1.4")
    assert (result.kind, result.extractor) == ("pdf", "none")
    assert result.warnings[0] == "PDF support not installed: pip install -e .[documents]"


# ---------------------------------------------------------------------------
# Optional LLM extractor (mocked — never calls the network)
# ---------------------------------------------------------------------------


class FakeMessages:
    def __init__(self, reply, stop_reason="end_turn"):
        self.reply, self.stop_reason, self.calls = reply, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=text)],
        )


def fake_client(reply, stop_reason="end_turn"):
    return SimpleNamespace(messages=FakeMessages(reply, stop_reason))


LLM_RECORD = {
    "name": "Prose project", "interchange_type": "DDI", "aadt": 41000, "num_lanes": 2,
    "design_speed": None, "terrain": None, "env_sensitivity": "Medium",
    "construction_cost_mln": 16.2, "land_area_hectares": None, "throughput_vph": 5600,
    "safety_index": None, "year": 2022, "country": None,
}


def test_llm_request_uses_structured_output():
    client = fake_client({"records": [LLM_RECORD]})
    records, warnings = llm_extraction.extract_records_with_llm(
        "Some prose.", "doc.txt", client=client)
    assert records == [LLM_RECORD] and warnings == []
    (call,) = client.messages.calls
    assert call["model"] == llm_extraction.DEFAULT_MODEL == "claude-haiku-5-5"
    assert call["output_config"]["format"] == {
        "type": "json_schema", "schema": llm_extraction.RECORDS_SCHEMA}
    assert "temperature" not in call
    assert "<document>\nSome prose.\n</document>" in call["messages"][0]["content"]
    item = llm_extraction.RECORDS_SCHEMA["properties"]["records"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])


@pytest.mark.parametrize("reply, stop_reason, fragment", [
    ({"records": []}, "refusal", "declined"),
    ('{"records": [', "max_tokens", "cut off"),
    ("not json", "end_turn", "unreadable model output"),
    ({"items": []}, "end_turn", "unreadable model output"),
])
def test_llm_failures_become_warnings(reply, stop_reason, fragment):
    records, warnings = llm_extraction.extract_records_with_llm(
        "text", client=fake_client(reply, stop_reason))
    assert records == [] and fragment in warnings[0]


def test_llm_is_a_fallback_and_its_output_is_validated():
    calls = []

    def fake_llm(text, name):
        calls.append(name)
        bad = dict(LLM_RECORD, interchange_type="Roundabout")
        return [LLM_RECORD, bad], []

    rules = read_document_bytes("rules.txt", b"Type: DDI\nCost: $16M", llm_extract=fake_llm)
    assert rules.extractor == "rules" and calls == []

    prose = read_document_bytes(
        "prose.txt", b"The DDI opened in 2022 and cost sixteen million.", llm_extract=fake_llm)
    assert calls == ["prose.txt"] and prose.extractor == "llm"
    (record,) = prose.records
    assert record.targets == {"construction_cost_mln": 16.2, "throughput_vph": 5600}
    assert record.env_sensitivity == "Medium" and "design_speed" in record.imputed
    assert "LLM record 2: unknown interchange type 'Roundabout' — record skipped" in prose.warnings


def test_llm_not_used_for_tables():
    result = read_document_bytes(
        "x.csv", b"cost\n10\n", llm_extract=lambda *_: pytest.fail("LLM called for a CSV"))
    assert result.records == []


@pytest.mark.parametrize("flag, key, installed, expected", [
    ("1", "sk-test", True, True),
    ("0", "sk-test", True, False),
    ("1", "", True, False),
    ("1", "sk-test", False, False),
])
def test_llm_availability_gate(monkeypatch, flag, key, installed, expected):
    monkeypatch.setenv("TDSS_LLM_EXTRACTION", flag)
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    monkeypatch.setattr(llm_extraction.importlib.util, "find_spec",
                        lambda name: object() if installed else None)
    assert llm_extraction.llm_available() is expected


def test_llm_model_override(monkeypatch):
    monkeypatch.setenv("TDSS_LLM_MODEL", "claude-sonnet-5-5")
    client = fake_client({"records": []})
    llm_extraction.extract_records_with_llm("x", client=client)
    assert client.messages.calls[0]["model"] == "claude-sonnet-5-5"
