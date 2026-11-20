"""Configuration for the Axiom manufacturing pipeline.

All thresholds and table definitions live here so that rules are visible in one place.
"""

from dataclasses import dataclass

PIPELINE_VERSION = "1.0.0"

# Quarantine rules and KPI thresholds
DATE_WINDOW_TOLERANCE_DAYS = 7      # DQ-03: child events further than this from the run window are flagged
MIN_RUNS_PER_STRATUM = 5            # Q4: strata smaller than this are "too small to judge"
MIN_EVENTS_FOR_Q2 = 3               # Q2: fewer linked downtime events than this = insufficient evidence
MIN_RUNS_FOR_Q1 = 5                 # Q1: fewer clean runs than this = provisional only
PROVISIONAL_TARGET_FACTOR = 0.8     # Q5: success target = baseline * factor (hypothesis, to be validated)


@dataclass(frozen=True)
class TableSpec:
    name: str
    title_keyword: str          # matched case-insensitively, whitespace-collapsed, against the title row
    key_column: str             # primary key; also used to locate the header row
    numeric: tuple = ()
    datetime: tuple = ()
    categorical: tuple = ()
    foreign_key: str | None = None
    columns: tuple = ()         # expected header names


PRODUCTION = TableSpec(
    name="production_runs",
    title_keyword="production runs",
    key_column="Run_ID",
    numeric=("Planned_Units", "Produced_Units", "Reported_Good_Units", "Standard_Cycle_Sec",
             "Actual_Run_Minutes", "Scheduled_Minutes", "Unit_Cost_USD"),
    datetime=("Production_Date",),
    categorical=("Plant_ID", "Production_Line", "Machine_ID", "Shift", "Product_ID",
                 "Supplier_ID", "Material_Lot_ID"),
    columns=("Run_ID", "Production_Date", "Plant_ID", "Production_Line", "Machine_ID", "Shift",
             "Product_ID", "Supplier_ID", "Material_Lot_ID", "Planned_Units", "Produced_Units",
             "Reported_Good_Units", "Standard_Cycle_Sec", "Actual_Run_Minutes", "Scheduled_Minutes",
             "Unit_Cost_USD"),
)

DOWNTIME = TableSpec(
    name="machine_downtime",
    title_keyword="machine downtime",
    key_column="Downtime_ID",
    numeric=("Downtime_Minutes", "Repair_Cost_USD"),
    datetime=("Event_Start",),
    categorical=("Plant_ID", "Machine_ID", "Failure_Category", "Failure_Reason", "Maintenance_Type"),
    foreign_key="Run_ID",
    columns=("Downtime_ID", "Run_ID", "Event_Start", "Plant_ID", "Machine_ID", "Downtime_Minutes",
             "Failure_Category", "Failure_Reason", "Maintenance_Type", "Repair_Cost_USD"),
)

INSPECTION = TableSpec(
    name="quality_inspections",
    title_keyword="quality inspection",
    key_column="Inspection_ID",
    numeric=("Sample_Size", "Defect_Count"),
    datetime=("Inspection_Time",),
    categorical=("Plant_ID", "Product_ID", "Defect_Type", "Inspection_Result", "Inspector_ID"),
    foreign_key="Run_ID",
    columns=("Inspection_ID", "Run_ID", "Inspection_Time", "Plant_ID", "Product_ID", "Sample_Size",
             "Defect_Count", "Defect_Type", "Inspection_Result", "Inspector_ID"),
)

MATERIAL = TableSpec(
    name="material_batches",
    title_keyword="material batches",
    key_column="Material_Record_ID",
    numeric=("Moisture_Pct", "Purity_Pct", "Material_Cost_USD"),
    datetime=("Received_Date",),
    categorical=("Material_Lot_ID", "Supplier_ID", "Material_Type", "Material_Grade",
                 "Incoming_QC_Status"),
    foreign_key="Run_ID",
    columns=("Material_Record_ID", "Run_ID", "Material_Lot_ID", "Supplier_ID", "Material_Type",
             "Received_Date", "Material_Grade", "Moisture_Pct", "Purity_Pct", "Incoming_QC_Status",
             "Material_Cost_USD"),
)

TABLE_SPECS = (PRODUCTION, DOWNTIME, INSPECTION, MATERIAL)

# DQ-06 format checks: the data is expected to use these code shapes.
CODE_PATTERNS = {
    "Plant_ID": r"^PLT-\d{2}$",
    "Machine_ID": r"^MC-\d{2}$",
    "Supplier_ID": r"^SUP-\d{2}$",
    "Run_ID": r"^RUN-\d{6}$",
    "Material_Lot_ID": r"^LOT-\d{2}-\d{5}$",
}
