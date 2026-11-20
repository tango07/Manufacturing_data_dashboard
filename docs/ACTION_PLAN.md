# Action plan (full dataset)

Basis: the four full exports (1,000 rows each, 975 clean production runs). Figures come from `data/processed/kpis.json`, which the pipeline writes from `data/db/axiom.db`. Impact ranges are hypotheses to validate, not forecasts.

## Headline position

Across the 975 clean runs, plan attainment is 95.8% (823,432 produced against 859,715 planned). Scrap is 3.8% of produced units, which is 31,183 units. Unplanned downtime is 17,695 minutes, and repair cost is $726,932. The sample defect rate is 4.5%, and the incoming QC fail rate is 13.9%. Every one of those rests on linked records, and between 62% and 63% of clean runs have linked downtime, inspection and material records. The other runs show n/a for the metrics that depend on missing links.

## Ranked actions

Actions are ranked by the USD loss behind each one, largest first. The three exposures overlap, because PLT-02 includes runs on MC-07 and runs that used SUP-04, so they must not be added together.

**1. Reduce unplanned downtime on MC-07 (status: supported).** MC-07 has the highest loss of any machine: $236,006, made up of $78,015 in scrap and $157,991 in repairs. It logged 3,843 unplanned minutes across 139 linked downtime events. Owner: Plant Maintenance Manager, PLT-02, since MC-07 runs in that plant. The data suggests jams are only a small part of the problem. Jam-related events account for 19.6% of MC-07's downtime minutes, against 16.4% across the fleet. Mechanical failures are the largest category on this machine, at 3,281 minutes. The first step is a mechanical root-cause review, not a material-handling fix. The success measure is unplanned downtime minutes on MC-07, with a baseline of 3,843 and a hypothesised target of 3,074 (a 20% reduction).

**2. Tighten incoming QC for SUP-04 (status: supported).** SUP-04 is the clearest signal in the data. 130 of its 212 material records failed incoming QC, a fail rate of 61.3%. Every other supplier is at 0% (see the caveat below). Its linked defect rate is 9.7%, against about 2.9% for each of the other four suppliers. The scrap cost of runs that used SUP-04 is $229,794. Owner: Supplier Quality Lead. The action is to hold or re-inspect SUP-04 lots and to start a supplier corrective-action request. Success measure: incoming QC fail rate, baseline 61.3%, target 49.1%.

**3. Reduce scrap at PLT-02 (status: supported).** PLT-02 has the highest scrap rate of the three plants, 4.0%, and the highest loss, $538,848 in total. Its scrap cost is $201,876. Owner: Production Manager, PLT-02. Scrap is spread across the shifts, and NIGHT carries the most scrap units (14,309), so the shift review should start there. Success measure: scrap rate, baseline 4.0%, target 3.2%.

## Caveats the leadership team should see

The SUP-04 finding does not show that SUP-04 caused the scrap. The per-run association between incoming QC failure and inspection defects is strong, at 0.68, and survives stratification by plant, product, shift and supplier. Even so, it is an association across the same runs, and the data does not show that a bad lot is the cause. The action therefore tests the supplier, not the conclusion.

The Q2 finding is weak. MC-07 is the machine with the most downtime, but its jam share is only 3 percentage points above the fleet average. Jams do not explain its excess on their own.

The scrap-versus-downtime correlation does not survive stratification (overall 0.03, with mixed signs across strata). Scrap and unplanned downtime should therefore be treated as separate problems, which is why actions 1 and 3 are separate.

Two data-quality items affect the reliability of these numbers. Eight production runs have no Run_ID, and one Run_ID (RUN-000302) appears twice. The 8 production runs with blank IDs and the 8 with invalid dates are quarantined, along with their child records, so any downtime, scrap or QC events they carried are excluded. Those exclusions are listed in `docs/ASSUMPTIONS.md` and in the DQ scorecard, and they should be fixed at source before the next export.

## Validation before committing budget

Confirm A-01 first, because the cost figures rest on Unit_Cost_USD being per unit. Then check that the SUP-04 lots and the MC-07 repair records are complete in the source systems. Finally, re-run the pipeline on the next export and confirm that the three rankings hold.
