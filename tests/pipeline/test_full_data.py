"""Full-dataset tests: database contents, reuse mode, and an independent recomputation of headline KPIs.

The independent check (test_independent_recompute_matches_pipeline) does NOT import the pipeline's
cleaning or KPI code. It reads the four raw workbooks with pandas and applies the same quarantine rules
in its own, simpler code. If the two disagree, one of them is wrong, and the test says which number.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from pipeline import db
from pipeline.run import run

ROOT = Path(__file__).resolve().parents[2]
FULL = ROOT / "data" / "raw" / "full_export"
FILES = {
    "prod": FULL / "01_Production_Runs.xlsx",
    "dt": FULL / "02_Machine_Downtime.xlsx",
    "qi": FULL / "03_Quality_Inspections.xlsx",
    "mat": FULL / "04_Material_Batches.xlsx",
}

pytestmark = pytest.mark.skipif(not all(p.exists() for p in FILES.values()),
                                reason="full export not present in data/raw/full_export")


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("full_out")
    dash = tmp_path_factory.mktemp("full_dash") / "index.html"
    dbp = tmp_path_factory.mktemp("full_db") / "axiom.db"
    payload = run(FULL, out, dash, db_path=dbp)
    return {"payload": payload, "out": out, "db": dbp}


# ---------- database ----------------------------------------------------------------------------

def test_database_holds_raw_clean_quarantine_and_snapshot(full_run):
    conn = sqlite3.connect(str(full_run["db"]))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("production_runs", "machine_downtime", "quality_inspections", "material_batches"):
        assert f"raw_{t}" in names, f"raw_{t} missing"
        assert f"clean_{t}" in names, f"clean_{t}" + " missing"
        assert f"quarantine_{t}" in names, f"quarantine_{t} missing"
    for t in ("dq_exceptions", "run_fact", "kpi_snapshot", "ingest_log"):
        assert t in names, f"{t} missing"
    conn.close()


def test_raw_tables_match_source_row_counts(full_run):
    conn = sqlite3.connect(str(full_run["db"]))
    for t in ("production_runs", "machine_downtime", "quality_inspections", "material_batches"):
        n = conn.execute(f"SELECT COUNT(*) FROM raw_{t}").fetchone()[0]
        assert n == 1000, t
    conn.close()


def test_clean_plus_quarantine_equals_raw(full_run):
    conn = sqlite3.connect(str(full_run["db"]))
    for t in ("production_runs", "machine_downtime", "quality_inspections", "material_batches"):
        raw = conn.execute(f"SELECT COUNT(*) FROM raw_{t}").fetchone()[0]
        clean = conn.execute(f"SELECT COUNT(*) FROM clean_{t}").fetchone()[0]
        quar = conn.execute(f"SELECT COUNT(*) FROM quarantine_{t}").fetchone()[0]
        assert clean + quar == raw, t
    conn.close()


def test_every_row_level_exception_traces_to_a_source_row(full_run):
    conn = sqlite3.connect(str(full_run["db"]))
    missing = conn.execute(
        "SELECT COUNT(*) FROM dq_exceptions "
        "WHERE rule_id NOT IN ('DQ-06', 'DQ-08') AND (source_row IS NULL OR source_row = '')"
    ).fetchone()[0]
    conn.close()
    # DQ-06 normalisation and DQ-08 notes are summaries over many rows, so they carry no single source row.
    assert missing == 0


def test_kpi_snapshot_matches_kpis_json(full_run):
    conn = sqlite3.connect(str(full_run["db"]))
    stored = json.loads(conn.execute("SELECT payload FROM kpi_snapshot WHERE id = 1").fetchone()[0])
    conn.close()
    assert stored["blocks"]["ALL|ALL"]["K1"]["value"] == full_run["payload"]["blocks"]["ALL|ALL"]["K1"]["value"]


def test_reuse_mode_gives_same_kpis(full_run, tmp_path):
    out2 = tmp_path / "out2"
    dash2 = tmp_path / "dash2.html"
    again = run(None, out2, dash2, db_path=full_run["db"], from_db=True)
    assert again["blocks"] == full_run["payload"]["blocks"]
    assert again["reconciliation"] == full_run["payload"]["reconciliation"]
    assert again["dq_scorecard"] == full_run["payload"]["dq_scorecard"]


def test_ingest_log_records_each_file_hash(full_run):
    conn = sqlite3.connect(str(full_run["db"]))
    rows = conn.execute("SELECT table_name, source_file, source_sha256, row_count FROM ingest_log").fetchall()
    conn.close()
    assert len(rows) == 4
    assert {r[1] for r in rows} == {p.name for p in FILES.values()}
    assert all(len(r[2]) == 64 and r[3] == 1000 for r in rows)


def test_reconciliation_passes_on_full_data(full_run):
    assert all(c["status"] == "PASS" for c in full_run["payload"]["reconciliation"])


# ---------- independent recomputation -----------------------------------------------------------

def _independent_clean():
    """Second implementation of the quarantine rules, written separately from pipeline/dq.py."""
    prod = pd.read_excel(FILES["prod"], dtype=object)
    dt = pd.read_excel(FILES["dt"], dtype=object)
    qi = pd.read_excel(FILES["qi"], dtype=object)
    mat = pd.read_excel(FILES["mat"], dtype=object)

    def valid_date(s):
        return pd.to_datetime(s, errors="coerce")

    # Production: id present, first occurrence, valid date, good <= produced
    p = prod.copy()
    p["_date"] = valid_date(p["Production_Date"])
    p = p[p["Run_ID"].notna() & p["_date"].notna()]
    p = p[~p["Run_ID"].duplicated(keep="first")]
    p = p[p["Reported_Good_Units"].astype(float) <= p["Produced_Units"].astype(float)]
    run_ids = set(p["Run_ID"].astype(str).str.strip())

    # Children: id present, first occurrence, valid date, numeric rule, parent is a clean run
    d = dt[dt["Downtime_ID"].notna()]
    d = d[~d["Downtime_ID"].duplicated(keep="first")]
    d = d[valid_date(d["Event_Start"]).notna()]
    d = d[d["Downtime_Minutes"].astype(float) >= 0]
    d = d[d["Run_ID"].isin(run_ids)]

    q = qi[qi["Inspection_ID"].notna()]
    q = q[~q["Inspection_ID"].duplicated(keep="first")]
    q = q[valid_date(q["Inspection_Time"]).notna()]
    q = q[q["Defect_Count"].astype(float) <= q["Sample_Size"].astype(float)]
    q = q[q["Run_ID"].isin(run_ids)]

    m = mat[mat["Material_Record_ID"].notna()]
    m = m[~m["Material_Record_ID"].duplicated(keep="first")]
    m = m[valid_date(m["Received_Date"]).notna()]
    m = m[m["Moisture_Pct"].astype(float).between(0, 100)]
    m = m[m["Run_ID"].isin(run_ids)]
    return p, d, q, m


def test_independent_recompute_matches_pipeline(full_run):
    p, d, q, m = _independent_clean()
    k = full_run["payload"]["blocks"]["ALL|ALL"]

    produced = p["Produced_Units"].astype(float).sum()
    planned = p["Planned_Units"].astype(float).sum()
    good = p["Reported_Good_Units"].astype(float).sum()
    assert k["K1"]["value"] == pytest.approx(produced / planned, abs=1e-6)
    assert k["K2"]["value"] == pytest.approx((produced - good) / produced, abs=1e-6)

    unplanned = d.loc[d["Maintenance_Type"].astype(str).str.strip().str.upper() == "UNPLANNED",
                      "Downtime_Minutes"].astype(float).sum()
    assert k["K3a"]["value"] == pytest.approx(unplanned, abs=1e-4)

    defects = q["Defect_Count"].astype(float).sum()
    sample = q["Sample_Size"].astype(float).sum()
    assert k["K5"]["value"] == pytest.approx(defects / sample, abs=1e-6)

    fails = (m["Incoming_QC_Status"].astype(str).str.strip().str.upper() == "FAIL").sum()
    assert k["K7"]["value"] == pytest.approx(fails / len(m), abs=1e-6)


def test_independent_clean_counts_match_pipeline(full_run):
    p, d, q, m = _independent_clean()
    rc = full_run["payload"]["row_counts"]
    assert len(p) == rc["production_runs"]["clean"]
    assert len(d) == rc["machine_downtime"]["clean"]
    assert len(q) == rc["quality_inspections"]["clean"]
    assert len(m) == rc["material_batches"]["clean"]


# ---------- decisions added with the full data --------------------------------------------------

from pipeline.leadership import q3_suppliers  # noqa: E402
from pipeline.transform import is_material_jam  # noqa: E402


def test_jam_definition_counts_feeder_blockage_by_category():
    dt = pd.DataFrame({
        "Failure_Category": ["Material Jam", "Material Jam", "Mechanical", "Mechanical"],
        "Failure_Reason": ["Feeder blockage", "Material jam", "Drive issue", "Motor jam"],
    })
    # Feeder blockage (by category) and Material jam (by reason) are jams; Drive issue is not;
    # 'Motor jam' under Mechanical counts because the reason mentions a jam.
    assert is_material_jam(dt).tolist() == [True, True, False, True]


def test_q3_flags_only_a_material_difference():
    suppliers = [
        {"supplier": "SUP-01", "material_records": 100, "linked_inspections": 90,
         "incoming_qc_fail_rate": 0.0, "linked_defect_rate": 0.0297},
        {"supplier": "SUP-02", "material_records": 100, "linked_inspections": 90,
         "incoming_qc_fail_rate": 0.0, "linked_defect_rate": 0.0292},
        {"supplier": "SUP-03", "material_records": 100, "linked_inspections": 90,
         "incoming_qc_fail_rate": 0.0, "linked_defect_rate": 0.0289},
        {"supplier": "SUP-04", "material_records": 100, "linked_inspections": 90,
         "incoming_qc_fail_rate": 0.61, "linked_defect_rate": 0.097},
    ]
    out = q3_suppliers(suppliers)
    # A 0.0004 difference in defect rate is not a material disagreement; SUP-04 is elevated on both signals.
    assert out["suppliers_elevated_on_both"] == ["SUP-04"]
    assert out["suppliers_disagreeing"] == []
