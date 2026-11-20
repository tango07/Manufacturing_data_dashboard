"""Pipeline entry point.

Usage:
    python -m pipeline.run --input data/raw/full_export            # folder of flat exports (full dataset)
    python -m pipeline.run --input data/raw/sample.xlsx            # single stacked workbook (earlier sample)
    python -m pipeline.run --from-db                               # recompute from the existing database

Flow: ingest source files -> raw_ tables in SQLite -> clean (DQ rules) -> clean_ tables, quarantine_ tables,
dq_exceptions -> join at run grain -> KPIs -> kpis.json, CSV exports, dashboard/index.html.
Every stage that reads or writes data uses the database; the JSON and CSV files are exports of it.

Outputs are deterministic (no timestamps), so re-running on the same input gives identical files.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import db
from pipeline.config import DOWNTIME, INSPECTION, MATERIAL, PIPELINE_VERSION, PRODUCTION, TABLE_SPECS
from pipeline.dq import ExceptionLog, clean_table, production_window
from pipeline.ingest import ingest
from pipeline.kpis import (coverage_summary, daily_trend, dq_scorecard, filtered_blocks, pareto,
                           segment_kpis, supplier_scorecard)
from pipeline.leadership import build_leadership
from pipeline.transform import build_run_fact, reconcile
from pipeline.views import build_rows, build_slices, build_views, period_ranges

ROOT = Path(__file__).resolve().parents[1]

ASSUMPTIONS = [
    {"id": "A-01", "text": "Unit_Cost_USD is per unit. Production cost = Unit_Cost_USD x Produced_Units. Confirm with Finance."},
    {"id": "A-02", "text": "A missing child record (no downtime, inspection or material for a run) is treated as no linked events, and the run is kept by a left join. Coverage shows how many runs have linked records."},
    {"id": "A-03", "text": "Child records whose Run_ID is not a clean production run are excluded from KPIs and listed in quarantine (orphans)."},
    {"id": "A-04", "text": "Repeated Run_ID in child tables is valid one-to-many and is kept (DQ-08). Values are aggregated to Run_ID before joining."},
    {"id": "A-05", "text": "Moisture and purity means are simple means over linked material records; quantity is not in the source, so no weighting is possible."},
    {"id": "A-06", "text": "Categorical codes are normalised to upper case and trimmed (DQ-06). 'NIGHT ' becomes NIGHT, 'sup-04' becomes SUP-04, 'Fail' becomes FAIL."},
    {"id": "A-07", "text": "Production window for DQ-03 flags is the earliest and latest clean run date, plus or minus 7 days. Flags do not remove rows."},
    {"id": "A-08", "text": "Q5 success targets are baseline x 0.8 and impact ranges are 10-20% of baseline. They are hypotheses for validation, not forecasts."},
    {"id": "A-09", "text": "Downtime rate uses SUM(Scheduled_Minutes) over all runs in the segment, including runs with no downtime."},
    {"id": "A-10", "text": "Reference lists (valid plant, machine and supplier codes) come from clean production runs. Codes outside the list are flagged under DQ-06, not removed."},
    {"id": "A-11", "text": "Where two production rows share a Run_ID, the first occurrence in file order is kept and the second is quarantined (DQ-01). Child rows with that Run_ID link to the kept run."},
    {"id": "A-12", "text": "A downtime event is a material jam if its Failure_Category is MATERIAL JAM or its reason mentions a jam. This covers 'Feeder blockage' events, which a reason-only match would miss."},
    {"id": "A-13", "text": "Leadership losses are in USD: loss = scrap cost + repair cost. Scrap cost = scrap units x Unit_Cost_USD (A-01). Minutes and units are never added together."},
    {"id": "A-14", "text": "Q3 treats a signal as elevated when it is more than 1.5 times the median across suppliers. A supplier is flagged as disagreeing only when exactly one of its two signals is elevated."},
    {"id": "A-15", "text": "Q5 actions are ranked by the USD loss behind them. Exposures overlap (for example, the PLT-02 scrap exposure includes runs on MC-07), so the three exposures must not be added together."},
    {"id": "A-16", "text": "Supplier exposure in Q5 is the scrap cost of runs that used that supplier. It shows where losses co-occur, not proof that the supplier caused them."},
    {"id": "A-17", "text": "Q4 stratifies by plant, product, shift and supplier. Supplier is included because it is the most likely confounder of the material-quality and defect associations."},
]


def _clean_json(obj):
    """Recursively convert numpy and pandas types and replace NaN/Inf with None."""
    if isinstance(obj, dict):
        return {str(k): _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if obj is pd.NaT:
        return None
    return obj


def _raw_reference(raw: dict) -> dict:
    """Unfiltered totals straight from the source rows, including orphans and quarantined rows.

    These are NOT used on the dashboard. They show what the raw export would say, so readers can see how
    much the DQ rules changed it.
    """
    insp = raw[INSPECTION.name]
    dt = raw[DOWNTIME.name]
    sample = pd.to_numeric(insp["Sample_Size"], errors="coerce").sum() if len(insp) else 0.0
    defects = pd.to_numeric(insp["Defect_Count"], errors="coerce").sum() if len(insp) else 0.0
    unplanned = pd.to_numeric(dt.loc[dt["Maintenance_Type"].astype(str).str.strip().str.upper() == "UNPLANNED",
                                     "Downtime_Minutes"], errors="coerce").sum() if len(dt) else 0.0
    return {
        "note": "Unfiltered source totals, including orphan and quarantined rows. Not used on the dashboard.",
        "K5_pooled_defect_rate_all_raw_inspections": {
            "numerator": float(defects), "denominator": float(sample),
            "value": round(float(defects / sample), 6) if sample else None,
        },
        "K3a_unplanned_downtime_minutes_all_raw_events": {"value": round(float(unplanned), 6)},
    }


def _ensure_tables(raw: dict) -> dict:
    """Guarantee every table exists with its expected columns, even if its source was missing."""
    out = {}
    for spec in TABLE_SPECS:
        df = raw.get(spec.name)
        if df is None or len(df.columns) == 0:
            df = pd.DataFrame(columns=list(spec.columns) + ["source_row", "source_file"])
        out[spec.name] = df
    return out


def run(input_path: Path | None, out_dir: Path, dashboard_path: Path, db_path: Path | None = None,
        from_db: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    db_path = Path(db_path) if db_path else out_dir / "axiom.db"
    conn = db.connect(db_path)
    log = ExceptionLog()

    # 1. Ingest into raw_ tables (or reuse what the database already holds)
    if from_db:
        raw = db.read_raw(conn, [s.name for s in TABLE_SPECS])
        sources = db.read_frame(conn, "ingest_log").to_dict("records") if db.has_table(conn, "ingest_log") else []
        load_issues, fingerprint, input_name = [], "from_db", "database"
    else:
        if input_path is None:
            raise ValueError("pass --input or --from-db")
        raw, sources, load_issues, fingerprint = ingest(Path(input_path))
        raw = _ensure_tables(raw)            # a missing source still gets a table with its columns
        db.replace_raw(conn, raw, sources)
        # Read back from the database so that cleaning works on what was stored, not on the in-memory frame.
        raw = db.read_raw(conn, [s.name for s in TABLE_SPECS])
        input_name = Path(input_path).name
    raw = _ensure_tables(raw)
    raw_counts = {name: len(df) for name, df in raw.items()}

    # 2. Clean production runs first (parents)
    prod_raw = raw[PRODUCTION.name]
    raw_run_ids = set(prod_raw[PRODUCTION.key_column].dropna().astype(str).str.strip())
    prod_res = clean_table(prod_raw, PRODUCTION, log)
    prod = prod_res.clean
    valid_ids = set(prod[PRODUCTION.key_column])
    window = production_window(prod)
    parent_lookup = {r.Run_ID: {"Plant_ID": r.Plant_ID, "Machine_ID": r.Machine_ID} for r in prod.itertuples()}
    reference = {
        "Plant_ID": set(prod["Plant_ID"].dropna()),
        "Machine_ID": set(prod["Machine_ID"].dropna()),
        "Supplier_ID": set(prod["Supplier_ID"].dropna()),
    }

    # 3. Clean child tables against clean parents, with reference-code checks
    child_results = {}
    for spec in (DOWNTIME, INSPECTION, MATERIAL):
        child_results[spec.name] = clean_table(
            raw[spec.name], spec, log,
            valid_run_ids=valid_ids, raw_run_ids=raw_run_ids,
            parent_lookup=parent_lookup, window=window, reference=reference,
        )
    dt = child_results[DOWNTIME.name].clean
    insp = child_results[INSPECTION.name].clean
    mat = child_results[MATERIAL.name].clean

    quarantine_by_table = {PRODUCTION.name: prod_res.quarantine,
                           DOWNTIME.name: child_results[DOWNTIME.name].quarantine,
                           INSPECTION.name: child_results[INSPECTION.name].quarantine,
                           MATERIAL.name: child_results[MATERIAL.name].quarantine}
    clean_by_table = {PRODUCTION.name: prod, DOWNTIME.name: dt, INSPECTION.name: insp, MATERIAL.name: mat}

    # 4. Join at the correct grain and reconcile
    fact = build_run_fact(prod, dt, insp, mat)
    checks = reconcile(fact, prod, dt, insp, mat)

    # 5. KPIs
    plants = sorted(prod["Plant_ID"].dropna().unique().tolist()) if len(prod) else []
    shifts = sorted(prod["Shift"].dropna().unique().tolist()) if len(prod) else []
    blocks = filtered_blocks(fact, dt, insp, mat, plants, shifts)
    by_machine = {}
    for machine in sorted(fact["Machine_ID"].dropna().unique().tolist()) if len(fact) else []:
        fseg = fact[fact["Machine_ID"] == machine]
        ids = set(fseg["Run_ID"])
        by_machine[machine] = segment_kpis(fseg, dt[dt["Run_ID"].isin(ids)],
                                           insp[insp["Run_ID"].isin(ids)], mat[mat["Run_ID"].isin(ids)])

    linked_dt = dt[dt["Run_ID"].isin(set(fact["Run_ID"]))] if len(fact) else dt.iloc[0:0]
    suppliers = supplier_scorecard(fact, mat) if len(fact) else []
    leadership = build_leadership(fact, linked_dt, suppliers)

    exceptions = log.to_frame()
    dq_rows = dq_scorecard(exceptions, quarantine_by_table)

    # 6. Payload (deterministic: no timestamps)
    payload = {
        "meta": {
            "pipeline_version": PIPELINE_VERSION,
            "input_file": input_name,
            "input_sha256": fingerprint,
            "database": db_path.name,
            "sources": [{k: s[k] for k in ("table_name", "source_file", "source_sha256", "row_count")}
                        for s in sources],
            "load_issues": load_issues,
        },
        "row_counts": {
            name: {"raw": raw_counts[name],
                   "clean": len(clean_by_table[name]),
                   "quarantined": len(quarantine_by_table[name])}
            for name in raw_counts
        },
        "raw_reference": _raw_reference(raw),
        "filters": {"plants": plants, "shifts": shifts},
        "blocks": blocks,
        "by_machine": by_machine,
        "machine_plant": ({m: str(fact.loc[fact["Machine_ID"] == m, "Plant_ID"].mode().iat[0])
                           for m in by_machine} if len(fact) else {}),
        "coverage": coverage_summary(fact),
        "reconciliation": checks,
        "trend": daily_trend(fact) if len(fact) else [],
        "views": build_views(fact, dt, insp, mat, plants, shifts),
        "slices": build_slices(fact, dt, insp, mat, plants, shifts),
        "rows": build_rows(fact, dt, insp, mat),
        "slice_order": (["L30", "L7", "ALL"] + [k for k in period_ranges(fact) if k.startswith("M")]) if len(fact) else [],
        "pareto": {"Failure_Category": pareto(linked_dt, "Failure_Category"),
                   "Failure_Reason": pareto(linked_dt, "Failure_Reason")},
        "suppliers": suppliers,
        "dq_scorecard": dq_rows,
        "leadership": leadership,
        "assumptions": ASSUMPTIONS,
    }
    payload = _clean_json(payload)
    payload_json = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"

    # 7. Persist derived tables to the database
    db.write_outputs(conn, clean_by_table, quarantine_by_table, exceptions, fact, payload_json)
    conn.close()

    # 8. Exports (files are views of the database contents)
    (out_dir / "kpis.json").write_text(payload_json, encoding="utf-8")
    exceptions.sort_values(["rule_id", "table", "primary_key", "field"]).to_csv(
        out_dir / "dq_exceptions.csv", index=False)
    for name, q in quarantine_by_table.items():
        q.to_csv(out_dir / f"quarantine_{name}.csv", index=False)
    fact.to_csv(out_dir / "run_fact.csv", index=False)

    template = (ROOT / "dashboard" / "template.html").read_text(encoding="utf-8")
    aggregate_js = (ROOT / "dashboard" / "aggregate.js").read_text(encoding="utf-8")
    embedded = {k: v for k, v in payload.items() if k not in ("slices", "views")}
    data_js = json.dumps(embedded, sort_keys=True, allow_nan=False)
    html = template.replace("/*__AGGREGATE_JS__*/", aggregate_js).replace("/*__KPI_DATA__*/null", data_js)
    dashboard_path.write_text(html, encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Axiom manufacturing data pipeline")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="folder of flat exports, or a single stacked workbook")
    src.add_argument("--from-db", action="store_true", help="recompute from the raw tables already in the database")
    parser.add_argument("--db", default=str(ROOT / "data" / "db" / "axiom.db"))
    parser.add_argument("--out", default=str(ROOT / "data" / "processed"))
    parser.add_argument("--dashboard", default=str(ROOT / "dashboard" / "index.html"))
    args = parser.parse_args(argv)
    payload = run(Path(args.input) if args.input else None, Path(args.out), Path(args.dashboard),
                  db_path=Path(args.db), from_db=args.from_db)
    print("Row counts (raw / clean / quarantined):")
    for name, c in payload["row_counts"].items():
        print(f"  {name}: {c['raw']} / {c['clean']} / {c['quarantined']}")
    print("Reconciliation:", ", ".join(f"{c['check']}={c['status']}" for c in payload["reconciliation"]))
    print(f"Database: {args.db}")
    print(f"Wrote {args.out}/kpis.json and {args.dashboard}")


if __name__ == "__main__":
    main()
