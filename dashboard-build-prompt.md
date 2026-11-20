# Master Build Prompt: Axiom Auto Components Manufacturing Intelligence Dashboard

Paste everything inside the `<prompt>` block below into your coding LLM (Claude Code, Cursor, or an API call with a large context window). Keep the `CLAUDE.md` and `.claude/` folder in the repo root so the agent picks up the project memory, skills, and sub-agents automatically.

Prompt design notes (why it is written this way):
- XML tags separate instructions, data, constraints, and outputs, so the model never confuses the brief with the sample data or the test cases.
- Every rule is stated as a positive instruction plus its reason, which makes edge-case decisions predictable.
- The model is told to show its working (assumptions, counts, exclusions) in a structured output, which satisfies the kata's "Responsible GenAI" criterion.
- Numbers are never invented. The LLM may only narrate values that the deterministic pipeline computed and passed to it.
- Expected outputs are given as worked examples so the model can self-check.

<prompt>

<role>
You are a senior data engineer and analytics product designer. You build reproducible data pipelines and executive dashboards for manufacturing operations. You are rigorous about data grain, joins, denominators, and uncertainty, and you explain trade-offs to non-technical leaders in plain business language.
</role>

<context>
Axiom Auto Components is an automotive supplier with 3 plants, 4 production lines per plant, and multiple machines. Leaders see reports where output looks healthy while rejection costs and downtime rise. Four departments (Production, Maintenance, Quality, Purchasing) export four separate Excel tables with inconsistent data. The COO wants a defensible root-cause analysis, an action plan, and an executive dashboard.

The four connected problems are:
<problem id="PRODUCTION">Missed output targets and unstable yield across plants, lines, and shifts.</problem>
<problem id="RELIABILITY">Recurring machine stoppages reduce available production time.</problem>
<problem id="QUALITY">Excessive rejects, porosity, and inspection failures drive rework.</problem>
<problem id="MATERIALS">Supplier lots and incoming QC may be correlated with downstream defects.</problem>

The core business question is: How can management reduce scrap, unplanned downtime, and delayed deliveries by combining fragmented operational data?
</context>

<input_data>
The source file is `sample data for the pipeline.xlsx`. It contains ONE sheet (`Sheet1`) with FOUR stacked tables. Each table begins with a title row in column A, followed by a blank row, then a header row, then data rows. Table titles are inconsistent (for example, `excel  - Material batches` has a double space and a different capitalization). Detect tables by their title text, not by fixed row numbers.

<table name="production_runs" title_contains="production runs" header_row_contains="Run_ID">
Columns: Run_ID, Production_Date, Plant_ID, Production_Line, Machine_ID, Shift, Product_ID, Supplier_ID, Material_Lot_ID, Planned_Units, Produced_Units, Reported_Good_Units, Standard_Cycle_Sec, Actual_Run_Minutes, Scheduled_Minutes, Unit_Cost_USD
Grain: one row per run. Primary key: Run_ID.
</table>

<table name="machine_downtime" title_contains="machine downtime" header_row_contains="Downtime_ID">
Columns: Downtime_ID, Run_ID, Event_Start, Plant_ID, Machine_ID, Downtime_Minutes, Failure_Category, Failure_Reason, Maintenance_Type, Repair_Cost_USD
Grain: one row per stoppage event. Run_ID may repeat. Primary key: Downtime_ID.
</table>

<table name="quality_inspections" title_contains="quality inspection" header_row_contains="Inspection_ID">
Columns: Inspection_ID, Run_ID, Inspection_Time, Plant_ID, Product_ID, Sample_Size, Defect_Count, Defect_Type, Inspection_Result, Inspector_ID
Grain: one row per inspection sample. Run_ID may repeat. Primary key: Inspection_ID.
</table>

<table name="material_batches" title_contains="material batches" header_row_contains="Material_Record_ID">
Columns: Material_Record_ID, Run_ID, Material_Lot_ID, Supplier_ID, Material_Type, Received_Date, Material_Grade, Moisture_Pct, Purity_Pct, Incoming_QC_Status, Material_Cost_USD
Grain: one row per material record. Run_ID may repeat. Primary key: Material_Record_ID.
</table>

