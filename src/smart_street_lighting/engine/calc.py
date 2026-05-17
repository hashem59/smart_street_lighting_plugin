"""
Deterministic AS/NZS 1158 lighting calculation engine.

All numbers in the system come from this module. The downstream LLM
report only narrates these values; it never invents them.

References
----------
* **AS/NZS 1158.3.1:2020** -- *Lighting for roads and public spaces,
  Part 3.1: Pedestrian area (Category P) lighting -- Performance and
  design requirements* (third edition, supersedes 2005). The
  ``SUBCATEGORIES`` table below is sourced verbatim from
  Tables 3.3 -- 3.7 of that standard.
* National Greenhouse Accounts factors (DCCEEW, latest published
  year) for Victorian Scope 2 + 3 emissions intensity.

The 2020 standard replaces the old P1--P12 category labels with five
families of subcategories. The capstone notebook uses the pathway
(PP) family for park paths; the other families are kept here so the
engine can also size designs for roads, public spaces, and car
parks without further work.

================  =================================================
Family            Use
================  =================================================
``PP1``--``PP5``  Pedestrian / cycle pathways (the capstone focus)
``PR1``--``PR6``  Roads in local areas
``PA1``--``PA3``  Public activity areas (excluding car parks)
``PC1``--``PC3``  Outdoor off-road car parks
``PE1``           Subways / connecting elements
================  =================================================

The defaults below are tuned for Melbourne, Victoria. Override the
module-level constants from a calling notebook for a different
tariff / emissions factor / dusk-to-dawn hours.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ================================================================
# AS/NZS 1158.3.1:2020 subcategory lookup
# ================================================================
#
# Values are taken verbatim from the standard (Section 3 tables).
# Note: ``uniformity`` here is the UE2 metric -- the maximum ratio of
# the maximum to the average horizontal illuminance allowed for the
# subcategory. *Lower is better*. This is the opposite of the
# pre-2020 standard's E_min / E_avg uniformity ratio.

SUBCATEGORIES: dict[str, dict] = {
    # --- Pathways (PP) -- Table 3.4 -----------------------------
    "PP1": {"name": "Pathway: high pedestrian/cycle activity",     "avg_lux": 10.00, "min_lux": 2.00, "uniformity": 5,  "table": "3.4"},
    "PP2": {"name": "Pathway: medium-high activity",               "avg_lux":  7.00, "min_lux": 1.00, "uniformity": 5,  "table": "3.4"},
    "PP3": {"name": "Pathway: medium activity",                    "avg_lux":  3.00, "min_lux": 0.50, "uniformity": 5,  "table": "3.4"},
    "PP4": {"name": "Pathway: low activity",                       "avg_lux":  1.50, "min_lux": 0.25, "uniformity": 5,  "table": "3.4"},
    "PP5": {"name": "Pathway: minimal activity",                   "avg_lux":  0.85, "min_lux": 0.14, "uniformity": 5,  "table": "3.4"},
    # --- Local roads (PR) -- Table 3.3 --------------------------
    "PR1": {"name": "Local road: high activity",                   "avg_lux":  7.00, "min_lux": 2.00, "uniformity": 8,  "table": "3.3"},
    "PR2": {"name": "Local road: medium-high activity",            "avg_lux":  3.50, "min_lux": 0.70, "uniformity": 8,  "table": "3.3"},
    "PR3": {"name": "Local road: medium activity",                 "avg_lux":  1.75, "min_lux": 0.30, "uniformity": 8,  "table": "3.3"},
    "PR4": {"name": "Local road: medium-low activity",             "avg_lux":  1.30, "min_lux": 0.22, "uniformity": 8,  "table": "3.3"},
    "PR5": {"name": "Local road: low activity",                    "avg_lux":  0.85, "min_lux": 0.14, "uniformity": 10, "table": "3.3"},
    "PR6": {"name": "Local road: minimal (legacy retrofit)",       "avg_lux":  0.70, "min_lux": 0.07, "uniformity": 10, "table": "3.3"},
    # --- Public activity (PA) -- Table 3.5 ----------------------
    "PA1": {"name": "Public activity: high",                       "avg_lux": 21.00, "min_lux": 7.00, "uniformity": 8,  "table": "3.5"},
    "PA2": {"name": "Public activity: medium",                     "avg_lux": 14.00, "min_lux": 4.00, "uniformity": 8,  "table": "3.5"},
    "PA3": {"name": "Public activity: low",                        "avg_lux":  7.00, "min_lux": 2.00, "uniformity": 8,  "table": "3.5"},
    # --- Outdoor car parks (PC) -- Table 3.7 --------------------
    "PC1": {"name": "Outdoor car park: high",                      "avg_lux": 14.00, "min_lux": 3.00, "uniformity": 8,  "table": "3.7"},
    "PC2": {"name": "Outdoor car park: medium",                    "avg_lux":  7.00, "min_lux": 1.50, "uniformity": 8,  "table": "3.7"},
    "PC3": {"name": "Outdoor car park: low",                       "avg_lux":  3.50, "min_lux": 0.70, "uniformity": 8,  "table": "3.7"},
    # --- Connecting elements (PE) -- Table 3.6 ------------------
    "PE1": {"name": "Subway / underpass",                          "avg_lux": 35.00, "min_lux": 17.50, "uniformity": 8, "table": "3.6"},
}

# Per-family bounds for safety_adjustment arithmetic (subcategory numbers).
_FAMILY_BOUNDS: dict[str, tuple[int, int]] = {
    "PP": (1, 5),
    "PR": (1, 6),
    "PA": (1, 3),
    "PC": (1, 3),
    "PE": (1, 1),
}


def _split_subcategory(subcat: str) -> tuple[str, int]:
    """Split ``"PP3"`` -> ``("PP", 3)``."""
    prefix = ""
    for ch in subcat:
        if ch.isdigit():
            break
        prefix += ch
    return prefix, int(subcat[len(prefix):])


def _apply_safety_adjustment(subcat: str, delta: int) -> str:
    """
    Shift a subcategory up or down inside its family.

    ``delta < 0`` moves to a *brighter* subcategory (lower number).
    Clamped to the family's valid range, so a -3 on ``PA3`` lands on
    ``PA1`` and stays there.
    """
    if delta == 0:
        return subcat
    prefix, num = _split_subcategory(subcat)
    lo, hi = _FAMILY_BOUNDS.get(prefix, (1, 1))
    return f"{prefix}{max(lo, min(hi, num + delta))}"


# ================================================================
# LED bands (typical luminaires)
# ================================================================

LED_SPECS: dict[str, dict] = {
    "low":       {"wattage":  30, "lumens":  4500, "description":  "30W LED (park path bollard / low-mount)"},
    "medium":    {"wattage":  60, "lumens":  9000, "description":  "60W LED (pedestrian area standard)"},
    "high":      {"wattage": 100, "lumens": 15000, "description": "100W LED (major pathway / road)"},
    "very_high": {"wattage": 150, "lumens": 22500, "description": "150W LED (intersection / high-activity)"},
}


# ================================================================
# Melbourne defaults (override from the notebook for other cities)
# ================================================================

OPERATING_HOURS_PER_YEAR: int = 4200       # dusk-to-dawn average
ELECTRICITY_RATE_PER_KWH: float = 0.20     # AUD, mid-range Victorian rate
CARBON_FACTOR_VIC_SCOPE2_3: float = 1.08   # kg CO2-e / kWh (NGA, VIC, Scope 2 + 3)
RECOMMENDED_CCT: int = 3000                # Kelvin, warm white
LED_MAINTENANCE_FACTOR: float = 0.87
LED_LIFESPAN_YEARS: int = 20
LED_CRI: int = 70


# ================================================================
# Per-subcategory engineering tables
# ================================================================

# Spacing multiplier (s = multiplier * pole_height); AS/NZS 1158
# guidance is 3-5x mounting height. Higher categories need closer
# spacing for the tighter uniformity target.
_SPACING_MULTIPLIER: dict[str, float] = {
    "PP1": 3.0, "PP2": 3.5, "PP3": 4.0, "PP4": 4.5, "PP5": 5.0,
    "PR1": 3.5, "PR2": 4.0, "PR3": 4.5, "PR4": 4.5, "PR5": 5.0, "PR6": 5.0,
    "PA1": 3.0, "PA2": 3.5, "PA3": 4.0,
    "PC1": 3.5, "PC2": 4.0, "PC3": 4.5,
    "PE1": 3.0,
}

# LED band selection from subcategory.
_LED_BAND: dict[str, str] = {
    "PP1": "high",      "PP2": "high",     "PP3": "medium",   "PP4": "low",   "PP5": "low",
    "PR1": "high",      "PR2": "medium",   "PR3": "medium",   "PR4": "low",   "PR5": "low",   "PR6": "low",
    "PA1": "very_high", "PA2": "high",     "PA3": "medium",
    "PC1": "high",      "PC2": "medium",   "PC3": "low",
    "PE1": "very_high",
}

# Like-for-like HPS baseline wattage by LED band (for retrofit
# comparison). Industry-typical replacements.
_HPS_EQUIVALENT_W: dict[str, int] = {"low": 70, "medium": 175, "high": 250, "very_high": 400}

# Installed cost per fixture (new install, includes pole + wiring),
# in AUD. Coarse industry averages.
_INSTALLED_COST_AUD: dict[str, float] = {"low": 3000, "medium": 4500, "high": 6000, "very_high": 8000}

# Retrofit cost per fixture (luminaire swap on an existing pole), AUD.
_RETROFIT_COST_AUD: dict[str, float] = {"low": 1000, "medium": 1500, "high": 2000, "very_high": 2800}


# ================================================================
# Design dataclass
# ================================================================

@dataclass
class LightingDesign:
    """Complete lighting design output from the calculation engine."""

    # Inputs
    location_name: str
    pathway_length_m: float
    pathway_width_m: float = 3.0
    activity_level: str = "moderate"

    # Subcategory selection
    subcategory: str = ""
    subcategory_name: str = ""
    required_avg_lux: float = 0.0
    required_min_lux: float = 0.0
    required_uniformity: float = 0.0   # UE2 (max/avg ratio per 2020 standard)

    # Design specs
    pole_height_m: float = 0.0
    spacing_m: float = 0.0
    num_lights: int = 0
    led_spec: str = ""
    led_wattage: int = 0
    led_lumens: int = 0
    colour_temperature_k: int = RECOMMENDED_CCT

    # Energy / cost / emissions
    total_system_wattage: float = 0.0
    annual_energy_kwh: float = 0.0
    annual_energy_cost_aud: float = 0.0
    annual_co2_kg: float = 0.0
    capital_cost_per_light_aud: float = 0.0
    total_capital_cost_aud: float = 0.0
    annual_maintenance_cost_aud: float = 0.0

    # HPS baseline comparison
    hps_equivalent_wattage: int = 0
    hps_annual_energy_kwh: float = 0.0
    hps_annual_cost_aud: float = 0.0
    energy_saving_percent: float = 0.0
    co2_saving_kg: float = 0.0
    payback_years: float = 0.0

    # Enriched outputs
    light_positions: list = field(default_factory=list)
    budget_analysis: dict = field(default_factory=dict)
    safety_adjustment_applied: int = 0
    pathway_geometry: dict = field(default_factory=dict)

    def summary_dict(self) -> dict:
        """Return the headline outputs as a dict (LLM grounding context)."""
        d = {
            "location": self.location_name,
            "pathway_length_m": self.pathway_length_m,
            "subcategory": self.subcategory,
            "subcategory_name": self.subcategory_name,
            "required_avg_lux": self.required_avg_lux,
            "num_lights": self.num_lights,
            "spacing_m": self.spacing_m,
            "pole_height_m": self.pole_height_m,
            "led_wattage": self.led_wattage,
            "colour_temperature": f"{self.colour_temperature_k}K",
            "annual_energy_cost_aud": round(self.annual_energy_cost_aud, 2),
            "annual_energy_kwh": round(self.annual_energy_kwh, 1),
            "annual_co2_kg": round(self.annual_co2_kg, 1),
            "total_capital_cost_aud": round(self.total_capital_cost_aud, 2),
            "energy_saving_vs_hps_percent": round(self.energy_saving_percent, 1),
            "co2_saving_vs_hps_kg": round(self.co2_saving_kg, 1),
            "payback_years": round(self.payback_years, 1),
        }
        if self.light_positions:
            d["light_positions"] = self.light_positions
        if self.budget_analysis:
            d["budget_analysis"] = self.budget_analysis
        if self.safety_adjustment_applied:
            d["safety_adjustment_applied"] = self.safety_adjustment_applied
        return d


# ================================================================
# Subcategory + engineering selection
# ================================================================

def select_subcategory(location_type: str, activity_level: str) -> str:
    """
    Map a (location_type, activity_level) pair to a 2020-standard subcategory.

    Args:
        location_type: ``"park_path"``, ``"shared_path"``,
            ``"public_space"``, ``"residential"``, or ``"car_park"``.
        activity_level: ``"low"`` | ``"moderate"`` | ``"high"`` |
            ``"very_high"``.

    Returns:
        An AS/NZS 1158.3.1:2020 subcategory string (e.g. ``"PP3"``).
    """
    if location_type in {"park_path", "shared_path"}:
        # Pathway family.
        return {
            "very_high": "PP1",
            "high":      "PP2",
            "moderate":  "PP3",
            "low":       "PP4",
        }.get(activity_level, "PP4")

    if location_type == "public_space":
        return {
            "very_high": "PA1",
            "high":      "PA1",
            "moderate":  "PA2",
            "low":       "PA3",
        }.get(activity_level, "PA3")

    if location_type == "residential":
        return {
            "very_high": "PR1",
            "high":      "PR2",
            "moderate":  "PR3",
            "low":       "PR5",
        }.get(activity_level, "PR5")

    if location_type == "car_park":
        return {
            "very_high": "PC1",
            "high":      "PC1",
            "moderate":  "PC2",
            "low":       "PC3",
        }.get(activity_level, "PC3")

    # Sensible default for unknown types.
    return "PP4"


def select_led_spec(subcategory: str) -> str:
    """Pick an LED band band based on the subcategory."""
    return _LED_BAND.get(subcategory, "low")


def calculate_spacing(pole_height: float, subcategory: str) -> float:
    """``spacing = pole_height * subcategory_multiplier`` (AS/NZS 1158 guidance, 3-5x)."""
    mult = _SPACING_MULTIPLIER.get(subcategory, 4.0)
    return round(pole_height * mult, 1)


def select_pole_height(subcategory: str, pathway_width: float) -> float:
    """Pole height from subcategory + pathway width."""
    if subcategory in {"PP1", "PA1", "PE1"}:
        return 6.0 if pathway_width >= 3.0 else 5.0
    if subcategory in {"PP2", "PA2", "PR1", "PR2", "PC1"}:
        return 5.0 if pathway_width >= 3.0 else 4.5
    if subcategory in {"PP3", "PA3", "PR3", "PC2"}:
        return 4.5 if pathway_width >= 3.0 else 4.0
    return 4.0 if pathway_width >= 2.0 else 3.5


# ================================================================
# Main design calculation
# ================================================================

def design_lighting(
    location_name: str,
    pathway_length_m: float,
    pathway_width_m: float = 3.0,
    activity_level: str = "moderate",
    location_type: str = "park_path",
    avg_pedestrian_count: Optional[float] = None,
    safety_adjustment: int = 0,
    pathway_geometry: Optional[dict] = None,
    intersections: Optional[list] = None,
    entry_points: Optional[list] = None,
    budget_cap: Optional[float] = None,
) -> LightingDesign:
    """
    Run the full lighting design for a pathway.

    Steps:

    1. Map sensor count to activity band if ``avg_pedestrian_count`` provided.
    2. Pick a subcategory (with optional safety adjustment).
    3. Pole height + spacing + light count (fence-post layout).
    4. LED band + wattage / lumens.
    5. Annual energy, cost, CO2-e emissions.
    6. Capital + maintenance costs.
    7. Like-for-like HPS baseline comparison.
    8. Simple retrofit payback.
    9. Optional: geometry-aware light placement on the actual polyline.
    10. Optional: budget cap analysis with a reduced-spec alternative.
    """
    # 1. Sensor count -> activity band.
    if avg_pedestrian_count is not None:
        if avg_pedestrian_count < 50:
            activity_level = "low"
        elif avg_pedestrian_count < 300:
            activity_level = "moderate"
        elif avg_pedestrian_count < 1000:
            activity_level = "high"
        else:
            activity_level = "very_high"

    design = LightingDesign(
        location_name=location_name,
        pathway_length_m=pathway_length_m,
        pathway_width_m=pathway_width_m,
        activity_level=activity_level,
    )

    # 2. Subcategory.
    design.subcategory = select_subcategory(location_type, activity_level)
    if safety_adjustment != 0:
        design.subcategory = _apply_safety_adjustment(design.subcategory, safety_adjustment)
    cat = SUBCATEGORIES[design.subcategory]
    design.subcategory_name = cat["name"]
    design.required_avg_lux = cat["avg_lux"]
    design.required_min_lux = cat["min_lux"]
    design.required_uniformity = cat["uniformity"]

    # 3. Pole height + spacing.
    design.pole_height_m = select_pole_height(design.subcategory, pathway_width_m)
    design.spacing_m = calculate_spacing(design.pole_height_m, design.subcategory)

    # Number of lights (fence-post).
    design.num_lights = max(2, math.floor(pathway_length_m / design.spacing_m) + 1)

    # 4. LED selection.
    design.led_spec = select_led_spec(design.subcategory)
    spec = LED_SPECS[design.led_spec]
    design.led_wattage = spec["wattage"]
    design.led_lumens = spec["lumens"]

    # 5. Energy / cost / CO2 (LED).
    design.total_system_wattage = design.num_lights * design.led_wattage
    design.annual_energy_kwh = design.total_system_wattage * OPERATING_HOURS_PER_YEAR / 1000.0
    design.annual_energy_cost_aud = design.annual_energy_kwh * ELECTRICITY_RATE_PER_KWH
    design.annual_co2_kg = design.annual_energy_kwh * CARBON_FACTOR_VIC_SCOPE2_3

    # 6. Capital + maintenance.
    design.capital_cost_per_light_aud = _INSTALLED_COST_AUD[design.led_spec]
    design.total_capital_cost_aud = design.num_lights * design.capital_cost_per_light_aud
    design.annual_maintenance_cost_aud = design.num_lights * 15  # ~$15/light/yr for LED

    # 7. HPS baseline.
    design.hps_equivalent_wattage = _HPS_EQUIVALENT_W[design.led_spec]
    hps_total_w = design.num_lights * design.hps_equivalent_wattage
    design.hps_annual_energy_kwh = hps_total_w * OPERATING_HOURS_PER_YEAR / 1000.0
    design.hps_annual_cost_aud = design.hps_annual_energy_kwh * ELECTRICITY_RATE_PER_KWH
    if design.hps_annual_energy_kwh > 0:
        design.energy_saving_percent = (
            (design.hps_annual_energy_kwh - design.annual_energy_kwh)
            / design.hps_annual_energy_kwh * 100
        )
    design.co2_saving_kg = (
        (design.hps_annual_energy_kwh - design.annual_energy_kwh) * CARBON_FACTOR_VIC_SCOPE2_3
    )

    # 8. Retrofit payback (luminaire swap, poles reused).
    retrofit_total = design.num_lights * _RETROFIT_COST_AUD[design.led_spec]
    annual_saving = (
        (design.hps_annual_cost_aud - design.annual_energy_cost_aud)
        + design.num_lights * 60  # +$60/light/yr avoided HPS maintenance
    )
    if annual_saving > 0:
        design.payback_years = retrofit_total / annual_saving

    design.safety_adjustment_applied = safety_adjustment

    # 9. Geometry-aware placement (optional).
    if pathway_geometry and pathway_geometry.get("coordinates"):
        try:
            from smart_street_lighting.osm.geometry import place_lights_on_polyline
            coords_lonlat = pathway_geometry["coordinates"]
            coords = [(c[1], c[0]) for c in coords_lonlat]
            design.light_positions = place_lights_on_polyline(
                coords,
                design.spacing_m,
                intersections=intersections,
                entry_points=entry_points,
            )
            design.pathway_geometry = pathway_geometry
            if design.light_positions:
                design.num_lights = len(design.light_positions)
                design.total_system_wattage = design.num_lights * design.led_wattage
                design.annual_energy_kwh = (
                    design.total_system_wattage * OPERATING_HOURS_PER_YEAR / 1000.0
                )
                design.annual_energy_cost_aud = design.annual_energy_kwh * ELECTRICITY_RATE_PER_KWH
                design.annual_co2_kg = design.annual_energy_kwh * CARBON_FACTOR_VIC_SCOPE2_3
                design.total_capital_cost_aud = (
                    design.num_lights * design.capital_cost_per_light_aud
                )
                design.annual_maintenance_cost_aud = design.num_lights * 15
                hps_total_w = design.num_lights * design.hps_equivalent_wattage
                design.hps_annual_energy_kwh = hps_total_w * OPERATING_HOURS_PER_YEAR / 1000.0
                design.hps_annual_cost_aud = (
                    design.hps_annual_energy_kwh * ELECTRICITY_RATE_PER_KWH
                )
                if design.hps_annual_energy_kwh > 0:
                    design.energy_saving_percent = (
                        (design.hps_annual_energy_kwh - design.annual_energy_kwh)
                        / design.hps_annual_energy_kwh * 100
                    )
                design.co2_saving_kg = (
                    (design.hps_annual_energy_kwh - design.annual_energy_kwh)
                    * CARBON_FACTOR_VIC_SCOPE2_3
                )
                retrofit_total = design.num_lights * _RETROFIT_COST_AUD[design.led_spec]
                annual_saving = (
                    (design.hps_annual_cost_aud - design.annual_energy_cost_aud)
                    + design.num_lights * 60
                )
                if annual_saving > 0:
                    design.payback_years = retrofit_total / annual_saving
        except Exception as e:
            print(f"Geometry placement failed, using linear calculation: {e}")

    # 10. Budget cap analysis.
    if budget_cap is not None:
        total_annual = (
            design.annual_energy_cost_aud + design.annual_maintenance_cost_aud
        )
        within_budget = total_annual <= budget_cap
        budget_alt = None
        compliance_notes: list[str] = []
        if not within_budget:
            alt_spacing = design.spacing_m * 1.3
            alt_num_lights = max(2, math.floor(pathway_length_m / alt_spacing) + 1)
            spec_order = ["very_high", "high", "medium", "low"]
            current_idx = (
                spec_order.index(design.led_spec) if design.led_spec in spec_order else -1
            )
            alt_spec_key = (
                spec_order[min(current_idx + 1, len(spec_order) - 1)]
                if current_idx >= 0
                else design.led_spec
            )
            alt_spec = LED_SPECS[alt_spec_key]
            alt_energy = alt_num_lights * alt_spec["wattage"] * OPERATING_HOURS_PER_YEAR / 1000.0
            alt_cost = alt_energy * ELECTRICITY_RATE_PER_KWH
            alt_maint = alt_num_lights * 15
            alt_total = alt_cost + alt_maint
            budget_alt = {
                "num_lights": alt_num_lights,
                "spacing_m": round(alt_spacing, 1),
                "led_wattage": alt_spec["wattage"],
                "annual_energy_cost_aud": round(alt_cost, 2),
                "annual_total_cost_aud": round(alt_total, 2),
            }
            compliance_notes.append(
                f"Budget alternative uses {alt_spacing:.1f}m spacing (1.3x standard), "
                "which may reduce uniformity below AS/NZS 1158 requirements."
            )
        design.budget_analysis = {
            "budget_cap": budget_cap,
            "within_budget": within_budget,
            "full_design_annual_cost": round(total_annual, 2),
            "budget_alternative": budget_alt,
            "compliance_notes": compliance_notes,
        }

    return design


# ================================================================
# Photometric verification (lumen method)
# ================================================================

def verify_design(
    design: LightingDesign,
    coefficient_of_utilisation: float = 0.45,
    maintenance_factor: float = LED_MAINTENANCE_FACTOR,
) -> dict:
    """
    Verify a design against AS/NZS 1158 illuminance with the lumen
    method:

    .. math::

        E_{\\text{avg}} = \\frac{N \\cdot F \\cdot \\text{CU} \\cdot \\text{MF}}{A}

    Returns a dict with the predicted illuminance, the target from the
    subcategory table, and a pass/fail verdict. Uniformity is reported
    using the 2020 UE2 definition (``max/avg``), which the lumen
    method cannot solve directly -- a strict point-by-point grid
    solver is out of scope.
    """
    if design.pathway_length_m <= 0 or design.pathway_width_m <= 0:
        raise ValueError("Pathway dimensions must be positive.")

    area_m2 = design.pathway_length_m * design.pathway_width_m
    total_flux = design.num_lights * design.led_lumens
    e_avg_predicted = (
        total_flux * coefficient_of_utilisation * maintenance_factor / area_m2
    )
    # Approximation: if uniformity (max/avg) is U, then min/avg ~ 1/U^2 worst-case.
    # Use 1/U as a conservative E_min estimate for the lumen method check.
    e_min_predicted = e_avg_predicted / max(1.0, design.required_uniformity)
    pass_avg = e_avg_predicted >= design.required_avg_lux
    pass_min = e_min_predicted >= design.required_min_lux
    return {
        "subcategory": design.subcategory,
        "coefficient_of_utilisation": coefficient_of_utilisation,
        "maintenance_factor": maintenance_factor,
        "task_area_m2": round(area_m2, 1),
        "total_luminaire_flux_lm": total_flux,
        "predicted_avg_lux": round(e_avg_predicted, 2),
        "predicted_min_lux": round(e_min_predicted, 2),
        "required_avg_lux": design.required_avg_lux,
        "required_min_lux": design.required_min_lux,
        "required_uniformity_UE2_max_avg": design.required_uniformity,
        "pass_avg": pass_avg,
        "pass_min": pass_min,
        "pass": pass_avg and pass_min,
        "headroom_avg_lux": round(e_avg_predicted - design.required_avg_lux, 2),
    }


# ================================================================
# Off-grid solar PV sizing
# ================================================================

def size_solar_alternative(
    design: LightingDesign,
    nightly_run_hours: float = 11.5,
    autonomy_days: float = 2.0,
    panel_derating: float = 0.80,
    peak_sun_hours: float = 3.6,
    battery_depth_of_discharge: float = 0.80,
    system_voltage_v: float = 24.0,
    panel_cost_per_wp_aud: float = 1.20,
    battery_cost_per_kwh_aud: float = 400.0,
    extra_per_light_aud: float = 800.0,
) -> dict:
    """
    Size an off-grid solar PV alternative for the same luminaire set.

    Per-light daily energy:

    .. math::

        E_{\\text{day}} = W \\cdot h_{\\text{night}}

    Panel size (Wp):

    .. math::

        P_{\\text{panel}} = \\frac{E_{\\text{day}}}{h_{\\text{sun}} \\cdot \\eta_{\\text{derate}}}

    Battery capacity (Wh):

    .. math::

        E_{\\text{batt}} = \\frac{E_{\\text{day}} \\cdot d_{\\text{auto}}}{\\text{DoD}}
    """
    if design.num_lights <= 0:
        raise ValueError("Design must have at least one luminaire to size solar.")
    per_light_daily_wh = design.led_wattage * nightly_run_hours
    panel_wp_per_light = per_light_daily_wh / (peak_sun_hours * panel_derating)
    battery_wh_per_light = (per_light_daily_wh * autonomy_days) / battery_depth_of_discharge
    battery_ah_per_light = battery_wh_per_light / system_voltage_v
    panel_cost_per_light = panel_wp_per_light * panel_cost_per_wp_aud
    battery_cost_per_light = (battery_wh_per_light / 1000.0) * battery_cost_per_kwh_aud
    capex_per_light = panel_cost_per_light + battery_cost_per_light + extra_per_light_aud
    return {
        "assumptions": {
            "nightly_run_hours": nightly_run_hours,
            "autonomy_days": autonomy_days,
            "panel_derating": panel_derating,
            "peak_sun_hours": peak_sun_hours,
            "battery_depth_of_discharge": battery_depth_of_discharge,
            "system_voltage_v": system_voltage_v,
        },
        "per_light": {
            "daily_energy_wh": round(per_light_daily_wh, 1),
            "panel_wp": round(panel_wp_per_light, 1),
            "battery_wh": round(battery_wh_per_light, 1),
            "battery_ah_at_system_v": round(battery_ah_per_light, 1),
            "panel_cost_aud": round(panel_cost_per_light, 2),
            "battery_cost_aud": round(battery_cost_per_light, 2),
            "capex_aud": round(capex_per_light, 2),
        },
        "system_total": {
            "num_lights": design.num_lights,
            "total_panel_kwp": round(panel_wp_per_light * design.num_lights / 1000.0, 2),
            "total_battery_kwh": round(battery_wh_per_light * design.num_lights / 1000.0, 2),
            "total_capex_aud": round(capex_per_light * design.num_lights, 2),
        },
        "annual_grid_kwh_avoided": round(design.annual_energy_kwh, 1),
        "annual_co2_avoided_kg": round(design.annual_co2_kg, 1),
    }


# ================================================================
# Pretty-printer
# ================================================================

def format_design_report(design: LightingDesign) -> str:
    """Format a human-readable design report from a LightingDesign."""
    return f"""
