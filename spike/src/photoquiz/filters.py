"""Pure filters (§1.3). Each rule returns what it dropped, so the report can show it."""

from __future__ import annotations

from dataclasses import dataclass

from photoquiz.models import PhotoMeta


@dataclass(frozen=True, slots=True)
class FilterStats:
    rule: str
    dropped: int


def drop_screenshots(ps: list[PhotoMeta]) -> tuple[list[PhotoMeta], FilterStats]:
    raise NotImplementedError("§1.3")


def drop_missing_timestamp(ps: list[PhotoMeta]) -> tuple[list[PhotoMeta], FilterStats]:
    raise NotImplementedError("§1.3")


def collapse_bursts(ps: list[PhotoMeta]) -> tuple[list[PhotoMeta], FilterStats]:
    """One photo per burst_id: prefer is_burst_pick, else earliest."""
    raise NotImplementedError("§1.3")


def apply_all(ps: list[PhotoMeta]) -> tuple[list[PhotoMeta], list[FilterStats]]:
    """All rules in order. No-GPS photos are kept (they count for >= 5 and for backfill)."""
    raise NotImplementedError("§1.3")
