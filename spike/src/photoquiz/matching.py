"""HASH-BLIND BY CONSTRUCTION (§1.4).

This module is what crosses the network in phase 2, so it may only ever see `BucketHash`.
`tests/test_matching_is_blind.py` enforces that with `ast` — do not import anything that
carries coordinates or timestamps here.

Only one side is expanded: intersect expand(A) against raw B. Expanding both roughly triples
the effective radius and window and inflates false matches.
"""

from __future__ import annotations

from photoquiz.models import BucketHash


def match(expanded_a: frozenset[BucketHash], raw_b: frozenset[BucketHash]) -> frozenset[BucketHash]:
    """The hashes both sides hold. Each device then maps them back to its own keys and photos
    (`buckets.matched_keys`, `buckets.matched_photos`); nothing here can."""
    return expanded_a & raw_b
