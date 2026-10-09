#!/usr/bin/env python3
"""Bounded official Earth Engine Python-API runner for AUDIT-001/AUDIT-003.

The WISE geometry is verified afresh and retained in memory.  The runner creates
no Earth Engine asset, export, task, deployment, or UI.  It evaluates one vector
row or one 14-row stream subrequest at a time.  Four canonical stream results
are combined into one unchanged 56-row logical chunk in memory; no partial
subrequest evidence is persisted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
from importlib import metadata as importlib_metadata
import json
import math
import os
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "tools" / "verify_wise_huaih049.py"

VERSION = {
    "schema": "whole_lake_shoreline_audit_v1",
    "vector_schema": "whole_lake_vector_manifest_v1_34_fields",
    "coverage_schema": "whole_lake_coverage_manifest_v1_45_fields",
    "specification": "AUDIT-001_AUDIT-003_AUDIT-005_AUDIT-006_AUDIT-007_AUDIT-008_AUDIT-009_AUDIT-010_2026-08-23",
    "implementation": "whole_lake_boundary_shoreline_audit_python_api_v11_immediate_stream_summary_gates",
}
PROTO_VERSION = {
    "schema": "modis_diagnostic_schema_v2_sparse_omission",
    "rule": "strict_engineering_qa_v1",
    "specification": "PROTO-001+PROTO-002_2026-08-17",
    "implementation": "modis_preprocessing_prototype_v2",
    "histogram": "fixed_index_array_v1",
}
WINDOWS = [
    {"window_id": "winter_2024", "season": "winter", "start": "2024-01-15", "end": "2024-01-29"},
    {"window_id": "spring_2024", "season": "spring", "start": "2024-04-15", "end": "2024-04-29"},
    {"window_id": "summer_2024", "season": "summer", "start": "2024-07-15", "end": "2024-07-29"},
    {"window_id": "autumn_2024", "season": "autumn", "start": "2024-10-15", "end": "2024-10-29"},
]
TREATMENTS = [
    {"erosion_id": "EROSION_0000M", "suffix": "erosion_0000m", "distance_m": 0.0},
    {"erosion_id": "EROSION_0463_3127M", "suffix": "erosion_0463_3127m", "distance_m": 463.31271656937485},
    {"erosion_id": "EROSION_0500M", "suffix": "erosion_0500m", "distance_m": 500.0},
    {"erosion_id": "EROSION_0926_6254M", "suffix": "erosion_0926_6254m", "distance_m": 926.6254331387497},
]
STREAMS = [
    {"stream_id": "terra_day", "platform": "Terra", "phase": "day", "collection_id": "MODIS/061/MOD11A1", "lst": "LST_Day_1km", "qc": "QC_Day", "time": "Day_view_time", "angle": "Day_view_angle", "clear": "Clear_day_cov"},
    {"stream_id": "terra_night", "platform": "Terra", "phase": "night", "collection_id": "MODIS/061/MOD11A1", "lst": "LST_Night_1km", "qc": "QC_Night", "time": "Night_view_time", "angle": "Night_view_angle", "clear": "Clear_night_cov"},
    {"stream_id": "aqua_day", "platform": "Aqua", "phase": "day", "collection_id": "MODIS/061/MYD11A1", "lst": "LST_Day_1km", "qc": "QC_Day", "time": "Day_view_time", "angle": "Day_view_angle", "clear": "Clear_day_cov"},
    {"stream_id": "aqua_night", "platform": "Aqua", "phase": "night", "collection_id": "MODIS/061/MYD11A1", "lst": "LST_Night_1km", "qc": "QC_Night", "time": "Night_view_time", "angle": "Night_view_angle", "clear": "Clear_night_cov"},
]
CHUNK_REQUEST_DECOMPOSITION = {
    "logical_chunk_rows": 56,
    "subrequest_count": 4,
    "rows_per_subrequest": 14,
    "stream_order": [stream["stream_id"] for stream in STREAMS],
    "sequential": True,
    "atomic_save_after_all_subrequests": True,
    "partial_subrequest_persistence": False,
}
SOURCE_CITATION = (
    "EEA WISE WFD v1.9 (September 2025), unrounded WFD2022 "
    "SurfaceWaterBody_polygon HUAIH049 (cYear 2022), cross-checked against "
    "the original Hungarian EPSG:3035 CDR GML."
)
AUDIT_NOTE = "AUDIT-001 sensitivity diagnostic only; no boundary, erosion distance, or coverage threshold is approved."
AUDIT_WARNING = (
    "The verified unrounded WISE HUAIH049 polygon and inward buffers are candidate "
    "whole-lake sensitivity geometries for AUDIT-001 only; no final boundary, erosion "
    "distance, or coverage threshold is approved."
)
PROTOTYPE_WATER_WARNING = "ROI is a provisional geometry proxy, not an authoritative water mask or application-grade coverage denominator."
COORDINATE_NOTE = (
    "Verified unrounded WISE WGS84 coordinates, cross-checked against the original "
    "Hungarian EPSG:3035 CDR GML, transformed to EPSG:3035 for planar inward "
    "buffering; no coordinate rounding; 1 m maximum operation error."
)
OP_CRS = "EPSG:3035"
EE_SERIALIZER_RECURSION_LIMIT = 10_000
DEFAULT_EE_REQUEST_DEADLINE_SECONDS = 8 * 60
MIN_EE_REQUEST_DEADLINE_SECONDS = DEFAULT_EE_REQUEST_DEADLINE_SECONDS
MAX_EE_REQUEST_DEADLINE_SECONDS = DEFAULT_EE_REQUEST_DEADLINE_SECONDS
DEFAULT_EE_TRANSPORT_MAX_ATTEMPTS = 1
MAX_EE_TRANSPORT_MAX_ATTEMPTS = 1
SESSION_LIMIT_SECONDS = 165 * 60
SESSION_COMPLETION_RESERVE_SECONDS = 60
CHECKPOINT_PATH = ROOT / "local_run_state" / "whole_lake_boundary_shoreline_audit_checkpoint.json"
CHECKPOINT_FORMAT = "whole_lake_boundary_shoreline_audit_checkpoint_v1"
ORIGINAL_GML_CONTENT_TYPE_METHOD = {
    "decision": "AUDIT-007",
    "media_type": "text/xml",
    "media_type_case_sensitive": False,
    "allowed_parameter_counts": [0, 1],
    "only_allowed_parameter": "charset",
    "allowed_charset": "UTF-8",
    "parameter_name_and_charset_case_sensitive": False,
    "duplicate_charset_rejected": True,
    "unknown_parameters_rejected": True,
    "malformed_syntax_rejected": True,
}
COORDINATE_FREE_FORBIDDEN_KEY_ALIASES = {
    "bounds", "bbox", "boundingbox", "geometry", "coordinate", "coordinates",
    "coord", "coords", "coordinatearray", "coordarray", "extent", "envelope",
    "lat", "latitude", "lon", "lng", "long", "longitude",
    "minlat", "maxlat", "minlon", "maxlon", "minlng", "maxlng",
    "minlatitude", "maxlatitude", "minlongitude", "maxlongitude",
    "xmin", "xmax", "ymin", "ymax", "minx", "maxx", "miny", "maxy",
}
COORDINATE_FIELDS_OMITTED_REQUIRED_VALUES = {
    "geometry", "bbox_wgs84", "lat", "lon",
    "seven_decimal_self_intersection",
}
COORDINATE_FREE_METRIC_KEYS = (
    "area_m2", "perimeter_m", "geometry_type", "part_count", "hole_count",
    "vertex_count_including_ring_closure", "is_empty", "is_valid", "is_simple",
    "validity_explanation",
)
COORDINATE_FREE_GML_PARSED_SCALAR_KEYS = (
    "axis_order_in_document", "axis_swap_applied",
    "coordinate_tuple_count_including_closure", "crs_bearing_element",
    "geometry_type", "hole_count", "is_empty", "is_simple", "is_valid",
    "part_count", "shapely_coordinate_order", "srs_dimension", "srs_name",
)
MODIS_GRID_WIDTH_COLUMNS = 43_200
MODIS_GRID_HEIGHT_ROWS = 21_600
AUDIT_AFFINE_MAX_DISPLACEMENT_M = 0.0001
MODIS_GRID_CORNER_CONVENTION = (
    "Pixel-grid outer corner coordinates (column,row): "
    "(0,0),(43200,0),(0,21600),(43200,21600); "
    "x=a*column+b*row+c; y=d*column+e*row+f."
)
SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS = [
    "eligible_roi_area_m2",
    "accepted_roi_fraction",
    "provisional_eligible_water_area_m2",
    "provisional_valid_water_area_m2",
    "provisional_valid_water_coverage_fraction",
    "accepted_area_m2",
    "produced_lst_area_m2",
    "produced_rejected_area_m2",
    "cloud_area_m2",
    "noncloud_no_retrieval_area_m2",
    "missing_qc_area_m2",
    "eligible_pixel_center_count",
    "qc_observed_pixel_center_count",
    "produced_lst_pixel_center_count",
    "accepted_pixel_center_count",
    "produced_rejected_pixel_center_count",
    "cloud_pixel_center_count",
    "noncloud_no_retrieval_pixel_center_count",
    "missing_qc_pixel_center_count",
    "area_partition_sum_m2",
    "area_partition_residual_m2",
    "area_partition_absolute_error_m2",
    "area_partition_relative_error",
    "area_partition_tolerance_m2",
    "area_partition_pass",
    "unclassified_area_m2",
    "overlap_excess_area_m2",
    "has_cloud",
    "has_rejected_qa",
    "has_noncloud_no_retrieval",
    "has_missing_qc",
    "failure_reason_count",
    "has_mixed_failure_reasons",
    "row_state",
    "source_image_id",
    "source_system_time_start",
    "source_image_ids_if_duplicate",
]
SINGLE_SOURCE_SPARSE_ERROR_BRANCHES = {
    "projection_mismatch": {
        "validation_error": "SOURCE_PROJECTION_MISMATCH",
        "row_state": "SOURCE_PRESENT_NO_RETRIEVAL",
        "state_reason": (
            "Source projection differs from the canonical stream projection; "
            "diagnostics were not computed."
        ),
    },
    "nonpositive_eligible_roi_area": {
        "validation_error": "NONPOSITIVE_ELIGIBLE_ROI_AREA",
        "row_state": "SOURCE_PRESENT_NO_RETRIEVAL",
        "state_reason": (
            "Eligible ROI area is nonpositive; diagnostics were not computed."
        ),
    },
}
SPARSE_BRANCH_ALLOWED_NULLABLE_FIELDS = {
    "source_image_id", "source_system_time_start", "null_reason", "notes",
}
SPARSE_BRANCH_INTERNAL_PROVENANCE_FIELDS = [
    "_sparse_expected_notes",
    "_sparse_expected_projection_reference_image_id",
    "_sparse_expected_source_crs",
    "_sparse_expected_source_crs_transform",
    "_sparse_expected_reducer_scale_or_transform",
]
VALIDATION_ERROR_DETAIL_FIELDS = [
    "date_utc", "stream_id", "_audit_key", "validation_errors", "row_state",
    "null_reason", "state_reason", "projection_reference_image_id", "source_crs",
    "_strict_row_errors",
]


def configure_ee_serializer_recursion_limit() -> dict[str, Any]:
    """Raise Python's stack bound for the official EE serializer, deterministically.

    The 56-row graph is bounded, but the EE expression serializer recursively
    traverses its nested DAG. This changes only local serialization capacity;
    it does not alter or simplify any Earth Engine object or geometry.
    """
    previous = sys.getrecursionlimit()
    effective = max(previous, EE_SERIALIZER_RECURSION_LIMIT)
    if effective != previous:
        sys.setrecursionlimit(effective)
    return {"previous_limit": previous, "configured_minimum": EE_SERIALIZER_RECURSION_LIMIT,
            "effective_limit": sys.getrecursionlimit(),
            "reason": "bounded official Earth Engine Python expression serialization"}


def type7(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    h = (len(values) - 1) * p
    lo, hi = math.floor(h), math.ceil(h)
    return values[lo] + (h - lo) * (values[hi] - values[lo])


def population_sd(values: list[float]) -> float | None:
    return statistics.pstdev(values) if values else None


def affine_displacement_evidence(canonical_affine: Iterable[float],
                                 source_affine: Iterable[float]) -> dict[str, Any]:
    """Compute exact full-grid corner displacement from a six-affine delta."""
    canonical = list(canonical_affine)
    source = list(source_affine)
    if len(canonical) != 6 or len(source) != 6 or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and
            math.isfinite(value) for value in canonical + source):
        raise ValueError("AFFINE_EVIDENCE_REQUIRES_TWO_FINITE_SIX_NUMBER_LISTS")
    canonical = [float(value) for value in canonical]
    source = [float(value) for value in source]
    delta = [source_value - canonical_value
             for source_value, canonical_value in zip(source, canonical)]
    corners = [
        (0, 0),
        (MODIS_GRID_WIDTH_COLUMNS, 0),
        (0, MODIS_GRID_HEIGHT_ROWS),
        (MODIS_GRID_WIDTH_COLUMNS, MODIS_GRID_HEIGHT_ROWS),
    ]
    corner_evidence = []
    for column, row in corners:
        delta_x = delta[0] * column + delta[1] * row + delta[2]
        delta_y = delta[3] * column + delta[4] * row + delta[5]
        corner_evidence.append({
            "column": column,
            "row": row,
            "delta_x_m": float(delta_x),
            "delta_y_m": float(delta_y),
            "displacement_m": float(math.hypot(delta_x, delta_y)),
        })
    maximum = max(item["displacement_m"] for item in corner_evidence)
    evidence = {
        "canonical_affine": canonical,
        "source_affine": source,
        "affine_elementwise_difference": delta,
        "grid_width_columns": MODIS_GRID_WIDTH_COLUMNS,
        "grid_height_rows": MODIS_GRID_HEIGHT_ROWS,
        "grid_corner_convention": MODIS_GRID_CORNER_CONVENTION,
        "corner_displacements": corner_evidence,
        "maximum_induced_displacement_m": float(maximum),
        "maximum_allowed_displacement_m": AUDIT_AFFINE_MAX_DISPLACEMENT_M,
        "affine_numerically_equivalent": maximum <= AUDIT_AFFINE_MAX_DISPLACEMENT_M,
    }
    return evidence


def validate_chunk_bounds(start_chunk: int, end_chunk: int | None) -> tuple[int, int]:
    stop = 16 if end_chunk is None else end_chunk
    if not (1 <= start_chunk <= 16) or not (1 <= stop <= 16) or stop < start_chunk:
        raise ValueError("chunk bounds must satisfy 1 <= start <= end <= 16")
    return start_chunk, stop


class SessionCeilingReached(RuntimeError):
    """Clean bounded-session stop; validated checkpoint evidence remains durable."""

    def __init__(self, phase: str, remaining_seconds: float) -> None:
        super().__init__("AUDIT_SESSION_CEILING_REACHED")
        self.phase = safe_phase_category(phase)
        self.remaining_seconds = max(0.0, float(remaining_seconds))


def enforce_session_budget(session_deadline_monotonic: float | None,
                           phase: str, *, required_remaining_seconds: float = 0,
                           clock: Any = time.monotonic) -> float:
    """Stop controllable work at deterministic boundaries around blocking calls."""
    if session_deadline_monotonic is None:
        return math.inf
    remaining = session_deadline_monotonic - clock()
    if remaining <= required_remaining_seconds:
        raise SessionCeilingReached(phase, remaining)
    return remaining


def guarded_local_action(action: Any, phase: str, *,
                         session_deadline_monotonic: float | None = None,
                         clock: Any = time.monotonic) -> Any:
    """Apply hard-ceiling checks immediately before and after one local action."""
    enforce_session_budget(session_deadline_monotonic, phase, clock=clock)
    result = action()
    enforce_session_budget(session_deadline_monotonic, phase, clock=clock)
    return result


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_coordinate_free_compatibility(compatibility: dict[str, Any]) -> None:
    """Reject spatial keys and coordinate-shaped arrays from checkpoint compatibility."""
    source_evidence = compatibility.get("verified_source_evidence")
    if not isinstance(source_evidence, dict):
        raise ValueError("COORDINATE_FREE_SOURCE_EVIDENCE_MISSING")

    def normalized_key_parts(key: str) -> tuple[set[str], str]:
        normalized = unicodedata.normalize("NFKC", key)
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
        normalized = re.sub(r"[^0-9A-Za-z]+", "_", normalized).strip("_").casefold()
        tokens = {token for token in normalized.split("_") if token}
        return tokens, "".join(normalized.split("_"))

    def require_allowed_spatial_identity(key: str, child: Any,
                                         path: tuple[str, ...]) -> bool:
        exact = {
            "coordinate_rounding_applied": child is False,
            "coordinates_persisted": child is False,
            "coordinate_tuple_count_including_closure": (
                isinstance(child, int) and not isinstance(child, bool) and
                child == 11012),
            "geometry_type": child == "Polygon",
            "geometry_is_valid": child is True,
            "geometry_is_simple": child is True,
            "shapely_coordinate_order": child == "easting_northing",
            "axis_order_in_document": child == "northing_easting",
            "axis_swap_applied": child is True,
        }
        if key == "coordinate_fields_omitted":
            valid = isinstance(child, list) and all(
                isinstance(item, str) for item in child) and \
                len(child) == len(COORDINATE_FIELDS_OMITTED_REQUIRED_VALUES) and \
                len(child) == len(set(child)) and \
                set(child) == COORDINATE_FIELDS_OMITTED_REQUIRED_VALUES
            if not valid:
                raise ValueError(
                    "COORDINATE_FREE_COMPATIBILITY_ALLOWED_FIELD_INVALID:" +
                    ".".join(path + (key,)))
            return True
        if key not in exact:
            return False
        if not exact[key]:
            raise ValueError(
                "COORDINATE_FREE_COMPATIBILITY_ALLOWED_SCALAR_INVALID:" +
                ".".join(path + (key,)))
        return True

    def walk_keys(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("COORDINATE_FREE_COMPATIBILITY_NONSTRING_KEY")
                allowed_spatial_identity = require_allowed_spatial_identity(
                    key, child, path)
                tokens, compact = normalized_key_parts(key)
                coordinate_alias = bool(
                    tokens.intersection(COORDINATE_FREE_FORBIDDEN_KEY_ALIASES) or
                    compact in COORDINATE_FREE_FORBIDDEN_KEY_ALIASES)
                if coordinate_alias and not allowed_spatial_identity:
                    raise ValueError(
                        "COORDINATE_FREE_COMPATIBILITY_FORBIDDEN_KEY:" +
                        ".".join(path + (key,)))
                if key != "coordinate_fields_omitted":
                    walk_keys(child, path + (key,))
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk_keys(child, path + (str(index),))

    def reject_numeric_arrays(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                reject_numeric_arrays(child, path + (key,))
        elif isinstance(value, (list, tuple)):
            if len(value) >= 2 and all(
                    isinstance(item, (int, float)) and not isinstance(item, bool)
                    for item in value):
                raise ValueError(
                    "COORDINATE_FREE_SOURCE_NUMERIC_ARRAY:" + ".".join(path))
            for index, child in enumerate(value):
                reject_numeric_arrays(child, path + (str(index),))

    walk_keys(compatibility)
    reject_numeric_arrays(source_evidence)


def checkpoint_compatibility(source_evidence: dict[str, Any], project: str,
                             earthengine_version: str,
                             request_policy: dict[str, Any]) -> dict[str, Any]:
    """Bind checkpoint evidence to every approved source/method/runtime contract."""
    manifests = load_authoritative_manifests()
    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    compatibility = {
        "checkpoint_format": CHECKPOINT_FORMAT,
        "verified_source_evidence": source_evidence,
        "approved_versions": {"audit": VERSION, "prototype": PROTO_VERSION},
        "implementation_file_sha256": runner_sha256,
        "verified_source_method": {
            "original_gml_content_type": ORIGINAL_GML_CONTENT_TYPE_METHOD,
            "verifier_file_sha256": hashlib.sha256(
                VERIFIER_PATH.read_bytes()).hexdigest(),
        },
        "runtime": {
            "python_version": sys.version.split()[0],
            "earthengine_api_version": earthengine_version,
            "google_cloud_project_id": project,
            "request_deadline_seconds": request_policy["deadline_seconds"],
            "transport_max_attempts": request_policy["max_attempts"],
            "earth_engine_internal_retries": 0,
            "session_limit_seconds": SESSION_LIMIT_SECONDS,
        },
        "request_decomposition": CHUNK_REQUEST_DECOMPOSITION,
        "windows": WINDOWS,
        "streams": STREAMS,
        "shoreline_treatments": TREATMENTS,
        "authoritative_manifests": manifests,
        "manifest_source_sha256": {
            "prototype": hashlib.sha256((
                ROOT / "src/prototype/modis_preprocessing_prototype.js").read_bytes()).hexdigest(),
            "audit": hashlib.sha256((
                ROOT / "src/audit/whole_lake_boundary_shoreline_audit.js").read_bytes()).hexdigest(),
        },
    }
    validate_coordinate_free_compatibility(compatibility)
    return compatibility


def empty_checkpoint(compatibility: dict[str, Any]) -> dict[str, Any]:
    return {
        "checkpoint_format": CHECKPOINT_FORMAT,
        "compatibility_sha256": canonical_sha256(compatibility),
        "compatibility": compatibility,
        "completed_vectors": {},
        "completed_chunks": {},
        "full_acceptance_claimed": False,
    }


def load_checkpoint(compatibility: dict[str, Any]) -> dict[str, Any]:
    expected = empty_checkpoint(compatibility)
    if not CHECKPOINT_PATH.exists():
        return expected
    try:
        observed = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("CHECKPOINT_READ_OR_JSON_FAILED") from exc
    if not isinstance(observed, dict) or \
       observed.get("checkpoint_format") != CHECKPOINT_FORMAT or \
       observed.get("compatibility_sha256") != expected["compatibility_sha256"] or \
       observed.get("compatibility") != compatibility:
        raise ValueError("CHECKPOINT_INCOMPATIBLE_FAIL_CLOSED")
    if set(observed) != set(expected) or \
       not isinstance(observed.get("completed_vectors"), dict) or \
       not isinstance(observed.get("completed_chunks"), dict) or \
       observed.get("full_acceptance_claimed") is not False:
        raise ValueError("CHECKPOINT_SHAPE_FAILED")
    return observed


def atomic_save_checkpoint(checkpoint: dict[str, Any], *,
                           session_deadline_monotonic: float | None = None,
                           clock: Any = time.monotonic) -> None:
    """Persist only a completely revalidated phase, atomically in the same directory."""
    def persist() -> None:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CHECKPOINT_PATH.with_name(CHECKPOINT_PATH.name + ".tmp")
        payload = json.dumps(checkpoint, indent=2, sort_keys=True) + "\n"
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, CHECKPOINT_PATH)
        finally:
            if temporary.exists():
                temporary.unlink()
    guarded_local_action(
        persist, "checkpoint_save",
        session_deadline_monotonic=session_deadline_monotonic, clock=clock)


def compact_validated_vector(properties: dict[str, Any]) -> dict[str, Any]:
    """Drop the coordinate-bearing bbox after full 34-field validation."""
    compact = {name: properties[name] for name in FINAL_DIGEST_VECTOR_FIELDS
               if name in properties}
    compact["validated_full_manifest_sha256"] = canonical_sha256(properties)
    return compact


def validate_compact_vectors(vectors: list[dict[str, Any]],
                             expected_count: int = 4) -> list[str]:
    errors: list[str] = []
    if len(vectors) != expected_count or not 1 <= expected_count <= 4:
        return ["VECTOR_COUNT_MISMATCH"]
    source_area = vectors[0].get("vector_area_epsg3035_m2")
    if not isinstance(source_area, (int, float)) or isinstance(source_area, bool) or \
       not math.isfinite(source_area) or source_area <= 0:
        return ["VECTOR_SOURCE_AREA_INVALID"]
    tolerance = max(100.0, float(source_area) * 1e-6)
    for index, (vector, treatment) in enumerate(zip(vectors, TREATMENTS)):
        expected_fields = set(FINAL_DIGEST_VECTOR_FIELDS) | {
            "validated_full_manifest_sha256"}
        if index == 0:
            expected_fields.remove("weaker_candidate_containment_area_m2")
        if not isinstance(vector, dict) or set(vector) != expected_fields:
            errors.append("COORDINATE_FREE_VECTOR_SHAPE_FAILED")
            continue
        if vector["erosion_id"] != treatment["erosion_id"] or \
           vector["erosion_distance_m"] != float(treatment["distance_m"]):
            errors.append("VECTOR_TREATMENT_IDENTITY_FAILED")
        if not re.fullmatch(r"[0-9a-f]{64}", vector["validated_full_manifest_sha256"]):
            errors.append("VECTOR_VALIDATION_CERTIFICATE_FAILED")
        if vector["validation_errors"] != []:
            errors.append("VECTOR_EMITTED_VALIDATION_ERRORS")
        area = vector["vector_area_epsg3035_m2"]
        if not isinstance(area, (int, float)) or isinstance(area, bool) or area <= 0:
            errors.append("EMPTY_OR_NONPOSITIVE_CANDIDATE")
            continue
        if abs(vector["retained_area_fraction"] - area / source_area) > 1e-12:
            errors.append("RETAINED_FRACTION_FORMULA_FAILED")
        if abs(vector["removed_area_m2"] - (source_area - area)) > tolerance:
            errors.append("REMOVED_AREA_FORMULA_FAILED")
        if abs(vector["area_balance_residual_m2"] -
               (source_area - (area + vector["removed_area_m2"]))) > tolerance:
            errors.append("VECTOR_AREA_BALANCE_FAILED")
        if not 0 <= vector["outside_source_area_m2"] <= tolerance:
            errors.append("CANDIDATE_OUTSIDE_SOURCE")
        if not 0 <= vector["opening_loss_area_m2"] <= source_area:
            errors.append("OPENING_LOSS_BOUNDS_FAILED")
        if index > 0 and vector["weaker_candidate_containment_area_m2"] > tolerance:
            errors.append("WEAKER_CANDIDATE_CONTAINMENT_FAILED")
        if index > 0 and vectors[index - 1]["vector_area_epsg3035_m2"] < area:
            errors.append("VECTOR_AREAS_NOT_NONINCREASING")
    return sorted(set(errors))


def aggregate_acceptance_pass(failures: list[dict[str, Any]]) -> bool:
    """The controlling aggregate gate: any strict failure makes acceptance false."""
    return len(failures) == 0


FINAL_DIGEST_VECTOR_FIELDS = (
    "erosion_id", "erosion_distance_m", "vector_area_epsg3035_m2",
    "retained_area_fraction", "removed_area_m2", "area_balance_residual_m2",
    "outside_source_area_m2", "opening_loss_area_m2",
    "weaker_candidate_containment_area_m2", "validation_errors",
)
FINAL_DIGEST_SUMMARY_FIELDS = (
    "summary_id", "window_id", "season", "stream_id", "erosion_id",
    "erosion_distance_m", "expected_date_count", "source_image_count_sum",
    "source_present_row_count", "no_source_row_count",
    "duplicate_source_row_count", "state_accepted_count", "state_cloud_count",
    "state_rejected_count", "state_no_retrieval_count", "state_other_count",
    "eligible_roi_area_m2", "coverage_observation_count",
    "coverage_missing_count", "marker_ge_005_count", "marker_ge_025_count",
    "marker_ge_050_count", "validation_errors",
)
FINAL_DIGEST_DISTRIBUTION_FIELDS = (
    "coverage_min", "coverage_q05_type7", "coverage_q25_type7",
    "coverage_q50_type7", "coverage_mean", "coverage_population_sd",
    "coverage_max",
)


def expected_final_summary_ids() -> list[str]:
    """Return the exact deterministic 64 seasonal + 16 overall ID order."""
    seasonal = [
        f"{window['window_id']}__{stream['stream_id']}__{treatment['erosion_id']}"
        for window in WINDOWS for treatment in TREATMENTS for stream in STREAMS
    ]
    overall = [
        f"all_windows_2024__{stream['stream_id']}__{treatment['erosion_id']}"
        for treatment in TREATMENTS for stream in STREAMS
    ]
    return seasonal + overall


def build_final_evidence_digest(result: dict[str, Any]) -> dict[str, Any]:
    """Project already evaluated evidence into a strict coordinate-free digest."""
    failures = result.get("failures")
    vectors = result.get("vectors")
    summaries = result.get("coverage_summaries")
    if not isinstance(failures, list) or not isinstance(vectors, list) or \
       not isinstance(summaries, list):
        raise ValueError("FINAL_DIGEST_INPUT_SHAPE_FAILED")
    expected_ids = expected_final_summary_ids()
    observed_ids = [summary.get("summary_id") if isinstance(summary, dict) else None
                    for summary in summaries]
    if len(vectors) != 4 or len(summaries) != 80 or observed_ids != expected_ids:
        raise ValueError("FINAL_DIGEST_COUNT_OR_ORDER_FAILED")
    vector_digest: list[dict[str, Any]] = []
    for index, (vector, treatment) in enumerate(zip(vectors, TREATMENTS)):
        if not isinstance(vector, dict) or \
           vector.get("erosion_id") != treatment["erosion_id"]:
            raise ValueError("FINAL_DIGEST_VECTOR_IDENTITY_FAILED")
        required = set(FINAL_DIGEST_VECTOR_FIELDS)
        if index == 0:
            required.remove("weaker_candidate_containment_area_m2")
            if "weaker_candidate_containment_area_m2" in vector:
                raise ValueError("FINAL_DIGEST_VECTOR_OPTIONAL_FIELD_FAILED")
        if not required.issubset(vector):
            raise ValueError("FINAL_DIGEST_VECTOR_FIELD_MISSING")
        vector_digest.append({name: vector[name]
                              for name in FINAL_DIGEST_VECTOR_FIELDS
                              if name in vector})
    summary_digest: list[dict[str, Any]] = []
    for summary in summaries:
        if not isinstance(summary, dict) or \
           not set(FINAL_DIGEST_SUMMARY_FIELDS).issubset(summary):
            raise ValueError("FINAL_DIGEST_SUMMARY_FIELD_MISSING")
        expected_id = (f"{summary['window_id']}__{summary['stream_id']}__"
                       f"{summary['erosion_id']}")
        if summary["summary_id"] != expected_id:
            raise ValueError("FINAL_DIGEST_SUMMARY_IDENTITY_FAILED")
        treatment = next((item for item in TREATMENTS
                          if item["erosion_id"] == summary["erosion_id"]), None)
        stream = next((item for item in STREAMS
                       if item["stream_id"] == summary["stream_id"]), None)
        window = next((item for item in WINDOWS
                       if item["window_id"] == summary["window_id"]), None)
        expected_season = ("all_selected_seasons"
                           if summary["window_id"] == "all_windows_2024"
                           else window["season"] if window else None)
        if treatment is None or stream is None or expected_season is None or \
           summary["season"] != expected_season or \
           summary["erosion_distance_m"] != float(treatment["distance_m"]):
            raise ValueError("FINAL_DIGEST_TREATMENT_SEASON_STREAM_FAILED")
        observation_count = summary["coverage_observation_count"]
        if not isinstance(observation_count, int) or isinstance(
                observation_count, bool) or observation_count < 0:
            raise ValueError("FINAL_DIGEST_OBSERVATION_COUNT_FAILED")
        present_distribution = {
            name for name in FINAL_DIGEST_DISTRIBUTION_FIELDS if name in summary
        }
        if observation_count == 0:
            if present_distribution:
                raise ValueError("FINAL_DIGEST_SPARSE_DISTRIBUTION_FAILED")
        elif present_distribution != set(FINAL_DIGEST_DISTRIBUTION_FIELDS):
            raise ValueError("FINAL_DIGEST_POPULATED_DISTRIBUTION_FAILED")
        compact = {name: summary[name] for name in FINAL_DIGEST_SUMMARY_FIELDS}
        compact.update({name: summary[name]
                        for name in FINAL_DIGEST_DISTRIBUTION_FIELDS
                        if name in summary})
        if any(value is None for value in compact.values()):
            raise ValueError("FINAL_DIGEST_EXPLICIT_NULL_FAILED")
        summary_digest.append(compact)
    pass_value = aggregate_acceptance_pass(failures)
    if result.get("pass") is not pass_value:
        raise ValueError("FINAL_DIGEST_PASS_IDENTITY_FAILED")
    counts = {
        "row_count": result.get("row_count"),
        "unique_row_key_count": result.get("unique_row_key_count"),
        "seasonal_summary_count": result.get("seasonal_summary_count"),
        "overall_summary_count": result.get("overall_summary_count"),
        "summary_count": result.get("summary_count"),
        "unique_summary_id_count": result.get("unique_summary_id_count"),
        "vector_count": result.get("vector_count"),
    }
    gates = {
        "exactly_896_rows": counts["row_count"] == 896,
        "exactly_896_unique_row_keys": counts["unique_row_key_count"] == 896,
        "exactly_64_seasonal_summaries": counts["seasonal_summary_count"] == 64,
        "exactly_16_overall_summaries": counts["overall_summary_count"] == 16,
        "exactly_80_summaries": counts["summary_count"] == 80,
        "exactly_80_unique_summary_ids": counts["unique_summary_id_count"] == 80,
        "exactly_4_vectors": counts["vector_count"] == 4,
        "no_failures": not failures,
        "overall_pass": pass_value,
    }
    if pass_value and not all(value for name, value in gates.items()
                              if name not in {"no_failures", "overall_pass"}):
        raise ValueError("FINAL_DIGEST_GATE_FALSE_PASS")
    treatment_comparison_index = []
    for treatment, vector in zip(TREATMENTS, vector_digest):
        treatment_summary_ids = [
            summary["summary_id"] for summary in summary_digest
            if summary["erosion_id"] == treatment["erosion_id"]]
        if len(treatment_summary_ids) != 20:
            raise ValueError("FINAL_DIGEST_TREATMENT_GROUP_FAILED")
        treatment_comparison_index.append({
            "erosion_id": treatment["erosion_id"],
            "erosion_distance_m": float(treatment["distance_m"]),
            "vector_metrics": vector,
            "seasonal_summary_ids": [identifier for identifier in treatment_summary_ids
                                     if not identifier.startswith("all_windows_2024__")],
            "overall_summary_ids": [identifier for identifier in treatment_summary_ids
                                    if identifier.startswith("all_windows_2024__")],
        })
    return {
        "AUDIT_FINAL_EVIDENCE_DIGEST": True,
        "counts": counts,
        "gates": gates,
        "failure_count": len(failures),
        "failures": failures,
        "nullable_distribution_semantics": (
            "Omitted coverage distribution properties mean unavailable/null; "
            "present values are observations; no sentinel values are used."),
        "vectors": vector_digest,
        "treatment_comparison_index": treatment_comparison_index,
        "coverage_summaries": summary_digest,
    }


def single_source_formula_presence_errors(
        property_names: Iterable[str], source_image_count: int,
        validation_errors: Iterable[str] = (),
        eligible_roi_area_m2: float = 1.0) -> list[str]:
    """Pure mirror of the server gate, used by fail-closed offline fixtures."""
    if source_image_count != 1 or list(validation_errors) or eligible_roi_area_m2 <= 0:
        return []
    present = set(property_names)
    return [
        "ROW_SINGLE_SOURCE_FORMULA_FIELD_MISSING:" + name
        for name in SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS if name not in present
    ]


def sparse_single_source_error_identity_errors(properties: dict[str, Any]) -> list[str]:
    """Pure fail-closed mirror of the two intentional sparse processing branches."""
    if properties.get("source_image_count") != 1:
        return []
    emitted = properties.get("validation_errors")
    if not isinstance(emitted, list):
        return ["ROW_SINGLE_SOURCE_PROCESSING_ERROR_IDENTITY_FAILED"]
    if not emitted:
        return [] if properties.get("eligible_roi_area_m2", 0) > 0 else [
            "ROW_SINGLE_SOURCE_PROCESSING_ERROR_IDENTITY_FAILED"]
    for null_reason, expected in SINGLE_SOURCE_SPARSE_ERROR_BRANCHES.items():
        if properties.get("null_reason") == null_reason and \
           emitted == [expected["validation_error"]] and \
           properties.get("row_state") == expected["row_state"] and \
           properties.get("state_reason") == expected["state_reason"]:
            if null_reason != "nonpositive_eligible_roi_area" or \
               properties.get("eligible_roi_area_m2", 0) <= 0:
                return []
    return ["ROW_SINGLE_SOURCE_PROCESSING_ERROR_IDENTITY_FAILED"]


def validate_validation_error_row_details(evidence: dict[str, Any]) -> list[str]:
    """Validate exact coordinate-free row-error evidence shape and identities."""
    errors: list[str] = []
    count = evidence.get("validation_error_row_count")
    details = evidence.get("validation_error_row_details")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return ["VALIDATION_ERROR_DETAIL_COUNT_INVALID"]
    if not isinstance(details, list) or len(details) != count:
        return ["VALIDATION_ERROR_DETAIL_COUNT_MISMATCH"]
    expected_fields = set(VALIDATION_ERROR_DETAIL_FIELDS)
    observed_keys: list[str] = []
    valid_streams = {stream["stream_id"] for stream in STREAMS}
    valid_treatments = {treatment["erosion_id"] for treatment in TREATMENTS}
    for index, detail in enumerate(details):
        prefix = f"VALIDATION_ERROR_DETAIL_{index}:"
        if not isinstance(detail, dict) or set(detail) != expected_fields:
            errors.append(prefix + "SHAPE_INVALID")
            continue
        if not all(isinstance(detail[name], str) and detail[name] for name in (
                "date_utc", "stream_id", "_audit_key", "row_state", "null_reason",
                "state_reason", "projection_reference_image_id", "source_crs")):
            errors.append(prefix + "IDENTITY_TYPE_INVALID")
        if not isinstance(detail["validation_errors"], list) or \
           not detail["validation_errors"] or \
           not all(isinstance(value, str) and value for value in detail["validation_errors"]):
            errors.append(prefix + "PROCESSING_ERRORS_INVALID")
        if not isinstance(detail["_strict_row_errors"], list) or \
           not all(isinstance(value, str) and value for value in detail["_strict_row_errors"]):
            errors.append(prefix + "STRICT_ERRORS_INVALID")
        key = detail.get("_audit_key", "")
        key_parts = key.split("|")
        if key_parts[:2] != [detail.get("date_utc"), detail.get("stream_id")] or \
           len(key_parts) != 3 or key_parts[2] not in valid_treatments:
            errors.append(prefix + "ROW_KEY_IDENTITY_INVALID")
        observed_keys.append(key)
        try:
            dt.date.fromisoformat(detail.get("date_utc", ""))
        except (TypeError, ValueError):
            errors.append(prefix + "DATE_INVALID")
        if detail.get("stream_id") not in valid_streams:
            errors.append(prefix + "STREAM_INVALID")
        null_reason = detail.get("null_reason")
        if null_reason in SINGLE_SOURCE_SPARSE_ERROR_BRANCHES:
            expected = SINGLE_SOURCE_SPARSE_ERROR_BRANCHES[null_reason]
            if detail.get("validation_errors") != [expected["validation_error"]] or \
               detail.get("row_state") != expected["row_state"] or \
               detail.get("state_reason") != expected["state_reason"]:
                errors.append(prefix + "SPARSE_BRANCH_IDENTITY_INVALID")
        elif null_reason == "duplicate_source_images":
            if detail.get("validation_errors") != ["DUPLICATE_SOURCE_IMAGES"] or \
               detail.get("row_state") != "DUPLICATE_SOURCE_IMAGES" or \
               detail.get("state_reason") != (
                   "More than one source image exists for the date-stream key; "
                   "no mosaic or scientific result was produced."):
                errors.append(prefix + "DUPLICATE_BRANCH_IDENTITY_INVALID")
        else:
            errors.append(prefix + "UNKNOWN_ERROR_BRANCH")
        forbidden = {"geometry", "coordinates", "geometry_json", "source_geometry"}
        if forbidden.intersection(detail):
            errors.append(prefix + "FORBIDDEN_COORDINATE_FIELD")
    if len(observed_keys) != len(set(observed_keys)):
        errors.append("VALIDATION_ERROR_DETAIL_DUPLICATE_KEYS")
    return errors


def validate_sparse_branch_physical_contract(
        properties: dict[str, Any], manifest: list[dict[str, Any]]) -> list[str]:
    """Offline mirror of exact sparse physical omission and provenance gates."""
    errors: list[str] = []
    manifest_names = {field["name"] for field in manifest}
    allowed = {field["name"] for field in manifest if not field["nullable"]}.union(
        SPARSE_BRANCH_ALLOWED_NULLABLE_FIELDS)
    actual = set(properties).intersection(manifest_names)
    if actual != allowed:
        errors.append("ROW_SPARSE_BRANCH_PHYSICAL_PROPERTIES_FAILED")
    expected_pairs = (
        ("notes", "_sparse_expected_notes"),
        ("projection_reference_image_id", "_sparse_expected_projection_reference_image_id"),
        ("source_crs", "_sparse_expected_source_crs"),
        ("source_crs_transform", "_sparse_expected_source_crs_transform"),
        ("reducer_scale_or_transform", "_sparse_expected_reducer_scale_or_transform"),
    )
    if any(properties.get(actual_name) != properties.get(expected_name)
           for actual_name, expected_name in expected_pairs):
        errors.append("ROW_SPARSE_BRANCH_PROVENANCE_FAILED")
    return errors


def validate_projection_diagnostic_request(date_utc: str,
                                           stream_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Validate and resolve a deterministic diagnostic request without EE."""
    try:
        parsed = dt.date.fromisoformat(date_utc)
    except ValueError as exc:
        raise ValueError("projection diagnostic date must be ISO YYYY-MM-DD") from exc
    if parsed.isoformat() != date_utc:
        raise ValueError("projection diagnostic date must be canonical ISO YYYY-MM-DD")
    requested = list(stream_ids)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("projection diagnostic streams must be nonempty and unique")
    lookup = {stream["stream_id"]: stream for stream in STREAMS}
    if any(stream_id not in lookup for stream_id in requested):
        raise ValueError("unknown projection diagnostic stream")
    return [lookup[stream_id] for stream_id in requested]


