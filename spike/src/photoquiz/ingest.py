"""CSV (iOS exporter or osxphotos) -> data/<person>_photos.parquet (§1.2c).

The only module besides report/cli that touches pandas. Metadata only: no image data,
thumbnails or file copies at any stage.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from pathlib import Path

import pandas as pd

from photoquiz.models import PhotoMeta
from photoquiz.schema import CSV_COLUMNS, CSV_DTYPES, SchemaError, check_header, parse_row


@dataclass(frozen=True, slots=True)
class IngestSummary:
    rows: int
    first_utc: int | None
    last_utc: int | None
    no_timestamp: int
    no_gps: int


def read_csv(path: Path) -> list[PhotoMeta]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise SchemaError(f"{path}: empty file")
        check_header(header)
        out = []
        for line_no, row in enumerate(reader, start=2):
            try:
                out.append(parse_row(row))
            except (SchemaError, ValueError) as e:
                raise SchemaError(f"{path}:{line_no}: {e}") from e
    return out


def summarize(ps: list[PhotoMeta]) -> IngestSummary:
    times = [p.utc_epoch for p in ps if p.utc_epoch is not None]
    return IngestSummary(
        rows=len(ps),
        first_utc=min(times, default=None),
        last_utc=max(times, default=None),
        no_timestamp=len(ps) - len(times),
        no_gps=sum(not p.has_gps for p in ps),
    )


def to_frame(ps: list[PhotoMeta]) -> pd.DataFrame:
    cols = {c: [getattr(p, c) for p in ps] for c in CSV_COLUMNS}
    return pd.DataFrame(cols).astype(CSV_DTYPES)


def write_parquet(ps: list[PhotoMeta], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_frame(ps).to_parquet(path, index=False)


def read_parquet(path: Path) -> list[PhotoMeta]:
    df = pd.read_parquet(path)
    check_header(list(df.columns))
    casts = {f.name: f.type for f in fields(PhotoMeta)}
    py = {"str": str, "int": int, "float": float, "bool": bool}

    def conv(col: str, v: object) -> object:
        if v is None or v is pd.NA or (isinstance(v, float) and v != v):
            return None
        base = str(casts[col]).split(" | ")[0]
        return py[base](v)

    return [
        PhotoMeta(**{c: conv(c, v) for c, v in zip(CSV_COLUMNS, row, strict=True)})
        for row in df.itertuples(index=False, name=None)
    ]
