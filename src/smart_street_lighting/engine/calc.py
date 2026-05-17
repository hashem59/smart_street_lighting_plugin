"""
Deterministic lighting calculation engine.

All numbers in the system come from this module. The downstream LLM
report only narrates these values; it never invents them.

References
----------
* AS/NZS 1158.3.1:2020 -- Pedestrian area (Category P) lighting.
* National Greenhouse Accounts factors (DCCEEW, latest published year)
  for Victorian Scope 2 + 3 emissions intensity.

The defaults below are tuned for Melbourne, Victoria. Override the
module-level constants from a calling notebook if you need a different
tariff / emissions factor / dusk-to-dawn hours.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# AS/NZS 1158 P-Category Standards Lookup
# ============================================================

P_CATEGORIES: dict[str, dict] = {
    "P1":  {"name": "Major pedestrian activity",       "avg_lux": 14.0, "min_lux": 7.00, "uniformity": 0.50},
    "P2":  {"name": "High-activity pedestrian",        "avg_lux": 10.0, "min_lux": 5.00, "uniformity": 0.50},
    "P3":  {"name": "Moderate pedestrian",             "avg_lux":  7.0, "min_lux": 3.50, "uniformity": 0.50},
    "P4":  {"name": "Moderate-low pedestrian",         "avg_lux":  5.0, "min_lux": 2.50, "uniformity": 0.50},
    "P5":  {"name": "Low pedestrian",                  "avg_lux":  3.5, "min_lux": 1.75, "uniformity": 0.50},
    "P6":  {"name": "Low-activity pedestrian",         "avg_lux":  3.5, "min_lux": 0.75, "uniformity": 0.21},
    "P7":  {"name": "Minor pedestrian",                "avg_lux":  1.5, "min_lux": 0.75, "uniformity": 0.50},
    "P8":  {"name": "Minor pedestrian (low risk)",     "avg_lux":  1.5, "min_lux": 0.38, "uniformity": 0.25},
    "P9":  {"name": "Park paths (moderate use)",       "avg_lux":  2.0, "min_lux": 1.00, "uniformity": 0.50},
    "P10": {"name": "Park paths (low use)",            "avg_lux":  1.0, "min_lux": 0.50, "uniformity": 0.50},
    "P11": {"name": "Outdoor car parks (commercial)",  "avg_lux":  7.0, "min_lux": 1.75, "uniformity": 0.25},
    "P12": {"name": "Outdoor car parks (residential)", "avg_lux":  3.5, "min_lux": 0.88, "uniformity": 0.25},
}


# ============================================================
# LED Technology Specs (typical bands)
# ============================================================

LED_SPECS: dict[str, dict] = {
    "low":       {"wattage":  30, "lumens":  4500, "description":  "30W LED (park path bollard / low-mount)"},
    "medium":    {"wattage":  60, "lumens":  9000, "description":  "60W LED (pedestrian area standard)"},
    "high":      {"wattage": 100, "lumens": 15000, "description": "100W LED (major pathway / road)"},
    "very_high": {"wattage": 150, "lumens": 22500, "description": "150W LED (intersection / high-activity)"},
}


# ============================================================
# Energy / Cost / Emissions constants (Melbourne defaults)
# ============================================================

OPERATING_HOURS_PER_YEAR: int = 4200       # dusk-to-dawn average for Melbourne
ELECTRICITY_RATE_PER_KWH: float = 0.20     # AUD, mid-range Victorian rate
CARBON_FACTOR_VIC_SCOPE2_3: float = 1.08   # kg CO2-e / kWh (Scope 2: 0.96 + Scope 3: 0.12)
RECOMMENDED_CCT: int = 3000                # Kelvin, warm white (Melbourne ecological guideline)
LED_MAINTENANCE_FACTOR: float = 0.87       # typical for LED luminaires
LED_LIFESPAN_YEARS: int = 20
LED_CRI: int = 70


# ============================================================
# Design dataclass
# ============================================================

@dataclass
class LightingDesign:
    """Complete lighting design output from the calculation engine."""

    # Inputs
    location_name: str
    pathway_length_m: float
    pathway_width_m: float = 3.0
    activity_level: str = "moderate"

    # Category selection
    p_category: str = ""
    category_name: str = ""
    required_avg_lux: float = 0.0
    required_min_lux: float = 0.0
    required_uniformity: float = 0.0

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
        """Return the key outputs as a dict (used as LLM grounding context)."""
        d = {
            "location": self.location_name,
            "pathway_length_m": self.pathway_length_m,
            "p_category": self.p_category,
            "category_name": self.category_name,
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


# ============================================================
# Category / luminaire / geometry selection
# ============================================================

def select_p_category(activity_level: str, location_type: str = "park_path") -> str:
    """Select an AS/NZS 1158 P-category from a location type and activity band."""
    if location_type == "park_path":
        mapping = {"low": "P10", "moderate": "P9", "high": "P3", "very_high": "P2"}
    elif location_type == "shared_path":
        mapping = {"low": "P5", "moderate": "P3", "high": "P2", "very_high": "P1"}
    elif location_type == "public_space":
        mapping = {"low": "P5", "moderate": "P3", "high": "P2", "very_high": "P1"}
    elif location_type == "residential":
        mapping = {"low": "P8", "moderate": "P6", "high": "P5", "very_high": "P4"}
    else:
        mapping = {"low": "P10", "moderate": "P9", "high": "P3", "very_high": "P2"}
    return mapping.get(activity_level, "P9")


def select_led_spec(p_category: str) -> str:
    """Pick an LED band based on the P-category."""
    if p_category in {"P1", "P2", "P11"}:
        return "high"
    if p_category in {"P3", "P4", "P5"}:
        return "medium"
    return "low"


def calculate_spacing(pole_height: float, p_category: str) -> float:
    """Spacing = pole_height x category multiplier (AS/NZS 1158 guidance, 3-5x)."""
    multipliers = {
        "P1": 3.0, "P2": 3.5, "P3": 3.5, "P4": 4.0, "P5": 4.0, "P6": 4.5,
        "P7": 5.0, "P8": 5.0, "P9": 4.0, "P10": 5.0, "P11": 4.0, "P12": 4.5,
    }
    return round(pole_height * multipliers.get(p_category, 4.0), 1)


def select_pole_height(p_category: str, pathway_width: float) -> float:
    """Pole height from category + pathway width."""
    if p_category in {"P1", "P2"}:
        return 6.0 if pathway_width >= 3.0 else 5.0
    if p_category in {"P3", "P4", "P5"}:
        return 5.0 if pathway_width >= 3.0 else 4.0
    return 4.0 if pathway_width >= 2.0 else 3.5


# ============================================================
# Main design calculation
# ============================================================

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

    Steps
    -----
    1. Select P-category (with optional safety adjustment).
    2. Select pole height + spacing.
    3. Count lights along the path (fence-post: lights at 0, s, 2s, ..., L).
    4. Select an LED band and pull wattage / lumens.
    5. Compute annual energy, cost, and CO2-e emissions.
    6. Compute capital + maintenance costs.
    7. Compare against a like-for-like HPS baseline.
    8. Compute simple retrofit payback.
    9. Optional: geometry-aware light placement on the actual polyline.
    10. Optional: budget cap analysis with a reduced-spec alternative.
    """
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

    # 1. P-category
    design.p_category = select_p_category(activity_level, location_type)
    if safety_adjustment != 0:
        p_num = int(design.p_category.replace("P", ""))
        adjusted = max(1, min(12, p_num + safety_adjustment))
        design.p_category = f"P{adjusted}"
    cat = P_CATEGORIES[design.p_category]
    design.category_name = cat["name"]
    design.required_avg_lux = cat["avg_lux"]
    design.required_min_lux = cat["min_lux"]
    design.required_uniformity = cat["uniformity"]

    # 2. Pole height + spacing
    design.pole_height_m = select_pole_height(design.p_category, pathway_width_m)
    design.spacing_m = calculate_spacing(design.pole_height_m, design.p_category)

    # 3. Number of lights (fence-post)
    design.num_lights = max(2, math.floor(pathway_length_m / design.spacing_m) + 1)

    # 4. LED selection
    design.led_spec = select_led_spec(design.p_category)
    spec = LED_SPECS[design.led_spec]
    design.led_wattage = spec["wattage"]
    design.led_lumens = spec["lumens"]

    # 5. Energy / cost / CO2 (LED)
    design.total_system_wattage = design.num_lights * design.led_wattage
    design.annual_energy_kwh = design.total_system_wattage * OPERATING_HOURS_PER_YEAR / 1000.0
    design.annual_energy_cost_aud = design.annual_energy_kwh * ELECTRICITY_RATE_PER_KWH
    design.annual_co2_kg = design.annual_energy_kwh * CARBON_FACTOR_VIC_SCOPE2_3

    # 6. Capital + maintenance
    cost_per_light_installed = {"low": 3000, "medium": 4500, "high": 6000, "very_high": 8000}
    design.capital_cost_per_light_aud = cost_per_light_installed[design.led_spec]
    design.total_capital_cost_aud = design.num_lights * design.capital_cost_per_light_aud
    design.annual_maintenance_cost_aud = design.num_lights * 15  # ~$15/light/yr for LED

    # 7. HPS baseline
    hps_wattage_map = {"low": 70, "medium": 175, "high": 250, "very_high": 400}
    design.hps_equivalent_wattage = hps_wattage_map[design.led_spec]
    hps_total_w = design.num_lights * design.hps_equivalent_wattage
    design.hps_annual_energy_kwh = hps_total_w * OPERATING_HOURS_PER_YEAR / 1000.0
    design.hps_annual_cost_aud = design.hps_annual_energy_kwh * ELECTRICITY_RATE_PER_KWH

    if design.hps_annual_energy_kwh > 0:
        design.energy_saving_percent = (
            (design.hps_annual_energy_kwh - design.annual_energy_kwh)
            / design.hps_annual_energy_kwh
            * 100
        )
    design.co2_saving_kg = (
        (design.hps_annual_energy_kwh - design.annual_energy_kwh) * CARBON_FACTOR_VIC_SCOPE2_3
    )

    # 8. Retrofit payback (luminaire swap, poles reused)
    retrofit_cost_per_light = {"low": 1000, "medium": 1500, "high": 2000, "very_high": 2800}
    retrofit_total = design.num_lights * retrofit_cost_per_light[design.led_spec]
    annual_saving = (
        (design.hps_annual_cost_aud - design.annual_energy_cost_aud)
        + design.num_lights * 60  # +$60/light/yr HPS maintenance saving (industry avg)
    )
    if annual_saving > 0:
        design.payback_years = retrofit_total / annual_saving

    design.safety_adjustment_applied = safety_adjustment

    # 9. Geometry-aware placement (optional)
    if pathway_geometry and pathway_geometry.get("coordinates"):
        try:
            from smart_street_lighting.osm.geometry import place_lights_on_polyline

            coords_lonlat = pathway_geometry["coordinates"]
            coords = [(c[1], c[0]) for c in coords_lonlat]  # GeoJSON is [lon, lat]
            design.light_positions = place_lights_on_polyline(
                coords,
                design.spacing_m,
                intersections=intersections,
                entry_points=entry_points,
            )
            design.pathway_geometry = pathway_geometry
            if design.light_positions:
                # Re-cost using the actual placed light count
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
                        / design.hps_annual_energy_kwh
                        * 100
                    )
                design.co2_saving_kg = (
                    (design.hps_annual_energy_kwh - design.annual_energy_kwh)
                    * CARBON_FACTOR_VIC_SCOPE2_3
                )
                retrofit_total = (
                    design.num_lights * retrofit_cost_per_light[design.led_spec]
                )
                annual_saving = (
                    (design.hps_annual_cost_aud - design.annual_energy_cost_aud)
                    + design.num_lights * 60
                )
                if annual_saving > 0:
                    design.payback_years = retrofit_total / annual_saving
        except Exception as e:
            print(f"Geometry placement failed, using linear calculation: {e}")

    # 10. Budget cap analysis
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