def certified_source_system_index(record: dict[str, Any]) -> str:
    """Return the exact certified collection identity or fail closed."""
    value = record.get("source_system_index")
    if not isinstance(value, str) or not value:
        raise ValueError("PROJECTION_CERTIFICATION_SOURCE_SYSTEM_INDEX_MISSING")
    return value


def validate_projection_diagnostic_evidence(
        evidence: dict[str, Any], date_utc: str, stream: dict[str, Any]) -> list[str]:
    """Fail-closed client validation for one coordinate-free projection record."""
    errors: list[str] = []
    required = {
        "date_utc", "stream_id", "collection_id", "lst_band", "source_image_count",
        "source_image_ids", "source_image_id", "source_system_time_start",
        "canonical_projection_reference_image_id", "canonical_crs", "canonical_affine",
        "source_crs", "source_affine", "affine_elementwise_difference",
        "crs_equal", "affine_equal", "projection_equal", "grid_width_columns",
        "grid_height_rows", "grid_corner_convention", "corner_displacements",
        "maximum_induced_displacement_m", "maximum_allowed_displacement_m",
        "affine_numerically_equivalent", "intra_image_bands_exact",
        "projection_acceptance_pass", "band_projections",
    }
    if not isinstance(evidence, dict) or set(evidence) != required:
        return ["PROJECTION_DIAGNOSTIC_SHAPE_INVALID"]
    if evidence["date_utc"] != date_utc or evidence["stream_id"] != stream["stream_id"] or \
       evidence["collection_id"] != stream["collection_id"] or \
       evidence["lst_band"] != stream["lst"]:
        errors.append("PROJECTION_DIAGNOSTIC_CONFIG_IDENTITY_FAILED")
    count = evidence["source_image_count"]
    ids = evidence["source_image_ids"]
    if not isinstance(count, int) or isinstance(count, bool) or count != 1:
        errors.append("PROJECTION_DIAGNOSTIC_SOURCE_COUNT_FAILED")
    if not isinstance(ids, list) or len(ids) != 1 or \
       not all(isinstance(value, str) and value for value in ids) or \
       evidence["source_image_id"] != (ids[0] if len(ids) == 1 else None):
        errors.append("PROJECTION_DIAGNOSTIC_SOURCE_IDENTITY_FAILED")
    if not isinstance(evidence["source_system_time_start"], int) or \
       isinstance(evidence["source_system_time_start"], bool):
        errors.append("PROJECTION_DIAGNOSTIC_SOURCE_TIME_TYPE_FAILED")
    else:
        day_start = dt.datetime.combine(
            dt.date.fromisoformat(date_utc), dt.time.min,
            tzinfo=dt.timezone.utc)
        start_ms = int(day_start.timestamp() * 1000)
        end_ms = int((day_start + dt.timedelta(days=1)).timestamp() * 1000)
        if not start_ms <= evidence["source_system_time_start"] < end_ms:
            errors.append("PROJECTION_DIAGNOSTIC_SOURCE_TIME_WINDOW_FAILED")
    for name in ("source_image_id", "canonical_projection_reference_image_id",
                 "canonical_crs", "source_crs"):
        if not isinstance(evidence[name], str) or not evidence[name]:
            errors.append("PROJECTION_DIAGNOSTIC_STRING_TYPE_FAILED:" + name)
    normalized_affines: dict[str, list[float]] = {}
    for name in ("canonical_affine", "source_affine", "affine_elementwise_difference"):
        value = evidence[name]
        if not isinstance(value, list) or len(value) != 6 or \
           not all(isinstance(item, (int, float)) and not isinstance(item, bool) and
                   math.isfinite(item) for item in value):
            errors.append("PROJECTION_DIAGNOSTIC_AFFINE_TYPE_FAILED:" + name)
        else:
            normalized_affines[name] = [float(item) for item in value]
    if len(normalized_affines) == 3:
        expected_difference = [
            source - canonical for source, canonical in zip(
                normalized_affines["source_affine"],
                normalized_affines["canonical_affine"])
        ]
        if any(abs(actual - expected) > 1e-12 for actual, expected in zip(
                normalized_affines["affine_elementwise_difference"],
                expected_difference)):
            errors.append("PROJECTION_DIAGNOSTIC_DIFFERENCE_FORMULA_FAILED")
    for name in ("crs_equal", "affine_equal", "projection_equal",
                 "affine_numerically_equivalent", "intra_image_bands_exact",
                 "projection_acceptance_pass"):
        if not isinstance(evidence[name], bool):
            errors.append("PROJECTION_DIAGNOSTIC_BOOLEAN_TYPE_FAILED:" + name)
    if all(isinstance(evidence[name], bool) for name in (
            "crs_equal", "affine_equal", "projection_equal")) and \
       evidence["projection_equal"] != (
           evidence["crs_equal"] and evidence["affine_equal"]):
        errors.append("PROJECTION_DIAGNOSTIC_EQUALITY_IDENTITY_FAILED")
    if isinstance(evidence["crs_equal"], bool) and \
       evidence["crs_equal"] != (
           evidence["source_crs"] == evidence["canonical_crs"]):
        errors.append("PROJECTION_DIAGNOSTIC_CRS_EQUALITY_IDENTITY_FAILED")
    if len(normalized_affines) == 3 and isinstance(evidence["affine_equal"], bool):
        exact_affine_equality = (
            normalized_affines["source_affine"] ==
            normalized_affines["canonical_affine"])
        zero_difference = all(
            value == 0.0 for value in
            normalized_affines["affine_elementwise_difference"])
        if evidence["affine_equal"] != exact_affine_equality or \
           evidence["affine_equal"] != zero_difference:
            errors.append("PROJECTION_DIAGNOSTIC_AFFINE_EQUALITY_IDENTITY_FAILED")
    if len(normalized_affines) == 3:
        expected_displacement = affine_displacement_evidence(
            normalized_affines["canonical_affine"],
            normalized_affines["source_affine"])
        for name, expected_value in (
                ("grid_width_columns", MODIS_GRID_WIDTH_COLUMNS),
                ("grid_height_rows", MODIS_GRID_HEIGHT_ROWS),
                ("grid_corner_convention", MODIS_GRID_CORNER_CONVENTION),
                ("maximum_allowed_displacement_m", AUDIT_AFFINE_MAX_DISPLACEMENT_M),
                ("affine_numerically_equivalent",
                 expected_displacement["affine_numerically_equivalent"])):
            if evidence[name] != expected_value:
                errors.append("PROJECTION_DIAGNOSTIC_DISPLACEMENT_IDENTITY_FAILED:" + name)
        actual_maximum = evidence["maximum_induced_displacement_m"]
        if not isinstance(actual_maximum, (int, float)) or isinstance(actual_maximum, bool) or \
           not math.isfinite(actual_maximum) or \
           abs(float(actual_maximum) - expected_displacement[
               "maximum_induced_displacement_m"]) > 1e-15:
            errors.append("PROJECTION_DIAGNOSTIC_MAX_DISPLACEMENT_FAILED")
        actual_corners = evidence["corner_displacements"]
        if actual_corners != expected_displacement["corner_displacements"]:
            errors.append("PROJECTION_DIAGNOSTIC_CORNER_DISPLACEMENTS_FAILED")
    expected_bands = {stream[key] for key in ("lst", "qc", "time", "angle", "clear")}
    bands = evidence["band_projections"]
    if not isinstance(bands, dict) or set(bands) != expected_bands:
        errors.append("PROJECTION_DIAGNOSTIC_BAND_SET_FAILED")
    else:
        for band_name, projection in bands.items():
            if not isinstance(projection, dict) or set(projection) != {"crs", "affine"} or \
               not isinstance(projection.get("crs"), str) or not projection["crs"] or \
               not isinstance(projection.get("affine"), list) or len(projection["affine"]) != 6 or \
               not all(isinstance(item, (int, float)) and not isinstance(item, bool) and
                       math.isfinite(item) for item in projection["affine"]):
                errors.append("PROJECTION_DIAGNOSTIC_BAND_PROJECTION_FAILED:" + band_name)
        lst_projection = bands.get(stream["lst"])
        if isinstance(lst_projection, dict) and \
           lst_projection.get("crs") != evidence["source_crs"]:
            errors.append("PROJECTION_DIAGNOSTIC_LST_CRS_IDENTITY_FAILED")
        if isinstance(lst_projection, dict) and \
           isinstance(lst_projection.get("affine"), list) and \
           len(lst_projection["affine"]) == 6 and \
           all(isinstance(item, (int, float)) and not isinstance(item, bool)
               for item in lst_projection["affine"]) and \
           "source_affine" in normalized_affines and \
           [float(item) for item in lst_projection["affine"]] != \
                normalized_affines["source_affine"]:
            errors.append("PROJECTION_DIAGNOSTIC_LST_AFFINE_IDENTITY_FAILED")
        expected_intra_image = all(
            isinstance(projection, dict) and
            projection.get("crs") == evidence["source_crs"] and
            isinstance(projection.get("affine"), list) and
            len(projection["affine"]) == 6 and
            all(isinstance(item, (int, float)) and not isinstance(item, bool) and
                math.isfinite(item) for item in projection["affine"]) and
            [float(item) for item in projection["affine"]] ==
                normalized_affines.get("source_affine")
            for projection in bands.values())
        if isinstance(evidence["intra_image_bands_exact"], bool) and \
           evidence["intra_image_bands_exact"] != expected_intra_image:
            errors.append("PROJECTION_DIAGNOSTIC_INTRA_BAND_IDENTITY_FAILED")
    expected_acceptance = (
        evidence.get("crs_equal") is True and
        evidence.get("intra_image_bands_exact") is True and
        evidence.get("affine_numerically_equivalent") is True)
    if isinstance(evidence["projection_acceptance_pass"], bool) and \
       evidence["projection_acceptance_pass"] != expected_acceptance:
        errors.append("PROJECTION_DIAGNOSTIC_ACCEPTANCE_IDENTITY_FAILED")
    if evidence.get("projection_acceptance_pass") is not True:
        errors.append("PROJECTION_DIAGNOSTIC_HARD_PROJECTION_FAILURE")
    return sorted(set(errors))


def extract_four_summary_evidence(evidence: dict[str, Any],
                                  expected_ids: list[str]) -> tuple[list[dict[str, Any]],
                                                                   dict[str, list[str]]]:
    """Fail-closed extraction for deterministic EE List<Dictionary> evidence."""
    summaries = evidence.get("seasonal_summary_dictionaries")
    runtime = evidence.get("summary_runtime_type_dictionaries")
    if not isinstance(summaries, list) or not isinstance(runtime, list):
        raise ValueError("SUMMARY_EVIDENCE_SHAPE_MISSING_LISTS")
    if len(summaries) != 4 or len(runtime) != 4:
        raise ValueError("SUMMARY_EVIDENCE_COUNT_MISMATCH")
    if not all(isinstance(item, dict) for item in summaries + runtime):
        raise ValueError("SUMMARY_EVIDENCE_ITEM_NOT_DICTIONARY")
    summary_ids = [item.get("summary_id") for item in summaries]
    runtime_ids = [item.get("summary_id") for item in runtime]
    if summary_ids != expected_ids or runtime_ids != expected_ids or len(set(summary_ids)) != 4:
        raise ValueError("SUMMARY_EVIDENCE_ID_MISMATCH")
    if not all(isinstance(item.get("errors"), list) for item in runtime):
        raise ValueError("SUMMARY_RUNTIME_ERRORS_NOT_LIST")
    return summaries, {item["summary_id"]: item["errors"] for item in runtime}


def validate_server_runtime_fixture(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if evidence.get("boolean_type") != "Boolean":
        errors.append("BOOLEAN_NORMALIZATION_RUNTIME_FAILED")
    transform_types = evidence.get("transform_element_types")
    if not isinstance(transform_types, list) or len(transform_types) != 6 or \
       any(value != "Float" for value in transform_types):
        errors.append("AFFINE_FLOAT_RUNTIME_FAILED")
    if evidence.get("unconverted_numeric_predicate_type") == "Boolean":
        errors.append("NEGATIVE_NUMERIC_PREDICATE_FIXTURE_FAILED")
    return errors


class TransientNetworkRetriesExhausted(RuntimeError):
    """Safe fail-closed signal with no transport message or sensitive payload."""


def safe_phase_category(phase: str) -> str:
    """Map internal phase labels to a strict coordinate-free allowlist."""
    if phase == "top_level":
        return "top_level"
    if phase == "runtime_fixture":
        return "runtime_fixture"
    if phase in {"earth_engine_import", "earth_engine_initialize",
                 "request_policy", "source_verification",
                 "checkpoint_compatibility", "checkpoint_load",
                 "checkpoint_save", "runner_initialization",
                 "checkpoint_revalidation", "final_aggregation"}:
        return phase
    for prefix, category in (
            ("canonical_projection_", "canonical_projection"),
            ("canonical_reference_id_", "canonical_reference_id"),
            ("projection_diagnostic_", "projection_diagnostic"),
            ("projection_inventory_", "projection_inventory"),
            ("vector_", "vector"),
            ("chunk_", "chunk")):
        if phase.startswith(prefix):
            return category
    return "unclassified_phase"


def redacted_exception_evidence(error: BaseException,
                                phase: str) -> dict[str, str]:
    """Return only strict allowlisted exception evidence; never its message."""
    classes = list(type(error).__mro__)
    identities = {(cls.__module__, cls.__name__) for cls in classes}
    names = {name for _, name in identities}
    modules = {module for module, _ in identities}
    if "TransientNetworkRetriesExhausted" in names:
        category, safe_class = "client_transport_exhausted", "TransportRetriesExhausted"
    elif any(module.startswith("ee.ee_exception") for module in modules) or \
         "EEException" in names:
        category, safe_class = "earth_engine_error", "EarthEngineException"
    elif any(module.startswith("google.auth") for module in modules) or \
         names.intersection({"GoogleAuthError", "RefreshError",
                             "DefaultCredentialsError", "OAuthError"}):
        category, safe_class = "authentication_error", "AuthenticationException"
    elif any(module.startswith("googleapiclient.errors") for module in modules) or \
         names.intersection({"HttpError", "HTTPError"}):
        category, safe_class = "api_http_error", "ApiHttpException"
    elif any(module.startswith("google.api_core.exceptions") for module in modules):
        category, safe_class = "cloud_api_error", "CloudApiException"
    elif is_recognized_transient_transport_error(error):
        kind = recognized_transient_transport_kind(error)
        category = kind or "client_transport_error"
        safe_class = ("ClientTransportTimeout" if kind == "client_transport_timeout"
                      else "ClientTransportConnectionError")
    elif isinstance(error, KeyError):
        category, safe_class = "response_shape_error", "ResponseShapeException"
    elif isinstance(error, ValueError):
        category, safe_class = "local_validation_error", "LocalValidationException"
    elif isinstance(error, RecursionError):
        category, safe_class = "local_runtime_error", "RecursionException"
    elif isinstance(error, RuntimeError):
        category, safe_class = "local_runtime_error", "LocalRuntimeException"
    else:
        category, safe_class = "unexpected_error", "RedactedException"
    return {"phase": safe_phase_category(phase),
            "exception_category": category,
            "exception_class": safe_class}


def validate_request_policy(deadline_seconds: int,
                            max_attempts: int) -> dict[str, int]:
    """Validate bounded execution-only HTTP policy without importing EE."""
    if isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int) or \
       deadline_seconds != DEFAULT_EE_REQUEST_DEADLINE_SECONDS:
        raise ValueError(
            f"request deadline must be exactly "
            f"{DEFAULT_EE_REQUEST_DEADLINE_SECONDS} seconds")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or \
       max_attempts != DEFAULT_EE_TRANSPORT_MAX_ATTEMPTS:
        raise ValueError(
            "transport max attempts must be exactly 1")
    return {"deadline_seconds": deadline_seconds,
            "deadline_milliseconds": deadline_seconds * 1_000,
            "max_attempts": max_attempts,
            "max_outer_retries": max_attempts - 1,
            "earth_engine_internal_retries": 0}


def configure_ee_request_policy(ee: Any, deadline_seconds: int,
                                max_attempts: int) -> dict[str, Any]:
    """Apply the official EE HTTP deadline and disable opaque internal retries."""
    policy: dict[str, Any] = validate_request_policy(
        deadline_seconds, max_attempts)
    if not callable(getattr(getattr(ee, "data", None), "setDeadline", None)) or \
       not callable(getattr(ee.data, "setMaxRetries", None)):
        raise RuntimeError("EARTH_ENGINE_REQUEST_POLICY_API_UNAVAILABLE")
    ee.data.setMaxRetries(0)
    # setDeadline rebuilds the Cloud API resource, so set the retry state first
    # and ensure the rebuilt transport also receives zero internal retries.
    ee.data.setDeadline(policy["deadline_milliseconds"])
    policy.update({
        "http_path": (
            "ComputedObject.getInfo -> ee.data.computeValue -> Cloud API "
            "projects/value:compute -> googleapiclient HttpRequest.execute"),
        "deadline_scope": "per official Earth Engine HTTP request",
        "retry_scope": (
            "outer runner only; recognized transient client transport failures; "
            "fresh identical graph per attempt"),
        "server_deadline_or_ee_exception_retry": False,
    })
    return policy


def is_recognized_transient_transport_error(error: BaseException) -> bool:
    """Recognize only client transport/DNS/timeout failures, including wrappers."""
    allowed = {
        ("requests.exceptions", "ConnectionError"),
        ("requests.exceptions", "Timeout"),
        ("requests.exceptions", "ConnectTimeout"),
        ("requests.exceptions", "ReadTimeout"),
        ("urllib3.exceptions", "NameResolutionError"),
        ("urllib3.exceptions", "NewConnectionError"),
        ("urllib3.exceptions", "ConnectTimeoutError"),
        ("urllib3.exceptions", "ReadTimeoutError"),
        ("urllib3.exceptions", "ProtocolError"),
        ("socket", "gaierror"),
        ("builtins", "ConnectionError"),
        ("builtins", "TimeoutError"),
    }
    denied_modules = (
        "ee.ee_exception",
        "google.api_core.exceptions",
        "googleapiclient.errors",
    )
    denied_names = {
        "EEException", "HTTPError", "HttpError", "GoogleAuthError", "RefreshError",
        "DefaultCredentialsError", "OAuthError", "AuthenticationError",
        "AuthorizationError", "PermissionDenied", "Forbidden", "Unauthorized",
        "TooManyRequests", "ResourceExhausted", "QuotaFailure",
    }

    def denied(exc: BaseException) -> bool:
        return any(
            cls.__module__.startswith(denied_modules) or cls.__name__ in denied_names
            for cls in type(exc).__mro__
        )

    seen: set[int] = set()
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    # Denial anywhere in the complete chain takes precedence over a transient
    # outer wrapper. This prevents EE/auth/quota/API errors from being retried.
    if any(denied(item) for item in chain):
        return False
    for current in chain:
        cls = type(current)
        if (cls.__module__, cls.__name__) in allowed:
            return True
    return False


def recognized_transient_transport_kind(error: BaseException) -> str | None:
    """Classify only an already allowlisted transport chain without messages."""
    if not is_recognized_transient_transport_error(error):
        return None
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if "timeout" in type(current).__name__.lower():
            return "client_transport_timeout"
        current = current.__cause__ or current.__context__
    return "client_transport_connection"


