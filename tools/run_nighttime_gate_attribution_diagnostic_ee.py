#!/usr/bin/env python3
"""Coordinate-free AUDIT-011 nighttime gate-attribution diagnostic.

This runner imports the byte-pinned completed AUDIT-010 implementation only to
reuse its verified source, projection checks, request lifecycle, native-grid
reducers, and exact QA bit decoding.  It never reads or writes the completed
audit checkpoint and creates no asset, export, task, deployment, or UI.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
from importlib import metadata as importlib_metadata
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_RUNNER_PATH = ROOT / "tools" / "run_whole_lake_boundary_shoreline_audit_ee.py"
EXPECTED_AUDIT_RUNNER_SHA256 = "0e6c33277c2180db756d7ccfd6bf7c0cf9a5895c1ff07384fbd64ac7cf9d218f"
IMPLEMENTATION = "nighttime_gate_attribution_diagnostic_python_api_v5_boolean_source_identity"
SPECIFICATION = "AUDIT-011_2026-08-23"
REQUEST_WALL_LIMIT_SECONDS = 480.000
EE_CLIENT_REQUEST_DEADLINE_SECONDS = 480
TRANSPORT_MAX_ATTEMPTS = 1
SESSION_LIMIT_SECONDS = 165 * 60
GATE_ORDER = (
    "valid_temperature_data",
    "mandatory_qa",
    "data_quality",
    "emissivity_error",
    "lst_error",
    "view_time_validity",
    "view_angle_validity",
)
WINDOWS = (
    {"window_id": "winter_2024", "season": "winter", "start": "2024-01-15", "end": "2024-01-29"},
    {"window_id": "spring_2024", "season": "spring", "start": "2024-04-15", "end": "2024-04-29"},
    {"window_id": "summer_2024", "season": "summer", "start": "2024-07-15", "end": "2024-07-29"},
    {"window_id": "autumn_2024", "season": "autumn", "start": "2024-10-15", "end": "2024-10-29"},
)
NIGHT_STREAM_IDS = ("terra_night", "aqua_night")
ATTRIBUTION_REQUESTS = tuple(
    f"nighttime_gate_attribution_{window['window_id']}_{stream_id}"
    for window in WINDOWS for stream_id in NIGHT_STREAM_IDS
)
ALLOWED_PHASES = frozenset(
    [f"canonical_projection_{stream_id}" for stream_id in NIGHT_STREAM_IDS]
    + [f"canonical_reference_id_{stream_id}" for stream_id in NIGHT_STREAM_IDS]
    + ["runtime_fixture"]
    + [f"projection_inventory_{window['window_id']}_{stream_id}"
       for window in WINDOWS for stream_id in NIGHT_STREAM_IDS]
    + list(ATTRIBUTION_REQUESTS)
)
REQUEST_DECOMPOSITION = {
    "canonical_metadata_requests": 4,
    "runtime_fixture_requests": 1,
    "projection_inventory_requests": 8,
    "attribution_requests": 8,
    "total_ee_requests": 21,
    "attribution_rows_per_request": 14,
    "stream_order": list(NIGHT_STREAM_IDS),
    "window_order": [window["window_id"] for window in WINDOWS],
    "sequential": True,
    "automatic_retry": False,
}
SAFE_ADMISSION_ERROR_CODE = re.compile(r"\A[A-Za-z0-9_.:-]{1,160}\Z")


class DiagnosticAdmissionFailure(RuntimeError):
    """Coordinate-free local admission failure with allowlisted code evidence."""

    def __init__(self, phase: str, codes: list[str]):
        safe_codes = sorted(set(code for code in codes
                                if isinstance(code, str) and
                                SAFE_ADMISSION_ERROR_CODE.fullmatch(code)))
        if not safe_codes or len(safe_codes) != len(set(codes)):
            raise RuntimeError("UNSAFE_OR_EMPTY_ADMISSION_ERROR_CODES")
        super().__init__("DIAGNOSTIC_ADMISSION_FAILED")
        self.phase = phase
        self.codes = safe_codes


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_audit_runner() -> Any:
    if sha256_file(AUDIT_RUNNER_PATH) != EXPECTED_AUDIT_RUNNER_SHA256:
        raise RuntimeError("PINNED_AUDIT010_RUNNER_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location("pinned_audit010_runner", AUDIT_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PINNED_AUDIT010_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if sha256_file(AUDIT_RUNNER_PATH) != EXPECTED_AUDIT_RUNNER_SHA256:
        raise RuntimeError("PINNED_AUDIT010_RUNNER_CHANGED_DURING_IMPORT")
    return module


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def expected_dates(window: dict[str, str]) -> list[str]:
    start = dt.date.fromisoformat(window["start"])
    end = dt.date.fromisoformat(window["end"])
    return [(start + dt.timedelta(days=index)).isoformat()
            for index in range((end - start).days)]


def validate_coordinate_free(value: Any) -> None:
    """Reject coordinate-bearing names and coordinate-shaped objects recursively."""
    forbidden = re.compile(
        r"(?:^|_)(?:geometry|coordinates?|coords?|bounds?|bbox|extent|envelope|"
        r"latitude|longitude|lat|lon|lng|xmin|xmax|ymin|ymax|minx|maxx|miny|maxy)(?:_|$)",
        re.IGNORECASE,
    )
    allowed = {"geometry_id", "coordinate_free", "source_coordinate_arrays_included"}
    compact_forbidden = {
        "geometry", "coordinate", "coordinates", "coord", "coords", "bounds",
        "bbox", "extent", "envelope", "latitude", "longitude", "lat", "lon",
        "lng", "xmin", "xmax", "ymin", "ymax", "minx", "maxx", "miny", "maxy",
    }

    def walk(item: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("COORDINATE_FREE_NONSTRING_KEY")
                normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
                normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").casefold()
                compact = normalized.replace("_", "")
                if key not in allowed and (forbidden.search(normalized) or
                                           compact in compact_forbidden):
                    raise ValueError("COORDINATE_FREE_FORBIDDEN_KEY:" + ".".join(path + (key,)))
                walk(child, path + (key,))
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                walk(child, path + (str(index),))
    walk(value)


def _metric_map(entries: Any, denominator: float) -> dict[str, float]:
    if not isinstance(entries, list) or [item.get("gate") for item in entries
                                         if isinstance(item, dict)] != list(GATE_ORDER):
        raise ValueError("GATE_LIST_ORDER_OR_SHAPE_FAILED")
    result: dict[str, float] = {}
    for item in entries:
        if set(item) != {"gate", "area_m2", "coverage_fraction"} or \
           not _finite_number(item["area_m2"]) or item["area_m2"] < 0 or \
           not _finite_number(item["coverage_fraction"]) or not 0 <= item["coverage_fraction"] <= 1:
            raise ValueError("GATE_METRIC_FAILED")
        if abs(item["coverage_fraction"] - item["area_m2"] / denominator) > 1e-9:
            raise ValueError("GATE_COVERAGE_FRACTION_IDENTITY_FAILED")
        result[item["gate"]] = float(item["area_m2"])
    return result


def validate_date_record(record: dict[str, Any], date_utc: str,
                         window_id: str, stream_id: str) -> list[str]:
    errors: list[str] = []
    required = {
        "date_utc", "window_id", "stream_id", "source_image_count",
        "source_image_id", "source_identity_matches_projection_inventory",
        "eligible_area_m2", "eligible_pixel_center_count", "standalone_pass_area_m2",
        "cumulative_waterfall_area_m2", "leave_one_out_area_m2",
        "exclusive_failure_area_m2", "pairwise_failure_overlap_area_m2",
        "final_accepted_area_m2", "final_accepted_coverage_fraction",
        "audit_mask_accepted_area_m2", "audit_mask_accepted_coverage_fraction",
        "final_mask_identity_symmetric_difference_area_m2", "validation_errors",
    }
    if not isinstance(record, dict) or set(record) != required:
        return ["DATE_RECORD_SHAPE_FAILED"]
    if (record["date_utc"], record["window_id"], record["stream_id"]) != (
            date_utc, window_id, stream_id):
        errors.append("DATE_RECORD_IDENTITY_FAILED")
    count = record["source_image_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count != 1:
        errors.append("SOURCE_IMAGE_COUNT_FAILED")
    if count == 1 and (not isinstance(record["source_image_id"], str) or
                       not record["source_image_id"]):
        errors.append("SOURCE_IMAGE_ID_FAILED")
    if record["source_identity_matches_projection_inventory"] is not True:
        errors.append("SOURCE_PROJECTION_IDENTITY_FAILED")
    for name in ("eligible_area_m2", "final_accepted_area_m2",
                 "audit_mask_accepted_area_m2",
                 "final_mask_identity_symmetric_difference_area_m2"):
        if not _finite_number(record[name]) or record[name] < 0:
            errors.append("NONNEGATIVE_FINITE_METRIC_FAILED:" + name)
    if not isinstance(record["eligible_pixel_center_count"], int) or isinstance(
            record["eligible_pixel_center_count"], bool) or record["eligible_pixel_center_count"] <= 0:
        errors.append("ELIGIBLE_PIXEL_COUNT_FAILED")
    try:
        denominator = float(record["eligible_area_m2"])
        if denominator <= 0:
            raise ValueError("NONPOSITIVE_ELIGIBLE_AREA")
        standalone = _metric_map(record["standalone_pass_area_m2"], denominator)
        leave_one_out = _metric_map(record["leave_one_out_area_m2"], denominator)
        exclusive = _metric_map(record["exclusive_failure_area_m2"], denominator)
    except ValueError as exc:
        errors.append(str(exc))
        standalone, leave_one_out, exclusive = {}, {}, {}
    waterfall = record["cumulative_waterfall_area_m2"]
    expected_stages = ["eligible"] + list(GATE_ORDER)
    if not isinstance(waterfall, list) or [item.get("stage") for item in waterfall
                                           if isinstance(item, dict)] != expected_stages:
        errors.append("WATERFALL_ORDER_OR_SHAPE_FAILED")
    elif any(set(item) != {"stage", "area_m2", "coverage_fraction"} or
             not _finite_number(item["area_m2"]) or item["area_m2"] < 0 or
             not _finite_number(item["coverage_fraction"]) or
             not 0 <= item["coverage_fraction"] <= 1 or
             abs(item["coverage_fraction"] - item["area_m2"] /
                 float(record["eligible_area_m2"])) > 1e-9 for item in waterfall):
        errors.append("WATERFALL_METRIC_FAILED")
    else:
        values = [float(item["area_m2"]) for item in waterfall]
        tolerance = max(1.0, float(record["eligible_area_m2"]) * 1e-6)
        if any(right - left > tolerance for left, right in zip(values, values[1:])):
            errors.append("WATERFALL_NOT_MONOTONIC")
        if abs(values[0] - float(record["eligible_area_m2"])) > tolerance:
            errors.append("WATERFALL_DENOMINATOR_FAILED")
        if abs(values[-1] - float(record["final_accepted_area_m2"])) > tolerance:
            errors.append("WATERFALL_FINAL_FAILED")
        if any(float(record["final_accepted_area_m2"]) > value + tolerance
               for value in values):
            errors.append("FINAL_EXCEEDS_WATERFALL_STAGE")
        if standalone:
            if abs(values[1] - standalone[GATE_ORDER[0]]) > tolerance:
                errors.append("WATERFALL_FIRST_GATE_IDENTITY_FAILED")
            for index, gate in enumerate(GATE_ORDER, start=1):
                if values[index] > standalone[gate] + tolerance:
                    errors.append("WATERFALL_STAGE_EXCEEDS_STANDALONE:" + gate)
    overlaps = record["pairwise_failure_overlap_area_m2"]
    expected_pairs = [(GATE_ORDER[i], GATE_ORDER[j])
                      for i in range(len(GATE_ORDER)) for j in range(i + 1, len(GATE_ORDER))]
    if not isinstance(overlaps, list) or len(overlaps) != len(expected_pairs):
        errors.append("PAIRWISE_OVERLAP_COUNT_FAILED")
    else:
        actual_pairs = [(item.get("gate_a"), item.get("gate_b"))
                        for item in overlaps if isinstance(item, dict)]
        if actual_pairs != expected_pairs or any(
                set(item) != {"gate_a", "gate_b", "area_m2", "coverage_fraction"} or
                not _finite_number(item["area_m2"]) or item["area_m2"] < 0 or
                not _finite_number(item["coverage_fraction"]) or
                not 0 <= item["coverage_fraction"] <= 1 or
                abs(item["coverage_fraction"] - item["area_m2"] /
                    float(record["eligible_area_m2"])) > 1e-9
                for item in overlaps):
            errors.append("PAIRWISE_OVERLAP_SHAPE_FAILED")
    tolerance = max(1.0, float(record["eligible_area_m2"]) * 1e-6) \
        if _finite_number(record["eligible_area_m2"]) else 1.0
    if _finite_number(record["final_mask_identity_symmetric_difference_area_m2"]) and \
       record["final_mask_identity_symmetric_difference_area_m2"] > tolerance:
        errors.append("FINAL_MASK_IDENTITY_FAILED")
    if _finite_number(record["final_accepted_area_m2"]) and \
       _finite_number(record["audit_mask_accepted_area_m2"]) and abs(
           record["final_accepted_area_m2"] - record["audit_mask_accepted_area_m2"]) > tolerance:
        errors.append("FINAL_ACCEPTED_AREA_IDENTITY_FAILED")
    for area_name, fraction_name in (
            ("final_accepted_area_m2", "final_accepted_coverage_fraction"),
            ("audit_mask_accepted_area_m2", "audit_mask_accepted_coverage_fraction")):
        if not _finite_number(record[fraction_name]) or not 0 <= record[fraction_name] <= 1 or \
           abs(record[fraction_name] - record[area_name] /
               float(record["eligible_area_m2"])) > 1e-9:
            errors.append("FINAL_COVERAGE_FRACTION_IDENTITY_FAILED:" + fraction_name)
    if standalone and leave_one_out and exclusive:
        final = float(record["final_accepted_area_m2"])
        eligible = float(record["eligible_area_m2"])
        for gate in GATE_ORDER:
            if standalone[gate] > eligible + tolerance or leave_one_out[gate] > eligible + tolerance:
                errors.append("GATE_AREA_EXCEEDS_ELIGIBLE:" + gate)
            if abs((leave_one_out[gate] - final) - exclusive[gate]) > tolerance:
                errors.append("EXCLUSIVE_FAILURE_IDENTITY_FAILED:" + gate)
            if final > standalone[gate] + tolerance:
                errors.append("FINAL_EXCEEDS_STANDALONE:" + gate)
            if leave_one_out[gate] + tolerance < final:
                errors.append("LEAVE_ONE_OUT_BELOW_FINAL:" + gate)
            if exclusive[gate] > eligible - standalone[gate] + tolerance:
                errors.append("EXCLUSIVE_FAILURE_EXCEEDS_MARGINAL_FAILURE:" + gate)
        if isinstance(overlaps, list) and len(overlaps) == 21:
            for item in overlaps:
                if isinstance(item, dict) and _finite_number(item.get("area_m2")):
                    for gate in (item.get("gate_a"), item.get("gate_b")):
                        if gate in standalone and item["area_m2"] > \
                           eligible - standalone[gate] + tolerance:
                            errors.append("PAIRWISE_OVERLAP_EXCEEDS_MARGINAL_FAILURE:" + str(gate))
                        if gate in standalone and (
                                item["area_m2"] + exclusive[gate] -
                                (eligible - standalone[gate])) / eligible > 1e-9:
                            errors.append(
                                "EXCLUSIVE_PLUS_PAIRWISE_EXCEEDS_MARGINAL_FAILURE:" + str(gate))
    if not isinstance(record["validation_errors"], list) or record["validation_errors"]:
        errors.append("SERVER_VALIDATION_ERRORS_PRESENT")
    try:
        validate_coordinate_free(record)
    except ValueError as exc:
        errors.append(str(exc))
    return sorted(set(errors))


def validate_request_result(result: dict[str, Any], window: dict[str, str],
                            stream: dict[str, Any]) -> list[str]:
    required = {"specification", "implementation", "window_id", "season", "stream_id",
                "geometry_id", "date_count", "records", "coordinate_free",
                "declared_gate_order", "attribution_interpretation", "validation_errors"}
    if not isinstance(result, dict) or set(result) != required:
        return ["REQUEST_RESULT_SHAPE_FAILED"]
    errors: list[str] = []
    if result["specification"] != SPECIFICATION or result["implementation"] != IMPLEMENTATION:
        errors.append("VERSION_IDENTITY_FAILED")
    if (result["window_id"], result["season"], result["stream_id"]) != (
            window["window_id"], window["season"], stream["stream_id"]):
        errors.append("REQUEST_IDENTITY_FAILED")
    if result["geometry_id"] != "wise_wfd_v1_9_huaih049_2022_unrounded__erosion_0000m":
        errors.append("GEOMETRY_IDENTITY_FAILED")
    dates = expected_dates(window)
    records = result["records"]
    if result["date_count"] != 14 or not isinstance(records, list) or len(records) != 14:
        errors.append("DATE_COUNT_FAILED")
    else:
        for date_utc, record in zip(dates, records):
            errors.extend(validate_date_record(
                record, date_utc, window["window_id"], stream["stream_id"]))
    if result["coordinate_free"] is not True or result["declared_gate_order"] != list(GATE_ORDER):
        errors.append("METHOD_METADATA_FAILED")
    if result["attribution_interpretation"] != (
            "descriptive logical gate attribution; cumulative losses depend on declared order; "
            "standalone, leave-one-out, exclusive-failure, and pairwise-overlap evidence is order-independent; not causal"):
        errors.append("ATTRIBUTION_INTERPRETATION_FAILED")
    if not isinstance(result["validation_errors"], list) or result["validation_errors"]:
        errors.append("REQUEST_SERVER_VALIDATION_ERRORS_PRESENT")
    try:
        validate_coordinate_free(result)
    except ValueError as exc:
        errors.append(str(exc))
    return sorted(set(errors))


class NighttimeDiagnosticRunner:
    """Use the pinned audit runner's exact native-grid and QA primitives."""

    def __init__(self, audit: Any, ee: Any, geometry_json: dict[str, Any],
                 source_record: dict[str, Any], request_options: dict[str, Any]):
        self.audit = audit
        self.ee = ee
        self.source_record = source_record
        self.request_options = dict(request_options)
        self.source = ee.Geometry(geometry_json, proj="EPSG:4326", geodesic=True)
        self.run_timestamp = dt.datetime.now(dt.timezone.utc).replace(
            microsecond=0).isoformat().replace("+00:00", "Z")
        self.contexts = {stream["stream_id"]: self._projection_metadata(stream)
                         for stream in self.streams}
        self.projection_certifications: dict[tuple[str, str], dict[str, Any]] = {}

    @property
    def streams(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(stream) for stream in self.audit.STREAMS
                if stream["stream_id"] in NIGHT_STREAM_IDS]

    _margin = property(lambda self: None)  # overwritten below for type checkers


