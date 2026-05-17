"""Smoke tests for the calculation engine."""

import math

from smart_street_lighting import (
    P_CATEGORIES,
    design_lighting,
    select_p_category,
    verify_design,
    size_solar_alternative,
)


def test_p_categories_complete():
    assert set(P_CATEGORIES.keys()) == {f"P{i}" for i in range(1, 13)}
    for cat in P_CATEGORIES.values():
        assert cat["avg_lux"] >= cat["min_lux"]
        assert 0 < cat["uniformity"] <= 1


def test_select_p_category_park_path():
    assert select_p_category("low", "park_path") == "P10"
    assert select_p_category("moderate", "park_path") == "P9"
    assert select_p_category("high", "park_path") == "P3"


def test_design_lighting_basic():
    d = design_lighting(
        location_name="Test Path",
        pathway_length_m=200,
        pathway_width_m=3.0,
        activity_level="high",
        location_type="park_path",
    )
    assert d.p_category == "P3"
    assert d.num_lights >= 2
    # Lights are at fence-post intervals
    assert d.num_lights == math.floor(200 / d.spacing_m) + 1
    assert d.led_wattage > 0
    assert d.annual_energy_kwh > 0
    assert d.annual_co2_kg > 0
    assert d.energy_saving_percent > 0  # LED beats HPS


def test_design_lighting_safety_adjustment_upgrades():
    base = design_lighting("X", 100, activity_level="low", location_type="park_path")
    adj = design_lighting(
        "X", 100, activity_level="low", location_type="park_path", safety_adjustment=-2
    )
    # Lower P number = brighter requirement
    assert int(adj.p_category[1:]) < int(base.p_category[1:])


def test_verify_design_returns_required_keys():
    d = design_lighting("T", 100, 3.0, "high", "park_path")
    v = verify_design(d)
    for k in (
        "predicted_avg_lux",
        "predicted_min_lux",
        "required_avg_lux",
        "required_min_lux",
        "pass",
        "pass_avg",
        "pass_min",
    ):
        assert k in v


def test_size_solar_returns_positive_sizes():
    d = design_lighting("T", 100, 3.0, "moderate", "park_path")
    s = size_solar_alternative(d)
    per = s["per_light"]
    assert per["daily_energy_wh"] > 0
    assert per["panel_wp"] > 0
    assert per["battery_wh"] > 0
    assert s["system_total"]["total_panel_kwp"] > 0


def test_budget_cap_triggers_alternative():
    d = design_lighting(
        "T", 500, 3.0, "very_high", "shared_path", budget_cap=10.0
    )
    assert d.budget_analysis["within_budget"] is False
    assert d.budget_analysis["budget_alternative"] is not None
