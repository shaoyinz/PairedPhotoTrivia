"""Home / work inference from local hours (§1.5)."""

from __future__ import annotations

from collections.abc import Sequence

from photoquiz.models import Anchors, PhotoMeta


def local_hour(p: PhotoMeta) -> int:
    """0..23 from local_epoch. Never use for matching."""
    raise NotImplementedError("§1.5")


def infer_anchors(
    ps: Sequence[PhotoMeta], *, now_utc: int, window_days: int = 90, min_support: int = 20
) -> Anchors:
    """Home = most frequent geohash-7 at local [00:00, 06:00).
    Work = most frequent geohash-7 at local [10:00, 16:00) Mon–Fri. Last `window_days` only.
    """
    raise NotImplementedError("§1.5")