# Reuse methods without changing the pinned class or constructing its four-stream context.
for _name in ("_margin", "_nbool", "_boolean", "_reduce", "_sum_area", "_count",
              "_validity", "_masks", "context_for_candidate", "_projection_metadata",
              "projection_inventory_evidence", "register_projection_inventory",
              "server_runtime_fixture"):
    setattr(NighttimeDiagnosticRunner, _name, getattr(load_audit_runner().AuditRunner, _name))


def _diagnostic_graph(self: NighttimeDiagnosticRunner, window: dict[str, str],
                      stream: dict[str, Any]) -> Any:
    ee = self.ee
    geometry = self.source.transform(proj=self.audit.OP_CRS, maxError=self._margin())
    context = self.context_for_candidate(stream, geometry)
    eligible = ee.Number(context["eligible_roi_area_m2"])

    def one_date(date_utc: str) -> Any:
        start = ee.Date(date_utc)
        collection = ee.ImageCollection(stream["collection_id"]).filterDate(
            start, start.advance(1, "day")).sort("system:time_start")
        count = collection.size()
        bands = [stream[key] for key in ("lst", "qc", "time", "angle", "clear")]
        fallback = ee.Image.constant([0] * 5).rename(bands).updateMask(ee.Image.constant(0))
        image = ee.Image(ee.Algorithms.If(count.eq(1), collection.first(), fallback))
        qc = image.select(stream["qc"])
        decoded = self._masks(image, stream)["decoded"]
        observed_qc = qc.mask().unmask(0).gt(0)
        gates = {
            "valid_temperature_data": self._validity(image.select(stream["lst"]), 7500, 65535),
            "mandatory_qa": observed_qc.And(decoded.select("mandatory_qa").unmask(0).eq(0)).unmask(0),
            "data_quality": observed_qc.And(decoded.select("data_quality").unmask(0).eq(0)).unmask(0),
            "emissivity_error": observed_qc.And(decoded.select("emissivity_error").unmask(0).eq(0)).unmask(0),
            "lst_error": observed_qc.And(decoded.select("lst_error").unmask(0).eq(0)).unmask(0),
            "view_time_validity": self._validity(image.select(stream["time"]), 0, 240),
            "view_angle_validity": self._validity(image.select(stream["angle"]), 0, 130),
        }
        always = ee.Image.constant(1).eq(1)
        cumulative = always
        masks: list[tuple[str, Any]] = [("waterfall__eligible", always)]
        for gate in GATE_ORDER:
            masks.append(("standalone__" + gate, gates[gate]))
            cumulative = cumulative.And(gates[gate]).unmask(0)
            masks.append(("waterfall__" + gate, cumulative))
        final_mask = cumulative
        all_except: dict[str, Any] = {}
        for gate in GATE_ORDER:
            other = always
            for other_gate in GATE_ORDER:
                if other_gate != gate:
                    other = other.And(gates[other_gate]).unmask(0)
            all_except[gate] = other
            masks.append(("leave_one_out__" + gate, other))
            masks.append(("exclusive_failure__" + gate,
                          other.And(gates[gate].Not()).unmask(0)))
        for left_index, left in enumerate(GATE_ORDER):
            for right in GATE_ORDER[left_index + 1:]:
                masks.append(("pairwise_failure__" + left + "__" + right,
                              gates[left].Not().And(gates[right].Not()).unmask(0)))
        audit_accepted = self._masks(image, stream)["accepted"]
        symmetric_difference = final_mask.neq(audit_accepted).unmask(0)
        masks.extend((("final_accepted", final_mask),
                      ("audit_mask_accepted", audit_accepted),
                      ("final_mask_identity_symmetric_difference", symmetric_difference)))
        area_image = ee.Image.cat([
            ee.Image.pixelArea().rename(name).updateMask(mask)
            for name, mask in masks
        ])
        reduced = ee.Dictionary(self._reduce(area_image, ee.Reducer.sum(), geometry, context))
        area = lambda name: ee.Number(reduced.get(name, 0)).toDouble()
        fraction = lambda name: area(name).divide(eligible).toDouble()
        certification = self.projection_certifications[(date_utc, stream["stream_id"])]
        certified_index = certification.get("source_system_index")
        certified_count = certification.get("source_image_count")
        projection_ok = (
            certified_count == 0 or
            certification.get("projection_acceptance_pass") is True
        )
        selected_id_ok = ee.Algorithms.If(
            count.eq(1), ee.Algorithms.IsEqual(image.get("system:index"), certified_index),
            count.eq(0))
        source_id_ok = self._nbool(count.eq(certified_count)).And(
            self._nbool(selected_id_ok))
        tolerance = eligible.multiply(1e-6).max(1.0)
        errors = ee.List([])
        errors = ee.List(ee.Algorithms.If(count.lte(1), errors,
                                          errors.add("DUPLICATE_SOURCE_IMAGES")))
        errors = ee.List(ee.Algorithms.If(projection_ok, errors,
                                          errors.add("PROJECTION_CERTIFICATION_FAILED")))
        errors = ee.List(ee.Algorithms.If(source_id_ok, errors,
                                          errors.add("SOURCE_IDENTITY_MISMATCH")))
        errors = ee.List(ee.Algorithms.If(eligible.gt(0), errors,
                                          errors.add("NONPOSITIVE_ELIGIBLE_AREA")))
        errors = ee.List(ee.Algorithms.If(
            area("final_mask_identity_symmetric_difference").lte(tolerance), errors,
            errors.add("FINAL_MASK_IDENTITY_FAILED")))
        valid_record = ee.Dictionary({
            "date_utc": date_utc,
            "window_id": window["window_id"],
            "stream_id": stream["stream_id"],
            "source_image_count": count.toInt64(),
            "source_image_id": ee.Algorithms.If(count.eq(1), image.id(), None),
            "source_identity_matches_projection_inventory": self._boolean(source_id_ok),
            "eligible_area_m2": eligible,
            "eligible_pixel_center_count": ee.Number(context["eligible_pixel_center_count"]).toInt64(),
            "standalone_pass_area_m2": ee.List([
                {"gate": gate, "area_m2": area("standalone__" + gate),
                 "coverage_fraction": fraction("standalone__" + gate)} for gate in GATE_ORDER]),
            "cumulative_waterfall_area_m2": ee.List(
                [{"stage": "eligible", "area_m2": area("waterfall__eligible"),
                  "coverage_fraction": fraction("waterfall__eligible")}] +
                [{"stage": gate, "area_m2": area("waterfall__" + gate),
                  "coverage_fraction": fraction("waterfall__" + gate)} for gate in GATE_ORDER]),
            "leave_one_out_area_m2": ee.List([
                {"gate": gate, "area_m2": area("leave_one_out__" + gate),
                 "coverage_fraction": fraction("leave_one_out__" + gate)} for gate in GATE_ORDER]),
            "exclusive_failure_area_m2": ee.List([
                {"gate": gate, "area_m2": area("exclusive_failure__" + gate),
                 "coverage_fraction": fraction("exclusive_failure__" + gate)} for gate in GATE_ORDER]),
            "pairwise_failure_overlap_area_m2": ee.List([
                {"gate_a": left, "gate_b": right,
                 "area_m2": area("pairwise_failure__" + left + "__" + right),
                 "coverage_fraction": fraction(
                     "pairwise_failure__" + left + "__" + right)}
                for index, left in enumerate(GATE_ORDER) for right in GATE_ORDER[index + 1:]
            ]),
            "final_accepted_area_m2": area("final_accepted"),
            "final_accepted_coverage_fraction": fraction("final_accepted"),
            "audit_mask_accepted_area_m2": area("audit_mask_accepted"),
            "audit_mask_accepted_coverage_fraction": fraction("audit_mask_accepted"),
            "final_mask_identity_symmetric_difference_area_m2": area(
                "final_mask_identity_symmetric_difference"),
            "validation_errors": errors.distinct().sort(),
        })
        invalid_record = ee.Dictionary({
            "date_utc": date_utc,
            "window_id": window["window_id"],
            "stream_id": stream["stream_id"],
            "source_image_count": count.toInt64(),
            "source_image_id": None,
            "validation_errors": ee.List(["SOURCE_IMAGE_COUNT_NOT_EXACTLY_ONE"]),
        })
        return ee.Dictionary(ee.Algorithms.If(count.eq(1), valid_record, invalid_record))

    records = ee.List([one_date(date_utc) for date_utc in expected_dates(window)])
    return ee.Dictionary({
        "specification": SPECIFICATION,
        "implementation": IMPLEMENTATION,
        "window_id": window["window_id"],
        "season": window["season"],
        "stream_id": stream["stream_id"],
        "geometry_id": "wise_wfd_v1_9_huaih049_2022_unrounded__erosion_0000m",
        "date_count": records.length(),
        "records": records,
        "coordinate_free": True,
        "declared_gate_order": list(GATE_ORDER),
        "attribution_interpretation": (
            "descriptive logical gate attribution; cumulative losses depend on declared order; "
            "standalone, leave-one-out, exclusive-failure, and pairwise-overlap evidence is order-independent; not causal"),
        "validation_errors": ee.List([]),
    })