def bounded_transient_getinfo(call: Any, phase: str, *, max_attempts: int = 3,
                              deadline_seconds: int | None = None,
                              session_deadline_monotonic: float | None = None,
                              clock: Any = time.monotonic,
                              sleeper: Any = time.sleep, emit: Any = print) -> Any:
    """Retry one unchanged read-only getInfo call only for recognized transport faults."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(1, max_attempts + 1):
        required = (deadline_seconds or 0) + SESSION_COMPLETION_RESERVE_SECONDS
        enforce_session_budget(
            session_deadline_monotonic, phase,
            required_remaining_seconds=required, clock=clock)
        started = clock()
        safe_phase = safe_phase_category(phase)
        if deadline_seconds is not None:
            emit(json.dumps({"PHASE_REQUEST_START": {
                "phase": safe_phase, "attempt": attempt,
                "max_attempts": max_attempts,
                "request_deadline_seconds": deadline_seconds}},
                sort_keys=True), flush=True)
        try:
            result = call()
            enforce_session_budget(
                session_deadline_monotonic, phase, clock=clock)
            if deadline_seconds is not None:
                emit(json.dumps({"PHASE_REQUEST_COMPLETE": {
                    "phase": safe_phase, "attempt": attempt,
                    "elapsed_seconds": round(clock() - started, 3)}},
                    sort_keys=True), flush=True)
            return result
        except SessionCeilingReached:
            raise
        except Exception as exc:
            transport_kind = recognized_transient_transport_kind(exc)
            if transport_kind is None:
                failure = redacted_exception_evidence(exc, phase)
                failure["elapsed_seconds"] = round(
                    clock() - started, 3)  # type: ignore[assignment]
                emit(json.dumps({"PHASE_REQUEST_FAILURE": failure},
                                sort_keys=True), flush=True)
                raise
            safe_transport = redacted_exception_evidence(exc, phase)
            if deadline_seconds is not None:
                emit(json.dumps({"PHASE_REQUEST_TRANSPORT_FAILURE": {
                    "phase": safe_phase, "attempt": attempt,
                    "elapsed_seconds": round(clock() - started, 3),
                    "exception_class": safe_transport["exception_class"],
                    "failure_class": transport_kind,
                    "will_retry": attempt < max_attempts}},
                    sort_keys=True), flush=True)
            if attempt == max_attempts:
                raise TransientNetworkRetriesExhausted(
                    "TRANSIENT_NETWORK_RETRIES_EXHAUSTED"
                ) from exc
            emit(json.dumps({"RETRY": {"phase": safe_phase, "failed_attempt": attempt,
                                       "next_attempt": attempt + 1,
                                       "max_attempts": max_attempts,
                                       "failure_class": transport_kind,
                                       "exception_class": safe_transport[
                                           "exception_class"]}},
                                sort_keys=True), flush=True)
            sleeper(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def evaluate_authenticated_phase(build_graph: Any, phase: str, **retry_options: Any) -> Any:
    """Build a fresh, identical read-only EE graph for every bounded attempt."""
    return bounded_transient_getinfo(
        lambda: build_graph().getInfo(), phase, **retry_options)


def dates(start: str, end: str) -> Iterable[str]:
    cursor = dt.date.fromisoformat(start)
    stop = dt.date.fromisoformat(end)
    while cursor < stop:
        yield cursor.isoformat()
        cursor += dt.timedelta(days=1)


def load_authoritative_manifests() -> dict[str, list[dict[str, Any]]]:
    """Read the already-approved JS manifests without executing JavaScript."""
    prototype_text = (ROOT / "src/prototype/modis_preprocessing_prototype.js").read_text(encoding="utf-8")
    audit_text = (ROOT / "src/audit/whole_lake_boundary_shoreline_audit.js").read_text(encoding="utf-8")
    row_block = prototype_text.split("var SCHEMA_MANIFEST = [", 1)[1].split("];", 1)[0]
    row = [{"name": n, "type": t, "nullable": nullable == "true"}
           for n, t, nullable in re.findall(
               r"schemaField\('([^']+)',\s*'([^']+)',\s*(true|false)\)", row_block)]
    def audit_manifest(marker: str) -> list[dict[str, Any]]:
        block = audit_text.split(f"var {marker} = [", 1)[1].split("];", 1)[0]
        result = []
        for name, logical_type, nullable in re.findall(
                r"field\('([^']+)',\s*'([^']+)'(?:,\s*(true))?\)", block):
            result.append({"name": name, "type": logical_type, "nullable": nullable == "true"})
        return result
    manifests = {"row": row, "vector": audit_manifest("VECTOR_MANIFEST"),
                 "coverage": audit_manifest("COVERAGE_MANIFEST")}
    if [len(manifests[k]) for k in ("row", "vector", "coverage")] != [100, 34, 45]:
        raise RuntimeError("Authoritative manifest parse failed")
    formula_fields = SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS
    row_names = {field["name"] for field in row}
    if len(formula_fields) != len(set(formula_fields)):
        raise RuntimeError("Single-source formula field list contains duplicates")
    if not set(formula_fields).issubset(row_names):
        raise RuntimeError("Single-source formula field is absent from row manifest")
    nullable_names = {field["name"] for field in row if field["nullable"]}
    if not SPARSE_BRANCH_ALLOWED_NULLABLE_FIELDS.issubset(nullable_names):
        raise RuntimeError("Sparse-branch allowed field is not nullable in row manifest")
    return manifests


FORBIDDEN_SENTINELS = {-9999, -999, "NA", "N/A", "NULL", "null"}


def normalize_evaluated_float64(properties: dict[str, Any],
                                manifest: list[dict[str, Any]]) -> dict[str, Any]:
    """Restore EE Float representation lost when JSON decodes integral values as int.

    Server-side runtime evidence independently establishes that these logical
    fields were Earth Engine Float values. Non-numeric values are deliberately
    left unchanged so strict validation still rejects real type defects.
    """
    normalized = dict(properties)
    for field in manifest:
        name, logical = field["name"], field["type"]
        if name not in normalized:
            continue
        value = normalized[name]
        if logical == "float64" and isinstance(value, (int, float)) and not isinstance(value, bool):
            normalized[name] = float(value)
        elif logical.startswith("list<float64>") and isinstance(value, list):
            normalized[name] = [float(item) if isinstance(item, (int, float)) and not isinstance(item, bool)
                                else item for item in value]
    return normalized


def validate_evaluated_properties(properties: dict[str, Any], manifest: list[dict[str, Any]],
                                  *, allowed_extra: set[str] | None = None) -> list[str]:
    """Validate evaluated sparse-omission shape and JSON runtime types."""
    allowed_extra = allowed_extra or set()
    declared = {f["name"]: f for f in manifest}
    errors: list[str] = []
    undeclared = sorted(set(properties) - set(declared) - allowed_extra)
    if undeclared:
        errors.append("UNDECLARED_FIELDS:" + ",".join(undeclared))
    missing = sorted(f["name"] for f in manifest if not f["nullable"] and f["name"] not in properties)
    if missing:
        errors.append("MISSING_REQUIRED_FIELDS:" + ",".join(missing))
    for name, value in properties.items():
        if name not in declared:
            continue
        if value is None:
            errors.append("PRESENT_NULL_INSTEAD_OF_OMISSION:" + name)
            continue
        logical = declared[name]["type"]
        ok = True
        if logical == "string": ok = isinstance(value, str)
        elif logical == "boolean": ok = isinstance(value, bool)
        elif logical == "int64": ok = isinstance(value, int) and not isinstance(value, bool)
        elif logical == "float64": ok = isinstance(value, float) and math.isfinite(value)
        elif logical.startswith("list<"): ok = isinstance(value, list)
        if not ok:
            errors.append("TYPE_MISMATCH:" + name)
        if value in FORBIDDEN_SENTINELS if not isinstance(value, list) else False:
            errors.append("FORBIDDEN_SENTINEL:" + name)
        length = re.search(r"\[(\d+)\]$", logical)
        if length and isinstance(value, list) and len(value) != int(length.group(1)):
            errors.append("LIST_LENGTH_MISMATCH:" + name)
        if isinstance(value, list):
            element_type = logical.split("<", 1)[1].split(">", 1)[0] if "<" in logical else ""
            for item in value:
                if element_type == "string" and not isinstance(item, str): ok = False
                elif element_type == "int64" and not (isinstance(item, int) and not isinstance(item, bool)): ok = False
                elif element_type == "float64" and not (isinstance(item, float) and math.isfinite(item)): ok = False
            if not ok:
                errors.append("LIST_ELEMENT_TYPE_MISMATCH:" + name)
            if any(item in FORBIDDEN_SENTINELS for item in value if isinstance(item, (str, int, float))):
                errors.append("FORBIDDEN_SENTINEL:" + name)
    return sorted(set(errors))


def validate_summary_formula(p: dict[str, Any], values: list[float] | None = None) -> list[str]:
    errors = validate_evaluated_properties(p, load_authoritative_manifests()["coverage"])
    row_count = p.get("row_count", 0)
    state_sum = sum(p.get(name, 0) for name in ("state_accepted_count", "state_cloud_count",
                                                "state_rejected_count", "state_no_retrieval_count",
                                                "state_other_count"))
    if row_count != p.get("expected_date_count"): errors.append("SUMMARY_ROW_COUNT_MISMATCH")
    if p.get("coverage_observation_count", 0) + p.get("coverage_missing_count", 0) != row_count:
        errors.append("COVERAGE_COUNT_IDENTITY_FAILED")
    if state_sum != row_count: errors.append("STATE_COUNT_IDENTITY_FAILED")
    if p.get("state_other_count", 0) != p.get("no_source_row_count", 0) + p.get("duplicate_source_row_count", 0):
        errors.append("STATE_OTHER_SOURCE_IDENTITY_FAILED")
    if p.get("source_present_row_count", 0) + p.get("no_source_row_count", 0) + p.get("duplicate_source_row_count", 0) != row_count:
        errors.append("SOURCE_COUNT_IDENTITY_FAILED")
    n = p.get("coverage_observation_count", 0)
    if n > p.get("source_present_row_count", 0): errors.append("COVERAGE_EXCEEDS_SOURCE_PRESENT")
    if p.get("source_image_count_sum", 0) < p.get("source_present_row_count", 0):
        errors.append("SOURCE_IMAGE_SUM_BELOW_PRESENT_COUNT")
    if not isinstance(p.get("eligible_roi_area_m2"), (int, float)) or p.get("eligible_roi_area_m2", 0) <= 0:
        errors.append("NONPOSITIVE_ELIGIBLE_ROI_AREA")
    for marker in ("marker_ge_005_count", "marker_ge_025_count", "marker_ge_050_count"):
        if not 0 <= p.get(marker, -1) <= n: errors.append("MARKER_COUNT_BOUNDS_FAILED")
    if p.get("marker_ge_050_count", 0) > p.get("marker_ge_025_count", 0) or p.get("marker_ge_025_count", 0) > p.get("marker_ge_005_count", 0):
        errors.append("MARKER_MONOTONICITY_FAILED")
    if p.get("validation_errors"):
        errors.append("SUMMARY_EMITTED_VALIDATION_ERRORS")
    if values is not None:
        values = sorted(values)
        expected = {
            "coverage_observation_count": len(values),
            "coverage_missing_count": p.get("expected_date_count", 0) - len(values),
            "marker_ge_005_count": sum(v >= .05 for v in values),
            "marker_ge_025_count": sum(v >= .25 for v in values),
            "marker_ge_050_count": sum(v >= .50 for v in values),
        }
        for name, value in expected.items():
            if p.get(name) != value: errors.append("SUMMARY_FORMULA_FAILED:" + name)
        stats = {"coverage_mean": sum(values) / len(values) if values else None,
                 "coverage_population_sd": population_sd(values),
                 "coverage_min": values[0] if values else None,
                 "coverage_q05_type7": type7(values, .05),
                 "coverage_q25_type7": type7(values, .25),
                 "coverage_q50_type7": type7(values, .50),
                 "coverage_max": values[-1] if values else None}
        for name, expected_value in stats.items():
            actual = p.get(name)
            if expected_value is None:
                if name in p: errors.append("SPARSE_NULL_OMISSION_FAILED:" + name)
            elif actual is None or abs(actual - expected_value) > 1e-12:
                errors.append("SUMMARY_FORMULA_FAILED:" + name)
    return sorted(set(errors))


def expected_chunk_keys(window: dict[str, Any], treatment: dict[str, Any]) -> list[str]:
    return [f"{date_utc}|{stream['stream_id']}|{treatment['erosion_id']}"
            for date_utc in dates(window["start"], window["end"])
            for stream in STREAMS]


def expected_stream_chunk_keys(window: dict[str, Any], treatment: dict[str, Any],
                               stream: dict[str, Any]) -> list[str]:
    return [f"{date_utc}|{stream['stream_id']}|{treatment['erosion_id']}"
            for date_utc in dates(window["start"], window["end"])]


def validate_stream_subrequest_evidence(
        evidence: Any, window: dict[str, Any], treatment: dict[str, Any],
        stream: dict[str, Any]) -> list[str]:
    """Fail closed on one transient, canonical, 14-row stream result."""
    errors: list[str] = []
    expected_fields = {
        "row_count", "row_keys", "unique_key_count",
        "validation_error_row_count", "validation_error_row_details",
        "strict_row_failure_count", "strict_row_failure_details",
        "stream_count", "treatment_count", "season_count",
        "coverage_values", "seasonal_summary_dictionaries",
        "summary_runtime_type_dictionaries",
    }
    stream_id = stream["stream_id"]
    if not isinstance(evidence, dict) or set(evidence) != expected_fields:
        return ["CHUNK_SUBREQUEST_SHAPE_FAILED:" + stream_id]
    expected_keys = expected_stream_chunk_keys(window, treatment, stream)
    if evidence["row_count"] != 14 or evidence["unique_key_count"] != 14 or \
       evidence["row_keys"] != expected_keys:
        errors.append("CHUNK_SUBREQUEST_ROW_KEYS_FAILED:" + stream_id)
    if evidence["validation_error_row_count"] != 0 or \
       evidence["validation_error_row_details"] != []:
        errors.append("CHUNK_SUBREQUEST_VALIDATION_FAILED:" + stream_id)
    if evidence["strict_row_failure_count"] != 0 or \
       evidence["strict_row_failure_details"] != []:
        errors.append("CHUNK_SUBREQUEST_STRICT_FAILED:" + stream_id)
    if evidence["stream_count"] != 1 or evidence["treatment_count"] != 1 or \
       evidence["season_count"] != 1:
        errors.append("CHUNK_SUBREQUEST_PROVENANCE_COUNT_FAILED:" + stream_id)
    values = evidence["coverage_values"]
    if not isinstance(values, list) or len(values) > 14 or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and
            math.isfinite(value) and 0 <= value <= 1 for value in values):
        errors.append("CHUNK_SUBREQUEST_COVERAGE_FAILED:" + stream_id)
    expected_summary_id = (
        f"{window['window_id']}__{stream_id}__{treatment['erosion_id']}")
    stream_summaries = evidence["seasonal_summary_dictionaries"]
    runtime = evidence["summary_runtime_type_dictionaries"]
    if not isinstance(stream_summaries, list) or len(stream_summaries) != 1 or \
       not isinstance(stream_summaries[0], dict) or \
       stream_summaries[0].get("summary_id") != expected_summary_id:
        errors.append("CHUNK_SUBREQUEST_SUMMARY_FAILED:" + stream_id)
    if not isinstance(runtime, list) or len(runtime) != 1 or \
       not isinstance(runtime[0], dict) or set(runtime[0]) != {
           "summary_id", "errors"} or \
       runtime[0].get("summary_id") != expected_summary_id or \
       runtime[0].get("errors") != []:
        errors.append("CHUNK_SUBREQUEST_SUMMARY_RUNTIME_FAILED:" + stream_id)
    if isinstance(stream_summaries, list) and len(stream_summaries) == 1 and \
       isinstance(stream_summaries[0], dict):
        summary = normalize_evaluated_float64(
            stream_summaries[0], load_authoritative_manifests()["coverage"])
        summary_errors = validate_evaluated_properties(
            summary, load_authoritative_manifests()["coverage"])
        if isinstance(values, list) and all(
                isinstance(value, (int, float)) and not isinstance(value, bool) and
                math.isfinite(value) and 0 <= value <= 1 for value in values):
            summary_errors.extend(validate_summary_formula(summary, values))
        expected_provenance = {
            "schema_version": VERSION["coverage_schema"],
            "specification_version": VERSION["specification"],
            "implementation_version_or_hash": VERSION["implementation"],
            "summary_id": expected_summary_id,
            "window_id": window["window_id"],
            "season": window["season"],
            "window_start_utc": window["start"],
            "window_end_exclusive_utc": window["end"],
            "stream_id": stream_id,
            "platform": stream["platform"],
            "phase": stream["phase"],
            "collection_id": stream["collection_id"],
            "erosion_id": treatment["erosion_id"],
            "erosion_distance_m": float(treatment["distance_m"]),
            "geometry_id": (
                "wise_wfd_v1_9_huaih049_2022_unrounded__" +
                treatment["suffix"]),
            "expected_date_count": 14,
            "coverage_definition": (
                "accepted_area_m2 / eligible_roi_area_m2; values exist only for "
                "one source image, positive eligible area, and no validation error"),
            "quantile_method": (
                "Hyndman-Fan Type 7: h=(n-1)p with linear interpolation; "
                "population SD divisor n"),
            "physical_schema_note": (
                "Unavailable nullable distribution values are omitted; "
                "no sentinel values."),
        }
        if any(summary.get(name) != expected
               for name, expected in expected_provenance.items()):
            summary_errors.append("CHUNK_SUMMARY_PROVENANCE_FAILED")
        if summary_errors:
            errors.append("CHUNK_SUBREQUEST_SUMMARY_GATES_FAILED:" + stream_id)
    return sorted(set(errors))


def collect_validated_stream_subrequests(
        window: dict[str, Any], treatment: dict[str, Any],
        evaluate_one: Any) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """Issue no later canonical request after one stream fails admission."""
    results: list[dict[str, Any]] = []
    for stream in STREAMS:
        evidence = evaluate_one(stream)
        errors = validate_stream_subrequest_evidence(
            evidence, window, treatment, stream)
        if errors:
            return results, errors, stream["stream_id"]
        results.append(evidence)
    return results, [], None


def combine_stream_subrequest_evidence(
        stream_evidence: list[dict[str, Any]], window: dict[str, Any],
        treatment: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate four transient 14-row results and rebuild one logical chunk."""
    if len(stream_evidence) != len(STREAMS):
        return {}, ["CHUNK_SUBREQUEST_COUNT_FAILED"]
    errors = [error
              for evidence, stream in zip(stream_evidence, STREAMS)
              for error in validate_stream_subrequest_evidence(
                  evidence, window, treatment, stream)]
    if errors:
        return {}, sorted(set(errors))
    return {
        "row_count": sum(item["row_count"] for item in stream_evidence),
        "row_keys": expected_chunk_keys(window, treatment),
        "unique_key_count": len(set(
            key for item in stream_evidence for key in item["row_keys"])),
        "validation_error_row_count": sum(
            item["validation_error_row_count"] for item in stream_evidence),
        "validation_error_row_details": [detail for item in stream_evidence
                                           for detail in item["validation_error_row_details"]],
        "strict_row_failure_count": sum(
            item["strict_row_failure_count"] for item in stream_evidence),
        "strict_row_failure_details": [detail for item in stream_evidence
                                         for detail in item["strict_row_failure_details"]],
        "stream_count": len(STREAMS),
        "treatment_count": 1,
        "season_count": 1,
        "coverage_values": {
            stream["stream_id"]: list(item["coverage_values"])
            for item, stream in zip(stream_evidence, STREAMS)},
        "seasonal_summary_dictionaries": [
            item["seasonal_summary_dictionaries"][0]
            for item in stream_evidence],
        "summary_runtime_type_dictionaries": [
            item["summary_runtime_type_dictionaries"][0]
            for item in stream_evidence],
    }, []


def canonical_checkpoint_coverage_values(
        value: Any) -> dict[str, Any] | None:
    """Accept the exact stream-name set and restore canonical stream order."""
    expected_stream_ids = [stream["stream_id"] for stream in STREAMS]
    if not isinstance(value, dict) or \
       set(value) != set(expected_stream_ids) or \
       len(value) != len(expected_stream_ids):
        return None
    return {stream_id: value[stream_id] for stream_id in expected_stream_ids}


def validate_checkpoint_chunk(record: dict[str, Any], index: int,
                              window: dict[str, Any],
                              treatment: dict[str, Any]) -> list[str]:
    """Revalidate all coordinate-free row-key, coverage, and summary evidence."""
    errors: list[str] = []
    required = {"chunk_index", "window_id", "erosion_id", "row_keys",
                "coverage_values", "seasonal_summaries",
                "validated_evidence_sha256"}
    if not isinstance(record, dict) or set(record) != required:
        return ["CHECKPOINT_CHUNK_SHAPE_FAILED"]
    if record["chunk_index"] != index or record["window_id"] != window["window_id"] or \
       record["erosion_id"] != treatment["erosion_id"]:
        errors.append("CHECKPOINT_CHUNK_IDENTITY_FAILED")
    keys = record["row_keys"]
    expected_keys = expected_chunk_keys(window, treatment)
    if not isinstance(keys, list) or keys != expected_keys or len(set(keys)) != 56:
        errors.append("CHECKPOINT_CHUNK_ROW_KEYS_FAILED")
    coverage_values = canonical_checkpoint_coverage_values(
        record["coverage_values"])
    if coverage_values is None:
        errors.append("CHECKPOINT_CHUNK_COVERAGE_SHAPE_FAILED")
        coverage_values = {}
    else:
        for stream_id, values in coverage_values.items():
            if not isinstance(values, list) or len(values) > 14 or not all(
                    isinstance(value, (int, float)) and not isinstance(value, bool) and
                    math.isfinite(value) and 0 <= value <= 1 for value in values):
                errors.append("CHECKPOINT_CHUNK_COVERAGE_VALUES_FAILED:" + stream_id)
    summaries = record["seasonal_summaries"]
    expected_ids = [
        f"{window['window_id']}__{stream['stream_id']}__{treatment['erosion_id']}"
        for stream in STREAMS]
    if not isinstance(summaries, list) or len(summaries) != 4 or \
       [item.get("summary_id") if isinstance(item, dict) else None
        for item in summaries] != expected_ids:
        errors.append("CHECKPOINT_CHUNK_SUMMARY_IDENTITY_FAILED")
    else:
        for summary, stream in zip(summaries, STREAMS):
            values = coverage_values.get(stream["stream_id"], [])
            formula_errors = validate_summary_formula(summary, values)
            if summary.get("window_id") != window["window_id"] or \
               summary.get("season") != window["season"] or \
               summary.get("stream_id") != stream["stream_id"] or \
               summary.get("platform") != stream["platform"] or \
               summary.get("phase") != stream["phase"] or \
               summary.get("collection_id") != stream["collection_id"] or \
               summary.get("erosion_id") != treatment["erosion_id"] or \
               summary.get("erosion_distance_m") != float(treatment["distance_m"]):
                formula_errors.append("CHECKPOINT_CHUNK_SUMMARY_PROVENANCE_FAILED")
            errors.extend(formula_errors)
    certificate_input = {name: value for name, value in record.items()
                         if name != "validated_evidence_sha256"}
    if record["validated_evidence_sha256"] != canonical_sha256(certificate_input):
        errors.append("CHECKPOINT_CHUNK_CERTIFICATE_FAILED")
    return sorted(set(errors))


def make_checkpoint_chunk(index: int, window: dict[str, Any],
                          treatment: dict[str, Any], evidence: dict[str, Any],
                          summaries: list[dict[str, Any]]) -> dict[str, Any]:
    record = {
        "chunk_index": index,
        "window_id": window["window_id"],
        "erosion_id": treatment["erosion_id"],
        "row_keys": list(evidence["row_keys"]),
        "coverage_values": {
            stream["stream_id"]: list(evidence["coverage_values"][stream["stream_id"]])
            for stream in STREAMS},
        "seasonal_summaries": summaries,
    }
    record["validated_evidence_sha256"] = canonical_sha256(record)
    return record


def validate_vector_formulas(vectors: list[dict[str, Any]]) -> list[str]:
    manifest = load_authoritative_manifests()["vector"]
    errors: list[str] = []
    if len(vectors) != 4: return ["VECTOR_COUNT_MISMATCH"]
    source_area = vectors[0]["vector_area_epsg3035_m2"]
    tolerance = max(100.0, source_area * 1e-6)
    for index, p in enumerate(vectors):
        errors += validate_evaluated_properties(p, manifest)
        expected_treatment = TREATMENTS[index]
        if p.get("erosion_id") != expected_treatment["erosion_id"] or abs(p.get("erosion_distance_m", math.inf) - expected_treatment["distance_m"]) > 1e-12:
            errors.append("VECTOR_TREATMENT_IDENTITY_FAILED")
        area = p["vector_area_epsg3035_m2"]
        if area <= 0: errors.append("EMPTY_OR_NONPOSITIVE_CANDIDATE")
        if abs(p["retained_area_fraction"] - area / source_area) > 1e-12: errors.append("RETAINED_FRACTION_FORMULA_FAILED")
        if abs(p["removed_area_m2"] - (source_area - area)) > tolerance: errors.append("REMOVED_AREA_FORMULA_FAILED")
        if abs(p["area_balance_residual_m2"] - (source_area - (area + p["removed_area_m2"]))) > tolerance: errors.append("VECTOR_AREA_BALANCE_FAILED")
        if not 0 <= p["outside_source_area_m2"] <= tolerance: errors.append("CANDIDATE_OUTSIDE_SOURCE")
        if not 0 <= p["opening_loss_area_m2"] <= source_area: errors.append("OPENING_LOSS_BOUNDS_FAILED")
        weaker_present = "weaker_candidate_containment_area_m2" in p
        if index == 0 and weaker_present: errors.append("UNEXPECTED_WEAKER_CONTAINMENT")
        if index > 0 and (not weaker_present or p["weaker_candidate_containment_area_m2"] > tolerance):
            errors.append("WEAKER_CANDIDATE_CONTAINMENT_FAILED")
        if index > 0 and vectors[index - 1]["vector_area_epsg3035_m2"] < area:
            errors.append("VECTOR_AREAS_NOT_NONINCREASING")
        if p.get("validation_errors"): errors.append("VECTOR_EMITTED_VALIDATION_ERRORS")
    return sorted(set(errors))


