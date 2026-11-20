# Axiom Auto Components: Manufacturing Intelligence

A reproducible pipeline, a SQLite database and a management dashboard for the EPAM Generative AI Kata (manufacturing data). It ingests four Excel exports, stores them in a database, cleans them with traceable quality rules, joins them at the production-run grain, computes the KPIs, answers the five leadership questions and produces a single-file dashboard.

## Run it

```bash
pip install pandas openpyxl pytest
python -m pipeline.run --input data/raw/full_export                  # the four full exports
python -m pipeline.run --from-db                                     # recompute from the existing database
python -m pytest tests -q
```

Open `dashboard/index.html` in a browser. Charts load Chart.js from a CDN, so the first load needs internet access.

The earlier stacked sample still works: `python -m pipeline.run --input data/raw/sample_data_for_the_pipeline.xlsx`.

## Data flow

Source files are read into `raw_` tables, which keep the Excel row number (`source_row`) and file name for every row. Cleaning reads back from the database and writes `clean_` and `quarantine_` tables, along with `dq_exceptions` (one row per rule failure, with its source row). The join produces `run_fact`, and the KPI payload is stored in `kpi_snapshot`. `ingest_log` records the SHA-256 of each source file.

The database is `data/db/axiom.db`. The JSON and CSV files in `data/processed/` are exports of it.

## Layout

`pipeline/db.py` handles the database. `pipeline/ingest.py` reads the flat exports and the stacked workbook. `pipeline/load.py` holds the stacked-workbook parser. `pipeline/dq.py` applies DQ-01 to DQ-08. `pipeline/transform.py` aggregates child tables to Run_ID before joining, and reconciles totals. `pipeline/kpis.py` computes K1 to K9. `pipeline/leadership.py` answers Q1 to Q5. `pipeline/run.py` orchestrates the stages. `api/assistant_core.py` holds the LLM logic (key handling, prompt, guardrails) without a server. `dashboard/template.html` is the page; `run.py` embeds the KPI JSON into it. `tests/pipeline/` holds 47 tests, including an independent recomputation of the headline KPIs. `docs/` holds the assumptions, the action plan and the GenAI evidence.

## Decisions to know about

The master prompt specified React, Vite, FastAPI and Playwright. This build uses a single HTML page with the data embedded, plus a framework-free assistant module, because the environment has no browser and no FastAPI. Moving to React later is straightforward, since the page only reads `kpis.json`.

Losses are in USD (scrap cost plus repair cost). Scrap cost uses Unit_Cost_USD per unit, which is assumption A-01 and should be confirmed with Finance.

The LLM key is read from the `LLM_API_KEY` environment variable on the server. The dashboard never contains a key or calls the provider directly. The `call_llm` function is not exercised by the tests, because they make no network calls.

## Current limits

The data is a development export. The results describe this export only. The Q2 jam finding is weak, and the action plan says so. Eight production runs have no Run_ID and one Run_ID is duplicated; those rows are quarantined and listed in the DQ scorecard, and they should be fixed at source.
