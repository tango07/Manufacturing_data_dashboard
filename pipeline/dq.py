"""Data quality rules DQ-01 to DQ-08.

Every failing cell or row is written to an ExceptionLog. Rows that break a quarantine rule are
moved to a quarantine table with their reasons, never deleted. Flag-only rules annotate the
clean row in a `dq_flags` column.

Rule summary (see skills/dq-rules/SKILL.md):
  DQ-01 primary key null or duplicate (duplicates: first occurrence kept)
  DQ-02 child Run_ID must exist in clean production runs (orphans quarantined)
  DQ-03 timestamps must parse (quarantine); outside the production window +/- tolerance (flag)
  DQ-04 numeric values present, parseable and in range (quarantine)
  DQ-05 impossible values (good > produced, run minutes > scheduled, defects > sample)
  DQ-06 codes normalised (trim, upper case); code shape checked against CODE_PATTERNS (flag)
  DQ-07 child Plant_ID / Machine_ID must match parent run (flag only)
  DQ-08 repeated Run_ID in child tables is valid one-to-many; never deduplicated on Run_ID
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from pipeline.config import CODE_PATTERNS, DATE_WINDOW_TOLERANCE_DAYS, TableSpec

EXCEPTION_COLUMNS = ["rule_id", "table", "primary_key", "source_row", "field", "value", "action", "reason"]

RULE_DESCRIPTIONS = {
    "DQ-01": "Primary key null or duplicate",
    "DQ-02": "Broken Run_ID foreign key (orphan or parent quarantined)",
    "DQ-03": "Timestamp unparseable (quarantine) or outside production window (flag)",
    "DQ-04": "Numeric value missing, non-numeric or negative; percentage outside 0-100",
    "DQ-05": "Impossible value (good > produced, run minutes > scheduled, defects > sample)",
    "DQ-06": "Categorical code normalised, code shape unexpected, or code not in reference list (flag)",
    "DQ-07": "Child Plant_ID or Machine_ID disagrees with parent run (flag)",
    "DQ-08": "Repeated Run_ID in child table kept as valid one-to-many event",
}


@dataclass
class ExceptionLog:
    rows: list = field(default_factory=list)

    def add(self, rule_id, table, primary_key, field_name, value, action, reason, source_row=None):
        self.rows.append({
            "rule_id": rule_id,
            "table": table,
            "primary_key": "" if primary_key is None or (isinstance(primary_key, float) and pd.isna(primary_key))
                           else str(primary_key),
            "source_row": "" if source_row is None or pd.isna(source_row) else int(source_row),
            "field": field_name,
            "value": "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value),
            "action": action,
            "reason": reason,
        })

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=EXCEPTION_COLUMNS)


@dataclass
class CleanResult:
    clean: pd.DataFrame
    quarantine: pd.DataFrame
    raw_count: int


def _is_missing(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def clean_table(
    raw: pd.DataFrame,
    spec: TableSpec,
    log: ExceptionLog,
    *,
    valid_run_ids: set | None = None,
    raw_run_ids: set | None = None,
    parent_lookup: dict | None = None,
    window: tuple | None = None,
    reference: dict | None = None,
) -> CleanResult:
    """Apply DQ rules to one table.

    valid_run_ids: clean production run IDs (required for child tables)
    raw_run_ids: all production run IDs as read, before quarantine (to tell orphans apart from
                 children whose parent was itself quarantined)
    parent_lookup: Run_ID -> {"Plant_ID": ..., "Machine_ID": ...} from clean production runs
    window: (min_date, max_date) of clean production runs for DQ-03 flags
    """
    df = raw.copy().reset_index(drop=True)
    raw_count = len(df)
    key = spec.key_column
    flags: dict[int, list[str]] = {}
    reasons: dict[int, list[str]] = {}

    def record(mask: pd.Series, rule: str, field_name: str | None, reason: str, action: str):
        if not mask.any():
            return
        for idx in df.index[mask]:
            pk = df.at[idx, key] if key in df.columns else None
            value = df.at[idx, field_name] if field_name and field_name in df.columns else None
            row_no = df.at[idx, "source_row"] if "source_row" in df.columns else None
            log.add(rule, spec.name, pk, field_name or "", value, action, reason, source_row=row_no)
            if action == "quarantine":
                reasons.setdefault(idx, []).append(f"{rule}: {reason}")
            else:
                flags.setdefault(idx, []).append(f"{rule}: {reason}")

    # --- Whitespace and empty strings ------------------------------------------------------
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
            df[col] = df[col].replace("", None)

    # --- DQ-06 categorical normalisation -----------------------------------------------------
    for col in spec.categorical:
        if col not in df.columns:
            continue
        original = df[col].copy()
        normalised = original.apply(lambda v: v.upper() if isinstance(v, str) else v)
        changed = original.notna() & (original.astype(str) != normalised.astype(str))
        # One log entry per distinct change, with the number of rows it touched. Per-row entries would
        # bury the real exceptions (thousands of case changes on a full export).
        if changed.any():
            pairs = pd.DataFrame({"from": original[changed].astype(str), "to": normalised[changed].astype(str)})
            for (src_val, dst_val), n in pairs.value_counts().items():
                log.add("DQ-06", spec.name, f"{n} rows", col, src_val, "correct",
                        f"normalised {src_val!r} to {dst_val!r}")
        df[col] = normalised

    # --- DQ-01 primary key -----------------------------------------------------------------
    if key in df.columns:
        record(_is_missing(df[key]), "DQ-01", key, "primary key is null", "quarantine")
        non_null = df[key].notna()
        duplicated = df[key].duplicated(keep="first") & non_null
        record(duplicated, "DQ-01", key, "duplicate primary key (first occurrence kept)", "quarantine")

    # --- DQ-04 type and presence for numeric fields; DQ-03 for datetimes -------------------
    for col in spec.numeric:
        if col not in df.columns:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        bad_type = numeric.isna()
        record(bad_type, "DQ-04", col, "value missing or not numeric", "quarantine")
        df[col] = numeric

    for col in spec.datetime:
        if col not in df.columns:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        bad = parsed.isna()
        record(bad, "DQ-03", col, "timestamp missing or unparseable", "quarantine")
        df[col] = parsed

    # --- DQ-04 ranges ------------------------------------------------------------------------
    for col in spec.numeric:
        if col in df.columns and col not in ("Moisture_Pct", "Purity_Pct"):
            record(df[col] < 0, "DQ-04", col, "negative value", "quarantine")
    for col in ("Moisture_Pct", "Purity_Pct"):
        if col in df.columns:
            record((df[col] < 0) | (df[col] > 100), "DQ-04", col, "percentage outside 0-100", "quarantine")

    # --- DQ-05 impossible values -------------------------------------------------------------
    if spec.name == "production_runs":
        record(df["Reported_Good_Units"] > df["Produced_Units"], "DQ-05", "Reported_Good_Units",
               "good units exceed produced units", "quarantine")
        record(df["Actual_Run_Minutes"] > df["Scheduled_Minutes"], "DQ-05", "Actual_Run_Minutes",
               "actual run minutes exceed scheduled minutes", "quarantine")
    if spec.name == "quality_inspections":
        record(df["Defect_Count"] > df["Sample_Size"], "DQ-05", "Defect_Count",
               "defect count exceeds sample size", "quarantine")

    # --- DQ-02 foreign key -------------------------------------------------------------------
    if spec.foreign_key and valid_run_ids is not None:
        fk = spec.foreign_key
        if fk in df.columns:
            present_clean = df[fk].isin(valid_run_ids)
            raw_ids = raw_run_ids or set()
            orphan = ~present_clean & df[fk].notna()
            parent_quarantined = orphan & df[fk].isin(raw_ids)
            true_orphan = orphan & ~df[fk].isin(raw_ids)
            record(true_orphan, "DQ-02", fk, "Run_ID not found in production_runs (orphan)", "quarantine")
            record(parent_quarantined, "DQ-02", fk,
                   "parent production run was quarantined", "quarantine")
            record(df[fk].isna(), "DQ-02", fk, "Run_ID missing", "quarantine")

    # --- DQ-07 parent consistency (flag only) -----------------------------------------------
    if parent_lookup is not None and spec.foreign_key:
        for col, parent_col in (("Plant_ID", "Plant_ID"), ("Machine_ID", "Machine_ID")):
            if col not in df.columns:
                continue
            parent_val = df[spec.foreign_key].map(lambda r: parent_lookup.get(r, {}).get(parent_col))
            known = parent_val.notna() & df[col].notna()
            mismatch = known & (parent_val != df[col])
            record(mismatch, "DQ-07", col,
                   f"{col} differs from parent production run", "flag")

    # --- DQ-03 window (flag only) -----------------------------------------------------------
    if window is not None and spec.datetime:
        lo, hi = window
        tol = pd.Timedelta(days=DATE_WINDOW_TOLERANCE_DAYS)
        for col in spec.datetime:
            if col not in df.columns:
                continue
            outside = df[col].notna() & ((df[col] < lo - tol) | (df[col] > hi + tol))
            record(outside, "DQ-03", col,
                   f"timestamp outside production window +/- {DATE_WINDOW_TOLERANCE_DAYS} days", "flag")

    # --- DQ-06 code shape and reference list (flag only) -----------------------------------
    for col, pattern in CODE_PATTERNS.items():
        if col in df.columns:
            shape_bad = df[col].notna() & ~df[col].astype(str).str.match(pattern)
            record(shape_bad, "DQ-06", col, f"code does not match expected shape {pattern}", "flag")
    if reference:
        for col, allowed in reference.items():
            if col in df.columns and allowed:
                unknown = df[col].notna() & ~df[col].isin(allowed)
                record(unknown, "DQ-06", col, f"{col} not in reference list from clean production runs", "flag")

    # --- DQ-08 informational -----------------------------------------------------------------
    if spec.foreign_key and spec.foreign_key in df.columns:
        repeated = df[spec.foreign_key].notna() & df[spec.foreign_key].duplicated(keep=False)
        if repeated.any():
            log.add("DQ-08", spec.name, "*", spec.foreign_key, int(repeated.sum()), "keep",
                    "repeated Run_ID kept as one-to-many child events; not deduplicated")

    # --- Split clean and quarantine ----------------------------------------------------------
    df["dq_flags"] = [" | ".join(flags.get(i, [])) for i in df.index]
    quarantine_mask = df.index.isin(list(reasons.keys()))
    quarantine = df[quarantine_mask].copy()
    quarantine["dq_reason"] = [" | ".join(reasons[i]) for i in quarantine.index]
    clean = df[~quarantine_mask].reset_index(drop=True)
    return CleanResult(clean=clean, quarantine=quarantine.reset_index(drop=True), raw_count=raw_count)


def production_window(production_clean: pd.DataFrame) -> tuple | None:
    if production_clean.empty or "Production_Date" not in production_clean.columns:
        return None
    dates = production_clean["Production_Date"].dropna()
    if dates.empty:
        return None
    return dates.min().normalize(), dates.max().normalize()


def valid_code(value) -> bool:
    return isinstance(value, str) and bool(re.match(r"^[A-Z0-9-]+$", value))
