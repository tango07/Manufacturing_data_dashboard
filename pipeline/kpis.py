"""KPI calculations K1 to K9.

Every rate is sum(numerator) / sum(denominator) over the run-grain fact table. Rates are never
averaged across rows. Each KPI reports its numerator, denominator, coverage and record count, and
returns value None with a reason when the denominator is zero.
"""

from __future__ import annotations

import pandas as pd

ROUND = 6


def _kpi(kid: str, label: str, numerator, denominator, definition: str, coverage: float | None,
         records: int, unit: str) -> dict:
    num = float(numerator) if numerator is not None and not pd.isna(numerator) else 0.0
    den = float(denominator) if denominator is not None and not pd.isna(denominator) else 0.0
    if den == 0:
        value, note = None, "n/a: denominator is zero in this segment"
    else:
        value, note = round(num / den, ROUND), ""
    return {
        "id": kid,
        "label": label,
        "value": value,
        "numerator": round(num, ROUND),
        "denominator": round(den, ROUND),
        "unit": unit,
        "definition": definition,
        "coverage": None if coverage is None else round(coverage, 4),
        "records": int(records),
        "note": note,
    }


def segment_kpis(fact: pd.DataFrame, downtime: pd.DataFrame, inspection: pd.DataFrame,
                 material: pd.DataFrame) -> dict:
    """KPI block for the run rows in `fact` (already filtered to a segment)."""
    n = len(fact)
    cov = lambda col: float(fact[col].mean()) if n else None  # noqa: E731

    produced = fact["Produced_Units"].sum()
    planned = fact["Planned_Units"].sum()
    good = fact["Reported_Good_Units"].sum()
    scheduled = fact["Scheduled_Minutes"].sum()
    dt_minutes = fact["dt_minutes"].sum()
    unplanned = fact["dt_unplanned_minutes"].sum()
    sample = fact["qi_sample_size"].sum()
    defects = fact["qi_defects"].sum()
    mt_records = fact["mt_records"].sum()
    mt_fail = fact["mt_qc_fail"].sum()
    moisture = fact["mt_moisture_sum"].sum()
    purity = fact["mt_purity_sum"].sum()

    k6 = {}
    if not inspection.empty:
        grouped = inspection.groupby("Defect_Type", dropna=False)["Defect_Count"].sum()
        k6 = {str(k): round(float(v), ROUND) for k, v in grouped.items()}

    kpis = {
        "K1": _kpi("K1", "Plan attainment", produced, planned,
                   "SUM(Produced_Units) / SUM(Planned_Units)", 1.0 if n else None, n, "ratio"),
        "K2": _kpi("K2", "Scrap rate", produced - good, produced,
                   "(SUM(Produced_Units) - SUM(Reported_Good_Units)) / SUM(Produced_Units)", 1.0 if n else None,
                   n, "ratio"),
        "K3a": _kpi("K3a", "Unplanned downtime minutes", unplanned, 1.0,
                    "SUM(Downtime_Minutes) where Maintenance_Type = UNPLANNED (value shown as minutes)",
                    cov("has_downtime"), int(fact["dt_events"].sum()), "minutes"),
        "K3b": _kpi("K3b", "Downtime rate", dt_minutes, scheduled,
                    "SUM(Downtime_Minutes) / SUM(Scheduled_Minutes)", cov("has_downtime"),
                    int(fact["dt_events"].sum()), "ratio"),
        "K4": _kpi("K4", "Repair cost (USD)", fact["dt_repair_cost"].sum(), 1.0,
                   "SUM(Repair_Cost_USD) (value shown as USD)", cov("has_downtime"),
                   int(fact["dt_events"].sum()), "USD"),
        "K5": _kpi("K5", "Sample defect rate", defects, sample,
                   "SUM(Defect_Count) / SUM(Sample_Size)", cov("has_inspection"),
                   int(fact["qi_inspections"].sum()), "ratio"),
        "K6": {"id": "K6", "label": "Failures by defect type", "value": k6, "unit": "count",
               "definition": "SUM(Defect_Count) grouped by Defect_Type",
               "coverage": cov("has_inspection"), "records": int(fact["qi_inspections"].sum()), "note": ""},
        "K7": _kpi("K7", "Incoming QC fail rate", mt_fail, mt_records,
                   "COUNT(Incoming_QC_Status = FAIL) / COUNT(material records)", cov("has_material"),
                   int(mt_records), "ratio"),
        "K8_moisture": _kpi("K8_moisture", "Moisture (mean %)", moisture, mt_records,
                            "simple mean of Moisture_Pct over linked material records",
                            cov("has_material"), int(mt_records), "percent"),
        "K8_purity": _kpi("K8_purity", "Purity (mean %)", purity, mt_records,
                          "simple mean of Purity_Pct over linked material records",
                          cov("has_material"), int(mt_records), "percent"),
        "K9": _kpi("K9", "Production cost (USD, assumed per-unit cost)", fact["unit_cost_total"].sum(), produced,
                   "SUM(Unit_Cost_USD * Produced_Units) / SUM(Produced_Units); assumption A-03",
                   1.0 if n else None, n, "USD per unit"),
        "K9_material_cost": _kpi("K9_material_cost", "Material cost (USD)", fact["mt_cost"].sum(), 1.0,
                                 "SUM(Material_Cost_USD) (value shown as USD)", cov("has_material"),
                                 int(mt_records), "USD"),
    }
    # K3a and K4 are totals, not ratios: keep the numerator as the value, denominator 1.
    for key in ("K3a", "K4", "K9_material_cost"):
        kpis[key]["value"] = kpis[key]["numerator"] if n else None
    return kpis


