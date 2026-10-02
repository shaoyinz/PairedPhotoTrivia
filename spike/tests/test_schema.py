import dataclasses
import re
from pathlib import Path

import pytest

from photoquiz.models import PhotoMeta
from photoquiz.schema import CSV_COLUMNS, CSV_DTYPES, CSV_HEADER, SchemaError, check_header, format_row, parse_row

# Pinned byte for byte. The Swift exporter (ios/MetadataExport/) copies this exact string;
# change both sides together or not at all.
PINNED_HEADER = (
    "asset_id,utc_epoch,tz_offset_s,lat,lon,is_screenshot,"
    "burst_id,is_burst_pick,camera_make,camera_model,width,height"
)


SWIFT_ROW = Path(__file__).resolve().parents[2] / "ios/MetadataExport/MetadataExport/CSVRow.swift"


def test_header_is_pinned():
    assert CSV_HEADER == PINNED_HEADER


def test_swift_exporter_header_is_pinned():
    m = re.search(r'static let header = "([^"]*)"', SWIFT_ROW.read_text())
    assert m is not None, f"no `static let header` in {SWIFT_ROW}"
    assert m.group(1) == PINNED_HEADER


def test_photo_meta_fields_follow_csv_order():
    assert tuple(f.name for f in dataclasses.fields(PhotoMeta)) == CSV_COLUMNS
    assert tuple(CSV_DTYPES) == CSV_COLUMNS


def test_check_header_rejects_reordered_columns():
    swapped = list(CSV_COLUMNS)
    swapped[3], swapped[4] = swapped[4], swapped[3]
    with pytest.raises(SchemaError):
        check_header(swapped)


def test_row_round_trip_with_missing_values():
    p = PhotoMeta("X-1", 1_700_000_000, -25200, None, None, True, None, False, None, None, 1179, 2556)
    assert parse_row(format_row(p)) == p


def test_parse_row_rejects_wrong_field_count():
    with pytest.raises(SchemaError):
        parse_row(["X-1", "1700000000"])
