# Assumptions

These assumptions are also written into `data/processed/kpis.json` under `assumptions`, so the dashboard footer and this document stay aligned.

| ID | Assumption | Why it matters | Who should confirm |
|---|---|---|---|
| A-01 | Unit_Cost_USD is per unit, so production cost = Unit_Cost_USD × Produced_Units, and scrap cost = scrap units × Unit_Cost_USD. | Every USD figure depends on it. If the field is per run, the costs are overstated by roughly the number of units per run. | Finance |
| A-02 | A run with no linked downtime, inspection or material record is kept by a left join. Coverage shows how many runs have linked records. | A zero can mean "no events" or "no link". Coverage is shown next to every KPI. | Data owner |
| A-03 | Child records whose Run_ID is not a clean production run are orphans. They are quarantined and excluded from KPIs. | Orphans can carry real downtime, defects or material failures. Excluding them is the conservative choice; the raw totals are kept in `raw_reference`. | Data owner |
| A-04 | Repeated Run_ID in child tables is valid one-to-many (DQ-08). Child rows are summed to Run_ID before the join. | Avoids double counting of units and cost. | Method |
| A-05 | Moisture and purity are simple means over linked material records. Quantity is not in the source, so no weighting is possible. | A weighted mean would be more accurate if quantities were available. | Quality |
| A-06 | Codes are trimmed and normalised to upper case, so "NIGHT " becomes NIGHT, "sup-04" becomes SUP-04 and "Fail" becomes FAIL. | Keeps grouping consistent across the four exports. | Method |
| A-07 | The DQ-03 production window is the earliest and latest clean run date ± 7 days. Events outside it are flagged, not removed. | Flags describe timing only; they do not change any KPI. | Data owner |
| A-08 | Q5 targets are baseline × 0.8, and impact ranges are 10–20% of baseline. | These are hypotheses for validation, not forecasts. | COO office |
| A-09 | Downtime rate uses the sum of Scheduled_Minutes over all runs in the segment, including runs with no downtime. | Gives a stable denominator per segment. | Method |
| A-10 | Reference lists (valid plant, machine and supplier codes) come from clean production runs. Codes outside the list are flagged under DQ-06, not removed. | Catches codes such as MC-99 and SUP-99, which match the shape but do not exist in production. | Data owner |
| A-11 | Where two production rows share a Run_ID, the first occurrence in file order is kept and the second is quarantined. Child rows with that Run_ID link to the kept run. | RUN-000302 appears twice in the export with different dates and lines. The choice of "first" is arbitrary and should be confirmed. | Data owner |
| A-12 | A downtime event is a material jam if its Failure_Category is MATERIAL JAM or its reason mentions a jam. | A reason-only match misses "Feeder blockage" events, which belong to the material-jam category. | Maintenance |
| A-13 | Leadership losses are in USD: loss = scrap cost + repair cost. Minutes and units are never added together. | An earlier version added minutes to units, which has no meaning. | Method |
| A-14 | Q3 treats a signal as elevated when it is more than 1.5 times the median across suppliers. A supplier is flagged as disagreeing only when exactly one of its two signals is elevated. | Stops a 0.0004 difference in defect rate from being reported as a disagreement. | Method |
| A-15 | Q5 actions are ranked by the USD loss behind them. Exposures overlap, so they must not be added together. | PLT-02's scrap exposure includes runs on MC-07 and on SUP-04. | Method |
| A-16 | Supplier exposure in Q5 is the scrap cost of runs that used that supplier. It shows where losses co-occur, not proof that the supplier caused them. | Prevents a supplier association being read as a cause. | Quality |
| A-17 | Q4 stratifies by plant, product, shift and supplier. Supplier is included because it is the most likely confounder of the material-quality and defect associations. | Without it, the material-quality association could be explained by one supplier. | Method |

Two things the data cannot tell us. One is whether Unit_Cost_USD is per unit (A-01). The other is whether the same plant, machine and supplier codes mean the same thing in all four exports. The pipeline checks the codes against the production reference list under DQ-06, but it cannot tell whether a valid-looking code has been reused.
