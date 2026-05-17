"""
OpenStreetMap resolver with a Nominatim geocoding fallback.

The notebook calls :func:`resolve_pathway` with a park name and gets
back a GeoJSON park polygon plus a list of pathways with measured
length, intersections, and entry points.

Caching has been intentionally removed from the library -- the
notebook is the single-shot deliverable, and the user does not want a
silent on-disk cache hiding network behaviour from the marker.
"""

from smart_street_lighting.osm.client import (
    OVERPASS_URL,
    NOMINATIM_URL,
    bounds_from_osm_boundary,
    geocode_nominatim,
    fetch_park_data,
    fetch_pathways,
    resolve_pathway,
)

__all__ = [
    "OVERPASS_URL",
    "NOMINATIM_URL",
    "bounds_from_osm_boundary",
    "geocode_nominatim",
    "fetch_park_data",
    "fetch_pathways",
    "resolve_pathway",
]
