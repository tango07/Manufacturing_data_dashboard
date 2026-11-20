"""Chart data for the dashboard.

Every view is computed for each plant x shift filter combination, keyed 'PLANT|SHIFT' with 'ALL' for no filter,
so the dashboard only displays values from kpis.json and every chart follows the same filters.
Sums are taken before dividing, so every rate is a ratio of totals.
"""

from __future__ import annotations

import pandas as pd

ROUND = 6


def _r(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    return round(float(x), ROUND)


def _window_metrics(g: pd.DataFrame, label: str) -> dict | None:
    if g.empty:
        return None
    produced = g["Produced_Units"].sum()
    planned = g["Planned_Units"].sum()
    good = g["Reported_Good_Units"].sum()
    return {
        "label": label,
        "days_with_runs": int(g["Production_Day"].nunique()),
        "runs": int(len(g)),
        "produced_units": _r(produced),
        "plan_attainment": _r(produced / planned) if planned else None,
        "scrap_rate": _r((produced - good) / produced) if produced else None,
        "unplanned_minutes": _r(g["dt_unplanned_minutes"].sum()),
        "repair_cost_usd": _r(g["dt_repair_cost"].sum()),
    }


def _in_window(fact: pd.DataFrame, lo, hi) -> pd.DataFrame:
    return fact[(fact["Production_Day"] >= lo) & (fact["Production_Day"] <= hi)]


def compare_window(fact: pd.DataFrame, lo, hi) -> dict | None:
    """The window [lo, hi] compared with an equal-length window directly before it. Equal lengths keep the
    comparison fair, including for a partly filled month."""
    length = (hi - lo).days + 1
    prev_lo, prev_hi = lo - pd.Timedelta(days=length), lo - pd.Timedelta(days=1)
    current = _window_metrics(_in_window(fact, lo, hi), f"{lo:%d %b} to {hi:%d %b %Y}")
    previous = _window_metrics(_in_window(fact, prev_lo, prev_hi), f"{prev_lo:%d %b} to {prev_hi:%d %b %Y}")
    if current is None or previous is None:
        return None
    change = {k: (None if current[k] is None or previous[k] is None else _r(current[k] - previous[k]))
              for k in ("plan_attainment", "scrap_rate", "unplanned_minutes", "runs", "produced_units")}
    return {"current": current, "previous": previous, "change": change}


def period_ranges(fact: pd.DataFrame) -> dict:
    """The date filter options, as {id: (label, first day, last day)}, all taken from the data's dates."""
    first, last = fact["Production_Day"].min(), fact["Production_Day"].max()
    ranges = {
        "L7": ("Last 7 days", last - pd.Timedelta(days=6), last),
        "L30": ("Last 30 days", last - pd.Timedelta(days=29), last),
        "ALL": ("All data", first, last),
    }
    months = fact["Production_Day"].dt.to_period("M").drop_duplicates().sort_values()
    for m in months:
        lo = max(m.start_time, first)
        hi = min(m.end_time.normalize(), last)
        label = m.strftime("%B %Y") + ("" if hi == m.end_time.normalize() else f" (to {hi:%d %b})")
        ranges[f"M{m.strftime('%Y-%m')}"] = (label, lo, hi)
    return ranges


def _daily(fact: pd.DataFrame, dt: pd.DataFrame) -> list[dict]:
    """Daily plan attainment and scrap rate (from runs), and daily unplanned downtime (from event dates)
    with a 7-day rolling average so the line is readable."""
    if fact.empty:
        return []
    days = fact.groupby("Production_Day").agg(
        produced=("Produced_Units", "sum"), planned=("Planned_Units", "sum"),
        good=("Reported_Good_Units", "sum"))
    index = pd.date_range(days.index.min(), days.index.max(), freq="D")
    days = days.reindex(index).fillna(0.0)
    unplanned = pd.Series(0.0, index=index)
    if not dt.empty:
        events = dt[dt["Maintenance_Type"].astype(str).str.upper().str.strip() == "UNPLANNED"]
        if not events.empty and events["Event_Start"].notna().any():
            per_day = events.groupby(events["Event_Start"].dt.normalize())["Downtime_Minutes"].sum()
            unplanned = per_day.reindex(index).fillna(0.0)
    rolling = unplanned.rolling(7, min_periods=1).mean()
    rows = []
    for day in index:
        d = days.loc[day]
        rows.append({
            "date": day.strftime("%Y-%m-%d"),
            "plan_attainment": _r(d["produced"] / d["planned"]) if d["planned"] else None,
            "scrap_rate": _r((d["produced"] - d["good"]) / d["produced"]) if d["produced"] else None,
            "unplanned_minutes": _r(unplanned.loc[day]),
            "unplanned_7day_avg": _r(rolling.loc[day]),
        })
    return rows


def _ranked(items: list[dict], key: str, descending: bool = True) -> list[dict]:
    return sorted(items, key=lambda r: (r[key] is None, -(r[key] or 0) if descending else (r[key] or 0)))


def _view(fact: pd.DataFrame, dt: pd.DataFrame, insp: pd.DataFrame, mat: pd.DataFrame) -> dict:
    if fact.empty:
        return {"totals": None, "daily": [], "runs_by_product": [], "downtime_by_category": [],
                "scrap_by_line": [], "loss_by_plant": [], "loss_by_machine": [], "qc_by_supplier": [],
                "defect_by_type": [], "materials_by_type": []}

    products = fact.groupby("Product_ID").agg(runs=("Run_ID", "size"), produced=("Produced_Units", "sum"))
    runs_by_product = [{"label": str(k), "runs": int(r["runs"]), "produced_units": _r(r["produced"])}
                       for k, r in products.sort_values("runs", ascending=False).iterrows()]

    linked = dt[dt["Run_ID"].isin(set(fact["Run_ID"]))] if not dt.empty else dt
    cat = linked.groupby("Failure_Category")["Downtime_Minutes"].sum() if not linked.empty else pd.Series(dtype=float)
    total_min = float(cat.sum()) if len(cat) else 0.0
    downtime_by_category = [{"label": str(k), "minutes": _r(v), "share": _r(v / total_min) if total_min else None}
                            for k, v in cat.sort_values(ascending=False).items()]

    lines = fact.groupby(["Plant_ID", "Production_Line"]).agg(
        runs=("Run_ID", "size"), produced=("Produced_Units", "sum"), scrap=("scrap_units", "sum"))
    scrap_by_line = _ranked([{"label": f"{p} · {ln}", "scrap_rate": _r(r["scrap"] / r["produced"]) if r["produced"] else None,
                              "runs": int(r["runs"])} for (p, ln), r in lines.iterrows()], "scrap_rate")

    plants = fact.groupby("Plant_ID").agg(scrap=("scrap_cost_usd", "sum"), repair=("dt_repair_cost", "sum"))
    loss_by_plant = _ranked([{"label": str(p), "scrap_cost_usd": _r(r["scrap"]), "repair_cost_usd": _r(r["repair"]),
                              "total_usd": _r(r["scrap"] + r["repair"])} for p, r in plants.iterrows()], "total_usd")

    machines = fact.groupby("Machine_ID").agg(scrap=("scrap_cost_usd", "sum"), repair=("dt_repair_cost", "sum"))
    loss_by_machine = _ranked([{"label": str(m), "scrap_cost_usd": _r(r["scrap"]), "repair_cost_usd": _r(r["repair"]),
                                "total_usd": _r(r["scrap"] + r["repair"])} for m, r in machines.iterrows()], "total_usd")

    qc = []
    if not mat.empty:
        m = mat[mat["Run_ID"].isin(set(fact["Run_ID"]))]
        for s, grp in m.groupby("Supplier_ID"):
            records = len(grp)
            fails = int((grp["Incoming_QC_Status"].astype(str).str.upper() == "FAIL").sum())
            qc.append({"label": str(s), "fail_rate": _r(fails / records), "records": records})
    qc_by_supplier = _ranked(qc, "fail_rate")

    totals = {"scrap_cost_usd": _r(fact["scrap_cost_usd"].sum()), "repair_cost_usd": _r(fact["dt_repair_cost"].sum())}
    # Defect types (K6) and sample defect rate (K5): inspections linked to the runs in scope.
    linked_insp = insp[insp["Run_ID"].isin(set(fact["Run_ID"]))] if not insp.empty else insp
    defect_by_type = []
    if not linked_insp.empty:
        grouped = linked_insp.groupby("Defect_Type").agg(
            defects=("Defect_Count", "sum"), sample=("Sample_Size", "sum"), inspections=("Inspection_ID", "size"))
        defect_by_type = _ranked([{"label": str(k), "defects": _r(r["defects"]), "sample": _r(r["sample"]),
                                   "rate": _r(r["defects"] / r["sample"]) if r["sample"] else None,
                                   "inspections": int(r["inspections"])} for k, r in grouped.iterrows()], "defects")

    # Materials by type (K7, K8, K9): records, incoming QC fail rate, cost, and mean moisture and purity.
    materials_by_type = []
    linked_mat = mat[mat["Run_ID"].isin(set(fact["Run_ID"]))] if not mat.empty else mat
    if not linked_mat.empty:
        for k, grp in linked_mat.groupby("Material_Type"):
            records = len(grp)
            fails = int((grp["Incoming_QC_Status"].astype(str).str.upper() == "FAIL").sum())
            materials_by_type.append({"label": str(k), "records": records,
                                      "fail_rate": _r(fails / records), "cost_usd": _r(grp["Material_Cost_USD"].sum()),
                                      "moisture_mean": _r(grp["Moisture_Pct"].mean()),
                                      "purity_mean": _r(grp["Purity_Pct"].mean())})
        materials_by_type = _ranked(materials_by_type, "records")

    return {"totals": totals, "daily": _daily(fact, linked), "runs_by_product": runs_by_product,
            "downtime_by_category": downtime_by_category, "scrap_by_line": scrap_by_line,
            "loss_by_plant": loss_by_plant, "loss_by_machine": loss_by_machine, "qc_by_supplier": qc_by_supplier,
            "defect_by_type": defect_by_type, "materials_by_type": materials_by_type}


def build_views(fact: pd.DataFrame, dt: pd.DataFrame, insp: pd.DataFrame, mat: pd.DataFrame,
                plants: list, shifts: list) -> dict:
    views = {}
    for p in ["ALL"] + plants:
        for s in ["ALL"] + shifts:
            fseg = fact
            if p != "ALL":
                fseg = fseg[fseg["Plant_ID"] == p]
            if s != "ALL":
                fseg = fseg[fseg["Shift"] == s]
            ids = set(fseg["Run_ID"])
            views[f"{p}|{s}"] = _view(fseg, dt[dt["Run_ID"].isin(ids)] if not dt.empty else dt,
                                      insp[insp["Run_ID"].isin(ids)] if not insp.empty else insp,
                                      mat[mat["Run_ID"].isin(ids)] if not mat.empty else mat)
    return views


def build_slices(fact: pd.DataFrame, dt: pd.DataFrame, insp: pd.DataFrame, mat: pd.DataFrame,
                 plants: list, shifts: list) -> dict:
    """One slice per date filter. Each slice holds the KPI blocks and chart views for every plant x shift,
    plus the comparison with the equal-length window before it."""
    from pipeline.kpis import filtered_blocks

    slices = {}
    for pid, (label, lo, hi) in period_ranges(fact).items():
        fp = _in_window(fact, lo, hi)
        ids = set(fp["Run_ID"])
        dtp = dt[dt["Run_ID"].isin(ids)] if not dt.empty else dt
        inp = insp[insp["Run_ID"].isin(ids)] if not insp.empty else insp
        matp = mat[mat["Run_ID"].isin(ids)] if not mat.empty else mat
        slices[pid] = {
            "label": label,
            "start": f"{lo:%Y-%m-%d}",
            "end": f"{hi:%Y-%m-%d}",
            "comparison": compare_window(fact, lo, hi),
            "blocks": filtered_blocks(fp, dtp, inp, matp, plants, shifts),
            "views": build_views(fp, dtp, inp, matp, plants, shifts),
        }
    return slices


def build_rows(fact: pd.DataFrame, dt: pd.DataFrame, insp: pd.DataFrame, mat: pd.DataFrame) -> dict:
    """The cleaned rows the dashboard adds up for any date range. Columns are named once, here, and the
    dashboard's aggregate.js reads them by name. Only rows that passed the quality rules are exported."""
    def table(columns, frame):
        return {"columns": columns, "data": frame[columns].values.tolist()}

    runs = pd.DataFrame({
        "run": fact["Run_ID"],
        "date": fact["Production_Day"].dt.strftime("%Y-%m-%d"),
        "plant": fact["Plant_ID"], "line": fact["Production_Line"], "machine": fact["Machine_ID"],
        "shift": fact["Shift"], "product": fact["Product_ID"], "supplier": fact["Supplier_ID"],
        "planned": fact["Planned_Units"].astype(float), "produced": fact["Produced_Units"].astype(float),
        "good": fact["Reported_Good_Units"].astype(float), "sched": fact["Scheduled_Minutes"].astype(float),
        "dt_min": fact["dt_minutes"].astype(float), "dt_unpl": fact["dt_unplanned_minutes"].astype(float),
        "dt_repair": fact["dt_repair_cost"].astype(float), "scrap_cost": fact["scrap_cost_usd"].astype(float),
    })
    events = pd.DataFrame({
        "run": dt["Run_ID"],
        "date": dt["Event_Start"].dt.strftime("%Y-%m-%d"),
        "category": dt["Failure_Category"].astype(str).str.upper().str.strip(),
        "minutes": dt["Downtime_Minutes"].astype(float),
        "unplanned": dt["Maintenance_Type"].astype(str).str.upper().str.strip().eq("UNPLANNED"),
    }) if not dt.empty else pd.DataFrame(columns=["run", "date", "category", "minutes", "unplanned"])
    materials = pd.DataFrame({
        "run": mat["Run_ID"],
        "supplier": mat["Supplier_ID"],
        "fail": mat["Incoming_QC_Status"].astype(str).str.upper().str.strip().eq("FAIL"),
        "material_type": mat["Material_Type"],
        "moisture": mat["Moisture_Pct"].astype(float),
        "purity": mat["Purity_Pct"].astype(float),
        "cost": mat["Material_Cost_USD"].astype(float),
    }) if not mat.empty else pd.DataFrame(columns=["run", "supplier", "fail", "material_type", "moisture", "purity", "cost"])
    inspections = pd.DataFrame({
        "run": insp["Run_ID"],
        "defect_type": insp["Defect_Type"],
        "sample": insp["Sample_Size"].astype(float),
        "defects": insp["Defect_Count"].astype(float),
    }) if not insp.empty else pd.DataFrame(columns=["run", "defect_type", "sample", "defects"])
    return {
        "runs": table(list(runs.columns), runs),
        "events": table(list(events.columns), events),
        "materials": table(list(materials.columns), materials),
        "inspections": table(list(inspections.columns), inspections),
    }
