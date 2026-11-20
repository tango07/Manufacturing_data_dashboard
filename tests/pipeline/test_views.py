"""Checks on the chart data written to kpis.json (views)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = ROOT / "data" / "processed" / "kpis.json"


@pytest.fixture(scope="module")
def payload():
    if not PAYLOAD.exists():
        pytest.skip("run the pipeline first")
    return json.loads(PAYLOAD.read_text(encoding="utf-8"))


def test_every_plant_shift_combination_has_views(payload):
    expected = {f"{p}|{s}" for p in ["ALL"] + payload["filters"]["plants"] for s in ["ALL"] + payload["filters"]["shifts"]}
    assert set(payload["views"]) == expected


def test_product_counts_add_up_to_clean_runs(payload):
    v = payload["views"]["ALL|ALL"]
    assert sum(r["runs"] for r in v["runs_by_product"]) == payload["row_counts"]["production_runs"]["clean"]


def test_downtime_shares_sum_to_one(payload):
    shares = [r["share"] for r in payload["views"]["ALL|ALL"]["downtime_by_category"]]
    assert sum(shares) == pytest.approx(1.0, abs=1e-4)


def test_downtime_minutes_match_headline_metric(payload):
    minutes = sum(r["minutes"] for r in payload["views"]["ALL|ALL"]["downtime_by_category"])
    assert minutes == pytest.approx(payload["blocks"]["ALL|ALL"]["K3b"]["numerator"], abs=1e-3)


def test_comparison_change_is_current_minus_previous(payload):
    for pid in ("L30", "L7", "M2026-08"):
        p = payload["slices"][pid]["comparison"]
        assert p["change"]["unplanned_minutes"] == pytest.approx(
            p["current"]["unplanned_minutes"] - p["previous"]["unplanned_minutes"], abs=1e-3)
        assert p["change"]["scrap_rate"] == pytest.approx(p["current"]["scrap_rate"] - p["previous"]["scrap_rate"], abs=1e-5)


def test_every_period_has_slices_for_every_plant_and_shift(payload):
    assert payload["slice_order"][0] == "L30"
    assert sorted(payload["slice_order"]) == sorted(payload["slices"].keys())
    for pid, sl in payload["slices"].items():
        keys = {f"{p}|{s}" for p in ["ALL"] + payload["filters"]["plants"] for s in ["ALL"] + payload["filters"]["shifts"]}
        assert set(sl["blocks"]) == keys == set(sl["views"]), pid


def test_period_runs_add_up_to_the_whole_dataset(payload):
    months = [pid for pid in payload["slices"] if pid.startswith("M")]
    total = sum(payload["slices"][m]["blocks"]["ALL|ALL"]["K1"]["records"] for m in months)
    assert total == payload["slices"]["ALL"]["blocks"]["ALL|ALL"]["K1"]["records"]


def test_first_period_has_no_earlier_window_to_compare(payload):
    assert payload["slices"]["ALL"]["comparison"] is None
    assert payload["slices"]["M2026-07"]["comparison"] is None


def test_daily_series_covers_every_day_and_rates_are_bounded(payload):
    daily = payload["views"]["ALL|ALL"]["daily"]
    assert len(daily) == len({r["date"] for r in daily})
    for r in daily:
        for k in ("plan_attainment", "scrap_rate"):
            assert r[k] is None or 0 <= r[k] <= 2


def test_machine_loss_totals_match_plant_loss_totals(payload):
    v = payload["views"]["ALL|ALL"]
    machines = sum(r["total_usd"] for r in v["loss_by_machine"])
    plants = sum(r["total_usd"] for r in v["loss_by_plant"])
    assert machines == pytest.approx(plants, rel=1e-6)