def self_test() -> dict[str, Any]:
    failures: list[str] = []
    original_recursion_limit = sys.getrecursionlimit()
    try:
        runner_source = Path(__file__).read_text(encoding="utf-8")
        projection_source = runner_source.rsplit(
            "    def projection_diagnostic_evidence", 1)[1].split(
            "    def _reduce", 1)[0]
        if '.filterDate(start, start.advance(1, "day"))' not in projection_source or \
           '.sort("system:time_start")' not in projection_source or \
           'self.contexts[stream["stream_id"]]' not in projection_source or \
           '.projection().getInfo()' not in projection_source:
            failures.append("projection_diagnostic_selection_static_fixture")
        if "ee.List(" in projection_source or ".transform()" in projection_source:
            failures.append("projection_diagnostic_wkt_list_cast_static_fixture")
        process_source = runner_source.rsplit(
            "    def _process", 1)[1].split("    def row", 1)[0]
        reduce_source = runner_source.rsplit(
            "    def _reduce", 1)[1].split("    def _sum_area", 1)[0]
        if "context[\"transform_wkt\"]" in process_source or \
           ".resample(" in process_source or ".reproject(" in process_source:
            failures.append("audit005_processing_projection_static_fixture")
        if 'image.get("system:index")' not in process_source or \
           "image.id(), certified_source_id" in process_source:
            failures.append("projection_certification_system_index_handoff_fixture")
        authenticated_certification = {
            "source_image_id": "MODIS/061/MYD11A1/MYD11A1.A2024295.h18v04.061",
            "source_system_index": "MYD11A1.A2024295.h18v04.061",
        }
        if certified_source_system_index(authenticated_certification) != \
                "MYD11A1.A2024295.h18v04.061" or \
           authenticated_certification["source_image_id"] == \
                certified_source_system_index(authenticated_certification):
            failures.append("projection_certification_authenticated_identity_fixture")
        for malformed_certification in ({}, {"source_system_index": ""},
                                        {"source_system_index": 1}):
            try:
                certified_source_system_index(malformed_certification)
                failures.append("projection_certification_missing_identity_false_pass_fixture")
            except ValueError:
                pass
        if 'crs=context["crs"]' not in reduce_source or \
           'crsTransform=context["transform"]' not in reduce_source or \
           "bestEffort=False" not in reduce_source:
            failures.append("audit005_reducer_affine_unchanged_static_fixture")
        resolved_projection_streams = validate_projection_diagnostic_request(
            "2024-10-21", ["aqua_day", "aqua_night"])
        if [stream["stream_id"] for stream in resolved_projection_streams] != [
                "aqua_day", "aqua_night"]:
            failures.append("projection_diagnostic_request_fixture")
        for bad_date, bad_streams in (
                ("2024-10-21T00:00:00", ["aqua_day"]),
                ("2024-10-21", []),
                ("2024-10-21", ["aqua_day", "aqua_day"]),
                ("2024-10-21", ["unknown_stream"])):
            try:
                validate_projection_diagnostic_request(bad_date, bad_streams)
                failures.append("projection_diagnostic_bad_request_false_pass_fixture")
            except ValueError:
                pass
        aqua_day = next(stream for stream in STREAMS
                        if stream["stream_id"] == "aqua_day")
        diagnostic_affine = [926.6254331387694, 0.0, -20015109.354,
                             0.0, -926.6254331387694, 10007554.677]
        exact_displacement = affine_displacement_evidence(
            diagnostic_affine, diagnostic_affine)
        valid_projection_evidence = {
            "date_utc": "2024-10-21",
            "stream_id": "aqua_day",
            "collection_id": aqua_day["collection_id"],
            "lst_band": aqua_day["lst"],
            "source_image_count": 1,
            "source_image_ids": ["MODIS/061/MYD11A1/source"],
            "source_image_id": "MODIS/061/MYD11A1/source",
            "source_system_time_start": 1729468800000,
            "canonical_projection_reference_image_id": "MODIS/061/MYD11A1/reference",
            "canonical_crs": "SR-ORG:6974",
            "canonical_affine": diagnostic_affine,
            "source_crs": "SR-ORG:6974",
            "source_affine": diagnostic_affine,
            "affine_elementwise_difference": [0.0] * 6,
            "crs_equal": True,
            "affine_equal": True,
            "projection_equal": True,
            "grid_width_columns": exact_displacement["grid_width_columns"],
            "grid_height_rows": exact_displacement["grid_height_rows"],
            "grid_corner_convention": exact_displacement["grid_corner_convention"],
            "corner_displacements": exact_displacement["corner_displacements"],
            "maximum_induced_displacement_m": 0.0,
            "maximum_allowed_displacement_m": AUDIT_AFFINE_MAX_DISPLACEMENT_M,
            "affine_numerically_equivalent": True,
            "intra_image_bands_exact": True,
            "projection_acceptance_pass": True,
            "band_projections": {
                aqua_day[key]: {"crs": "SR-ORG:6974",
                                "affine": diagnostic_affine}
                for key in ("lst", "qc", "time", "angle", "clear")
            },
        }
        if validate_projection_diagnostic_evidence(
                valid_projection_evidence, "2024-10-21", aqua_day):
            failures.append("projection_diagnostic_valid_evidence_fixture")
        affine_test_base = [1.0, 0.0, 0.0, 0.0, -1.0, 0.0]
        micrometre_affine = list(affine_test_base)
        micrometre_affine[2] += 0.000001
        micrometre = affine_displacement_evidence(
            affine_test_base, micrometre_affine)
        if not micrometre["affine_numerically_equivalent"] or \
           abs(micrometre["maximum_induced_displacement_m"] - 0.000001) > 1e-15:
            failures.append("affine_micrometre_equivalence_fixture")
        observed_scale_case = list(diagnostic_affine)
        observed_scale_case[0] += 2e-11
        observed_micrometre = affine_displacement_evidence(
            diagnostic_affine, observed_scale_case)
        if not observed_micrometre["affine_numerically_equivalent"] or \
           not 0 < observed_micrometre["maximum_induced_displacement_m"] < 0.000001:
            failures.append("affine_observed_micrometre_scale_fixture")
        threshold_affine = list(affine_test_base)
        threshold_affine[2] += AUDIT_AFFINE_MAX_DISPLACEMENT_M
        threshold_case = affine_displacement_evidence(
            affine_test_base, threshold_affine)
        if not threshold_case["affine_numerically_equivalent"]:
            failures.append("affine_threshold_inclusive_fixture")
        above_affine = list(affine_test_base)
        above_affine[2] += AUDIT_AFFINE_MAX_DISPLACEMENT_M * 1.001
        if affine_displacement_evidence(
                affine_test_base, above_affine)["affine_numerically_equivalent"]:
            failures.append("affine_above_threshold_fixture")
        accumulated_scale_affine = list(affine_test_base)
        accumulated_scale_affine[0] += (
            AUDIT_AFFINE_MAX_DISPLACEMENT_M * 1.001 /
            MODIS_GRID_WIDTH_COLUMNS)
        accumulated = affine_displacement_evidence(
            affine_test_base, accumulated_scale_affine)
        if accumulated["affine_numerically_equivalent"] or \
           accumulated["maximum_induced_displacement_m"] <= \
                AUDIT_AFFINE_MAX_DISPLACEMENT_M:
            failures.append("affine_accumulated_scale_error_fixture")
        projection_negative_shapes = []
        wrong_count = dict(valid_projection_evidence)
        wrong_count["source_image_count"] = 2
        projection_negative_shapes.append(wrong_count)
        wrong_affine_type = dict(valid_projection_evidence)
        wrong_affine_type["source_affine"] = ["bad"] * 6
        projection_negative_shapes.append(wrong_affine_type)
        wrong_difference = dict(valid_projection_evidence)
        wrong_difference["affine_elementwise_difference"] = [1.0] + [0.0] * 5
        projection_negative_shapes.append(wrong_difference)
        wrong_equality = dict(valid_projection_evidence)
        wrong_equality["projection_equal"] = False
        projection_negative_shapes.append(wrong_equality)
        wrong_crs_identity = dict(valid_projection_evidence)
        wrong_crs_identity["source_crs"] = "EPSG:4326"
        projection_negative_shapes.append(wrong_crs_identity)
        wrong_affine_identity = dict(valid_projection_evidence)
        changed_source_affine = list(diagnostic_affine)
        changed_source_affine[0] += 1.0
        wrong_affine_identity["source_affine"] = changed_source_affine
        wrong_affine_identity["affine_elementwise_difference"] = [1.0] + [0.0] * 5
        projection_negative_shapes.append(wrong_affine_identity)
        wrong_lst_projection = dict(valid_projection_evidence)
        wrong_lst_projection["band_projections"] = {
            name: dict(value)
            for name, value in valid_projection_evidence["band_projections"].items()
        }
        wrong_lst_projection["band_projections"][aqua_day["lst"]] = {
            "crs": "EPSG:4326", "affine": diagnostic_affine,
        }
        projection_negative_shapes.append(wrong_lst_projection)
        wrong_time_window = dict(valid_projection_evidence)
        wrong_time_window["source_system_time_start"] = 1729555200000
        projection_negative_shapes.append(wrong_time_window)
        malformed_projection = dict(valid_projection_evidence)
        malformed_projection.pop("band_projections")
        projection_negative_shapes.append(malformed_projection)
        if any(not validate_projection_diagnostic_evidence(
                value, "2024-10-21", aqua_day)
               for value in projection_negative_shapes):
            failures.append("projection_diagnostic_negative_false_pass_fixture")
        strict_source = runner_source.rsplit(
            "    def _strict_row_validation", 1)[1].split(
            "    def summary", 1)[0]
        nullable_names = {
            field["name"] for field in load_authoritative_manifests()["row"]
            if field["nullable"]
        }
        unsafe_nullable_numbers = set(re.findall(
            r'ee\.Number\(feature\.get\("([^"]+)"\)\)', strict_source
        )).intersection(nullable_names)
        unsafe_nullable_lists = set(re.findall(
            r'ee\.List\(feature\.get\("([^"]+)"\)\)', strict_source
        )).intersection(nullable_names)
        if unsafe_nullable_numbers or unsafe_nullable_lists:
            failures.append(
                "strict_nullable_direct_access_source_audit:" +
                ",".join(sorted(unsafe_nullable_numbers | unsafe_nullable_lists)))
        manifest_names = {
            field["name"] for field in load_authoritative_manifests()["row"]
        }
        if len(SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS) != len(set(
                SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS)):
            failures.append("single_source_formula_required_fields_not_unique")
        undeclared_formula_fields = set(
            SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS).difference(manifest_names)
        if undeclared_formula_fields:
            failures.append(
                "single_source_formula_required_fields_undeclared:" +
                ",".join(sorted(undeclared_formula_fields)))
        complete_formula_names = set(SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS)
        if single_source_formula_presence_errors(complete_formula_names, 1):
            failures.append("single_source_formula_complete_fixture")
        for missing_name in SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS:
            missing_errors = single_source_formula_presence_errors(
                complete_formula_names - {missing_name}, 1)
            if missing_errors != [
                    "ROW_SINGLE_SOURCE_FORMULA_FIELD_MISSING:" + missing_name]:
                failures.append(
                    "single_source_formula_missing_field_fixture:" + missing_name)
        if single_source_formula_presence_errors(set(), 0) or \
           single_source_formula_presence_errors(set(), 2):
            failures.append("non_single_source_sparse_omission_fixture")
        projection_branch = SINGLE_SOURCE_SPARSE_ERROR_BRANCHES["projection_mismatch"]
        sparse_error_fixture = {
            "source_image_count": 1,
            "eligible_roi_area_m2": 100.0,
            "validation_errors": [projection_branch["validation_error"]],
            "null_reason": "projection_mismatch",
            "row_state": projection_branch["row_state"],
            "state_reason": projection_branch["state_reason"],
        }
        if single_source_formula_presence_errors(
                sparse_error_fixture.keys(), 1,
                sparse_error_fixture["validation_errors"],
                sparse_error_fixture["eligible_roi_area_m2"]) or \
           sparse_single_source_error_identity_errors(sparse_error_fixture):
            failures.append("single_source_sparse_processing_error_fixture")
        row_manifest = load_authoritative_manifests()["row"]
        sparse_contract_fixture = {
            field["name"]: "base_value"
            for field in row_manifest if not field["nullable"]
        }
        sparse_contract_fixture.update({
            "source_image_id": "MODIS/source_image",
            "source_system_time_start": 1,
            "null_reason": "projection_mismatch",
            "notes": "exact mismatch note",
            "_sparse_expected_notes": "exact mismatch note",
            "_sparse_expected_projection_reference_image_id": "reference_image",
            "projection_reference_image_id": "reference_image",
            "_sparse_expected_source_crs": "SR-ORG:6974",
            "source_crs": "SR-ORG:6974",
            "_sparse_expected_source_crs_transform": [1.0, 0.0, 0.0, 0.0, -1.0, 0.0],
            "source_crs_transform": [1.0, 0.0, 0.0, 0.0, -1.0, 0.0],
            "_sparse_expected_reducer_scale_or_transform": [1.0, 0.0, 0.0, 0.0, -1.0, 0.0],
            "reducer_scale_or_transform": [1.0, 0.0, 0.0, 0.0, -1.0, 0.0],
        })
        if validate_sparse_branch_physical_contract(
                sparse_contract_fixture, row_manifest):
            failures.append("sparse_branch_exact_physical_contract_fixture")
        forbidden_science_fixture = dict(sparse_contract_fixture)
        forbidden_science_fixture["temperature_k_mean"] = 290.0
        if "ROW_SPARSE_BRANCH_PHYSICAL_PROPERTIES_FAILED" not in \
                validate_sparse_branch_physical_contract(
                    forbidden_science_fixture, row_manifest):
            failures.append("sparse_branch_forbidden_science_negative_fixture")
        bad_notes_fixture = dict(sparse_contract_fixture)
        bad_notes_fixture["notes"] = "forged note"
        if "ROW_SPARSE_BRANCH_PROVENANCE_FAILED" not in \
                validate_sparse_branch_physical_contract(bad_notes_fixture, row_manifest):
            failures.append("sparse_branch_bad_notes_negative_fixture")
        bad_projection_fixture = dict(sparse_contract_fixture)
        bad_projection_fixture["source_crs"] = "wrong_crs"
        if "ROW_SPARSE_BRANCH_PROVENANCE_FAILED" not in \
                validate_sparse_branch_physical_contract(
                    bad_projection_fixture, row_manifest):
            failures.append("sparse_branch_bad_projection_negative_fixture")
        malformed_sparse_error = dict(sparse_error_fixture)
        malformed_sparse_error["validation_errors"] = ["WRONG_ERROR"]
        if not sparse_single_source_error_identity_errors(malformed_sparse_error):
            failures.append("single_source_sparse_error_identity_negative_fixture")
        default_only_success = {
            "source_image_count": 1,
            "eligible_roi_area_m2": 100.0,
            "validation_errors": [],
        }
        if not single_source_formula_presence_errors(
                default_only_success.keys(), 1, [], 100.0) or \
           sparse_single_source_error_identity_errors(default_only_success):
            failures.append("single_source_safe_defaults_false_pass_fixture")
        invalid_nonpositive_success = {
            "source_image_count": 1,
            "eligible_roi_area_m2": 0.0,
            "validation_errors": [],
        }
        if not sparse_single_source_error_identity_errors(invalid_nonpositive_success):
            failures.append("single_source_branch_classification_negative_fixture")
        valid_error_detail = {
            "date_utc": "2024-10-21",
            "stream_id": "aqua_day",
            "_audit_key": "2024-10-21|aqua_day|EROSION_0000M",
            "validation_errors": ["SOURCE_PROJECTION_MISMATCH"],
            "row_state": "SOURCE_PRESENT_NO_RETRIEVAL",
            "null_reason": "projection_mismatch",
            "state_reason": projection_branch["state_reason"],
            "projection_reference_image_id": "MODIS/reference_image",
            "source_crs": "SR-ORG:6974",
            "_strict_row_errors": [],
        }
        valid_detail_evidence = {
            "validation_error_row_count": 1,
            "validation_error_row_details": [valid_error_detail],
        }
        if validate_validation_error_row_details(valid_detail_evidence):
            failures.append("validation_error_detail_expected_shape_fixture")
        malformed_detail_evidence = [
            {**valid_detail_evidence, "validation_error_row_count": 2},
            {**valid_detail_evidence, "validation_error_row_details": [
                {key: value for key, value in valid_error_detail.items()
                 if key != "state_reason"}]},
            {**valid_detail_evidence, "validation_error_row_details": "not_a_list"},
        ]
        if any(not validate_validation_error_row_details(value)
               for value in malformed_detail_evidence):
            failures.append("validation_error_detail_malformed_false_pass_fixture")
        recursion_evidence = configure_ee_serializer_recursion_limit()
        def bounded_recursive_walk(remaining: int) -> int:
            return 0 if remaining == 0 else 1 + bounded_recursive_walk(remaining - 1)
        if recursion_evidence["effective_limit"] < EE_SERIALIZER_RECURSION_LIMIT or \
           bounded_recursive_walk(1500) != 1500:
            failures.append("bounded_serializer_recursion_guard")
    except RecursionError:
        failures.append("bounded_serializer_recursion_guard")
    finally:
        sys.setrecursionlimit(original_recursion_limit)
    if [type7([0, 10, 20, 30, 40], p) for p in (0.05, 0.25, 0.5)] != [2, 10, 20]:
        failures.append("type7")
    if population_sd([9, 11]) != 1:
        failures.append("population_sd")
    descriptors = [(w["window_id"], t["erosion_id"]) for w in WINDOWS for t in TREATMENTS]
    keys = [f"{d}|{s['stream_id']}|{t['erosion_id']}" for w in WINDOWS for d in dates(w['start'], w['end']) for s in STREAMS for t in TREATMENTS]
    if len(descriptors) != 16 or len(set(descriptors)) != 16:
        failures.append("chunk_arithmetic")
    if len(keys) != 896 or len(set(keys)) != 896:
        failures.append("row_key_arithmetic")
    if 4 * 4 * 5 != 80:
        failures.append("summary_arithmetic")
    try:
        manifests = load_authoritative_manifests()
        if [len(manifests[k]) for k in ("row", "vector", "coverage")] != [100, 34, 45]:
            failures.append("manifest_counts")
        sparse_fixture = {f["name"]: ("x" if f["type"] == "string" else
                          False if f["type"] == "boolean" else
                          [] if f["type"].startswith("list<") else 1)
                          for f in manifests["coverage"] if not f["nullable"]}
        # Prove strict validators reject defects instead of merely exercising pass paths.
        broken = dict(sparse_fixture)
        broken.pop("summary_id")
        broken["erosion_id"] = "NA"
        caught = validate_evaluated_properties(broken, manifests["coverage"])
        if not any(x.startswith("MISSING_REQUIRED_FIELDS") for x in caught) or not any(x.startswith("FORBIDDEN_SENTINEL") for x in caught):
            failures.append("strict_schema_negative_fixture")
        swapped = dict(sparse_fixture)
        swapped.update({"row_count": 1.0, "erosion_distance_m": 1,
                        "validation_errors": [1]})
        swapped_errors = validate_evaluated_properties(swapped, manifests["coverage"])
        if not any(x == "TYPE_MISMATCH:row_count" for x in swapped_errors) or \
           not any(x == "TYPE_MISMATCH:erosion_distance_m" for x in swapped_errors) or \
           not any(x == "LIST_ELEMENT_TYPE_MISMATCH:validation_errors" for x in swapped_errors):
            failures.append("strict_swapped_scalar_list_type_fixture")
        vector_type_fixture = {f["name"]: ("x" if f["type"] == "string" else
                               True if f["type"] == "boolean" else
                               [1, 2, 3, 4] if f["name"] == "source_bbox_wgs84" else
                               [] if f["type"].startswith("list<") else
                               1 if f["type"] == "int64" else 1.0)
                               for f in manifests["vector"] if not f["nullable"]}
        vector_type_errors = validate_evaluated_properties(vector_type_fixture, manifests["vector"])
        if "LIST_ELEMENT_TYPE_MISMATCH:source_bbox_wgs84" not in vector_type_errors:
            failures.append("strict_swapped_numeric_list_type_fixture")
        fake_summary = dict(sparse_fixture)
        fake_summary.update({"row_count": 14, "expected_date_count": 14,
                             "coverage_observation_count": 12, "coverage_missing_count": 5,
                             "state_accepted_count": 4, "state_cloud_count": 4,
                             "state_rejected_count": 2, "state_no_retrieval_count": 2,
                             "state_other_count": 2, "source_present_row_count": 10,
                             "no_source_row_count": 4, "duplicate_source_row_count": 0,
                             "source_image_count_sum": 5, "eligible_roi_area_m2": -1.0,
                             "marker_ge_005_count": 7, "marker_ge_025_count": 6,
                             "marker_ge_050_count": 9, "validation_errors": []})
        formula_errors = validate_summary_formula(fake_summary)
        required_summary_failures = {"COVERAGE_COUNT_IDENTITY_FAILED", "MARKER_MONOTONICITY_FAILED",
                                     "STATE_OTHER_SOURCE_IDENTITY_FAILED", "COVERAGE_EXCEEDS_SOURCE_PRESENT",
                                     "SOURCE_IMAGE_SUM_BELOW_PRESENT_COUNT", "NONPOSITIVE_ELIGIBLE_ROI_AREA"}
        if not required_summary_failures.issubset(formula_errors):
            failures.append("strict_summary_negative_fixture")
        seasonal_zero_fixture: list[dict[str, Any]] = []
        zero_coverage: dict[tuple[str, str], list[float]] = {}
        for treatment in TREATMENTS:
            for stream in STREAMS:
                zero_coverage[(treatment["erosion_id"], stream["stream_id"])] = [0, 0, 0, 0]
                for window in WINDOWS:
                    seasonal_zero_fixture.append({
                        "schema_version": VERSION["coverage_schema"],
                        "specification_version": VERSION["specification"],
                        "implementation_version_or_hash": VERSION["implementation"],
                        "run_timestamp_utc": "2026-08-20T00:00:00Z",
                        "platform": stream["platform"], "phase": stream["phase"],
                        "collection_id": stream["collection_id"],
                        "geometry_id": "wise_fixture", "coverage_definition": "fixture",
                        "quantile_method": "fixture", "physical_schema_note": "fixture",
                        "eligible_roi_area_m2": 1.0, "erosion_id": treatment["erosion_id"],
                        "stream_id": stream["stream_id"], "row_count": 14,
                        "source_image_count_sum": 14, "source_present_row_count": 14,
                        "no_source_row_count": 0, "duplicate_source_row_count": 0,
                        "validation_error_row_count": 0, "state_accepted_count": 14,
                        "state_cloud_count": 0, "state_rejected_count": 0,
                        "state_no_retrieval_count": 0, "state_other_count": 0,
                    })
        overall_zero = combine_overall(seasonal_zero_fixture, zero_coverage)
        zero_type_errors = validate_evaluated_properties(
            overall_zero[0], manifests["coverage"])
        if any(error.startswith("TYPE_MISMATCH:") for error in zero_type_errors):
            failures.append("overall_integer_zero_float64_fixture")
        for float_field in ("erosion_distance_m", "eligible_roi_area_m2", "coverage_mean",
                            "coverage_population_sd", "coverage_min", "coverage_q05_type7",
                            "coverage_q25_type7", "coverage_q50_type7", "coverage_max"):
            if not isinstance(overall_zero[0].get(float_field), float):
                failures.append("overall_float_cast_fixture:" + float_field)
        vector_rows = []
        for index, area in enumerate((1000.0, 900.0, 800.0, 700.0)):
            row: dict[str, Any] = {}
            for field in manifests["vector"]:
                logical = field["type"]
                if field["nullable"] and index == 0:
                    continue
                if logical == "string": row[field["name"]] = "x"
                elif logical == "boolean": row[field["name"]] = True
                elif logical == "int64": row[field["name"]] = 1
                elif logical == "float64": row[field["name"]] = 1.0
                elif logical.startswith("list<string>"): row[field["name"]] = []
                elif logical.startswith("list<float64>"): row[field["name"]] = [1.0] * (4 if "[4]" in logical else 0)
            row.update({"vector_area_epsg3035_m2": area,
                        "erosion_id": TREATMENTS[index]["erosion_id"],
                        "erosion_distance_m": float(TREATMENTS[index]["distance_m"]),
                        "retained_area_fraction": area / 1000.0,
                        "removed_area_m2": 1000.0 - area,
                        "area_balance_residual_m2": 0.0,
                        "outside_source_area_m2": 0.0,
                        "opening_loss_area_m2": 0.0,
                        "validation_errors": []})
            if index > 0: row["weaker_candidate_containment_area_m2"] = 0.0
            vector_rows.append(row)
        authenticated_vector_shape = []
        for row in vector_rows:
            json_shaped = {
                name: ([int(item) if isinstance(item, float) and item.is_integer() else item
                        for item in value] if isinstance(value, list) else
                       int(value) if isinstance(value, float) and value.is_integer() else value)
                for name, value in row.items()
            }
            authenticated_vector_shape.append(normalize_evaluated_float64(
                json_shaped, manifests["vector"]))
        if validate_vector_formulas(authenticated_vector_shape):
            failures.append("authenticated_vector_integer_zero_normalization_fixture")
        compact_vector_fixture = [compact_validated_vector(row)
                                  for row in authenticated_vector_shape]
        if validate_compact_vectors(compact_vector_fixture):
            failures.append("checkpoint_compact_vector_validation_fixture")
        malformed_compact = json.loads(json.dumps(compact_vector_fixture))
        malformed_compact[1]["validated_full_manifest_sha256"] = "not_sha256"
        if "VECTOR_VALIDATION_CERTIFICATE_FAILED" not in \
                validate_compact_vectors(malformed_compact):
            failures.append("checkpoint_compact_vector_certificate_negative_fixture")
        checkpoint_fixture = empty_checkpoint({"fixture": "compatible"})
        if checkpoint_fixture["checkpoint_format"] != CHECKPOINT_FORMAT or \
           checkpoint_fixture["compatibility_sha256"] != canonical_sha256(
               {"fixture": "compatible"}) or \
           checkpoint_fixture["completed_vectors"] or \
           checkpoint_fixture["completed_chunks"] or \
           checkpoint_fixture["full_acceptance_claimed"] is not False:
            failures.append("checkpoint_empty_shape_fixture")
        canonical_stream_ids = [stream["stream_id"] for stream in STREAMS]
        reversed_coverage_fixture = {
            stream_id: [float(index) / 10.0]
            for index, stream_id in enumerate(reversed(canonical_stream_ids))
        }
        canonicalized_coverage = canonical_checkpoint_coverage_values(
            reversed_coverage_fixture)
        if canonicalized_coverage is None or \
           list(canonicalized_coverage) != canonical_stream_ids or \
           any(canonicalized_coverage[stream_id] !=
               reversed_coverage_fixture[stream_id]
               for stream_id in canonical_stream_ids):
            failures.append("checkpoint_stream_order_independent_fixture")
        for invalid_coverage in (
                {key: [] for key in canonical_stream_ids[:-1]},
                {**{key: [] for key in canonical_stream_ids}, "extra_stream": []}):
            if canonical_checkpoint_coverage_values(invalid_coverage) is not None:
                failures.append("checkpoint_exact_stream_set_negative_fixture")
        if CHUNK_REQUEST_DECOMPOSITION != {
                "logical_chunk_rows": 56,
                "subrequest_count": 4,
                "rows_per_subrequest": 14,
                "stream_order": canonical_stream_ids,
                "sequential": True,
                "atomic_save_after_all_subrequests": True,
                "partial_subrequest_persistence": False}:
            failures.append("audit010_request_decomposition_fixture")
        subrequest_fixtures: list[dict[str, Any]] = []
        fixture_window, fixture_treatment = WINDOWS[0], TREATMENTS[2]
        for stream in STREAMS:
            summary_id = (
                f"{fixture_window['window_id']}__{stream['stream_id']}__"
                f"{fixture_treatment['erosion_id']}")
            summary_fixture = dict(sparse_fixture)
            summary_fixture.update({
                "schema_version": VERSION["coverage_schema"],
                "specification_version": VERSION["specification"],
                "implementation_version_or_hash": VERSION["implementation"],
                "summary_id": summary_id,
                "window_id": fixture_window["window_id"],
                "season": fixture_window["season"],
                "window_start_utc": fixture_window["start"],
                "window_end_exclusive_utc": fixture_window["end"],
                "stream_id": stream["stream_id"],
                "platform": stream["platform"],
                "phase": stream["phase"],
                "collection_id": stream["collection_id"],
                "erosion_id": fixture_treatment["erosion_id"],
                "erosion_distance_m": float(fixture_treatment["distance_m"]),
                "geometry_id": (
                    "wise_wfd_v1_9_huaih049_2022_unrounded__" +
                    fixture_treatment["suffix"]),
                "expected_date_count": 14,
                "row_count": 14,
                "source_image_count_sum": 0,
                "source_present_row_count": 0,
                "no_source_row_count": 14,
                "duplicate_source_row_count": 0,
                "validation_error_row_count": 0,
                "state_accepted_count": 0,
                "state_cloud_count": 0,
                "state_rejected_count": 0,
                "state_no_retrieval_count": 0,
                "state_other_count": 14,
                "coverage_observation_count": 0,
                "coverage_missing_count": 14,
                "marker_ge_005_count": 0,
                "marker_ge_025_count": 0,
                "marker_ge_050_count": 0,
                "eligible_roi_area_m2": 1.0,
                "coverage_definition": (
                    "accepted_area_m2 / eligible_roi_area_m2; values exist only for "
                    "one source image, positive eligible area, and no validation error"),
                "quantile_method": (
                    "Hyndman-Fan Type 7: h=(n-1)p with linear interpolation; "
                    "population SD divisor n"),
                "physical_schema_note": (
                    "Unavailable nullable distribution values are omitted; "
                    "no sentinel values."),
                "validation_errors": [],
            })
            subrequest_fixtures.append({
                "row_count": 14,
                "row_keys": expected_stream_chunk_keys(
                    fixture_window, fixture_treatment, stream),
                "unique_key_count": 14,
                "validation_error_row_count": 0,
                "validation_error_row_details": [],
                "strict_row_failure_count": 0,
                "strict_row_failure_details": [],
                "stream_count": 1,
                "treatment_count": 1,
                "season_count": 1,
                "coverage_values": [],
                "seasonal_summary_dictionaries": [summary_fixture],
                "summary_runtime_type_dictionaries": [{
                    "summary_id": summary_id, "errors": []}],
            })
        combined_fixture, combined_errors = combine_stream_subrequest_evidence(
            subrequest_fixtures, fixture_window, fixture_treatment)
        if combined_errors or combined_fixture.get("row_count") != 56 or \
           combined_fixture.get("row_keys") != expected_chunk_keys(
               fixture_window, fixture_treatment) or \
           list(combined_fixture.get("coverage_values", {})) != canonical_stream_ids or \
           len(combined_fixture.get("seasonal_summary_dictionaries", [])) != 4:
            failures.append("audit010_four_subrequest_combination_fixture")
        incomplete_combination, incomplete_errors = combine_stream_subrequest_evidence(
            subrequest_fixtures[:3], fixture_window, fixture_treatment)
        if incomplete_combination or incomplete_errors != [
                "CHUNK_SUBREQUEST_COUNT_FAILED"]:
            failures.append("audit010_incomplete_subrequest_negative_fixture")
        wrong_stream_fixture = json.loads(json.dumps(subrequest_fixtures))
        wrong_stream_fixture[1]["row_keys"] = wrong_stream_fixture[2]["row_keys"]
        _, wrong_stream_errors = combine_stream_subrequest_evidence(
            wrong_stream_fixture, fixture_window, fixture_treatment)
        if "CHUNK_SUBREQUEST_ROW_KEYS_FAILED:terra_night" not in wrong_stream_errors:
            failures.append("audit010_canonical_stream_order_negative_fixture")
        malformed_subrequest = json.loads(json.dumps(subrequest_fixtures[0]))
        malformed_subrequest["row_count"] = 13
        if "CHUNK_SUBREQUEST_ROW_KEYS_FAILED:terra_day" not in \
                validate_stream_subrequest_evidence(
                    malformed_subrequest, fixture_window, fixture_treatment,
                    STREAMS[0]):
            failures.append("audit010_subrequest_count_negative_fixture")
        adversarial_subrequests: list[tuple[str, dict[str, Any]]] = []
        mutation = json.loads(json.dumps(subrequest_fixtures[0]))
        mutation["seasonal_summary_dictionaries"][0]["undeclared"] = True
        adversarial_subrequests.append(("undeclared", mutation))
        mutation = json.loads(json.dumps(subrequest_fixtures[0]))
        mutation["seasonal_summary_dictionaries"][0].pop("row_count")
        adversarial_subrequests.append(("missing", mutation))
        mutation = json.loads(json.dumps(subrequest_fixtures[0]))
        mutation["summary_runtime_type_dictionaries"][0]["errors"] = [
            "TYPE_MISMATCH:eligible_roi_area_m2"]
        adversarial_subrequests.append(("runtime", mutation))
        mutation = json.loads(json.dumps(subrequest_fixtures[0]))
        mutation["seasonal_summary_dictionaries"][0][
            "eligible_roi_area_m2"] = "wrong_type"
        adversarial_subrequests.append(("type", mutation))
        mutation = json.loads(json.dumps(subrequest_fixtures[0]))
        mutation["seasonal_summary_dictionaries"][0]["collection_id"] = "wrong"
        adversarial_subrequests.append(("provenance", mutation))
        mutation = json.loads(json.dumps(subrequest_fixtures[0]))
        mutation["seasonal_summary_dictionaries"][0]["coverage_missing_count"] = 13
        adversarial_subrequests.append(("formula", mutation))
        for label, mutation in adversarial_subrequests:
            mutation_errors = validate_stream_subrequest_evidence(
                mutation, fixture_window, fixture_treatment, STREAMS[0])
            if not any(error.startswith("CHUNK_SUBREQUEST_SUMMARY_")
                       for error in mutation_errors):
                failures.append(
                    "audit010_immediate_summary_gate_negative_fixture:" + label)
        issued_streams: list[str] = []
        def fail_first_stream(stream: dict[str, Any]) -> dict[str, Any]:
            issued_streams.append(stream["stream_id"])
            return adversarial_subrequests[-1][1]
        admitted, admission_errors, failed_stream = \
            collect_validated_stream_subrequests(
                fixture_window, fixture_treatment, fail_first_stream)
        if admitted or not admission_errors or failed_stream != "terra_day" or \
           issued_streams != ["terra_day"]:
            failures.append("audit010_later_stream_not_issued_fixture")
        chunk_loop_source = runner_source.rsplit(
            "    for index in range(start_chunk - 1, stop):", 1)[1].split(
            "    enforce_session_budget(session_deadline, \"final_aggregation\")", 1)[0]
        if "collect_validated_stream_subrequests(" not in chunk_loop_source or \
           "runner.chunk_stream(" not in chunk_loop_source or \
           chunk_loop_source.index("combine_stream_subrequest_evidence(") > \
           chunk_loop_source.index("make_checkpoint_chunk(") or \
           chunk_loop_source.index("make_checkpoint_chunk(") > \
           chunk_loop_source.index("atomic_save_checkpoint("):
            failures.append("audit010_atomic_logical_chunk_static_fixture")
        wrong_vector_type = dict(authenticated_vector_shape[0])
        wrong_vector_type["outside_source_area_m2"] = "not_numeric"
        if "TYPE_MISMATCH:outside_source_area_m2" not in validate_evaluated_properties(
                normalize_evaluated_float64(wrong_vector_type, manifests["vector"]),
                manifests["vector"]):
            failures.append("authenticated_vector_wrong_type_still_fails_fixture")
        authenticated_summary_shape = {
            name: int(value) if isinstance(value, float) and value.is_integer() else value
            for name, value in overall_zero[0].items()
        }
        normalized_summary_shape = normalize_evaluated_float64(
            authenticated_summary_shape, manifests["coverage"])
        if validate_summary_formula(normalized_summary_shape, [0, 0, 0, 0]):
            failures.append("authenticated_summary_integer_zero_normalization_fixture")
        wrong_summary_type = dict(normalized_summary_shape)
        wrong_summary_type["coverage_min"] = "not_numeric"
        if "TYPE_MISMATCH:coverage_min" not in validate_evaluated_properties(
                normalize_evaluated_float64(wrong_summary_type, manifests["coverage"]),
                manifests["coverage"]):
            failures.append("authenticated_summary_wrong_type_still_fails_fixture")
        nullable_distribution_fields = {
            "coverage_mean", "coverage_population_sd", "coverage_min",
            "coverage_q05_type7", "coverage_q25_type7", "coverage_q50_type7",
            "coverage_max",
        }
        typed_sparse_summary = normalize_evaluated_float64(
            sparse_fixture, manifests["coverage"])
        authenticated_empty_summary = {
            name: value for name, value in typed_sparse_summary.items()
            if name not in nullable_distribution_fields
        }
        if validate_evaluated_properties(
                authenticated_empty_summary, manifests["coverage"]):
            failures.append("authenticated_sparse_empty_summary_fixture")
        present_bad_empty_summary = dict(authenticated_empty_summary)
        present_bad_empty_summary["coverage_mean"] = "computed_null"
        if "TYPE_MISMATCH:coverage_mean" not in validate_evaluated_properties(
                present_bad_empty_summary, manifests["coverage"]):
            failures.append("authenticated_sparse_present_wrong_type_negative_fixture")
        summary_source = runner_source.rsplit(
            "    def summary", 1)[1].split("    def vector", 1)[0]
        summary_base_source = summary_source.split(
            "        sparse_summary =", 1)[0]
        if any(f'"{name}":' in summary_base_source
               for name in nullable_distribution_fields) or \
           "ee.Algorithms.If(n.gt(0), populated_summary" not in summary_source:
            failures.append("summary_sparse_branch_construction_static_fixture")
        digest_summaries: list[dict[str, Any]] = []
        window_seasons = {window["window_id"]: window["season"]
                          for window in WINDOWS}
        treatment_distances = {treatment["erosion_id"]: treatment["distance_m"]
                               for treatment in TREATMENTS}
        for summary_id in expected_final_summary_ids():
            window_id, stream_id, erosion_id = summary_id.split("__")
            digest_summaries.append({
                "summary_id": summary_id,
                "window_id": window_id,
                "season": ("all_selected_seasons" if window_id == "all_windows_2024"
                           else window_seasons[window_id]),
                "stream_id": stream_id,
                "erosion_id": erosion_id,
                "erosion_distance_m": float(treatment_distances[erosion_id]),
                "expected_date_count": 56 if window_id == "all_windows_2024" else 14,
                "source_image_count_sum": 0,
                "source_present_row_count": 0,
                "no_source_row_count": 56 if window_id == "all_windows_2024" else 14,
                "duplicate_source_row_count": 0,
                "state_accepted_count": 0,
                "state_cloud_count": 0,
                "state_rejected_count": 0,
                "state_no_retrieval_count": 0,
                "state_other_count": 56 if window_id == "all_windows_2024" else 14,
                "eligible_roi_area_m2": 1.0,
                "coverage_observation_count": 0,
                "coverage_missing_count": 56 if window_id == "all_windows_2024" else 14,
                "marker_ge_005_count": 0,
                "marker_ge_025_count": 0,
                "marker_ge_050_count": 0,
                "validation_errors": [],
            })
        digest_result = {
            "row_count": 896,
            "unique_row_key_count": 896,
            "seasonal_summary_count": 64,
            "overall_summary_count": 16,
            "summary_count": 80,
            "unique_summary_id_count": 80,
            "vector_count": 4,
            "failures": [],
            "pass": True,
            "vectors": vector_rows,
            "coverage_summaries": digest_summaries,
        }
        digest = build_final_evidence_digest(digest_result)
        if len(digest["coverage_summaries"]) != 80 or \
           [summary["summary_id"] for summary in digest["coverage_summaries"]] != \
                expected_final_summary_ids() or \
           len(digest["treatment_comparison_index"]) != 4 or \
           any(len(group["seasonal_summary_ids"]) != 16 or
               len(group["overall_summary_ids"]) != 4
               for group in digest["treatment_comparison_index"]) or \
           any(name in summary for summary in digest["coverage_summaries"]
               for name in FINAL_DIGEST_DISTRIBUTION_FIELDS):
            failures.append("final_digest_80_id_order_sparse_fixture")
        if any(set(summary) != set(FINAL_DIGEST_SUMMARY_FIELDS)
               for summary in digest["coverage_summaries"]) or \
           any(set(vector) != (set(FINAL_DIGEST_VECTOR_FIELDS) -
                               ({"weaker_candidate_containment_area_m2"}
                                if index == 0 else set()))
               for index, vector in enumerate(digest["vectors"])):
            failures.append("final_digest_exact_projected_field_identity_fixture")
        populated_digest_input = json.loads(json.dumps(digest_result))
        populated = populated_digest_input["coverage_summaries"][0]
        populated["coverage_observation_count"] = 1
        populated["coverage_missing_count"] = populated["expected_date_count"] - 1
        populated.update({name: 0.0 for name in FINAL_DIGEST_DISTRIBUTION_FIELDS})
        populated_digest = build_final_evidence_digest(populated_digest_input)
        if set(populated_digest["coverage_summaries"][0]) != \
                set(FINAL_DIGEST_SUMMARY_FIELDS).union(
                    FINAL_DIGEST_DISTRIBUTION_FIELDS):
            failures.append("final_digest_populated_field_identity_fixture")
        negative_digest_inputs: list[dict[str, Any]] = []
        too_few = json.loads(json.dumps(digest_result))
        too_few["coverage_summaries"].pop()
        negative_digest_inputs.append(too_few)
        wrong_order = json.loads(json.dumps(digest_result))
        wrong_order["coverage_summaries"][0], wrong_order["coverage_summaries"][1] = \
            wrong_order["coverage_summaries"][1], wrong_order["coverage_summaries"][0]
        negative_digest_inputs.append(wrong_order)
        missing_identity_field = json.loads(json.dumps(digest_result))
        missing_identity_field["coverage_summaries"][0].pop("state_cloud_count")
        negative_digest_inputs.append(missing_identity_field)
        missing_populated_stats = json.loads(json.dumps(digest_result))
        missing_populated_stats["coverage_summaries"][0]["coverage_observation_count"] = 1
        negative_digest_inputs.append(missing_populated_stats)
        explicit_null = json.loads(json.dumps(digest_result))
        explicit_null["coverage_summaries"][0]["coverage_mean"] = None
        negative_digest_inputs.append(explicit_null)
        false_pass = json.loads(json.dumps(digest_result))
        false_pass["row_count"] = 895
        negative_digest_inputs.append(false_pass)
        for malformed in negative_digest_inputs:
            try:
                build_final_evidence_digest(malformed)
                failures.append("final_digest_negative_false_pass_fixture")
            except ValueError:
                pass
        failed_digest_input = json.loads(json.dumps(digest_result))
        failed_digest_input["failures"] = [{"test_id": "fixture_failure"}]
        failed_digest_input["pass"] = False
        failed_digest = build_final_evidence_digest(failed_digest_input)
        if failed_digest["failure_count"] != 1 or \
           failed_digest["gates"]["overall_pass"] or \
           failed_digest["gates"]["no_failures"]:
            failures.append("final_digest_failure_preservation_fixture")
        vector_rows[2]["area_balance_residual_m2"] = 500.0
        if "VECTOR_AREA_BALANCE_FAILED" not in validate_vector_formulas(vector_rows):
            failures.append("strict_vector_balance_negative_fixture")
        try:
            validate_chunk_bounds(1, 17)
            failures.append("raw_end_chunk_out_of_range_fixture")
        except ValueError:
            pass
        if aggregate_acceptance_pass([{"test_id": "strict_failure"}]):
            failures.append("aggregate_false_pass_negative_fixture")
        expected_shape_ids = [f"fixture_{index}" for index in range(4)]
        valid_shape = {
            "seasonal_summary_dictionaries": [
                {"summary_id": identifier, "row_count": 14}
                for identifier in expected_shape_ids],
            "summary_runtime_type_dictionaries": [
                {"summary_id": identifier, "errors": []}
                for identifier in expected_shape_ids],
        }
        extracted, extracted_runtime = extract_four_summary_evidence(
            valid_shape, expected_shape_ids)
        if len(extracted) != 4 or set(extracted_runtime) != set(expected_shape_ids):
            failures.append("summary_evidence_expected_shape_fixture")
        malformed_shapes = [
            {},
            {**valid_shape, "seasonal_summary_dictionaries": valid_shape["seasonal_summary_dictionaries"][:3]},
            {**valid_shape, "summary_runtime_type_dictionaries": [
                {"summary_id": identifier, "errors": "not_a_list"}
                for identifier in expected_shape_ids]},
            {**valid_shape, "summary_runtime_type_dictionaries": [
                {"summary_id": "wrong_" + identifier, "errors": []}
                for identifier in expected_shape_ids]},
        ]
        for malformed in malformed_shapes:
            try:
                extract_four_summary_evidence(malformed, expected_shape_ids)
                failures.append("summary_evidence_malformed_shape_false_pass_fixture")
            except ValueError:
                pass
        valid_runtime_shape = {
            "boolean_type": "Boolean",
            "transform_element_types": ["Float"] * 6,
            "unconverted_numeric_predicate_type": "Long",
        }
        if validate_server_runtime_fixture(valid_runtime_shape):
            failures.append("server_runtime_expected_shape_fixture")
        runtime_negative_shapes = [
            {**valid_runtime_shape, "boolean_type": "Long"},
            {**valid_runtime_shape, "transform_element_types": ["Float"] * 5 + ["Long"]},
            {**valid_runtime_shape, "unconverted_numeric_predicate_type": "Boolean"},
        ]
        if any(not validate_server_runtime_fixture(shape) for shape in runtime_negative_shapes):
            failures.append("server_runtime_negative_shape_false_pass_fixture")
        class FakeEEData:
            def __init__(self) -> None:
                self.deadlines: list[int] = []
                self.retries: list[int] = []
                self.events: list[str] = []
            def setDeadline(self, value: int) -> None:
                self.deadlines.append(value)
                self.events.append("deadline")
            def setMaxRetries(self, value: int) -> None:
                self.retries.append(value)
                self.events.append("retries")
        fake_ee = type("FakeEE", (), {"data": FakeEEData()})()
        request_policy = configure_ee_request_policy(
            fake_ee, DEFAULT_EE_REQUEST_DEADLINE_SECONDS,
            DEFAULT_EE_TRANSPORT_MAX_ATTEMPTS)
        if fake_ee.data.deadlines != [480_000] or \
           fake_ee.data.retries != [0] or \
           fake_ee.data.events != ["retries", "deadline"] or \
           request_policy["max_outer_retries"] != 0 or \
           request_policy["server_deadline_or_ee_exception_retry"] is not False or \
           "projects/value:compute" not in request_policy["http_path"]:
            failures.append("earth_engine_request_policy_configuration_fixture")
        compatibility_source_fixture = {
            "original_gml": {
                "content_type": "text/xml; charset=utf-8",
                "content_type_parsed": {
                    "media_type": "text/xml", "charset": "UTF-8",
                    "parameter_count": 1,
                },
            },
            "topology": {
                "geometry_type": "Polygon",
                "coordinate_tuple_count_including_closure": 11012,
                "geometry_is_valid": True,
                "geometry_is_simple": True,
            },
            "parsed": {
                "shapely_coordinate_order": "easting_northing",
                "axis_order_in_document": "northing_easting",
                "axis_swap_applied": True,
            },
            "coordinate_fields_omitted": [
                "geometry", "bbox_wgs84", "lat", "lon",
                "seven_decimal_self_intersection"],
            "spatial_arrays_included": False,
        }
        audit007_compatibility = checkpoint_compatibility(
            compatibility_source_fixture, "fixture-project", "1.7.37",
            request_policy)
        expected_verifier_sha256 = hashlib.sha256(
            VERIFIER_PATH.read_bytes()).hexdigest()
        if "AUDIT-007" not in audit007_compatibility[
                "approved_versions"]["audit"]["specification"] or \
           audit007_compatibility["verified_source_method"][
               "original_gml_content_type"] != ORIGINAL_GML_CONTENT_TYPE_METHOD or \
           audit007_compatibility["verified_source_method"][
               "verifier_file_sha256"] != expected_verifier_sha256:
            failures.append("audit007_checkpoint_compatibility_binding_fixture")
        base_compatibility_hash = canonical_sha256(audit007_compatibility)
        compatibility_mutations: list[dict[str, Any]] = []
        changed_verifier = json.loads(json.dumps(audit007_compatibility))
        changed_verifier["verified_source_method"]["verifier_file_sha256"] = "0" * 64
        compatibility_mutations.append(changed_verifier)
        changed_method = json.loads(json.dumps(audit007_compatibility))
        changed_method["verified_source_method"]["original_gml_content_type"][
            "allowed_charset"] = "UTF-16"
        compatibility_mutations.append(changed_method)
        for parsed_field, changed_value in (
                ("media_type", "application/xml"),
                ("charset", None), ("parameter_count", 0)):
            changed_parsed = json.loads(json.dumps(audit007_compatibility))
            changed_parsed["verified_source_evidence"]["original_gml"][
                "content_type_parsed"][parsed_field] = changed_value
            compatibility_mutations.append(changed_parsed)
        changed_raw_header = json.loads(json.dumps(audit007_compatibility))
        changed_raw_header["verified_source_evidence"]["original_gml"][
            "content_type"] = "text/xml"
        compatibility_mutations.append(changed_raw_header)
        if any(canonical_sha256(mutation) == base_compatibility_hash
               for mutation in compatibility_mutations):
            failures.append("audit007_checkpoint_compatibility_negative_fixture")
        forbidden_coordinate_sources = [
            {**compatibility_source_fixture,
             "nested": {"bounds_epsg3035": [1.0, 2.0, 3.0, 4.0]}},
            {**compatibility_source_fixture,
             "nested": {"bbox": [1.0, 2.0, 3.0, 4.0]}},
            {**compatibility_source_fixture,
             "nested": {"geometry": {"type": "Point", "values": [1.0, 2.0]}}},
            {**compatibility_source_fixture,
             "nested": {"lat": 46.8, "lon": 17.8}},
            {**compatibility_source_fixture,
             "nested": {"samples": [[17.8, 46.8], [17.9, 46.9]]}},
        ]
        for alias in (
                "latitude", "longitude", "coords", "extent", "envelope",
                "coordinateArray", "coordinate_array", "coordinate-array",
                "coordinate array", "minLatitude", "max_longitude",
                "min-lon", "MAX LON", "geoMetry", "co-ordinate",
                "b_o_u_n_d_s", "xmin", "xmax", "ymin", "ymax",
                "xMin", "xMax", "yMin", "yMax", "minX", "maxX",
                "minY", "maxY", "min-x", "MAX Y", "min_x", "MAX-X",
                "min y", "Max Y", "ｍｉｎＸ", "ＭＡＸＸ", "ｍｉｎＹ", "ＭＡＸＹ"):
            forbidden_coordinate_sources.append({
                **compatibility_source_fixture,
                "nested": {alias: 17.8},
            })
        for forbidden_source in forbidden_coordinate_sources:
            try:
                checkpoint_compatibility(
                    forbidden_source, "fixture-project", "1.7.37",
                    request_policy)
                failures.append("coordinate_free_compatibility_false_pass_fixture")
            except ValueError:
                pass
        allowed_scalar_spatial_source = {
            **compatibility_source_fixture,
            "coordinate_rounding_applied": False,
            "coordinates_persisted": False,
        }
        try:
            checkpoint_compatibility(
                allowed_scalar_spatial_source, "fixture-project", "1.7.37",
                request_policy)
        except ValueError:
            failures.append("coordinate_free_scalar_identity_false_rejection_fixture")
        invalid_allowed_spatial_sources = []
        for key, invalid_value in (
                ("geometry_type", ["Polygon"]),
                ("coordinate_tuple_count_including_closure", 0),
                ("coordinate_tuple_count_including_closure", 1),
                ("coordinate_tuple_count_including_closure", 11011),
                ("coordinate_rounding_applied", True),
                ("coordinates_persisted", True),
                ("shapely_coordinate_order", "northing_easting"),
                ("axis_order_in_document", "easting_northing"),
                ("axis_swap_applied", False),
                ("coordinate_fields_omitted", []),
                ("coordinate_fields_omitted", [
                    "geometry", "bbox_wgs84", "lat", "lon"]),
                ("coordinate_fields_omitted", [
                    "geometry", "bbox_wgs84", "lat", "lon",
                    "seven_decimal_self_intersection", "extent"]),
                ("coordinate_fields_omitted", [
                    "geometry", "bbox_wgs84", "lat", "lon",
                    "seven_decimal_self_intersection", "geometry"]),
                ("coordinate_fields_omitted", ["unexpected_spatial_field"])):
            invalid_allowed_spatial_sources.append({
                **compatibility_source_fixture,
                "nested": {key: invalid_value},
            })
        for invalid_source in invalid_allowed_spatial_sources:
            try:
                checkpoint_compatibility(
                    invalid_source, "fixture-project", "1.7.37",
                    request_policy)
                failures.append("coordinate_free_allowed_scalar_false_pass_fixture")
            except ValueError:
                pass
        for bad_deadline, bad_attempts in (
                (479, 1), (481, 1), (480.0, 1), (480, 0),
                (480, 2), (480, True)):
            try:
                validate_request_policy(bad_deadline, bad_attempts)  # type: ignore[arg-type]
                failures.append("earth_engine_request_policy_bounds_false_pass_fixture")
            except ValueError:
                pass
        FakeConnectionError = type(
            "ConnectionError", (Exception,), {"__module__": "requests.exceptions"})
        FakeReadTimeout = type(
            "ReadTimeout", (Exception,), {"__module__": "requests.exceptions"})
        retry_calls = {"count": 0}
        retry_sleeps: list[int] = []
        retry_events: list[str] = []
        def succeeds_after_transient() -> str:
            retry_calls["count"] += 1
            if retry_calls["count"] < 2:
                raise FakeConnectionError("sensitive transport detail must not print")
            return "ok"
        def fixture_emit(value: str, **_: Any) -> None:
            retry_events.append(value)
        retry_result = bounded_transient_getinfo(
            succeeds_after_transient, "fixture", sleeper=retry_sleeps.append,
            emit=fixture_emit)
        if retry_result != "ok" or retry_calls["count"] != 2 or retry_sleeps != [1] or \
           len(retry_events) != 1 or "sensitive transport detail" in retry_events[0]:
            failures.append("transient_retry_success_fixture")
        timeout_calls = {"count": 0}
        timeout_events: list[str] = []
        def succeeds_after_client_timeout() -> str:
            timeout_calls["count"] += 1
            if timeout_calls["count"] == 1:
                raise FakeReadTimeout("sensitive timeout detail")
            return "timeout_rebuilt_ok"
        if bounded_transient_getinfo(
                succeeds_after_client_timeout, "deadline_fixture",
                max_attempts=2, deadline_seconds=1200, sleeper=lambda _: None,
                emit=lambda value, **_: timeout_events.append(value)) != \
                "timeout_rebuilt_ok" or timeout_calls["count"] != 2 or \
           len(timeout_events) != 5 or \
           not any("PHASE_REQUEST_START" in event for event in timeout_events) or \
           not any("PHASE_REQUEST_COMPLETE" in event for event in timeout_events) or \
           not any("PHASE_REQUEST_TRANSPORT_FAILURE" in event
                   for event in timeout_events) or \
           not any('"failure_class": "client_transport_timeout"' in event
                   for event in timeout_events) or \
           any("sensitive timeout detail" in event for event in timeout_events):
            failures.append("client_timeout_deadline_lifecycle_fixture")
        ceiling_calls = {"count": 0}
        def must_not_start_after_ceiling() -> None:
            ceiling_calls["count"] += 1
        try:
            bounded_transient_getinfo(
                must_not_start_after_ceiling, "chunk_06_fixture",
                max_attempts=1, deadline_seconds=480,
                session_deadline_monotonic=time.monotonic() + 480,
                sleeper=lambda _: None, emit=fixture_emit)
            failures.append("session_ceiling_pre_request_false_pass_fixture")
        except SessionCeilingReached:
            if ceiling_calls["count"] != 0:
                failures.append("session_ceiling_pre_request_false_pass_fixture")
        post_request_calls = {"count": 0}
        post_request_clock = iter([0.0, 0.0, 601.0])
        try:
            bounded_transient_getinfo(
                lambda: post_request_calls.__setitem__(
                    "count", post_request_calls["count"] + 1),
                "chunk_06_fixture", max_attempts=1,
                deadline_seconds=480, session_deadline_monotonic=600.0,
                clock=lambda: next(post_request_clock), sleeper=lambda _: None,
                emit=fixture_emit)
            failures.append("session_ceiling_post_request_false_pass_fixture")
        except SessionCeilingReached:
            if post_request_calls["count"] != 1:
                failures.append("session_ceiling_post_request_false_pass_fixture")
        local_checkpoint_events: list[str] = []
        acceptance_claimed = {"value": False}
        try:
            guarded_local_action(
                lambda: local_checkpoint_events.append("persisted"),
                "checkpoint_save", session_deadline_monotonic=10.0,
                clock=lambda: 10.0)
            failures.append("session_ceiling_pre_local_action_false_pass_fixture")
        except SessionCeilingReached:
            if local_checkpoint_events or acceptance_claimed["value"]:
                failures.append("session_ceiling_pre_local_action_false_pass_fixture")
        post_local_clock = iter([0.0, 11.0])
        try:
            guarded_local_action(
                lambda: local_checkpoint_events.append("persisted"),
                "checkpoint_save", session_deadline_monotonic=10.0,
                clock=lambda: next(post_local_clock))
            failures.append("session_ceiling_post_local_action_false_pass_fixture")
        except SessionCeilingReached:
            if local_checkpoint_events != ["persisted"] or \
               acceptance_claimed["value"]:
                failures.append("session_ceiling_post_local_action_false_pass_fixture")
        nontransient_calls = {"count": 0}
        def nontransient() -> None:
            nontransient_calls["count"] += 1
            raise ValueError("scientific or response-shape failure")
        try:
            bounded_transient_getinfo(nontransient, "fixture", sleeper=lambda _: None,
                                      emit=fixture_emit)
            failures.append("nontransient_not_retried_fixture")
        except ValueError:
            if nontransient_calls["count"] != 1:
                failures.append("nontransient_not_retried_fixture")
        exhausted_calls = {"count": 0}
        def always_transient() -> None:
            exhausted_calls["count"] += 1
            raise FakeConnectionError("sensitive exhausted detail")
        exhausted_sleeps: list[int] = []
        try:
            bounded_transient_getinfo(always_transient, "fixture_exhaustion",
                                      sleeper=exhausted_sleeps.append,
                                      emit=fixture_emit)
            failures.append("transient_retry_exhaustion_fixture")
        except TransientNetworkRetriesExhausted as exc:
            if exhausted_calls["count"] != 3 or exhausted_sleeps != [1, 2] or \
               exc.args != ("TRANSIENT_NETWORK_RETRIES_EXHAUSTED",):
                failures.append("transient_retry_exhaustion_fixture")
        FakeEEException = type(
            "EEException", (Exception,), {"__module__": "ee.ee_exception"})
        FakeRefreshError = type(
            "RefreshError", (Exception,), {"__module__": "google.auth.exceptions"})
        FakeGoogleAuthError = type(
            "GoogleAuthError", (Exception,), {"__module__": "google.auth.exceptions"})
        FakeQuotaError = type(
            "ResourceExhausted", (Exception,), {"__module__": "google.api_core.exceptions"})
        FakeHttpError = type(
            "HttpError", (Exception,), {"__module__": "googleapiclient.errors"})
        sensitive_fragments = (
            "47.123456,18.654321", "oauth_token_secret",
            "https://earthengine.googleapis.com/private?token=secret",
            "Image.reduceRegion(secret_expression)",
        )
        redaction_errors = (
            FakeHttpError(" ".join(sensitive_fragments)),
            FakeEEException(" ".join(sensitive_fragments)),
            RuntimeError("WISE verifier failed " + " ".join(sensitive_fragments)),
        )
        for redaction_error in redaction_errors:
            lifecycle: list[str] = []
            try:
                bounded_transient_getinfo(
                    lambda error=redaction_error: (_ for _ in ()).throw(error),
                    "malicious_phase_oauth_token_secret_47.123456,18.654321",
                    max_attempts=2, sleeper=lambda _: None,
                    emit=lambda value, **_: lifecycle.append(value))
                failures.append("exception_redaction_false_pass_fixture")
            except type(redaction_error):
                pass
            top_level = json.dumps({
                "audit_failed_closed": True,
                **redacted_exception_evidence(redaction_error, "top_level")},
                sort_keys=True)
            emitted = "\n".join(lifecycle + [top_level])
            if len(lifecycle) != 1 or "PHASE_REQUEST_FAILURE" not in lifecycle[0] or \
               any(fragment in emitted for fragment in sensitive_fragments) or \
               "malicious_phase" in emitted or "\"error\"" in emitted:
                failures.append("exception_redaction_sensitive_output_fixture")
        runner_output_source = runner_source.rsplit(
            'if __name__ == "__main__":', 1)[1]
        if "str" + "(exc)" in runner_output_source or \
           "type(exc)" + ".__name__" in runner_output_source or \
           '"error"' + ":" in runner_output_source:
            failures.append("top_level_exception_message_static_fixture")
        for label, denied_error in (
                ("ee", FakeEEException("server/scientific failure")),
                ("ee_server_deadline", FakeEEException("Deadline exceeded")),
                ("auth", FakeRefreshError("credential failure")),
                ("generic_auth", FakeGoogleAuthError("generic credential failure")),
                ("quota", FakeQuotaError("quota failure")),
                ("http", FakeHttpError("API HTTP failure"))):
            denied_error.__cause__ = FakeConnectionError("wrapped transport cause")
            denied_calls = {"count": 0}
            def denied_call(error: BaseException = denied_error) -> None:
                denied_calls["count"] += 1
                raise error
            try:
                bounded_transient_getinfo(
                    denied_call, "fixture_" + label, sleeper=lambda _: None,
                    emit=fixture_emit)
                failures.append("denied_error_false_retry_fixture:" + label)
            except type(denied_error):
                if denied_calls["count"] != 1:
                    failures.append("denied_error_false_retry_fixture:" + label)
        for label, denied_cause in (
                ("ee", FakeEEException("server/scientific cause")),
                ("auth", FakeRefreshError("credential cause")),
                ("generic_auth", FakeGoogleAuthError("generic credential cause")),
                ("quota", FakeQuotaError("quota cause")),
                ("http", FakeHttpError("API HTTP cause"))):
            transport_outer = FakeConnectionError("transient outer wrapper")
            transport_outer.__cause__ = denied_cause
            reverse_calls = {"count": 0}
            def reverse_chain_call(error: BaseException = transport_outer) -> None:
                reverse_calls["count"] += 1
                raise error
            try:
                bounded_transient_getinfo(
                    reverse_chain_call, "fixture_reverse_" + label,
                    sleeper=lambda _: None, emit=fixture_emit)
                failures.append("reverse_chain_denial_false_retry_fixture:" + label)
            except FakeConnectionError:
                if reverse_calls["count"] != 1:
                    failures.append("reverse_chain_denial_false_retry_fixture:" + label)
        integration_builds = {"count": 0}
        class RetryOnceGraph:
            def __init__(self, should_fail: bool) -> None:
                self.should_fail = should_fail
            def getInfo(self) -> str:
                if self.should_fail:
                    raise FakeConnectionError("transient integration failure")
                return "rebuilt_ok"
        def build_retry_graph() -> RetryOnceGraph:
            integration_builds["count"] += 1
            return RetryOnceGraph(integration_builds["count"] == 1)
        integration_sleeps: list[int] = []
        if evaluate_authenticated_phase(
                build_retry_graph, "fixture_graph_rebuild",
                sleeper=integration_sleeps.append,
                emit=fixture_emit) != "rebuilt_ok" or \
           integration_builds["count"] != 2 or integration_sleeps != [1]:
            failures.append("transient_integration_graph_rebuild_fixture")
        production_phase_builds: list[str] = []
        class FakeEvaluatedGraph:
            def __init__(self, phase: str) -> None:
                self.phase = phase
            def getInfo(self) -> dict[str, str]:
                return {"phase": self.phase}
        for phase in ("runtime_fixture", "vector_01_EROSION_0000M",
                      "chunk_01_winter_2024__EROSION_0000M"):
            def build_fixture_graph(current_phase: str = phase) -> FakeEvaluatedGraph:
                production_phase_builds.append(current_phase)
                return FakeEvaluatedGraph(current_phase)
            phase_result = evaluate_authenticated_phase(
                build_fixture_graph, phase, sleeper=lambda _: None,
                emit=fixture_emit)
            if phase_result != {"phase": phase}:
                failures.append("production_phase_wrapper_fixture:" + phase)
        if production_phase_builds != [
                "runtime_fixture", "vector_01_EROSION_0000M",
                "chunk_01_winter_2024__EROSION_0000M"]:
            failures.append("production_phase_wrapper_coverage_fixture")
        projection_metadata_source = runner_source.rsplit(
            "    def _projection_metadata", 1)[1].split(
            "    def projection_diagnostic_evidence", 1)[0]
        if projection_metadata_source.count("bounded_transient_getinfo(") != 2 or \
           "**self.request_options" not in projection_metadata_source or \
           "canonical_projection_" not in projection_metadata_source or \
           "canonical_reference_id_" not in projection_metadata_source:
            failures.append("canonical_preflight_deadline_wrapper_fixture")
    except Exception as exc:
        failures.append(
            "strict_fixture_exception:" +
            redacted_exception_evidence(exc, "top_level")["exception_class"])
    result = {"self_test": True, "pass": not failures, "failures": failures,
              "expected_rows": 896, "expected_summaries": 80,
              "network_or_authentication_used": False}
    print(json.dumps(result, indent=2))
    return result


