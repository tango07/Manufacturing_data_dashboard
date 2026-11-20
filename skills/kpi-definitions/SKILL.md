---
name: kpi-definitions
description: Exact formulas, denominators, and grains for the manufacturing KPIs K1 to K9. Use when computing, testing, or labelling any KPI on the dashboard or in the AI assistant.
---

# KPI definitions

Always compute as sum of numerator divided by sum of denominator. Never average row-level rates. Show the denominator, coverage, and cleaned-record count next to every value. Guard zero denominators and return "n/a" with a reason.

| ID | KPI | Formula | Grain |
|---|---|---|---|
| K1 | Plan attainment | SUM(Produced_Units) / SUM(Planned_Units) | plant, line, shift, product, day |
| K2 | Scrap rate | (SUM(Produced_Units) - SUM(Reported_Good_Units)) / SUM(Produced_Units) | same |
| K3 | Unplanned downtime minutes | SUM(Downtime_Minutes) where Maintenance_Type = "Unplanned"; also total downtime rate = SUM(Downtime_Minutes) / SUM(Scheduled_Minutes) | run, then roll up |
| K4 | Repair cost | SUM(Repair_Cost_USD) by plant, machine, shift (via parent run), Failure_Category | event |
| K5 | Sample defect rate | SUM(Defect_Count) / SUM(Sample_Size) | inspection |
| K6 | Failures by defect type | SUM(Defect_Count) by Defect_Type | inspection |
| K7 | Incoming QC fail rate | COUNT(Incoming_QC_Status = "FAIL") / COUNT(material records) | supplier, lot |
| K8 | Moisture and purity | Mean by supplier and lot; state whether simple or weighted mean | material record |
| K9 | Material and unit cost | Assumed Unit_Cost_USD * Produced_Units; flag as assumption | run |

## Worked check on the sample

Two runs: produced 997 and 886 (total 1883), planned 996 and 951 (total 1947), good 924 and 845 (total 1769).

K1 = 1883 / 1947 = 0.9671. K2 = (1883 - 1769) / 1883 = 0.0605. Per run, K2 is 0.0732 for RUN-000001 and 0.0463 for RUN-000002.

K5 pooled = 7 / 160 = 0.0437 (samples 6/100 and 1/60). The unweighted average of the two rates would be 0.0383, which is wrong for this purpose.

## Common mistakes to avoid

- Averaging percentages across rows or plants.
- Computing scrap as 1 - yield on a different denominator from K2.
- Summing Repair_Cost_USD after joining to production runs, which double-counts when a run has several events.
- Reporting a KPI without its denominator.
