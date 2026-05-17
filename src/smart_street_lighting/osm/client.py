"""
OpenStreetMap client: Overpass + Nominatim fallback.

The notebook calls :func:`resolve_pathway` and gets back a
``{park_boundary, pathways, selected_pathway}`` dict ready to feed
into :func:`smart_street_lighting.engine.design_lighting`.

No on-disk cache -- callers can re-issue queries themselves if needed.
A Nominatim fallback supplies a boundary-only result when Overpass is
unavailable; this keeps the notebook runnable in a marker's
environment even if Overpass times out.
"""

from __future__ import annotations

from typing import Optional

import requests

from smart_street_lighting.osm.geometry import (
    bounds_from_osm_boundary,
    find_entry_points,
    find_intersections,
    measure_polyline_length,
)


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "smart-street-lighting-plugin/0.1 (https://github.com/hashem59/smart_street_lighting_plugin)"


def _query_overpass(query: str, timeout: int = 60) -> dict:
    """POST an Overpass-QL query and return the parsed JSON response."""
    resp = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=(15, timeout + 15),
    )
    resp.raise_for_status()
    return resp.json()


def geocode_nominatim(
    place_name: str,
    city: str = "Melbourne",
    country: str = "Australia",
    user_agent: str = DEFAULT_USER_AGENT,
) -> Optional[dict]:
    """
    Geocode a place name via Nominatim and return a boundary-shaped dict.

    Used as a fallback when Overpass is unavailable -- gives us a
    rectangular bounding-box polygon (no internal pathway geometry)
    so spatial context can still be visualised.
    """
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": f"{place_name}, {city}, {country}", "format": "json", "limit": 1},
            headers={"User-Agent": user_agent},
            timeout=(10, 15),
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        print(f"Nominatim geocoding failed for '{place_name}': {e}")
        return None

    if not results:
        print(f"Nominatim found no results for '{place_name}' in {city}.")
        return None

    hit = results[0]
    bbox = hit.get("boundingbox")
    if not bbox or len(bbox) < 4:
        return None

    south, north = float(bbox[0]), float(bbox[1])
    west, east = float(bbox[2]), float(bbox[3])

    boundary = {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]],
    }
    return {
        "boundary": boundary,
        "name": hit.get("display_name", place_name),
        "osm_id": hit.get("osm_id"),
        "source": "nominatim",
    }


def _nodes_to_coords(elements: list) -> dict:
    return {
        e["id"]: (e["lat"], e["lon"])
        for e in elements
        if e["type"] == "node" and "lat" in e and "lon" in e
    }


def _way_to_polygon(way: dict, node_lookup: dict) -> Optional[list]:
    coords: list = []
    for nid in way.get("nodes", []):
        if nid in node_lookup:
            lat, lon = node_lookup[nid]
            coords.append([lon, lat])
    return coords if len(coords) >= 3 else None


def fetch_park_data(park_name: str, city: str = "Melbourne") -> Optional[dict]:
    """
    Fetch a park boundary from Overpass.

    Returns ``{"boundary": GeoJSON Polygon, "name": str, "osm_id": int}``
    or ``None`` if the park is not found.
    """
    query = f"""
    [out:json][timeout:60];
    area["name"="{city}"]->.city;
    (
      way(area.city)["leisure"="park"]["name"~"{park_name}",i];
      relation(area.city)["leisure"="park"]["name"~"{park_name}",i];
    );
    out body; >; out skel qt;
    """

    try:
        data = _query_overpass(query)
    except Exception as e:
        print(f"Overpass query failed for park '{park_name}': {e}")
        return None

    elements = data.get("elements", [])
    if not elements:
        print(f"No OSM park found for '{park_name}' in {city}.")
        return None

    node_lookup = _nodes_to_coords(elements)

    boundary_coords: Optional[list] = None
    osm_id: Optional[int] = None
    osm_name = park_name

    for el in elements:
        tags = el.get("tags", {}) or {}
        if el["type"] == "way" and "nodes" in el and tags.get("leisure") == "park":
            coords = _way_to_polygon(el, node_lookup)
            if coords:
                boundary_coords = coords
                osm_id = el["id"]
                osm_name = tags.get("name", park_name)
                break
        elif el["type"] == "relation" and tags.get("leisure") == "park":
            osm_id = el["id"]
            osm_name = tags.get("name", park_name)
            for member in el.get("members", []):
                if member.get("role") == "outer" and member["type"] == "way":
                    for w in elements:
                        if w["type"] == "way" and w["id"] == member["ref"]:
                            coords = _way_to_polygon(w, node_lookup)
                            if coords:
                                boundary_coords = coords
                                break
                    if boundary_coords:
                        break
            if boundary_coords:
                break

    if not boundary_coords:
        print(f"Could not extract boundary for '{park_name}'.")
        return None

    return {
        "boundary": {"type": "Polygon", "coordinates": [boundary_coords]},
        "name": osm_name,
        "osm_id": osm_id,
    }


