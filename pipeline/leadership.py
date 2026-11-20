"""Answers to the five leadership questions (skills/leadership-insights/SKILL.md).

Each answer has a status:
  "answered"              enough evidence to state the finding
  "provisional"           a ranking exists, but the evidence behind it is thin
  "insufficient_evidence" the data cannot support the answer; the minimum data needed is stated

Losses are measured in USD so that segments can be compared: loss = scrap cost + repair cost, where
scrap cost = scrap units x Unit_Cost_USD (assumption A-01). Earlier versions added minutes to units,
which has no meaning, so that is no longer used.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.config import (MIN_EVENTS_FOR_Q2, MIN_RUNS_FOR_Q1, MIN_RUNS_PER_STRATUM,
                             PROVISIONAL_TARGET_FACTOR)
from pipeline.transform import is_material_jam

MIN_MATERIAL_RECORDS_FOR_SUPPLIER = 20   # Q5: below this, a supplier's QC fail rate is not used for an action
ELEVATED_FACTOR = 1.5                    # Q3: a signal is elevated when it is this many times the median


def _rank(fact: pd.DataFrame, by: str) -> list[dict]:
    g = fact.groupby(by, dropna=False).agg(
        runs=("Run_ID", "size"),
        unplanned_minutes=("dt_unplanned_minutes", "sum"),
        scrap_units=("scrap_units", "sum"),
        scrap_cost_usd=("scrap_cost_usd", "sum"),
        repair_cost_usd=("dt_repair_cost", "sum"),
    ).reset_index()
    g["loss_usd"] = g["scrap_cost_usd"] + g["repair_cost_usd"]
    g = g.sort_values(["loss_usd", by], ascending=[False, True])
    return [{"segment": str(r[by]), "runs": int(r["runs"]),
             "unplanned_minutes": round(float(r["unplanned_minutes"]), 2),
             "scrap_units": int(r["scrap_units"]),
             "scrap_cost_usd": round(float(r["scrap_cost_usd"]), 2),
             "repair_cost_usd": round(float(r["repair_cost_usd"]), 2),
             "loss_usd": round(float(r["loss_usd"]), 2)}
            for _, r in g.iterrows()]


def _usd(v: float) -> str:
    return f"${v:,.0f}"


def q1_losses(fact: pd.DataFrame) -> dict:
    question = "Which plant, machine and shift show the highest operational losses?"
    runs = len(fact)
    if runs == 0:
        return {"id": "Q1", "question": question, "status": "insufficient_evidence",
                "answer": "No clean production runs.", "rankings": {},
                "minimum_data": "At least one clean production run."}
    rankings = {"plant": _rank(fact, "Plant_ID"), "machine": _rank(fact, "Machine_ID"),
                "shift": _rank(fact, "Shift")}
    top_m = rankings["machine"][0]
    top_p = rankings["plant"][0]
    has_repairs = int(fact["dt_events"].sum()) > 0
    status = "answered" if (runs >= MIN_RUNS_FOR_Q1 and has_repairs) else "provisional"
    answer = (f"Highest-loss machine: {top_m['segment']} at {_usd(top_m['loss_usd'])} "
              f"(scrap {_usd(top_m['scrap_cost_usd'])}, repairs {_usd(top_m['repair_cost_usd'])}). "
              f"Highest-loss plant: {top_p['segment']} at {_usd(top_p['loss_usd'])}. "
              f"Loss = scrap cost + repair cost over {runs} clean runs; scrap cost uses Unit_Cost_USD (assumption A-01).")
    return {"id": "Q1", "question": question, "status": status, "answer": answer, "rankings": rankings,
            "minimum_data": f"At least {MIN_RUNS_FOR_Q1} clean runs with linked repair records."}


def q2_jams(dt: pd.DataFrame, fact: pd.DataFrame) -> dict:
    question = "Do frequent material jams explain excess downtime on a specific machine?"
    linked = dt[dt["Run_ID"].isin(set(fact["Run_ID"]))] if not dt.empty else dt
    n_events = len(linked)
    if n_events < MIN_EVENTS_FOR_Q2:
        return {"id": "Q2", "question": question, "status": "insufficient_evidence", "table": [],
                "answer": (f"Insufficient evidence: {n_events} linked downtime event(s); at least "
                           f"{MIN_EVENTS_FOR_Q2} are needed. Association only; no causation is claimed."),
                "minimum_data": f"At least {MIN_EVENTS_FOR_Q2} linked downtime events."}

    work = linked.assign(jam=is_material_jam(linked))
    work["jam_minutes"] = work["Downtime_Minutes"].where(work["jam"], 0.0)
    g = work.groupby("Machine_ID").agg(events=("Downtime_ID", "size"), jam_events=("jam", "sum"),
                                       minutes=("Downtime_Minutes", "sum"),
                                       jam_minutes=("jam_minutes", "sum")).reset_index()
    g["jam_minute_share"] = g["jam_minutes"] / g["minutes"]
    fleet_share = float(work["jam_minutes"].sum() / work["Downtime_Minutes"].sum())
    g = g.sort_values("minutes", ascending=False)
    table = [{"machine": r["Machine_ID"], "events": int(r["events"]), "jam_events": int(r["jam_events"]),
              "downtime_minutes": round(float(r["minutes"]), 2),
              "jam_minute_share": round(float(r["jam_minute_share"]), 4)} for _, r in g.iterrows()]

    top = table[0]
    ratio = top["jam_minute_share"] / fleet_share if fleet_share else float("inf")
    if ratio >= 1.5:
        verdict = "so jams are a strong part of this machine's downtime; the jam hypothesis is supported by these data"
    elif ratio > 1.0:
        verdict = ("so jams are only slightly above the fleet average on this machine; they cannot explain its "
                   "excess downtime on their own, and the other failure categories need checking")
    else:
        verdict = "so jams do not explain this machine's excess downtime; look at the other failure categories"
    answer = (f"Machine with the most downtime: {top['machine']} ({top['downtime_minutes']:,.0f} min). "
              f"Jam-related events account for {top['jam_minute_share']:.1%} of its downtime minutes, against "
              f"{fleet_share:.1%} across all machines, {verdict}. Association only; no causation is claimed.")
    return {"id": "Q2", "question": question, "status": "answered", "answer": answer,
            "table": table, "fleet_jam_minute_share": round(fleet_share, 4), "minimum_data": ""}


def _elevated(values: dict[str, float]) -> dict[str, bool]:
    vals = [v for v in values.values() if v is not None]
    if not vals:
        return {k: False for k in values}
    median = float(np.median(vals))
    out = {}
    for k, v in values.items():
        if v is None:
            out[k] = False
        elif median > 0:
            out[k] = v > ELEVATED_FACTOR * median
        else:
            out[k] = v > 0
    return out


def q3_suppliers(suppliers: list[dict]) -> dict:
    question = "Does a supplier have more inspection defects or lower incoming material quality?"
    eligible = [s for s in suppliers if s["linked_inspections"] > 0 and s["material_records"] > 0]
    if len(eligible) < 2:
        return {"id": "Q3", "question": question, "status": "insufficient_evidence", "suppliers_elevated_on_both": [],
                "suppliers_disagreeing": [],
                "answer": ("Insufficient evidence: fewer than two suppliers have both linked inspections and "
                           "material records."),
                "minimum_data": "Linked inspections and material records for at least two suppliers."}

    qc = _elevated({s["supplier"]: s["incoming_qc_fail_rate"] for s in eligible})
    df = _elevated({s["supplier"]: s["linked_defect_rate"] for s in eligible})
    both = sorted(k for k in qc if qc[k] and df[k])
    disagree = sorted(k for k in qc if qc[k] != df[k])
    worst = max(eligible, key=lambda s: s["incoming_qc_fail_rate"] or 0)
    answer = (f"{worst['supplier']} has the highest incoming QC fail rate "
              f"({worst['incoming_qc_fail_rate']:.1%} of {worst['material_records']} records) and "
              f"a linked defect rate of {worst['linked_defect_rate']:.1%}. "
              f"Suppliers elevated on both signals: {', '.join(both) or 'none'}. "
              f"Elevated on one signal only: {', '.join(disagree) or 'none'}.")
    return {"id": "Q3", "question": question, "status": "answered", "answer": answer,
            "suppliers_elevated_on_both": both, "suppliers_disagreeing": disagree, "minimum_data": ""}


def _corr(a: pd.Series, b: pd.Series):
    pair = pd.concat([a, b], axis=1).dropna()
    if len(pair) < 3 or pair.iloc[:, 0].std(ddof=0) == 0 or pair.iloc[:, 1].std(ddof=0) == 0:
        return None
    return float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))


def q4_correlations(fact: pd.DataFrame) -> dict:
    per_run = pd.DataFrame({
        "Plant_ID": fact["Plant_ID"],
        "Product_ID": fact["Product_ID"],
        "Shift": fact["Shift"],
        "Supplier_ID": fact["Supplier_ID"],
        "scrap_rate": fact["scrap_units"] / fact["Produced_Units"].replace(0, np.nan),
        "unplanned_downtime_min": fact["dt_unplanned_minutes"].where(fact["has_downtime"]),
        "inspection_defect_rate": fact["qi_defects"] / fact["qi_sample_size"].replace(0, np.nan)
                                    .where(fact["has_inspection"]),
        "material_qc_fail_rate": fact["mt_qc_fail"] / fact["mt_records"].replace(0, np.nan)
                                 .where(fact["has_material"]),
    })
    candidates = [
        ("scrap_rate", "unplanned_downtime_min"),
        ("scrap_rate", "inspection_defect_rate"),
        ("material_qc_fail_rate", "inspection_defect_rate"),
    ]
    results = []
    for x, y in candidates:
        overall = _corr(per_run[x], per_run[y])
        strata = []
        for dim in ("Plant_ID", "Product_ID", "Shift", "Supplier_ID"):
            for value, grp in per_run.groupby(dim):
                n = int(grp[[x, y]].dropna().shape[0])
                if n < MIN_RUNS_PER_STRATUM:
                    strata.append({"dimension": dim, "stratum": str(value), "n": n,
                                   "correlation": None, "judgement": "too small to judge"})
                    continue
                c = _corr(grp[x], grp[y])
                strata.append({"dimension": dim, "stratum": str(value), "n": n,
                               "correlation": None if c is None else round(c, 4),
                               "judgement": "judged" if c is not None else "no variation"})
        judged = [s for s in strata if s["judgement"] == "judged"]
        if overall is None or not judged:
            verdict = "insufficient evidence"
        elif all(np.sign(s["correlation"]) == np.sign(overall) for s in judged):
            verdict = "survives"
        elif any(np.sign(s["correlation"]) != np.sign(overall) for s in judged):
            verdict = "does not survive"
        else:
            verdict = "partially survives"
        results.append({"pair": f"{x} vs {y}",
                        "overall_correlation": None if overall is None else round(overall, 4),
                        "overall_n": int(per_run[[x, y]].dropna().shape[0]),
                        "strata": strata, "verdict": verdict,
                        "judged_strata": len(judged)})

    all_insufficient = all(r["verdict"] == "insufficient evidence" for r in results)
    return {"id": "Q4", "question": "Which correlations survive when compared within a plant, product, shift or supplier?",
            "status": "insufficient_evidence" if all_insufficient else "answered",
            "answer": ("Insufficient evidence: no stratum has at least "
                       f"{MIN_RUNS_PER_STRATUM} runs with both values present, so no correlation can be judged."
                       if all_insufficient else
                       "A correlation survives only if its sign agrees in every judged stratum. Strata with fewer "
                       f"than {MIN_RUNS_PER_STRATUM} runs are not judged. Correlation is association, not cause."),
            "candidates": results,
            "minimum_data": f"At least {MIN_RUNS_PER_STRATUM} runs per stratum with linked downtime and inspection data."}


def _action(title, evidence, owner, baseline, metric, exposure_usd, status, rate_based):
    target = round(baseline * PROVISIONAL_TARGET_FACTOR, 6)
    unit = "rate points" if rate_based else "minutes"
    low, high = round(baseline * 0.10, 6), round(baseline * 0.20, 6)
    return {
        "title": title,
        "status": status,
        "evidence": evidence,
        "owner": owner,
        "exposure_usd": round(exposure_usd, 2),
        "success_metric": {"name": metric, "baseline": round(baseline, 6), "target": target,
                           "target_basis": f"baseline x {PROVISIONAL_TARGET_FACTOR} (hypothesis)"},
        "impact_hypothesis": (f"{_usd(exposure_usd)} of loss sits behind this action. A 10-20% reduction in "
                              f"{metric.lower()} is hypothesised to move it by {low} to {high} {unit}; "
                              "validate against the next data export before committing."),
    }


def q5_actions(fact: pd.DataFrame, q1: dict, suppliers: list[dict]) -> dict:
    """Three actions, ranked by the USD exposure behind each. Ranking is by exposure, not by KPI size."""
    candidates = []

    # A1: the machine with the highest loss (Q1 top machine)
    top_m = q1["rankings"]["machine"][0] if q1.get("rankings", {}).get("machine") else None
    if top_m and top_m["unplanned_minutes"] > 0:
        machine = top_m["segment"]
        plant = str(fact.loc[fact["Machine_ID"] == machine, "Plant_ID"].mode().iat[0])
        events = int(fact.loc[fact["Machine_ID"] == machine, "dt_events"].sum())
        status = "supported" if (events >= MIN_EVENTS_FOR_Q2 and top_m["runs"] >= MIN_RUNS_FOR_Q1) else "provisional"
        candidates.append(_action(
            f"Reduce unplanned downtime on {machine}",
            {"kpi": "K3a", "value": top_m["unplanned_minutes"], "unit": "minutes",
             "denominator": f"{events} linked downtime events on {top_m['runs']} runs"},
            f"Plant Maintenance Manager, {plant}", top_m["unplanned_minutes"],
            "Unplanned downtime minutes on this machine", top_m["loss_usd"], status, rate_based=False))

    # A2: the plant with the highest scrap rate
    rates = []
    for plant, grp in fact.groupby("Plant_ID"):
        produced = grp["Produced_Units"].sum()
        if produced:
            rates.append((plant, float(grp["scrap_units"].sum() / produced), int(len(grp)),
                          float(grp["scrap_cost_usd"].sum())))
    if rates:
        plant, rate, n, cost = max(rates, key=lambda t: t[1])
        status = "supported" if n >= MIN_RUNS_FOR_Q1 else "provisional"
        produced = float(fact.loc[fact["Plant_ID"] == plant, "Produced_Units"].sum())
        candidates.append(_action(
            f"Reduce scrap at {plant}",
            {"kpi": "K2", "value": round(rate, 6), "unit": "ratio",
             "denominator": f"{produced:,.0f} produced units over {n} runs"},
            f"Production Manager, {plant}", rate, "Scrap rate", cost, status, rate_based=True))

    # A3: the supplier with the highest incoming QC fail rate, among suppliers with enough records
    qc = [s for s in suppliers if s["incoming_qc_fail_rate"] is not None
          and s["material_records"] >= MIN_MATERIAL_RECORDS_FOR_SUPPLIER]
    if qc:
        worst = max(qc, key=lambda s: s["incoming_qc_fail_rate"])
        cost = float(fact.loc[fact["Supplier_ID"] == worst["supplier"], "scrap_cost_usd"].sum())
        status = "supported" if worst["linked_inspections"] >= MIN_EVENTS_FOR_Q2 else "provisional"
        candidates.append(_action(
            f"Tighten incoming QC for {worst['supplier']}",
            {"kpi": "K7", "value": worst["incoming_qc_fail_rate"], "unit": "ratio",
             "denominator": f"{worst['material_records']} material records"},
            "Supplier Quality Lead", worst["incoming_qc_fail_rate"], "Incoming QC fail rate", cost, status,
            rate_based=True))

    # Always three slots: a missing action is shown as "insufficient evidence", never dropped or invented.
    slots = {
        "downtime": "Reduce unplanned downtime on the highest-loss machine",
        "scrap": "Reduce scrap at the plant with the highest scrap rate",
        "supplier": "Tighten incoming QC for the supplier with the highest fail rate",
    }
    have = {"downtime": None, "scrap": None, "supplier": None}
    for a in candidates:
        key = ("downtime" if a["title"].startswith("Reduce unplanned") else
               "scrap" if a["title"].startswith("Reduce scrap") else "supplier")
        have[key] = a
    actions = []
    for key in ("downtime", "scrap", "supplier"):
        actions.append(have[key] or {
            "title": slots[key], "status": "insufficient_evidence", "evidence": None, "owner": None,
            "exposure_usd": 0.0, "success_metric": None,
            "impact_hypothesis": "No linked records support this action yet.",
            "minimum_data": {"downtime": "Linked downtime events on at least one machine.",
                             "scrap": "Clean production runs with produced units.",
                             "supplier": f"At least {MIN_MATERIAL_RECORDS_FOR_SUPPLIER} material records per supplier."}[key],
        })
    actions.sort(key=lambda a: -a["exposure_usd"])
    for i, a in enumerate(actions, start=1):
        a["rank"] = i
        a["priority"] = i
    candidates = actions
    overall = "answered" if all(a["status"] == "supported" for a in actions) else "provisional"
    return {"id": "Q5", "question": "What are the top three interventions, owners, priorities and success measures?",
            "status": overall,
            "answer": ("Ranked by the USD loss behind each action, largest first. Impact ranges are hypotheses "
                       "to validate, not forecasts. Supplier exposure is the scrap cost of runs using that supplier, "
                       "which shows where losses co-occur, not proof that the supplier caused them."),
            "actions": candidates,
            "minimum_data": "Full dataset with linked downtime, scrap and incoming-QC records."}


def build_leadership(fact, dt_linked, suppliers) -> dict:
    q1 = q1_losses(fact)
    q2 = q2_jams(dt_linked, fact)
    q3 = q3_suppliers(suppliers)
    q4 = q4_correlations(fact) if len(fact) else {
        "id": "Q4", "question": "Which correlations survive when compared within a plant, product, shift or supplier?",
        "status": "insufficient_evidence", "answer": "No clean production runs.", "candidates": [],
        "minimum_data": "Clean production runs."}
    q5 = q5_actions(fact, q1, suppliers) if len(fact) else {
        "id": "Q5", "question": "What are the top three interventions, owners, priorities and success measures?",
        "status": "insufficient_evidence", "answer": "No clean production runs.", "actions": [],
        "minimum_data": "Clean production runs."}
    return {"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4, "Q5": q5}
