"""
Deterministic AS/NZS 1158.3.1:2020 lighting calculation engine.

This module is the project's intellectual property. The LLM
(notebook side) explains and justifies; the numbers come from here.

Public surface
--------------
* :data:`SUBCATEGORIES`           -- AS/NZS 1158.3.1:2020 lookup
  (PP1-PP5 pathways, PR1-PR6 roads, PA1-PA3 public activity,
  PC1-PC3 car parks, PE1 connecting elements).
* :data:`LED_SPECS`               -- Typical LED luminaire bands.
* :class:`LightingDesign`         -- Dataclass holding a full design.
* :func:`select_subcategory`      -- ``(location_type, activity_level)``
  -> subcategory string.
* :func:`design_lighting`         -- End-to-end design calculation.
* :func:`verify_design`           -- Photometric (lumen-method) check.
* :func:`size_solar_alternative`  -- Off-grid solar PV sizing.
* :func:`format_design_report`    -- Human-readable text report.
"""

from smart_street_lighting.engine.calc import (
    SUBCATEGORIES,
    LED_SPECS,
    OPERATING_HOURS_PER_YEAR,
    ELECTRICITY_RATE_PER_KWH,
    CARBON_FACTOR_VIC_SCOPE2_3,
    RECOMMENDED_CCT,
    LED_MAINTENANCE_FACTOR,
    LED_LIFESPAN_YEARS,
    LED_CRI,
    LightingDesign,
    select_subcategory,
    select_led_spec,
    select_pole_height,
    calculate_spacing,
    design_lighting,
    verify_design,
    size_solar_alternative,
    format_design_report,
)

__all__ = [
    "SUBCATEGORIES",
    "LED_SPECS",
    "OPERATING_HOURS_PER_YEAR",
    "ELECTRICITY_RATE_PER_KWH",
    "CARBON_FACTOR_VIC_SCOPE2_3",
    "RECOMMENDED_CCT",
    "LED_MAINTENANCE_FACTOR",
    "LED_LIFESPAN_YEARS",
    "LED_CRI",
    "LightingDesign",
    "select_subcategory",
    "select_led_spec",
    "select_pole_height",
    "calculate_spacing",
    "design_lighting",
    "verify_design",
    "size_solar_alternative",
    "format_design_report",
]