def load_verified_source() -> tuple[dict[str, Any], dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("audit003_verifier", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load approved WISE verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.verify()


def coordinate_free_source_evidence(record: dict[str, Any], project: str,
                                    earthengine_version: str,
                                    serializer_recursion: dict[str, Any]) -> dict[str, Any]:
    properties = record["properties"]
    original_gml = record["original_gml"]
    original_gml_metrics = {
        key: original_gml["metrics_epsg3035"][key]
        for key in COORDINATE_FREE_METRIC_KEYS
        if key in original_gml["metrics_epsg3035"]
    }
    unrounded_metrics = {
        key: record["unrounded_metrics_epsg3035"][key]
        for key in COORDINATE_FREE_METRIC_KEYS
        if key in record["unrounded_metrics_epsg3035"]
    }
    original_parsed = {
        key: original_gml["parsed"][key]
        for key in COORDINATE_FREE_GML_PARSED_SCALAR_KEYS
        if key in original_gml["parsed"]
    }
    original_identity = original_gml["parsed"].get("identity")
    if not isinstance(original_identity, dict) or any(
            isinstance(value, (dict, list, tuple))
            for value in original_identity.values()):
        raise ValueError("COORDINATE_FREE_GML_IDENTITY_FAILED")
    original_parsed["identity"] = dict(original_identity)
    content_type_parsed = original_gml.get("content_type_parsed")
    if not isinstance(content_type_parsed, dict) or \
       set(content_type_parsed) != {
           "raw_header", "media_type", "charset", "parameter_count"} or \
       content_type_parsed.get("raw_header") != original_gml.get("content_type") or \
       content_type_parsed.get("media_type") != "text/xml" or \
       content_type_parsed.get("charset") not in {None, "UTF-8"} or \
       content_type_parsed.get("parameter_count") != (
           0 if content_type_parsed.get("charset") is None else 1):
        raise ValueError("AUDIT007_ORIGINAL_GML_CONTENT_TYPE_EVIDENCE_FAILED")
    evidence = {
        "verification_pass": record["verification_pass"],
        "operational_use": record["operational_use"],
        "coordinate_rounding_applied": record["coordinate_rounding_applied"],
        "coordinates_persisted": record["coordinates_persisted"],
        "source_documents_persisted": record["source_documents_persisted"],
        "http": {name: record[name] for name in (
            "requested_url", "final_url", "redirect_count", "status",
            "content_type", "content_encoding")},
        "payload": {name: record[name] for name in (
            "decompressed_bytes", "raw_sha256", "canonical_bytes", "canonical_sha256")},
        "identity": {
            "feature_count": record["feature_count"],
            "source_feature_id": record["source_feature_id"],
            "thematic_id": record["thematic_id"],
            "reporting_year": record["reporting_year"],
            "inspireIdLocalId": properties["inspireIdLocalId"],
            "inspireIdNamespace": properties["inspireIdNamespace"],
            "inspireIdVersionId": properties["inspireIdVersionId"],
            "thematicIdIdentifierScheme": properties["thematicIdIdentifierScheme"],
            "nameTextInternational": properties["nameTextInternational"],
            "nameText": properties["nameText"],
            "nameLanguage": properties["nameLanguage"],
            "countryCode": properties["countryCode"],
            "size_value": record["size_value"], "size_uom": record["size_uom"],
            "meanDepth": properties["meanDepth"], "link": properties["link"],
        },
        "topology": {name: record[name] for name in (
            "geometry_type", "ring_count", "coordinate_tuple_count_including_closure",
            "ring_is_closed", "geometry_is_valid", "geometry_is_simple")},
        "cdr_metadata": record["cdr_metadata"],
        "original_gml": {
            "requested_url": original_gml["requested_url"],
            "final_url": original_gml["final_url"],
            "redirect_count": original_gml["redirect_count"],
            "status": original_gml["status"],
            "content_type": original_gml["content_type"],
            "content_type_parsed": {
                "media_type": content_type_parsed["media_type"],
                "charset": content_type_parsed["charset"],
                "parameter_count": content_type_parsed["parameter_count"],
            },
            "content_encoding": original_gml["content_encoding"],
            "last_modified": original_gml["last_modified"],
            "bytes": original_gml["bytes"],
            "sha256": original_gml["sha256"],
            "parsed": original_parsed,
            "metrics_epsg3035": original_gml_metrics,
        },
        "unrounded_metrics_epsg3035": unrounded_metrics,
        "gml_vs_unrounded_cross_check": record["gml_vs_unrounded_cross_check"],
        "runtime": {
            **record["runtime"],
            "earthengine_api": earthengine_version,
            "google_cloud_project": project,
            "serializer_recursion": serializer_recursion,
        },
        "spatial_arrays_included": False,
        "source_evidence_profile": "coordinate_free_scalar_identity_hash_topology_metrics",
        "oauth_tokens_emitted": False,
    }
    # Validate before the object can be printed or passed to compatibility.
    validate_coordinate_free_compatibility({
        "verified_source_evidence": evidence})
    return evidence


def import_ee() -> Any:
    try:
        import ee  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "earthengine-api==1.7.37 is required; install the pinned requirements first"
        ) from exc
    return ee


def authenticate(project: str, mode: str) -> None:
    ee = import_ee()
    ee.Authenticate(auth_mode=mode)
    ee.Initialize(project=project)
    print(json.dumps({"authentication_complete": True, "project": project,
                      "requested_scope": "Earth Engine client authorization; choose read-only in the Google flow"}))


class AuditRunner:
    def __init__(self, ee: Any, geometry_json: dict[str, Any],
                 source_record: dict[str, Any],
                 request_options: dict[str, Any] | None = None):
        self.ee = ee
        self.source_record = source_record
        self.request_options = dict(request_options or {})
        self.source = ee.Geometry(geometry_json, proj="EPSG:4326", geodesic=True)
        self.run_timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.contexts = {s["stream_id"]: self._projection_metadata(s) for s in STREAMS}
        self.projection_certifications: dict[tuple[str, str], dict[str, Any]] = {}

    def _margin(self) -> Any:
        return self.ee.ErrorMargin(1, "projected")

    def _nbool(self, condition: Any) -> Any:
        """Normalize a server Boolean to confirmed numeric 0/1 for And/Or/Not."""
        return self.ee.Number(self.ee.Algorithms.If(condition, 1, 0))

    def _boolean(self, condition: Any) -> Any:
        """Serialize an output flag as an actual EE Boolean, matching the JS prototype."""
        return self.ee.Algorithms.IsEqual(self._nbool(condition), 1)

    def server_runtime_fixture(self) -> Any:
        ee = self.ee
        affine = ee.List([926.6254331387694, 0, -20015109.354, 0,
                          -926.6254331387694, 10007554.677]).map(
            lambda value: ee.Number(value).toDouble())
        return ee.Dictionary({
            "boolean_type": ee.Algorithms.ObjectType(self._boolean(ee.Number(1))),
            "transform_element_types": affine.map(
                lambda value: ee.Algorithms.ObjectType(value)),
            "unconverted_numeric_predicate_type": ee.Algorithms.ObjectType(
                ee.Number(1).eq(1)),
        })

    def server_runtime_type_errors(self, feature: Any,
                                   manifest: list[dict[str, Any]]) -> Any:
        """Require the authenticated EE runtime types, not JSON-coerced approximations."""
        ee = self.ee
        feature = ee.Feature(feature)
        names = feature.propertyNames()
        errors = ee.List([])
        for field in manifest:
            name, logical = field["name"], field["type"]
            object_type = ee.String(ee.Algorithms.ObjectType(feature.get(name)))
            if logical == "string": ok = object_type.compareTo("String").eq(0)
            elif logical == "boolean": ok = object_type.compareTo("Boolean").eq(0)
            elif logical == "int64": ok = object_type.compareTo("Long").eq(0)
            elif logical == "float64": ok = object_type.compareTo("Float").eq(0)
            else: ok = object_type.compareTo("List").eq(0)
            ok_if_present = ee.Algorithms.If(names.contains(name), ok, field["nullable"])
            errors = ee.List(ee.Algorithms.If(ok_if_present, errors,
                                              errors.add("RUNTIME_TYPE_MISMATCH:" + name)))
            if logical.startswith("list<"):
                values = ee.List(ee.Algorithms.If(names.contains(name), feature.get(name), []))
                types = values.map(lambda value: ee.Algorithms.ObjectType(value))
                expected = "String" if "<string>" in logical else "Long" if "<int64>" in logical else "Float"
                errors = ee.List(ee.Algorithms.If(types.removeAll([expected]).length().eq(0), errors,
                                                  errors.add("RUNTIME_LIST_ELEMENT_TYPE_MISMATCH:" + name)))
        return errors.distinct().sort()

    def _planar(self, geometry: Any) -> Any:
        return geometry.transform(proj=OP_CRS, maxError=self._margin())

    def candidate(self, treatment: dict[str, Any]) -> Any:
        source = self._planar(self.source)
        if treatment["distance_m"] == 0:
            return source
        return source.buffer(distance=-treatment["distance_m"], maxError=self._margin(), proj=OP_CRS)

    def _projection_metadata(self, stream: dict[str, Any]) -> dict[str, Any]:
        ee = self.ee
        def key(image: Any) -> Any:
            image = ee.Image(image)
            return image.set("_audit_order", ee.Number(image.get("system:time_start")).format("%013d").cat("|").cat(ee.String(image.get("system:index"))))
        def build_reference() -> Any:
            return ee.Image(ee.ImageCollection(stream["collection_id"]) \
                .filterBounds(self.source).map(key).sort("_audit_order").first())
        info = bounded_transient_getinfo(
            lambda: build_reference().select(stream["lst"]).projection().getInfo(),
            f"canonical_projection_{stream['stream_id']}",
            **self.request_options)
        reference_id = bounded_transient_getinfo(
            lambda: build_reference().id().getInfo(),
            f"canonical_reference_id_{stream['stream_id']}",
            **self.request_options)
        if not info or not info.get("crs") or len(info.get("transform", [])) != 6:
            raise RuntimeError(f"Invalid projection metadata for {stream['stream_id']}")
        if not isinstance(reference_id, str) or not reference_id:
            raise RuntimeError(f"Invalid reference image ID for {stream['stream_id']}")
        affine = [float(v) for v in info["transform"]]
        if not all(math.isfinite(v) for v in affine):
            raise RuntimeError(f"Non-finite projection affine for {stream['stream_id']}")
        reference = build_reference()
        projection = reference.select(stream["lst"]).projection()
        return {"reference_image_id": reference_id, "crs": info["crs"],
                "transform": affine, "transform_wkt": projection.transform(),
                "nominal_scale_m": projection.nominalScale().toDouble()}

    def projection_diagnostic_evidence(self, date_utc: str,
                                       stream: dict[str, Any]) -> dict[str, Any]:
        """Evaluate one diagnostic with official Projection.getInfo metadata."""
        ee = self.ee
        start = ee.Date(date_utc)
        collection = ee.ImageCollection(stream["collection_id"]) \
            .filterDate(start, start.advance(1, "day")) \
            .sort("system:time_start") \
            .map(lambda image: ee.Image(image).set(
                "_diagnostic_source_image_id", ee.Image(image).id()))
        selection = ee.Dictionary({
            "source_image_count": collection.size().toInt64(),
            "source_image_ids": collection.aggregate_array(
                "_diagnostic_source_image_id"),
            "source_system_time_starts": collection.aggregate_array(
                "system:time_start"),
        }).getInfo()
        if not isinstance(selection, dict) or \
           not isinstance(selection.get("source_image_count"), int) or \
           isinstance(selection.get("source_image_count"), bool) or \
           selection["source_image_count"] != 1 or \
           not isinstance(selection.get("source_image_ids"), list) or \
           len(selection["source_image_ids"]) != 1 or \
           not isinstance(selection["source_image_ids"][0], str) or \
           not selection["source_image_ids"][0] or \
           not isinstance(selection.get("source_system_time_starts"), list) or \
           len(selection["source_system_time_starts"]) != 1 or \
           not isinstance(selection["source_system_time_starts"][0], int) or \
           isinstance(selection["source_system_time_starts"][0], bool):
            raise ValueError("PROJECTION_DIAGNOSTIC_SOURCE_SELECTION_FAILED")
        configured_bands = [stream[key] for key in (
            "lst", "qc", "time", "angle", "clear")]
        image = ee.Image(collection.first())
        context = self.contexts[stream["stream_id"]]
        canonical_affine = [float(value) for value in context["transform"]]
        canonical_reference = context["reference_image_id"]
        if not isinstance(canonical_reference, str) or not canonical_reference:
            raise ValueError("PROJECTION_DIAGNOSTIC_CANONICAL_REFERENCE_FAILED")
        band_projections: dict[str, dict[str, Any]] = {}
        for band in configured_bands:
            projection_info = image.select(band).projection().getInfo()
            if not isinstance(projection_info, dict) or \
               not isinstance(projection_info.get("crs"), str) or \
               not projection_info["crs"] or \
               not isinstance(projection_info.get("transform"), list) or \
               len(projection_info["transform"]) != 6 or \
               not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(value)
                       for value in projection_info["transform"]):
                raise ValueError(
                    "PROJECTION_DIAGNOSTIC_BAND_METADATA_FAILED:" + band)
            band_projections[band] = {
                "crs": projection_info["crs"],
                "affine": [float(value) for value in projection_info["transform"]],
            }
        source_crs = band_projections[stream["lst"]]["crs"]
        source_affine = band_projections[stream["lst"]]["affine"]
        displacement = affine_displacement_evidence(
            canonical_affine, source_affine)
        crs_equal = source_crs == context["crs"]
        affine_equal = source_affine == canonical_affine
        intra_image_bands_exact = all(
            projection["crs"] == source_crs and
            projection["affine"] == source_affine
            for projection in band_projections.values())
        return {
            "date_utc": date_utc,
            "stream_id": stream["stream_id"],
            "collection_id": stream["collection_id"],
            "lst_band": stream["lst"],
            "source_image_count": selection["source_image_count"],
            "source_image_ids": selection["source_image_ids"],
            "source_image_id": selection["source_image_ids"][0],
            "source_system_time_start": selection["source_system_time_starts"][0],
            "canonical_projection_reference_image_id": canonical_reference,
            "canonical_crs": context["crs"],
            "canonical_affine": canonical_affine,
            "source_crs": source_crs,
            "source_affine": source_affine,
            "affine_elementwise_difference": displacement[
                "affine_elementwise_difference"],
            "crs_equal": crs_equal,
            "affine_equal": affine_equal,
            "projection_equal": crs_equal and affine_equal,
            "grid_width_columns": displacement["grid_width_columns"],
            "grid_height_rows": displacement["grid_height_rows"],
            "grid_corner_convention": displacement["grid_corner_convention"],
            "corner_displacements": displacement["corner_displacements"],
            "maximum_induced_displacement_m": displacement[
                "maximum_induced_displacement_m"],
            "maximum_allowed_displacement_m": displacement[
                "maximum_allowed_displacement_m"],
            "affine_numerically_equivalent": displacement[
                "affine_numerically_equivalent"],
            "intra_image_bands_exact": intra_image_bands_exact,
            "projection_acceptance_pass": (
                crs_equal and intra_image_bands_exact and
                displacement["affine_numerically_equivalent"]),
            "band_projections": band_projections,
        }

    def projection_inventory_evidence(self, window: dict[str, Any],
                                      stream: dict[str, Any]) -> dict[str, Any]:
        """Evaluate all source projection metadata for one 14-day stream window."""
        ee = self.ee
        configured_bands = [stream[key] for key in (
            "lst", "qc", "time", "angle", "clear")]
        collection_info = ee.ImageCollection(stream["collection_id"]) \
            .filterDate(window["start"], window["end"]) \
            .sort("system:time_start").select(configured_bands).getInfo()
        if not isinstance(collection_info, dict) or \
           not isinstance(collection_info.get("features"), list):
            raise ValueError("PROJECTION_INVENTORY_COLLECTION_SHAPE_FAILED")
        context = self.contexts[stream["stream_id"]]
        canonical_reference = context["reference_image_id"]
        canonical_affine = [float(value) for value in context["transform"]]
        by_date: dict[str, list[dict[str, Any]]] = {
            date_utc: [] for date_utc in dates(window["start"], window["end"])
        }
        for feature in collection_info["features"]:
            if not isinstance(feature, dict) or not isinstance(feature.get("id"), str) or \
               not isinstance(feature.get("properties"), dict) or \
               not isinstance(feature["properties"].get("system:time_start"), int) or \
               not isinstance(feature["properties"].get("system:index"), str) or \
               not feature["properties"]["system:index"]:
                raise ValueError("PROJECTION_INVENTORY_IMAGE_SHAPE_FAILED")
            timestamp = feature["properties"]["system:time_start"]
            date_utc = dt.datetime.fromtimestamp(
                timestamp / 1000, tz=dt.timezone.utc).date().isoformat()
            if date_utc not in by_date:
                raise ValueError("PROJECTION_INVENTORY_IMAGE_OUTSIDE_WINDOW")
            by_date[date_utc].append(feature)
        records: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for date_utc, features in by_date.items():
            if len(features) != 1:
                records.append({
                    "date_utc": date_utc,
                    "stream_id": stream["stream_id"],
                    "source_image_count": len(features),
                    "source_image_ids": [feature["id"] for feature in features],
                    "projection_not_applicable_reason": (
                        "no_source_image" if not features else "duplicate_source_images"),
                })
                continue
            feature = features[0]
            bands = feature.get("bands")
            if not isinstance(bands, list):
                raise ValueError("PROJECTION_INVENTORY_BANDS_SHAPE_FAILED")
            band_projections: dict[str, dict[str, Any]] = {}
            for band in bands:
                if not isinstance(band, dict) or band.get("id") not in configured_bands or \
                   not isinstance(band.get("crs"), str) or not band["crs"] or \
                   not isinstance(band.get("crs_transform"), list) or \
                   len(band["crs_transform"]) != 6 or \
                   not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                           and math.isfinite(value) for value in band["crs_transform"]):
                    raise ValueError("PROJECTION_INVENTORY_BAND_METADATA_FAILED")
                band_projections[band["id"]] = {
                    "crs": band["crs"],
                    "affine": [float(value) for value in band["crs_transform"]],
                }
            if set(band_projections) != set(configured_bands):
                raise ValueError("PROJECTION_INVENTORY_BAND_SET_FAILED")
            source = band_projections[stream["lst"]]
            displacement = affine_displacement_evidence(
                canonical_affine, source["affine"])
            exact_bands = all(
                value == source for value in band_projections.values())
            crs_equal = source["crs"] == context["crs"]
            accepted = (crs_equal and exact_bands and
                        displacement["affine_numerically_equivalent"])
            record = {
                "date_utc": date_utc,
                "stream_id": stream["stream_id"],
                "source_image_count": 1,
                "source_image_ids": [feature["id"]],
                "source_image_id": feature["id"],
                "source_system_index": feature["properties"]["system:index"],
                "source_system_time_start": feature["properties"]["system:time_start"],
                "canonical_projection_reference_image_id": canonical_reference,
                "canonical_crs": context["crs"],
                "source_crs": source["crs"],
                "crs_equal": crs_equal,
                "band_projections": band_projections,
                "intra_image_bands_exact": exact_bands,
                "projection_acceptance_pass": accepted,
                **displacement,
            }
            records.append(record)
            if not accepted:
                failures.append({
                    "date_utc": date_utc,
                    "stream_id": stream["stream_id"],
                    "source_image_id": feature["id"],
                    "crs_equal": crs_equal,
                    "intra_image_bands_exact": exact_bands,
                    "maximum_induced_displacement_m": displacement[
                        "maximum_induced_displacement_m"],
                    "maximum_allowed_displacement_m": AUDIT_AFFINE_MAX_DISPLACEMENT_M,
                })
        return {
            "window_id": window["window_id"],
            "stream_id": stream["stream_id"],
            "record_count": len(records),
            "records": records,
            "hard_projection_failures": failures,
            "pass": not failures and len(records) == 14,
        }

    def register_projection_inventory(self, evidence: dict[str, Any]) -> None:
        for record in evidence["records"]:
            self.projection_certifications[(
                record["date_utc"], record["stream_id"])] = record

    def _reduce(self, image: Any, reducer: Any, geometry: Any, context: dict[str, Any]) -> Any:
        return image.reduceRegion(reducer=reducer, geometry=geometry, crs=context["crs"],
                                  crsTransform=context["transform"], bestEffort=False,
                                  maxPixels=1_000_000, tileScale=1)

    def _sum_area(self, mask: Any, geometry: Any, context: dict[str, Any], name: str) -> Any:
        ee = self.ee
        image = ee.Image.pixelArea().rename(name).updateMask(mask)
        return ee.Number(ee.Dictionary(self._reduce(image, ee.Reducer.sum(), geometry, context)).get(name, 0)).toDouble()

    def _count(self, mask: Any, geometry: Any, context: dict[str, Any], name: str) -> Any:
        ee = self.ee
        image = ee.Image.constant(1).rename(name).updateMask(mask)
        return ee.Number(ee.Dictionary(self._reduce(image, ee.Reducer.count().unweighted(), geometry, context)).get(name, 0)).toInt64()

    def context_for_candidate(self, stream: dict[str, Any], geometry: Any) -> dict[str, Any]:
        base = dict(self.contexts[stream["stream_id"]])
        base["eligible_roi_area_m2"] = self._sum_area(self.ee.Image.constant(1), geometry, base, "eligible_roi_area_m2")
        base["eligible_pixel_center_count"] = self._count(self.ee.Image.constant(1), geometry, base, "eligible_pixel_center_count")
        return base

    def _validity(self, band: Any, minimum: int, maximum: int) -> Any:
        present = band.mask().unmask(0).gt(0)
        in_range = band.gte(minimum).And(band.lte(maximum)).unmask(0)
        return present.And(in_range).unmask(0).neq(0)

    def _masks(self, image: Any, stream: dict[str, Any]) -> dict[str, Any]:
        ee = self.ee
        lst, qc = image.select(stream["lst"]), image.select(stream["qc"])
        time, angle = image.select(stream["time"]), image.select(stream["angle"])
        q = qc.toUint8()
        decoded = ee.Image.cat([q.bitwiseAnd(3).rename("mandatory_qa"),
                                q.rightShift(2).bitwiseAnd(3).rename("data_quality"),
                                q.rightShift(4).bitwiseAnd(3).rename("emissivity_error"),
                                q.rightShift(6).bitwiseAnd(3).rename("lst_error")]).updateMask(qc.mask())
        E = ee.Image.constant(1).eq(1)
        Q = qc.mask().unmask(0).gt(0)
        mandatory = decoded.select("mandatory_qa").unmask(0)
        produced = E.And(Q).And(mandatory.eq(0).Or(mandatory.eq(1))).And(self._validity(lst, 7500, 65535)).unmask(0)
        accepted = (produced.And(self._validity(time, 0, 240)).And(self._validity(angle, 0, 130))
                    .And(mandatory.eq(0)).And(decoded.select("data_quality").unmask(0).eq(0))
                    .And(decoded.select("emissivity_error").unmask(0).eq(0))
                    .And(decoded.select("lst_error").unmask(0).eq(0)).unmask(0))
        return {"Q": Q, "decoded": decoded, "produced": produced, "accepted": accepted,
                "rejected": produced.And(accepted.Not()).unmask(0),
                "cloud": E.And(Q).And(mandatory.eq(2)).unmask(0),
                "no_retrieval": E.And(Q).And(produced.Not()).And(mandatory.neq(2)).unmask(0),
                "missing_qc": E.And(Q.Not()).unmask(0)}

    def _frequency(self, image: Any, mask: Any, length: int, geometry: Any, context: dict[str, Any]) -> Any:
        ee = self.ee
        reduced = self._reduce(image.rename("v").updateMask(mask), ee.Reducer.frequencyHistogram().unweighted(), geometry, context)
        histogram = ee.Dictionary(ee.Dictionary(reduced).get("v", ee.Dictionary({})))
        return ee.List.sequence(0, length - 1).map(lambda v: ee.Number(histogram.get(ee.Number(v).format("%d"), 0)).toInt64())

    def _area_array(self, component: Any, qc_mask: Any, geometry: Any, context: dict[str, Any]) -> Any:
        ee = self.ee
        return ee.List.sequence(0, 3).map(lambda v: self._sum_area(qc_mask.And(component.eq(ee.Number(v))), geometry, context, "component_area_m2"))

    def _weighted(self, image: Any, mask: Any, area: Any, geometry: Any, context: dict[str, Any], name: str) -> Any:
        ee = self.ee
        numerator = ee.Number(ee.Dictionary(self._reduce(image.multiply(ee.Image.pixelArea()).rename(name).updateMask(mask), ee.Reducer.sum(), geometry, context)).get(name, 0))
        return ee.Algorithms.If(ee.Number(area).gt(0), numerator.divide(area), None)

    def _range(self, image: Any, mask: Any, geometry: Any, context: dict[str, Any], name: str) -> tuple[Any, Any]:
        reduced = self.ee.Dictionary(self._reduce(image.rename(name).updateMask(mask), self.ee.Reducer.minMax(), geometry, context))
        return reduced.get(name + "_min"), reduced.get(name + "_max")

    def _base(self, date: str, stream: dict[str, Any], context: dict[str, Any], geometry: Any,
              treatment: dict[str, Any]) -> Any:
        ee = self.ee
        output_affine = ee.List(context["transform"]).map(
            lambda value: ee.Number(value).toDouble())
        p = {"schema_version": PROTO_VERSION["schema"], "rule_version": PROTO_VERSION["rule"],
             "specification_version": VERSION["specification"], "implementation_version_or_hash": VERSION["implementation"],
             "run_timestamp_utc": self.run_timestamp, "date_utc": date, "stream_id": stream["stream_id"],
             "platform": stream["platform"], "phase": stream["phase"], "collection_id": stream["collection_id"],
             "lst_band": stream["lst"], "qc_band": stream["qc"], "view_time_band": stream["time"],
             "view_angle_band": stream["angle"], "clear_coverage_band": stream["clear"],
             "projection_reference_image_id": context["reference_image_id"], "source_image_count": ee.Number(0).toInt64(),
             "source_image_ids_if_duplicate": ee.List([]),
             "geometry_id": "wise_wfd_v1_9_huaih049_2022_unrounded__" + treatment["suffix"],
             "geometry_status": "candidate_whole_lake_boundary_sensitivity_only_not_approved",
             "geometry_source_citation": SOURCE_CITATION, "geometry_coordinate_normalization_note": COORDINATE_NOTE,
             "geometry_area_m2": geometry.area(maxError=self._margin(), proj=OP_CRS).toDouble(),
             "source_crs": context["crs"], "source_crs_transform": output_affine,
             "nominal_scale_m": context["nominal_scale_m"], "reducer_scale_or_transform": output_affine,
             "best_effort": False, "resampling_policy": "none_exact_native_crs_transform",
             "eligible_roi_area_m2": context["eligible_roi_area_m2"], "provisional_eligible_water_area_m2": context["eligible_roi_area_m2"],
             "water_area_semantics": "candidate_geometry_proxy_not_approved_water_mask", "provider_numeric_range_only": True,
             "view_time_basis": "local_solar_hour", "clear_coverage_semantics": "scaled_unitless_uninterpreted",
             "histogram_serialization_version": PROTO_VERSION["histogram"], "row_state": "NO_SOURCE_IMAGE",
             "state_reason": "No source image in the one-day half-open UTC interval.", "validation_errors": ee.List([]),
             "validation_warnings": ee.List(["Provider numeric ranges only; no physical-plausibility temperature threshold is applied.",
                                             "View time is per-pixel local solar hour; no local observation datetime or rollover is constructed.",
                                             AUDIT_WARNING]).sort(),
             "notes": AUDIT_NOTE}
        return ee.Feature(None, p)

    def _process(self, image: Any, base: Any, stream: dict[str, Any], context: dict[str, Any],
                 geometry: Any, projection_certification: dict[str, Any]) -> Any:
        ee = self.ee
        source_projection = image.select(stream["lst"]).projection()
        crs_matches = ee.Algorithms.IsEqual(source_projection.crs(), context["crs"])
        # ImageCollection.getInfo() exposes a catalog-qualified feature ``id``,
        # while the computed image graph's stable collection identity is its
        # ``system:index``.  Certification therefore carries both for evidence,
        # but the processing handoff compares the exact system:index value.
        certified_system_index = certified_source_system_index(
            projection_certification)
        source_identity_matches = ee.Algorithms.IsEqual(
            image.get("system:index"), certified_system_index)
        projection_matches = ee.Algorithms.If(
            crs_matches,
            ee.Algorithms.If(
                projection_certification.get("projection_acceptance_pass", False),
                source_identity_matches, False),
            False)
        masks = self._masks(image, stream)
        area_names = [("qc_observed_area_m2", masks["Q"]), ("produced_lst_area_m2", masks["produced"]),
                      ("accepted_area_m2", masks["accepted"]), ("produced_rejected_area_m2", masks["rejected"]),
                      ("cloud_area_m2", masks["cloud"]), ("noncloud_no_retrieval_area_m2", masks["no_retrieval"]),
                      ("missing_qc_area_m2", masks["missing_qc"])]
        area_image = ee.Image.cat([ee.Image.pixelArea().rename(n).updateMask(m) for n, m in area_names])
        reduced = ee.Dictionary(self._reduce(area_image, ee.Reducer.sum(), geometry, context))
        areas = {n: ee.Number(reduced.get(n, 0)).toDouble() for n, _ in area_names}
        eligible, accepted = ee.Number(context["eligible_roi_area_m2"]), areas["accepted_area_m2"]
        partition_sum = accepted.add(areas["produced_rejected_area_m2"]).add(areas["cloud_area_m2"]).add(areas["noncloud_no_retrieval_area_m2"]).add(areas["missing_qc_area_m2"])
        residual, tolerance = eligible.subtract(partition_sum), eligible.multiply(1e-6).max(1.0)
        raw_lst, raw_time, raw_angle, raw_clear = (image.select(stream[k]) for k in ("lst", "time", "angle", "clear"))
        temp_k, temp_c = raw_lst.multiply(0.02), raw_lst.multiply(0.02).subtract(273.15)
        view_time, view_angle, clear_scaled = raw_time.multiply(0.1), raw_angle.subtract(65).toDouble(), raw_clear.multiply(0.0005)
        accepted_mask = masks["accepted"]
        clear_mask = accepted_mask.And(self._validity(raw_clear, 1, 65535))
        values: dict[str, Any] = dict(areas)
        values.update({"accepted_roi_fraction": accepted.divide(eligible), "provisional_valid_water_area_m2": accepted,
                       "provisional_valid_water_coverage_fraction": accepted.divide(eligible),
                       "unclassified_area_m2": residual.max(0), "overlap_excess_area_m2": residual.multiply(-1).max(0),
                       "area_partition_sum_m2": partition_sum, "area_partition_residual_m2": residual,
                       "area_partition_absolute_error_m2": residual.abs(), "area_partition_relative_error": residual.abs().divide(eligible),
                       "area_partition_tolerance_m2": tolerance,
                       "area_partition_pass": self._boolean(residual.abs().lte(tolerance)),
                       "eligible_pixel_center_count": context["eligible_pixel_center_count"]})
        count_masks = [("qc_observed_pixel_center_count", masks["Q"]), ("produced_lst_pixel_center_count", masks["produced"]),
                       ("accepted_pixel_center_count", accepted_mask), ("produced_rejected_pixel_center_count", masks["rejected"]),
                       ("cloud_pixel_center_count", masks["cloud"]), ("noncloud_no_retrieval_pixel_center_count", masks["no_retrieval"]),
                       ("missing_qc_pixel_center_count", masks["missing_qc"])]
        values.update({n: self._count(m, geometry, context, n) for n, m in count_masks})
        for prefix, band in [("temperature_k", temp_k), ("temperature_c", temp_c),
                             ("view_time_local_solar_hour", view_time), ("view_angle_degrees", view_angle)]:
            mn, mx = self._range(band, accepted_mask, geometry, context, prefix)
            values[prefix + "_area_weighted_mean" if prefix.startswith("view_") else prefix + "_mean"] = self._weighted(band, accepted_mask, accepted, geometry, context, prefix + "_weighted")
            values[prefix + "_min"], values[prefix + "_max"] = mn, mx
        clear_area = self._sum_area(clear_mask, geometry, context, "clear_area")
        clear_min, clear_max = self._range(clear_scaled, clear_mask, geometry, context, "clear_coverage_scaled")
        values.update({"clear_coverage_scaled_mean": self._weighted(clear_scaled, clear_mask, clear_area, geometry, context, "clear_weighted"),
                       "clear_coverage_scaled_min": clear_min, "clear_coverage_scaled_max": clear_max})
        decoded = masks["decoded"]
        values["qc_byte_histogram"] = self._frequency(image.select(stream["qc"]).toUint8(), masks["Q"], 256, geometry, context)
        for out, component in [("mandatory_qa", "mandatory_qa"), ("data_quality", "data_quality"),
                               ("emissivity_error", "emissivity_error"), ("lst_error", "lst_error")]:
            comp = decoded.select(component)
            values[out + "_count_histogram"] = self._frequency(comp, masks["Q"], 4, geometry, context)
            values[out + "_area_histogram_m2"] = self._area_array(comp, masks["Q"], geometry, context)
        qc_count = values["qc_observed_pixel_center_count"]
        def list_sum(value: Any) -> Any:
            return ee.Number(ee.List(value).reduce(ee.Reducer.sum()))
        count_histograms_pass = self._nbool(list_sum(values["qc_byte_histogram"]).eq(qc_count))
        area_histograms_pass = ee.Number(1)
        for out in ("mandatory_qa", "data_quality", "emissivity_error", "lst_error"):
            count_histograms_pass = count_histograms_pass.And(
                self._nbool(list_sum(values[out + "_count_histogram"]).eq(qc_count)))
            area_histograms_pass = area_histograms_pass.And(
                self._nbool(list_sum(values[out + "_area_histogram_m2"])
                .subtract(areas["qc_observed_area_m2"]).abs().lte(tolerance)))
        produced_identity_pass = areas["produced_lst_area_m2"].subtract(
            accepted.add(areas["produced_rejected_area_m2"])).abs().lte(tolerance)
        flags = [areas["cloud_area_m2"].gt(0), areas["produced_rejected_area_m2"].gt(0),
                 areas["noncloud_no_retrieval_area_m2"].gt(0), areas["missing_qc_area_m2"].gt(0)]
        failure_count = ee.Number(0)
        for flag in flags:
            failure_count = failure_count.add(ee.Number(ee.Algorithms.If(flag, 1, 0)))
        errors = ee.List([])
        errors = ee.List(ee.Algorithms.If(eligible.lte(0), errors.add("NONPOSITIVE_ELIGIBLE_ROI_AREA"), errors))
        errors = ee.List(ee.Algorithms.If(residual.abs().lte(tolerance), errors,
                                          errors.add("AREA_PARTITION_RESIDUAL_EXCEEDS_TOLERANCE")))
        errors = ee.List(ee.Algorithms.If(produced_identity_pass, errors,
                                          errors.add("PRODUCED_LST_AREA_INCONSISTENT")))
        errors = ee.List(ee.Algorithms.If(count_histograms_pass, errors,
                                          errors.add("COUNT_HISTOGRAM_SUM_MISMATCH")))
        errors = ee.List(ee.Algorithms.If(area_histograms_pass, errors,
                                          errors.add("AREA_HISTOGRAM_SUM_MISMATCH")))
        values.update({"has_cloud": self._boolean(flags[0]),
                       "has_rejected_qa": self._boolean(flags[1]),
                       "has_noncloud_no_retrieval": self._boolean(flags[2]),
                       "has_missing_qc": self._boolean(flags[3]),
                       "failure_reason_count": failure_count.toInt64(),
                       "has_mixed_failure_reasons": self._boolean(failure_count.gte(2)),
                       "validation_errors": errors.distinct().sort()})
        state = ee.String(ee.Algorithms.If(accepted.gt(0), "ACCEPTED",
                  ee.Algorithms.If(areas["produced_lst_area_m2"].gt(0), "SOURCE_PRESENT_REJECTED_QA",
                  ee.Algorithms.If(self._nbool(areas["cloud_area_m2"].gt(0)).And(
                      self._nbool(areas["noncloud_no_retrieval_area_m2"].eq(0))),
                      "SOURCE_PRESENT_CLOUD", "SOURCE_PRESENT_NO_RETRIEVAL"))))
        reasons = ee.Dictionary({"ACCEPTED": "Accepted area is greater than zero.",
                                 "SOURCE_PRESENT_REJECTED_QA": "No accepted area; produced LST area is present.",
                                 "SOURCE_PRESENT_CLOUD": "No accepted or produced LST area; cloud is the sole observed retrieval failure.",
                                 "SOURCE_PRESENT_NO_RETRIEVAL": "Source exists but no accepted retrieval; remaining failure conditions apply."})
        values.update({"row_state": state, "state_reason": reasons.get(state)})
        valid_feature = ee.Feature(base).set(values)
        mismatch_notes = ee.String(
            "Canonical CRS/affine provenance retained. Mismatched source transform WKT: "
        ).cat(source_projection.transform())
        branch_projection_provenance = {
            "_sparse_expected_projection_reference_image_id": context["reference_image_id"],
            "_sparse_expected_source_crs": context["crs"],
            "_sparse_expected_source_crs_transform": ee.List(context["transform"]).map(
                lambda value: ee.Number(value).toDouble()),
            "_sparse_expected_reducer_scale_or_transform": ee.List(context["transform"]).map(
                lambda value: ee.Number(value).toDouble()),
        }
        mismatch = ee.Feature(base).set({
            "row_state": "SOURCE_PRESENT_NO_RETRIEVAL",
            "state_reason": "Source projection differs from the canonical stream projection; diagnostics were not computed.",
            "null_reason": "projection_mismatch",
            "validation_errors": ["SOURCE_PROJECTION_MISMATCH"],
            "notes": mismatch_notes,
            "_sparse_expected_notes": mismatch_notes,
        }).set(branch_projection_provenance)
        nonpositive = ee.Feature(base).set({
            "row_state": "SOURCE_PRESENT_NO_RETRIEVAL",
            "state_reason": "Eligible ROI area is nonpositive; diagnostics were not computed.",
            "null_reason": "nonpositive_eligible_roi_area",
            "validation_errors": ["NONPOSITIVE_ELIGIBLE_ROI_AREA"],
            "_sparse_expected_notes": AUDIT_NOTE,
        }).set(branch_projection_provenance)
        return ee.Feature(ee.Algorithms.If(
            projection_matches,
            ee.Algorithms.If(eligible.gt(0), valid_feature, nonpositive),
            mismatch,
        ))

    def row(self, date: str, stream: dict[str, Any], treatment: dict[str, Any], geometry: Any, context: dict[str, Any]) -> Any:
        ee = self.ee
        base = self._base(date, stream, context, geometry, treatment).set({
            "erosion_id": treatment["erosion_id"], "erosion_distance_m": treatment["distance_m"]})
        start = ee.Date(date)
        collection = ee.ImageCollection(stream["collection_id"]).filterDate(start, start.advance(1, "day")).sort("system:time_start")
        count = collection.size()
        bands = [stream[k] for k in ("lst", "qc", "time", "angle", "clear")]
        fallback = ee.Image.constant([0] * 5).rename(bands).updateMask(ee.Image.constant(0))
        image = ee.Image(ee.Algorithms.If(count.eq(1), collection.first(), fallback))
        certification = self.projection_certifications.get((date, stream["stream_id"]))
        if certification is None:
            raise RuntimeError(
                "MISSING_PROJECTION_CERTIFICATION:" + date + ":" + stream["stream_id"])
        processed = self._process(image, base, stream, context, geometry,
                                  certification).set({"source_image_count": ee.Number(1).toInt64(),
                                                                              "source_image_id": image.id(),
                                                                              "source_system_time_start": ee.Number(image.get("system:time_start")).toInt64()})
        no_source = base.set({"source_image_count": ee.Number(0).toInt64(), "null_reason": "no_source_image"})
        duplicate = base.set({"source_image_count": count.toInt64(),
                              "source_image_ids_if_duplicate": collection.aggregate_array("system:index").sort(),
                              "row_state": "DUPLICATE_SOURCE_IMAGES", "state_reason": "More than one source image exists for the date-stream key; no mosaic or scientific result was produced.",
                              "null_reason": "duplicate_source_images", "validation_errors": ["DUPLICATE_SOURCE_IMAGES"]})
        return ee.Feature(ee.Algorithms.If(count.eq(0), no_source, ee.Algorithms.If(count.eq(1), processed, duplicate)))

    def chunk(self, window: dict[str, Any], treatment: dict[str, Any]) -> Any:
        ee = self.ee
        geometry = self.candidate(treatment)
        contexts = {s["stream_id"]: self.context_for_candidate(s, geometry) for s in STREAMS}
        rows = ee.FeatureCollection([
            self.row(d, s, treatment, geometry, contexts[s["stream_id"]]).set({
                "audit_window_id": window["window_id"],
                "audit_season": window["season"],
                "erosion_id": treatment["erosion_id"],
                "erosion_distance_m": treatment["distance_m"],
            })
            for d in dates(window["start"], window["end"]) for s in STREAMS
        ])
        keyed = rows.map(lambda f: ee.Feature(f).set("_audit_key", ee.String(ee.Feature(f).get("date_utc")).cat("|").cat(ee.String(ee.Feature(f).get("stream_id"))).cat("|").cat(ee.String(ee.Feature(f).get("erosion_id"))))
                         .set("_error_count", ee.List(ee.Feature(f).get("validation_errors")).length()))
        return keyed.map(self._strict_row_validation)

    def chunk_stream(self, window: dict[str, Any], treatment: dict[str, Any],
                     stream: dict[str, Any]) -> Any:
        """Build the unchanged 14 rows for exactly one canonical stream."""
        ee = self.ee
        geometry = self.candidate(treatment)
        context = self.context_for_candidate(stream, geometry)
        rows = ee.FeatureCollection([
            self.row(date_utc, stream, treatment, geometry, context).set({
                "audit_window_id": window["window_id"],
                "audit_season": window["season"],
                "erosion_id": treatment["erosion_id"],
                "erosion_distance_m": treatment["distance_m"],
            })
            for date_utc in dates(window["start"], window["end"])
        ])
        keyed = rows.map(lambda feature: ee.Feature(feature).set(
            "_audit_key", ee.String(ee.Feature(feature).get("date_utc"))
            .cat("|").cat(ee.String(ee.Feature(feature).get("stream_id")))
            .cat("|").cat(ee.String(ee.Feature(feature).get("erosion_id"))))
            .set("_error_count", ee.List(
                ee.Feature(feature).get("validation_errors")).length()))
        return keyed.map(self._strict_row_validation)

    def _strict_row_validation(self, feature: Any) -> Any:
        """Attach comprehensive logical-schema, provenance, and identity failures."""
        ee = self.ee
        feature = ee.Feature(feature)
        names = feature.propertyNames().remove("system:index")
        def safe_number(name: str, default: float | int = 0) -> Any:
            # Graph-safety only: manifest presence/type gates below remain
            # authoritative and still reject absent required/single-source data.
            return ee.Number(ee.Algorithms.If(
                names.contains(name), feature.get(name), default))
        def safe_list(name: str) -> Any:
            return ee.List(ee.Algorithms.If(
                names.contains(name), feature.get(name), []))
        manifest = load_authoritative_manifests()["row"]
        audit_fields = ["audit_window_id", "audit_season", "erosion_id", "erosion_distance_m",
                        "_audit_key", "_error_count"] + SPARSE_BRANCH_INTERNAL_PROVENANCE_FIELDS
        declared = ee.List([f["name"] for f in manifest] + audit_fields)
        required = ee.List([f["name"] for f in manifest if not f["nullable"]] + audit_fields[:4])
        errors = ee.List([])
        errors = ee.List(ee.Algorithms.If(names.removeAll(declared).length().eq(0), errors,
                                          errors.add("ROW_UNDECLARED_FIELDS")))
        errors = ee.List(ee.Algorithms.If(required.removeAll(names).length().eq(0), errors,
                                          errors.add("ROW_MISSING_REQUIRED_FIELDS")))
        for field in manifest:
            name, logical = field["name"], field["type"]
            object_type = ee.String(ee.Algorithms.ObjectType(feature.get(name)))
            if logical == "string": type_ok = object_type.compareTo("String").eq(0)
            elif logical == "boolean": type_ok = object_type.compareTo("Boolean").eq(0)
            elif logical == "int64": type_ok = object_type.compareTo("Long").eq(0)
            elif logical == "float64": type_ok = object_type.compareTo("Float").eq(0)
            elif logical.startswith("list<"): type_ok = object_type.compareTo("List").eq(0)
            else: type_ok = ee.Number(0).eq(1)
            present_type_ok = ee.Algorithms.If(names.contains(name), type_ok, True)
            errors = ee.List(ee.Algorithms.If(present_type_ok, errors,
                                              errors.add("ROW_TYPE_MISMATCH:" + name)))
            fixed = re.search(r"\[(\d+)\]$", logical)
            if fixed:
                length_ok = ee.Algorithms.If(names.contains(name),
                    safe_list(name).length().eq(int(fixed.group(1))), True)
                errors = ee.List(ee.Algorithms.If(length_ok, errors,
                                                  errors.add("ROW_LIST_LENGTH_MISMATCH:" + name)))
            if logical.startswith("list<"):
                element_kind = logical.split("<", 1)[1].split(">", 1)[0]
                present_list = safe_list(name)
                element_types = present_list.map(lambda item: ee.Algorithms.ObjectType(item))
                if element_kind == "string":
                    bad_elements = element_types.removeAll(["String"]).length()
                elif element_kind == "int64":
                    bad_elements = element_types.removeAll(["Long"]).length()
                else:
                    bad_elements = element_types.removeAll(["Float"]).length()
                errors = ee.List(ee.Algorithms.If(bad_elements.eq(0), errors,
                                                  errors.add("ROW_LIST_ELEMENT_TYPE_MISMATCH:" + name)))
                sentinel_free = present_list.removeAll([-9999, -999, "NA", "N/A", "NULL", "null"]).length().eq(present_list.length())
                errors = ee.List(ee.Algorithms.If(sentinel_free, errors,
                                                  errors.add("ROW_FORBIDDEN_SENTINEL:" + name)))
            if logical in ("string", "int64", "float64"):
                sentinel = ee.List([-9999, -999, "NA", "N/A", "NULL", "null"])
                sentinel_ok = ee.Algorithms.If(names.contains(name),
                                                ee.Algorithms.If(sentinel.contains(feature.get(name)), False, True), True)
                errors = ee.List(ee.Algorithms.If(sentinel_ok, errors,
                                                  errors.add("ROW_FORBIDDEN_SENTINEL:" + name)))
        exact = {
            "specification_version": VERSION["specification"],
            "implementation_version_or_hash": VERSION["implementation"],
            "geometry_status": "candidate_whole_lake_boundary_sensitivity_only_not_approved",
            "geometry_source_citation": SOURCE_CITATION,
            "geometry_coordinate_normalization_note": COORDINATE_NOTE,
            "water_area_semantics": "candidate_geometry_proxy_not_approved_water_mask",
        }
        for name, expected in exact.items():
            errors = ee.List(ee.Algorithms.If(ee.Algorithms.IsEqual(feature.get(name), expected), errors,
                                              errors.add("ROW_REQUIRED_PROVENANCE_FAILED:" + name)))
        treatment_lookup = ee.Dictionary({t["erosion_id"]: t["distance_m"] for t in TREATMENTS})
        suffix_lookup = ee.Dictionary({t["erosion_id"]:
            "wise_wfd_v1_9_huaih049_2022_unrounded__" + t["suffix"] for t in TREATMENTS})
        erosion_id = ee.String(feature.get("erosion_id"))
        erosion_ok = ee.Algorithms.IsEqual(feature.get("erosion_distance_m"), treatment_lookup.get(erosion_id))
        geometry_id_ok = ee.Algorithms.IsEqual(feature.get("geometry_id"), suffix_lookup.get(erosion_id))
        errors = ee.List(ee.Algorithms.If(erosion_ok, errors, errors.add("ROW_EROSION_DISTANCE_IDENTITY_FAILED")))
        errors = ee.List(ee.Algorithms.If(geometry_id_ok, errors, errors.add("ROW_GEOMETRY_IDENTITY_FAILED")))
        window_lookup = ee.Dictionary({w["window_id"]: w["season"] for w in WINDOWS})
        window_id = ee.String(feature.get("audit_window_id"))
        window_ok = ee.Algorithms.IsEqual(feature.get("audit_season"), window_lookup.get(window_id))
        errors = ee.List(ee.Algorithms.If(window_ok, errors,
                                          errors.add("ROW_WINDOW_SEASON_IDENTITY_FAILED")))
        warnings = safe_list("validation_warnings")
        warning_ok = ee.Algorithms.If(warnings.contains(AUDIT_WARNING),
                                      ee.Algorithms.If(warnings.contains(PROTOTYPE_WATER_WARNING), False, True),
                                      False)
        errors = ee.List(ee.Algorithms.If(warning_ok, errors,
                                          errors.add("ROW_WARNING_PROVENANCE_FAILED")))
        source_count = safe_number("source_image_count")
        single = source_count.eq(1)
        eligible = safe_number("eligible_roi_area_m2")
        processing_errors = safe_list("validation_errors")
        formula_applicable = self._nbool(single).And(
            self._nbool(processing_errors.length().eq(0))).And(
            self._nbool(eligible.gt(0)))
        single_source_required = ee.List(SINGLE_SOURCE_FORMULA_REQUIRED_FIELDS)
        missing_single_source_fields = single_source_required.removeAll(names)
        missing_single_source_errors = missing_single_source_fields.map(
            lambda name: ee.String(
                "ROW_SINGLE_SOURCE_FORMULA_FIELD_MISSING:").cat(ee.String(name)))
        errors = ee.List(ee.Algorithms.If(
            formula_applicable,
            errors.cat(missing_single_source_errors),
            errors))
        sparse_branch_user_names = names.removeAll(audit_fields)
        sparse_branch_allowed_names = ee.List(
            [field["name"] for field in manifest if not field["nullable"]] +
            sorted(SPARSE_BRANCH_ALLOWED_NULLABLE_FIELDS))
        sparse_physical_properties_ok = ee.Algorithms.IsEqual(
            sparse_branch_user_names.sort(), sparse_branch_allowed_names.sort())
        sparse_projection_provenance_ok = self._nbool(ee.Algorithms.IsEqual(
            feature.get("notes"), feature.get("_sparse_expected_notes")))
        sparse_projection_provenance_ok = sparse_projection_provenance_ok.And(
            self._nbool(ee.Algorithms.IsEqual(
                feature.get("projection_reference_image_id"),
                feature.get("_sparse_expected_projection_reference_image_id"))))
        sparse_projection_provenance_ok = sparse_projection_provenance_ok.And(
            self._nbool(ee.Algorithms.IsEqual(
                feature.get("source_crs"), feature.get("_sparse_expected_source_crs"))))
        sparse_projection_provenance_ok = sparse_projection_provenance_ok.And(
            self._nbool(ee.Algorithms.IsEqual(
                feature.get("source_crs_transform"),
                feature.get("_sparse_expected_source_crs_transform"))))
        sparse_projection_provenance_ok = sparse_projection_provenance_ok.And(
            self._nbool(ee.Algorithms.IsEqual(
                feature.get("reducer_scale_or_transform"),
                feature.get("_sparse_expected_reducer_scale_or_transform"))))
        sparse_branch_candidate = self._nbool(single).And(
            self._nbool(processing_errors.length().gt(0)))
        errors = ee.List(ee.Algorithms.If(
            sparse_branch_candidate,
            ee.Algorithms.If(sparse_physical_properties_ok, errors,
                             errors.add("ROW_SPARSE_BRANCH_PHYSICAL_PROPERTIES_FAILED")),
            errors))
        errors = ee.List(ee.Algorithms.If(
            sparse_branch_candidate,
            ee.Algorithms.If(sparse_projection_provenance_ok, errors,
                             errors.add("ROW_SPARSE_BRANCH_PROVENANCE_FAILED")),
            errors))
        def sparse_error_branch_ok(null_reason: str, expected: dict[str, str]) -> Any:
            branch_ok = self._nbool(ee.Algorithms.IsEqual(
                feature.get("null_reason"), null_reason))
            branch_ok = branch_ok.And(self._nbool(
                processing_errors.length().eq(1)))
            branch_ok = branch_ok.And(self._nbool(
                processing_errors.contains(expected["validation_error"])))
            branch_ok = branch_ok.And(self._nbool(ee.Algorithms.IsEqual(
                feature.get("row_state"), expected["row_state"])))
            branch_ok = branch_ok.And(self._nbool(ee.Algorithms.IsEqual(
                feature.get("state_reason"), expected["state_reason"])))
            if null_reason == "nonpositive_eligible_roi_area":
                branch_ok = branch_ok.And(self._nbool(eligible.lte(0)))
            return branch_ok
        projection_error_ok = sparse_error_branch_ok(
            "projection_mismatch",
            SINGLE_SOURCE_SPARSE_ERROR_BRANCHES["projection_mismatch"])
        nonpositive_error_ok = sparse_error_branch_ok(
            "nonpositive_eligible_roi_area",
            SINGLE_SOURCE_SPARSE_ERROR_BRANCHES["nonpositive_eligible_roi_area"])
        sparse_processing_error_ok = projection_error_ok.Or(nonpositive_error_ok)
        notes_identity_ok = ee.Algorithms.If(
            projection_error_ok, True,
            ee.Algorithms.IsEqual(feature.get("notes"), AUDIT_NOTE))
        errors = ee.List(ee.Algorithms.If(
            notes_identity_ok, errors,
            errors.add("ROW_REQUIRED_PROVENANCE_FAILED:notes")))
        single_branch_ok = formula_applicable.Or(sparse_processing_error_ok)
        errors = ee.List(ee.Algorithms.If(
            ee.Algorithms.If(single, single_branch_ok, True), errors,
            errors.add("ROW_SINGLE_SOURCE_PROCESSING_ERROR_IDENTITY_FAILED")))
        accepted = safe_number("accepted_area_m2")
        rejected = safe_number("produced_rejected_area_m2")
        produced = safe_number("produced_lst_area_m2")
        cloud = safe_number("cloud_area_m2")
        no_retrieval = safe_number("noncloud_no_retrieval_area_m2")
        fraction_ok = ee.Algorithms.If(formula_applicable,
            safe_number("accepted_roi_fraction").subtract(accepted.divide(eligible)).abs().lte(1e-12), True)
        errors = ee.List(ee.Algorithms.If(fraction_ok, errors,
                                          errors.add("ROW_COVERAGE_FORMULA_FAILED")))
        alias_ok = ee.Algorithms.If(formula_applicable,
            self._nbool(safe_number("provisional_eligible_water_area_m2").subtract(eligible).abs().lte(1e-12))
            .And(self._nbool(safe_number("provisional_valid_water_area_m2").subtract(accepted).abs().lte(1e-12)))
            .And(self._nbool(safe_number("provisional_valid_water_coverage_fraction")
                 .subtract(accepted.divide(eligible)).abs().lte(1e-12))), True)
        errors = ee.List(ee.Algorithms.If(alias_ok, errors,
                                          errors.add("ROW_AREA_ALIAS_FORMULA_FAILED")))
        produced_tolerance = eligible.multiply(1e-6).max(1)
        produced_ok = ee.Algorithms.If(formula_applicable,
            produced.subtract(accepted.add(rejected)).abs().lte(produced_tolerance), True)
        errors = ee.List(ee.Algorithms.If(produced_ok, errors,
                                          errors.add("ROW_PRODUCED_AREA_IDENTITY_FAILED")))
        produced_count_ok = ee.Algorithms.If(formula_applicable,
            safe_number("produced_lst_pixel_center_count").eq(
                safe_number("accepted_pixel_center_count").add(
                    safe_number("produced_rejected_pixel_center_count"))), True)
        errors = ee.List(ee.Algorithms.If(produced_count_ok, errors,
                                          errors.add("ROW_PRODUCED_COUNT_IDENTITY_FAILED")))
        missing_qc = safe_number("missing_qc_area_m2")
        partition_sum = accepted.add(rejected).add(cloud).add(no_retrieval).add(missing_qc)
        partition_ok = ee.Algorithms.If(formula_applicable,
            self._nbool(safe_number("area_partition_sum_m2").subtract(partition_sum).abs().lte(produced_tolerance))
            .And(self._nbool(safe_number("area_partition_residual_m2").subtract(eligible.subtract(partition_sum)).abs().lte(produced_tolerance))), True)
        errors = ee.List(ee.Algorithms.If(partition_ok, errors,
                                          errors.add("ROW_AREA_PARTITION_IDENTITY_FAILED")))
        expected_residual = eligible.subtract(partition_sum)
        exact_partition_metrics_ok = ee.Algorithms.If(formula_applicable,
            self._nbool(safe_number("area_partition_absolute_error_m2").subtract(expected_residual.abs()).abs().lte(1e-12))
            .And(self._nbool(safe_number("area_partition_relative_error").subtract(expected_residual.abs().divide(eligible)).abs().lte(1e-12)))
            .And(self._nbool(safe_number("area_partition_tolerance_m2").subtract(produced_tolerance).abs().lte(1e-12)))
            .And(self._nbool(ee.Algorithms.IsEqual(
                feature.get("area_partition_pass"),
                self._boolean(expected_residual.abs().lte(produced_tolerance)))))
            .And(self._nbool(safe_number("unclassified_area_m2").subtract(expected_residual.max(0)).abs().lte(1e-12)))
            .And(self._nbool(safe_number("overlap_excess_area_m2").subtract(expected_residual.multiply(-1).max(0)).abs().lte(1e-12))), True)
        errors = ee.List(ee.Algorithms.If(exact_partition_metrics_ok, errors,
                                          errors.add("ROW_AREA_PARTITION_METRICS_FAILED")))
        flag_values = [cloud.gt(0), rejected.gt(0), no_retrieval.gt(0), missing_qc.gt(0)]
        expected_failure_count = ee.Number(0)
        for flag in flag_values:
            expected_failure_count = expected_failure_count.add(ee.Number(ee.Algorithms.If(flag, 1, 0)))
        flag_ok = ee.Algorithms.If(formula_applicable,
            ee.Algorithms.IsEqual(feature.get("failure_reason_count"), expected_failure_count.toInt64()), True)
        errors = ee.List(ee.Algorithms.If(flag_ok, errors,
                                          errors.add("ROW_FAILURE_REASON_COUNT_FAILED")))
        for name, expected_flag in zip(("has_cloud", "has_rejected_qa", "has_noncloud_no_retrieval", "has_missing_qc"), flag_values):
            exact_flag_ok = ee.Algorithms.If(formula_applicable, ee.Algorithms.IsEqual(
                feature.get(name), self._boolean(expected_flag)), True)
            errors = ee.List(ee.Algorithms.If(exact_flag_ok, errors,
                                              errors.add("ROW_FLAG_FORMULA_FAILED:" + name)))
        mixed_ok = ee.Algorithms.If(formula_applicable,
            ee.Algorithms.IsEqual(feature.get("has_mixed_failure_reasons"),
                                  self._boolean(expected_failure_count.gte(2))), True)
        errors = ee.List(ee.Algorithms.If(mixed_ok, errors,
                                          errors.add("ROW_FLAG_FORMULA_FAILED:has_mixed_failure_reasons")))
        expected_state = ee.String(ee.Algorithms.If(accepted.gt(0), "ACCEPTED",
            ee.Algorithms.If(produced.gt(0), "SOURCE_PRESENT_REJECTED_QA",
            ee.Algorithms.If(self._nbool(cloud.gt(0)).And(self._nbool(no_retrieval.eq(0))), "SOURCE_PRESENT_CLOUD",
                             "SOURCE_PRESENT_NO_RETRIEVAL"))))
        state_ok = ee.Algorithms.If(formula_applicable,
                                    ee.Algorithms.IsEqual(feature.get("row_state"), expected_state),
                                    ee.Algorithms.If(single, sparse_processing_error_ok,
                                    ee.Algorithms.If(source_count.eq(0),
                                        ee.Algorithms.IsEqual(feature.get("row_state"), "NO_SOURCE_IMAGE"),
                                        ee.Algorithms.IsEqual(feature.get("row_state"), "DUPLICATE_SOURCE_IMAGES"))))
        errors = ee.List(ee.Algorithms.If(state_ok, errors, errors.add("ROW_STATE_IDENTITY_FAILED")))
        source_identity_ok = ee.Algorithms.If(source_count.eq(0),
            ee.Algorithms.If(names.contains("source_image_id"), False,
                ee.Algorithms.If(names.contains("source_system_time_start"), False, True)),
            ee.Algorithms.If(single,
                ee.Algorithms.If(names.contains("source_image_id"), names.contains("source_system_time_start"), False),
                             safe_list("source_image_ids_if_duplicate").length().eq(source_count)))
        errors = ee.List(ee.Algorithms.If(source_identity_ok, errors,
                                          errors.add("ROW_SOURCE_IDENTITY_FAILED")))
        null_reason_ok = ee.Algorithms.If(single,
            ee.Algorithms.If(formula_applicable,
                ee.Algorithms.If(names.contains("null_reason"), False, True),
                sparse_processing_error_ok),
            ee.Algorithms.If(source_count.eq(0),
            ee.Algorithms.IsEqual(feature.get("null_reason"), "no_source_image"),
            ee.Algorithms.If(source_count.gt(1),
                ee.Algorithms.IsEqual(feature.get("null_reason"), "duplicate_source_images"),
                ee.Algorithms.If(names.contains("null_reason"), False, True))))
        errors = ee.List(ee.Algorithms.If(null_reason_ok, errors,
                                          errors.add("ROW_NULL_REASON_IDENTITY_FAILED")))
        output = feature.set("_strict_row_errors", errors.distinct().sort()) \
                        .set("_strict_row_error_count", errors.distinct().length())
        return output.select(output.propertyNames().removeAll(
            SPARSE_BRANCH_INTERNAL_PROVENANCE_FIELDS))

    def summary(self, rows: Any, window: dict[str, Any], stream: dict[str, Any], treatment: dict[str, Any]) -> Any:
        ee = self.ee
        def as_long(value: Any) -> Any: return ee.Number(value).toInt64()
        def as_float(value: Any) -> Any: return ee.Number(value).toDouble()
        selected = rows.filter(ee.Filter.eq("stream_id", stream["stream_id"]))
        eligible = selected.filter(ee.Filter.eq("source_image_count", 1)).filter(ee.Filter.eq("_error_count", 0)).filter(ee.Filter.gt("eligible_roi_area_m2", 0))
        values = ee.List(eligible.aggregate_array("accepted_roi_fraction")).sort()
        n = values.length()
        def quantile(p: float) -> Any:
            h = n.subtract(1).multiply(p); lo, hi = h.floor(), h.ceil()
            return as_float(ee.Number(values.get(lo)).add(
                ee.Number(values.get(hi)).subtract(
                    ee.Number(values.get(lo))).multiply(h.subtract(lo))))
        mean = as_float(values.reduce(ee.Reducer.mean()))
        sd = as_float(ee.Number(values.map(
            lambda x: ee.Number(x).subtract(mean).pow(2)).reduce(
                ee.Reducer.sum())).divide(n).sqrt())
        state_total = selected.filter(ee.Filter.inList("row_state", ["ACCEPTED", "SOURCE_PRESENT_CLOUD", "SOURCE_PRESENT_REJECTED_QA", "SOURCE_PRESENT_NO_RETRIEVAL"])).size()
        errors = ee.List(ee.Algorithms.If(selected.size().eq(14), [], ["SUMMARY_ROW_COUNT_MISMATCH"]))
        p = {"schema_version": VERSION["coverage_schema"], "specification_version": VERSION["specification"],
             "implementation_version_or_hash": VERSION["implementation"], "run_timestamp_utc": self.run_timestamp,
             "summary_id": window["window_id"] + "__" + stream["stream_id"] + "__" + treatment["erosion_id"],
             "window_id": window["window_id"], "season": window["season"], "window_start_utc": window["start"],
             "window_end_exclusive_utc": window["end"], "stream_id": stream["stream_id"], "platform": stream["platform"],
             "phase": stream["phase"], "collection_id": stream["collection_id"], "erosion_id": treatment["erosion_id"],
             "erosion_distance_m": as_float(treatment["distance_m"]), "geometry_id": "wise_wfd_v1_9_huaih049_2022_unrounded__" + treatment["suffix"],
             "expected_date_count": as_long(14), "row_count": as_long(selected.size()),
             "source_image_count_sum": as_long(selected.aggregate_sum("source_image_count")),
             "source_present_row_count": as_long(selected.filter(ee.Filter.eq("source_image_count", 1)).size()),
             "no_source_row_count": as_long(selected.filter(ee.Filter.eq("source_image_count", 0)).size()),
             "duplicate_source_row_count": as_long(selected.filter(ee.Filter.gt("source_image_count", 1)).size()),
             "validation_error_row_count": as_long(selected.filter(ee.Filter.gt("_error_count", 0)).size()),
             "state_accepted_count": as_long(selected.filter(ee.Filter.eq("row_state", "ACCEPTED")).size()),
             "state_cloud_count": as_long(selected.filter(ee.Filter.eq("row_state", "SOURCE_PRESENT_CLOUD")).size()),
             "state_rejected_count": as_long(selected.filter(ee.Filter.eq("row_state", "SOURCE_PRESENT_REJECTED_QA")).size()),
             "state_no_retrieval_count": as_long(selected.filter(ee.Filter.eq("row_state", "SOURCE_PRESENT_NO_RETRIEVAL")).size()),
             "state_other_count": as_long(selected.size().subtract(state_total)), "coverage_observation_count": as_long(n),
             "coverage_missing_count": as_long(ee.Number(14).subtract(n)),
             "marker_ge_005_count": as_long(eligible.filter(ee.Filter.gte("accepted_roi_fraction", 0.05)).size()),
             "marker_ge_025_count": as_long(eligible.filter(ee.Filter.gte("accepted_roi_fraction", 0.25)).size()),
             "marker_ge_050_count": as_long(eligible.filter(ee.Filter.gte("accepted_roi_fraction", 0.50)).size()),
             "eligible_roi_area_m2": ee.Number(selected.first().get("eligible_roi_area_m2")).toDouble(),
             "coverage_definition": "accepted_area_m2 / eligible_roi_area_m2; values exist only for one source image, positive eligible area, and no validation error",
             "quantile_method": "Hyndman-Fan Type 7: h=(n-1)p with linear interpolation; population SD divisor n",
             "physical_schema_note": "Unavailable nullable distribution values are omitted; no sentinel values.",
             "validation_errors": errors}
        sparse_summary = ee.Feature(None, p)
        populated_summary = sparse_summary.set({
            "coverage_mean": mean,
            "coverage_population_sd": sd,
            "coverage_min": as_float(values.get(0)),
            "coverage_q05_type7": quantile(0.05),
            "coverage_q25_type7": quantile(0.25),
            "coverage_q50_type7": quantile(0.50),
            "coverage_max": as_float(values.get(n.subtract(1))),
        })
        # Sparse null-by-omission is physical Earth Engine behavior.  Selecting
        # the whole feature branch keeps nullable distribution properties absent
        # when there are no eligible observations, so runtime type validation
        # never inspects a computed null as though it were a present Float.
        return ee.Feature(ee.Algorithms.If(n.gt(0), populated_summary,
                                           sparse_summary))

    def vector(self, index: int) -> Any:
        ee, treatment = self.ee, TREATMENTS[index]
        def as_long(value: Any) -> Any: return ee.Number(value).toInt64()
        def as_float(value: Any) -> Any: return ee.Number(value).toDouble()
        source, candidate = self._planar(self.source), self.candidate(treatment)
        source_area = source.area(maxError=self._margin(), proj=OP_CRS)
        area = candidate.area(maxError=self._margin(), proj=OP_CRS)
        removed = source_area.subtract(area); tolerance = source_area.multiply(1e-6).max(100)
        balance = source_area.subtract(area.add(removed))
        outside = candidate.difference(right=source, maxError=self._margin(), proj=OP_CRS).area(maxError=self._margin(), proj=OP_CRS)
        opened = source if index == 0 else candidate.buffer(distance=treatment["distance_m"], maxError=self._margin(), proj=OP_CRS)
        opening_loss = source_area.subtract(opened.intersection(right=source, maxError=self._margin(), proj=OP_CRS).area(maxError=self._margin(), proj=OP_CRS)).max(0)
        errors = ee.List([])
        errors = ee.List(ee.Algorithms.If(area.lte(0), errors.add("EMPTY_OR_NONPOSITIVE_CANDIDATE"), errors))
        errors = ee.List(ee.Algorithms.If(balance.abs().gt(tolerance),
                                          errors.add("VECTOR_AREA_BALANCE_FAILED"), errors))
        errors = ee.List(ee.Algorithms.If(outside.gt(tolerance), errors.add("CANDIDATE_OUTSIDE_SOURCE"), errors))
        record = self.source_record
        p = {"schema_version": VERSION["vector_schema"], "specification_version": VERSION["specification"],
             "implementation_version_or_hash": VERSION["implementation"], "run_timestamp_utc": self.run_timestamp,
             "source_dataset_version": "WISE_WFD_v1.9_2025-09", "source_layer_id": "17_SurfaceWaterBody_polygon",
             "source_requested_url": record["requested_url"], "source_raw_sha256": record["raw_sha256"],
             "source_canonical_sha256": record["canonical_sha256"], "source_feature_id": as_long(record["properties"]["OBJECTID"]),
             "source_thematic_id": record["thematic_id"], "source_reporting_year": as_long(record["reporting_year"]),
             "source_name_international": record["properties"]["nameTextInternational"], "source_name": record["properties"]["nameText"],
             "source_size_value": as_float(record["size_value"]), "source_size_uom": record["size_uom"],
             "source_mean_depth_reported_value": as_float(record["properties"]["meanDepth"]),
             "source_mean_depth_unit_interpretation": "provider_field_meanDepth_reported_without_unit_in_service_response",
             "source_geometry_type": record["geometry_type"], "source_ring_count": as_long(record["ring_count"]),
             "source_coordinate_tuple_count_including_closure": as_long(record["coordinate_tuple_count_including_closure"]),
             "source_bbox_wgs84": ee.List(record["bbox_wgs84"]).map(lambda value: as_float(value)), "source_geometry_valid": record["geometry_is_valid"],
             "source_geometry_simple": record["geometry_is_simple"], "erosion_id": treatment["erosion_id"],
             "erosion_distance_m": as_float(treatment["distance_m"]), "vector_area_epsg3035_m2": as_float(area),
             "retained_area_fraction": as_float(area.divide(source_area)), "removed_area_m2": as_float(removed),
             "area_balance_residual_m2": as_float(balance), "outside_source_area_m2": as_float(outside),
             "opening_loss_area_m2": as_float(opening_loss), "validation_errors": errors}
        if index > 0:
            weaker = self.candidate(TREATMENTS[index - 1])
            p["weaker_candidate_containment_area_m2"] = as_float(candidate.difference(right=weaker, maxError=self._margin(), proj=OP_CRS).area(maxError=self._margin(), proj=OP_CRS))
        return ee.Feature(None, p)