def coverage_summary(fact: pd.DataFrame) -> dict:
    n = len(fact)
    def share(mask_col):
        return round(float(fact[mask_col].mean()), 4) if n else None
    return {
        "production_runs": n,
        "runs_with_downtime": int(fact["has_downtime"].sum()) if n else 0,
        "runs_with_inspection": int(fact["has_inspection"].sum()) if n else 0,
        "runs_with_material": int(fact["has_material"].sum()) if n else 0,
        "share_with_downtime": share("has_downtime"),
        "share_with_inspection": share("has_inspection"),
        "share_with_material": share("has_material"),
    }


def _filter(fact: pd.DataFrame, plant: str | None, shift: str | None) -> pd.DataFrame:
    out = fact
    if plant is not None:
        out = out[out["Plant_ID"] == plant]
    if shift is not None:
        out = out[out["Shift"] == shift]
    return out


def _children_for(fact_seg: pd.DataFrame, dt, insp, mat):
    ids = set(fact_seg["Run_ID"])
    return (dt[dt["Run_ID"].isin(ids)], insp[insp["Run_ID"].isin(ids)], mat[mat["Run_ID"].isin(ids)])


def filtered_blocks(fact, dt, insp, mat, plants: list, shifts: list) -> dict:
    """KPI blocks for every plant x shift combination, keyed 'PLANT|SHIFT' with 'ALL' for no filter."""
    blocks = {}
    for p in ["ALL"] + plants:
        for s in ["ALL"] + shifts:
            fseg = _filter(fact, None if p == "ALL" else p, None if s == "ALL" else s)
            dseg, iseg, mseg = _children_for(fseg, dt, insp, mat)
            blocks[f"{p}|{s}"] = segment_kpis(fseg, dseg, iseg, mseg)
    return blocks


def daily_trend(fact: pd.DataFrame) -> list[dict]:
    rows = []
    for day, grp in fact.groupby("Production_Day"):
        produced = grp["Produced_Units"].sum()
        planned = grp["Planned_Units"].sum()
        good = grp["Reported_Good_Units"].sum()
        rows.append({
            "date": day.strftime("%Y-%m-%d"),
            "K1": round(produced / planned, ROUND) if planned else None,
            "K2": round((produced - good) / produced, ROUND) if produced else None,
            "runs": int(len(grp)),
        })
    return rows


def pareto(dt: pd.DataFrame, column: str) -> list[dict]:
    if dt.empty:
        return []
    grouped = (dt.groupby(column, dropna=False)["Downtime_Minutes"].sum()
               .sort_values(ascending=False))
    total = grouped.sum()
    cum = 0.0
    out = []
    for name, minutes in grouped.items():
        cum += float(minutes)
        out.append({
            "category": str(name),
            "minutes": round(float(minutes), ROUND),
            "share": round(float(minutes) / total, ROUND) if total else None,
            "cumulative_share": round(cum / total, ROUND) if total else None,
        })
    return out


def supplier_scorecard(fact: pd.DataFrame, mat: pd.DataFrame) -> list[dict]:
    """Q3 input. Incoming QC and moisture/purity come from material records; defect rate comes from
    inspections linked to runs whose Supplier_ID is this supplier (via Run_ID)."""
    suppliers = sorted(set(fact["Supplier_ID"].dropna()) | set(mat["Supplier_ID"].dropna()))
    rows = []
    for s in suppliers:
        m = mat[mat["Supplier_ID"] == s]
        f = fact[fact["Supplier_ID"] == s]
        records = len(m)
        lots = int(m["Material_Lot_ID"].nunique()) if records else 0
        fails = int((m["Incoming_QC_Status"] == "FAIL").sum()) if records else 0
        sample = float(f["qi_sample_size"].sum())
        defects = float(f["qi_defects"].sum())
        rows.append({
            "supplier": s,
            "lots": lots,
            "material_records": records,
            "incoming_qc_fail_rate": round(fails / records, ROUND) if records else None,
            "moisture_mean_pct": round(float(m["Moisture_Pct"].mean()), ROUND) if records else None,
            "purity_mean_pct": round(float(m["Purity_Pct"].mean()), ROUND) if records else None,
            "linked_inspections": int(f["qi_inspections"].sum()),
            "linked_defect_rate": round(defects / sample, ROUND) if sample else None,
        })
    return rows


def dq_scorecard(exceptions: pd.DataFrame, quarantine_by_table: dict) -> list[dict]:
    from pipeline.dq import RULE_DESCRIPTIONS

    rows = []
    for rule, desc in RULE_DESCRIPTIONS.items():
        affected = int((exceptions["rule_id"] == rule).sum()) if not exceptions.empty else 0
        rejected = 0
        for tbl, q in quarantine_by_table.items():
            if q.empty or "dq_reason" not in q.columns:
                continue
            rejected += int(q["dq_reason"].str.contains(rule, regex=False).sum())
        impact = "no rows affected"
        if rejected:
            impact = f"{rejected} rows excluded from KPIs"
        if rule == "DQ-02" and rejected:
            minutes = quarantine_by_table.get("machine_downtime", pd.DataFrame())
            if not minutes.empty and "dq_reason" in minutes.columns:
                orphan_min = float(minutes.loc[minutes["dq_reason"].str.contains("DQ-02", regex=False),
                                               "Downtime_Minutes"].sum())
                impact += f"; {orphan_min:.1f} downtime minutes excluded"
        rows.append({"rule_id": rule, "description": desc, "affected_rows": affected,
                     "rejected_rows": rejected, "kpi_impact": impact})
    return rows
