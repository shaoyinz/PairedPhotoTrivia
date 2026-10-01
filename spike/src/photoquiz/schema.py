"""THE CSV contract between the Swift exporter (and osxphotos) and the Python reader.

The iOS exporter copies `CSV_HEADER` verbatim; `tests/test_schema.py` pins it, so a change on
either side fails a test instead of shifting columns silently.
"""

from __future__ import annotations

from collections.abc import Sequence

from photoquiz.models import PhotoMeta

CSV_COLUMNS: tuple[str, ...] = (
    "asset_id", "utc_epoch", "tz_offset_s", "lat", "lon", "is_screenshot",
    "burst_id", "is_burst_pick", "camera_make", "camera_model", "width", "height",
)  # fmt: skip
CSV_HEADER: str = ",".join(CSV_COLUMNS)

# pandas nullable dtypes for the parquet edge (as strings, so this module stays pandas-free)
CSV_DTYPES: dict[str, str] = {
    "asset_id": "string",
    "utc_epoch": "Int64",
    "tz_offset_s": "Int32",
    "lat": "Float64",
    "lon": "Float64",
    "is_screenshot": "boolean",
    "burst_id": "string",
    "is_burst_pick": "boolean",
    "camera_make": "string",
    "camera_model": "string",
    "width": "Int32",
    "height": "Int32",
}

# Hand-labeled ground truth (§1.8). Dates are UTC, ISO yyyy-mm-dd, inclusive.
LABEL_COLUMNS: tuple[str, ...] = ("label", "start_date", "end_date", "place")
LABEL_HEADER: str = ",".join(LABEL_COLUMNS)


class SchemaError(ValueError):
    pass


def check_header(header: Sequence[str]) -> None:
    """Fail loudly on any difference in names or order."""
    got = tuple(h.strip() for h in header)
    if got != CSV_COLUMNS:
        raise SchemaError(f"CSV header mismatch.\n  expected: {CSV_HEADER}\n  got:      {','.join(got)}")


def _opt_str(s: str) -> str | None:
    return s if s != "" else None


def _opt_int(s: str) -> int | None:
    return int(s) if s != "" else None


def _opt_float(s: str) -> float | None:
    return float(s) if s != "" else None


def _bool(s: str) -> bool:
    v = s.strip().lower()
    if v in ("1", "true"):
        return True
    if v in ("0", "false", ""):
        return False
    raise SchemaError(f"not a boolean: {s!r}")


def parse_row(row: Sequence[str]) -> PhotoMeta:
    """Empty cell = missing. Booleans are 0/1 (true/false also accepted)."""
    if len(row) != len(CSV_COLUMNS):
        raise SchemaError(f"expected {len(CSV_COLUMNS)} fields, got {len(row)}: {row!r}")
    (asset_id, utc_epoch, tz_offset_s, lat, lon, is_screenshot,
     burst_id, is_burst_pick, camera_make, camera_model, width, height) = row  # fmt: skip
    if asset_id == "":
        raise SchemaError("empty asset_id")
    return PhotoMeta(
        asset_id=asset_id,
        utc_epoch=_opt_int(utc_epoch),
        tz_offset_s=_opt_int(tz_offset_s),
        lat=_opt_float(lat),
        lon=_opt_float(lon),
        is_screenshot=_bool(is_screenshot),
        burst_id=_opt_str(burst_id),
        is_burst_pick=_bool(is_burst_pick),
        camera_make=_opt_str(camera_make),
        camera_model=_opt_str(camera_model),
        width=_opt_int(width),
        height=_opt_int(height),
    )


def format_row(p: PhotoMeta) -> list[str]:
    def s(v: object) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "1" if v else "0"
        if isinstance(v, float):
            return f"{v:.6f}"
        return str(v)

    return [s(getattr(p, c)) for c in CSV_COLUMNS]
