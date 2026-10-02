"""Pure filters (§1.3). Each rule returns what it dropped, so the report can show it.

Every rule keeps input order, and no rule looks at GPS: no-GPS photos still count for the
>= 5 rule and for backfill.
"""

from __future__ import annotations

from dataclasses import dataclass

from photoquiz.models import PhotoMeta


@dataclass(frozen=True, slots=True)
class FilterStats:
    rule: str
    dropped: int


def drop_screenshots(ps: list[PhotoMeta]) -> tuple[list[PhotoMeta], FilterStats]:
    """Trusts `is_screenshot` alone. Both exporters set it (PhotoKit's subtype; osxphotos' flag or
    a PNG with no camera make). Re-deriving it here from `camera_make` would be wrong: the iOS
    exporter leaves that column empty on every row."""
    kept = [p for p in ps if not p.is_screenshot]
    return kept, FilterStats("screenshot", len(ps) - len(kept))


def drop_missing_timestamp(ps: list[PhotoMeta]) -> tuple[list[PhotoMeta], FilterStats]:
    kept = [p for p in ps if p.utc_epoch is not None]
    return kept, FilterStats("no_timestamp", len(ps) - len(kept))


def _burst_rank(p: PhotoMeta) -> tuple[bool, bool, int, str]:
    # Lowest wins: a pick, then a timestamp, then the earliest, then asset_id for a stable tie-break.
    return (not p.is_burst_pick, p.utc_epoch is None, p.utc_epoch or 0, p.asset_id)


def collapse_bursts(ps: list[PhotoMeta]) -> tuple[list[PhotoMeta], FilterStats]:
    """One photo per burst_id: prefer is_burst_pick, else earliest."""
    best: dict[str, int] = {}  # burst_id -> index of its representative
    for i, p in enumerate(ps):
        if p.burst_id is None:
            continue
        j = best.get(p.burst_id)
        if j is None or _burst_rank(p) < _burst_rank(ps[j]):
            best[p.burst_id] = i
    kept = [p for i, p in enumerate(ps) if p.burst_id is None or best[p.burst_id] == i]
    return kept, FilterStats("burst_duplicate", len(ps) - len(kept))


def apply_all(ps: list[PhotoMeta]) -> tuple[list[PhotoMeta], list[FilterStats]]:
    """All rules in order. No-GPS photos are kept (they count for >= 5 and for backfill).

    A photo that breaks two rules is counted once, under the first: screenshots, then missing
    timestamps, then bursts (last, so "earliest" compares real timestamps).
    """
    stats = []
    for rule in (drop_screenshots, drop_missing_timestamp, collapse_bursts):
        ps, s = rule(ps)
        stats.append(s)
    return ps, stats
