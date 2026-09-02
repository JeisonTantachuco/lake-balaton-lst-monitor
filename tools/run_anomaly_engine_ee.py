"""Phase 3 — Lake Balaton anomaly engine.

Coordinate-free. Turns the approved decisions (SPACE-001, QA-002, METH-001..006) into
the "is this temperature unusual?" computation:

  --build-climatology : one per-day lake value for every day 2003-2022 (4 streams),
                        then the +/-5-day day-of-year baseline (median + mean + sorted
                        list for Type-7 percentiles). Writes artefacts 0 and 1.
  --daily-records     : anomaly records for monitoring dates (default 2023-01-01..today)
                        against the baseline. Writes artefact 2.
  --monthly           : stream-specific monthly summaries from the daily records.
                        Writes artefact 3.
  --self-test         : offline; no Earth Engine, no network, no filesystem mutation.

Reads observation values and counts only -- never a coordinate, never a raster byte.
See docs/PHASE_3_ANOMALY_ENGINE_SPECIFICATION.md and DECISIONS.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
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

IMPLEMENTATION = "anomaly_engine_python_api_v1_lake_wide_candidate_c"
SPECIFICATION = "PHASE-3_2026-09-02"

STREAM_IDS = ("terra_day", "terra_night", "aqua_day", "aqua_night")
HISTORICAL_YEARS = tuple(range(2003, 2023))          # 2003-2022 inclusive
WINDOW_HALF_WIDTH_DAYS = 5                            # METH-001
DAYS_IN_YEAR = 366                                   # 29 Feb folds to day 60 (28 Feb)
CONFIDENCE_OK_FRACTION = 0.15                        # QA-002 provisional
MONTHLY_MIN_VALID_DAYS = 3                           # QA-002 / METH-005
PERCENTILE_MIN_N = 10                                # METH-003
PERCENTILE_FULL_N = 20                               # METH-003
WARM_PERCENTILE = 90.0                               # METH-004
LABEL_BREAKS = ((10.0, "below normal"), (90.0, "within normal range"),
                (95.0, "warm"), (99.0, "unusually warm"))
LABEL_TOP = "extreme warm observation"

EE_CLIENT_REQUEST_DEADLINE_SECONDS = 480
TRANSPORT_MAX_ATTEMPTS = 1
SESSION_LIMIT_SECONDS = 165 * 60
REQUEST_PAUSE_SECONDS = 2.0
HALF_YEAR_BLOCKS = ((1, 1), (7, 12))                 # (start_month, end_month) per year
STATE_DIR = ROOT / "local_run_state" / "phase3"

# The approved geometry (SPACE-001 / AUDIT-003) — its exact identity is pinned here so
# the anomaly engine can reuse a locally cached verified copy without re-fetching the
# provenance chain from the EEA servers on every run. A full live verification still
# runs whenever the cache is absent.
PINNED_SOURCE_IDENTITY = {
    "raw_sha256": "5d5f9c8edfced710fcc8657a6aceb398f14cd815d1c5e41a7df9f00601f312d8",
    "canonical_sha256": "394a929617bb975d2f3e3aa627abe26dbcc98f42fa48fe038757b3e734c35020",
    "coordinate_tuple_count_including_closure": 11012,
}
VERIFIED_SOURCE_CACHE = STATE_DIR / "verified_source_cache.json"

_FORBIDDEN = re.compile(
    r"(?:^|_)(?:geometry|coordinates?|coords?|bounds?|bbox|extent|envelope|"
    r"latitude|longitude|lat|lon|lng|xmin|xmax|ymin|ymax|minx|maxx|miny|maxy|"
    r"easting|northing|wkt|geojson)(?:_|$)", re.IGNORECASE)
_ALLOWED_KEYS = {"coordinate_free", "reads_coordinates", "geometry", "geometry_identity_sha256"}


class EngineFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_coordinate_free(value: Any) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise EngineFailure("COORDINATE_FREE_NONSTRING_KEY")
                normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
                normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").casefold()
                if key not in _ALLOWED_KEYS and _FORBIDDEN.search(normalized):
                    raise EngineFailure("COORDINATE_KEY_LEAK:" + key)
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
    walk(value)


def _load(path: Path, expected: str, name: str) -> Any:
    if sha256_file(path) != expected:
        raise EngineFailure(name + "_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location(name.casefold(), path)
    if spec is None or spec.loader is None:
        raise EngineFailure(name + "_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    if sha256_file(path) != expected:
        raise EngineFailure(name + "_CHANGED_DURING_IMPORT")
    return module


_AUDIT010: Any = None


def load_audit010() -> Any:
    global _AUDIT010
    if _AUDIT010 is None:
        _AUDIT010 = _load(AUDIT010_PATH, EXPECTED_AUDIT010_SHA256, "PINNED_AUDIT010")
    return _AUDIT010


# --- pure method functions (offline-testable) -----------------------------------

def fold_day_of_year(month: int, day: int) -> int:
    """1..366 day-of-year in a leap frame, with 29 Feb folded onto 28 Feb (day 59)."""
    doy = dt.date(2004, month, day).timetuple().tm_yday   # 2004 is a leap year
    if month == 2 and day == 29:
        return 59
    return doy


def window_offsets(reference_doy: int, half_width: int = WINDOW_HALF_WIDTH_DAYS) -> set[int]:
    return {((reference_doy - 1 + delta) % DAYS_IN_YEAR) + 1
            for delta in range(-half_width, half_width + 1)}


def type7_percentile_rank(sorted_values: list[float], x: float) -> float:
    """Percentile (0..100) of x within sorted_values: the value p for which the
    Type-7 quantile Q(p) (h = (n-1)p, linear interpolation between order statistics)
    equals x. Ties on a plateau use the plateau midpoint; x outside the sample
    range returns 0 or 100."""
    import bisect
    n = len(sorted_values)
    if n == 0:
        raise EngineFailure("PERCENTILE_EMPTY_SAMPLE")
    if n == 1:
        return 50.0
    if x <= sorted_values[0]:
        return 0.0
    if x >= sorted_values[-1]:
        return 100.0
    lo = bisect.bisect_left(sorted_values, x)
    hi = bisect.bisect_right(sorted_values, x)
    if lo < hi:                       # x equals one or more sample values
        h = (lo + hi - 1) / 2.0
    else:                            # x strictly between two adjacent samples
        i = lo - 1
        h = i + (x - sorted_values[i]) / (sorted_values[i + 1] - sorted_values[i])
    return 100.0 * h / (n - 1)


def classify(percentile: float | None) -> str:
    if percentile is None:
        return "historical context unavailable"
    for threshold, label in LABEL_BREAKS:
        if percentile < threshold:
            return label
    return LABEL_TOP


def confidence_from_fraction(fraction: float) -> str:
    if fraction <= 0:
        return "none"
    return "ok" if fraction >= CONFIDENCE_OK_FRACTION else "low"


def assemble_baseline(daily_values: list[dict[str, Any]], eligible_counts: dict[str, int]
                      ) -> list[dict[str, Any]]:
    """daily_values: [{stream_id, date_utc, daily_lst_c, accepted_pixel_count}] for
    historical days with >=1 accepted pixel. One row per (stream, day-of-year)."""
    by_stream: dict[str, list[dict[str, Any]]] = {s: [] for s in STREAM_IDS}
    for value in daily_values:
        by_stream[value["stream_id"]].append(value)
    rows: list[dict[str, Any]] = []
    for stream_id in STREAM_IDS:
        eligible = eligible_counts[stream_id]
        # index this stream's days by day-of-year
        by_doy: dict[int, list[dict[str, Any]]] = {}
        for value in by_stream[stream_id]:
            date = dt.date.fromisoformat(value["date_utc"])
            by_doy.setdefault(fold_day_of_year(date.month, date.day), []).append(value)
        for reference_doy in range(1, DAYS_IN_YEAR + 1):
            offsets = window_offsets(reference_doy)
            contributing = [v for doy in offsets for v in by_doy.get(doy, [])]
            temps = sorted(round(v["daily_lst_c"], 4) for v in contributing)
            n = len(temps)
            n_by_year = [0] * len(HISTORICAL_YEARS)
            for v in contributing:
                year = dt.date.fromisoformat(v["date_utc"]).year
                n_by_year[year - HISTORICAL_YEARS[0]] += 1
            fractions = sorted(v["accepted_pixel_count"] / eligible for v in contributing) \
                if eligible else []
            row: dict[str, Any] = {
                "stream_id": stream_id, "day_of_year": reference_doy, "n": n,
                "n_by_year": n_by_year, "sorted_daily_lst_c": temps,
            }
            if n:
                row["median_lst_c"] = round(statistics.median(temps), 4)
                row["mean_lst_c"] = round(statistics.fmean(temps), 4)
                row["sd_lst_c"] = round(statistics.pstdev(temps), 4) if n > 1 else 0.0
                row["median_minus_mean_c"] = round(row["median_lst_c"] - row["mean_lst_c"], 4)
                row["median_valid_water_fraction"] = round(
                    statistics.median(fractions), 4) if fractions else None
            else:
                for key in ("median_lst_c", "mean_lst_c", "sd_lst_c",
                            "median_minus_mean_c", "median_valid_water_fraction"):
                    row[key] = None
            rows.append(row)
    return rows


def anomaly_record(daily: dict[str, Any], baseline_row: dict[str, Any]) -> dict[str, Any]:
    """daily: {stream_id, date_utc, daily_lst_c|None, valid_water_fraction, accepted_pixel_count,
    eligible_pixel_count}. baseline_row: one assemble_baseline row for the matched day-of-year."""
    confidence = confidence_from_fraction(daily["valid_water_fraction"])
    record: dict[str, Any] = {
        "stream_id": daily["stream_id"], "date_utc": daily["date_utc"],
        "day_of_year": baseline_row["day_of_year"],
        "daily_lst_c": daily["daily_lst_c"],
        "valid_water_fraction": round(daily["valid_water_fraction"], 4),
        "accepted_pixel_count": daily["accepted_pixel_count"],
        "confidence": confidence,
        "historical_n": baseline_row["n"],
        "reference_median_lst_c": baseline_row["median_lst_c"],
        "reference_mean_lst_c": baseline_row["mean_lst_c"],
        "reference_sd_lst_c": baseline_row["sd_lst_c"],
        "reference_median_minus_mean_c": baseline_row["median_minus_mean_c"],
    }
    if confidence == "none" or daily["daily_lst_c"] is None:
        record.update({"anomaly_vs_median_c": None, "anomaly_vs_mean_c": None,
                       "historical_percentile": None,
                       "percentile_confidence": "no_valid_observation",
                       "classification": "no valid observation"})
        return record
    if baseline_row["n"] and baseline_row["median_lst_c"] is not None:
        record["anomaly_vs_median_c"] = round(daily["daily_lst_c"] - baseline_row["median_lst_c"], 4)
        record["anomaly_vs_mean_c"] = round(daily["daily_lst_c"] - baseline_row["mean_lst_c"], 4)
    else:
        record["anomaly_vs_median_c"] = None
        record["anomaly_vs_mean_c"] = None
    n = baseline_row["n"]
    if n >= PERCENTILE_MIN_N:
        percentile = round(type7_percentile_rank(baseline_row["sorted_daily_lst_c"],
                                                 daily["daily_lst_c"]), 3)
        record["historical_percentile"] = percentile
        record["percentile_confidence"] = (
            "full" if n >= PERCENTILE_FULL_N else "limited_historical_sample")
        record["classification"] = classify(percentile)
    else:
        record["historical_percentile"] = None
        record["percentile_confidence"] = "insufficient_history"
        record["classification"] = classify(None)
    return record


def assemble_monthly(daily_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in daily_records:
        month_key = record["date_utc"][:7]
        groups.setdefault((record["stream_id"], month_key), []).append(record)
    rows: list[dict[str, Any]] = []
    for (stream_id, month_key), records in sorted(groups.items()):
        year, month = int(month_key[:4]), int(month_key[5:7])
        calendar_days = (dt.date(year + (month == 12), (month % 12) + 1, 1)
                         - dt.date(year, month, 1)).days
        qualifying = [r for r in records if r["confidence"] in ("ok", "low")
                      and r["daily_lst_c"] is not None]
        row: dict[str, Any] = {
            "stream_id": stream_id, "month": month_key,
            "calendar_day_count": calendar_days,
            "valid_day_count": len(qualifying),
            "missing_or_cloud_fraction": round(1 - len(qualifying) / calendar_days, 4),
        }
        if len(qualifying) < MONTHLY_MIN_VALID_DAYS:
            row["state"] = "insufficient valid observations"
            rows.append(row)
            continue
        temps = [r["daily_lst_c"] for r in qualifying]
        anomalies_median = [r["anomaly_vs_median_c"] for r in qualifying
                            if r["anomaly_vs_median_c"] is not None]
        anomalies_mean = [r["anomaly_vs_mean_c"] for r in qualifying
                          if r["anomaly_vs_mean_c"] is not None]
        with_percentile = [r for r in qualifying if r["historical_percentile"] is not None]
        warm = [r for r in with_percentile if r["historical_percentile"] >= WARM_PERCENTILE]
        hottest = max(qualifying, key=lambda r: r["daily_lst_c"])
        row.update({
            "state": "reported",
            "monthly_mean_lst_c": round(statistics.fmean(temps), 4),
            "monthly_mean_anomaly_vs_median_c": (
                round(statistics.fmean(anomalies_median), 4) if anomalies_median else None),
            "monthly_mean_anomaly_vs_mean_c": (
                round(statistics.fmean(anomalies_mean), 4) if anomalies_mean else None),
            "hottest_observation_date": hottest["date_utc"],
            "hottest_observation_lst_c": hottest["daily_lst_c"],
            "warm_observation_count": len(warm),
            "days_with_a_percentile": len(with_percentile),
        })
        if anomalies_median:
            peak = max((r for r in qualifying if r["anomaly_vs_median_c"] is not None),
                       key=lambda r: r["anomaly_vs_median_c"])
            row["max_anomaly_vs_median_date"] = peak["date_utc"]
            row["max_anomaly_vs_median_c"] = peak["anomaly_vs_median_c"]
        rows.append(row)
    return rows


# --- Earth Engine: one per-day lake value --------------------------------------

def _per_day_feature(audit010: Any, runner: Any, ee: Any, image: Any, stream: dict[str, Any],
                     geometry: Any, context: dict[str, Any]) -> Any:
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
    v = (masks["Q"].And(runner._validity(lst, 7500, 65535))
         .And(runner._validity(view_time, 0, 240)).And(runner._validity(view_angle, 0, 130)))
    c = v.And(m.lte(1)).And(d.eq(0)).And(e.lte(1)).And(t.lte(1)).unmask(0)
    lst_c = lst.multiply(0.02).subtract(273.15)
    area = ee.Image.pixelArea()
    stacked = ee.Image.cat([
        lst_c.multiply(area).rename("weighted_sum"),
        area.rename("area_sum"),
        ee.Image.constant(1).rename("accepted_count"),
    ]).updateMask(c)
    reduced = ee.Dictionary(stacked.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geometry, crs=context["crs"],
        crsTransform=context["transform"], bestEffort=False, maxPixels=2_000_000, tileScale=1))
    return ee.Feature(None, {
        "date_utc": image.date().format("YYYY-MM-dd"),
        "weighted_sum": ee.Number(reduced.get("weighted_sum", 0)),
        "area_sum": ee.Number(reduced.get("area_sum", 0)),
        "accepted_count": ee.Number(reduced.get("accepted_count", 0)).toInt64(),
    })


def _source_identity_matches_pin(record: dict[str, Any]) -> bool:
    return all(record.get(key) == value for key, value in PINNED_SOURCE_IDENTITY.items())


def load_verified_source_cached(audit010: Any) -> tuple[Any, dict[str, Any]]:
    """Reuse a locally cached, hash-pinned verified copy of the approved geometry when
    present; otherwise run the full live verification and cache its result. The cache is
    trusted only when its recorded identity matches the AUDIT-003 pins exactly."""
    if VERIFIED_SOURCE_CACHE.exists():
        cached = json.loads(VERIFIED_SOURCE_CACHE.read_text(encoding="utf-8"))
        record = cached.get("source_record", {})
        if _source_identity_matches_pin(record) and \
           canonical_sha256(cached.get("geometry_json")) == cached.get("geometry_json_sha256"):
            print(json.dumps({"ANOMALY_ENGINE_SOURCE": {
                "mode": "cached_hash_pinned",
                "canonical_sha256": record["canonical_sha256"]}}, sort_keys=True), flush=True)
            return cached["geometry_json"], record
        raise EngineFailure("VERIFIED_SOURCE_CACHE_IDENTITY_MISMATCH")
    geometry_json, source_record = audit010.load_verified_source()
    if not _source_identity_matches_pin(source_record):
        raise EngineFailure("VERIFIED_SOURCE_IDENTITY_DOES_NOT_MATCH_AUDIT003_PIN")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    VERIFIED_SOURCE_CACHE.write_text(json.dumps({
        "note": "hash-pinned cache of the AUDIT-003 verified WISE HUAIH049 2022 geometry",
        "geometry_json": geometry_json, "source_record": source_record,
        "geometry_json_sha256": canonical_sha256(geometry_json),
    }, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"ANOMALY_ENGINE_SOURCE": {
        "mode": "live_verified_and_cached",
        "canonical_sha256": source_record["canonical_sha256"]}}, sort_keys=True), flush=True)
    return geometry_json, source_record


def _init_ee(project: str) -> tuple[Any, Any, Any, Any, dict[str, Any]]:
    audit010 = load_audit010()
    audit010.configure_ee_serializer_recursion_limit()
    ee = audit010.import_ee()
    ee.Initialize(project=project)
    policy = audit010.configure_ee_request_policy(
        ee, EE_CLIENT_REQUEST_DEADLINE_SECONDS, TRANSPORT_MAX_ATTEMPTS)
    geometry_json, source_record = load_verified_source_cached(audit010)
    session_deadline = time.monotonic() + SESSION_LIMIT_SECONDS
    options = {"max_attempts": 1, "deadline_seconds": EE_CLIENT_REQUEST_DEADLINE_SECONDS,
               "session_deadline_monotonic": session_deadline}
    runner = audit010.AuditRunner(ee, geometry_json, source_record, options)
    context = {"ee": ee, "audit010": audit010, "runner": runner, "options": options,
               "session_deadline": session_deadline, "policy": policy,
               "geometry": runner._planar(runner.source),
               "stream_by_id": {s["stream_id"]: s for s in audit010.STREAMS},
               "source_record": source_record}
    return ee, audit010, runner, geometry_json, context


def _eligible_counts(context: dict[str, Any]) -> dict[str, int]:
    ee, audit010, runner = context["ee"], context["audit010"], context["runner"]
    counts: dict[str, int] = {}
    for stream_id in STREAM_IDS:
        ctx = runner.contexts[stream_id]
        image = ee.Image.constant(1).rename("eligible")
        reduced = ee.Dictionary(image.reduceRegion(
            reducer=ee.Reducer.count().unweighted(), geometry=context["geometry"],
            crs=ctx["crs"], crsTransform=ctx["transform"], bestEffort=False,
            maxPixels=2_000_000, tileScale=1))
        counts[stream_id] = int(audit010.bounded_transient_getinfo(
            lambda reduced=reduced: ee.Number(reduced.get("eligible", 0)).toInt64().getInfo(),
            f"eligible_count_{stream_id}", **context["options"]))
    return counts


def _collect_daily_values(context: dict[str, Any], years: "list[int]") -> list[dict[str, Any]]:
    ee, audit010, runner = context["ee"], context["audit010"], context["runner"]
    values: list[dict[str, Any]] = []
    for stream_id in STREAM_IDS:
        stream = context["stream_by_id"][stream_id]
        ctx = runner.contexts[stream_id]
        for year in years:
            for start_month, end_month in HALF_YEAR_BLOCKS:
                phase = f"daily_{stream_id}_{year}_h{start_month}"
                remaining = context["session_deadline"] - time.monotonic()
                pause = max(0.0, min(REQUEST_PAUSE_SECONDS, remaining - 600.0))
                if pause > 0:
                    time.sleep(pause)
                start = ee.Date.fromYMD(year, start_month, 1)
                end = ee.Date.fromYMD(year, end_month, 1).advance(1, "month")
                collection = (ee.ImageCollection(stream["collection_id"])
                              .filterBounds(runner.source).filterDate(start, end))

                def _feature(image: Any, stream=stream, ctx=ctx) -> Any:
                    return _per_day_feature(audit010, runner, ee, image, stream,
                                            context["geometry"], ctx)

                payload = ee.FeatureCollection(collection.map(_feature)).toList(20000).map(
                    lambda f: ee.Feature(f).toDictionary(
                        ["date_utc", "weighted_sum", "area_sum", "accepted_count"]))
                rows = audit010.bounded_transient_getinfo(
                    lambda payload=payload: payload.getInfo(), phase, **context["options"])
                print(json.dumps({"ANOMALY_ENGINE_BLOCK": {
                    "phase": phase, "rows": len(rows) if isinstance(rows, list) else -1}},
                    sort_keys=True), flush=True)
                if not isinstance(rows, list):
                    raise EngineFailure("DAILY_RESPONSE_SHAPE_FAILED")
                for row in rows:
                    if not isinstance(row, dict) or set(row) != {
                            "date_utc", "weighted_sum", "area_sum", "accepted_count"}:
                        raise EngineFailure("DAILY_ROW_SHAPE_FAILED")
                    count = int(row["accepted_count"])
                    if count <= 0:
                        continue
                    area_sum = float(row["area_sum"])
                    if not area_sum > 0:
                        continue
                    values.append({
                        "stream_id": stream_id, "date_utc": row["date_utc"],
                        "daily_lst_c": round(float(row["weighted_sum"]) / area_sum, 4),
                        "accepted_pixel_count": count,
                    })
    return values


def _write_artifact(name: str, payload: dict[str, Any]) -> Path:
    validate_coordinate_free(payload)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / (name + ".json")
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _method_parameters() -> dict[str, Any]:
    return {
        "acceptance_rule": "qa_002_candidate_c", "window_half_width_days": WINDOW_HALF_WIDTH_DAYS,
        "historical_reference_period": [HISTORICAL_YEARS[0], HISTORICAL_YEARS[-1]],
        "reference_statistics": ["median", "mean"], "headline_anomaly": "median",
        "percentile_estimator": "type7_h=(n-1)p_linear_interpolation",
        "percentile_min_n": PERCENTILE_MIN_N, "percentile_full_n": PERCENTILE_FULL_N,
        "confidence_ok_fraction": CONFIDENCE_OK_FRACTION,
        "monthly_min_valid_days": MONTHLY_MIN_VALID_DAYS, "warm_percentile": WARM_PERCENTILE,
        "label_breaks": [[b, l] for b, l in LABEL_BREAKS] + [[100.0, LABEL_TOP]],
        "streams_merged": False,
    }


def _geometry_identity(source_record: dict[str, Any]) -> str:
    return canonical_sha256({
        "raw_sha256": source_record.get("raw_sha256"),
        "canonical_sha256": source_record.get("canonical_sha256"),
        "coordinate_tuple_count": source_record.get("coordinate_tuple_count_including_closure"),
    })


def build_climatology(project: str) -> int:
    ee, audit010, runner, _gj, context = _init_ee(project)
    identity = _geometry_identity(context["source_record"])
    print(json.dumps({"ANOMALY_ENGINE_PREFLIGHT": {
        "mode": "build_climatology", "specification": SPECIFICATION,
        "implementation": IMPLEMENTATION, "pinned_audit010_sha256": EXPECTED_AUDIT010_SHA256,
        "method_parameters": _method_parameters(), "geometry_identity_sha256": identity,
        "reads_coordinates": False}}, sort_keys=True), flush=True)
    eligible = _eligible_counts(context)
    daily_values = _collect_daily_values(context, list(HISTORICAL_YEARS))
    daily_values.sort(key=lambda v: (STREAM_IDS.index(v["stream_id"]), v["date_utc"]))
    baseline = assemble_baseline(daily_values, eligible)

    historical_payload = {
        "artifact": "historical_daily_values", "specification": SPECIFICATION,
        "implementation": IMPLEMENTATION, "coordinate_free": True, "reads_coordinates": False,
        "geometry_identity_sha256": identity, "method_parameters": _method_parameters(),
        "eligible_pixel_counts": eligible, "value_count": len(daily_values),
        "values": daily_values, "values_sha256": canonical_sha256(daily_values),
    }
    baseline_payload = {
        "artifact": "climatology_baseline", "specification": SPECIFICATION,
        "implementation": IMPLEMENTATION, "coordinate_free": True, "reads_coordinates": False,
        "geometry_identity_sha256": identity, "method_parameters": _method_parameters(),
        "eligible_pixel_counts": eligible,
        "historical_daily_values_sha256": historical_payload["values_sha256"],
        "row_count": len(baseline), "rows": baseline,
        "rows_sha256": canonical_sha256(baseline),
    }
    errors = validate_baseline(baseline_payload)
    if errors:
        raise EngineFailure("BASELINE_ADMISSION_FAILED:" + errors[0])
    _write_artifact("historical_daily_values", historical_payload)
    _write_artifact("climatology_baseline", baseline_payload)

    coverage = _baseline_coverage_summary(baseline)
    print(json.dumps({"ANOMALY_ENGINE_CLIMATOLOGY_COMPLETE": {
        "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
        "coordinate_free": True, "reads_coordinates": False,
        "historical_daily_value_count": len(daily_values),
        "baseline_row_count": len(baseline),
        "baseline_rows_sha256": baseline_payload["rows_sha256"],
        "eligible_pixel_counts": eligible,
        "coverage_summary": coverage, "pass": not errors,
    }}, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


def _baseline_coverage_summary(baseline: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for stream_id in STREAM_IDS:
        rows = [r for r in baseline if r["stream_id"] == stream_id]
        ns = [r["n"] for r in rows]
        divergence = [abs(r["median_minus_mean_c"]) for r in rows
                      if r["median_minus_mean_c"] is not None]
        summary[stream_id] = {
            "day_of_year_rows": len(rows),
            "n_min": min(ns), "n_median": int(statistics.median(ns)), "n_max": max(ns),
            "doy_with_n_lt_10": sum(1 for v in ns if v < PERCENTILE_MIN_N),
            "doy_with_n_lt_20": sum(1 for v in ns if v < PERCENTILE_FULL_N),
            "abs_median_minus_mean_c_median": (
                round(statistics.median(divergence), 4) if divergence else None),
            "abs_median_minus_mean_c_max": (
                round(max(divergence), 4) if divergence else None),
        }
    return summary


def validate_baseline(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != len(STREAM_IDS) * DAYS_IN_YEAR:
        return ["BASELINE_ROW_COUNT_FAILED"]
    seen: set[tuple[str, int]] = set()
    for row in rows:
        key = (row.get("stream_id"), row.get("day_of_year"))
        if row.get("stream_id") not in STREAM_IDS or not 1 <= row.get("day_of_year", 0) <= DAYS_IN_YEAR \
           or key in seen:
            errors.append("BASELINE_KEY_FAILED")
            break
        seen.add(key)
        temps = row.get("sorted_daily_lst_c")
        if not isinstance(temps, list) or temps != sorted(temps) or len(temps) != row["n"]:
            errors.append("BASELINE_SORTED_LIST_FAILED")
            break
        n_by_year = row.get("n_by_year")
        if not isinstance(n_by_year, list) or len(n_by_year) != len(HISTORICAL_YEARS) or \
           sum(n_by_year) != row["n"]:
            errors.append("BASELINE_N_BY_YEAR_FAILED")
            break
        if row["n"]:
            if not (min(temps) <= row["median_lst_c"] <= max(temps)) or \
               not (min(temps) <= row["mean_lst_c"] <= max(temps)):
                errors.append("BASELINE_STATISTIC_RANGE_FAILED")
                break
            if abs(row["median_minus_mean_c"] - (row["median_lst_c"] - row["mean_lst_c"])) > 1e-6:
                errors.append("BASELINE_DIVERGENCE_IDENTITY_FAILED")
                break
        else:
            if any(row[k] is not None for k in ("median_lst_c", "mean_lst_c", "sd_lst_c")):
                errors.append("BASELINE_EMPTY_NOT_NULL_FAILED")
                break
    if canonical_sha256(rows) != payload["rows_sha256"]:
        errors.append("BASELINE_HASH_FAILED")
    return errors


# --- self test -----------------------------------------------------------------

def self_test() -> int:
    failures: list[str] = []
    if sha256_file(AUDIT010_PATH) != EXPECTED_AUDIT010_SHA256:
        failures.append("audit010_pin")

    if not _source_identity_matches_pin(dict(PINNED_SOURCE_IDENTITY)) or \
       _source_identity_matches_pin({"raw_sha256": "x", "canonical_sha256": "y",
                                     "coordinate_tuple_count_including_closure": 1}) or \
       set(PINNED_SOURCE_IDENTITY) != {"raw_sha256", "canonical_sha256",
                                       "coordinate_tuple_count_including_closure"}:
        failures.append("source_identity_pin")

    # day-of-year folding + window wrap
    if fold_day_of_year(2, 29) != 59 or fold_day_of_year(2, 28) != 59 or \
       fold_day_of_year(1, 1) != 1 or fold_day_of_year(12, 31) != 366:
        failures.append("fold_day_of_year")
    if window_offsets(1) != {362, 363, 364, 365, 366, 1, 2, 3, 4, 5, 6} or \
       len(window_offsets(200)) != 11:
        failures.append("window_offsets")

    # Type-7 percentile: midpoint, ends, interpolation
    s = [0.0, 1.0, 2.0, 3.0, 4.0]      # n=5, h=(n-1)p
    checks = [(0.0, 0.0), (4.0, 100.0), (2.0, 50.0), (1.0, 25.0), (1.5, 37.5)]
    for x, expected in checks:
        got = type7_percentile_rank(s, x)
        if abs(got - expected) > 1e-6:
            failures.append(f"type7:{x}->{got}!={expected}")
    if type7_percentile_rank([5.0], 5.0) != 50.0:
        failures.append("type7_singleton")

    # classification boundaries
    for pct, label in [(5, "below normal"), (10, "within normal range"),
                       (89.999, "within normal range"), (90, "warm"), (95, "unusually warm"),
                       (99, "extreme warm observation"), (100, "extreme warm observation")]:
        if classify(pct) != label:
            failures.append(f"classify:{pct}->{classify(pct)}!={label}")
    if classify(None) != "historical context unavailable":
        failures.append("classify_none")
    if confidence_from_fraction(0.0) != "none" or confidence_from_fraction(0.05) != "low" or \
       confidence_from_fraction(0.15) != "ok" or confidence_from_fraction(0.9) != "ok":
        failures.append("confidence")

    # assemble_baseline + anomaly_record + assemble_monthly on a fixture
    daily = []
    for year in HISTORICAL_YEARS:
        # 3 observations near 15 Jan each year: values year-dependent, mild spread
        for day, offset in ((10, -0.5), (15, 0.0), (18, 0.6)):
            daily.append({"stream_id": "terra_night",
                          "date_utc": f"{year}-01-{day:02d}",
                          "daily_lst_c": 2.0 + (year - 2003) * 0.05 + offset,
                          "accepted_pixel_count": 40})
    baseline = assemble_baseline(daily, {s: 500 for s in STREAM_IDS})
    if len(baseline) != len(STREAM_IDS) * DAYS_IN_YEAR:
        failures.append("baseline_row_count")
    jan15 = next(r for r in baseline if r["stream_id"] == "terra_night" and r["day_of_year"] == 15)
    if jan15["n"] != 60 or jan15["median_lst_c"] is None or \
       jan15["sorted_daily_lst_c"] != sorted(jan15["sorted_daily_lst_c"]):
        failures.append("baseline_jan15")
    empty = next(r for r in baseline if r["stream_id"] == "terra_day" and r["day_of_year"] == 200)
    if empty["n"] != 0 or empty["median_lst_c"] is not None:
        failures.append("baseline_empty_row")
    payload = {"rows": baseline, "rows_sha256": canonical_sha256(baseline)}
    if validate_baseline(payload):
        failures.append("validate_baseline_positive:" + str(validate_baseline(payload)))
    bad = json.loads(json.dumps(payload))
    bad["rows"][0]["n_by_year"] = bad["rows"][0]["n_by_year"][:-1]
    if not validate_baseline({"rows": bad["rows"], "rows_sha256": canonical_sha256(bad["rows"])}):
        failures.append("validate_baseline_negative")

    warm_daily = {"stream_id": "terra_night", "date_utc": "2024-01-15",
                  "daily_lst_c": 5.0, "valid_water_fraction": 0.30, "accepted_pixel_count": 150,
                  "eligible_pixel_count": 500}
    rec = anomaly_record(warm_daily, jan15)
    if rec["confidence"] != "ok" or rec["anomaly_vs_median_c"] is None or \
       rec["historical_percentile"] is None or rec["percentile_confidence"] != "full" or \
       rec["classification"] not in ("unusually warm", "extreme warm observation", "warm"):
        failures.append("anomaly_record_warm:" + json.dumps(rec))
    if rec["anomaly_vs_median_c"] <= 0:
        failures.append("anomaly_record_sign")
    thin_daily = dict(warm_daily, valid_water_fraction=0.0, daily_lst_c=None)
    rec2 = anomaly_record(thin_daily, jan15)
    if rec2["classification"] != "no valid observation" or rec2["anomaly_vs_median_c"] is not None:
        failures.append("anomaly_record_none")
    short_n = dict(jan15, n=4, sorted_daily_lst_c=[1.0, 2.0, 3.0, 4.0],
                   n_by_year=[0] * len(HISTORICAL_YEARS))
    rec3 = anomaly_record(warm_daily, short_n)
    if rec3["historical_percentile"] is not None or \
       rec3["percentile_confidence"] != "insufficient_history" or \
       rec3["classification"] != "historical context unavailable" or \
       rec3["anomaly_vs_median_c"] is None:
        failures.append("anomaly_record_short_history")

    records = []
    for day in range(1, 11):
        records.append(anomaly_record(
            {"stream_id": "terra_night", "date_utc": f"2024-01-{day:02d}",
             "daily_lst_c": 2.0 + day * 0.1, "valid_water_fraction": 0.25,
             "accepted_pixel_count": 120, "eligible_pixel_count": 500}, jan15))
    monthly = assemble_monthly(records)
    row = next(r for r in monthly if r["stream_id"] == "terra_night" and r["month"] == "2024-01")
    if row["state"] != "reported" or row["valid_day_count"] != 10 or \
       row["monthly_mean_anomaly_vs_median_c"] is None or \
       row["calendar_day_count"] != 31:
        failures.append("assemble_monthly:" + json.dumps(row))
    short_month = assemble_monthly(records[:2])
    if next(r for r in short_month)["state"] != "insufficient valid observations":
        failures.append("assemble_monthly_short")

    for bad_key in ("latitude", "geometry_coordinates", "bbox"):
        try:
            validate_coordinate_free({bad_key: 1})
            failures.append("coord_free_negative:" + bad_key)
        except EngineFailure:
            pass
    try:
        validate_coordinate_free({"coordinate_free": True, "reads_coordinates": False,
                                  "rows": [{"day_of_year": 5, "median_lst_c": 1.0}]})
    except EngineFailure as exc:
        failures.append("coord_free_false_positive:" + exc.code)

    print(json.dumps({"self_test": not failures, "failures": failures,
                      "baseline_rows_expected": len(STREAM_IDS) * DAYS_IN_YEAR}, sort_keys=True))
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--build-climatology", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.project:
        parser.error("--project is required unless --self-test is used")
    try:
        if args.build_climatology:
            return build_climatology(args.project)
        parser.error("choose a mode: --build-climatology")
        return 2
    except EngineFailure as exc:
        print(json.dumps({"ANOMALY_ENGINE_FAILED": {
            "exception_class": type(exc).__name__, "validation_error_code": exc.code,
            "coordinate_free": True}}, sort_keys=True), flush=True)
        return 2
    except Exception as exc:  # noqa: BLE001
        message = str(exc)[:400]
        try:
            validate_coordinate_free({"exception_message": message})
        except Exception:  # noqa: BLE001
            message = "<redacted>"
        print(json.dumps({"ANOMALY_ENGINE_FAILED": True, "exception_class": type(exc).__name__,
                          "exception_message": message}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
