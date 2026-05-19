"""
smart_street_lighting_plugin
============================

Plumbing for an AS/NZS 1158-compliant smart street lighting design system.

The library is deliberately split into a few small modules so a Jupyter
notebook can import only what it needs:

* :mod:`smart_street_lighting.engine`   -- deterministic AS/NZS 1158
  calculation engine (P-category lookup, lighting design, photometric
  verification, solar sizing, LCC and CO2 math).
* :mod:`smart_street_lighting.osm`      -- Overpass + Nominatim fallback
  resolver for parks / pathways, plus geometric helpers (haversine,
  polyline measurement, light placement).
* :mod:`smart_street_lighting.rag`      -- ChromaDB + LlamaIndex
  ingestion and query helpers wired to LM Studio's OpenAI-compatible
  API. The notebook supplies the model names so model choice stays
  visible to the marker.

The notebook is the deliverable; this library is the plumbing.
"""

__version__ = "0.1.5"

from smart_street_lighting._defaults import (
    default_openrouter_key,
    bundled_dotenv,
)
from smart_street_lighting.engine import (
    SUBCATEGORIES,
    LED_SPECS,
    LightingDesign,
    design_lighting,
    select_subcategory,
    verify_design,
    size_solar_alternative,
    format_design_report,
)
from smart_street_lighting.osm import (
    resolve_pathway,
    fetch_park_data,
    fetch_pathways,
    geocode_nominatim,
    bounds_from_osm_boundary,
)
from smart_street_lighting.osm.geometry import (
    haversine,
    measure_polyline_length,
    find_intersections,
    find_entry_points,
    place_lights_on_polyline,
)
from smart_street_lighting.rag import bootstrap_knowledge_base

__all__ = [
    "__version__",
    # defaults
    "default_openrouter_key",
    "bundled_dotenv",
    # engine
    "SUBCATEGORIES",
    "LED_SPECS",
    "LightingDesign",
    "design_lighting",
    "select_subcategory",
    "verify_design",
    "size_solar_alternative",
    "format_design_report",
    # osm
    "resolve_pathway",
    "fetch_park_data",
    "fetch_pathways",
    "geocode_nominatim",
    "bounds_from_osm_boundary",
    # geometry
    "haversine",
    "measure_polyline_length",
    "find_intersections",
    "find_entry_points",
    "place_lights_on_polyline",
    # rag
    "bootstrap_knowledge_base",
]
