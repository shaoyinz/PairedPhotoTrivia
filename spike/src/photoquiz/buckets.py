"""geohash6 x hour buckets, neighbor expansion, salting (§1.4).

Device-local: this module sees coordinates and timestamps. Only `salted` output leaves a device,
and `matching.py` sees nothing else. After the intersection, `matched_keys` and `matched_photos`
map the surviving hashes back using this device's own data alone.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterable

import pygeohash as pgh

from photoquiz.models import BucketHash, BucketKey, PhotoMeta

GEOHASH_PRECISION = 6
SALT_BYTES = 32
HASH_BYTES = 16


def bucket_key(p: PhotoMeta) -> BucketKey | None:
    """(geohash6, utc_epoch // 3600). None when no GPS — not an error.

    Floor division, so a pre-1970 photo lands in the hour that contains it; Swift's `/`
    truncates toward zero, so the port needs floor division too. Also None without a timestamp,
    though filters drop those first.
    """
    if p.lat is None or p.lon is None or p.utc_epoch is None:
        return None
    return BucketKey(pgh.encode(p.lat, p.lon, precision=GEOHASH_PRECISION), p.utc_epoch // 3600)


def _cells(gh: str) -> list[str]:
    """Self + 8 neighbors: the rows above, at and below, each with its left and right cell."""
    rows = [gh]
    for vertical in ("top", "bottom"):
        try:
            rows.append(pgh.get_adjacent(gh, vertical))
        except ValueError:  # "No adjacent geohash to the top…": that row lies beyond a pole
            pass
    return [c for r in rows for c in (r, pgh.get_adjacent(r, "left"), pgh.get_adjacent(r, "right"))]


def expand(k: BucketKey) -> frozenset[BucketKey]:
    """Self + 8 geohash-6 neighbors, x hours {h-1, h, h+1}: 27 keys normally.

    Neighbors come from `pygeohash.get_adjacent(gh, direction)` with the bare strings
    "right"/"left"/"top"/"bottom" (a typing.Literal, not an enum). At either pole it raises
    `ValueError: No adjacent geohash to the top…`, so that row is skipped: 6 cells, 18 keys.
    The antimeridian wraps on its own.
    """
    return frozenset(BucketKey(c, k.hour_index + dh) for c in _cells(k.geohash6) for dh in (-1, 0, 1))


def salted(k: BucketKey, salt: bytes) -> BucketHash:
    """HMAC-SHA256(salt, f"{geohash6}|{hour_index}"), truncated to 16 bytes."""
    if len(salt) != SALT_BYTES:
        raise ValueError(f"salt must be {SALT_BYTES} bytes, got {len(salt)}")
    msg = f"{k.geohash6}|{k.hour_index}".encode("ascii")
    return BucketHash(hmac.digest(salt, msg, "sha256")[:HASH_BYTES])


def salted_set(ks: Iterable[BucketKey], salt: bytes) -> frozenset[BucketHash]:
    return frozenset(salted(k, salt) for k in ks)


def own_keys(ps: Iterable[PhotoMeta], *, expanded: bool) -> frozenset[BucketKey]:
    """This device's bucket keys; with expanded=True (side A only), their neighborhoods too."""
    ks = {k for p in ps if (k := bucket_key(p)) is not None}
    return frozenset(e for k in ks for e in expand(k)) if expanded else frozenset(ks)


def matched_keys(own: Iterable[BucketKey], matched: frozenset[BucketHash], salt: bytes) -> frozenset[BucketKey]:
    """The keys behind the surviving hashes, recovered from this device's own keys alone.

    A passes its expanded keys, B its raw ones, and both get the same set back: B's matched
    cells. A surviving hash is in raw_b by construction, and A reached it by expanding.
    """
    return frozenset(k for k in own if salted(k, salt) in matched)


def matched_photos(ps: Iterable[PhotoMeta], keys: frozenset[BucketKey], *, expanded: bool) -> list[PhotoMeta]:
    """This device's photos behind the matched keys, in input order. A (expanded=True) keeps a
    photo whose neighborhood reaches a matched key; B keeps a photo whose own key matched."""
    kept = []
    for p in ps:
        k = bucket_key(p)
        if k is not None and (not expand(k).isdisjoint(keys) if expanded else k in keys):
            kept.append(p)
    return kept
