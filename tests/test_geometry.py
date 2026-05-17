"""Smoke tests for geometric helpers."""

import pytest

from smart_street_lighting import (
    bounds_from_osm_boundary,
    haversine,
    measure_polyline_length,
    place_lights_on_polyline,
)


def test_haversine_known_distance():
    # Melbourne CBD to St Kilda is ~6 km
    d = haversine(-37.8136, 144.9631, -37.8676, 144.9810)
    assert 5500 < d < 6500


def test_measure_polyline_length_straight():
    coords = [(-37.81, 144.96), (-37.82, 144.96)]
    length = measure_polyline_length(coords)
    assert 1000 < length < 1300


def test_place_lights_returns_evenly_spaced():
    coords = [(-37.81, 144.96), (-37.815, 144.96)]
    placed = place_lights_on_polyline(coords, spacing_m=50.0)
    assert len(placed) >= 2
    # chainage_m strictly non-decreasing
    chainages = [p["chainage_m"] for p in placed]
    assert chainages == sorted(chainages)


def test_bounds_from_osm_boundary():
    boundary = {
        "type": "Polygon",
        "coordinates": [[
            [144.96, -37.82],
            [144.98, -37.82],
            [144.98, -37.81],
            [144.96, -37.81],
            [144.96, -37.82],
        ]],
    }
    south, west, north, east = bounds_from_osm_boundary(boundary)
    assert south == -37.82 and north == -37.81
    assert west == 144.96 and east == 144.98


def test_bounds_rejects_empty():
    with pytest.raises(ValueError):
        bounds_from_osm_boundary({"type": "Polygon", "coordinates": []})