NighttimeDiagnosticRunner.diagnostic_graph = _diagnostic_graph


def synthetic_record() -> dict[str, Any]:
    eligible = 100.0
    standalone_values = [90, 80, 85, 87, 88, 92, 91]
    final = 50.0
    exclusive_values = [2, 3, 4, 5, 6, 7, 8]
    return {
        "date_utc": "2024-01-15", "window_id": "winter_2024",
        "stream_id": "terra_night", "source_image_count": 1,
        "source_image_id": "MODIS/061/MOD11A1/example",
        "source_identity_matches_projection_inventory": True,
        "eligible_area_m2": eligible, "eligible_pixel_center_count": 10,
        "standalone_pass_area_m2": [{"gate": gate, "area_m2": value,
                                      "coverage_fraction": value / eligible}
                                    for gate, value in zip(GATE_ORDER, standalone_values)],
        "cumulative_waterfall_area_m2": [
            {"stage": stage, "area_m2": value, "coverage_fraction": value / eligible}
            for stage, value in zip(
                ["eligible"] + list(GATE_ORDER), [100, 90, 75, 70, 65, 60, 55, final])],
        "leave_one_out_area_m2": [{"gate": gate, "area_m2": final + value,
                                    "coverage_fraction": (final + value) / eligible}
                                   for gate, value in zip(GATE_ORDER, exclusive_values)],
        "exclusive_failure_area_m2": [{"gate": gate, "area_m2": value,
                                        "coverage_fraction": value / eligible}
                                       for gate, value in zip(GATE_ORDER, exclusive_values)],
        "pairwise_failure_overlap_area_m2": [
            {"gate_a": left, "gate_b": right, "area_m2": 1.0,
             "coverage_fraction": 0.01}
            for index, left in enumerate(GATE_ORDER) for right in GATE_ORDER[index + 1:]],
        "final_accepted_area_m2": final, "final_accepted_coverage_fraction": 0.5,
        "audit_mask_accepted_area_m2": final, "audit_mask_accepted_coverage_fraction": 0.5,
        "final_mask_identity_symmetric_difference_area_m2": 0.0,
        "validation_errors": [],
    }


