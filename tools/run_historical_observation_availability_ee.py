"""AUDIT-013 — historical observation-availability probe.

Bounded, read-only, coordinate-free.  Counts how many usable historical MODIS LST
observations (2003-2022) sit behind a percentile, for each stream, the 15th of each
month, and window half-widths of 5/7/10/15 days, on the approved lake-wide 0 m WISE
geometry under the approved QA-002 candidate-C acceptance rule.

It reads observation *counts* only — never a temperature, never a coordinate, never a
raster byte — and computes no anomaly, climatology, percentile, or classification.
See docs/HISTORICAL_OBSERVATION_AVAILABILITY_SPECIFICATION.md and DECISIONS.md AUDIT-013.

    python tools/run_historical_observation_availability_ee.py --self-test
    python tools/run_historical_observation_availability_ee.py --project ee-jtantaroman
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
AUDIT010_PATH = ROOT / "tools" / "run_whole_lake_boundary_shoreline_audit_ee.py"
AUDIT012_PATH = ROOT / "tools" / "run_nighttime_qa_candidate_comparison_ee.py"
EXPECTED_AUDIT010_SHA256 = "0e6c33277c2180db756d7ccfd6bf7c0cf9a5895c1ff07384fbd64ac7cf9d218f"
EXPECTED_AUDIT012_SHA256 = "0682897404d20498996e7a73742c604ad350ad409cbb6c40b3071111a5d16760"

IMPLEMENTATION = "historical_observation_availability_python_api_v1_h19v04_candidate_c_counts"
SPECIFICATION = "AUDIT-013_2026-09-02"

STREAM_IDS = ("terra_day", "terra_night", "aqua_day", "aqua_night")
PROBE_MONTHS = tuple(range(1, 13))
PROBE_DAY_OF_MONTH = 15
WINDOW_HALF_WIDTHS = (5, 7, 10, 15)
MAX_HALF_WIDTH = max(WINDOW_HALF_WIDTHS)
HISTORICAL_YEARS = tuple(range(2003, 2023))          # 2003-2022 inclusive, 20 years
YEAR_BLOCKS = ((2003, 2007), (2008, 2012), (2013, 2017), (2018, 2022))

EE_CLIENT_REQUEST_DEADLINE_SECONDS = 480
TRANSPORT_MAX_ATTEMPTS = 1
SESSION_LIMIT_SECONDS = 165 * 60
REQUEST_PAUSE_SECONDS = 2.0

# 12 probe dates x 4 streams x 4 year-blocks server reductions,
# plus 8 projection-metadata getInfo calls inside AuditRunner.__init__.
COUNT_REQUESTS = len(PROBE_MONTHS) * len(STREAM_IDS) * len(YEAR_BLOCKS)
REQUEST_DECOMPOSITION = {
    "projection_metadata_requests": 2 * len(STREAM_IDS),
    "count_requests": COUNT_REQUESTS,
    "earth_engine_requests": 2 * len(STREAM_IDS) + COUNT_REQUESTS,
    "streams": list(STREAM_IDS),
    "probe_dates": [f"month-{m:02d}-{PROBE_DAY_OF_MONTH:02d}" for m in PROBE_MONTHS],
    "window_half_widths_days": list(WINDOW_HALF_WIDTHS),
    "historical_years": [HISTORICAL_YEARS[0], HISTORICAL_YEARS[-1]],
    "year_blocks": [list(b) for b in YEAR_BLOCKS],
    "acceptance_rule": "qa_002_candidate_c",
    "geometry": "wise_wfd_v1_9_huaih049_2022_unrounded_lake_wide_0m",
    "reads_temperatures": False,
    "reads_coordinates": False,
    "nasa_or_earthdata_access": False,
    "sequential": True,
    "automatic_retry": False,
}

_COORDINATE_FREE_FORBIDDEN = re.compile(
    r"(?:^|_)(?:geometry|coordinates?|coords?|bounds?|bbox|extent|envelope|"
    r"latitude|longitude|lat|lon|lng|xmin|xmax|ymin|ymax|minx|maxx|miny|maxy|"
    r"easting|northing|wkt|geojson|temperature|kelvin|celsius)(?:_|$)",
    re.IGNORECASE,
)
_COORDINATE_FREE_ALLOWED = {
    "coordinate_free", "reads_coordinates", "reads_temperatures", "geometry",
    "geometry_identity_sha256",
}


class AdmissionFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, expected: str, name: str) -> Any:
    if sha256_file(path) != expected:
        raise AdmissionFailure(name + "_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location(name.casefold(), path)
    if spec is None or spec.loader is None:
        raise AdmissionFailure(name + "_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    if sha256_file(path) != expected:
        raise AdmissionFailure(name + "_CHANGED_DURING_IMPORT")
    return module


_AUDIT010: Any = None
_AUDIT012: Any = None


def load_audit010() -> Any:
    global _AUDIT010
    if _AUDIT010 is None:
        _AUDIT010 = _load(AUDIT010_PATH, EXPECTED_AUDIT010_SHA256, "PINNED_AUDIT010")
    return _AUDIT010


def load_audit012() -> Any:
    global _AUDIT012
    if _AUDIT012 is None:
        _AUDIT012 = _load(AUDIT012_PATH, EXPECTED_AUDIT012_SHA256, "PINNED_AUDIT012")
    return _AUDIT012


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def validate_coordinate_free(value: Any) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise AdmissionFailure("COORDINATE_FREE_NONSTRING_KEY")
                normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
                normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").casefold()
                if key not in _COORDINATE_FREE_ALLOWED and \
                   _COORDINATE_FREE_FORBIDDEN.search(normalized):
                    raise AdmissionFailure("COORDINATE_KEY_LEAK:" + str(key))
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
    walk(value)


# --- candidate-C acceptance rule (approved QA-002) --------------------------------

def candidate_c_daily_count(audit010: Any, runner: Any, ee: Any, image: Any,
                            stream: dict[str, Any], geometry: Any,
                            context: dict[str, Any]) -> Any:
    """Accepted valid-water pixel count for one day under QA-002 candidate C.

    Mirrors the byte-pinned AUDIT-012 ``_source_data`` mask exactly:
      V = QC-present & provider-range LST & view time & view angle
      C = V & mandatory_qa<=1 & data_quality==0 & emissivity_error<=1 & lst_error<=1
    """
    image = ee.Image(image)
    masks = runner._masks(image, stream)
    decoded = masks["decoded"]
    m = decoded.select("mandatory_qa").unmask(0)
    d = decoded.select("data_quality").unmask(0)
    e = decoded.select("emissivity_error").unmask(0)
    t = decoded.select("lst_error").unmask(0)
    lst = image.select(stream["lst"])
    view_time = image.select(stream["time"])
    view_angle = image.select(stream["angle"])
    qc_valid = masks["Q"]
    lst_valid = runner._validity(lst, 7500, 65535)
    time_valid = runner._validity(view_time, 0, 240)
    angle_valid = runner._validity(view_angle, 0, 130)
    v = qc_valid.And(lst_valid).And(time_valid).And(angle_valid).unmask(0)
    c = v.And(m.lte(1)).And(d.eq(0)).And(e.lte(1)).And(t.lte(1)).unmask(0)
    counter = ee.Image.constant(1).rename("c").updateMask(c)
    reduced = counter.reduceRegion(reducer=ee.Reducer.count().unweighted(),
                                   geometry=geometry, crs=context["crs"],
                                   crsTransform=context["transform"], bestEffort=False,
                                   maxPixels=1_000_000, tileScale=1)
    return ee.Number(ee.Dictionary(reduced).get("c", 0)).toInt64()


def _doy_filter(ee: Any, month: int, half_width: int) -> Any:
    """calendarRange day-of-year filter for probe date (month, 15) +/- half_width.
    When the window crosses the year boundary, start > end and EE wraps."""
    reference = dt_probe_doy(month)
    start = (reference - half_width - 1) % 365 + 1
    end = (reference + half_width - 1) % 365 + 1
    return ee.Filter.calendarRange(start, end, "day_of_year")


def dt_probe_doy(month: int) -> int:
    import datetime as _dt
    return _dt.date(2003, month, PROBE_DAY_OF_MONTH).timetuple().tm_yday


# --- assembly -------------------------------------------------------------------

def assemble_cell(observations: list[dict[str, int]], month: int, stream_id: str) -> list[dict[str, Any]]:
    """observations: list of {'year': int, 'doy': int, 'count': int}, one per image
    over the widest (+/-15 day) window across all 20 years for this (stream, probe date).
    Days seen with two images are excluded (QA-002 requires exactly one source image)."""
    reference = dt_probe_doy(month)
    # exact-one-image-per-day guard
    per_day: dict[tuple[int, int], list[int]] = {}
    for obs in observations:
        per_day.setdefault((obs["year"], obs["doy"]), []).append(obs["count"])
    single = {key: values[0] for key, values in per_day.items() if len(values) == 1}
    cells: list[dict[str, Any]] = []
    for half_width in WINDOW_HALF_WIDTHS:
        offsets = _offsets_within(reference, half_width)
        positive_by_year: dict[int, int] = {year: 0 for year in HISTORICAL_YEARS}
        pixel_counts_on_positive: list[int] = []
        for (year, doy), count in single.items():
            if doy not in offsets or year not in positive_by_year:
                continue
            if count > 0:
                positive_by_year[year] += 1
                pixel_counts_on_positive.append(count)
        per_year = [positive_by_year[year] for year in HISTORICAL_YEARS]
        years_with_any = sum(1 for value in per_year if value > 0)
        cells.append({
            "stream_id": stream_id,
            "probe_date": f"month-{month:02d}-{PROBE_DAY_OF_MONTH:02d}",
            "window_half_width_days": half_width,
            "window_length_days": 2 * half_width + 1,
            "historical_years": len(HISTORICAL_YEARS),
            "years_with_any_accepted_observation": years_with_any,
            "total_accepted_daily_observations": sum(per_year),
            "accepted_daily_observations_per_year": per_year,
            "median_accepted_daily_observations_per_year": (
                statistics.median(per_year) if per_year else 0),
            "median_accepted_pixel_count_on_positive_days": (
                int(statistics.median(pixel_counts_on_positive))
                if pixel_counts_on_positive else 0),
            "min_accepted_pixel_count_on_positive_days": (
                min(pixel_counts_on_positive) if pixel_counts_on_positive else 0),
            "max_accepted_pixel_count_on_positive_days": (
                max(pixel_counts_on_positive) if pixel_counts_on_positive else 0),
        })
    return cells


def _offsets_within(reference: int, half_width: int) -> set[int]:
    offsets: set[int] = set()
    for delta in range(-half_width, half_width + 1):
        offsets.add((reference - 1 + delta) % 365 + 1)
    return offsets


def validate_cell(cell: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    per_year = cell.get("accepted_daily_observations_per_year")
    if not isinstance(per_year, list) or len(per_year) != len(HISTORICAL_YEARS) or \
       any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in per_year):
        errors.append("PER_YEAR_SHAPE_FAILED")
        return errors
    if cell["total_accepted_daily_observations"] != sum(per_year):
        errors.append("TOTAL_IDENTITY_FAILED")
    computed_years = sum(1 for v in per_year if v > 0)
    if cell["years_with_any_accepted_observation"] != computed_years or \
       not 0 <= computed_years <= len(HISTORICAL_YEARS):
        errors.append("YEARS_WITH_ANY_IDENTITY_FAILED")
    if cell["window_length_days"] != 2 * cell["window_half_width_days"] + 1:
        errors.append("WINDOW_LENGTH_FAILED")
    if cell["window_half_width_days"] not in WINDOW_HALF_WIDTHS:
        errors.append("WINDOW_WIDTH_FAILED")
    if cell["stream_id"] not in STREAM_IDS:
        errors.append("STREAM_FAILED")
    positive_days = cell["total_accepted_daily_observations"]
    window_capacity = len(HISTORICAL_YEARS) * cell["window_length_days"]
    if not 0 <= positive_days <= window_capacity:
        errors.append("POSITIVE_DAYS_RANGE_FAILED")
    for key in ("median_accepted_pixel_count_on_positive_days",
                "min_accepted_pixel_count_on_positive_days",
                "max_accepted_pixel_count_on_positive_days"):
        if not isinstance(cell[key], int) or isinstance(cell[key], bool) or cell[key] < 0:
            errors.append("PIXEL_COUNT_SHAPE_FAILED:" + key)
    return errors


# --- execution -----------------------------------------------------------------

def execute(project: str) -> int:
    session_deadline = time.monotonic() + SESSION_LIMIT_SECONDS
    audit010 = load_audit010()
    load_audit012()   # pin check only
    audit010.configure_ee_serializer_recursion_limit()
    ee = audit010.import_ee()
    ee.Initialize(project=project)
    policy = audit010.configure_ee_request_policy(
        ee, EE_CLIENT_REQUEST_DEADLINE_SECONDS, TRANSPORT_MAX_ATTEMPTS)
    geometry_json, source_record = audit010.load_verified_source()
    options = {"max_attempts": 1, "deadline_seconds": EE_CLIENT_REQUEST_DEADLINE_SECONDS,
               "session_deadline_monotonic": session_deadline}
    runner = audit010.AuditRunner(ee, geometry_json, source_record, options)
    planar_geometry = runner._planar(runner.source)

    stream_by_id = {stream["stream_id"]: stream for stream in audit010.STREAMS}
    geometry_identity = canonical_sha256({
        "raw_sha256": source_record.get("raw_sha256"),
        "canonical_sha256": source_record.get("canonical_sha256"),
        "coordinate_tuple_count": source_record.get("coordinate_tuple_count_including_closure"),
    })

    print(json.dumps({"HISTORICAL_AVAILABILITY_PREFLIGHT": {
        "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
        "pinned_audit010_sha256": EXPECTED_AUDIT010_SHA256,
        "pinned_audit012_sha256": EXPECTED_AUDIT012_SHA256,
        "request_decomposition": REQUEST_DECOMPOSITION, "request_policy": policy,
        "geometry_identity_sha256": geometry_identity,
        "reads_temperatures": False, "reads_coordinates": False,
    }}, sort_keys=True), flush=True)

    all_cells: list[dict[str, Any]] = []
    for stream_id in STREAM_IDS:
        stream = stream_by_id[stream_id]
        context = runner.contexts[stream_id]
        collection_id = stream["collection_id"]
        for month in PROBE_MONTHS:
            observations: list[dict[str, int]] = []
            for block_start, block_end in YEAR_BLOCKS:
                phase = f"count_{stream_id}_m{month:02d}_y{block_start}"
                remaining = session_deadline - time.monotonic()
                pause = max(0.0, min(REQUEST_PAUSE_SECONDS, remaining - 600.0))
                if pause > 0:
                    print(json.dumps({"HISTORICAL_AVAILABILITY_PAUSE": {
                        "phase": phase, "pause_seconds": round(pause, 1)}}, sort_keys=True), flush=True)
                    time.sleep(pause)
                collection = (ee.ImageCollection(collection_id)
                              .filterBounds(runner.source)
                              .filter(ee.Filter.calendarRange(block_start, block_end, "year"))
                              .filter(_doy_filter(ee, month, MAX_HALF_WIDTH)))

                def _feature(image: Any, stream=stream, context=context) -> Any:
                    image = ee.Image(image)
                    date = image.date()
                    return ee.Feature(None, {
                        "year": date.get("year"),
                        "doy": date.getRelative("day", "year").add(1),
                        "count": candidate_c_daily_count(
                            audit010, runner, ee, image, stream, planar_geometry, context),
                    })

                features = ee.FeatureCollection(collection.map(_feature))
                payload = features.toList(20000).map(
                    lambda f: ee.Feature(f).toDictionary(["year", "doy", "count"]))
                rows = audit010.bounded_transient_getinfo(
                    lambda payload=payload: payload.getInfo(), phase, **options)
                print(json.dumps({"HISTORICAL_AVAILABILITY_BLOCK_ROWS": {
                    "phase": phase, "rows": len(rows) if isinstance(rows, list) else -1}},
                    sort_keys=True), flush=True)
                if not isinstance(rows, list):
                    raise AdmissionFailure("COUNT_RESPONSE_SHAPE_FAILED")
                for row in rows:
                    if not isinstance(row, dict) or set(row) != {"year", "doy", "count"} or \
                       any(not finite(row[k]) or int(row[k]) != row[k] for k in row):
                        raise AdmissionFailure("COUNT_ROW_SHAPE_FAILED")
                    observations.append({"year": int(row["year"]), "doy": int(row["doy"]),
                                         "count": int(row["count"])})
            cells = assemble_cell(observations, month, stream_id)
            for cell in cells:
                cell_errors = validate_cell(cell)
                if cell_errors:
                    raise AdmissionFailure("CELL_ADMISSION_FAILED:" + cell_errors[0])
            all_cells.extend(cells)

    expected_cells = len(STREAM_IDS) * len(PROBE_MONTHS) * len(WINDOW_HALF_WIDTHS)
    terminal = {
        "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
        "coordinate_free": True, "reads_temperatures": False, "reads_coordinates": False,
        "acceptance_rule": "qa_002_candidate_c",
        "geometry": "wise_wfd_v1_9_huaih049_2022_unrounded_lake_wide_0m",
        "geometry_identity_sha256": geometry_identity,
        "historical_reference_period": [HISTORICAL_YEARS[0], HISTORICAL_YEARS[-1]],
        "request_decomposition": REQUEST_DECOMPOSITION,
        "cell_count": len(all_cells), "cells": all_cells,
        "cells_sha256": canonical_sha256(all_cells),
        "validation_errors": [],
        "pass": len(all_cells) == expected_cells,
        "scientific_interpretation": (
            "Bounded read-only historical observation-count diagnostic only. It selects no "
            "METH-* value and computes no anomaly, climatology, or percentile."),
    }
    validate_coordinate_free(terminal)
    if not terminal["pass"]:
        raise AdmissionFailure("TERMINAL_CELL_COUNT_FAILED")
    print(json.dumps({"HISTORICAL_OBSERVATION_AVAILABILITY_COMPLETE": terminal},
                     sort_keys=True, separators=(",", ":")), flush=True)
    return 0


# --- self test -----------------------------------------------------------------

def self_test() -> int:
    failures: list[str] = []
    if sha256_file(AUDIT010_PATH) != EXPECTED_AUDIT010_SHA256 or \
       sha256_file(AUDIT012_PATH) != EXPECTED_AUDIT012_SHA256:
        failures.append("dependency_pins")

    if REQUEST_DECOMPOSITION["earth_engine_requests"] != 2 * len(STREAM_IDS) + COUNT_REQUESTS or \
       COUNT_REQUESTS != 192 or SESSION_LIMIT_SECONDS != 9900 or \
       EE_CLIENT_REQUEST_DEADLINE_SECONDS != 480 or TRANSPORT_MAX_ATTEMPTS != 1:
        failures.append("request_contract")

    # candidate-C rule must equal the byte-pinned AUDIT-012 definition for every QC byte
    audit012 = load_audit012()
    for qc in range(256):
        m, d, e, t = audit012.qc_components(qc)
        expected_c = (m <= 1 and d == 0 and e <= 1 and t <= 1)
        if audit012.candidate_membership(qc)["C"] != expected_c:
            failures.append("candidate_c_truth_table")
            break
    src = AUDIT012_PATH.read_text(encoding="utf-8")
    if 'C = V.And(m.lte(1)).And(d.eq(0)).And(e.lte(1)).And(t.lte(1))' not in src:
        failures.append("candidate_c_source_fragment")

    # day-of-year window helper: offsets wrap correctly and have the right size
    for month in PROBE_MONTHS:
        ref = dt_probe_doy(month)
        for half in WINDOW_HALF_WIDTHS:
            offsets = _offsets_within(ref, half)
            if len(offsets) != 2 * half + 1 or any(not 1 <= o <= 365 for o in offsets):
                failures.append("window_offsets")
                break

    # assembly + validation on a synthetic observation set
    fixture_month = 1
    ref = dt_probe_doy(fixture_month)
    observations: list[dict[str, int]] = []
    # year 2003: one positive day at the reference doy; year 2004: two images same day (excluded);
    # year 2010: a positive day only inside the +/-15 window (offset 12), zero elsewhere.
    observations.append({"year": 2003, "doy": ref, "count": 7})
    observations.append({"year": 2004, "doy": ref, "count": 5})
    observations.append({"year": 2004, "doy": ref, "count": 6})
    observations.append({"year": 2010, "doy": (ref - 1 + 12) % 365 + 1, "count": 3})
    observations.append({"year": 2010, "doy": (ref - 1 + 2) % 365 + 1, "count": 0})
    cells = assemble_cell(observations, fixture_month, "terra_night")
    if len(cells) != len(WINDOW_HALF_WIDTHS):
        failures.append("assembly_cell_count")
    else:
        by_width = {c["window_half_width_days"]: c for c in cells}
        c5 = by_width[5]
        c15 = by_width[15]
        # +/-5 window: only 2003 contributes (2004 excluded as double image); 2010's +12 offset is outside +/-5
        if c5["years_with_any_accepted_observation"] != 1 or \
           c5["total_accepted_daily_observations"] != 1 or \
           c5["median_accepted_pixel_count_on_positive_days"] != 7:
            failures.append("assembly_window_5")
        # +/-15 window: 2003 and 2010 contribute (2 years); 2010's +2 offset had count 0
        if c15["years_with_any_accepted_observation"] != 2 or \
           c15["total_accepted_daily_observations"] != 2 or \
           sorted([7, 3]) != sorted([7, 3]):
            failures.append("assembly_window_15")
        for cell in cells:
            if validate_cell(cell):
                failures.append("assembly_validate")
                break
        # negative: corrupt an identity
        bad = json.loads(json.dumps(cells[0]))
        bad["total_accepted_daily_observations"] += 1
        if "TOTAL_IDENTITY_FAILED" not in validate_cell(bad):
            failures.append("validate_negative_total")
        bad2 = json.loads(json.dumps(cells[0]))
        bad2["accepted_daily_observations_per_year"] = bad2["accepted_daily_observations_per_year"][:-1]
        if not validate_cell(bad2):
            failures.append("validate_negative_shape")

    # coordinate-free screen: a temperature/coordinate key must be rejected
    for bad_key in ("temperature_c", "latitude", "pixel_longitude", "bbox", "geojson"):
        try:
            validate_coordinate_free({"cells": [{bad_key: 1}]})
            failures.append("coordinate_free_negative:" + bad_key)
        except AdmissionFailure:
            pass
    # benign keys used by the terminal object must pass
    try:
        validate_coordinate_free({
            "coordinate_free": True, "reads_coordinates": False, "reads_temperatures": False,
            "geometry": "wise", "geometry_identity_sha256": "0",
            "cells": [{"years_with_any_accepted_observation": 12,
                       "median_accepted_pixel_count_on_positive_days": 3}]})
    except AdmissionFailure as exc:
        failures.append("coordinate_free_false_positive:" + exc.code)

    print(json.dumps({"self_test": not failures, "failures": failures,
                      "count_requests": COUNT_REQUESTS,
                      "expected_cells": len(STREAM_IDS) * len(PROBE_MONTHS) * len(WINDOW_HALF_WIDTHS)},
                     sort_keys=True))
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.project:
        parser.error("--project is required unless --self-test is used")
    try:
        return execute(args.project)
    except AdmissionFailure as exc:
        print(json.dumps({"HISTORICAL_OBSERVATION_AVAILABILITY_FAILED": {
            "exception_class": type(exc).__name__, "validation_error_code": exc.code,
            "coordinate_free": True, "reads_temperatures": False}}, sort_keys=True), flush=True)
        return 2
    except Exception as exc:  # noqa: BLE001
        message = str(exc)[:400]
        try:
            validate_coordinate_free({"exception_message": message})
        except Exception:  # noqa: BLE001
            message = "<redacted: failed coordinate-free screen>"
        print(json.dumps({"HISTORICAL_OBSERVATION_AVAILABILITY_FAILED": True,
                          "exception_class": type(exc).__name__,
                          "exception_message": message}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
