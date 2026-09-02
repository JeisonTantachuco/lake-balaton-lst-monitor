#!/usr/bin/env python3
"""Bounded, coordinate-free AUDIT-012 nighttime QA A/B/C comparison.

The completed audit and AUDIT-011 implementations are imported only through
byte pins.  This runner evaluates the three approved candidates together for
each date/treatment and never reads or writes the completed audit checkpoint.
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
import statistics
import sys
import tempfile
import time
from typing import Any
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
AUDIT_RUNNER_PATH = ROOT / "tools" / "run_whole_lake_boundary_shoreline_audit_ee.py"
AUDIT011_RUNNER_PATH = ROOT / "tools" / "run_nighttime_gate_attribution_diagnostic_ee.py"
EXPECTED_AUDIT_RUNNER_SHA256 = "0e6c33277c2180db756d7ccfd6bf7c0cf9a5895c1ff07384fbd64ac7cf9d218f"
EXPECTED_AUDIT011_RUNNER_SHA256 = "437c1b03f73cfec2a11eb50b86b236b0fe64574aa2e79c4b012a0d16f377bb9a"
IMPLEMENTATION = "nighttime_qa_candidate_comparison_python_api_v14_h19v04_date_batched_comparison"
SPECIFICATION = "AUDIT-012_2026-08-28"
REQUEST_WALL_LIMIT_SECONDS = 480.000
EE_CLIENT_REQUEST_DEADLINE_SECONDS = 480
TRANSPORT_MAX_ATTEMPTS = 1
SESSION_LIMIT_SECONDS = 165 * 60
# Comparison requests are split into 2-date batches (see DATE_BATCHES), each well
# under the Earth Engine concurrency ceiling and well under the per-request memory
# capacity.  A short drain pause before each batch keeps back-to-back load low.  A
# pause is a bounded wait, not a retry -- each batch is still one attempt with no
# automatic retry -- and the independent 165-minute session ceiling (enforced by
# both this runner and the supervisor) still bounds total runtime.
COMPARISON_REQUEST_PAUSE_SECONDS = 8.0
NIGHT_STREAM_IDS = ("terra_night", "aqua_night")
SAMPLE_LIMIT = 16
CMR_ENDPOINT = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
CMR_HOST = "cmr.earthdata.nasa.gov"
CMR_CONCEPTS_PREFIX = "/search/concepts/"
ALLOWED_DOWNLOAD_HOST = "data.lpdaac.earthdatacloud.nasa.gov"
# LP DAAC Earthdata Cloud answers an authenticated protected-granule GET with a
# 302 to a short-lived signed download URL -- observed 2026-09-01 to be the LP
# DAAC egress CloudFront distribution (`*.cloudfront.net`), and for other DAACs a
# pre-signed AWS S3 URL.  The credential is in the URL query string.  There is no
# zero-redirect way to fetch a protected granule.  The HDF download follows AT
# MOST TWO hops, each only to an allowed NASA-egress host (CloudFront, AWS S3, or
# LP DAAC itself) whose path still carries the granule `.hdf` file name; the
# bearer token is stripped after the first hop, and the downloaded bytes are
# still verified against the echo10 SHA-256 and exact byte size.  No other
# request follows any redirect.
_DOWNLOAD_REDIRECT_HOST_RE = re.compile(
    r"[a-z0-9]{1,20}\.cloudfront\.net"
    r"|(?:[a-z0-9][a-z0-9.\-]{0,62}\.)?s3(?:[.\-][a-z0-9\-]{1,20})?\.amazonaws\.com"
    r"|data\.lpdaac\.earthdatacloud\.nasa\.gov")
_MAX_DOWNLOAD_REDIRECTS = 2


def _is_allowed_download_redirect_host(host: str) -> bool:
    return bool(_DOWNLOAD_REDIRECT_HOST_RE.fullmatch(host or ""))


def _validate_hdf_redirect(base_url: str, location: Any, granule_file: str) -> str:
    if not isinstance(location, str) or not location.strip():
        raise AdmissionFailure("NASA_REDIRECT_LOCATION_MISSING")
    absolute = urllib.parse.urljoin(base_url, location.strip())
    parts = urllib.parse.urlsplit(absolute)
    last_segment = parts.path.rsplit("/", 1)[-1]
    host_ok = _is_allowed_download_redirect_host(parts.hostname or "")
    # The granule .hdf file name must survive as a full path segment (NASA's
    # egress preserves the object key); a 43-character name plus the echo10
    # checksum/size check on the bytes makes this a safe integrity gate.
    object_ok = bool(granule_file) and granule_file in parts.path.split("/")
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or \
       parts.fragment or not host_ok or not object_ok:
        # Host + path only (the query string is a credential); neither is a
        # coordinate.  Makes a wrong-target failure diagnosable without a re-run.
        print(json.dumps({"NIGHTTIME_QA_HDF_REDIRECT_REJECTED": {
            "redirect_scheme": parts.scheme, "redirect_host": parts.hostname or "",
            "redirect_object": last_segment, "host_allowed": host_ok,
            "object_matches_granule": object_ok,
        }}, sort_keys=True), flush=True)
        raise AdmissionFailure("NASA_REDIRECT_TARGET_NOT_ALLOWED")
    return absolute
HDF_READER_VERSION = "pyhdf_0.11.7"
EXPECTED_MODIS_TILE = {"h": 19, "v": 4, "tile_id": "h19v04"}
_AUDIT_CONTRACT: Any = None
_AUDIT011_CONTRACT: Any = None
WINDOWS = (
    {"window_id": "winter_2024", "season": "winter", "start": "2024-01-15", "end": "2024-01-29"},
    {"window_id": "spring_2024", "season": "spring", "start": "2024-04-15", "end": "2024-04-29"},
    {"window_id": "summer_2024", "season": "summer", "start": "2024-07-15", "end": "2024-07-29"},
    {"window_id": "autumn_2024", "season": "autumn", "start": "2024-10-15", "end": "2024-10-29"},
)
CANDIDATES = {
    "A": "V_and_M0_detailed_flags_reported_not_gating",
    "B": "V_and_M01_and_D0_and_E0_and_T0",
    "C": "V_and_M01_and_D0_and_E_le1_and_T_le1",
}
GROUPS = ("A_intersection_B", "A_only", "B_only", "B", "C_minus_B")
VARIABLES = ("temperature_c", "view_time_hours", "view_angle_degrees", "clear_night_cov_scaled")
WINDOW_DATE_COUNT = 14
# Each comparison request fans out into ~120 concurrent Earth Engine aggregations
# per date (14 metrics + two 256-bin QC histograms + two 6-bin cross-tabs + 20
# exact Type-7 value-list reductions).  Evaluating all 14 dates in one request
# (~1,500 aggregations) trips a 429 "Too many concurrent aggregations" under load;
# 5-date batches cleared that but a run on 2026-09-01 then hit "Earth Engine
# memory capacity exceeded" on a single 5-date batch -- a per-request compute-size
# limit that also varies with service load.  Fixed 2-date batches keep every
# request far under both the concurrency ceiling and the memory ceiling regardless
# of load.  The 14 per-date records are reassembled in Python before validation;
# nothing about the graph, the masks, the candidate definitions, or the evidence
# changes.
COMPARISON_DATE_BATCH_SIZE = 2
DATE_BATCHES = tuple(
    tuple(range(start, min(start + COMPARISON_DATE_BATCH_SIZE, WINDOW_DATE_COUNT)))
    for start in range(0, WINDOW_DATE_COUNT, COMPARISON_DATE_BATCH_SIZE))
EARLIEST_ANOMALY_PROBE_REQUESTS = 8
_COMPARISON_REQUESTS = 32 * len(DATE_BATCHES)
REQUEST_DECOMPOSITION = {
    "canonical_metadata_requests": 4,
    "runtime_fixture_requests": 1,
    "projection_inventory_requests": 8,
    "earliest_anomaly_probe_requests": EARLIEST_ANOMALY_PROBE_REQUESTS,
    "comparison_requests": _COMPARISON_REQUESTS,
    "comparison_date_batch_size": COMPARISON_DATE_BATCH_SIZE,
    "comparison_batches_per_treatment": len(DATE_BATCHES),
    "comparison_rows_per_request": COMPARISON_DATE_BATCH_SIZE,
    "assembled_rows_per_treatment": WINDOW_DATE_COUNT,
    "treatments_per_observation": 4,
    "earth_engine_requests": 4 + 1 + 8 + EARLIEST_ANOMALY_PROBE_REQUESTS + _COMPARISON_REQUESTS,
    "nasa_source_requests_min": 0,
    "nasa_source_requests_max": 24,
    "nasa_requests_per_selected_anomaly": 3,
    "nasa_source_request_sequence_per_anomaly": (
        "cmr_umm_json_search|cmr_echo10_checksum|authenticated_hdf_download"),
    "source_samples_per_selected_granule_max": SAMPLE_LIMIT,
    "sampled_dates_per_stream_season_max": 1,
    "nonselected_dates_aggregate_only": True,
    "http_redirects_allowed": "hdf_download_only_up_to_two_validated_hops_to_nasa_egress",
    "sequential": True,
    "automatic_retry": False,
}


class AdmissionFailure(RuntimeError):
    def __init__(self, code: str):
        if not re.fullmatch(r"[A-Z0-9_:.-]{1,180}", code):
            raise RuntimeError("UNSAFE_ADMISSION_CODE")
        super().__init__(code)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def _load(path: Path, expected: str, name: str) -> Any:
    if sha256_file(path) != expected:
        raise RuntimeError(name + "_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location(name.casefold(), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(name + "_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if sha256_file(path) != expected:
        raise RuntimeError(name + "_CHANGED_DURING_IMPORT")
    return module


def load_audit() -> Any:
    global _AUDIT_CONTRACT
    if sha256_file(AUDIT_RUNNER_PATH) != EXPECTED_AUDIT_RUNNER_SHA256:
        raise RuntimeError("PINNED_AUDIT010_SHA256_MISMATCH")
    if _AUDIT_CONTRACT is None:
        _AUDIT_CONTRACT = _load(
            AUDIT_RUNNER_PATH, EXPECTED_AUDIT_RUNNER_SHA256, "PINNED_AUDIT010")
    return _AUDIT_CONTRACT


def load_audit011() -> Any:
    global _AUDIT011_CONTRACT
    if sha256_file(AUDIT011_RUNNER_PATH) != EXPECTED_AUDIT011_RUNNER_SHA256:
        raise RuntimeError("PINNED_AUDIT011_SHA256_MISMATCH")
    if _AUDIT011_CONTRACT is None:
        _AUDIT011_CONTRACT = _load(
            AUDIT011_RUNNER_PATH, EXPECTED_AUDIT011_RUNNER_SHA256, "PINNED_AUDIT011")
    return _AUDIT011_CONTRACT


def dates(window: dict[str, str]) -> list[str]:
    start, end = dt.date.fromisoformat(window["start"]), dt.date.fromisoformat(window["end"])
    return [(start + dt.timedelta(days=index)).isoformat()
            for index in range((end - start).days)]


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def qc_components(qc_byte: int) -> tuple[int, int, int, int]:
    if not isinstance(qc_byte, int) or isinstance(qc_byte, bool) or not 0 <= qc_byte <= 255:
        raise ValueError("QC_BYTE_RANGE_FAILED")
    return qc_byte & 3, (qc_byte >> 2) & 3, (qc_byte >> 4) & 3, (qc_byte >> 6) & 3


def candidate_membership(qc_byte: int) -> dict[str, bool]:
    m, d, e, t = qc_components(qc_byte)
    return {
        "A": m == 0,
        "B": m in (0, 1) and d == 0 and e == 0 and t == 0,
        "C": m in (0, 1) and d == 0 and e <= 1 and t <= 1,
        "B_M0": m == 0 and d == 0 and e == 0 and t == 0,
        "B_M1": m == 1 and d == 0 and e == 0 and t == 0,
        "C_minus_B_M0": m == 0 and d == 0 and e <= 1 and t <= 1 and not (e == 0 and t == 0),
        "C_minus_B_M1": m == 1 and d == 0 and e <= 1 and t <= 1 and not (e == 0 and t == 0),
        "M0_D_gt0": m == 0 and d > 0,
        "M1_D0": m == 1 and d == 0,
        "M1_D1": m == 1 and d == 1,
        "M1_D2": m == 1 and d == 2,
        "M1_D3": m == 1 and d == 3,
        "D1_diagnostic": d == 1,
    }


def validate_coordinate_free(value: Any) -> None:
    global _AUDIT011_CONTRACT
    if _AUDIT011_CONTRACT is None:
        _AUDIT011_CONTRACT = load_audit011()
    _AUDIT011_CONTRACT.validate_coordinate_free(value)


def _fixed_histogram(groups: Any, length: int, ee: Any, value_name: str) -> Any:
    dictionary = ee.Dictionary(ee.List(groups).iterate(
        lambda item, acc: ee.Dictionary(acc).set(
            ee.Number(ee.Dictionary(item).get(value_name)).format("%d"),
            ee.Dictionary(item).get("sum")), ee.Dictionary({})))
    return ee.List.sequence(0, length - 1).map(
        lambda value: ee.Number(dictionary.get(ee.Number(value).format("%d"), 0)).toDouble())


def _area_histogram(runner: Any, value: Any, mask: Any, length: int,
                    geometry: Any, context: dict[str, Any], value_name: str) -> Any:
    ee = runner.ee
    image = ee.Image.pixelArea().rename("area_m2").addBands(
        value.rename(value_name)).updateMask(mask)
    reduced = ee.Dictionary(runner._reduce(
        image, ee.Reducer.sum().group(groupField=1, groupName=value_name), geometry, context))
    return _fixed_histogram(reduced.get("groups", ee.List([])), length, ee, value_name)


def _distribution(runner: Any, image: Any, mask: Any, geometry: Any,
                  context: dict[str, Any], name: str) -> Any:
    ee = runner.ee
    member_count = runner._count(mask, geometry, context, name + "_member_count")
    available = mask.And(image.mask().unmask(0).gt(0)).unmask(0)
    count = runner._count(available, geometry, context, name + "_value_count")
    area = runner._sum_area(available, geometry, context, name + "_area")
    raw_values = ee.Dictionary(runner._reduce(
        image.rename(name).updateMask(mask), ee.Reducer.toList(), geometry, context)).get(
            name, ee.List([]))
    ordered = ee.List(raw_values).sort()
    size = ordered.length()
    positive = size.gt(0)
    # ``ee.Algorithms.If`` evaluates both branches, so any ``.get()`` on an empty
    # list raises server-side even when the guard is false.  Index a list that is
    # always non-empty and null every value-derived statistic out for empty groups;
    # the counts above stay real (0) and the estimator is unchanged when size > 0.
    safe = ee.List(ee.Algorithms.If(positive, ordered, ee.List([0])))
    safe_size = safe.length()
    def exact_type7(probability: float) -> Any:
        h = safe_size.subtract(1).multiply(probability)
        lower = h.floor().toInt()
        upper = h.ceil().toInt()
        weight = h.subtract(lower)
        interpolated = ee.Number(safe.get(lower)).multiply(
            ee.Number(1).subtract(weight)).add(ee.Number(safe.get(upper)).multiply(weight))
        return ee.Algorithms.If(positive, interpolated, None)
    return ee.Dictionary({
        "member_pixel_center_count": member_count,
        "value_pixel_center_count": count, "type7_value_list_count": size,
        "value_area_m2": area,
        "quantile_method": "Type-7_h=(n-1)p_linear_interpolation",
        "mean": ee.Algorithms.If(positive, ordered.reduce(ee.Reducer.mean()), None),
        "min": ee.Algorithms.If(positive, safe.get(0), None),
        "max": ee.Algorithms.If(positive, safe.get(safe_size.subtract(1)), None),
        "p05_type7": exact_type7(0.05), "p25_type7": exact_type7(0.25),
        "p50_type7": exact_type7(0.50), "p75_type7": exact_type7(0.75),
        "p95_type7": exact_type7(0.95),
    })


class ComparisonRunner:
    def __init__(self, audit: Any, ee: Any, geometry_json: dict[str, Any],
                 source_record: dict[str, Any], request_options: dict[str, Any]):
        diagnostic = load_audit011()
        self._delegate = diagnostic.NighttimeDiagnosticRunner(
            audit, ee, geometry_json, source_record, request_options)
        self.audit, self.ee, self.source_record = audit, ee, source_record
        self.source, self.contexts = self._delegate.source, self._delegate.contexts
        self.projection_certifications = self._delegate.projection_certifications
        self.request_options = request_options

    @property
    def streams(self) -> list[dict[str, Any]]:
        return self._delegate.streams

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def _source_data(self, stream: dict[str, Any], date_utc: str) -> dict[str, Any]:
        ee = self.ee
        start = ee.Date(date_utc)
        collection = ee.ImageCollection(stream["collection_id"]).filterDate(
            start, start.advance(1, "day")).sort("system:time_start")
        count = collection.size()
        bands = [stream[key] for key in ("lst", "qc", "time", "angle", "clear")]
        fallback = ee.Image.constant([0] * 5).rename(bands).updateMask(ee.Image.constant(0))
        image = ee.Image(ee.Algorithms.If(count.eq(1), collection.first(), fallback))
        lst, qc = image.select(stream["lst"]), image.select(stream["qc"])
        view_time, view_angle, clear = (image.select(stream[key]) for key in ("time", "angle", "clear"))
        decoded = self._masks(image, stream)["decoded"]
        q = qc.toUint8()
        m, d, e, t = (decoded.select(name).unmask(0) for name in
                      ("mandatory_qa", "data_quality", "emissivity_error", "lst_error"))
        qc_valid = qc.mask().unmask(0).gt(0)
        lst_valid = self._validity(lst, 7500, 65535)
        time_valid = self._validity(view_time, 0, 240)
        angle_valid = self._validity(view_angle, 0, 130)
        V = qc_valid.And(lst_valid).And(time_valid).And(angle_valid).unmask(0)
        A = V.And(m.eq(0)).unmask(0)
        B = V.And(m.lte(1)).And(d.eq(0)).And(e.eq(0)).And(t.eq(0)).unmask(0)
        C = V.And(m.lte(1)).And(d.eq(0)).And(e.lte(1)).And(t.lte(1)).unmask(0)
        return {"collection": collection, "count": count, "image": image,
                "lst": lst, "qc": qc, "view_time": view_time,
                "view_angle": view_angle, "clear": clear, "q": q, "m": m,
                "d": d, "e": e, "t": t, "qc_valid": qc_valid,
                "lst_valid": lst_valid, "V": V, "A": A, "B": B, "C": C,
                "M0_D_gt0": V.And(m.eq(0)).And(d.gt(0)).unmask(0)}

    def _treatment_geometry(self, stream: dict[str, Any], treatment: dict[str, Any]) -> tuple[Any, Any]:
        ee = self.ee
        source_geometry = self.source.transform(proj=self.audit.OP_CRS, maxError=self._margin())
        distance = ee.Number(treatment["distance_m"])
        geometry = ee.Geometry(ee.Algorithms.If(
            distance.eq(0), source_geometry,
            source_geometry.buffer(distance.multiply(-1), self._margin(), self.audit.OP_CRS)))
        return geometry, self.context_for_candidate(stream, geometry)

    def earliest_anomaly_position(self, window: dict[str, str], stream: dict[str, Any]) -> Any:
        """One lightweight request: the earliest date position (0..13) whose M0&D>0
        pixel-CENTRE count in the original 0 m geometry is positive, else -1.  The
        heavy per-date-batch graph then samples only that position.  This is the
        SAME predicate select_source_verifications() uses in Python."""
        ee = self.ee
        geometry, context = self._treatment_geometry(
            stream, next(t for t in self.audit.TREATMENTS if t["erosion_id"] == "EROSION_0000M"))
        date_values = dates(window)
        counts = [self._count(self._source_data(stream, date_utc)["M0_D_gt0"],
                              geometry, context, f"earliest_anomaly_probe_{position}")
                  for position, date_utc in enumerate(date_values)]
        flagged = ee.List([ee.Algorithms.If(ee.Number(count).gt(0), position, len(date_values))
                           for position, count in enumerate(counts)])
        earliest = ee.Number(flagged.reduce(ee.Reducer.min()))
        return ee.Dictionary({
            "window_id": window["window_id"], "stream_id": stream["stream_id"],
            "date_count": len(date_values),
            "position": ee.Number(ee.Algorithms.If(
                earliest.lt(len(date_values)), earliest, -1)).toInt(),
            "coordinate_free": True,
        })

    def graph(self, window: dict[str, str], stream: dict[str, Any],
              treatment: dict[str, Any], positions: "list[int]",
              earliest_position: int) -> Any:
        ee = self.ee
        geometry, context = self._treatment_geometry(stream, treatment)
        eligible = ee.Number(context["eligible_roi_area_m2"])
        date_values = dates(window)
        prepared = {position: self._source_data(stream, date_values[position])
                    for position in positions}
        earliest_anomaly_index = ee.Number(earliest_position)

        def one_date(index: int, date_utc: str, data: dict[str, Any]) -> Any:
            count, image = data["count"], data["image"]
            lst, qc = data["lst"], data["qc"]
            view_time, view_angle, clear = data["view_time"], data["view_angle"], data["clear"]
            q, m, d, e, t = data["q"], data["m"], data["d"], data["e"], data["t"]
            qc_valid, lst_valid = data["qc_valid"], data["lst_valid"]
            V, A, B, C = data["V"], data["A"], data["B"], data["C"]
            masks = {
                "V": V, "A": A, "B": B, "C": C,
                "B_M0": B.And(m.eq(0)), "B_M1": B.And(m.eq(1)),
                "C_minus_B_M0": C.And(B.Not()).And(m.eq(0)),
                "C_minus_B_M1": C.And(B.Not()).And(m.eq(1)),
                "M0_D_gt0": data["M0_D_gt0"],
                "M1_D0": V.And(m.eq(1)).And(d.eq(0)),
                "M1_D1": V.And(m.eq(1)).And(d.eq(1)),
                "M1_D2": V.And(m.eq(1)).And(d.eq(2)),
                "M1_D3": V.And(m.eq(1)).And(d.eq(3)),
                "D1_diagnostic": V.And(d.eq(1)),
            }
            group_masks = {
                "A_intersection_B": A.And(B), "A_only": A.And(B.Not()),
                "B_only": B.And(A.Not()), "B": B, "C_minus_B": C.And(B.Not()),
            }
            def metric(name: str, mask: Any) -> Any:
                # One _sum_area per mask: coverage_fraction is that area / eligible,
                # not an independent reduction (halves the metric aggregations and
                # makes coverage_fraction == area_m2 / eligible exactly).
                area = self._sum_area(mask, geometry, context, name + "_area")
                return ee.Dictionary({
                    "name": name,
                    "pixel_center_count": self._count(mask, geometry, context, name + "_count"),
                    "area_m2": area,
                    "coverage_fraction": area.divide(eligible),
                })
            qc_count = self._frequency(q, V, 256, geometry, context)
            qc_area = _area_histogram(self, q, V, 256, geometry, context, "qc_byte")
            cross_code = qc_valid.toInt().multiply(3).add(
                lst.mask().unmask(0).gt(0).multiply(ee.Image(1).add(lst_valid.toInt())))
            cross_count = self._frequency(cross_code, ee.Image.constant(1), 6, geometry, context)
            cross_area = _area_histogram(self, cross_code, ee.Image.constant(1), 6,
                                         geometry, context, "cross_code")
            temperature = lst.multiply(0.02).subtract(273.15)
            variables = {
                "temperature_c": temperature,
                "view_time_hours": view_time.multiply(0.1),
                "view_angle_degrees": view_angle.subtract(65),
                "clear_night_cov_scaled": clear.multiply(0.0005),
            }
            distributions = ee.List([
                ee.Dictionary({"group": group, "variable": variable,
                               "statistics": _distribution(
                                   self, variables[variable], group_masks[group], geometry,
                                   context, group + "__" + variable)})
                for group in GROUPS for variable in VARIABLES
            ])
            sample_properties = [
                "global_x", "global_y", "qc_raw", "lst_raw", "view_time_raw",
                "view_angle_raw", "clear_raw", "qc_mask", "lst_mask",
                "view_time_mask", "view_angle_mask", "clear_mask",
            ]
            transient_samples: Any = ee.List([])
            if treatment["erosion_id"] == "EROSION_0000M":
                anomaly = masks["M0_D_gt0"].And(earliest_anomaly_index.eq(index)).unmask(0)
                pixel_indices = ee.Image.pixelCoordinates(ee.Projection(
                    context["crs"], context["transform"]))
                raw_and_masks = ee.Image.cat([
                    # pixelCoordinates returns pixel-CENTRE coordinates (index + 0.5);
                    # floor to the integer global grid index the tile derivation needs.
                    pixel_indices.select("x").floor().rename("global_x"),
                    pixel_indices.select("y").floor().rename("global_y"),
                    qc.unmask(-1).rename("qc_raw"), lst.unmask(-1).rename("lst_raw"),
                    view_time.unmask(-1).rename("view_time_raw"),
                    view_angle.unmask(-1).rename("view_angle_raw"),
                    clear.unmask(-1).rename("clear_raw"),
                    qc_valid.rename("qc_mask"), lst.mask().unmask(0).gt(0).rename("lst_mask"),
                    view_time.mask().unmask(0).gt(0).rename("view_time_mask"),
                    view_angle.mask().unmask(0).gt(0).rename("view_angle_mask"),
                    clear.mask().unmask(0).gt(0).rename("clear_mask"),
                ]).updateMask(anomaly)
                # Deterministic, exhaustive extraction of the (rare) anomaly pixels
                # in native-grid scan order.  Random ``Image.sample`` with a small
                # numPixels misses a 1-2 pixel mask; ``Reducer.toList`` returns every
                # unmasked pixel, and we keep the first SAMPLE_LIMIT.
                lists = ee.Dictionary(self._reduce(
                    raw_and_masks, ee.Reducer.toList(), geometry, context))
                available = ee.Number(ee.List(lists.get("global_x", ee.List([]))).length())
                keep = available.min(SAMPLE_LIMIT)
                transient_samples = ee.List(ee.Algorithms.If(
                    keep.gt(0),
                    ee.List.sequence(0, keep.subtract(1)).map(
                        lambda position: ee.Dictionary.fromLists(
                            sample_properties,
                            [ee.List(lists.get(name, ee.List([]))).get(position)
                             for name in sample_properties])),
                    ee.List([])))
            certification = self.projection_certifications[(date_utc, stream["stream_id"])]
            selected_id_ok = ee.Algorithms.If(count.eq(1), self._nbool(
                ee.Algorithms.IsEqual(image.get("system:index"),
                                      certification.get("source_system_index"))).And(self._nbool(
                ee.Algorithms.IsEqual(image.id(), certification.get("source_system_index")))), False)
            errors = ee.List([])
            errors = ee.List(ee.Algorithms.If(count.eq(1), errors,
                                               errors.add("SOURCE_IMAGE_COUNT_NOT_EXACTLY_ONE")))
            errors = ee.List(ee.Algorithms.If(selected_id_ok, errors,
                                               errors.add("SOURCE_IDENTITY_MISMATCH")))
            errors = ee.List(ee.Algorithms.If(eligible.gt(0), errors,
                                               errors.add("NONPOSITIVE_ELIGIBLE_AREA")))
            return ee.Dictionary({
                "date_utc": date_utc, "window_id": window["window_id"],
                "stream_id": stream["stream_id"], "erosion_id": treatment["erosion_id"],
                "source_image_count": count.toInt64(),
                "source_image_id": ee.Algorithms.If(count.eq(1), image.id(), None),
                "source_system_index": certification.get("source_system_index"),
                "projection_inventory_source_image_id": certification.get("source_image_id"),
                "source_identity_matches_projection_inventory": self._boolean(selected_id_ok),
                "eligible_area_m2": eligible,
                "eligible_pixel_center_count": ee.Number(context["eligible_pixel_center_count"]).toInt64(),
                "candidate_and_tier_metrics": ee.List([metric(name, mask) for name, mask in masks.items()]),
                "qc_byte_pixel_count_histogram_conditional_on_V": qc_count,
                "qc_byte_area_histogram_m2_conditional_on_V": qc_area,
                "qc_lst_mask_range_cross_tab_labels": [
                    "qc_masked_lst_masked", "qc_masked_lst_observed_out_of_range",
                    "qc_masked_lst_valid", "qc_observed_lst_masked",
                    "qc_observed_lst_observed_out_of_range", "qc_observed_lst_valid"],
                "qc_lst_mask_range_cross_tab_pixel_counts": cross_count,
                "qc_lst_mask_range_cross_tab_areas_m2": cross_area,
                "group_distributions": distributions,
                "transient_original_hdf_samples": transient_samples,
                "validation_errors": errors.distinct().sort(),
            })

        records = ee.List([one_date(position, date_values[position], prepared[position])
                           for position in positions])
        return ee.Dictionary({
            "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
            "window_id": window["window_id"], "season": window["season"],
            "stream_id": stream["stream_id"], "erosion_id": treatment["erosion_id"],
            "erosion_distance_m": treatment["distance_m"],
            "date_positions": list(positions), "date_count": records.length(),
            "records": records, "candidate_definitions": CANDIDATES,
            "coordinate_free": True, "validation_errors": ee.List([]),
        })


# ``NighttimeDiagnosticRunner`` (AUDIT-011) delegates most native-grid/QA
# primitives from the pinned AUDIT-010 ``AuditRunner``, but its delegation list
# omits ``_frequency`` — which ``graph()`` needs for the fixed 256-bin QC-byte
# histogram and the 6-bin QC/LST cross-tab.  Bind it here from the same pinned
# source; ``AuditRunner._frequency`` uses only ``self.ee`` and ``self._reduce``,
# both resolvable on a ``ComparisonRunner`` instance.
ComparisonRunner._frequency = load_audit().AuditRunner._frequency


METRIC_NAMES = (
    "V", "A", "B", "C", "B_M0", "B_M1", "C_minus_B_M0", "C_minus_B_M1",
    "M0_D_gt0", "M1_D0", "M1_D1", "M1_D2", "M1_D3", "D1_diagnostic",
)
CROSS_TAB_LABELS = (
    "qc_masked_lst_masked", "qc_masked_lst_observed_out_of_range",
    "qc_masked_lst_valid", "qc_observed_lst_masked",
    "qc_observed_lst_observed_out_of_range", "qc_observed_lst_valid",
)


def _validate_distribution(item: Any, expected_count: int, errors: list[str]) -> None:
    keys = {"member_pixel_center_count", "value_pixel_center_count", "type7_value_list_count",
            "value_area_m2", "quantile_method",
            "mean", "min", "max", "p05_type7", "p25_type7", "p50_type7",
            "p75_type7", "p95_type7"}
    if not isinstance(item, dict) or set(item) != keys:
        errors.append("DISTRIBUTION_SHAPE_FAILED")
        return
    if item["member_pixel_center_count"] != expected_count or not isinstance(
            item["member_pixel_center_count"], int) or isinstance(
                item["member_pixel_center_count"], bool):
        errors.append("DISTRIBUTION_COUNT_IDENTITY_FAILED")
    value_count = item["value_pixel_center_count"]
    if not isinstance(value_count, int) or isinstance(value_count, bool) or \
       not 0 <= value_count <= expected_count:
        errors.append("DISTRIBUTION_VALUE_COUNT_FAILED")
        value_count = -1
    if item["type7_value_list_count"] != value_count or \
       item["quantile_method"] != "Type-7_h=(n-1)p_linear_interpolation":
        errors.append("DISTRIBUTION_TYPE7_METHOD_OR_COUNT_FAILED")
    if not finite(item["value_area_m2"]) or item["value_area_m2"] < 0:
        errors.append("DISTRIBUTION_AREA_FAILED")
    statistics_keys = ("mean", "min", "max", "p05_type7", "p25_type7",
                       "p50_type7", "p75_type7", "p95_type7")
    if value_count == 0:
        if any(item[name] is not None for name in statistics_keys):
            errors.append("EMPTY_DISTRIBUTION_NOT_NULL")
    elif any(not finite(item[name]) for name in statistics_keys):
        errors.append("DISTRIBUTION_NONFINITE")
    else:
        # Type-7 interpolation (v*w + v*(1-w)) carries sub-ULP rounding, so the
        # ordered chain and the mean bound are checked with a small relative
        # tolerance; a genuine ordering fault is orders of magnitude larger.
        ordered_stats = [item["min"], item["p05_type7"], item["p25_type7"],
                         item["p50_type7"], item["p75_type7"], item["p95_type7"], item["max"]]
        tol = max([1.0] + [abs(v) for v in ordered_stats]) * 1e-9
        if not all(a <= b + tol for a, b in zip(ordered_stats, ordered_stats[1:])) or \
           not item["min"] - tol <= item["mean"] <= item["max"] + tol:
            errors.append("DISTRIBUTION_TYPE7_OR_MEAN_RANGE_FAILED")


def validate_record(record: Any, expected_date: str, window_id: str, stream_id: str,
                    erosion_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    transient: list[dict[str, Any]] = []
    if not isinstance(record, dict):
        return ["RECORD_NOT_OBJECT"], transient
    transient_value = record.pop("transient_original_hdf_samples", None)
    if transient_value is not None:
        if not isinstance(transient_value, list) or len(transient_value) > SAMPLE_LIMIT:
            errors.append("TRANSIENT_SAMPLE_COUNT_FAILED")
        elif erosion_id != "EROSION_0000M" and transient_value:
            errors.append("TRANSIENT_SAMPLE_NONORIGINAL_TREATMENT")
        else:
            transient = transient_value
    required = {
        "date_utc", "window_id", "stream_id", "erosion_id", "source_image_count",
        "source_image_id", "source_system_index", "projection_inventory_source_image_id",
        "source_identity_matches_projection_inventory",
        "eligible_area_m2", "eligible_pixel_center_count", "candidate_and_tier_metrics",
        "qc_byte_pixel_count_histogram_conditional_on_V",
        "qc_byte_area_histogram_m2_conditional_on_V",
        "qc_lst_mask_range_cross_tab_labels", "qc_lst_mask_range_cross_tab_pixel_counts",
        "qc_lst_mask_range_cross_tab_areas_m2", "group_distributions", "validation_errors",
    }
    if set(record) != required:
        return errors + ["RECORD_SHAPE_FAILED"], transient
    if (record["date_utc"], record["window_id"], record["stream_id"], record["erosion_id"]) != (
            expected_date, window_id, stream_id, erosion_id):
        errors.append("RECORD_IDENTITY_FAILED")
    expected_ee_id = expected_date.replace("-", "_")
    collection_id = {"terra_night": "MODIS/061/MOD11A1",
                     "aqua_night": "MODIS/061/MYD11A1"}.get(stream_id)
    if record["source_image_count"] != 1 or record["source_image_id"] != expected_ee_id or \
       record["source_system_index"] != expected_ee_id or \
       record["projection_inventory_source_image_id"] != collection_id + "/" + expected_ee_id:
        errors.append("SOURCE_IMAGE_EXACTLY_ONE_FAILED")
    if record["source_identity_matches_projection_inventory"] is not True:
        errors.append("SOURCE_IDENTITY_FAILED")
    eligible_area, eligible_count = record["eligible_area_m2"], record["eligible_pixel_center_count"]
    if not finite(eligible_area) or eligible_area <= 0 or not isinstance(eligible_count, int) or \
       isinstance(eligible_count, bool) or eligible_count <= 0:
        errors.append("ELIGIBLE_METRIC_FAILED")
        eligible_area, eligible_count = 1.0, 1
    metrics_raw = record["candidate_and_tier_metrics"]
    if not isinstance(metrics_raw, list) or [item.get("name") for item in metrics_raw
                                              if isinstance(item, dict)] != list(METRIC_NAMES):
        errors.append("METRIC_ORDER_FAILED")
        metrics: dict[str, dict[str, Any]] = {}
    else:
        metrics = {item["name"]: item for item in metrics_raw}
        for name, item in metrics.items():
            if set(item) != {"name", "pixel_center_count", "area_m2", "coverage_fraction"} or \
               not isinstance(item["pixel_center_count"], int) or isinstance(
                   item["pixel_center_count"], bool) or not 0 <= item["pixel_center_count"] <= eligible_count or \
               not finite(item["area_m2"]) or not 0 <= item["area_m2"] <= eligible_area or \
               not finite(item["coverage_fraction"]) or abs(
                   item["coverage_fraction"] - item["area_m2"] / eligible_area) > 1e-9:
                errors.append("METRIC_VALUE_FAILED:" + name)
        tolerance = max(1.0, eligible_area * 1e-6)
        for field in ("pixel_center_count", "area_m2"):
            tol = 0 if field == "pixel_center_count" else tolerance
            def near(left: float, right: float) -> bool:
                return abs(left - right) <= tol
            if metrics["B"][field] > metrics["C"][field] + tol:
                errors.append("B_NOT_SUBSET_C:" + field)
            if not near(metrics["B_M0"][field] + metrics["B_M1"][field], metrics["B"][field]):
                errors.append("B_TIER_PARTITION_FAILED:" + field)
            if not near(metrics["B"][field] + metrics["C_minus_B_M0"][field] +
                        metrics["C_minus_B_M1"][field], metrics["C"][field]):
                errors.append("C_TIER_PARTITION_FAILED:" + field)
    count_hist = record["qc_byte_pixel_count_histogram_conditional_on_V"]
    area_hist = record["qc_byte_area_histogram_m2_conditional_on_V"]
    if not isinstance(count_hist, list) or len(count_hist) != 256 or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in count_hist):
        errors.append("QC_COUNT_HISTOGRAM_FAILED")
    if not isinstance(area_hist, list) or len(area_hist) != 256 or any(
            not finite(value) or value < 0 for value in area_hist):
        errors.append("QC_AREA_HISTOGRAM_FAILED")
    if "metrics" in locals() and metrics and isinstance(count_hist, list) and len(count_hist) == 256:
        for name in METRIC_NAMES:
            expected = sum(count_hist[q] for q in range(256)
                           if (name == "V" or candidate_membership(q).get(name, False)))
            if metrics[name]["pixel_center_count"] != expected:
                errors.append("QC_COUNT_IDENTITY_FAILED:" + name)
    if "metrics" in locals() and metrics and isinstance(area_hist, list) and len(area_hist) == 256:
        tolerance = max(1.0, eligible_area * 1e-6)
        for name in METRIC_NAMES:
            expected = sum(float(area_hist[q]) for q in range(256)
                           if (name == "V" or candidate_membership(q).get(name, False)))
            if abs(metrics[name]["area_m2"] - expected) > tolerance:
                errors.append("QC_AREA_IDENTITY_FAILED:" + name)
    labels = record["qc_lst_mask_range_cross_tab_labels"]
    cross_counts, cross_areas = (record["qc_lst_mask_range_cross_tab_pixel_counts"],
                                 record["qc_lst_mask_range_cross_tab_areas_m2"])
    if labels != list(CROSS_TAB_LABELS) or not isinstance(cross_counts, list) or \
       len(cross_counts) != 6 or any(not isinstance(v, int) or isinstance(v, bool) or v < 0
                                     for v in cross_counts) or sum(cross_counts) != eligible_count:
        errors.append("MASK_CROSS_TAB_COUNT_FAILED")
    if not isinstance(cross_areas, list) or len(cross_areas) != 6 or any(
            not finite(v) or v < 0 for v in cross_areas) or abs(sum(cross_areas) - eligible_area) > \
            max(1.0, eligible_area * 1e-6):
        errors.append("MASK_CROSS_TAB_AREA_FAILED")
    distributions = record["group_distributions"]
    expected_pairs = [(group, variable) for group in GROUPS for variable in VARIABLES]
    if not isinstance(distributions, list) or [(item.get("group"), item.get("variable"))
                                                for item in distributions if isinstance(item, dict)] != expected_pairs:
        errors.append("GROUP_DISTRIBUTION_ORDER_FAILED")
    elif metrics:
        group_counts = {
            "A_intersection_B": sum(count_hist[q] for q in range(256)
                                      if candidate_membership(q)["A"] and candidate_membership(q)["B"]),
            "A_only": metrics["A"]["pixel_center_count"] - sum(
                count_hist[q] for q in range(256)
                if candidate_membership(q)["A"] and candidate_membership(q)["B"]),
            "B_only": metrics["B"]["pixel_center_count"] - sum(
                count_hist[q] for q in range(256)
                if candidate_membership(q)["A"] and candidate_membership(q)["B"]),
            "B": metrics["B"]["pixel_center_count"],
            "C_minus_B": metrics["C"]["pixel_center_count"] - metrics["B"]["pixel_center_count"],
        }
        for item in distributions:
            if set(item) != {"group", "variable", "statistics"}:
                errors.append("GROUP_DISTRIBUTION_SHAPE_FAILED")
            else:
                _validate_distribution(item["statistics"], group_counts[item["group"]], errors)
    if record["validation_errors"] != []:
        errors.append("SERVER_VALIDATION_ERRORS_PRESENT")
    try:
        validate_coordinate_free(record)
    except ValueError:
        errors.append("COORDINATE_FREE_VALIDATION_FAILED")
    return sorted(set(errors)), transient


def validate_result(result: Any, window: dict[str, str], stream: dict[str, Any],
                    treatment: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    required = {"specification", "implementation", "window_id", "season", "stream_id",
                "erosion_id", "erosion_distance_m", "date_count", "records",
                "candidate_definitions", "coordinate_free", "validation_errors"}
    if not isinstance(result, dict) or set(result) != required:
        return ["RESULT_SHAPE_FAILED"], []
    errors: list[str] = []
    transients: list[dict[str, Any]] = []
    if result["specification"] != SPECIFICATION or result["implementation"] != IMPLEMENTATION:
        errors.append("VERSION_FAILED")
    if (result["window_id"], result["season"], result["stream_id"], result["erosion_id"],
            result["erosion_distance_m"]) != (window["window_id"], window["season"],
                                                stream["stream_id"], treatment["erosion_id"],
                                                treatment["distance_m"]):
        errors.append("RESULT_IDENTITY_FAILED")
    records = result["records"]
    if result["date_count"] != 14 or not isinstance(records, list) or len(records) != 14:
        errors.append("RESULT_DATE_COUNT_FAILED")
    else:
        for date_utc, record in zip(dates(window), records):
            record_errors, samples = validate_record(
                record, date_utc, window["window_id"], stream["stream_id"], treatment["erosion_id"])
            errors.extend(record_errors)
            if samples:
                transients.append({"window_id": window["window_id"], "date_utc": date_utc,
                                   "stream_id": stream["stream_id"],
                                   "collection_id": stream["collection_id"],
                                   "ee_image_id": record.get("source_image_id"),
                                   "source_system_index": record.get("source_system_index"),
                                   "projection_inventory_source_image_id": record.get(
                                       "projection_inventory_source_image_id"),
                                   "samples": samples})
    if result["candidate_definitions"] != CANDIDATES or result["coordinate_free"] is not True or \
       result["validation_errors"] != []:
        errors.append("RESULT_METADATA_FAILED")
    try:
        validate_coordinate_free(result)
    except ValueError:
        errors.append("RESULT_COORDINATE_FREE_FAILED")
    return sorted(set(errors)), transients


BATCH_PIECE_KEYS = {
    "specification", "implementation", "window_id", "season", "stream_id", "erosion_id",
    "erosion_distance_m", "date_positions", "date_count", "records",
    "candidate_definitions", "coordinate_free", "validation_errors",
}


def validate_batch_piece(piece: Any, window: dict[str, str], stream: dict[str, Any],
                         treatment: dict[str, Any], positions: tuple[int, ...]) -> list[str]:
    if not isinstance(piece, dict) or set(piece) != BATCH_PIECE_KEYS:
        return ["BATCH_PIECE_SHAPE_FAILED"]
    errors: list[str] = []
    if piece["specification"] != SPECIFICATION or piece["implementation"] != IMPLEMENTATION:
        errors.append("BATCH_PIECE_VERSION_FAILED")
    if (piece["window_id"], piece["season"], piece["stream_id"], piece["erosion_id"],
            piece["erosion_distance_m"]) != (
            window["window_id"], window["season"], stream["stream_id"],
            treatment["erosion_id"], treatment["distance_m"]):
        errors.append("BATCH_PIECE_IDENTITY_FAILED")
    if piece["date_positions"] != list(positions) or piece["date_count"] != len(positions) or \
       not isinstance(piece["records"], list) or len(piece["records"]) != len(positions):
        errors.append("BATCH_PIECE_POSITIONS_FAILED")
    if piece["candidate_definitions"] != CANDIDATES or piece["coordinate_free"] is not True or \
       piece["validation_errors"] != []:
        errors.append("BATCH_PIECE_METADATA_FAILED")
    try:
        validate_coordinate_free(piece)
    except ValueError:
        errors.append("BATCH_PIECE_COORDINATE_FREE_FAILED")
    return sorted(set(errors))


def assemble_batches(pieces: list[dict[str, Any]]) -> dict[str, Any]:
    records_by_position: dict[int, Any] = {}
    for piece in pieces:
        for position, record in zip(piece["date_positions"], piece["records"]):
            if position in records_by_position:
                raise AdmissionFailure("COMPARISON_BATCH_DUPLICATE_POSITION")
            records_by_position[position] = record
    if sorted(records_by_position) != list(range(WINDOW_DATE_COUNT)):
        raise AdmissionFailure("COMPARISON_BATCH_ASSEMBLY_INCOMPLETE")
    base = pieces[0]
    return {
        "specification": base["specification"], "implementation": base["implementation"],
        "window_id": base["window_id"], "season": base["season"],
        "stream_id": base["stream_id"], "erosion_id": base["erosion_id"],
        "erosion_distance_m": base["erosion_distance_m"], "date_count": WINDOW_DATE_COUNT,
        "records": [records_by_position[position] for position in range(WINDOW_DATE_COUNT)],
        "candidate_definitions": base["candidate_definitions"],
        "coordinate_free": True, "validation_errors": [],
    }


def _json_no_duplicates(data: bytes) -> Any:
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise AdmissionFailure("NASA_JSON_DUPLICATE_KEY")
            output[key] = value
        return output
    return json.loads(data.decode("utf-8"), object_pairs_hook=hook)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _network_request(url: str, phase: str, headers: dict[str, str],
                     session_deadline: float, maximum_bytes: int,
                     redirect_object_name: "str | None" = None) -> tuple[
                         bytes, dict[str, str], dict[str, Any]]:
    if time.monotonic() >= session_deadline:
        raise AdmissionFailure("SESSION_CEILING_BEFORE_SOURCE_REQUEST")
    print(json.dumps({"SOURCE_REQUEST_START": {
        "phase": phase, "attempt": 1, "max_attempts": 1,
        "request_deadline_seconds": EE_CLIENT_REQUEST_DEADLINE_SECONDS,
    }}, sort_keys=True), flush=True)
    started = time.monotonic()
    redirect_count = 0
    current_url = url
    current_headers = dict(headers)
    try:
        while True:
            opener = urllib.request.build_opener(_NoRedirect())
            request = urllib.request.Request(current_url, headers=current_headers, method="GET")
            try:
                response = opener.open(request, timeout=EE_CLIENT_REQUEST_DEADLINE_SECONDS)
            except urllib.error.HTTPError as exc:
                if redirect_object_name is not None and \
                   redirect_count < _MAX_DOWNLOAD_REDIRECTS and 300 <= exc.code < 400:
                    location = exc.headers.get("Location")
                    exc.close()
                    current_url = _validate_hdf_redirect(
                        current_url, location, redirect_object_name)
                    # Never carry the Earthdata bearer token past the first hop;
                    # the signed download URL authenticates itself in its query.
                    current_headers = {"User-Agent": headers.get(
                        "User-Agent", "lake-balaton-audit012/1")}
                    redirect_count += 1
                    if time.monotonic() - started >= REQUEST_WALL_LIMIT_SECONDS:
                        raise AdmissionFailure("SOURCE_REQUEST_WALL_LIMIT_REACHED")
                    continue
                raise
            with response:
                status = getattr(response, "status", None)
                final_url = response.geturl()
                if status != 200 or final_url != current_url:
                    raise AdmissionFailure("NASA_HTTP_STATUS_FAILED")
                response_headers = {key.casefold(): value
                                    for key, value in response.headers.items()}
                chunks: list[bytes] = []
                total = 0
                while True:
                    block = response.read(min(1024 * 1024, maximum_bytes + 1 - total))
                    if not block:
                        break
                    total += len(block)
                    if total > maximum_bytes:
                        raise AdmissionFailure("NASA_RESPONSE_SIZE_LIMIT")
                    chunks.append(block)
                data = b"".join(chunks)
            break
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - started
        category = "redirect_forbidden" if 300 <= exc.code < 400 else "source_http_failure"
        print(json.dumps({"SOURCE_REQUEST_FAILED": {
            "phase": phase, "attempt": 1, "elapsed_seconds": elapsed,
            "exception_category": category,
        }}, sort_keys=True), flush=True)
        raise AdmissionFailure("NASA_REDIRECT_FORBIDDEN" if 300 <= exc.code < 400
                               else "NASA_HTTP_STATUS_FAILED")
    except AdmissionFailure:
        elapsed = time.monotonic() - started
        print(json.dumps({"SOURCE_REQUEST_FAILED": {
            "phase": phase, "attempt": 1, "elapsed_seconds": elapsed,
            "exception_category": "source_admission_failure",
        }}, sort_keys=True), flush=True)
        raise
    except Exception:
        elapsed = time.monotonic() - started
        print(json.dumps({"SOURCE_REQUEST_FAILED": {
            "phase": phase, "attempt": 1, "elapsed_seconds": elapsed,
            "exception_category": "source_transport_failure",
        }}, sort_keys=True), flush=True)
        raise AdmissionFailure("NASA_SOURCE_TRANSPORT_FAILED")
    elapsed = time.monotonic() - started
    if elapsed >= REQUEST_WALL_LIMIT_SECONDS or time.monotonic() >= session_deadline:
        raise AdmissionFailure("SOURCE_REQUEST_WALL_LIMIT_REACHED")
    print(json.dumps({"SOURCE_REQUEST_COMPLETE": {
        "phase": phase, "attempt": 1, "elapsed_seconds": elapsed,
    }}, sort_keys=True), flush=True)
    requested_parts = urllib.parse.urlsplit(url)
    final_parts = urllib.parse.urlsplit(final_url)
    return data, response_headers, {
        "transaction_count": 1, "redirect_count": redirect_count,
        "requested_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        "final_url_sha256": hashlib.sha256(final_url.encode("utf-8")).hexdigest(),
        "exact_final_url": final_url == url,
        "requested_scheme": requested_parts.scheme, "requested_host": requested_parts.hostname,
        "requested_path": requested_parts.path,
        "requested_query_sha256": hashlib.sha256(
            requested_parts.query.encode("utf-8")).hexdigest(),
        "requested_query_present": bool(requested_parts.query),
        "final_scheme": final_parts.scheme, "final_host": final_parts.hostname,
        "final_path": final_parts.path,
        "final_query_sha256": hashlib.sha256(final_parts.query.encode("utf-8")).hexdigest(),
        "final_query_present": bool(final_parts.query),
    }


def derive_modis_tile_from_samples(samples: Any) -> dict[str, Any]:
    if not isinstance(samples, list) or not 1 <= len(samples) <= SAMPLE_LIMIT:
        raise AdmissionFailure("SOURCE_SAMPLE_COUNT_FAILED")
    observed_tiles: set[tuple[int, int]] = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise AdmissionFailure("SOURCE_SAMPLE_SHAPE_FAILED")
        global_x, global_y = sample.get("global_x"), sample.get("global_y")
        if not finite(global_x) or int(global_x) != global_x or \
           not finite(global_y) or int(global_y) != global_y:
            raise AdmissionFailure("SOURCE_SAMPLE_INDEX_FAILED")
        global_x, global_y = int(global_x), int(global_y)
        if global_x < 0 or global_y < 0:
            raise AdmissionFailure("SOURCE_SAMPLE_INDEX_FAILED")
        h, v = global_x // 1200, global_y // 1200
        column, row = global_x - h * 1200, global_y - v * 1200
        if not 0 <= column < 1200 or not 0 <= row < 1200:
            raise AdmissionFailure("SOURCE_SAMPLE_INDEX_FAILED")
        observed_tiles.add((h, v))
    if observed_tiles != {(EXPECTED_MODIS_TILE["h"], EXPECTED_MODIS_TILE["v"])}:
        raise AdmissionFailure("SOURCE_MODIS_TILE_IDENTITY_FAILED")
    return dict(EXPECTED_MODIS_TILE)


def nasa_identity_from_ee(selection: dict[str, Any],
                          tile_identity: dict[str, Any]) -> dict[str, Any]:
    stream_contract = {
        "terra_night": ("MODIS/061/MOD11A1", "MOD11A1"),
        "aqua_night": ("MODIS/061/MYD11A1", "MYD11A1"),
    }
    if selection.get("stream_id") not in stream_contract:
        raise AdmissionFailure("SOURCE_STREAM_FAILED")
    collection_id, short_name = stream_contract[selection["stream_id"]]
    date_utc = selection.get("date_utc")
    try:
        observed_date = dt.date.fromisoformat(date_utc)
    except (TypeError, ValueError):
        raise AdmissionFailure("SOURCE_SELECTION_DATE_FAILED")
    ee_id = observed_date.strftime("%Y_%m_%d")
    if selection.get("collection_id") != collection_id or \
       selection.get("ee_image_id") != ee_id or \
       selection.get("source_system_index") != ee_id or \
       selection.get("projection_inventory_source_image_id") != collection_id + "/" + ee_id:
        raise AdmissionFailure("EE_PROJECTION_INVENTORY_IDENTITY_FAILED")
    if tile_identity != EXPECTED_MODIS_TILE:
        raise AdmissionFailure("SOURCE_MODIS_TILE_IDENTITY_FAILED")
    doy = observed_date.strftime("%j")
    tile_id = tile_identity["tile_id"]
    return {"short_name": short_name, "year": str(observed_date.year), "doy": doy,
            "h": tile_identity["h"], "v": tile_identity["v"], "tile_id": tile_id,
            "date_utc": date_utc,
            "ee_image_id": ee_id, "collection_id": collection_id,
            "projection_inventory_source_image_id": collection_id + "/" + ee_id,
            "granule_prefix": f"{short_name}.A{observed_date.year}{doy}.{tile_id}.061."}


def _parse_cmr_item(item: Any, expected: dict[str, Any]) -> tuple[str, dict[str, str]]:
    # UMM-G for MOD11A1/MYD11A1 .061 states the archived granule identity and the
    # download URL, but carries no per-file checksum.  The SHA-256 checksum and the
    # exact byte size live only in CMR's legacy echo10 metadata, fetched separately
    # (see ``fetch_echo10_checksum``).  ``GranuleUR`` is the producer granule id
    # with no ``.hdf`` suffix; the archived file name adds ``.hdf``.
    if not isinstance(item, dict) or not isinstance(item.get("meta"), dict) or \
       not isinstance(item.get("umm"), dict):
        raise AdmissionFailure("CMR_GRANULE_SHAPE_FAILED")
    meta, umm = item["meta"], item["umm"]
    granule_bare = umm.get("GranuleUR")
    if not isinstance(granule_bare, str) or \
       not granule_bare.startswith(expected["granule_prefix"]) or \
       not re.fullmatch(r"\d{13}", granule_bare[len(expected["granule_prefix"]):]):
        raise AdmissionFailure("CMR_GRANULE_IDENTITY_FAILED")
    production_timestamp = granule_bare[len(expected["granule_prefix"]):]
    granule_filename = granule_bare + ".hdf"
    urls = []
    for related in umm.get("RelatedUrls", []):
        if isinstance(related, dict) and related.get("Type") == "GET DATA" and \
           isinstance(related.get("URL"), str) and related["URL"].endswith(".hdf"):
            parsed_candidate = urllib.parse.urlsplit(related["URL"])
            if parsed_candidate.scheme == "https" and \
               parsed_candidate.hostname == ALLOWED_DOWNLOAD_HOST:
                urls.append(related["URL"])
    if len(urls) != 1:
        raise AdmissionFailure("CMR_EXACTLY_ONE_HDF_URL_FAILED")
    parsed = urllib.parse.urlsplit(urls[0])
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_DOWNLOAD_HOST or \
       parsed.username is not None or parsed.password is not None or parsed.fragment or \
       parsed.query or not parsed.path.startswith("/lp-prod-protected/") or \
       parsed.path.rsplit("/", 1)[-1] != granule_filename:
        raise AdmissionFailure("CMR_HDF_URL_ALLOWLIST_FAILED")
    concept_id = meta.get("concept-id")
    if not isinstance(concept_id, str) or not re.fullmatch(r"G\d+-[A-Z0-9_]+", concept_id):
        raise AdmissionFailure("CMR_CONCEPT_ID_FAILED")
    return production_timestamp, {
        "granule_ur": granule_filename, "granule_bare": granule_bare,
        "url": urls[0], "concept_id": concept_id}


def parse_cmr_granule(payload: Any, expected: dict[str, Any]) -> dict[str, Any]:
    # NASA occasionally lists an original plus one or more reprocessed versions of
    # the same tile/date.  Validate every returned granule and deterministically
    # keep the one with the latest 13-digit production timestamp (the field after
    # the granule prefix).  ``hits == len(items)`` guarantees the page holds every
    # match, so the selection is not sensitive to CMR's default ordering.
    if not isinstance(payload, dict) or set(payload) != {"hits", "took", "items"} or \
       not isinstance(payload["hits"], int) or isinstance(payload["hits"], bool) or \
       not isinstance(payload["items"], list) or payload["hits"] < 1 or \
       payload["hits"] != len(payload["items"]) or not 1 <= len(payload["items"]) <= 20:
        raise AdmissionFailure("CMR_GRANULE_RESULT_SET_FAILED")
    candidates = [_parse_cmr_item(item, expected) for item in payload["items"]]
    timestamps = [timestamp for timestamp, _granule in candidates]
    if len(set(timestamps)) != len(timestamps):
        raise AdmissionFailure("CMR_AMBIGUOUS_PRODUCTION_TIMESTAMP")
    timestamp, selected = max(candidates, key=lambda pair: pair[0])
    return {**selected, "cmr_granules_considered": len(candidates),
            "selected_production_timestamp": timestamp}


_ECHO10_ALGORITHMS = {"SHA256": "SHA-256", "SHA-256": "SHA-256", "MD5": "MD5"}


def fetch_echo10_checksum(metadata: dict[str, Any], phase: str,
                          session_deadline: float) -> tuple[dict[str, Any], dict[str, Any]]:
    # UMM-G carries no per-file checksum for this product.  CMR's legacy echo10
    # metadata for the same concept id does: one bounded XML request per selected
    # granule, read only for the archived ``.hdf`` file's SHA-256 (or MD5) checksum
    # and exact byte size.  Nothing here is persisted.
    concept_id = metadata["concept_id"]
    if not re.fullmatch(r"G\d+-[A-Z0-9_]+", concept_id):
        raise AdmissionFailure("CMR_CONCEPT_ID_FAILED")
    echo_url = "https://" + CMR_HOST + CMR_CONCEPTS_PREFIX + concept_id + ".echo10"
    parsed = urllib.parse.urlsplit(echo_url)
    if parsed.scheme != "https" or parsed.hostname != CMR_HOST or parsed.query or \
       parsed.fragment or parsed.path != CMR_CONCEPTS_PREFIX + concept_id + ".echo10":
        raise AdmissionFailure("CMR_ECHO10_REQUEST_URL_FAILED")
    body, _headers, transaction = _network_request(
        echo_url, phase,
        {"Accept": "application/echo10+xml", "Client-Id": "lake-balaton-audit012"},
        session_deadline, 5_000_000)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise AdmissionFailure("CMR_ECHO10_XML_PARSE_FAILED")
    if root.tag != "Granule" or root.findtext("GranuleUR") != metadata["granule_bare"]:
        raise AdmissionFailure("CMR_ECHO10_GRANULE_IDENTITY_FAILED")
    data_granule = root.find("DataGranule")
    matches = [child for child in (data_granule.findall("AdditionalFile") if data_granule
                                   is not None else [])
               if child.findtext("Name") == metadata["granule_ur"]]
    if len(matches) != 1:
        raise AdmissionFailure("CMR_ECHO10_HDF_FILE_ENTRY_FAILED")
    file_entry = matches[0]
    size_text = file_entry.findtext("SizeInBytes")
    if not isinstance(size_text, str) or not re.fullmatch(r"[1-9][0-9]{0,11}", size_text.strip()):
        raise AdmissionFailure("CMR_ECHO10_SIZE_FAILED")
    declared_size = int(size_text.strip())
    checksum_element = file_entry.find("Checksum")
    raw_algorithm = (checksum_element.findtext("Algorithm") or "").strip().upper() \
        if checksum_element is not None else ""
    checksum_value = (checksum_element.findtext("Value") or "").strip() \
        if checksum_element is not None else ""
    algorithm = _ECHO10_ALGORITHMS.get(raw_algorithm)
    if algorithm is None:
        raise AdmissionFailure("CMR_ECHO10_CHECKSUM_ALGORITHM_FAILED")
    pattern = r"[0-9A-Fa-f]{32}" if algorithm == "MD5" else r"[0-9A-Fa-f]{64}"
    if not re.fullmatch(pattern, checksum_value):
        raise AdmissionFailure("CMR_ECHO10_CHECKSUM_FORMAT_FAILED")
    if metadata["url"] not in {element.text for element in root.iter("URL") if element.text}:
        raise AdmissionFailure("CMR_ECHO10_URL_CONSISTENCY_FAILED")
    return {"checksum_algorithm": algorithm, "checksum": checksum_value.casefold(),
            "declared_size_bytes": declared_size}, transaction


def validate_transient_samples(samples: Any, source: dict[str, Any]) -> list[dict[str, int]]:
    fields = {"global_x", "global_y", "qc_raw", "lst_raw", "view_time_raw",
              "view_angle_raw", "clear_raw", "qc_mask", "lst_mask", "view_time_mask",
              "view_angle_mask", "clear_mask"}
    if not isinstance(samples, list) or not 1 <= len(samples) <= SAMPLE_LIMIT:
        raise AdmissionFailure("SOURCE_SAMPLE_COUNT_FAILED")
    output: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != fields or any(
                not finite(value) or int(value) != value for value in sample.values()):
            raise AdmissionFailure("SOURCE_SAMPLE_SHAPE_FAILED")
        normalized = {key: int(value) for key, value in sample.items()}
        row = normalized.pop("global_y") - source["v"] * 1200
        column = normalized.pop("global_x") - source["h"] * 1200
        if not 0 <= row < 1200 or not 0 <= column < 1200 or (row, column) in seen:
            raise AdmissionFailure("SOURCE_SAMPLE_INDEX_FAILED")
        seen.add((row, column))
        normalized["row"] = row
        normalized["column"] = column
        if qc_components(normalized["qc_raw"])[0] != 0 or qc_components(
                normalized["qc_raw"])[1] == 0:
            raise AdmissionFailure("SOURCE_SAMPLE_NOT_M0_D_GT0")
        if any(normalized[name] != 1 for name in
               ("qc_mask", "lst_mask", "view_time_mask", "view_angle_mask")):
            raise AdmissionFailure("SOURCE_SAMPLE_NOT_COMMON_V")
        output.append(normalized)
    return sorted(output, key=lambda item: (item["row"], item["column"]))


def _unlink_and_verify(path: Path) -> None:
    path.unlink()
    if path.exists():
        raise AdmissionFailure("TEMPORARY_HDF_RESIDUE_PRESENT")


def verify_hdf_bytes(hdf_bytes: bytes, metadata: dict[str, str], source: dict[str, Any],
                     samples: list[dict[str, int]]) -> dict[str, Any]:
    try:
        if importlib_metadata.version("pyhdf") != "0.11.7":
            raise AdmissionFailure("PYHDF_VERSION_PIN_FAILED")
        from pyhdf.SD import SD, SDC  # type: ignore
    except AdmissionFailure:
        raise
    except Exception:
        raise AdmissionFailure("PYHDF_0_11_7_UNAVAILABLE")
    checksum_name = "md5" if metadata["checksum_algorithm"] == "MD5" else "sha256"
    observed_declared = hashlib.new(checksum_name, hdf_bytes).hexdigest()
    if observed_declared != metadata["checksum"]:
        raise AdmissionFailure("HDF_DECLARED_CHECKSUM_MISMATCH")
    if len(hdf_bytes) != metadata["declared_size_bytes"]:
        raise AdmissionFailure("HDF_DECLARED_SIZE_MISMATCH")
    hdf_sha256 = hashlib.sha256(hdf_bytes).hexdigest()
    temporary_path: Path | None = None
    dataset: Any = None
    sds: dict[str, Any] = {}
    arrays: dict[str, Any] = {}
    shapes: dict[str, list[int]] = {}
    compared: list[dict[str, int]] = []
    try:
        handle, raw_path = tempfile.mkstemp(prefix="audit012-source-", suffix=".hdf")
        os.close(handle)
        temporary_path = Path(raw_path)
        temporary_path.write_bytes(hdf_bytes)
        dataset = SD(str(temporary_path), SDC.READ)
        mapping = {
            "qc_raw": ("QC_Night", 0, 255, "qc_mask"),
            "lst_raw": ("LST_Night_1km", 7500, 65535, "lst_mask"),
            "view_time_raw": ("Night_view_time", 0, 240, "view_time_mask"),
            # The MOD11A1/MYD11A1 HDF-EOS2 SDS name is truncated to "Night_view_angl"
            # (no trailing "e"); confirmed against NASA's Earthdata product catalog.
            "view_angle_raw": ("Night_view_angl", 0, 130, "view_angle_mask"),
            "clear_raw": ("Clear_night_cov", 1, 65535, "clear_mask"),
        }
        for field, (name, _minimum, _maximum, _mask) in mapping.items():
            selected = dataset.select(name)
            information = selected.info()
            if not isinstance(information, tuple) or len(information) != 5 or \
               tuple(information[2]) != (1200, 1200):
                raise AdmissionFailure("HDF_SDS_SHAPE_FAILED")
            sds[field] = selected
            # pyhdf's scalar-index read ``selected[row, col]`` silently returns a
            # constant (1) on this file's uint16 SDS (LST_Night_1km, Clear_night_cov);
            # a full-array ``.get()`` (and slice reads) return the true values.  Read
            # each 1200x1200 SDS once and index the NumPy array.
            whole = selected.get()
            if tuple(getattr(whole, "shape", ())) != (1200, 1200):
                raise AdmissionFailure("HDF_SDS_SHAPE_FAILED")
            arrays[field] = whole
            shapes[name] = [1200, 1200]
        for sample in samples:
            digest_item: dict[str, int] = {}
            for field, (_name, minimum, maximum, mask_name) in mapping.items():
                observed = int(arrays[field][sample["row"], sample["column"]])
                observed_mask = int(minimum <= observed <= maximum)
                if observed_mask != sample[mask_name] or (observed_mask and observed != sample[field]):
                    raise AdmissionFailure("HDF_EE_SAMPLE_MISMATCH")
                digest_item[field] = observed
                digest_item[mask_name] = observed_mask
            compared.append(digest_item)
    finally:
        cleanup_failed = False
        for selected in sds.values():
            try:
                selected.endaccess()
            except Exception:
                cleanup_failed = True
        if dataset is not None:
            try:
                dataset.end()
            except Exception:
                cleanup_failed = True
        if temporary_path is not None and temporary_path.exists():
            try:
                _unlink_and_verify(temporary_path)
            except Exception:
                cleanup_failed = True
        if temporary_path is not None and temporary_path.exists():
            cleanup_failed = True
        if cleanup_failed:
            raise AdmissionFailure("TEMPORARY_HDF_CLEANUP_FAILED")
    sample_digest = canonical_sha256(compared)
    return {
        "status": "verified_exact_original_hdf_samples",
        "cmr_concept_id": metadata["concept_id"], "producer_granule_id": metadata["granule_ur"],
        "declared_checksum_algorithm": metadata["checksum_algorithm"],
        "declared_checksum": metadata["checksum"],
        "declared_checksum_verified": True,
        "declared_size_bytes": metadata["declared_size_bytes"],
        "declared_size_verified": True, "hdf_sha256": hdf_sha256,
        "hdf_reader": HDF_READER_VERSION,
        "sds_names": list(mapping_value[0] for mapping_value in mapping.values()),
        "sds_shapes": shapes,
        "sample_count": len(samples), "ee_sample_values_sha256": sample_digest,
        "hdf_sample_values_sha256": sample_digest,
        "all_ee_values_and_masks_exact": True, "source_coordinate_arrays_included": False,
        "temporary_hdf_persisted": False, "raw_hdf_persisted": False,
        "cmr_granules_considered": metadata["cmr_granules_considered"],
        "selected_production_timestamp": metadata["selected_production_timestamp"],
    }


def verify_original_source(selection: dict[str, Any], session_deadline: float) -> dict[str, Any]:
    tile_identity = derive_modis_tile_from_samples(selection.get("samples"))
    source = nasa_identity_from_ee(selection, tile_identity)
    samples = validate_transient_samples(selection["samples"], source)
    query = urllib.parse.urlencode({
        "short_name": source["short_name"], "version": "061", "page_size": "20",
        "producer_granule_id": source["granule_prefix"] + "*",
        "options[producer_granule_id][pattern]": "true",
    })
    cmr_url = CMR_ENDPOINT + "?" + query
    parsed_cmr = urllib.parse.urlsplit(cmr_url)
    if parsed_cmr.scheme != "https" or parsed_cmr.hostname != "cmr.earthdata.nasa.gov" or \
       parsed_cmr.path != "/search/granules.umm_json" or parsed_cmr.fragment:
        raise AdmissionFailure("CMR_REQUEST_URL_FAILED")
    cmr_bytes, cmr_headers, cmr_transaction = _network_request(
        cmr_url,
        "nasa_cmr_" + selection["window_id"] + "_" + selection["stream_id"],
        {"Accept": "application/vnd.nasa.cmr.umm_results+json",
         "Client-Id": "lake-balaton-audit012"}, session_deadline, 2_000_000)
    if cmr_headers.get("cmr-time-out", "false").casefold() == "true":
        raise AdmissionFailure("CMR_PARTIAL_TIMEOUT_RESPONSE")
    metadata = parse_cmr_granule(_json_no_duplicates(cmr_bytes), source)
    echo_checksum, echo_transaction = fetch_echo10_checksum(
        metadata, "nasa_meta_" + selection["window_id"] + "_" + selection["stream_id"],
        session_deadline)
    metadata.update(echo_checksum)
    token = os.environ.get("EARTHDATA_BEARER_TOKEN")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+\-/=]{20,4096}", token):
        raise AdmissionFailure("EARTHDATA_BEARER_TOKEN_MISSING_OR_MALFORMED")
    hdf_bytes, _headers, hdf_transaction = _network_request(
        metadata["url"], "nasa_hdf_" + selection["window_id"] + "_" + selection["stream_id"],
        {"Authorization": "Bearer " + token, "User-Agent": "lake-balaton-audit012/1"},
        session_deadline, 128 * 1024 * 1024, redirect_object_name=metadata["granule_ur"])
    evidence = verify_hdf_bytes(hdf_bytes, metadata, source, samples)
    evidence.update({"window_id": selection["window_id"], "stream_id": selection["stream_id"],
                     "date_utc": selection["date_utc"],
                     "ee_image_id": source["ee_image_id"],
                     "source_system_index": source["ee_image_id"],
                     "projection_inventory_source_image_id": source[
                         "projection_inventory_source_image_id"],
                     "collection_id": source["collection_id"],
                     "modis_sinusoidal_tile_id": source["tile_id"],
                     "modis_sinusoidal_horizontal_tile": source["h"],
                     "modis_sinusoidal_vertical_tile": source["v"],
                     "tile_identity_derived_from_transient_samples": True,
                     "cmr_transaction": cmr_transaction,
                     "meta_transaction": echo_transaction,
                     "hdf_transaction": hdf_transaction,
                     "network_transaction_count": 3,
                     "source_identity_sha256": canonical_sha256({
                         "window_id": selection["window_id"],
                         "stream_id": selection["stream_id"],
                         "date_utc": selection["date_utc"],
                         "collection_id": source["collection_id"],
                         "ee_image_id": source["ee_image_id"],
                         "source_system_index": source["ee_image_id"],
                         "projection_inventory_source_image_id": source[
                             "projection_inventory_source_image_id"],
                         "modis_sinusoidal_tile_id": source["tile_id"],
                         "modis_sinusoidal_horizontal_tile": source["h"],
                         "modis_sinusoidal_vertical_tile": source["v"],
                     }),
                     "selection_rule": "earliest_M0_D_gt0_date_in_stream_season",
                     "coordinate_free": True})
    validate_coordinate_free(evidence)
    return evidence


def validate_source_evidence_item(item: Any, window_id: str, stream_id: str,
                                  earliest_record: dict[str, Any] | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(item, dict) or item.get("window_id") != window_id or \
       item.get("stream_id") != stream_id:
        return ["SOURCE_EVIDENCE_IDENTITY_FAILED"]
    if earliest_record is None:
        if set(item) != {"window_id", "stream_id", "status", "selection_rule",
                         "coordinate_free", "network_transaction_count"} or \
           item.get("status") != "not_applicable_no_M0_D_gt0_pixel" or \
           item.get("selection_rule") != "earliest_M0_D_gt0_date_in_stream_season" or \
           item.get("coordinate_free") is not True or item.get("network_transaction_count") != 0:
            errors.append("SOURCE_NOT_APPLICABLE_EVIDENCE_FAILED")
        return errors
    required = {
        "status", "cmr_concept_id", "producer_granule_id", "declared_checksum_algorithm",
        "declared_checksum", "declared_checksum_verified", "declared_size_bytes",
        "declared_size_verified", "hdf_sha256", "hdf_reader",
        "sds_names", "sds_shapes", "sample_count", "ee_sample_values_sha256",
        "hdf_sample_values_sha256", "all_ee_values_and_masks_exact",
        "source_coordinate_arrays_included", "temporary_hdf_persisted", "raw_hdf_persisted",
        "window_id", "stream_id", "date_utc", "ee_image_id", "source_system_index",
        "projection_inventory_source_image_id", "collection_id", "cmr_transaction",
        "meta_transaction", "hdf_transaction", "network_transaction_count",
        "source_identity_sha256",
        "selection_rule", "coordinate_free", "modis_sinusoidal_tile_id",
        "modis_sinusoidal_horizontal_tile", "modis_sinusoidal_vertical_tile",
        "tile_identity_derived_from_transient_samples",
        "cmr_granules_considered", "selected_production_timestamp",
    }
    if set(item) != required:
        return ["SOURCE_VERIFIED_EVIDENCE_SHAPE_FAILED"]
    if not isinstance(item.get("cmr_granules_considered"), int) or \
       isinstance(item.get("cmr_granules_considered"), bool) or \
       not 1 <= item["cmr_granules_considered"] <= 20 or \
       not re.fullmatch(r"\d{13}", item.get("selected_production_timestamp", "")) or \
       not item.get("producer_granule_id", "").endswith(
           item.get("selected_production_timestamp", "\0") + ".hdf"):
        errors.append("SOURCE_CMR_MULTI_GRANULE_SELECTION_FAILED")
    identity = {"window_id": window_id, "stream_id": stream_id,
                "date_utc": earliest_record["date_utc"],
                "collection_id": {"terra_night": "MODIS/061/MOD11A1",
                                  "aqua_night": "MODIS/061/MYD11A1"}[stream_id],
                "ee_image_id": earliest_record["source_image_id"],
                "source_system_index": earliest_record["source_system_index"],
                "projection_inventory_source_image_id": earliest_record[
                    "projection_inventory_source_image_id"],
                "modis_sinusoidal_tile_id": item.get("modis_sinusoidal_tile_id"),
                "modis_sinusoidal_horizontal_tile": item.get(
                    "modis_sinusoidal_horizontal_tile"),
                "modis_sinusoidal_vertical_tile": item.get("modis_sinusoidal_vertical_tile")}
    if any(item.get(key) != value for key, value in identity.items()) or \
       item.get("source_identity_sha256") != canonical_sha256(identity):
        errors.append("SOURCE_VERIFIED_IDENTITY_FAILED")
    tile_identity = {
        "h": item.get("modis_sinusoidal_horizontal_tile"),
        "v": item.get("modis_sinusoidal_vertical_tile"),
        "tile_id": item.get("modis_sinusoidal_tile_id"),
    }
    try:
        source = nasa_identity_from_ee({**identity, "stream_id": stream_id}, tile_identity)
    except AdmissionFailure:
        errors.append("SOURCE_MODIS_TILE_IDENTITY_FAILED")
        source = nasa_identity_from_ee(
            {**identity, "stream_id": stream_id}, dict(EXPECTED_MODIS_TILE))
    if item.get("tile_identity_derived_from_transient_samples") is not True:
        errors.append("SOURCE_MODIS_TILE_DERIVATION_FAILED")
    if not isinstance(item.get("producer_granule_id"), str) or not item[
            "producer_granule_id"].startswith(source["granule_prefix"]) or \
       not item["producer_granule_id"].endswith(".hdf") or \
       not re.fullmatch(r"G\d+-[A-Z0-9_]+", item.get("cmr_concept_id", "")):
        errors.append("SOURCE_GRANULE_IDENTITY_FAILED")
    algorithm = item.get("declared_checksum_algorithm")
    checksum_pattern = r"[0-9a-f]{32}" if algorithm == "MD5" else r"[0-9a-f]{64}"
    if algorithm not in ("MD5", "SHA-256") or not re.fullmatch(
            checksum_pattern, item.get("declared_checksum", "")) or \
       item.get("declared_checksum_verified") is not True or \
       not re.fullmatch(r"[0-9a-f]{64}", item.get("hdf_sha256", "")):
        errors.append("SOURCE_HASH_CHECKSUM_FAILED")
    if not isinstance(item.get("declared_size_bytes"), int) or \
       isinstance(item.get("declared_size_bytes"), bool) or \
       not 1 <= item.get("declared_size_bytes", 0) <= 128 * 1024 * 1024 or \
       item.get("declared_size_verified") is not True:
        errors.append("SOURCE_DECLARED_SIZE_FAILED")
    expected_sds = ["QC_Night", "LST_Night_1km", "Night_view_time",
                    "Night_view_angl", "Clear_night_cov"]
    if item.get("hdf_reader") != HDF_READER_VERSION or item.get("sds_names") != expected_sds or \
       item.get("sds_shapes") != {name: [1200, 1200] for name in expected_sds}:
        errors.append("SOURCE_HDF_SCHEMA_FAILED")
    if not isinstance(item.get("sample_count"), int) or isinstance(item.get("sample_count"), bool) or \
       not 1 <= item["sample_count"] <= SAMPLE_LIMIT or \
       not re.fullmatch(r"[0-9a-f]{64}", item.get("ee_sample_values_sha256", "")) or \
       item.get("ee_sample_values_sha256") != item.get("hdf_sample_values_sha256") or \
       item.get("all_ee_values_and_masks_exact") is not True:
        errors.append("SOURCE_SAMPLE_CROSSCHECK_FAILED")
    _transaction_keys = {
        "transaction_count", "redirect_count", "requested_url_sha256",
        "final_url_sha256", "exact_final_url", "requested_scheme", "requested_host",
        "requested_path", "requested_query_sha256", "requested_query_present",
        "final_scheme", "final_host", "final_path", "final_query_sha256",
        "final_query_present"}
    for name in ("cmr_transaction", "meta_transaction"):
        transaction = item.get(name)
        if not isinstance(transaction, dict) or set(transaction) != _transaction_keys or \
           transaction.get("transaction_count") != 1 or transaction.get("redirect_count") != 0 or \
           transaction.get("exact_final_url") is not True or \
           not re.fullmatch(r"[0-9a-f]{64}", transaction.get("requested_url_sha256", "")) or \
           transaction.get("requested_url_sha256") != transaction.get("final_url_sha256"):
            errors.append("SOURCE_NETWORK_TRANSACTION_FAILED:" + name)
            continue
        if transaction["requested_scheme"] != "https" or \
           transaction["final_scheme"] != transaction["requested_scheme"] or \
           transaction["final_host"] != transaction["requested_host"] or \
           transaction["final_path"] != transaction["requested_path"] or \
           transaction["final_query_sha256"] != transaction["requested_query_sha256"] or \
           transaction["final_query_present"] != transaction["requested_query_present"]:
            errors.append("SOURCE_NETWORK_FINAL_IDENTITY_FAILED:" + name)
        if name == "cmr_transaction" and (
                transaction["requested_host"] != "cmr.earthdata.nasa.gov" or
                transaction["requested_path"] != "/search/granules.umm_json" or
                transaction["requested_query_present"] is not True):
            errors.append("SOURCE_CMR_URL_GATE_FAILED")
        if name == "meta_transaction" and (
                transaction["requested_host"] != "cmr.earthdata.nasa.gov" or
                not transaction["requested_path"].startswith("/search/concepts/") or
                not transaction["requested_path"].endswith(
                    item.get("cmr_concept_id", "\0") + ".echo10") or
                transaction["requested_query_present"] is not False):
            errors.append("SOURCE_ECHO10_URL_GATE_FAILED")
    # The HDF download is the one request that may follow up to two hops: LP DAAC
    # answers an authenticated protected-granule GET with a 302 to a signed
    # download URL (observed: the LP DAAC egress CloudFront distribution; for some
    # DAACs a pre-signed AWS S3 URL).  Accept redirect_count 0 (served directly)
    # or 1-2 validated hops to a NASA-egress host whose object name still matches
    # the granule file.
    hdf_txn = item.get("hdf_transaction")
    granule_file = item.get("producer_granule_id")
    if not isinstance(hdf_txn, dict) or set(hdf_txn) != _transaction_keys or \
       hdf_txn.get("transaction_count") != 1 or \
       hdf_txn.get("redirect_count") not in (0, 1, 2) or \
       not re.fullmatch(r"[0-9a-f]{64}", hdf_txn.get("requested_url_sha256", "")) or \
       hdf_txn.get("requested_scheme") != "https" or \
       hdf_txn.get("requested_host") != ALLOWED_DOWNLOAD_HOST or \
       not str(hdf_txn.get("requested_path", "")).startswith("/lp-prod-protected/") or \
       str(hdf_txn.get("requested_path", "")).rsplit("/", 1)[-1] != granule_file or \
       hdf_txn.get("requested_query_present") is not False:
        errors.append("SOURCE_HDF_URL_GATE_FAILED")
    elif hdf_txn["redirect_count"] == 0:
        if hdf_txn.get("exact_final_url") is not True or \
           hdf_txn.get("final_url_sha256") != hdf_txn.get("requested_url_sha256") or \
           hdf_txn.get("final_scheme") != "https" or \
           hdf_txn.get("final_host") != ALLOWED_DOWNLOAD_HOST or \
           hdf_txn.get("final_path") != hdf_txn.get("requested_path") or \
           hdf_txn.get("final_query_present") is not False:
            errors.append("SOURCE_HDF_DIRECT_IDENTITY_FAILED")
    else:
        if hdf_txn.get("exact_final_url") is not False or \
           hdf_txn.get("final_url_sha256") == hdf_txn.get("requested_url_sha256") or \
           hdf_txn.get("final_scheme") != "https" or \
           not _is_allowed_download_redirect_host(hdf_txn.get("final_host") or "") or \
           granule_file not in str(hdf_txn.get("final_path", "")).split("/") or \
           hdf_txn.get("final_query_present") is not True:
            errors.append("SOURCE_HDF_DOWNLOAD_REDIRECT_IDENTITY_FAILED")
    if item.get("network_transaction_count") != 3 or \
       item.get("source_coordinate_arrays_included") is not False or \
       item.get("temporary_hdf_persisted") is not False or \
       item.get("raw_hdf_persisted") is not False or item.get("coordinate_free") is not True or \
       item.get("selection_rule") != "earliest_M0_D_gt0_date_in_stream_season":
        errors.append("SOURCE_PERSISTENCE_OR_METHOD_FAILED")
    try:
        validate_coordinate_free(item)
    except ValueError:
        errors.append("SOURCE_COORDINATE_FREE_FAILED")
    return sorted(set(errors))


def type7(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[min(lower + 1, len(ordered) - 1)] * weight


def summary_statistics(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values), "mean": statistics.fmean(values) if values else None,
        "minimum": min(values) if values else None, "p05_type7": type7(values, 0.05),
        "p25_type7": type7(values, 0.25), "median_type7": type7(values, 0.5),
        "p75_type7": type7(values, 0.75), "p95_type7": type7(values, 0.95),
        "maximum": max(values) if values else None,
    }


def metric_map(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in record["candidate_and_tier_metrics"]}


def build_summaries(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],
                                                            list[dict[str, Any]]]:
    seasonal: list[dict[str, Any]] = []
    for result in results:
        for metric_name in METRIC_NAMES:
            fractions = [metric_map(record)[metric_name]["coverage_fraction"]
                         for record in result["records"]]
            seasonal.append({
                "window_id": result["window_id"], "season": result["season"],
                "stream_id": result["stream_id"], "erosion_id": result["erosion_id"],
                "metric": metric_name, "daily_coverage_fraction": summary_statistics(fractions),
                "positive_date_count": sum(value > 0 for value in fractions),
                "zero_date_count": sum(value == 0 for value in fractions),
                "missing_date_count": sum(record["source_image_count"] != 1
                                          for record in result["records"]),
            })
    by_key = {(result["window_id"], result["stream_id"], result["erosion_id"]): result
              for result in results}
    sensitivity: list[dict[str, Any]] = []
    audit = load_audit()
    for window in WINDOWS:
        for stream_id in NIGHT_STREAM_IDS:
            baseline = by_key[(window["window_id"], stream_id, "EROSION_0000M")]
            for treatment in audit.TREATMENTS:
                result = by_key[(window["window_id"], stream_id, treatment["erosion_id"])]
                for candidate in ("A", "B", "C"):
                    deltas = [metric_map(record)[candidate]["coverage_fraction"] -
                              metric_map(base)[candidate]["coverage_fraction"]
                              for record, base in zip(result["records"], baseline["records"])]
                    sensitivity.append({
                        "window_id": window["window_id"], "stream_id": stream_id,
                        "erosion_id": treatment["erosion_id"], "candidate": candidate,
                        "coverage_fraction_difference_from_0m": summary_statistics(deltas),
                    })
    return seasonal, sensitivity


def select_source_verifications(results: list[dict[str, Any]],
                                transient_by_key: dict[tuple[str, str, str], list[dict[str, Any]]]
                                ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    not_applicable: list[dict[str, Any]] = []
    originals = {(result["window_id"], result["stream_id"]): result for result in results
                 if result["erosion_id"] == "EROSION_0000M"}
    for window in WINDOWS:
        for stream_id in NIGHT_STREAM_IDS:
            result = originals[(window["window_id"], stream_id)]
            anomalous = [record for record in result["records"]
                         if metric_map(record)["M0_D_gt0"]["pixel_center_count"] > 0]
            if not anomalous:
                not_applicable.append({
                    "window_id": window["window_id"], "stream_id": stream_id,
                    "status": "not_applicable_no_M0_D_gt0_pixel",
                    "selection_rule": "earliest_M0_D_gt0_date_in_stream_season",
                    "coordinate_free": True, "network_transaction_count": 0,
                })
                continue
            earliest = anomalous[0]
            key = (window["window_id"], stream_id, earliest["date_utc"])
            samples = transient_by_key.get(key)
            if not samples:
                raise AdmissionFailure("ANOMALY_WITHOUT_BOUNDED_SOURCE_SAMPLE")
            selected.append({
                "window_id": window["window_id"], "stream_id": stream_id,
                "date_utc": earliest["date_utc"],
                "collection_id": {"terra_night": "MODIS/061/MOD11A1",
                                  "aqua_night": "MODIS/061/MYD11A1"}[stream_id],
                "ee_image_id": earliest["source_image_id"],
                "source_system_index": earliest["source_system_index"],
                "projection_inventory_source_image_id": earliest[
                    "projection_inventory_source_image_id"],
                "samples": samples,
            })
    return selected, not_applicable


def synthetic_record() -> dict[str, Any]:
    count_hist = [0] * 256
    for qc_byte, count in ((0, 4), (1, 2), (4, 3), (17, 1)):
        count_hist[qc_byte] = count
    area_hist = [float(value) * 10.0 for value in count_hist]
    eligible_count, eligible_area = 12, 120.0
    metrics = []
    for name in METRIC_NAMES:
        count = sum(count_hist[q] for q in range(256)
                    if name == "V" or candidate_membership(q).get(name, False))
        metrics.append({"name": name, "pixel_center_count": count, "area_m2": count * 10.0,
                        "coverage_fraction": count / eligible_count})
    intersection = sum(count_hist[q] for q in range(256)
                       if candidate_membership(q)["A"] and candidate_membership(q)["B"])
    group_counts = {"A_intersection_B": intersection,
                    "A_only": metrics[1]["pixel_center_count"] - intersection,
                    "B_only": metrics[2]["pixel_center_count"] - intersection,
                    "B": metrics[2]["pixel_center_count"],
                    "C_minus_B": metrics[3]["pixel_center_count"] - metrics[2]["pixel_center_count"]}
    distributions = []
    for group in GROUPS:
        for variable in VARIABLES:
            count = group_counts[group]
            stats = {"member_pixel_center_count": count, "value_pixel_center_count": count,
                     "type7_value_list_count": count, "value_area_m2": count * 10.0,
                     "quantile_method": "Type-7_h=(n-1)p_linear_interpolation"}
            stats.update({name: (1.0 if count else None) for name in (
                "mean", "min", "max", "p05_type7", "p25_type7", "p50_type7",
                "p75_type7", "p95_type7")})
            distributions.append({"group": group, "variable": variable, "statistics": stats})
    return {
        "date_utc": "2024-01-15", "window_id": "winter_2024",
        "stream_id": "terra_night", "erosion_id": "EROSION_0000M",
        "source_image_count": 1, "source_image_id": "2024_01_15",
        "source_system_index": "2024_01_15",
        "projection_inventory_source_image_id": "MODIS/061/MOD11A1/2024_01_15",
        "source_identity_matches_projection_inventory": True,
        "eligible_area_m2": eligible_area, "eligible_pixel_center_count": eligible_count,
        "candidate_and_tier_metrics": metrics,
        "qc_byte_pixel_count_histogram_conditional_on_V": count_hist,
        "qc_byte_area_histogram_m2_conditional_on_V": area_hist,
        "qc_lst_mask_range_cross_tab_labels": list(CROSS_TAB_LABELS),
        "qc_lst_mask_range_cross_tab_pixel_counts": [0, 0, 0, 1, 1, 10],
        "qc_lst_mask_range_cross_tab_areas_m2": [0, 0, 0, 10.0, 10.0, 100.0],
        "group_distributions": distributions, "validation_errors": [],
    }


def synthetic_source_evidence(record: dict[str, Any]) -> dict[str, Any]:
    collection = {"terra_night": "MODIS/061/MOD11A1",
                  "aqua_night": "MODIS/061/MYD11A1"}[record["stream_id"]]
    identity = {"window_id": record["window_id"], "stream_id": record["stream_id"],
                "date_utc": record["date_utc"], "collection_id": collection,
                "ee_image_id": record["source_image_id"],
                "source_system_index": record["source_system_index"],
                "projection_inventory_source_image_id": record[
                    "projection_inventory_source_image_id"],
                "modis_sinusoidal_tile_id": EXPECTED_MODIS_TILE["tile_id"],
                "modis_sinusoidal_horizontal_tile": EXPECTED_MODIS_TILE["h"],
                "modis_sinusoidal_vertical_tile": EXPECTED_MODIS_TILE["v"]}
    base_transaction = {"transaction_count": 1, "redirect_count": 0,
                        "requested_url_sha256": "1" * 64, "final_url_sha256": "1" * 64,
                        "exact_final_url": True, "requested_scheme": "https",
                        "requested_query_sha256": "6" * 64, "final_scheme": "https",
                        "final_query_sha256": "6" * 64}
    names = ["QC_Night", "LST_Night_1km", "Night_view_time",
             "Night_view_angl", "Clear_night_cov"]
    source = nasa_identity_from_ee(
        {**identity, "stream_id": record["stream_id"]}, dict(EXPECTED_MODIS_TILE))
    return {
        "status": "verified_exact_original_hdf_samples", "cmr_concept_id": "G123-LPCLOUD",
        "producer_granule_id": source["granule_prefix"] + "2024020000000.hdf",
        "declared_checksum_algorithm": "SHA-256", "declared_checksum": "0" * 64,
        "declared_checksum_verified": True,
        "declared_size_bytes": 2378960, "declared_size_verified": True,
        "hdf_sha256": "2" * 64,
        "hdf_reader": HDF_READER_VERSION, "sds_names": names,
        "sds_shapes": {name: [1200, 1200] for name in names}, "sample_count": 1,
        "ee_sample_values_sha256": "3" * 64, "hdf_sample_values_sha256": "3" * 64,
        "all_ee_values_and_masks_exact": True, "source_coordinate_arrays_included": False,
        "temporary_hdf_persisted": False, "raw_hdf_persisted": False,
        "cmr_granules_considered": 1, "selected_production_timestamp": "2024020000000",
        "modis_sinusoidal_tile_id": source["tile_id"],
        "modis_sinusoidal_horizontal_tile": source["h"],
        "modis_sinusoidal_vertical_tile": source["v"],
        "tile_identity_derived_from_transient_samples": True,
        **identity, "cmr_transaction": {**base_transaction,
            "requested_host": "cmr.earthdata.nasa.gov",
            "requested_path": "/search/granules.umm_json", "requested_query_present": True,
            "final_host": "cmr.earthdata.nasa.gov",
            "final_path": "/search/granules.umm_json", "final_query_present": True},
        "meta_transaction": {**base_transaction,
            "requested_host": "cmr.earthdata.nasa.gov",
            "requested_path": "/search/concepts/G123-LPCLOUD.echo10",
            "requested_query_present": False, "final_host": "cmr.earthdata.nasa.gov",
            "final_path": "/search/concepts/G123-LPCLOUD.echo10",
            "final_query_present": False},
        "hdf_transaction": {**base_transaction,
            "redirect_count": 1, "exact_final_url": False, "final_url_sha256": "7" * 64,
            "requested_host": ALLOWED_DOWNLOAD_HOST,
            "requested_path": "/lp-prod-protected/MOD11A1.061/x/" +
                              source["granule_prefix"] + "2024020000000.hdf",
            "requested_query_present": False,
            "final_host": "d1nklfio7vscoe.cloudfront.net",
            "final_path": "/MOD11A1.061/x/" + source["granule_prefix"] + "2024020000000.hdf",
            "final_query_present": True},
        "network_transaction_count": 3,
        "source_identity_sha256": canonical_sha256(identity),
        "selection_rule": "earliest_M0_D_gt0_date_in_stream_season", "coordinate_free": True,
    }


def synthetic_terminal_payload() -> dict[str, Any]:
    audit = load_audit()
    results: list[dict[str, Any]] = []
    for window in WINDOWS:
        for stream_id in NIGHT_STREAM_IDS:
            collection = {"terra_night": "MODIS/061/MOD11A1",
                          "aqua_night": "MODIS/061/MYD11A1"}[stream_id]
            for treatment in audit.TREATMENTS:
                records = []
                for date_utc in dates(window):
                    record = copy.deepcopy(synthetic_record())
                    ee_id = date_utc.replace("-", "_")
                    record.update({"date_utc": date_utc, "window_id": window["window_id"],
                                   "stream_id": stream_id, "erosion_id": treatment["erosion_id"],
                                   "source_image_id": ee_id, "source_system_index": ee_id,
                                   "projection_inventory_source_image_id": collection + "/" + ee_id})
                    records.append(record)
                results.append({"specification": SPECIFICATION, "implementation": IMPLEMENTATION,
                                "window_id": window["window_id"], "season": window["season"],
                                "stream_id": stream_id, "erosion_id": treatment["erosion_id"],
                                "erosion_distance_m": treatment["distance_m"], "date_count": 14,
                                "records": records, "candidate_definitions": CANDIDATES,
                                "coordinate_free": True, "validation_errors": []})
    seasonal, shoreline = build_summaries(results)
    original = [result for result in results if result["erosion_id"] == "EROSION_0000M"]
    source_evidence = [synthetic_source_evidence(result["records"][0]) for result in original]
    return {
        "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
        "coordinate_free": True, "source_coordinate_arrays_included": False,
        "candidate_definitions": CANDIDATES,
        "candidate_ordering_interpretation": (
            "A is non-nested with B and C; B is an exact subset of C; no candidate is selected"),
        "joint_qc_table_encoding": (
            "fixed arrays indexed by raw QC byte q=0..255; M=q&3,D=(q>>2)&3,E=(q>>4)&3,T=(q>>6)&3"),
        "request_decomposition": REQUEST_DECOMPOSITION,
        "projection_certification_digests": [
            {"window_id": window["window_id"], "stream_id": stream,
             "record_count": 14, "source_image_ids_sha256": "4" * 64,
             "projection_inventory_sha256": "5" * 64, "pass": True}
            for window in WINDOWS for stream in NIGHT_STREAM_IDS],
        "observation_count": 112, "treatment_record_count": 448,
        "result_count": 32, "results": results,
        "seasonal_candidate_summaries": seasonal,
        "shoreline_sensitivity_summaries": shoreline,
        "temperature_and_ancillary_selectivity": temperature_selectivity(results),
        "original_nasa_hdf_source_verification": source_evidence,
        "nasa_network_transaction_count": 24, "validation_errors": [], "pass": True,
        "scientific_interpretation": (
            "Bounded simultaneous A/B/C diagnostic comparison only. It selects no QA rule and "
            "does not change or relax the completed strict audit mask."),
    }


def self_test() -> int:
    failures: list[str] = []
    if sha256_file(AUDIT_RUNNER_PATH) != EXPECTED_AUDIT_RUNNER_SHA256 or \
       sha256_file(AUDIT011_RUNNER_PATH) != EXPECTED_AUDIT011_RUNNER_SHA256:
        failures.append("dependency_pins")
    expected_ee = 4 + 1 + 8 + EARLIEST_ANOMALY_PROBE_REQUESTS + 32 * len(DATE_BATCHES)
    if REQUEST_DECOMPOSITION["earth_engine_requests"] != expected_ee or \
       REQUEST_DECOMPOSITION["comparison_requests"] != 32 * len(DATE_BATCHES) or \
       REQUEST_WALL_LIMIT_SECONDS != 480.000 or TRANSPORT_MAX_ATTEMPTS != 1 or \
       SESSION_LIMIT_SECONDS != 9900:
        failures.append("execution_contract")
    covered = sorted(pos for batch in DATE_BATCHES for pos in batch)
    if covered != list(range(WINDOW_DATE_COUNT)) or \
       any(not 1 <= len(batch) <= COMPARISON_DATE_BATCH_SIZE for batch in DATE_BATCHES):
        failures.append("date_batches")
    runner_source = Path(__file__).read_text(encoding="utf-8")
    if not isinstance(COMPARISON_REQUEST_PAUSE_SECONDS, float) or \
       not 0 <= COMPARISON_REQUEST_PAUSE_SECONDS <= 60 or \
       COMPARISON_REQUEST_PAUSE_SECONDS * REQUEST_DECOMPOSITION["comparison_requests"] > \
       SESSION_LIMIT_SECONDS / 3 or \
       "time.sleep(pause)" not in runner_source or \
       "min(COMPARISON_REQUEST_PAUSE_SECONDS, remaining - 180.0)" not in runner_source:
        failures.append("comparison_request_pause")
    if "earliest_anomaly_index.eq(index)" not in runner_source or \
       "earliest_M0_D_gt0_date_in_stream_season" not in runner_source:
        failures.append("earliest_only_source_sampling")
    _floor_global_x = 'pixel_indices.select("x").fl' + 'oor().rename("global_x")'
    _tolist_extract = "raw_and_masks, ee.Reducer.to" + "List(), geometry, context))"
    _random_sample = "numPixels=SAMPLE_LIMIT, se" + "ed=12028"
    if _floor_global_x not in runner_source or _tolist_extract not in runner_source or \
       _random_sample in runner_source:
        failures.append("transient_sample_extraction")
    for qc_byte in range(256):
        m, d, e, t = qc_components(qc_byte)
        membership = candidate_membership(qc_byte)
        if membership["A"] != (m == 0) or membership["B"] != (
                m in (0, 1) and d == e == t == 0) or membership["C"] != (
                m in (0, 1) and d == 0 and e <= 1 and t <= 1) or \
           (membership["B"] and not membership["C"]):
            failures.append("candidate_truth_table")
            break
    if candidate_membership(4)["A"] is not True or candidate_membership(4)["B"] is not False:
        failures.append("A_non_nested_fixture")
    runner_text = Path(__file__).read_text(encoding="utf-8")
    # Every self.<primitive>(...) / runner.<primitive>(...) used by the graph path
    # (ComparisonRunner.graph and the module-level _distribution / _area_histogram
    # helpers) must resolve on ComparisonRunner itself or on the delegated
    # NighttimeDiagnosticRunner.  This would have caught the missing `_frequency`
    # delegation before an authenticated run.
    graph_body = runner_text.split("    def graph(", 1)[-1].split("\n\n\n", 1)[0]
    helper_bodies = "".join(
        runner_text.split(f"def {helper}(", 1)[-1].split("\n\n\n", 1)[0]
        for helper in ("_distribution", "_area_histogram", "_source_data",
                       "_treatment_geometry", "earliest_anomaly_position"))
    delegate_cls = load_audit011().NighttimeDiagnosticRunner
    for primitive in sorted(set(re.findall(
            r"(?:self|runner)\.([a-zA-Z_]+)\(", graph_body + helper_bodies))):
        if primitive in ("ee",):
            continue
        if not (hasattr(ComparisonRunner, primitive) or hasattr(delegate_cls, primitive)):
            failures.append("comparison_runner_missing_primitive:" + primitive)
    if type7([1.0, 2.0, 3.0, 4.0], 0.25) != 1.75 or \
       type7([1.0, 2.0, 3.0, 4.0], 0.50) != 2.5 or \
       type7([], 0.5) is not None or type7([7.0], 0.95) != 7.0 or \
       "h = safe_size.subtract(1).multiply(probability)" not in runner_text or \
       "safe = ee.List(ee.Algorithms.If(positive, ordered, ee.List([0])))" not in runner_text:
        failures.append("exact_type7_formula")
    # _validate_distribution tolerates sub-ULP Type-7 rounding but still rejects a
    # real ordering fault.
    _noise = 25.3
    _tol_errs: list[str] = []
    _validate_distribution({
        "member_pixel_center_count": 3, "value_pixel_center_count": 3,
        "type7_value_list_count": 3, "value_area_m2": 30.0,
        "quantile_method": "Type-7_h=(n-1)p_linear_interpolation",
        "mean": _noise, "min": _noise, "max": _noise - 5e-15,
        "p05_type7": _noise + 3e-15, "p25_type7": _noise - 1e-15,
        "p50_type7": _noise, "p75_type7": _noise + 1e-15, "p95_type7": _noise,
    }, 3, _tol_errs)
    if _tol_errs:
        failures.append("distribution_tolerance_too_strict")
    _real_errs: list[str] = []
    _validate_distribution({
        "member_pixel_center_count": 3, "value_pixel_center_count": 3,
        "type7_value_list_count": 3, "value_area_m2": 30.0,
        "quantile_method": "Type-7_h=(n-1)p_linear_interpolation",
        "mean": 5.0, "min": 1.0, "max": 9.0, "p05_type7": 2.0, "p25_type7": 8.0,
        "p50_type7": 3.0, "p75_type7": 7.0, "p95_type7": 8.5,
    }, 3, _real_errs)
    if "DISTRIBUTION_TYPE7_OR_MEAN_RANGE_FAILED" not in _real_errs:
        failures.append("distribution_tolerance_too_loose")
    record = synthetic_record()
    errors, transient = validate_record(copy.deepcopy(record), "2024-01-15",
                                        "winter_2024", "terra_night", "EROSION_0000M")
    if errors or transient:
        failures.append("positive_record:" + ",".join(errors))
    # Date-batch pieces validate and reassemble into a 14-record result.
    _win = WINDOWS[0]
    _str = {"stream_id": "terra_night", "collection_id": "MODIS/061/MOD11A1"}
    _trt = {"erosion_id": "EROSION_0000M", "distance_m": 0}
    _dates = dates(_win)

    def _batch_piece(batch: tuple[int, ...]) -> dict[str, Any]:
        recs = []
        for pos in batch:
            rec = copy.deepcopy(synthetic_record())
            ee_id = _dates[pos].replace("-", "_")
            rec.update({"date_utc": _dates[pos], "window_id": _win["window_id"],
                        "stream_id": "terra_night", "erosion_id": "EROSION_0000M",
                        "source_image_id": ee_id, "source_system_index": ee_id,
                        "projection_inventory_source_image_id": "MODIS/061/MOD11A1/" + ee_id})
            recs.append(rec)
        return {"specification": SPECIFICATION, "implementation": IMPLEMENTATION,
                "window_id": _win["window_id"], "season": _win["season"],
                "stream_id": "terra_night", "erosion_id": "EROSION_0000M",
                "erosion_distance_m": 0, "date_positions": list(batch),
                "date_count": len(batch), "records": recs,
                "candidate_definitions": CANDIDATES, "coordinate_free": True,
                "validation_errors": []}

    _pieces = [_batch_piece(batch) for batch in DATE_BATCHES]
    for _batch, _piece in zip(DATE_BATCHES, _pieces):
        if validate_batch_piece(copy.deepcopy(_piece), _win, _str, _trt, _batch):
            failures.append("batch_piece_positive")
            break
    _assembled = assemble_batches([copy.deepcopy(p) for p in _pieces])
    _assembly_errors, _assembly_transient = validate_result(_assembled, _win, _str, _trt)
    if _assembly_errors or _assembly_transient:
        failures.append("batch_assembly:" + ",".join(_assembly_errors))
    _bad_positions = copy.deepcopy(_pieces[0])
    _bad_positions["date_positions"] = [9] * len(DATE_BATCHES[0])
    if not validate_batch_piece(_bad_positions, _win, _str, _trt, DATE_BATCHES[0]):
        failures.append("batch_piece_negative_positions")
    try:
        assemble_batches([copy.deepcopy(_pieces[0])])
        failures.append("batch_assembly_incomplete_not_rejected")
    except AdmissionFailure:
        pass
    # A transient sample must surface from validate_result with every key
    # execute() reads to build transient_by_key and select_source_verifications().
    _tr_sample = {"global_x": 23076, "global_y": 5169, "qc_raw": 8, "lst_raw": 13677,
                  "view_time_raw": 23, "view_angle_raw": 39, "clear_raw": 2875,
                  "qc_mask": 1, "lst_mask": 1, "view_time_mask": 1,
                  "view_angle_mask": 1, "clear_mask": 1}
    _tr_pieces = [copy.deepcopy(p) for p in _pieces]
    _tr_pieces[0]["records"][0]["transient_original_hdf_samples"] = [_tr_sample]
    _tr_errors, _tr_transients = validate_result(
        assemble_batches(_tr_pieces), _win, _str, _trt)
    if _tr_errors or len(_tr_transients) != 1 or any(
            key not in _tr_transients[0]
            for key in ("window_id", "stream_id", "date_utc", "collection_id", "samples")) or \
       _tr_transients[0]["window_id"] != _win["window_id"] or \
       _tr_transients[0]["date_utc"] != _dates[0] or _tr_transients[0]["samples"] != [_tr_sample]:
        failures.append("transient_dict_keys:" + ",".join(_tr_errors))
    mutations = {
        "B_subset": lambda x: x["candidate_and_tier_metrics"][2].update(
            {"pixel_center_count": 11, "area_m2": 110.0, "coverage_fraction": 11 / 12}),
        "hist_identity": lambda x: x["qc_byte_pixel_count_histogram_conditional_on_V"].__setitem__(0, 3),
        "cross_tab": lambda x: x["qc_lst_mask_range_cross_tab_pixel_counts"].__setitem__(0, 1),
        "source_count": lambda x: x.__setitem__("source_image_count", 2),
        "server_error": lambda x: x["validation_errors"].append("FAIL"),
        "distribution_count": lambda x: x["group_distributions"][0]["statistics"].__setitem__(
            "member_pixel_center_count", 99),
    }
    for name, mutate in mutations.items():
        fixture = copy.deepcopy(record)
        mutate(fixture)
        observed, _ = validate_record(fixture, "2024-01-15", "winter_2024",
                                      "terra_night", "EROSION_0000M")
        if not observed:
            failures.append("negative_" + name)
    sample = {"global_x": 23001, "global_y": 4802, "qc_raw": 4, "lst_raw": 15000,
              "view_time_raw": 120, "view_angle_raw": 65, "clear_raw": 2000,
              "qc_mask": 1, "lst_mask": 1, "view_time_mask": 1,
              "view_angle_mask": 1, "clear_mask": 1}
    source_selection = {"stream_id": "terra_night", "date_utc": "2024-01-15",
                        "collection_id": "MODIS/061/MOD11A1", "ee_image_id": "2024_01_15",
                        "source_system_index": "2024_01_15",
                        "projection_inventory_source_image_id":
                        "MODIS/061/MOD11A1/2024_01_15"}
    tile_identity = derive_modis_tile_from_samples([sample])
    source = nasa_identity_from_ee(source_selection, tile_identity)
    normalized = validate_transient_samples([sample], source)
    if normalized[0]["row"] != 2 or normalized[0]["column"] != 201:
        failures.append("sample_index_conversion")
    for name, mutate in {
            "invented_full_ee_id": lambda x: x.__setitem__(
                "ee_image_id", "MODIS/061/MOD11A1/MOD11A1.A2024015.h19v04.061"),
            "wrong_inventory_id": lambda x: x.__setitem__(
                "projection_inventory_source_image_id", "MODIS/061/MOD11A1/wrong"),
            "wrong_collection": lambda x: x.__setitem__("collection_id", "MODIS/061/MYD11A1"),
    }.items():
        fixture = copy.deepcopy(source_selection)
        mutate(fixture)
        try:
            nasa_identity_from_ee(fixture, tile_identity)
            failures.append("ee_identity_negative_" + name)
        except AdmissionFailure:
            pass
    for name, bad_sample in {
            "wrong_h18": {**sample, "global_x": 21801},
            "wrong_h20": {**sample, "global_x": 24201},
            "mixed_tiles": [{**sample}, {**sample, "global_x": 24201}],
    }.items():
        try:
            derive_modis_tile_from_samples(
                bad_sample if isinstance(bad_sample, list) else [bad_sample])
            failures.append("tile_derivation_negative_" + name)
        except AdmissionFailure:
            pass
    _hdf_url_1 = ("https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/"
                  "MOD11A1.061/MOD11A1.A2024015.h19v04.061.2024020000000/"
                  "MOD11A1.A2024015.h19v04.061.2024020000000.hdf")
    cmr_fixture = {"hits": 1, "took": 1, "items": [{
        "meta": {"concept-id": "G123-LPCLOUD"},
        "umm": {"GranuleUR": "MOD11A1.A2024015.h19v04.061.2024020000000",
                "RelatedUrls": [
                    {"Type": "GET DATA VIA DIRECT ACCESS",
                     "URL": "s3://lp-prod-protected/x.hdf"},
                    {"Type": "GET DATA", "URL": _hdf_url_1}]}}]}
    try:
        parsed = parse_cmr_granule(cmr_fixture, source)
        if parsed["concept_id"] != "G123-LPCLOUD" or \
           parsed["cmr_granules_considered"] != 1 or \
           parsed["selected_production_timestamp"] != "2024020000000" or \
           parsed["granule_ur"] != "MOD11A1.A2024015.h19v04.061.2024020000000.hdf" or \
           parsed["granule_bare"] != "MOD11A1.A2024015.h19v04.061.2024020000000" or \
           parsed["url"] != _hdf_url_1:
            failures.append("cmr_positive")
    except Exception:
        failures.append("cmr_positive_exception")
    for name, mutate in {
            "hits_gt_items": lambda x: x.__setitem__("hits", 2),
            "host": lambda x: x["items"][0]["umm"]["RelatedUrls"][1].__setitem__(
                "URL", "https://example.invalid/file.hdf"),
            "ur_has_hdf_suffix": lambda x: x["items"][0]["umm"].__setitem__(
                "GranuleUR", "MOD11A1.A2024015.h19v04.061.2024020000000.hdf"),
            "ur_not_13_digits": lambda x: x["items"][0]["umm"].__setitem__(
                "GranuleUR", "MOD11A1.A2024015.h19v04.061.202402000000"),
            "url_wrong_filename": lambda x: x["items"][0]["umm"]["RelatedUrls"][1].__setitem__(
                "URL", _hdf_url_1.rsplit("/", 1)[0] + "/other.hdf"),
    }.items():
        fixture = copy.deepcopy(cmr_fixture)
        mutate(fixture)
        try:
            parse_cmr_granule(fixture, source)
            failures.append("cmr_negative_" + name)
        except AdmissionFailure:
            pass
    reprocessed = copy.deepcopy(cmr_fixture["items"][0])
    reprocessed["umm"]["GranuleUR"] = "MOD11A1.A2024015.h19v04.061.2024300123045"
    reprocessed["umm"]["RelatedUrls"][1]["URL"] = (
        "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/"
        "MOD11A1.061/MOD11A1.A2024015.h19v04.061.2024300123045/"
        "MOD11A1.A2024015.h19v04.061.2024300123045.hdf")
    multi_fixture = {"hits": 2, "took": 1,
                     "items": [copy.deepcopy(cmr_fixture["items"][0]), reprocessed]}
    try:
        picked = parse_cmr_granule(multi_fixture, source)
        if picked["cmr_granules_considered"] != 2 or \
           picked["selected_production_timestamp"] != "2024300123045" or \
           not picked["granule_ur"].endswith("2024300123045.hdf"):
            failures.append("cmr_multi_granule_selection")
    except Exception:
        failures.append("cmr_multi_granule_exception")
    same_timestamp_fixture = {"hits": 2, "took": 1,
                              "items": [copy.deepcopy(cmr_fixture["items"][0]),
                                        copy.deepcopy(cmr_fixture["items"][0])]}
    try:
        parse_cmr_granule(same_timestamp_fixture, source)
        failures.append("cmr_ambiguous_timestamp_not_rejected")
    except AdmissionFailure:
        pass
    # echo10 checksum fetch: the SHA-256 checksum and exact byte size live only in
    # CMR's legacy echo10 XML.  _network_request is stubbed so the parser is
    # exercised offline.
    def _echo10_doc(hdf_name: str, algorithm: str, value: str, size: str,
                    granule_ur: str, online_url: str) -> bytes:
        return (
            "<Granule><GranuleUR>" + granule_ur + "</GranuleUR><DataGranule>"
            "<AdditionalFile><Name>BROWSE.a.jpg</Name><SizeInBytes>2048</SizeInBytes>"
            "<Checksum><Value>" + "a" * 64 + "</Value><Algorithm>SHA256</Algorithm>"
            "</Checksum></AdditionalFile>"
            "<AdditionalFile><Name>" + hdf_name + "</Name>"
            "<SizeInBytes>" + size + "</SizeInBytes><Checksum><Value>" + value +
            "</Value><Algorithm>" + algorithm + "</Algorithm></Checksum></AdditionalFile>"
            "</DataGranule><OnlineAccessURLs><OnlineAccessURL><URL>" + online_url +
            "</URL></OnlineAccessURL></OnlineAccessURLs></Granule>").encode("utf-8")
    _echo_meta = {"concept_id": "G123-LPCLOUD",
                  "granule_bare": "MOD11A1.A2024015.h19v04.061.2024020000000",
                  "granule_ur": "MOD11A1.A2024015.h19v04.061.2024020000000.hdf",
                  "url": _hdf_url_1}
    _echo_good = _echo10_doc("MOD11A1.A2024015.h19v04.061.2024020000000.hdf", "SHA256",
                             "b" * 64, "2378960", _echo_meta["granule_bare"], _hdf_url_1)
    _echo_txn = {"transaction_count": 1, "redirect_count": 0}
    _orig_network_request = _network_request
    try:
        globals()["_network_request"] = lambda *a, **k: (_echo_good, {}, _echo_txn)
        got, txn = fetch_echo10_checksum(dict(_echo_meta),
                                         "nasa_meta_winter_2024_terra_night",
                                         time.monotonic() + 100)
        if got != {"checksum_algorithm": "SHA-256", "checksum": "b" * 64,
                   "declared_size_bytes": 2378960} or txn is not _echo_txn:
            failures.append("echo10_positive")
        for label, doc in {
                "wrong_granule_ur": _echo10_doc(
                    "MOD11A1.A2024015.h19v04.061.2024020000000.hdf", "SHA256", "b" * 64,
                    "2378960", "MOD11A1.A2099999.h19v04.061.2024020000000", _hdf_url_1),
                "no_hdf_entry": _echo10_doc(
                    "MOD11A1.A2024015.h19v04.061.2024020000000.hdf_mvs.h5", "SHA256",
                    "b" * 64, "2378960", _echo_meta["granule_bare"], _hdf_url_1),
                "sha512_algo": _echo10_doc(
                    "MOD11A1.A2024015.h19v04.061.2024020000000.hdf", "sha512", "c" * 128,
                    "2378960", _echo_meta["granule_bare"], _hdf_url_1),
                "bad_checksum_hex": _echo10_doc(
                    "MOD11A1.A2024015.h19v04.061.2024020000000.hdf", "SHA256", "nothex",
                    "2378960", _echo_meta["granule_bare"], _hdf_url_1),
                "bad_size": _echo10_doc(
                    "MOD11A1.A2024015.h19v04.061.2024020000000.hdf", "SHA256", "b" * 64,
                    "0", _echo_meta["granule_bare"], _hdf_url_1),
                "url_mismatch": _echo10_doc(
                    "MOD11A1.A2024015.h19v04.061.2024020000000.hdf", "SHA256", "b" * 64,
                    "2378960", _echo_meta["granule_bare"], "https://example.invalid/x.hdf"),
                "not_xml": b"{not xml",
        }.items():
            globals()["_network_request"] = lambda *a, _d=doc, **k: (_d, {}, _echo_txn)
            try:
                fetch_echo10_checksum(dict(_echo_meta),
                                      "nasa_meta_winter_2024_terra_night",
                                      time.monotonic() + 100)
                failures.append("echo10_negative_" + label)
            except AdmissionFailure:
                pass
    finally:
        globals()["_network_request"] = _orig_network_request
    evidence = synthetic_source_evidence(record)
    if validate_source_evidence_item(
            evidence, "winter_2024", "terra_night", record):
        failures.append("source_evidence_positive")
    source_evidence_mutations = {
        "reader": lambda x: x.__setitem__("hdf_reader", "wrong"),
        "checksum": lambda x: x.__setitem__("declared_checksum", "bad"),
        "hdf_hash": lambda x: x.__setitem__("hdf_sha256", "bad"),
        "sds_name": lambda x: x["sds_names"].__setitem__(0, "wrong"),
        "sds_shape": lambda x: x["sds_shapes"]["QC_Night"].__setitem__(0, 1),
        "concept": lambda x: x.__setitem__("cmr_concept_id", "bad"),
        "granule": lambda x: x.__setitem__("producer_granule_id", "bad.hdf"),
        "sample_hash": lambda x: x.__setitem__("hdf_sample_values_sha256", "4" * 64),
        "sample_count": lambda x: x.__setitem__("sample_count", 0),
        "redirect": lambda x: x["cmr_transaction"].__setitem__("redirect_count", 1),
        "hdf_too_many_redirects": lambda x: x["hdf_transaction"].__setitem__("redirect_count", 3),
        "hdf_redirect_bad_host": lambda x: x["hdf_transaction"].__setitem__(
            "final_host", "evil.example.com"),
        "hdf_redirect_obj_mismatch": lambda x: x["hdf_transaction"].__setitem__(
            "final_path", "/MOD11A1.061/x/other.hdf"),
        "hdf_redirect_no_query": lambda x: x["hdf_transaction"].__setitem__(
            "final_query_present", False),
        "hdf_redirect_same_url": lambda x: x["hdf_transaction"].__setitem__(
            "final_url_sha256", "1" * 64),
        "hdf_redirect_not_https": lambda x: x["hdf_transaction"].__setitem__(
            "final_scheme", "http"),
        "transaction_count": lambda x: x.__setitem__("network_transaction_count", 2),
        "declared_size_zero": lambda x: x.__setitem__("declared_size_bytes", 0),
        "declared_size_unverified": lambda x: x.__setitem__("declared_size_verified", False),
        "meta_redirect": lambda x: x["meta_transaction"].__setitem__("redirect_count", 1),
        "meta_gate": lambda x: x["meta_transaction"].__setitem__(
            "requested_path", "/search/granules.umm_json"),
        "temp_residue": lambda x: x.__setitem__("temporary_hdf_persisted", True),
        "raw_persisted": lambda x: x.__setitem__("raw_hdf_persisted", True),
        "identity": lambda x: x.__setitem__("ee_image_id", "2024_01_16"),
        "tile_id": lambda x: x.__setitem__("modis_sinusoidal_tile_id", "h18v04"),
        "tile_h": lambda x: x.__setitem__("modis_sinusoidal_horizontal_tile", 18),
        "tile_v": lambda x: x.__setitem__("modis_sinusoidal_vertical_tile", 5),
        "tile_derivation": lambda x: x.__setitem__(
            "tile_identity_derived_from_transient_samples", False),
        "cmr_granules_zero": lambda x: x.__setitem__("cmr_granules_considered", 0),
        "cmr_timestamp_shape": lambda x: x.__setitem__("selected_production_timestamp", "bad"),
        "cmr_timestamp_mismatch": lambda x: x.__setitem__(
            "selected_production_timestamp", "2024999999999"),
    }
    for name, mutate in source_evidence_mutations.items():
        fixture = copy.deepcopy(evidence)
        mutate(fixture)
        if not validate_source_evidence_item(
                fixture, "winter_2024", "terra_night", record):
            failures.append("source_evidence_negative_" + name)
    # A directly-served HDF (no redirect) is also acceptable.
    _direct = copy.deepcopy(evidence)
    _gid = _direct["producer_granule_id"]
    _direct["hdf_transaction"].update({
        "redirect_count": 0, "exact_final_url": True, "final_url_sha256": "1" * 64,
        "final_host": ALLOWED_DOWNLOAD_HOST,
        "final_path": _direct["hdf_transaction"]["requested_path"],
        "final_query_present": False})
    if validate_source_evidence_item(_direct, "winter_2024", "terra_night", record):
        failures.append("source_evidence_hdf_direct_positive")
    for host, ok in {
            "d1nklfio7vscoe.cloudfront.net": True,
            "lp-prod-protected.s3.us-west-2.amazonaws.com": True,
            "s3.us-west-2.amazonaws.com": True,
            "s3-us-west-2.amazonaws.com": True,
            "s3.amazonaws.com": True,
            "data.lpdaac.earthdatacloud.nasa.gov": True,
            "urs.earthdata.nasa.gov": False,
            "cloudfront.net": False,
            "d1nklfio7vscoe.cloudfront.net.attacker.net": False,
            "evil-s3.amazonaws.com.attacker.net": False,
            "": False}.items():
        if _is_allowed_download_redirect_host(host) is not ok:
            failures.append("download_redirect_host_classification:" + host)
    _redir_base = ("https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/"
                   "MOD11A1.061/g/g.hdf")
    try:
        good = _validate_hdf_redirect(
            _redir_base,
            "https://d1nklfio7vscoe.cloudfront.net/MOD11A1.061/g/g.hdf?A-userid=x&X-Amz-Sig=1",
            "g.hdf")
        if not good.endswith("g.hdf?A-userid=x&X-Amz-Sig=1"):
            failures.append("hdf_redirect_positive")
    except AdmissionFailure:
        failures.append("hdf_redirect_positive_exception")
    for label, loc in {
            "not_allowed_host": "https://urs.earthdata.nasa.gov/oauth/authorize?x=1",
            "wrong_object": "https://d1nklfio7vscoe.cloudfront.net/x/other.hdf?s=1",
            "http_scheme": "http://d1nklfio7vscoe.cloudfront.net/g.hdf?s=1",
            "suffix_attack": "https://d1nklfio7vscoe.cloudfront.net.attacker.net/g.hdf?s=1",
            "empty": ""}.items():
        try:
            _validate_hdf_redirect(_redir_base, loc, "g.hdf")
            failures.append("hdf_redirect_negative_" + label)
        except AdmissionFailure:
            pass
    handle, cleanup_path_raw = tempfile.mkstemp(prefix="audit012-cleanup-test-", suffix=".tmp")
    os.close(handle)
    cleanup_path = Path(cleanup_path_raw)
    try:
        _unlink_and_verify(cleanup_path)
        if cleanup_path.exists():
            failures.append("windows_unlink_residue")
    except Exception:
        failures.append("windows_unlink_exception")
    if _NoRedirect().redirect_request(None, None, 302, "Found", {},
                                      "https://example.invalid") is not None:
        failures.append("redirect_handler")
    for forbidden in ("coordinates", "latitude", "bbox", "coordinateArray"):
        fixture = copy.deepcopy(record)
        fixture[forbidden] = 1
        try:
            validate_coordinate_free(fixture)
            failures.append("coordinate_guard_" + forbidden)
        except ValueError:
            pass
    print(json.dumps({"self_test": not failures, "failures": failures,
                      "request_decomposition": REQUEST_DECOMPOSITION}, sort_keys=True))
    return 0 if not failures else 2


def source_access_preflight() -> dict[str, Any]:
    try:
        if importlib_metadata.version("pyhdf") != "0.11.7":
            raise AdmissionFailure("PYHDF_VERSION_PIN_FAILED")
        from pyhdf.SD import SD  # type: ignore  # noqa: F401
    except AdmissionFailure:
        raise
    except Exception:
        raise AdmissionFailure("PYHDF_0_11_7_UNAVAILABLE")
    token = os.environ.get("EARTHDATA_BEARER_TOKEN")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+\-/=]{20,4096}", token):
        raise AdmissionFailure("EARTHDATA_BEARER_TOKEN_MISSING_OR_MALFORMED")
    return {"cmr_endpoint_sha256": hashlib.sha256(CMR_ENDPOINT.encode("ascii")).hexdigest(),
            "download_host": ALLOWED_DOWNLOAD_HOST, "hdf_reader": HDF_READER_VERSION,
            "earthdata_token_present": True, "earthdata_token_included": False}


def temperature_selectivity(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for result in results:
        for record in result["records"]:
            lookup = {(item["group"], item["variable"]): item["statistics"]
                      for item in record["group_distributions"]}
            comparisons = []
            for left, right in (("A_intersection_B", "A_only"), ("B", "C_minus_B")):
                left_stat, right_stat = lookup[(left, "temperature_c")], lookup[(right, "temperature_c")]
                difference = None
                if left_stat["mean"] is not None and right_stat["mean"] is not None:
                    difference = right_stat["mean"] - left_stat["mean"]
                comparisons.append({"left_group": left, "right_group": right,
                                    "right_minus_left_mean_temperature_c": difference})
            output.append({
                "date_utc": record["date_utc"], "window_id": record["window_id"],
                "stream_id": record["stream_id"], "erosion_id": record["erosion_id"],
                "group_distributions": record["group_distributions"],
                "temperature_mean_differences": comparisons,
            })
    return output


def execute(project: str) -> int:
    session_deadline = time.monotonic() + SESSION_LIMIT_SECONDS
    source_access = source_access_preflight()
    audit = load_audit()
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
    print(json.dumps({"NIGHTTIME_QA_COMPARISON_PREFLIGHT": {
        "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
        "pinned_audit_runner_sha256": EXPECTED_AUDIT_RUNNER_SHA256,
        "pinned_audit011_runner_sha256": EXPECTED_AUDIT011_RUNNER_SHA256,
        "source_evidence_sha256": canonical_sha256(source_evidence),
        "source_access": source_access, "request_policy": policy,
        "request_decomposition": REQUEST_DECOMPOSITION,
        "completed_audit_checkpoint_read_or_written": False,
        "source_coordinate_arrays_included": False,
    }}, sort_keys=True), flush=True)
    runner = ComparisonRunner(audit, ee, geometry_json, source_record, options)
    runtime_fixture = audit.evaluate_authenticated_phase(
        runner.server_runtime_fixture, "runtime_fixture", **options)
    fixture_errors = audit.validate_server_runtime_fixture(runtime_fixture)
    if fixture_errors:
        raise AdmissionFailure("SERVER_RUNTIME_FIXTURE_FAILED")
    projection_digests = []
    for window in WINDOWS:
        for stream in runner.streams:
            phase = f"projection_inventory_{window['window_id']}_{stream['stream_id']}"
            inventory = audit.bounded_transient_getinfo(
                lambda w=window, s=stream: runner.projection_inventory_evidence(w, s),
                phase, **options)
            if inventory.get("record_count") != 14 or len(inventory.get("records", [])) != 14 or \
               not inventory.get("pass") or any(record.get("source_image_count") != 1
                                                  for record in inventory.get("records", [])):
                raise AdmissionFailure("PROJECTION_INVENTORY_FAILED")
            runner.register_projection_inventory(inventory)
            projection_digests.append({
                "window_id": window["window_id"], "stream_id": stream["stream_id"],
                "record_count": 14,
                "source_image_ids_sha256": canonical_sha256(
                    [record["source_image_ids"] for record in inventory["records"]]),
                "projection_inventory_sha256": canonical_sha256(inventory), "pass": True,
            })
    earliest_positions: dict[tuple[str, str], int] = {}
    for window in WINDOWS:
        for stream in runner.streams:
            phase = f"earliest_anomaly_{window['window_id']}_{stream['stream_id']}"
            probe = audit.evaluate_authenticated_phase(
                lambda w=window, s=stream: runner.earliest_anomaly_position(w, s),
                phase, **options)
            if not isinstance(probe, dict) or probe.get("window_id") != window["window_id"] or \
               probe.get("stream_id") != stream["stream_id"] or \
               probe.get("date_count") != WINDOW_DATE_COUNT or \
               not isinstance(probe.get("position"), int) or isinstance(probe.get("position"), bool) or \
               not -1 <= probe["position"] < WINDOW_DATE_COUNT or \
               probe.get("coordinate_free") is not True:
                raise AdmissionFailure("EARLIEST_ANOMALY_PROBE_FAILED")
            earliest_positions[(window["window_id"], stream["stream_id"])] = probe["position"]

    results: list[dict[str, Any]] = []
    transient_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for window in WINDOWS:
        for stream in runner.streams:
            for treatment in audit.TREATMENTS:
                is_original = treatment["erosion_id"] == "EROSION_0000M"
                earliest = earliest_positions[(window["window_id"], stream["stream_id"])] \
                    if is_original else -1
                pieces: list[dict[str, Any]] = []
                for batch in DATE_BATCHES:
                    phase = (f"nighttime_qa_comparison_{window['window_id']}_"
                             f"{stream['stream_id']}_{treatment['erosion_id']}_b{batch[0]:02d}")
                    remaining = session_deadline - time.monotonic()
                    pause = max(0.0, min(COMPARISON_REQUEST_PAUSE_SECONDS, remaining - 180.0))
                    if pause > 0:
                        print(json.dumps({"NIGHTTIME_QA_COMPARISON_CONCURRENCY_PAUSE": {
                            "phase": "unclassified_phase", "pause_seconds": round(pause, 1)}},
                            sort_keys=True), flush=True)
                        time.sleep(pause)
                    piece = audit.evaluate_authenticated_phase(
                        lambda w=window, s=stream, t=treatment, b=batch, e=earliest:
                            runner.graph(w, s, t, list(b), e),
                        phase, **options)
                    piece_errors = validate_batch_piece(piece, window, stream, treatment, batch)
                    if piece_errors:
                        raise AdmissionFailure("COMPARISON_BATCH_ADMISSION_FAILED:" + piece_errors[0])
                    pieces.append(piece)
                result = assemble_batches(pieces)
                errors, transient = validate_result(result, window, stream, treatment)
                if errors:
                    raise AdmissionFailure("COMPARISON_ADMISSION_FAILED:" + errors[0])
                for selection in transient:
                    transient_by_key[(selection["window_id"], selection["stream_id"],
                                      selection["date_utc"])] = selection["samples"]
                results.append(result)
    selected, not_applicable = select_source_verifications(results, transient_by_key)
    source_verification = list(not_applicable)
    for selection in selected:
        source_verification.append(verify_original_source(selection, session_deadline))
    source_verification.sort(key=lambda item: (
        [window["window_id"] for window in WINDOWS].index(item["window_id"]),
        NIGHT_STREAM_IDS.index(item["stream_id"])))
    original_results = {(result["window_id"], result["stream_id"]): result
                        for result in results if result["erosion_id"] == "EROSION_0000M"}
    for item in source_verification:
        original = original_results[(item["window_id"], item["stream_id"])]
        anomalous = [record for record in original["records"]
                     if metric_map(record)["M0_D_gt0"]["pixel_center_count"] > 0]
        evidence_errors = validate_source_evidence_item(
            item, item["window_id"], item["stream_id"], anomalous[0] if anomalous else None)
        if evidence_errors:
            raise AdmissionFailure("SOURCE_EVIDENCE_ADMISSION_FAILED:" + evidence_errors[0])
    seasonal, shoreline = build_summaries(results)
    final = {
        "specification": SPECIFICATION, "implementation": IMPLEMENTATION,
        "coordinate_free": True, "source_coordinate_arrays_included": False,
        "candidate_definitions": CANDIDATES,
        "candidate_ordering_interpretation": (
            "A is non-nested with B and C; B is an exact subset of C; no candidate is selected"),
        "joint_qc_table_encoding": (
            "fixed arrays indexed by raw QC byte q=0..255; M=q&3,D=(q>>2)&3,E=(q>>4)&3,T=(q>>6)&3"),
        "request_decomposition": REQUEST_DECOMPOSITION,
        "projection_certification_digests": projection_digests,
        "observation_count": 112, "treatment_record_count": 448,
        "result_count": len(results), "results": results,
        "seasonal_candidate_summaries": seasonal,
        "shoreline_sensitivity_summaries": shoreline,
        "temperature_and_ancillary_selectivity": temperature_selectivity(results),
        "original_nasa_hdf_source_verification": source_verification,
        "nasa_network_transaction_count": sum(
            item["network_transaction_count"] for item in source_verification),
        "validation_errors": [], "pass": len(results) == 32 and len(source_verification) == 8,
        "scientific_interpretation": (
            "Bounded simultaneous A/B/C diagnostic comparison only. It selects no QA rule and "
            "does not change or relax the completed strict audit mask."),
    }
    validate_coordinate_free(final)
    print(json.dumps({"NIGHTTIME_QA_CANDIDATE_COMPARISON_COMPLETE": final},
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
    except AdmissionFailure as exc:
        print(json.dumps({"NIGHTTIME_QA_CANDIDATE_COMPARISON_FAILED": {
            "exception_class": type(exc).__name__, "validation_error_code": exc.code,
            "coordinate_free": True, "raw_values_included": False,
            "source_coordinate_arrays_included": False, "acceptance_claimed": False,
        }}, sort_keys=True), flush=True)
        return 2
    except Exception as exc:
        # Surface the Earth Engine / transport message (structural, e.g.
        # "Too many concurrent aggregations", "User memory limit exceeded") so a
        # failure is self-diagnosing.  Truncated and coordinate-free-screened; no
        # evaluated numbers or arrays are in an EEException message.
        message = str(exc)[:400]
        try:
            validate_coordinate_free({"exception_message": message})
        except Exception:
            message = "<redacted: failed coordinate-free screen>"
        print(json.dumps({"NIGHTTIME_QA_CANDIDATE_COMPARISON_FAILED": True,
                          "exception_class": type(exc).__name__,
                          "exception_message": message,
                          "acceptance_claimed": False}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