The uploaded sample is a SMALL EXCERPT for development. Its row counts are: production_runs = 2, machine_downtime = 1, quality_inspections = 2, material_batches = 2. The real submission data will be larger. Every code path must work for any row count, including zero.
</input_data>

<join_rules>
Production runs are the fact grain. Join the child tables to production_runs on Run_ID.
1. Aggregate each child table to Run_ID BEFORE joining. A naive join multiplies Produced_Units and Unit_Cost when a Run_ID repeats in a child table, which inflates totals. Build a per-run rollup for each child table, then left-join each rollup onto production_runs.
2. Use a left join from production_runs. Never drop production runs because they have no downtime, inspection, or material records. Treat a missing child record as zero stoppage, zero samples, or unknown material, and report which of these applies.
3. Track orphan child records. A child row whose Run_ID does not exist in production_runs is an orphan. Keep orphans in a quarantine table with a reason code. Do not silently discard them.
4. Integrate incrementally in this order and reconcile after each step: (a) production + downtime, (b) add quality inspections, (c) add material batches. After each step, assert that the row count of production_runs is unchanged, and log the change in total units and total cost.
5. Check that the sum of per-run rollups equals the sum of the raw child table, minus any quarantined rows. This is the reconciliation check.
</join_rules>

<data_quality_rules>
Implement each check as a named, testable function. Record every failure in an exception log with: rule_id, table, primary_key, field, value, action (quarantine | correct | flag), and reason.

DQ-01 Null or duplicate primary key: Primary keys must be non-null and unique within their table. Duplicates are quarantined except for the first occurrence, which is kept, and this is logged.
DQ-02 Broken foreign key: Run_ID in each child table must exist in production_runs. Failing rows are quarantined as orphans.
DQ-03 Timestamp validity: Parse timestamps. Unparseable values are quarantined. Flag timestamps outside the production window (data range observed in production_runs plus or minus a configurable tolerance).
DQ-04 Numeric range: Units, minutes, costs, and percentages must be non-negative. Moisture_Pct and Purity_Pct must be between 0 and 100.
DQ-05 Impossible values: Reported_Good_Units must be less than or equal to Produced_Units. Actual_Run_Minutes must be less than or equal to Scheduled_Minutes. Defect_Count must be less than or equal to Sample_Size. Quarantine or correct these rows and log the rule.
DQ-06 Categorical standardization: Trim whitespace, normalize case, and map codes to canonical values (for example "pass", "PASS ", "Pass" become "PASS"). Cross-check that Plant_ID, Machine_ID, and Supplier_ID values exist in a reference list derived from the data. Flag unknown codes.
DQ-07 Cross-table consistency: A downtime or inspection row must have the same Plant_ID as its parent production run. Mismatches are flagged, not silently corrected. Machine_ID in downtime should match the parent run's Machine_ID; flag mismatches.
DQ-08 One-to-many preservation: Never delete valid repeated Run_ID events. Document any deduplication rule explicitly and only apply it to true duplicate primary keys.

Produce a DQ scorecard with: errors by rule_id, affected row count, rejected row count, and the KPI impact (for example, "removing 1 orphan downtime event changes downtime minutes by 19.1 min, which is 100% of current downtime in this sample"). Report coverage (the share of production runs that have each child record type), cleaned-record counts, and an uncertainty note next to every KPI.
</data_quality_rules>

<kpi_definitions>
Every KPI must state its numerator, denominator, grain, and filter. Show the denominator next to the value. Use these exact definitions:

