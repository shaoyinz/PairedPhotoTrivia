"""Commute buffer and the "counts as away" rule (§1.6). Geometry on the project.to_km plane."""

from __future__ import annotations

from shapely.geometry.base import BaseGeometry

from photoquiz.models import LatLon


def commute_buffer(home: LatLon, work: LatLon | None, km: float = 5.0) -> BaseGeometry:
    """Buffer around the straight home->work segment (a disc around home when work is None)."""
    raise NotImplementedError("§1.6")


def is_shared_home(a: LatLon, b: LatLon, km: float = 1.0) -> bool:
    raise NotImplementedError("§1.6")


def is_away(p: LatLon, buf_a: BaseGeometry, buf_b: BaseGeometry, *, shared_home: bool) -> bool:
    """Shared home -> outside BOTH buffers. Different homes -> outside EITHER (visits count)."""
    raise NotImplementedError("§1.6")