# ============================================================
# Photometric verification (lumen method)
# ============================================================

def verify_design(
    design: LightingDesign,
    coefficient_of_utilisation: float = 0.45,
    maintenance_factor: float = LED_MAINTENANCE_FACTOR,
) -> dict:
    """
    Verify a design against AS/NZS 1158 illuminance requirements.

    Uses the standard lumen-method estimate of average maintained
    illuminance::

        E_avg = (N * F * CU * MF) / A

    where:

    * ``N``   -- number of luminaires
    * ``F``   -- lumens per luminaire
    * ``CU``  -- coefficient of utilisation (fraction of luminaire flux
      that reaches the task plane; 0.40-0.55 is typical for outdoor
      post-top luminaires)
    * ``MF``  -- maintenance factor (lumen depreciation, dirt, etc.;
      ~0.87 for sealed LEDs in clean outdoor environments)
    * ``A``   -- task area in m^2 (pathway length x width)

    Returns a dict with the predicted illuminance, the target
    illuminance from the P-category table, and a pass/fail verdict.
    Uniformity is approximated from category-typical layouts because a
    point-by-point grid solve is out of scope for the lumen method.
    """
    if design.pathway_length_m <= 0 or design.pathway_width_m <= 0:
        raise ValueError("Pathway dimensions must be positive.")

    area_m2 = design.pathway_length_m * design.pathway_width_m
    total_flux = design.num_lights * design.led_lumens
    e_avg_predicted = (
        total_flux * coefficient_of_utilisation * maintenance_factor / area_m2
    )

    # Approximate min illuminance from the category's typical uniformity
    e_min_predicted = e_avg_predicted * design.required_uniformity

    pass_avg = e_avg_predicted >= design.required_avg_lux
    pass_min = e_min_predicted >= design.required_min_lux
    overall_pass = pass_avg and pass_min

    return {
        "p_category": design.p_category,
        "coefficient_of_utilisation": coefficient_of_utilisation,
        "maintenance_factor": maintenance_factor,
        "task_area_m2": round(area_m2, 1),
        "total_luminaire_flux_lm": total_flux,
        "predicted_avg_lux": round(e_avg_predicted, 2),
        "predicted_min_lux": round(e_min_predicted, 2),
        "required_avg_lux": design.required_avg_lux,
        "required_min_lux": design.required_min_lux,
        "required_uniformity": design.required_uniformity,
        "pass_avg": pass_avg,
        "pass_min": pass_min,
        "pass": overall_pass,
        "headroom_avg_lux": round(e_avg_predicted - design.required_avg_lux, 2),
    }


