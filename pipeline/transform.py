"""Joins and reconciliation.

Production runs are the fact grain. Each child table is aggregated to Run_ID first, then left-joined
onto production runs. This prevents a repeated Run_ID in a child table from multiplying units or cost.
"""

from __future__ import annotations

import pandas as pd


def is_material_jam(dt: pd.DataFrame) -> pd.Series:
    """A downtime event is a material jam if its category is MATERIAL JAM or its reason mentions a jam.

    The category covers 'Feeder blockage' as well as 'Material jam', so checking the reason text alone
    would miss feeder events.
    """
    category = dt["Failure_Category"].fillna("").astype(str).str.upper().str.strip()
    reason = dt["Failure_Reason"].fillna("").astype(str).str.upper()
    return ((category == "MATERIAL JAM") | reason.str.contains("JAM")).astype(bool)


def rollup_downtime(dt: pd.DataFrame) -> pd.DataFrame:
    if dt.empty:
        return pd.DataFrame(columns=["Run_ID", "dt_events", "dt_minutes", "dt_unplanned_minutes",
                                     "dt_repair_cost", "dt_jam_events"])
    jam = is_material_jam(dt)
    unplanned = dt["Maintenance_Type"].fillna("").eq("UNPLANNED")
    work = pd.DataFrame({
        "Run_ID": dt["Run_ID"],
        "dt_minutes": dt["Downtime_Minutes"],
        "dt_unplanned_minutes": dt["Downtime_Minutes"].where(unplanned, 0.0),
        "dt_repair_cost": dt["Repair_Cost_USD"],
        "dt_jam": jam.astype(int),
    })
    out = work.groupby("Run_ID", as_index=False).agg(
        dt_events=("dt_minutes", "size"),
        dt_minutes=("dt_minutes", "sum"),
        dt_unplanned_minutes=("dt_unplanned_minutes", "sum"),
        dt_repair_cost=("dt_repair_cost", "sum"),
        dt_jam_events=("dt_jam", "sum"),
    )
    return out


def rollup_inspection(insp: pd.DataFrame) -> pd.DataFrame:
    if insp.empty:
        return pd.DataFrame(columns=["Run_ID", "qi_inspections", "qi_sample_size", "qi_defects", "qi_fail_results"])
    work = pd.DataFrame({
        "Run_ID": insp["Run_ID"],
        "qi_sample_size": insp["Sample_Size"],
        "qi_defects": insp["Defect_Count"],
        "qi_fail": insp["Inspection_Result"].fillna("").eq("FAIL").astype(int),
    })
    return work.groupby("Run_ID", as_index=False).agg(
        qi_inspections=("qi_sample_size", "size"),
        qi_sample_size=("qi_sample_size", "sum"),
        qi_defects=("qi_defects", "sum"),
        qi_fail_results=("qi_fail", "sum"),
    )


def rollup_material(mat: pd.DataFrame) -> pd.DataFrame:
    if mat.empty:
        return pd.DataFrame(columns=["Run_ID", "mt_records", "mt_cost", "mt_qc_fail", "mt_moisture_sum", "mt_purity_sum"])
    work = pd.DataFrame({
        "Run_ID": mat["Run_ID"],
        "mt_cost": mat["Material_Cost_USD"],
        "mt_qc_fail": mat["Incoming_QC_Status"].fillna("").eq("FAIL").astype(int),
        "mt_moisture_sum": mat["Moisture_Pct"],
        "mt_purity_sum": mat["Purity_Pct"],
    })
    return work.groupby("Run_ID", as_index=False).agg(
        mt_records=("mt_cost", "size"),
        mt_cost=("mt_cost", "sum"),
        mt_qc_fail=("mt_qc_fail", "sum"),
        mt_moisture_sum=("mt_moisture_sum", "sum"),
        mt_purity_sum=("mt_purity_sum", "sum"),
    )


def build_run_fact(production: pd.DataFrame, downtime: pd.DataFrame,
                   inspection: pd.DataFrame, material: pd.DataFrame) -> pd.DataFrame:
    """One row per clean production run, with child rollups joined on Run_ID (left join)."""
    fact = production.copy()
    for rollup in (rollup_downtime(downtime), rollup_inspection(inspection), rollup_material(material)):
        fact = fact.merge(rollup, on="Run_ID", how="left", validate="one_to_one")

    # Integer counts only. Minutes, costs and percentages stay float: truncating them changes totals.
    count_cols = ["dt_events", "dt_jam_events", "qi_inspections", "qi_sample_size", "qi_defects",
                  "qi_fail_results", "mt_records", "mt_qc_fail"]
    float_cols = ["dt_minutes", "dt_unplanned_minutes", "dt_repair_cost", "mt_cost",
                  "mt_moisture_sum", "mt_purity_sum"]
    for col in float_cols:
        if col in fact.columns:
            fact[col] = pd.to_numeric(fact[col], errors="coerce").fillna(0).astype(float)
    for col in count_cols:
        if col in fact.columns:
            fact[col] = pd.to_numeric(fact[col], errors="coerce").fillna(0).astype(int)

    fact["has_downtime"] = fact["dt_events"] > 0
    fact["has_inspection"] = fact["qi_inspections"] > 0
    fact["has_material"] = fact["mt_records"] > 0
    fact["scrap_units"] = fact["Produced_Units"] - fact["Reported_Good_Units"]
    fact["unit_cost_total"] = fact["Unit_Cost_USD"] * fact["Produced_Units"]
    # Scrap cost in USD (assumption A-01: Unit_Cost_USD is per unit). Used for leadership ranking.
    fact["scrap_cost_usd"] = fact["scrap_units"] * fact["Unit_Cost_USD"]
    fact["Production_Day"] = fact["Production_Date"].dt.normalize()
    return fact


def reconcile(fact: pd.DataFrame, production: pd.DataFrame, downtime: pd.DataFrame,
              inspection: pd.DataFrame, material: pd.DataFrame) -> list[dict]:
    """Checks that the joined output has not inflated or lost totals.

    Each check compares a total on the joined output with the matching total on the clean source
    table. Child totals are compared to the clean child rows whose parent run is in the fact.
    """
    checks = []

    def check(name, left, right):
        ok = abs(float(left) - float(right)) < 1e-6
        checks.append({"check": name, "joined_value": round(float(left), 6),
                       "source_value": round(float(right), 6), "status": "PASS" if ok else "FAIL"})

    check("production row count unchanged by joins", len(fact), len(production))
    check("produced units preserved", fact["Produced_Units"].sum(), production["Produced_Units"].sum())
    check("downtime minutes preserved", fact["dt_minutes"].sum(),
          downtime[downtime["Run_ID"].isin(fact["Run_ID"])]["Downtime_Minutes"].sum())
    check("downtime repair cost preserved", fact["dt_repair_cost"].sum(),
          downtime[downtime["Run_ID"].isin(fact["Run_ID"])]["Repair_Cost_USD"].sum())
    check("inspection defects preserved", fact["qi_defects"].sum(),
          inspection[inspection["Run_ID"].isin(fact["Run_ID"])]["Defect_Count"].sum())
    check("material cost preserved", fact["mt_cost"].sum(),
          material[material["Run_ID"].isin(fact["Run_ID"])]["Material_Cost_USD"].sum())
    return checks
