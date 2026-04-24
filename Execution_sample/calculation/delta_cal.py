"""
Standalone DELTA_ANGLE calculator for saved candle CSV files.

Reads candle files from ``data`` by default, computes:
  - S_DIP_BB
  - S_DIM_BB
  - DL_Plus_Angle
  - DL_Minus_Angle
  - DELTA_ANGLE

and writes enriched CSV files to ``data/delta`` unless ``--in-place`` is used.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Iterable, Iterator, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_DIR, MAINTENANCE_CONTACT_MESSAGE, MAINTENANCE_MODE
from calculation.calc_lib import SMA

DI_PLUS_COL = "DI_Plus"
DI_MINUS_COL = "DI_Minus"
SLOPE_PLUS_COL = "S_DIP_BB"
SLOPE_MINUS_COL = "S_DIM_BB"
DL_PLUS_ANGLE_COL = "DL_Plus_Angle"
DL_MINUS_ANGLE_COL = "DL_Minus_Angle"
DELTA_ANGLE_COL = "DELTA_ANGLE"


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == ""


def _to_float(value: object) -> float | None:
    if _is_blank(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _format_number(value: float | None, decimals: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{decimals}f}"


def _calculate_delta_angle(
    di_plus: float | None,
    di_minus: float | None,
    dl_plus_angle: float | None,
    dl_minus_angle: float | None,
) -> float | None:
    if (
        di_plus is None
        or di_minus is None
        or dl_plus_angle is None
        or dl_minus_angle is None
    ):
        return None

    if math.isclose(di_plus, di_minus, rel_tol=0.0, abs_tol=1e-12):
        return 0.0

    if di_plus > di_minus:
        return dl_plus_angle - dl_minus_angle

    return -(dl_minus_angle - dl_plus_angle)


def enrich_rows(rows: Sequence[dict], smooth_len: int = 5) -> list[dict]:
    """Return enriched copies of CSV rows with DELTA_ANGLE-related columns."""
    plus_sma = SMA(max(1, int(smooth_len)))
    minus_sma = SMA(max(1, int(smooth_len)))

    prev_di_plus: float | None = None
    prev_di_minus: float | None = None
    enriched: list[dict] = []

    for source_row in rows:
        row = dict(source_row)

        di_plus = _to_float(row.get(DI_PLUS_COL))
        di_minus = _to_float(row.get(DI_MINUS_COL))

        slope_plus = _to_float(row.get(SLOPE_PLUS_COL))
        if slope_plus is None:
            if di_plus is None or prev_di_plus is None:
                slope_plus = 0.0
            else:
                slope_plus = di_plus - prev_di_plus

        slope_minus = _to_float(row.get(SLOPE_MINUS_COL))
        if slope_minus is None:
            if di_minus is None or prev_di_minus is None:
                slope_minus = 0.0
            else:
                slope_minus = di_minus - prev_di_minus

        raw_plus_angle = math.degrees(math.atan(slope_plus))
        raw_minus_angle = math.degrees(math.atan(slope_minus))

        dl_plus_angle = plus_sma.update(raw_plus_angle, is_close=True)
        dl_minus_angle = minus_sma.update(raw_minus_angle, is_close=True)
        delta_angle = _calculate_delta_angle(
            di_plus=di_plus,
            di_minus=di_minus,
            dl_plus_angle=dl_plus_angle,
            dl_minus_angle=dl_minus_angle,
        )

        row[SLOPE_PLUS_COL] = _format_number(slope_plus)
        row[SLOPE_MINUS_COL] = _format_number(slope_minus)
        row[DL_PLUS_ANGLE_COL] = _format_number(dl_plus_angle)
        row[DL_MINUS_ANGLE_COL] = _format_number(dl_minus_angle)
        row[DELTA_ANGLE_COL] = _format_number(delta_angle)

        enriched.append(row)

        if di_plus is not None:
            prev_di_plus = di_plus
        if di_minus is not None:
            prev_di_minus = di_minus

    return enriched


def _iter_input_files(input_paths: Iterable[str]) -> Iterator[Path]:
    for raw_path in input_paths:
        path = Path(raw_path)
        if path.is_dir():
            yield from sorted(path.glob("*.csv"))
            continue
        if any(char in raw_path for char in "*?[]"):
            yield from sorted(Path().glob(raw_path))
            continue
        yield path


def _read_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("missing CSV header")
        rows = list(reader)
        return list(reader.fieldnames), rows


def _write_rows(path: Path, fieldnames: list[str], rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def process_file(
    input_path: Path,
    output_path: Path,
    smooth_len: int = 5,
) -> tuple[bool, str]:
    if MAINTENANCE_MODE:
        try:
            _write_rows(output_path, ["Output"], [{"Output": MAINTENANCE_CONTACT_MESSAGE}])
        except Exception as exc:
            return False, f"{input_path.name}: write failed ({exc})"
        return True, MAINTENANCE_CONTACT_MESSAGE

    try:
        fieldnames, rows = _read_rows(input_path)
    except Exception as exc:
        return False, f"{input_path.name}: read failed ({exc})"

    if DI_PLUS_COL not in fieldnames or DI_MINUS_COL not in fieldnames:
        return False, f"{input_path.name}: skipped (missing {DI_PLUS_COL}/{DI_MINUS_COL})"

    enriched = enrich_rows(rows, smooth_len=smooth_len)

    ordered_fields = list(fieldnames)
    for name in (
        SLOPE_PLUS_COL,
        SLOPE_MINUS_COL,
        DL_PLUS_ANGLE_COL,
        DL_MINUS_ANGLE_COL,
        DELTA_ANGLE_COL,
    ):
        if name not in ordered_fields:
            ordered_fields.append(name)

    try:
        _write_rows(output_path, ordered_fields, enriched)
    except Exception as exc:
        return False, f"{input_path.name}: write failed ({exc})"

    return True, f"{input_path.name} -> {output_path}"


def parse_args() -> argparse.Namespace:
    default_input = str(Path(DATA_DIR))
    default_output = str(Path(DATA_DIR) / "delta")

    parser = argparse.ArgumentParser(description="Calculate DELTA_ANGLE from saved DI data.")
    parser.add_argument(
        "inputs",
        nargs="*",
        default=[default_input],
        help="CSV files, glob patterns, or directories to process. Defaults to the data folder.",
    )
    parser.add_argument(
        "--output-dir",
        default=default_output,
        help="Directory for enriched files. Default: data/delta",
    )
    parser.add_argument(
        "--smooth-len",
        type=int,
        default=5,
        help="SMA length used to smooth DL angles. Default: 5",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the source CSV instead of writing to output-dir.",
    )
    return parser.parse_args()


def main() -> int:
    if MAINTENANCE_MODE:
        print(MAINTENANCE_CONTACT_MESSAGE)
        return 0

    args = parse_args()

    files = [path for path in _iter_input_files(args.inputs) if path.suffix.lower() == ".csv"]
    if not files:
        print("No CSV files found.")
        return 1

    output_dir = Path(args.output_dir)
    processed = 0

    for input_path in files:
        output_path = input_path if args.in_place else output_dir / input_path.name
        ok, message = process_file(
            input_path=input_path,
            output_path=output_path,
            smooth_len=args.smooth_len,
        )
        print(message)
        if ok:
            processed += 1

    return 0 if processed else 1


if __name__ == "__main__":
    raise SystemExit(main())