def feature_properties(value: dict[str, Any]) -> dict[str, Any]:
    return value.get("properties", value)


def combine_overall(seasonal: list[dict[str, Any]], coverage: dict[tuple[str, str], list[float]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for treatment in TREATMENTS:
        for stream in STREAMS:
            rows = [x for x in seasonal if x["erosion_id"] == treatment["erosion_id"] and x["stream_id"] == stream["stream_id"]]
            values = sorted(coverage.get((treatment["erosion_id"], stream["stream_id"]), []))
            first = rows[0]
            sum_fields = ["row_count", "source_image_count_sum", "source_present_row_count", "no_source_row_count",
                          "duplicate_source_row_count", "validation_error_row_count", "state_accepted_count", "state_cloud_count",
                          "state_rejected_count", "state_no_retrieval_count", "state_other_count"]
            p = {k: first[k] for k in ["schema_version", "specification_version", "implementation_version_or_hash",
                                                    "run_timestamp_utc", "platform", "phase", "collection_id", "geometry_id",
                                                    "coverage_definition", "quantile_method", "physical_schema_note", "eligible_roi_area_m2"]}
            p.update({"summary_id": f"all_windows_2024__{stream['stream_id']}__{treatment['erosion_id']}",
                      "window_id": "all_windows_2024", "season": "all_selected_seasons", "window_start_utc": WINDOWS[0]["start"],
                      "window_end_exclusive_utc": WINDOWS[-1]["end"], "stream_id": stream["stream_id"],
                      "erosion_id": treatment["erosion_id"], "erosion_distance_m": float(treatment["distance_m"]),
                      "expected_date_count": 56, "coverage_observation_count": len(values), "coverage_missing_count": 56 - len(values),
                      "marker_ge_005_count": sum(v >= .05 for v in values), "marker_ge_025_count": sum(v >= .25 for v in values),
                      "marker_ge_050_count": sum(v >= .50 for v in values), "validation_errors": []})
            p.update({field: sum(int(r[field]) for r in rows) for field in sum_fields})
            p["eligible_roi_area_m2"] = float(p["eligible_roi_area_m2"])
            if values:
                p.update({"coverage_mean": float(sum(values) / len(values)),
                          "coverage_population_sd": float(population_sd(values)),
                          "coverage_min": float(values[0]),
                          "coverage_q05_type7": float(type7(values, .05)),
                          "coverage_q25_type7": float(type7(values, .25)),
                          "coverage_q50_type7": float(type7(values, .50)),
                          "coverage_max": float(values[-1])})
            if p["row_count"] != 56:
                p["validation_errors"].append("SUMMARY_ROW_COUNT_MISMATCH")
            results.append(p)
    return results


def execute_projection_diagnostic(project: str, date_utc: str,
                                  stream_ids: Iterable[str],
                                  deadline_seconds: int,
                                  max_attempts: int) -> int:
    """Run only the bounded coordinate-free projection diagnostic."""
    selected_streams = validate_projection_diagnostic_request(date_utc, stream_ids)
    serializer_recursion = configure_ee_serializer_recursion_limit()
    ee = import_ee()
    ee.Initialize(project=project)
    request_policy = configure_ee_request_policy(
        ee, deadline_seconds, max_attempts)
    retry_options = {"max_attempts": request_policy["max_attempts"],
                     "deadline_seconds": request_policy["deadline_seconds"]}
    print(json.dumps({"EARTH_ENGINE_REQUEST_POLICY": request_policy},
                     sort_keys=True), flush=True)
    geometry_json, source_record = load_verified_source()
    print(json.dumps({"COMPLETE_COORDINATE_FREE_SOURCE_EVIDENCE":
                      coordinate_free_source_evidence(
                          source_record, project,
                          getattr(ee, "__version__", importlib_metadata.version(
                              "earthengine-api")), serializer_recursion)},
                     indent=2, sort_keys=True), flush=True)
    runner = AuditRunner(ee, geometry_json, source_record, retry_options)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for stream in selected_streams:
        phase = f"projection_diagnostic_{date_utc}_{stream['stream_id']}"
        evidence = bounded_transient_getinfo(
            lambda current_stream=stream: runner.projection_diagnostic_evidence(
                date_utc, current_stream), phase, **retry_options)
        errors = validate_projection_diagnostic_evidence(
            evidence, date_utc, stream)
        records.append(evidence)
        if errors:
            failures.append({"stream_id": stream["stream_id"], "errors": errors})
    result = {
        "PROJECTION_DIAGNOSTIC_COMPLETE": True,
        "date_utc": date_utc,
        "requested_stream_ids": [stream["stream_id"] for stream in selected_streams],
        "record_count": len(records),
        "records": records,
        "failures": failures,
        "pass": not failures,
        "execution_note": (
            "Read-only official Earth Engine Python API projection diagnostic; "
            "no geometry coordinates, assets, exports, files, deployment, or UI."
        ),
    }
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0 if not failures else 2


def execute(project: str, start_chunk: int, end_chunk: int | None,
            vectors_only: bool, deadline_seconds: int,
            max_attempts: int) -> int:
    session_started = time.monotonic()
    session_deadline = session_started + SESSION_LIMIT_SECONDS
    validated_start, validated_stop = validate_chunk_bounds(start_chunk, end_chunk)
    serializer_recursion = guarded_local_action(
        configure_ee_serializer_recursion_limit, "runner_initialization",
        session_deadline_monotonic=session_deadline)
    ee = guarded_local_action(
        import_ee, "earth_engine_import",
        session_deadline_monotonic=session_deadline)
    guarded_local_action(
        lambda: ee.Initialize(project=project), "earth_engine_initialize",
        session_deadline_monotonic=session_deadline)
    request_policy = guarded_local_action(
        lambda: configure_ee_request_policy(
            ee, deadline_seconds, max_attempts), "request_policy",
        session_deadline_monotonic=session_deadline)
    retry_options = {"max_attempts": request_policy["max_attempts"],
                     "deadline_seconds": request_policy["deadline_seconds"],
                     "session_deadline_monotonic": session_deadline}
    print(json.dumps({"EARTH_ENGINE_REQUEST_POLICY": request_policy},
                     sort_keys=True), flush=True)
    geometry_json, source_record = guarded_local_action(
        load_verified_source, "source_verification",
        session_deadline_monotonic=session_deadline)
    earthengine_version = getattr(
        ee, "__version__", importlib_metadata.version("earthengine-api"))
    source_evidence = guarded_local_action(
        lambda: coordinate_free_source_evidence(
            source_record, project, earthengine_version, serializer_recursion),
        "source_verification", session_deadline_monotonic=session_deadline)
    print(json.dumps({"COMPLETE_COORDINATE_FREE_SOURCE_EVIDENCE": source_evidence},
                     indent=2, sort_keys=True), flush=True)
    compatibility = guarded_local_action(
        lambda: checkpoint_compatibility(
            source_evidence, project, earthengine_version, request_policy),
        "checkpoint_compatibility",
        session_deadline_monotonic=session_deadline)
    checkpoint = guarded_local_action(
        lambda: load_checkpoint(compatibility), "checkpoint_load",
        session_deadline_monotonic=session_deadline)
    descriptors = [(window, treatment) for window in WINDOWS for treatment in TREATMENTS]
    expected_vector_ids = [treatment["erosion_id"] for treatment in TREATMENTS]
    completed_vector_ids = list(checkpoint["completed_vectors"])
    if completed_vector_ids != expected_vector_ids[:len(completed_vector_ids)]:
        raise ValueError("CHECKPOINT_VECTOR_SEQUENCE_FAILED")
    vectors = [checkpoint["completed_vectors"][identifier]
               for identifier in completed_vector_ids]
    def revalidate_completed_vectors() -> None:
        if vectors and validate_compact_vectors(vectors, len(vectors)):
            raise ValueError("CHECKPOINT_VECTOR_REVALIDATION_FAILED")
    guarded_local_action(
        revalidate_completed_vectors, "checkpoint_revalidation",
        session_deadline_monotonic=session_deadline)
    completed_chunk_numbers = [int(key) for key in checkpoint["completed_chunks"]]
    if completed_chunk_numbers != list(range(1, len(completed_chunk_numbers) + 1)):
        raise ValueError("CHECKPOINT_CHUNK_SEQUENCE_FAILED")
    def revalidate_completed_chunks() -> None:
        for chunk_number in completed_chunk_numbers:
            window, treatment = descriptors[chunk_number - 1]
            errors = validate_checkpoint_chunk(
                checkpoint["completed_chunks"][f"{chunk_number:02d}"],
                chunk_number, window, treatment)
            if errors:
                raise ValueError("CHECKPOINT_CHUNK_REVALIDATION_FAILED")
            enforce_session_budget(
                session_deadline, "checkpoint_revalidation")
    guarded_local_action(
        revalidate_completed_chunks, "checkpoint_revalidation",
        session_deadline_monotonic=session_deadline)
    print(json.dumps({"AUDIT_CHECKPOINT_RESUME": {
        "path": CHECKPOINT_PATH.relative_to(ROOT).as_posix(),
        "compatible": True,
        "completed_vector_count": len(vectors),
        "completed_chunk_count": len(completed_chunk_numbers),
        "first_incomplete_vector": (len(vectors) + 1 if len(vectors) < 4 else None),
        "first_incomplete_chunk": (
            len(completed_chunk_numbers) + 1
            if len(completed_chunk_numbers) < 16 else None),
        "full_acceptance_claimed": False,
    }}, sort_keys=True), flush=True)
    runner = guarded_local_action(
        lambda: AuditRunner(ee, geometry_json, source_record, retry_options),
        "runner_initialization",
        session_deadline_monotonic=session_deadline)
    runtime_fixture = evaluate_authenticated_phase(
        runner.server_runtime_fixture, "runtime_fixture", **retry_options)
    runtime_fixture_failures = guarded_local_action(
        lambda: validate_server_runtime_fixture(runtime_fixture),
        "checkpoint_revalidation",
        session_deadline_monotonic=session_deadline)
    print(json.dumps({"SERVER_RUNTIME_TYPE_FIXTURE": runtime_fixture,
                      "failures": runtime_fixture_failures,
                      "pass": not runtime_fixture_failures}, sort_keys=True), flush=True)
    if runtime_fixture_failures:
        print(json.dumps({"fail_closed": True, "phase": "server_runtime_type_fixture",
                          "failures": runtime_fixture_failures}, indent=2))
        return 2
    first_incomplete_chunk = len(completed_chunk_numbers) + 1
    # AUDIT-006 makes the first incomplete compatible chunk controlling.  A
    # legacy --start-chunk value must never skip an incomplete predecessor.
    effective_start = first_incomplete_chunk
    selected_window_ids = []
    for window, _ in descriptors[effective_start - 1:validated_stop]:
        if window["window_id"] not in selected_window_ids:
            selected_window_ids.append(window["window_id"])
    selected_windows = [
        window for window in WINDOWS if window["window_id"] in selected_window_ids
    ]
    projection_inventories: list[dict[str, Any]] = []
    projection_inventory_failures: list[dict[str, Any]] = []
    for window in selected_windows:
        for stream in STREAMS:
            phase = f"projection_inventory_{window['window_id']}_{stream['stream_id']}"
            evidence = bounded_transient_getinfo(
                lambda current_window=window, current_stream=stream:
                    runner.projection_inventory_evidence(
                        current_window, current_stream),
                phase, **retry_options)
            projection_inventories.append(evidence)
            if evidence.get("record_count") != 14 or \
               not isinstance(evidence.get("records"), list) or \
               len(evidence["records"]) != 14 or not evidence.get("pass"):
                projection_inventory_failures.append({
                    "window_id": window["window_id"],
                    "stream_id": stream["stream_id"],
                    "hard_projection_failures": evidence.get(
                        "hard_projection_failures", []),
                    "record_count": evidence.get("record_count"),
                })
            runner.register_projection_inventory(evidence)
    print(json.dumps({
        "AUDIT_PROJECTION_EQUIVALENCE_EVIDENCE": projection_inventories,
        "projection_inventory_failure_count": len(projection_inventory_failures),
        "pass": not projection_inventory_failures,
    }, indent=2, sort_keys=True), flush=True)
    if projection_inventory_failures:
        print(json.dumps({
            "fail_closed": True,
            "phase": "projection_equivalence_inventory",
            "failures": projection_inventory_failures,
        }, indent=2, sort_keys=True), flush=True)
        return 2
    for index in range(len(vectors), 4):
        print(f"START VECTOR {index + 1}/4: {TREATMENTS[index]['erosion_id']}", flush=True)
        def build_vector_evidence(current_index: int = index) -> Any:
            vector_feature = runner.vector(current_index)
            return ee.Dictionary({
                "feature": vector_feature,
                "runtime_type_errors": runner.server_runtime_type_errors(
                    vector_feature, load_authoritative_manifests()["vector"]),
            })
        vector_evidence = evaluate_authenticated_phase(
            build_vector_evidence,
            f"vector_{index + 1:02d}_{TREATMENTS[index]['erosion_id']}",
            **retry_options)
        enforce_session_budget(session_deadline, "checkpoint_revalidation")
        props = normalize_evaluated_float64(
            feature_properties(vector_evidence["feature"]),
            load_authoritative_manifests()["vector"])
        if vector_evidence["runtime_type_errors"]:
            props["validation_errors"] = sorted(set(
                props.get("validation_errors", []) + vector_evidence["runtime_type_errors"]))
        full_manifest_errors = validate_evaluated_properties(
            props, load_authoritative_manifests()["vector"])
        if props.get("validation_errors"):
            full_manifest_errors.append("VECTOR_EMITTED_VALIDATION_ERRORS")
        compact = compact_validated_vector(props)
        candidate_vectors = vectors + [compact]
        full_manifest_errors.extend(validate_compact_vectors(
            candidate_vectors, len(candidate_vectors)))
        if full_manifest_errors:
            print(json.dumps({"fail_closed": True, "phase": "vector",
                              "strict_vector_failures": sorted(set(
                                  full_manifest_errors))}, indent=2))
            return 2
        enforce_session_budget(session_deadline, "checkpoint_save")
        vectors.append(compact)
        checkpoint["completed_vectors"][treatment_id := TREATMENTS[index][
            "erosion_id"]] = compact
        atomic_save_checkpoint(
            checkpoint, session_deadline_monotonic=session_deadline)
        enforce_session_budget(session_deadline, "checkpoint_save")
        print(json.dumps({"complete_vector": index + 1, "properties": props}, sort_keys=True), flush=True)
    vector_gate_failures = validate_compact_vectors(vectors)
    if vector_gate_failures:
        print(json.dumps({"fail_closed": True, "phase": "vectors",
                          "strict_vector_failures": vector_gate_failures}, indent=2))
        return 2
    if vectors_only:
        print(json.dumps({"vectors_only_complete": True, "vector_count": 4,
                          "strict_vector_failures": [], "pass": True}, indent=2))
        return 0
    start_chunk, stop = effective_start, validated_stop
    seasonal: list[dict[str, Any]] = []
    coverage: dict[tuple[str, str], list[float]] = {}
    seasonal_coverage: dict[tuple[str, str, str], list[float]] = {}
    all_keys: list[str] = []
    chunk_failures: list[dict[str, Any]] = []
    for chunk_number in completed_chunk_numbers:
        stored = checkpoint["completed_chunks"][f"{chunk_number:02d}"]
        all_keys.extend(stored["row_keys"])
        seasonal.extend(stored["seasonal_summaries"])
        for stream in STREAMS:
            values = stored["coverage_values"][stream["stream_id"]]
            treatment_id = stored["erosion_id"]
            window_id = stored["window_id"]
            coverage.setdefault((treatment_id, stream["stream_id"]), []).extend(values)
            seasonal_coverage[(treatment_id, stream["stream_id"], window_id)] = list(values)
    for index in range(start_chunk - 1, stop):
        window, treatment = descriptors[index]
        print(f"START CHUNK {index + 1}/16: {window['window_id']}__{treatment['erosion_id']}", flush=True)
        def evaluate_stream_subrequest(stream: dict[str, Any]) -> dict[str, Any]:
            def build_stream_evidence(
                    current_window: dict[str, Any] = window,
                    current_treatment: dict[str, Any] = treatment,
                    current_stream: dict[str, Any] = stream) -> Any:
                rows = runner.chunk_stream(
                    current_window, current_treatment, current_stream)
                summary_feature = runner.summary(
                    rows, current_window, current_stream, current_treatment)
                eligible_rows = rows.filter(
                    ee.Filter.eq("source_image_count", 1)).filter(
                    ee.Filter.eq("_error_count", 0)).filter(
                    ee.Filter.gt("eligible_roi_area_m2", 0))
                validation_error_rows = rows.filter(
                    ee.Filter.gt("_error_count", 0))
                return ee.Dictionary({
                    "row_count": rows.size(),
                    "row_keys": rows.aggregate_array("_audit_key"),
                    "unique_key_count": rows.distinct(["_audit_key"]).size(),
                    "validation_error_row_count": validation_error_rows.size(),
                    "validation_error_row_details": validation_error_rows.toList(14).map(
                        lambda feature: ee.Feature(feature).toDictionary(
                            VALIDATION_ERROR_DETAIL_FIELDS)),
                    "strict_row_failure_count": rows.filter(
                        ee.Filter.gt("_strict_row_error_count", 0)).size(),
                    "strict_row_failure_details": rows.filter(
                        ee.Filter.gt("_strict_row_error_count", 0)).aggregate_array(
                            "_strict_row_errors"),
                    "stream_count": rows.aggregate_array("stream_id").distinct().size(),
                    "treatment_count": rows.aggregate_array("erosion_id").distinct().size(),
                    "season_count": rows.aggregate_array("audit_season").distinct().size(),
                    "coverage_values": eligible_rows.aggregate_array(
                        "accepted_roi_fraction"),
                    "seasonal_summary_dictionaries": ee.List([
                        summary_feature.toDictionary()]),
                    "summary_runtime_type_dictionaries": ee.List([
                        ee.Dictionary({
                            "summary_id": summary_feature.get("summary_id"),
                            "errors": runner.server_runtime_type_errors(
                                summary_feature,
                                load_authoritative_manifests()["coverage"]),
                        })]),
                })
            phase = (
                f"chunk_{index + 1:02d}_{window['window_id']}__"
                f"{treatment['erosion_id']}__{stream['stream_id']}")
            current_evidence = evaluate_authenticated_phase(
                build_stream_evidence, phase, **retry_options)
            enforce_session_budget(session_deadline, "chunk_subrequest_validation")
            return current_evidence
        stream_evidence, subrequest_errors, failed_stream_id = \
            collect_validated_stream_subrequests(
                window, treatment, evaluate_stream_subrequest)
        enforce_session_budget(session_deadline, "chunk_subrequest_validation")
        if subrequest_errors:
            print(json.dumps({
                "fail_closed": True,
                "phase": "chunk_subrequest_validation",
                "failed_stream_id": failed_stream_id,
                "subrequest_failures": subrequest_errors,
                "partial_subrequest_evidence_persisted": False,
            }, indent=2))
            return 2
        evidence, combination_errors = combine_stream_subrequest_evidence(
            stream_evidence, window, treatment)
        enforce_session_budget(session_deadline, "chunk_subrequest_combination")
        if combination_errors:
            print(json.dumps({
                "fail_closed": True,
                "phase": "chunk_subrequest_combination",
                "chunk": index + 1,
                "subrequest_failures": combination_errors,
                "partial_subrequest_evidence_persisted": False,
            }, indent=2))
            return 2
        all_keys.extend(evidence["row_keys"])
        for stream_id, values in evidence["coverage_values"].items():
            coverage.setdefault((treatment["erosion_id"], stream_id), []).extend(values)
            seasonal_coverage[(treatment["erosion_id"], stream_id, window["window_id"])] = list(values)
        expected_summary_ids = [
            f"{window['window_id']}__{stream['stream_id']}__{treatment['erosion_id']}"
            for stream in STREAMS
        ]
        summary_rows, runtime_by_id = extract_four_summary_evidence(
            evidence, expected_summary_ids)
        validation_detail_failures = validate_validation_error_row_details(evidence)
        summary_runtime_failure_count = sum(len(errors) for errors in runtime_by_id.values())
        for feature in summary_rows:
            properties = normalize_evaluated_float64(
                feature,
                load_authoritative_manifests()["coverage"])
            if runtime_by_id.get(properties["summary_id"]):
                properties["validation_errors"] = sorted(set(
                    properties.get("validation_errors", []) + runtime_by_id[properties["summary_id"]]))
            seasonal.append(properties)
        strict = evidence["row_count"] == 56 and evidence["unique_key_count"] == 56 and evidence["validation_error_row_count"] == 0 and not validation_detail_failures and evidence["strict_row_failure_count"] == 0 and summary_runtime_failure_count == 0 and evidence["stream_count"] == 4 and evidence["treatment_count"] == 1 and evidence["season_count"] == 1
        if evidence["row_keys"] != expected_chunk_keys(window, treatment):
            strict = False
            evidence["row_key_identity_failure"] = True
        summary_formula_failures: list[dict[str, Any]] = []
        for summary, stream in zip(seasonal[-4:], STREAMS):
            formula_errors = validate_summary_formula(
                summary, evidence["coverage_values"][stream["stream_id"]])
            if summary.get("summary_id") != expected_summary_ids[
                    STREAMS.index(stream)] or \
               summary.get("window_id") != window["window_id"] or \
               summary.get("season") != window["season"] or \
               summary.get("stream_id") != stream["stream_id"] or \
               summary.get("platform") != stream["platform"] or \
               summary.get("phase") != stream["phase"] or \
               summary.get("collection_id") != stream["collection_id"] or \
               summary.get("erosion_id") != treatment["erosion_id"] or \
               summary.get("erosion_distance_m") != float(treatment["distance_m"]):
                formula_errors.append("CHUNK_SUMMARY_PROVENANCE_FAILED")
            if formula_errors:
                summary_formula_failures.append({
                    "summary_id": summary.get("summary_id"),
                    "errors": sorted(set(formula_errors))})
        if summary_formula_failures:
            strict = False
            evidence["summary_formula_failures"] = summary_formula_failures
        if validation_detail_failures:
            evidence["validation_error_detail_failures"] = validation_detail_failures
        if not strict:
            chunk_failures.append({"chunk": index + 1, "evidence": evidence})
        print(json.dumps({"complete_chunk": index + 1, "strict_pass": strict,
                          "row_count": evidence["row_count"], "unique_key_count": evidence["unique_key_count"],
                          "validation_error_row_count": evidence["validation_error_row_count"],
                          "validation_error_detail_failure_count": len(validation_detail_failures),
                          "strict_row_failure_count": evidence["strict_row_failure_count"],
                          "seasonal_summary_dictionary_count": len(summary_rows),
                          "summary_runtime_dictionary_count": len(runtime_by_id),
                          "summary_runtime_failure_count": summary_runtime_failure_count}), flush=True)
        if not strict:
            print(json.dumps({"fail_closed": True, "chunk_failures": chunk_failures}, indent=2))
            return 2
        stored_chunk = make_checkpoint_chunk(
            index + 1, window, treatment, evidence, seasonal[-4:])
        stored_errors = validate_checkpoint_chunk(
            stored_chunk, index + 1, window, treatment)
        if stored_errors:
            print(json.dumps({"fail_closed": True, "phase": "checkpoint_chunk",
                              "failures": stored_errors}, indent=2))
            return 2
        enforce_session_budget(session_deadline, "checkpoint_save")
        checkpoint["completed_chunks"][f"{index + 1:02d}"] = stored_chunk
        atomic_save_checkpoint(
            checkpoint, session_deadline_monotonic=session_deadline)
        enforce_session_budget(session_deadline, "checkpoint_save")
    if len(checkpoint["completed_chunks"]) != 16:
        print(json.dumps({"partial_run_complete": True,
                          "evaluated_chunk_range": [start_chunk, stop],
                          "first_incomplete_chunk": len(
                              checkpoint["completed_chunks"]) + 1,
                          "final_896_80_acceptance_not_claimed": True}, indent=2))
        return 0
    enforce_session_budget(
        session_deadline, "final_aggregation",
        required_remaining_seconds=SESSION_COMPLETION_RESERVE_SECONDS)
    overall = combine_overall(seasonal, coverage)
    enforce_session_budget(session_deadline, "final_aggregation")
    summaries = seasonal + overall
    failures: list[dict[str, Any]] = []
    def check(name: str, passed: bool, actual: Any, expected: Any) -> None:
        if not passed:
            failures.append({"test_id": name, "actual": actual, "expected": expected})
    check("exactly_896_rows", len(all_keys) == 896, len(all_keys), 896)
    check("exactly_896_unique_keys", len(set(all_keys)) == 896, len(set(all_keys)), 896)
    check("exactly_80_summaries", len(summaries) == 80, len(summaries), 80)
    summary_ids = [s["summary_id"] for s in summaries]
    check("exactly_80_unique_summary_ids", len(set(summary_ids)) == 80, len(set(summary_ids)), 80)
    check("no_summary_validation_errors", all(not s["validation_errors"] for s in summaries),
          [s for s in summaries if s["validation_errors"]], [])
    summary_strict_failures = []
    for summary in summaries:
        enforce_session_budget(session_deadline, "final_aggregation")
        if summary["window_id"] == "all_windows_2024":
            summary_values = coverage[(summary["erosion_id"], summary["stream_id"])]
        else:
            summary_values = seasonal_coverage[(summary["erosion_id"], summary["stream_id"], summary["window_id"])]
        errors = validate_summary_formula(summary, summary_values)
        expected_id = f"{summary['window_id']}__{summary['stream_id']}__{summary['erosion_id']}"
        if summary["summary_id"] != expected_id:
            errors.append("SUMMARY_ID_FORMULA_FAILED")
        treatment = next((t for t in TREATMENTS if t["erosion_id"] == summary["erosion_id"]), None)
        stream = next((s for s in STREAMS if s["stream_id"] == summary["stream_id"]), None)
        if treatment is None or abs(summary["erosion_distance_m"] - treatment["distance_m"]) > 1e-12:
            errors.append("SUMMARY_TREATMENT_IDENTITY_FAILED")
        if stream is None or summary["platform"] != stream["platform"] or summary["phase"] != stream["phase"] or summary["collection_id"] != stream["collection_id"]:
            errors.append("SUMMARY_STREAM_IDENTITY_FAILED")
        if errors:
            summary_strict_failures.append({"summary_id": summary["summary_id"], "errors": sorted(set(errors))})
    check("strict_summary_manifest_types_formulas", not summary_strict_failures,
          summary_strict_failures, [])
    vector_strict_failures = validate_compact_vectors(vectors)
    check("strict_vector_manifest_types_formulas", not vector_strict_failures,
          vector_strict_failures, [])
    enforce_session_budget(session_deadline, "final_aggregation")
    result = {"AUDIT_PYTHON_API_COMPLETE": True, "row_count": len(all_keys), "unique_row_key_count": len(set(all_keys)),
              "seasonal_summary_count": len(seasonal), "overall_summary_count": len(overall),
              "summary_count": len(summaries), "unique_summary_id_count": len(set(summary_ids)),
              "vector_count": len(vectors), "failures": failures,
              "pass": aggregate_acceptance_pass(failures),
              "vectors": vectors, "coverage_summaries": summaries,
              "execution_note": "Official Earth Engine Python API; validated coordinate-free checkpoint; one vector or 56-row chunk evaluated at a time; no asset/export/deployment/UI."}
    digest = guarded_local_action(
        lambda: build_final_evidence_digest(result), "final_aggregation",
        session_deadline_monotonic=session_deadline)
    digest_output = "AUDIT_FINAL_EVIDENCE_DIGEST " + json.dumps(
        digest, separators=(",", ":"), sort_keys=False)
    result_output = json.dumps(result, indent=2, sort_keys=True)
    enforce_session_budget(
        session_deadline, "final_aggregation",
        required_remaining_seconds=SESSION_COMPLETION_RESERVE_SECONDS)
    print(digest_output, flush=True)
    print(result_output, flush=True)
    return 0 if aggregate_acceptance_pass(failures) else 2


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test", action="store_true", help="Run pure local tests; no EE import, auth, or network")
    p.add_argument("--authenticate", action="store_true", help="Run official ee.Authenticate then initialize")
    p.add_argument("--auth-mode", default="localhost", choices=["localhost", "notebook", "gcloud"], help="Official Earth Engine OAuth mode")
    p.add_argument("--project", help="Google Cloud project used by ee.Initialize")
    p.add_argument("--start-chunk", type=int, default=1, help="First deterministic chunk, 1-based")
    p.add_argument("--end-chunk", type=int, help="Last deterministic chunk, inclusive")
    p.add_argument("--vectors-only", action="store_true", help="Evaluate only the four bounded vector rows")
    p.add_argument("--projection-diagnostic", action="store_true",
                   help="Run only the read-only source/canonical projection diagnostic")
    p.add_argument("--diagnostic-date", default="2024-10-21",
                   help="Projection diagnostic UTC date (default: 2024-10-21)")
    p.add_argument("--diagnostic-streams", nargs="+", default=["aqua_day", "aqua_night"],
                   help="Projection diagnostic stream IDs (default: aqua_day aqua_night)")
    p.add_argument(
        "--request-deadline-seconds", type=int,
        default=DEFAULT_EE_REQUEST_DEADLINE_SECONDS,
        help=("Official Earth Engine per-request HTTP deadline; AUDIT-006 "
              f"requires exactly {DEFAULT_EE_REQUEST_DEADLINE_SECONDS} seconds"))
    p.add_argument(
        "--transport-max-attempts", type=int,
        default=DEFAULT_EE_TRANSPORT_MAX_ATTEMPTS,
        help=("Earth Engine request attempts; AUDIT-006 requires exactly one "
              "attempt and no outer retry"))
    return p


def main() -> int:
    args = parser().parse_args()
    validate_request_policy(args.request_deadline_seconds,
                            args.transport_max_attempts)
    if args.self_test:
        return 0 if self_test()["pass"] else 2
    if not args.project:
        raise SystemExit("--project is required for authentication or execution")
    if args.authenticate:
        authenticate(args.project, args.auth_mode)
        return 0
    if args.projection_diagnostic:
        return execute_projection_diagnostic(
            args.project, args.diagnostic_date, args.diagnostic_streams,
            args.request_deadline_seconds, args.transport_max_attempts)
    return execute(args.project, args.start_chunk, args.end_chunk,
                   args.vectors_only, args.request_deadline_seconds,
                   args.transport_max_attempts)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SessionCeilingReached as exc:
        print(json.dumps({
            "AUDIT_SESSION_LIMIT_STOP": True,
            "phase": exc.phase,
            "hard_session_limit_seconds": SESSION_LIMIT_SECONDS,
            "remaining_seconds_at_stop": round(exc.remaining_seconds, 3),
            "checkpoint_path": CHECKPOINT_PATH.relative_to(ROOT).as_posix(),
            "validated_checkpoint_preserved": True,
            "full_896_80_acceptance_not_claimed": True,
        }, sort_keys=True), flush=True)
        raise SystemExit(0)
    except Exception as exc:
        print(json.dumps({"audit_failed_closed": True,
                          **redacted_exception_evidence(exc, "top_level")},
                         sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
