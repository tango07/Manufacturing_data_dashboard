"""SQLite storage for the Axiom pipeline.

Table naming:
  raw_<table>        exactly what was read from the source files, plus source_file and source_row
  clean_<table>      typed, validated rows that the KPIs are computed from
  quarantine_<table> rows that broke a quarantine rule, with dq_reason
  dq_exceptions      one row per rule failure (rule_id, table, primary key, source row, action, reason)
  run_fact           one row per clean production run, with child rollups joined on Run_ID
  kpi_snapshot       the full kpis.json payload for each pipeline run
  ingest_log         which source file (and SHA-256) produced each raw table

The database is rebuilt for the raw and derived tables on each ingest, so re-running the pipeline on the
same input gives the same database contents. The ingest_log keeps the file hashes for audit.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DERIVED_TABLES = ("run_fact", "dq_exceptions", "kpi_snapshot")


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _drop_prefixed(conn: sqlite3.Connection, prefix: str) -> None:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?", (prefix + "%",))]
    for name in names:
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')


def write_frame(conn: sqlite3.Connection, name: str, df: pd.DataFrame) -> None:
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
    df.to_sql(name, conn, if_exists="replace", index=False)


def read_frame(conn: sqlite3.Connection, name: str) -> pd.DataFrame:
    return pd.read_sql_query(f'SELECT * FROM "{name}"', conn)


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def replace_raw(conn: sqlite3.Connection, raw: dict[str, pd.DataFrame], sources: list[dict]) -> None:
    """Replace all raw_ tables and the ingest log in one transaction."""
    with conn:
        _drop_prefixed(conn, "raw_")
        _drop_prefixed(conn, "clean_")
        _drop_prefixed(conn, "quarantine_")
        for name in DERIVED_TABLES:
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.execute("DROP TABLE IF EXISTS ingest_log")
        for name, df in raw.items():
            write_frame(conn, f"raw_{name}", df)
        pd.DataFrame(sources, columns=["table_name", "source_file", "source_sha256", "row_count", "mode"]) \
            .to_sql("ingest_log", conn, if_exists="replace", index=False)


def read_raw(conn: sqlite3.Connection, table_names: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for name in table_names:
        if not has_table(conn, f"raw_{name}"):
            raise RuntimeError(f"raw_{name} is missing from the database; run the pipeline with --input first")
        out[name] = read_frame(conn, f"raw_{name}")
    return out


def write_outputs(conn: sqlite3.Connection, clean: dict[str, pd.DataFrame], quarantine: dict[str, pd.DataFrame],
                  exceptions: pd.DataFrame, fact: pd.DataFrame, payload_json: str) -> None:
    with conn:
        for name, df in clean.items():
            write_frame(conn, f"clean_{name}", df)
        for name, df in quarantine.items():
            write_frame(conn, f"quarantine_{name}", df)
        write_frame(conn, "dq_exceptions", exceptions)
        write_frame(conn, "run_fact", fact)
        conn.execute("DROP TABLE IF EXISTS kpi_snapshot")
        conn.execute("CREATE TABLE kpi_snapshot (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("INSERT INTO kpi_snapshot (id, payload) VALUES (1, ?)", (payload_json,))
