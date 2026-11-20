"""The dashboard's browser-side totals must equal the pipeline's own figures for the same window.

Runs dashboard/aggregate.js under Node (skipped if Node is not installed) against the cleaned rows in
kpis.json, and compares the results with the pipeline's views and comparisons.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = ROOT / "data" / "processed" / "kpis.json"
AGG_JS = ROOT / "dashboard" / "aggregate.js"

RUNNER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const rows = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const cases = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const createAggregator = new Function(src + '; return createAggregator;')();
const agg = createAggregator(rows);
const out = {};
for (const c of cases) {
  out[c.id] = {view: agg.viewFor(c.from, c.to, c.plant, c.shift, c.material || "ALL"),
               cmp: agg.compareWith(c.from, c.to, c.plant, c.shift)};
}
process.stdout.write(JSON.stringify(out));
"""

CASES = [
    ("L30", "ALL", "ALL", "ALL|ALL"),
    ("L7", "ALL", "ALL", "ALL|ALL"),
    ("M2026-08", "PLT-01", "NIGHT", "PLT-01|NIGHT"),
    ("ALL", "PLT-02", "ALL", "PLT-02|ALL"),
    ("ALL", "ALL", "ALL", "ALL|ALL"),
]


@pytest.fixture(scope="module")
def payload():
    if not PAYLOAD.exists():
        pytest.skip("run the pipeline first")
    return json.loads(PAYLOAD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def browser_results(payload, tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    d = tmp_path_factory.mktemp("agg")
    (d / "rows.json").write_text(json.dumps(payload["rows"]), encoding="utf-8")
    cases = []
    for pid, plant, shift, _ in CASES:
        sl = payload["slices"][pid]
        cases.append({"id": f"{pid}|{plant}|{shift}", "from": sl["start"], "to": sl["end"],
                      "plant": plant, "shift": shift})
    (d / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    (d / "runner.js").write_text(RUNNER, encoding="utf-8")
    proc = subprocess.run([node, str(d / "runner.js"), str(AGG_JS), str(d / "rows.json"), str(d / "cases.json")],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _close(a, b, tol=1e-6):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


@pytest.mark.parametrize("pid,plant,shift,key", CASES)
def test_headline_matches_pipeline(payload, browser_results, pid, plant, shift, key):
    got = browser_results[f"{pid}|{plant}|{shift}"]["view"]["headline"]
    want = payload["slices"][pid]["blocks"][key]
    assert got["K1"]["records"] == want["K1"]["records"]
    assert _close(got["K1"]["value"], want["K1"]["value"])
    assert _close(got["K2"]["value"], want["K2"]["value"])
    assert _close(got["K3a"]["value"], want["K3a"]["value"])
    assert _close(got["K3b"]["value"], want["K3b"]["value"])
    assert _close(got["K4"]["value"], want["K4"]["value"])
    assert _close(got["K5"]["value"], want["K5"]["value"])
    assert _close(got["K8_moisture"]["value"], want["K8_moisture"]["value"])
    assert _close(got["K8_purity"]["value"], want["K8_purity"]["value"])
    assert _close(got["K9_material_cost"]["value"], want["K9_material_cost"]["value"], tol=1e-6)


@pytest.mark.parametrize("pid,plant,shift,key", CASES)
def test_charts_match_pipeline(payload, browser_results, pid, plant, shift, key):
    got = browser_results[f"{pid}|{plant}|{shift}"]["view"]
    want = payload["slices"][pid]["views"][key]
    # The page lists every day in the chosen range; the pipeline lists days up to its last run. Compare the
    # days both have, and check the page starts on the same day.
    assert got["daily"][0]["date"] == want["daily"][0]["date"]
    by_date = {r["date"]: r for r in got["daily"]}
    assert {r["date"] for r in want["daily"]} <= set(by_date)
    for w in want["daily"]:
        g = by_date[w["date"]]
        for f in ("plan_attainment", "scrap_rate", "unplanned_minutes", "unplanned_7day_avg"):
            assert _close(g[f], w[f], tol=1e-5), (w["date"], f)
    for list_name, key_field, value_fields in [
        ("runs_by_product", "label", ["runs", "produced_units"]),
        ("downtime_by_category", "label", ["minutes", "share"]),
        ("scrap_by_line", "label", ["scrap_rate", "runs"]),
        ("loss_by_plant", "label", ["scrap_cost_usd", "repair_cost_usd", "total_usd"]),
        ("loss_by_machine", "label", ["scrap_cost_usd", "repair_cost_usd", "total_usd"]),
        ("qc_by_supplier", "label", ["fail_rate", "records"]),
        ("defect_by_type", "label", ["defects", "rate", "inspections"]),
        ("materials_by_type", "label", ["records", "fail_rate", "cost_usd", "moisture_mean", "purity_mean"]),
    ]:
        g = {r[key_field]: r for r in got[list_name]}
        w = {r[key_field]: r for r in want[list_name]}
        assert set(g) == set(w), list_name
        for k in w:
            for f in value_fields:
                assert _close(g[k][f], w[k][f], tol=1e-5), (list_name, k, f)


def test_comparison_matches_pipeline_for_all_plants(payload, browser_results):
    got = browser_results["L30|ALL|ALL"]["cmp"]
    want = payload["slices"]["L30"]["comparison"]
    for f in ("plan_attainment", "scrap_rate", "unplanned_minutes", "runs", "produced_units"):
        assert _close(got["change"][f], want["change"][f], tol=1e-5), f
    assert got["current"]["runs"] == want["current"]["runs"]
    assert got["previous"]["runs"] == want["previous"]["runs"]


def test_first_window_has_no_comparison(browser_results):
    assert browser_results["ALL|ALL|ALL"]["cmp"] is None


def test_material_filter_matches_an_independent_count(payload, tmp_path):
    """Browser-side material filter, checked against a count done here from the exported rows."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    rows = payload["rows"]
    sl = payload["slices"]["L30"]
    material = "ALUMINUM"
    (tmp_path / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "cases.json").write_text(json.dumps([
        {"id": "x", "from": sl["start"], "to": sl["end"], "plant": "ALL", "shift": "ALL", "material": material}]),
        encoding="utf-8")
    (tmp_path / "runner.js").write_text(RUNNER, encoding="utf-8")
    proc = subprocess.run([node, str(tmp_path / "runner.js"), str(AGG_JS), str(tmp_path / "rows.json"),
                           str(tmp_path / "cases.json")], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    head = json.loads(proc.stdout)["x"]["view"]["headline"]

    def table(name):
        return {c: i for i, c in enumerate(rows[name]["columns"])}, rows[name]["data"]

    rc, runs = table("runs")
    mc, mats = table("materials")
    in_window = {r[rc["run"]] for r in runs if sl["start"] <= r[rc["date"]] <= sl["end"]}
    picked = [m for m in mats if m[mc["run"]] in in_window and m[mc["material_type"]] == material]
    assert head["K7"]["records"] == len(picked)
    assert head["K7"]["numerator"] == sum(1 for m in picked if m[mc["fail"]])
    assert head["K8_moisture"]["value"] == pytest.approx(sum(m[mc["moisture"]] for m in picked) / len(picked), rel=1e-6)
