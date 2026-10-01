"""Matched buckets -> trip windows (§1.7)."""

from __future__ import annotations

from collections.abc import Sequence

from photoquiz.models import Anchors, BucketKey, PhotoMeta, TripWindow


def sessionize(matched: Sequence[BucketKey], *, gap_hours: int = 6) -> list[list[BucketKey]]:
    """Sort by hour; a gap > gap_hours starts a new session."""
    raise NotImplementedError("§1.7")


def assemble(
    sessions: Sequence[Sequence[BucketKey]],
    anchors_a: Anchors,
    anchors_b: Anchors,
    *,
    ps_a: Sequence[PhotoMeta],
    ps_b: Sequence[PhotoMeta],
    min_photos: int = 5,
) -> list[TripWindow]:
    """Keep a session if >= 1 matched bucket is away and the backfilled window holds
    >= min_photos across both devices."""
    raise NotImplementedError("§1.7")


def backfill(w: TripWindow, ps_a: Sequence[PhotoMeta], ps_b: Sequence[PhotoMeta]) -> TripWindow:
    """Count every photo from both partners inside the window, unmatched and GPS-less included."""
    raise NotImplementedError("§1.7")