K1 Plan attainment = SUM(Produced_Units) / SUM(Planned_Units). Grain: plant, line, shift, product, day.
K2 Scrap rate = (SUM(Produced_Units) - SUM(Reported_Good_Units)) / SUM(Produced_Units). Use this formula for the scrap rate. Do not use one-minus-yield variants that compute on a different denominator.
K3 Unplanned downtime minutes = SUM(Downtime_Minutes) where Maintenance_Type = "Unplanned". Also show total downtime minutes and the downtime rate = Downtime_Minutes / Scheduled_Minutes at the run grain, aggregated by summing numerators and denominators.
K4 Repair cost = SUM(Repair_Cost_USD) by plant, machine, shift (via parent run), and Failure_Category.
K5 Sample defect rate = SUM(Defect_Count) / SUM(Sample_Size). Aggregate by summing, never by averaging per-sample rates.
K6 Failures by defect type = SUM(Defect_Count) grouped by Defect_Type.
K7 Incoming QC fail rate = COUNT(Incoming_QC_Status = "FAIL") / COUNT(material records), by supplier and lot.
K8 Moisture and purity = weighted or simple mean by supplier and lot, with the mean method stated.
K9 Material cost and unit cost, where cost is defined as Unit_Cost_USD * Produced_Units if Unit_Cost_USD is per unit. State this as an assumption because the source does not say whether Unit_Cost_USD is per unit or per run.

Every ratio must guard against a zero denominator and display "n/a" with the reason, never Infinity or NaN.
</kpi_definitions>

<leadership_questions>
The dashboard must answer each of these five questions directly, with the evidence, the method, and the uncertainty. Each answer appears in a "Leadership Answers" panel near the top of the dashboard.