# ============================================================
# Off-grid solar PV sizing
# ============================================================

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

    Pole-mounted solar fixtures need a PV panel, battery storage, and a
    charge controller per light. This function returns a per-light and
    a system-level sizing using the standard worked equations below.

    Per-light daily energy::

        E_day_Wh = wattage_W * nightly_run_hours

    Panel size (Wp) needed for that daily load given local sun and
    derating::

        P_panel_Wp = E_day_Wh / (peak_sun_hours * panel_derating)

    Battery capacity (Wh) for ``autonomy_days`` of overcast weather,
    derated for usable depth-of-discharge::

        E_batt_Wh = (E_day_Wh * autonomy_days) / battery_depth_of_discharge
        C_batt_Ah = E_batt_Wh / system_voltage_v

    The defaults match Melbourne winter average peak sun hours
    (~3.4-3.8) and LiFePO4 battery chemistry.
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

    total = {
        "num_lights": design.num_lights,
        "total_panel_kwp": round(panel_wp_per_light * design.num_lights / 1000.0, 2),
        "total_battery_kwh": round(battery_wh_per_light * design.num_lights / 1000.0, 2),
        "total_capex_aud": round(capex_per_light * design.num_lights, 2),
    }

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
        "system_total": total,
        "annual_grid_kwh_avoided": round(design.annual_energy_kwh, 1),
        "annual_co2_avoided_kg": round(design.annual_co2_kg, 1),
    }


# ============================================================
# Pretty-printer (used by the notebook for inline narrative)
# ============================================================

def format_design_report(design: LightingDesign) -> str:
    """Format a human-readable design report from a LightingDesign."""
    return f"""
LIGHTING DESIGN CALCULATION REPORT
{'=' * 50}
Location: {design.location_name}
Pathway: {design.pathway_length_m}m long x {design.pathway_width_m}m wide
Activity Level: {design.activity_level}

CATEGORY SELECTION
  AS/NZS 1158 Category: {design.p_category} - {design.category_name}
  Required average illuminance: {design.required_avg_lux} lux
  Required minimum illuminance: {design.required_min_lux} lux
  Required uniformity (Emin/Eavg): {design.required_uniformity}

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