def fetch_pathways(park_boundary: dict) -> list[dict]:
    """
    Fetch footway / path / cycleway / pedestrian ways inside a park polygon.

    Returns a list of pathway dicts with GeoJSON geometry, measured
    length, and the source OSM ``highway``, ``name``, ``surface`` tags.
    """
    ring = park_boundary.get("coordinates", [[]])[0]
    if not ring:
        return []

    poly_parts = [f"{coord[1]} {coord[0]}" for coord in ring]
    poly_str = " ".join(poly_parts)

    query = f"""
    [out:json][timeout:60];
    way(poly:"{poly_str}")["highway"~"footway|path|cycleway|pedestrian"];
    out geom;
    """
    try:
        data = _query_overpass(query)
    except Exception as e:
        print(f"Overpass pathway query failed: {e}")
        return []

    pathways: list[dict] = []
    for el in data.get("elements", []):
        if el["type"] != "way" or "geometry" not in el:
            continue
        coords = [[pt["lon"], pt["lat"]] for pt in el["geometry"]]
        lat_lon_coords = [(pt["lat"], pt["lon"]) for pt in el["geometry"]]
        length = measure_polyline_length(lat_lon_coords)
        tags = el.get("tags", {}) or {}
        pathways.append({
            "geometry": {"type": "LineString", "coordinates": coords},
            "length_m": round(length, 1),
            "highway_type": tags.get("highway", "path"),
            "name": tags.get("name"),
            "surface": tags.get("surface"),
        })
    return pathways


def resolve_pathway(
    park_name: str,
    pathway_hint: Optional[str] = None,
    city: str = "Melbourne",
) -> Optional[dict]:
    """
    Resolve a park boundary and the primary pathway within it.

    Args:
        park_name: Common name (e.g., ``"Fitzroy Gardens"``).
        pathway_hint: Optional hint like ``"main pathway"`` or a name
            fragment used to pick a pathway.
        city: City to search within.

    Returns:
        ``{park_name, park_boundary, pathways, selected_pathway,
        data_source?}`` or ``None`` if the park is not found at all.
    """
    park = fetch_park_data(park_name, city=city)
    if not park:
        print(f"Overpass unavailable for '{park_name}', trying Nominatim geocoding...")
        nominatim = geocode_nominatim(park_name, city=city)
        if nominatim:
            print(f"Nominatim resolved '{park_name}' (boundary only, no pathways).")
            return {
                "park_name": nominatim["name"],
                "park_boundary": nominatim["boundary"],
                "pathways": [],
                "selected_pathway": None,
                "data_source": "nominatim",
            }
        return None

    pathways_raw = fetch_pathways(park["boundary"])
    if not pathways_raw:
        print(f"No pathways found in '{park_name}'.")
        return {
            "park_name": park["name"],
            "park_boundary": park["boundary"],
            "pathways": [],
            "selected_pathway": None,
            "data_source": "overpass",
        }

    intersections = find_intersections(pathways_raw)

    enriched: list[dict] = []
    longest_idx = 0
    longest_length = 0.0

    for i, pw in enumerate(pathways_raw):
        geom = pw["geometry"]
        lat_lon = [(c[1], c[0]) for c in geom["coordinates"]]
        true_length = measure_polyline_length(lat_lon)
        entries = find_entry_points(pw, park["boundary"])
        pw_intersections: list[dict] = []
        for ix in intersections:
            for coord in geom["coordinates"]:
                if abs(coord[1] - ix["lat"]) < 0.0001 and abs(coord[0] - ix["lng"]) < 0.0001:
                    pw_intersections.append(ix)
                    break
        enriched.append({
            "geometry": geom,
            "true_length_m": round(true_length, 1),
            "intersections": pw_intersections,
            "entry_points": entries,
            "is_primary": False,
            "highway_type": pw["highway_type"],
            "name": pw.get("name"),
            "surface": pw.get("surface"),
        })
        if true_length > longest_length:
            longest_length = true_length
            longest_idx = i

    if enriched:
        enriched[longest_idx]["is_primary"] = True

    selected: Optional[int] = None
    if pathway_hint and enriched:
        hint = pathway_hint.lower()
        if any(k in hint for k in ("main", "primary", "longest")):
            selected = longest_idx
        else:
            for i, pw in enumerate(enriched):
                if pw.get("name") and hint in pw["name"].lower():
                    selected = i
                    break
            if selected is None:
                selected = longest_idx
    elif enriched:
        selected = longest_idx

    return {
        "park_name": park["name"],
        "park_boundary": park["boundary"],
        "pathways": enriched,
        "selected_pathway": selected,
        "data_source": "overpass",
    }


__all__ = [
    "OVERPASS_URL",
    "NOMINATIM_URL",
    "DEFAULT_USER_AGENT",
    "bounds_from_osm_boundary",
    "geocode_nominatim",
    "fetch_park_data",
    "fetch_pathways",
    "resolve_pathway",
]