def self_test() -> int:
    failures: list[str] = []
    if sha256_file(AUDIT_RUNNER_PATH) != EXPECTED_AUDIT_RUNNER_SHA256:
        failures.append("audit_runner_pin")
    if len(ALLOWED_PHASES) != 21 or len(ATTRIBUTION_REQUESTS) != 8 or \
       REQUEST_DECOMPOSITION["total_ee_requests"] != 21:
        failures.append("request_decomposition")
    if REQUEST_WALL_LIMIT_SECONDS != 480.000 or \
       EE_CLIENT_REQUEST_DEADLINE_SECONDS != 480 or \
       isinstance(EE_CLIENT_REQUEST_DEADLINE_SECONDS, bool) or \
       not isinstance(EE_CLIENT_REQUEST_DEADLINE_SECONDS, int):
        failures.append("request_deadline_types")
    try:
        audit_contract = load_audit_runner()
        if audit_contract.validate_request_policy(
                EE_CLIENT_REQUEST_DEADLINE_SECONDS, TRANSPORT_MAX_ATTEMPTS
        )["deadline_seconds"] != 480:
            failures.append("integer_client_deadline_contract")
        try:
            audit_contract.validate_request_policy(
                REQUEST_WALL_LIMIT_SECONDS, TRANSPORT_MAX_ATTEMPTS)
            failures.append("float_client_deadline_negative_fixture")
        except ValueError:
            pass
    except Exception:
        failures.append("request_policy_contract_exception")
    record = synthetic_record()
    if validate_date_record(record, "2024-01-15", "winter_2024", "terra_night"):
        failures.append("positive_record")
    def set_area_fraction(item: dict[str, Any], value: float) -> None:
        item["area_m2"] = value
        item["coverage_fraction"] = value / 100.0
    mutations = {
        "waterfall_increase": (lambda x: set_area_fraction(
            x["cumulative_waterfall_area_m2"][3], 99.0), "WATERFALL_NOT_MONOTONIC"),
        "first_gate_identity": (lambda x: set_area_fraction(
            x["cumulative_waterfall_area_m2"][1], 88.5), "WATERFALL_FIRST_GATE_IDENTITY_FAILED"),
        "cumulative_standalone_bound": (lambda x: set_area_fraction(
            x["cumulative_waterfall_area_m2"][2], 82.0),
            "WATERFALL_STAGE_EXCEEDS_STANDALONE:mandatory_qa"),
        "final_waterfall_bound": (lambda x: set_area_fraction(
            x["cumulative_waterfall_area_m2"][-2], 48.0),
            "FINAL_EXCEEDS_WATERFALL_STAGE"),
        "final_standalone_bound": (lambda x: set_area_fraction(
            x["standalone_pass_area_m2"][-1], 48.0),
            "FINAL_EXCEEDS_STANDALONE:view_angle_validity"),
        "pairwise_marginal_bound": (lambda x: set_area_fraction(
            x["pairwise_failure_overlap_area_m2"][0], 12.0),
            "PAIRWISE_OVERLAP_EXCEEDS_MARGINAL_FAILURE:valid_temperature_data"),
        "exclusive_plus_pairwise_bound": (lambda x: set_area_fraction(
            x["pairwise_failure_overlap_area_m2"][0], 9.0),
            "EXCLUSIVE_PLUS_PAIRWISE_EXCEEDS_MARGINAL_FAILURE:valid_temperature_data"),
        "final_identity": (lambda x: x.__setitem__("audit_mask_accepted_area_m2", 40.0),
                           "FINAL_ACCEPTED_AREA_IDENTITY_FAILED"),
        "exclusive_identity": (lambda x: set_area_fraction(
            x["exclusive_failure_area_m2"][0], 9.0),
            "EXCLUSIVE_FAILURE_IDENTITY_FAILED:valid_temperature_data"),
        "server_errors": (lambda x: x.__setitem__("validation_errors", ["FAIL"]),
                          "SERVER_VALIDATION_ERRORS_PRESENT"),
        "pair_missing": (lambda x: x["pairwise_failure_overlap_area_m2"].pop(),
                         "PAIRWISE_OVERLAP_COUNT_FAILED"),
        "source_identity": (lambda x: x.__setitem__(
            "source_identity_matches_projection_inventory", False),
            "SOURCE_PROJECTION_IDENTITY_FAILED"),
        "missing_source": (lambda x: x.__setitem__("source_image_count", 0),
                           "SOURCE_IMAGE_COUNT_FAILED"),
        "duplicate_source": (lambda x: x.__setitem__("source_image_count", 2),
                             "SOURCE_IMAGE_COUNT_FAILED"),
    }
    for name, (mutate, expected_error) in mutations.items():
        fixture = copy.deepcopy(record)
        mutate(fixture)
        observed_errors = validate_date_record(
            fixture, "2024-01-15", "winter_2024", "terra_night")
        if expected_error not in observed_errors:
            failures.append("negative_" + name)
    for forbidden in ("bounds", "bbox", "coordinates", "coordinateArray", "latitude", "minX"):
        fixture = copy.deepcopy(record)
        fixture[forbidden] = 1.0
        try:
            validate_coordinate_free(fixture)
            failures.append("coordinate_guard_" + forbidden)
        except ValueError:
            pass
    if list(GATE_ORDER) != [
            "valid_temperature_data", "mandatory_qa", "data_quality",
            "emissivity_error", "lst_error", "view_time_validity",
            "view_angle_validity"]:
        failures.append("gate_order")
    numeric_boolean_fixture = copy.deepcopy(record)
    numeric_boolean_fixture["source_identity_matches_projection_inventory"] = 1
    if "SOURCE_PROJECTION_IDENTITY_FAILED" not in validate_date_record(
            numeric_boolean_fixture, "2024-01-15", "winter_2024", "terra_night"):
        failures.append("numeric_source_identity_boolean_rejection")
    try:
        admission_fixture = DiagnosticAdmissionFailure(
            "attribution_client_admission",
            ["SOURCE_PROJECTION_IDENTITY_FAILED"])
        if admission_fixture.codes != ["SOURCE_PROJECTION_IDENTITY_FAILED"]:
            failures.append("safe_admission_error_code_positive")
    except Exception:
        failures.append("safe_admission_error_code_exception")
    try:
        DiagnosticAdmissionFailure(
            "attribution_client_admission", ["UNSAFE ERROR WITH SPACES"])
        failures.append("unsafe_admission_error_code_rejection")
    except RuntimeError:
        pass
    source = AUDIT_RUNNER_PATH.read_text(encoding="utf-8")
    for exact in (
            "self._validity(lst, 7500, 65535)",
            "self._validity(time, 0, 240)",
            "self._validity(angle, 0, 130)",
            ".And(mandatory.eq(0)).And(decoded.select(\"data_quality\")",
            ".And(decoded.select(\"emissivity_error\")",
            ".And(decoded.select(\"lst_error\")"):
        if exact not in source:
            failures.append("pinned_mask_source_" + canonical_sha256(exact)[:8])
    diagnostic_source = Path(__file__).read_text(encoding="utf-8")
    for exact in (
            "If(count.eq(1), valid_record, invalid_record)",
            "SOURCE_IMAGE_COUNT_NOT_EXACTLY_ONE",
            'record.get("source_image_count") != 1',
            '"source_identity_matches_projection_inventory": self._boolean(source_id_ok)'):
        if exact not in diagnostic_source:
            failures.append("fail_closed_source_branch_" + canonical_sha256(exact)[:8])
    print(json.dumps({"self_test": not failures, "failures": failures,
                      "request_decomposition": REQUEST_DECOMPOSITION}, sort_keys=True))
    return 0 if not failures else 2


