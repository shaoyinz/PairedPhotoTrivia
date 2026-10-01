"""Coverage stats and evaluation against hand labels (§1.8)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from photoquiz.filters import FilterStats
from photoquiz.models import PhotoMeta, TripWindow


@dataclass(frozen=True, slots=True)
class Label:
    label: str
    start_date: str  # UTC yyyy-mm-dd, inclusive
    end_date: str
    place: str


@dataclass(frozen=True, slots=True)
class Coverage:
    total: int
    with_gps: int
    by_year: dict[int, tuple[int, int]]  # year -> (with_gps, total)
    camera: tuple[int, int]  # (with_gps, total) where camera_make is set
    imported: tuple[int, int]  # (with_gps, total) where it is not


@dataclass(frozen=True, slots=True)
class Evaluation:
    precision: float
    recall: float
    true_positives: int
    false_positives: int
    false_negatives: int
    splits: int  # n detected : 1 labeled
    merges: int  # 1 detected : n labeled


def coverage(ps: Sequence[PhotoMeta]) -> Coverage:
    raise NotImplementedError("§1.8")


def evaluate(trips: Sequence[TripWindow], labels: Sequence[Label]) -> Evaluation:
    """A detected trip is a true positive if it overlaps a labeled trip in time."""
    raise NotImplementedError("§1.8")


def render(
    cov: dict[str, Coverage], filter_stats: dict[str, list[FilterStats]], ev: Evaluation
) -> str:
    """Markdown for data/spike_report.md: numbers only, no raw rows."""
    raise NotImplementedError("§1.8")