LIGHTING DESIGN CALCULATION REPORT
{'=' * 50}
Location: {design.location_name}
Pathway: {design.pathway_length_m}m long x {design.pathway_width_m}m wide
Activity Level: {design.activity_level}

AS/NZS 1158.3.1:2020 SUBCATEGORY
  Subcategory: {design.subcategory} - {design.subcategory_name}
  Required average illuminance:  {design.required_avg_lux} lux
  Required minimum illuminance:  {design.required_min_lux} lux
  Required uniformity (UE2, max/avg): {design.required_uniformity}

DESIGN SPECIFICATIONS
  Number of lights: {design.num_lights}
  Spacing: {design.spacing_m}m
  Pole height: {design.pole_height_m}m
  Technology: {design.led_wattage}W LED ({design.led_lumens} lumens)
  Colour temperature: {design.colour_temperature_k}K (warm white)
  CRI: {LED_CRI}

ENERGY & COST ESTIMATES (LED)
  Total system wattage: {design.total_system_wattage}W
  Annual energy: {design.annual_energy_kwh:.0f} kWh
  Annual energy cost: ${design.annual_energy_cost_aud:.2f}
  Annual CO2 emissions: {design.annual_co2_kg:.1f} kg CO2-e
  Capital cost (new install): ${design.total_capital_cost_aud:,.0f} ({design.num_lights} x ${design.capital_cost_per_light_aud}, includes pole + wiring)

COMPARISON vs HPS BASELINE
  HPS equivalent: {design.hps_equivalent_wattage}W per light
  HPS annual energy cost: ${design.hps_annual_cost_aud:.2f}
  Energy saving: {design.energy_saving_percent:.1f}%
  CO2 saving: {design.co2_saving_kg:.1f} kg CO2-e/year
  Retrofit payback period: {design.payback_years:.1f} years (luminaire swap only)
""".strip()
