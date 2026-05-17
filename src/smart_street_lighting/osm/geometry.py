"""
Geometric helpers for pathway analysis.

Pure-Python, no third-party deps -- everything operates on lists of
``(lat, lon)`` tuples or GeoJSON-style dicts. Distance calculations
use the haversine formula on a spherical earth approximation, which is
accurate to better than 0.5 percent for the path lengths we deal with.
"""

from __future__ import annotations

import math
from typing import Optional


EARTH_RADIUS_M = 6_371_000


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two ``(lat, lon)`` points in metres.

    Formula::

        a = sin^2((lat2-lat1)/2) + cos(lat1) cos(lat2) sin^2((lon2-lon1)/2)
        d = 2 R asin(sqrt(a))
    """
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# Internal alias retained for parity with the original codebase.
_haversine = haversine


def measure_polyline_length(coords: list[tuple]) -> float:
    """Sum haversine distances between consecutive ``(lat, lon)`` points."""
    total = 0.0
    for i in range(len(coords) - 1):
        total += haversine(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
    return total


def _point_near(p1: tuple, p2: tuple, threshold_m: float) -> bool:
    return haversine(p1[0], p1[1], p2[0], p2[1]) < threshold_m


def find_intersections(pathways: list[dict], threshold_m: float = 5.0) -> list[dict]:
    """
    Find points where two or more pathway polylines meet.

    Args:
        pathways: List of dicts with a ``"geometry"`` key holding a
            GeoJSON LineString (coordinates as ``[[lon, lat], ...]``).
        threshold_m: Two vertices within this distance are treated as
            the same node.

    Returns:
        List of ``{"lat": float, "lng": float, "paths_meeting": int}``
        dicts.
    """
    node_counts: dict[tuple, int] = {}

    for pw in pathways:
        geom = pw.get("geometry", {})
        coords = geom.get("coordinates", [])
        seen_in_this_path: set = set()
        for coord in coords:
            lon, lat = coord[0], coord[1]
            point = (round(lat, 7), round(lon, 7))
            matched = False
            for existing in list(node_counts.keys()):
                if _point_near(point, existing, threshold_m) and existing not in seen_in_this_path:
                    node_counts[existing] += 1
                    seen_in_this_path.add(existing)
                    matched = True
                    break
            if not matched and point not in seen_in_this_path:
                node_counts[point] = node_counts.get(point, 0) + 1
                seen_in_this_path.add(point)

    return [
        {"lat": lat, "lng": lon, "paths_meeting": count}
        for (lat, lon), count in node_counts.items()
        if count >= 2
    ]


def find_entry_points(
    pathway: dict, park_boundary: dict, threshold_m: float = 20.0
) -> list[dict]:
    """
    Find pathway endpoints that touch the park boundary.

    Args:
        pathway: Dict with a ``"geometry"`` GeoJSON LineString.
        park_boundary: GeoJSON Polygon dict.
        threshold_m: Max distance from boundary to count as an entry.

    Returns:
        List of ``{"lat": float, "lng": float, "adjacent_to": str}``.
    """
    geom = pathway.get("geometry", {})
    path_coords = geom.get("coordinates", [])
    if not path_coords:
        return []

    boundary_coords: list[tuple] = []
    raw_boundary = park_boundary.get("coordinates", [])
    if raw_boundary and isinstance(raw_boundary[0], list):
        ring = raw_boundary[0] if isinstance(raw_boundary[0][0], list) else raw_boundary
        for coord in ring:
            boundary_coords.append((coord[1], coord[0]))

    if not boundary_coords:
        return []

    entry_points: list[dict] = []
    endpoints = [path_coords[0], path_coords[-1]]
    for coord in endpoints:
        lon, lat = coord[0], coord[1]
        for blat, blon in boundary_coords:
            if haversine(lat, lon, blat, blon) < threshold_m:
                entry_points.append({"lat": lat, "lng": lon, "adjacent_to": "park_boundary"})
                break
    return entry_points


def _interpolate_point(p1: tuple, p2: tuple, fraction: float) -> tuple:
    return (
        p1[0] + (p2[0] - p1[0]) * fraction,
        p1[1] + (p2[1] - p1[1]) * fraction,
    )


def _point_at_chainage(
    coords: list[tuple], chainages: list[float], target: float
) -> tuple:
    if target <= 0:
        return coords[0]
    if target >= chainages[-1]:
        return coords[-1]
    for i in range(1, len(chainages)):
        if chainages[i] >= target:
            seg_length = chainages[i] - chainages[i - 1]
            if seg_length == 0:
                return coords[i]
            fraction = (target - chainages[i - 1]) / seg_length
            return _interpolate_point(coords[i - 1], coords[i], fraction)
    return coords[-1]


def place_lights_on_polyline(
    coords: list[tuple],
    spacing_m: float,
    intersections: Optional[list[dict]] = None,
    entry_points: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Place lights along a pathway at regular intervals.

    Mandatory placements: one at every intersection and entry point.
    Fill remaining segments at the calculated spacing. Lights are
    placed in chainage order so the result can be drawn directly on a
    map.

    Args:
        coords: ``[(lat, lon), ...]`` polyline vertices.
        spacing_m: Target spacing between lights in metres.
        intersections: Intersection dicts (``lat``, ``lng``).
        entry_points: Entry-point dicts (``lat``, ``lng``).

    Returns:
        List of ``{"lat", "lng", "type", "chainage_m"}`` dicts.
    """
    if not coords or spacing_m <= 0:
        return []

    intersections = intersections or []
    entry_points = entry_points or []

    chainages = [0.0]
    for i in range(1, len(coords)):
        seg = haversine(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])
        chainages.append(chainages[-1] + seg)
    total_length = chainages[-1]

    if total_length == 0:
        return [{"lat": coords[0][0], "lng": coords[0][1], "type": "pathway", "chainage_m": 0.0}]

    mandatory: list[dict] = []
    for pt_list, pt_type in [(intersections, "intersection"), (entry_points, "entry")]:
        for pt in pt_list:
            plat, plon = pt["lat"], pt["lng"]
            best_chainage = 0.0
            best_dist = float("inf")
            for i in range(len(coords) - 1):
                seg_len = chainages[i + 1] - chainages[i]
                if seg_len == 0:
                    continue
                d_start = haversine(plat, plon, coords[i][0], coords[i][1])
                d_end = haversine(plat, plon, coords[i + 1][0], coords[i + 1][1])
                if d_start < best_dist:
                    best_dist = d_start
                    best_chainage = chainages[i]
                if d_end < best_dist:
                    best_dist = d_end
                    best_chainage = chainages[i + 1]
                frac = max(
                    0.0,
                    min(1.0, (d_start ** 2 + seg_len ** 2 - d_end ** 2) / (2 * seg_len ** 2) * seg_len),
                )
                proj_lat = coords[i][0] + (coords[i + 1][0] - coords[i][0]) * (
                    frac / seg_len if seg_len else 0
                )
                proj_lon = coords[i][1] + (coords[i + 1][1] - coords[i][1]) * (
                    frac / seg_len if seg_len else 0
                )
                d_proj = haversine(plat, plon, proj_lat, proj_lon)
                if d_proj < best_dist:
                    best_dist = d_proj
                    best_chainage = chainages[i] + frac
            d_last = haversine(plat, plon, coords[-1][0], coords[-1][1])
            if d_last < best_dist:
                best_dist = d_last
                best_chainage = chainages[-1]
            if best_dist < total_length * 0.5:
                mandatory.append(
                    {"lat": plat, "lng": plon, "type": pt_type, "chainage_m": round(best_chainage, 1)}
                )

    regular: list[dict] = []
    chainage = 0.0
    while chainage <= total_length:
        lat, lon = _point_at_chainage(coords, chainages, chainage)
        regular.append({"lat": lat, "lng": lon, "type": "pathway", "chainage_m": round(chainage, 1)})
        chainage += spacing_m

    if regular and abs(regular[-1]["chainage_m"] - total_length) > spacing_m * 0.3:
        lat, lon = coords[-1]
        regular.append({"lat": lat, "lng": lon, "type": "pathway", "chainage_m": round(total_length, 1)})

    merged = list(mandatory)
    mandatory_chainages = {m["chainage_m"] for m in mandatory}
    for r in regular:
        too_close = any(abs(r["chainage_m"] - mc) < spacing_m * 0.4 for mc in mandatory_chainages)
        if not too_close:
            merged.append(r)
    merged.sort(key=lambda x: x["chainage_m"])
    return merged


def bounds_from_osm_boundary(boundary: dict) -> tuple[float, float, float, float]:
    """
    Return ``(south, west, north, east)`` for a GeoJSON Polygon.

    Useful when you have an OSM park boundary and need its bounding
    box (e.g., for an Overpass ``bbox`` query or a map fit).
    """
    raw = boundary.get("coordinates", [])
    if not raw:
        raise ValueError("Boundary has no coordinates.")
    ring = raw[0] if isinstance(raw[0][0], list) else raw
    lats = [c[1] for c in ring]
    lons = [c[0] for c in ring]
    return (min(lats), min(lons), max(lats), max(lons))
