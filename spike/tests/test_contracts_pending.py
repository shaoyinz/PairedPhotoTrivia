"""Contract details §1.1.5 fixes now, for stubs filled later.

Strict xfail: each turns into a failure the moment its stub is implemented, which is the cue
to delete the marker and keep the test.
"""

import pytest

from photoquiz.buckets import expand
from photoquiz.models import BucketKey

pending = pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="§1.4 not implemented")


@pending
def test_expand_is_27_cells_normally():
    assert len(expand(BucketKey("9q8yyk", 1000))) == 27


@pending
def test_expand_wraps_the_antimeridian():
    assert len(expand(BucketKey("800000", 1000))) == 27  # lon -180


@pending
@pytest.mark.parametrize("pole", ["zzzzzz", "000000"])
def test_expand_degrades_at_the_poles(pole):
    cells = {k.geohash6 for k in expand(BucketKey(pole, 1000))}
    assert pole in cells and len(cells) < 9
