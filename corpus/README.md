# Prediction-model corpus

The **prediction model** (tab *Prediction model* in the UI, `/api/model/*` in the API) corrects
the expert criterion values with what past interchange projects actually cost, occupied, carried
and scored. It learns from the documents in `corpus/documents/` (or the directory named by
`TDSS_CORPUS_DIR`). With no documents it returns the expert values unchanged.

Retraining re-reads every document and refits the model in a few milliseconds — add a document,
press **Retrain**, and the new evidence is used immediately.

## Supported formats

| Extension | Kind | How it is read |
| --- | --- | --- |
| `.csv` | table | Header row of field names, one project per row. `,` `;` or tab delimited. |
| `.json` | table | A list of project objects, or `{"records": [...]}`. |
| `.jsonl` | table | One project object per line. |
| `.txt`, `.md` | text | "Field: value" lines (template below). Several projects per file are separated by a line of three or more dashes `---`. |
| `.pdf` | text | The text layer is extracted, then read like a text document. Needs the optional `documents` extra. |

Uploads are limited to 5 MB per file. File names must be plain names (no folders).

## Fields

Only the interchange type and at least one of the four target values are required. A missing
site condition is replaced by its reference value (shown in brackets) and reported as a warning.
Field names are case-insensitive and may be written in English or Ukrainian; CSV headers may be
the canonical names or any synonym, optionally with a unit in brackets (`Land area (m²)`).

| Field (canonical) | Synonyms (EN / UK) | Unit / values |
| --- | --- | --- |
| `interchange_type` | interchange type, type / тип розв'язки, тип | Cloverleaf, Turbine, Stack (4-Level), Diamond, SPUI, DDI, Trumpet, Directional T (also e.g. clover leaf, four-level, diverging diamond, single point / конюшина, турбіна, чотирирівнева, ромб, розбіжний ромб, одноточкова, труба, напрямна Т) |
| `aadt` | traffic (AADT) / інтенсивність, СДР | vehicles per day [45 000]; `52,000`, `52 000`, `52k`, `52 тис.` |
| `num_lanes` | lanes per direction, lanes / кількість смуг | through lanes per direction, 1–6 [2] |
| `design_speed` | design speed / розрахункова швидкість | km/h, 40–140 [100] |
| `terrain` | terrain / рельєф | Flat, Rolling, Mountainous (рівнинний, горбистий, гірський) [Flat] |
| `env_sensitivity` | environmental sensitivity / екологічна чутливість | Low, Medium, High, Critical (низька, середня, висока, критична) [Low] |
| `construction_cost_mln` | construction cost, cost / вартість будівництва, вартість | **millions of US dollars**: `$48.5M`, `48.5 M USD`, `USD 48.5 million`, `48,5 млн дол.`, `$48,500,000`. Other currencies (грн, UAH, EUR, €) are not converted — the value is skipped with a warning. |
| `land_area_hectares` | land area, land take, right-of-way / площа, площа відведення | hectares (`ha`, `га`); `m²` / `м2` are converted |
| `throughput_vph` | capacity, throughput / пропускна здатність | vehicles per hour (`veh/h`, `vph`, `авт/год`) |
| `safety_index` | safety index / індекс безпеки | score 1–10 |
| `name` | project, name / проєкт, назва | free text |
| `year` | year / рік | e.g. 2019 |
| `country` | country / країна | free text |
| `synthetic` | synthetic / синтетичний | `yes`/`true`/`так` marks demo data |

Numbers may use thousands separators (comma, space, apostrophe) and a decimal comma or point:
`52,000` → 52000, `48,5` → 48.5.

## Text template (English)

Copy, fill in, save as `.txt` or `.md`. Leave out any line you do not know.

```text
Project: <project name>
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
---
Project: <second project in the same file>
Interchange type: Diamond
...
```

## Шаблон тексту (українською)

```text
Проєкт: <назва проєкту>
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
```

Separators `:` `=` `—` `–` and ` - ` all work; Markdown bullets, bold text and two-column
Markdown tables (`| Field | value |`) are understood too. Lines that do not start with a known
field name are ignored, so the facts can sit inside an ordinary report.

## CSV and JSON

```csv
name,interchange_type,year,country,aadt,num_lanes,design_speed,terrain,env_sensitivity,construction_cost_mln,land_area_hectares,throughput_vph,safety_index
Ring road junction,Turbine,2021,Poland,68000,3,110,Rolling,Medium,78.4,29.6,8050,7.9
```

```json
{"records": [{"interchange_type": "DDI", "aadt": 41000, "num_lanes": 2,
              "construction_cost_mln": 16.2, "throughput_vph": 5600}]}
```

## Synthetic demo data

The files whose names start with `synthetic_` are **invented** examples so the model has
something to show before real documents exist:

- `synthetic_precedents.csv` — 60 generated projects (`python -m scripts.make_synthetic_corpus`
  regenerates it deterministically; the hidden "true" effects are listed in that script);
- `synthetic_report_*.md` — the text format in English and Ukrainian.

A document is treated as synthetic when its file name starts with `synthetic_` or a record has
`synthetic: yes`. The UI flags synthetic records with an amber badge. Delete these files once
real project documents are available.

## Retraining

- UI: *Prediction model* tab → upload documents, then **Retrain** (uploads and deletions retrain
  automatically).
- API: `POST /api/model/retrain`; upload with `POST /api/model/documents` (multipart field
  `file`, `?overwrite=true` to replace); delete with `DELETE /api/model/documents/{name}`;
  status with `GET /api/model/status`.
- Files copied straight into `corpus/documents/` are picked up by the next retrain.

## Optional extras

```bash
pip install -e .[documents]     # pypdf (PDF text) + anthropic (LLM extraction)
```

- **PDF**: with `pypdf` installed, `.pdf` documents are read through their text layer. Scanned
  PDFs without a text layer yield a warning.
- **LLM extraction**: for text or PDF documents in which the rules find no project, Claude can
  read the document and return the records. Enable it explicitly — the document text is sent to
  the Anthropic API:

  ```bash
  export TDSS_LLM_EXTRACTION=1
  export ANTHROPIC_API_KEY=...
  export TDSS_LLM_MODEL=claude-haiku-5-5   # optional; this is the default
  ```

  LLM output is validated exactly like any other record; documents that the rules can read never
  reach the LLM.
