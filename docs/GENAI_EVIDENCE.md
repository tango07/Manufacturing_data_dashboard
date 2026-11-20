# GenAI evidence

This document records how generative AI was used on this project, what was checked by a second method, and where the conclusions stop being reliable. It supports the kata's "Responsible GenAI" criterion.

## Prompts and assistance

The project began with a master prompt (`dashboard-build-prompt.md`) that briefed a coding assistant on the kata's four problems, the join rules, the DQ rules, the KPI definitions, the leadership questions, the dashboard and 30 test cases. The prompt separates the brief, the data description, the constraints and the expected output with XML tags, and it states that the model must not invent numbers.

The database work came later, from a request to load the four full exports. An AI assistant (Claude) profiled the four files, wrote the ingestion, the database layer and the DQ extensions, and rewrote the leadership logic. The pipeline computes every number, and the dashboard and the assistant module only display or narrate them.

Two of the assistant's own decisions were corrected by the checks described below, and both are recorded in the assumptions. The first was an integer cast that truncated fractional downtime minutes; the reconciliation check caught it. The second was a leadership measure that added minutes to scrap units, which has no meaning; it was replaced with USD. A third problem was found by the test suite: a loader that ended a table at the first blank row, which would have silently dropped data.

## Verification

The assistant's outputs were checked in four ways that do not depend on its own reasoning.

First, the test suite runs 47 tests. They cover the parser, each DQ rule, the joins, the KPIs, the leadership logic, the database, reuse mode and the assistant guardrails. The synthetic-workbook tests build their own inputs.

Second, the headline KPIs were recomputed in a separate implementation (`tests/pipeline/test_full_data.py`). That code reads the four raw workbooks with pandas, applies the same quarantine rules in a simpler form, and does not import the pipeline's cleaning or KPI code. Plan attainment, scrap rate, the sample defect rate and the incoming QC fail rate agree with the pipeline to within 10⁻⁶, and unplanned downtime minutes agree to within 10⁻⁴ minutes. The clean row counts for all four tables also agree.

Third, the database was checked for the properties that matter. Every raw table has 1,000 rows, every clean row plus every quarantined row equals the raw count, the reconciliation checks pass, the ingest log holds the SHA-256 of each source file, and the integrity check returns ok. Each row-level exception carries its source row, so a reader can find the line in the Excel file.

Fourth, the pipeline was run three times: once from the folder of files, once more to confirm byte-identical output, and once in reuse mode from the database. All three give the same KPIs and leadership answers.

## What was not verified

The browser tests for the dashboard (filter behaviour and accessibility, T-20 and T-24) have not been run, because the build environment has no browser. The live LLM call is not tested either, because it needs a real key. The assistant's guardrails are tested without calling the model.

The data is a development export, and the assistant has not confirmed that it matches production systems. The cost figures depend on an unconfirmed assumption about Unit_Cost_USD (A-01).

## Limits of the conclusions

The headline results are reliable as descriptions of this export. Their causes are less certain. The strong association between incoming QC failure and inspection defects is measured across the same runs, and stratification by supplier does not remove the possibility that a third factor drives both. The Q2 jam result is weak (3 points above the fleet average), and the report says so.

The model's role is limited to explaining the numbers. Every number in its reply must cite a KPI ID from the summary. The grounding check in `api/assistant_core.py` flags a reply that cites an unknown KPI ID, but it cannot check that the prose matches the numbers, so a human should read the answers before they are used.