Q1 Which plant, machine, and shift show the highest operational losses? Define operational loss as (unplanned downtime minutes) plus (scrap units) and rank segments by it. Show both components separately as well as the combined rank.
Q2 Do frequent material jams explain excess downtime on a specific machine? Test this by comparing downtime on the suspect machine against the other machines, controlling for plant and shift. Report Failure_Reason values such as jam-related reasons, and state whether the association holds within plant and shift. Do not claim causation.
Q3 Does a supplier have more inspection defects or lower incoming material quality? Compare supplier-level defect rate from linked inspections (via Run_ID to Supplier_ID on the run) against supplier-level incoming QC fail rate and moisture/purity. Report both, and state where they disagree.
Q4 Which correlations survive when compared within a plant, product, or shift? Compute each candidate correlation overall, then within each plant, product, and shift stratum. A correlation "survives" only if its sign is consistent across strata and it is not explained by a single stratum. Flag strata with fewer than 5 runs as too small to judge.
Q5 What are the top three interventions, owners, priorities, and success measures? Produce exactly three ranked actions. Each action must include: the evidence KPI and value, the proposed owner (role, not a person's name), the priority (1 to 3), the expected business impact as a hypothesis with a range, and a measurable success metric with a baseline and target.

If the data cannot support an answer, the dashboard must say "Insufficient evidence" and state the minimum data needed. Never fill a gap with a plausible-sounding guess.
</leadership_questions>

<dashboard_requirements>
The dashboard must show at least 5 KPIs, trend comparisons, and drilldowns, and must satisfy every item below:
- KPI cards (K1, K2, K3, K5, K7 minimum), each with its value, denominator, coverage percentage, cleaned-record count, and an uncertainty note.
- Trend chart: K1 and K2 by day or week, with the current period compared to the previous period.
- Drilldown: click plant, then line, then shift, then machine. Breadcrumb navigation returns to the parent level.
- Pareto chart of downtime by Failure_Category and by Failure_Reason.
- Supplier scorecard table: supplier, lot count, incoming QC fail rate, defect rate from linked inspections, moisture, purity. Sortable.
- Data quality panel: the DQ scorecard, plus a link to the exception log.
- Leadership Answers panel: Q1 to Q5 with evidence and confidence level (High, Medium, Low, Insufficient).
- Filters: date range, plant, shift, product. All KPIs and charts update together.
- An "About this data" footer listing source file, pipeline run timestamp, row counts, and quarantine count.
</dashboard_requirements>

<ai_assistant_requirements>
The dashboard includes an AI assistant panel that answers natural-language questions about the data. The app uses an LLM API key, so follow these rules:
1. Never place the API key in browser code. Call the LLM from a backend route that reads the key from an environment variable (`LLM_API_KEY`). Never commit the key.
2. The LLM never computes numbers. The backend first runs the deterministic pipeline, then passes a JSON summary of computed KPIs and the relevant rows to the model. The model narrates and explains. If a user asks for a number that is not in the summary, the model must say it cannot compute it from the current data.
3. Each answer must cite the KPI IDs and the denominators it used, and state the confidence level.
4. Prompt structure for the model call: a system prompt containing role and rules, a `<data_summary>` block with the JSON, a `<question>` block with the user question, and an `<output_format>` block requiring JSON with fields: answer, evidence (list of KPI IDs with values), assumptions, confidence, and limitations.
5. Include a refusal path: if the question is outside the data, the model returns "out_of_scope" with a suggestion of which KPI to view.
6. Log each prompt and response to a local file for the GenAI evidence appendix. Redact any key material.
</ai_assistant_requirements>

<technical_stack>
Unless the repository already defines a stack, use:
- Pipeline: Python 3.11, pandas, openpyxl, pydantic for schema validation, pytest for tests. Output: `data/processed/*.parquet` or CSV, plus `data/processed/dq_exceptions.csv` and `data/processed/kpis.json`.
- Backend: FastAPI with one route for the LLM proxy and one route that serves the KPI JSON.
- Frontend: React and Vite, Recharts for charts, Vitest and React Testing Library for unit tests, Playwright for end-to-end tests.
- Fonts: a professional sans-serif (Inter or Arial). Use a clear color palette with red and amber for alert states. Make it readable on a projector.
- Keep the pipeline runnable with one command: `make pipeline` or `python -m pipeline.run --input "<path>"`.
</technical_stack>

<deliverables>
Produce the following, in this order, and commit after each step:
A. Data pipeline: reproducible cleaning, join logic, exception log, DQ scorecard. Document all assumptions in `docs/ASSUMPTIONS.md`.
B. Management dashboard: all panels from dashboard_requirements, responsive, with drilldown and filters.
C. Action plan: `docs/ACTION_PLAN.md` with three ranked actions following the Q5 format.
D. GenAI evidence: `docs/GENAI_EVIDENCE.md` listing every prompt used to build the project, which AI assistance was used for each step, the verification performed, and the limitations of the conclusions.
E. Tests: all tests in the test_cases section below, passing.
</deliverables>

<test_cases>
Write these tests before the implementation (test-first). Use the sample workbook as fixture for the golden tests. Each golden test must assert the exact expected value shown.

Parsing and structure
T-01 Block detection finds exactly four tables by title, regardless of extra spaces or capitalization. Expected: production_runs, machine_downtime, quality_inspections, material_batches.
T-02 Row counts per table on the sample: production_runs = 2, machine_downtime = 1, quality_inspections = 2, material_batches = 2.
T-03 Blank rows and the title row are not counted as data rows.
T-04 Header detection works when the header row is found by its key column name, not by a fixed row index.

Data quality
T-05 DQ-02 orphan detection: the downtime row for RUN-000315 is an orphan, because RUN-000315 is not in production_runs for the sample. Expected orphan count for machine_downtime = 1. Same for quality_inspections (RUN-000278, RUN-000570 = 2 orphans) and material_batches (RUN-000695, RUN-000445 = 2 orphans).
T-06 DQ-05 impossible values: a synthetic fixture where Reported_Good_Units = Produced_Units + 1 is quarantined with rule DQ-05.
T-07 DQ-04 negative numbers: a synthetic fixture with Downtime_Minutes = -5 is quarantined with rule DQ-04.
T-08 DQ-01 duplicate primary key: a synthetic fixture with two identical Downtime_ID values keeps the first and logs one exception.
T-09 DQ-08 one-to-many: a synthetic fixture with two downtime rows sharing RUN-000001 keeps both rows and does not flag either as a duplicate.
T-10 DQ-06 normalization: " pass ", "PASS", and "Pass" all map to "PASS".
T-11 Timestamp parse failure: "2026-13-45" is quarantined under DQ-03.

Joins and KPIs
T-12 Pre-aggregation join: a fixture with 1 production run (Produced_Units = 1000, Unit_Cost_USD = 10) and 3 downtime rows on the same Run_ID must produce exactly one joined row, with Produced_Units still 1000 and total cost 10000, not 30000.
T-13 Left join preserves runs: a production run with no downtime, inspection, or material rows still appears in the output, with zero stoppage minutes and an "unknown" coverage flag.
T-14 Golden K1 (plan attainment) on the sample: produced 1883, planned 1947, plan attainment = 0.9671 (rounded to 4 dp).
T-15 Golden K2 (scrap rate) on the sample: (1883 - 1769) / 1883 = 0.0605 (rounded to 4 dp).
T-16 Golden per-run scrap: RUN-000001 = 0.0732, RUN-000002 = 0.0463.
T-17 Golden K5 (sample defect rate) pooled: 7 / 160 = 0.0437 (rounded to 4 dp). The per-sample average (0.06 and 0.0167, mean 0.0383) must NOT be the result. This test guards against averaging rates.
T-18 Zero denominator: a fixture with Planned_Units = 0 returns "n/a" with reason, not Infinity or NaN.
T-19 Reconciliation: sum of per-run rollups equals the raw child total minus quarantined rows, for every child table.
T-20 Filter consistency: applying plant = PLT-01 changes every KPI card, chart, and table together. Test with Playwright.

Leadership answers
T-21 Q5 output always contains exactly three ranked actions, each with KPI evidence, a role-based owner, priority, impact range, and a success metric with baseline and target.
T-22 Q4 stratum rule: a correlation with the same sign in all strata is marked "survives"; a correlation whose sign flips is marked "does not survive"; strata with fewer than 5 runs are marked "too small to judge".
T-23 Q2 with insufficient data: when machine downtime has fewer than 3 events, Q2 returns "Insufficient evidence" and lists the minimum data needed.

Dashboard and assistant
T-24 Accessibility: all KPI cards and charts have text alternatives, and colour is never the only signal for alert state.
T-25 LLM key safety: the frontend bundle contains no string matching the LLM key pattern, and the backend returns 500 with a generic message if `LLM_API_KEY` is missing.
T-26 AI assistant grounding: asking "What is the scrap rate for PLT-03?" when PLT-03 has no runs returns "insufficient data", not a number.
T-27 AI assistant citation: every numeric claim in a response references a KPI ID present in the data summary. Validate with a regex check over the JSON response.
T-28 Out-of-scope refusal: "What is the weather in Pune?" returns out_of_scope.
T-29 Pipeline idempotency: running the pipeline twice on the same input produces byte-identical kpis.json and dq_exceptions.csv.
T-30 Pipeline run summary: the "About this data" footer shows the same row counts and quarantine count as the pipeline output.
</test_cases>

<working_method>
1. Before writing code, restate the four problems, the three joins, and the five leadership questions in your own words, and list any assumptions you must make (for example, the per-unit cost interpretation in K9). Write these to `docs/ASSUMPTIONS.md`.
2. Write the failing tests from test_cases first. Then implement until they pass.
3. After each deliverable, run the full test suite and the pipeline, and report the results.
4. If a requirement conflicts with the data, prefer the data's truth, document the conflict, and continue. Do not stop to ask unless a decision would change the business conclusion.
5. Do not invent numbers. Every figure in the dashboard must trace back to kpis.json, and kpis.json must trace back to the pipeline.
6. Use the time guide from the kata: about 20 minutes to understand and profile, 25 minutes to clean and validate, 30 minutes to combine and calculate, 30 minutes to analyse and visualise, and 15 minutes to prepare the submission.
</working_method>

<output_format>
At the end of the build, reply with:
1. A short summary of what was built (under 150 words).
2. The test results: number passed, failed, and skipped, with any failures explained.
3. The DQ scorecard numbers.
4. The three ranked actions from Q5.
5. A list of assumptions made, with the one that most affects the conclusions marked.
6. The limitations of the conclusions, given the sample size.
Use headings for these sections and plain prose inside them. Do not paste the whole codebase into the reply.
</output_format>

</prompt>

---

## How to use this with the project files

1. Copy `CLAUDE.md` into the root of your project repo. Move the `skills/` and `agents/` folders into a `.claude/` folder at the same root (`.claude/skills/`, `.claude/agents/`).
2. Start the coding agent in that folder, then paste the `<prompt>` block.
3. Use the sub-agents in `.claude/agents/` for specialised steps (pipeline, DQ audit, UI, test verification). Use the skills in `.claude/skills/` as shared reference for DQ rules, KPI formulas, and leadership answers.
4. Set `LLM_API_KEY` in a local `.env` file that is git-ignored. Never paste the key into the prompt.
