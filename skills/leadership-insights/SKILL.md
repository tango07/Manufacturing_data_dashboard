---
name: leadership-insights
description: Method for answering the five leadership questions (Q1 to Q5) from the Axiom kata with evidence, confidence, and three ranked actions. Use when building the Leadership Answers panel or writing the action plan.
---

# Leadership insights method

The dashboard must answer each question directly. For each answer, record: the answer, the evidence KPIs with values and denominators, the method, a confidence level (High, Medium, Low, or Insufficient), and the limitations.

## Q1: Highest operational losses

Operational loss per segment = unplanned downtime minutes + scrap units. Rank plant, machine, and shift by the combined value, and also show each component separately. A segment high on one component only tells a different story from one high on both, so say which.

## Q2: Do material jams explain excess downtime on a machine?

Compare downtime on the suspect machine against other machines, within each plant and shift. Filter Failure_Reason for jam-related terms and report the share of that machine's downtime they explain. State association only. Confidence is Low if fewer than 3 events.

## Q3: Supplier defects versus incoming quality

For each supplier, compute the defect rate from linked inspections (Run_ID to Supplier_ID on the run; K5) and the incoming QC fail rate (K7) with moisture and purity (K8). Show both. State explicitly where they disagree, because a supplier can pass incoming QC and still produce defects downstream.

## Q4: Which correlations survive stratification?

Compute each candidate correlation overall and within each plant, product, and shift stratum. Rules:
- Same sign in all strata with at least 5 runs: "survives".
- Sign flips across strata: "does not survive" (likely confounded).
- Stratum with fewer than 5 runs: "too small to judge".
- Report the number of strata used.

## Q5: Top three interventions

Produce exactly three actions, ranked 1 to 3. Each action has: the evidence KPI and value, an owner by role (for example "Plant Maintenance Manager, PLT-02"), the priority, a business impact hypothesis with a range, and a success metric with baseline and target. Frame impact as a hypothesis to test, not a forecast.

## Insufficient evidence

When data cannot support an answer, write "Insufficient evidence", state the minimum data needed, and do not substitute a plausible guess. The sample workbook is an excerpt, so many answers will be Insufficient until the full dataset is loaded. That is a correct outcome and should be stated clearly.