def execute(project: str) -> int:
    session_started = time.monotonic()
    session_deadline = session_started + SESSION_LIMIT_SECONDS
    audit = load_audit_runner()
    audit.configure_ee_serializer_recursion_limit()
    ee = audit.import_ee()
    ee.Initialize(project=project)
    policy = audit.configure_ee_request_policy(
        ee, EE_CLIENT_REQUEST_DEADLINE_SECONDS, TRANSPORT_MAX_ATTEMPTS)
    options = {"max_attempts": 1, "deadline_seconds": 480,
               "session_deadline_monotonic": session_deadline}
    geometry_json, source_record = audit.load_verified_source()
    source_evidence = audit.coordinate_free_source_evidence(
        source_record, project, getattr(ee, "__version__",
        importlib_metadata.version("earthengine-api")),
        audit.configure_ee_serializer_recursion_limit())
    print(json.dumps({"NIGHTTIME_DIAGNOSTIC_PREFLIGHT": {
        "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
        "pinned_audit_runner_sha256": EXPECTED_AUDIT_RUNNER_SHA256,
        "source_evidence_sha256": canonical_sha256(source_evidence),
        "request_policy": policy, "request_decomposition": REQUEST_DECOMPOSITION,
        "completed_audit_checkpoint_read_or_written": False,
        "source_coordinate_arrays_included": False,
    }}, sort_keys=True), flush=True)
    runner = NighttimeDiagnosticRunner(audit, ee, geometry_json, source_record, options)
    runtime_fixture = audit.evaluate_authenticated_phase(
        runner.server_runtime_fixture, "runtime_fixture", **options)
    fixture_errors = audit.validate_server_runtime_fixture(runtime_fixture)
    if fixture_errors:
        raise RuntimeError("SERVER_RUNTIME_FIXTURE_FAILED:" + ",".join(fixture_errors))
    projection_digests: list[dict[str, Any]] = []
    for window in WINDOWS:
        for stream in runner.streams:
            phase = f"projection_inventory_{window['window_id']}_{stream['stream_id']}"
            inventory = audit.bounded_transient_getinfo(
                lambda w=window, s=stream: runner.projection_inventory_evidence(w, s),
                phase, **options)
            if inventory.get("record_count") != 14 or len(inventory.get("records", [])) != 14 or \
               not inventory.get("pass") or any(
                   record.get("source_image_count") != 1
                   for record in inventory.get("records", [])):
                raise RuntimeError("PROJECTION_INVENTORY_FAILED:" + phase)
            runner.register_projection_inventory(inventory)
            projection_digests.append({
                "window_id": window["window_id"], "stream_id": stream["stream_id"],
                "record_count": 14,
                "source_image_counts": [record.get("source_image_count")
                                        for record in inventory["records"]],
                "source_image_ids_sha256": canonical_sha256([
                    record.get("source_image_ids") for record in inventory["records"]]),
                "projection_inventory_sha256": canonical_sha256(inventory),
                "pass": True,
            })
    results: list[dict[str, Any]] = []
    for window in WINDOWS:
        for stream in runner.streams:
            phase = f"nighttime_gate_attribution_{window['window_id']}_{stream['stream_id']}"
            result = audit.evaluate_authenticated_phase(
                lambda w=window, s=stream: runner.diagnostic_graph(w, s), phase, **options)
            errors = validate_request_result(result, window, stream)
            if errors:
                raise DiagnosticAdmissionFailure(
                    "attribution_client_admission", errors)
            results.append(result)
    final = {
        "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
        "coordinate_free": True, "source_coordinate_arrays_included": False,
        "geometry_id": "wise_wfd_v1_9_huaih049_2022_unrounded__erosion_0000m",
        "request_decomposition": REQUEST_DECOMPOSITION,
        "projection_certification_digests": projection_digests,
        "result_count": len(results), "results": results,
        "validation_errors": [], "pass": len(results) == 8,
        "scientific_interpretation": (
            "Diagnostic attribution only. Cumulative differences are declared-order bookkeeping; "
            "overlap-aware logical evidence is descriptive and must not be interpreted as causal."),
    }
    validate_coordinate_free(final)
    print(json.dumps({"NIGHTTIME_GATE_ATTRIBUTION_DIAGNOSTIC_COMPLETE": final},
                     sort_keys=True, separators=(",", ":")), flush=True)
    return 0


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
    except DiagnosticAdmissionFailure as exc:
        print(json.dumps({"NIGHTTIME_GATE_ATTRIBUTION_DIAGNOSTIC_FAILED": {
            "exception_class": type(exc).__name__,
            "failure_phase": exc.phase,
            "validation_error_codes": exc.codes,
            "coordinate_free": True,
            "evaluated_metric_values_included": False,
            "spatial_arrays_included": False,
            "acceptance_claimed": False,
        }}, sort_keys=True), flush=True)
        return 2
    except Exception as exc:
        print(json.dumps({"NIGHTTIME_GATE_ATTRIBUTION_DIAGNOSTIC_FAILED": True,
                          "exception_class": type(exc).__name__,
                          "acceptance_claimed": False}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
