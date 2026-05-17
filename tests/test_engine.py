"""Smoke tests for the calculation engine."""

import math

from smart_street_lighting import (
    SUBCATEGORIES,
    design_lighting,
    select_subcategory,
    verify_design,
    size_solar_alternative,
)


def test_subcategories_complete():
    expected = {f"PP{i}" for i in range(1, 6)} | {f"PR{i}" for i in range(1, 7)} \
        | {f"PA{i}" for i in range(1, 4)} | {f"PC{i}" for i in range(1, 4)} | {"PE1"}
    assert set(SUBCATEGORIES.keys()) == expected
    for sub in SUBCATEGORIES.values():
        assert sub["avg_lux"] >= sub["min_lux"]
        assert sub["uniformity"] >= 1  # UE2 is max/avg, must be >= 1


def test_select_subcategory_park_path():
    assert select_subcategory("park_path", "low")       == "PP4"
    assert select_subcategory("park_path", "moderate")  == "PP3"
    assert select_subcategory("park_path", "high")      == "PP2"
    assert select_subcategory("park_path", "very_high") == "PP1"


def test_select_subcategory_residential_returns_PR():
    assert select_subcategory("residential", "moderate") == "PR3"


def test_select_subcategory_public_space_returns_PA():
    assert select_subcategory("public_space", "high") == "PA1"


def test_design_lighting_basic_park_path():
    d = design_lighting(
        location_name="Test Path",
        pathway_length_m=200,
        pathway_width_m=3.0,
        activity_level="high",
        location_type="park_path",
    )
    assert d.subcategory == "PP2"
    assert d.num_lights >= 2
    assert d.num_lights == math.floor(200 / d.spacing_m) + 1
    assert d.led_wattage > 0
    assert d.annual_energy_kwh > 0
    assert d.annual_co2_kg > 0
    assert d.energy_saving_percent > 0  # LED beats HPS


def test_safety_adjustment_brightens_within_family():
    base = design_lighting("X", 100, activity_level="moderate", location_type="park_path")
    adj  = design_lighting("X", 100, activity_level="moderate", location_type="park_path",
                           safety_adjustment=-1)
    # PP3 -> PP2 (lower number = brighter)
    assert base.subcategory == "PP3"
    assert adj.subcategory  == "PP2"
    assert adj.required_avg_lux > base.required_avg_lux


def test_safety_adjustment_clamped_to_family_bounds():
    # PP3 with -10 should clamp at PP1, not leak into another family.
    d = design_lighting("X", 100, activity_level="moderate", location_type="park_path",
                        safety_adjustment=-10)
    assert d.subcategory == "PP1"


def test_verify_design_returns_required_keys():
    d = design_lighting("T", 100, 3.0, "high", "park_path")
    v = verify_design(d)
    for k in ("predicted_avg_lux", "predicted_min_lux", "required_avg_lux",
              "required_min_lux", "pass", "pass_avg", "pass_min",
              "required_uniformity_UE2_max_avg"):
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
    d = design_lighting("T", 500, 3.0, "very_high", "shared_path", budget_cap=10.0)
    assert d.budget_analysis["within_budget"] is False
    assert d.budget_analysis["budget_alternative"] is not None


def test_PP3_matches_standard_verbatim():
    """Spot-check that PP3 in our dict matches AS/NZS 1158.3.1:2020 Table 3.4."""
    pp3 = SUBCATEGORIES["PP3"]
    assert pp3["avg_lux"]    == 3.00
    assert pp3["min_lux"]    == 0.50
    assert pp3["uniformity"] == 5
    assert pp3["table"]      == "3.4"
