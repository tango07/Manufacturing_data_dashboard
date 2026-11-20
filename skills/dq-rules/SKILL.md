---
name: dq-rules
description: Data quality rules DQ-01 to DQ-08 for the Axiom manufacturing workbook. Use when writing or reviewing cleaning, validation, quarantine, or the DQ scorecard.
---

# Data quality rules

Each rule has an ID, a test, and an action. Every failure writes one row to `dq_exceptions.csv` with: rule_id, table, primary_key, field, value, action, reason.

| ID | Check | Action on failure |
|---|---|---|
| DQ-01 | Primary key (Run_ID, Downtime_ID, Inspection_ID, Material_Record_ID) is non-null and unique within its table | Null: quarantine. Duplicate: keep first, quarantine the rest |
| DQ-02 | Child Run_ID exists in production_runs | Quarantine as orphan |
| DQ-03 | Timestamp parses; value is inside production window +/- tolerance | Unparseable: quarantine. Out of window: flag |
| DQ-04 | Units, minutes, costs, and counts >= 0; Moisture_Pct and Purity_Pct in [0, 100] | Quarantine |
| DQ-05 | Good <= Produced; Actual_Run_Minutes <= Scheduled_Minutes; Defect_Count <= Sample_Size | Quarantine, log the rule |
| DQ-06 | Trim whitespace, normalise case, map codes to canonical values; Plant, Machine, and Supplier IDs appear in the reference list | Normalise. Unknown code: flag |
| DQ-07 | Child Plant_ID matches parent run Plant_ID; child Machine_ID matches parent Machine_ID | Flag only. Never auto-correct |
| DQ-08 | One-to-many events (repeated Run_ID) are kept | Never deduplicate on Run_ID |

## Scorecard

Report per rule: rule_id, affected rows, rejected rows, and KPI impact. Example KPI impact wording: "Quarantining 1 orphan downtime event removes 19.1 downtime minutes; that is 100% of downtime in the sample, so downtime KPIs are not meaningful until the full dataset is loaded."

## Rules of thumb

- Quarantine means moved aside with a reason, never deleted.
- A rule that changes a value must say what changed and why, in the exception log.
- If a rule would remove most of a dataset, stop and report it. Do not tune the rule to make the numbers look better.
