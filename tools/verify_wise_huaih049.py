#!/usr/bin/env python3
"""Fail-closed AUDIT-003 verifier for AUDIT-001 operational geometry.

Sources remain in memory. Default output contains provenance/metrics but no
coordinates. ``--emit-ee`` prints verified unrounded coordinates to stdout for
transient use in an authenticated Earth Engine scratch editor.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.ops import transform


ANALYSIS_PATH = Path(__file__).with_name("analyze_wise_huaih049_source_representations.py")
SPEC = importlib.util.spec_from_file_location("wise_audit_002_source", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load the approved source-analysis helpers")
source = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = source
SPEC.loader.exec_module(source)

EXPECTED_GML_METRICS = {
    "area_m2": 594326718.1165043,
    "perimeter_m": 273998.4655011837,
    "geometry_type": "Polygon", "part_count": 1, "hole_count": 0,
    "vertex_count_including_ring_closure": 11012,
    "is_empty": False, "is_valid": True, "is_simple": True,
}
EXPECTED_UNROUNDED_METRICS = {
    "area_m2": 594326718.0574977,
    "perimeter_m": 273998.46545718645,
    "geometry_type": "Polygon", "part_count": 1, "hole_count": 0,
    "vertex_count_including_ring_closure": 11012,
    "is_empty": False, "is_valid": True, "is_simple": True,
}
EXPECTED_CROSS_CHECK = {
    "absolute_area_difference_m2": 0.059006571769714355,
    "absolute_area_difference_percent_of_gml": 9.928305420411447e-09,
    "symmetric_difference_m2": 11.503473830219795,
    "symmetric_difference_percent_of_gml": 1.9355471459664038e-06,
    "hausdorff_distance_m": 9.942694772289642e-05,
}
EXPECTED_CDR_ROW = {
    "cYear": "2022", "countryCode": "HU", "dataset": "SurfaceWaterBody",
    "envUrl": "https://cdr.eionet.europa.eu/hu/eu/wfd2022/spatial/envzrahxw",
    "metadataUrl": "https://cdr.eionet.europa.eu/hu/eu/wfd2022/spatial/envzrahxw/SurfaceWaterBody_HU_20220322.xml",
    "fileUrl": source.GML_URL, "isRestricted": "0",
    "title": "SurfaceWaterBody_HU_20220322",
    "useLimitation": "no conditions apply to access and use",
    "accessConstraints": "otherRestrictions",
    "otherConstraints": "no conditions to access and use / no limitations to public access / no limitations on public access",
}
EXPECTED_UNROUNDED_BBOX = [
    17.24328753321951, 46.70340589559091,
    18.16856173871584, 47.06299246599697,
]

HTTP_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
MEDIA_TYPE_PATTERN = re.compile(
    rf"^[ \t]*({HTTP_TOKEN})/({HTTP_TOKEN})[ \t]*(.*)$")
PARAMETER_PATTERN = re.compile(
    rf";[ \t]*({HTTP_TOKEN})[ \t]*=[ \t]*"
    rf"(?:({HTTP_TOKEN})|\"((?:[^\"\\\r\n]|\\[\t -~])*)\")[ \t]*")


def fail(message: str) -> None:
    raise RuntimeError("WISE_UNROUNDED_SOURCE_VERIFICATION_FAILED: " + message)


def require_exact_metrics(label: str, actual: dict[str, Any], expected: dict[str, Any]) -> None:
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            fail(f"{label} metric {key}: expected {expected_value!r}, got {actual.get(key)!r}")


def require_http(label: str, actual: dict[str, Any], url: str, content_type: str) -> None:
    expected = {
        "requested_url": url, "final_url": url, "redirect_count": 0,
        "http_status": 200, "content_type": content_type, "content_encoding": "",
    }
    for key, value in expected.items():
        if actual.get(key) != value:
            fail(f"{label} HTTP {key}: expected {value!r}, got {actual.get(key)!r}")


def parse_original_gml_content_type(raw_header: Any) -> dict[str, Any]:
    """Parse the exact narrow AUDIT-007 text/xml UTF-8 media-type contract."""
    if not isinstance(raw_header, str) or not raw_header or \
       any(character in raw_header for character in "\r\n"):
        fail("original GML Content-Type malformed")
    match = MEDIA_TYPE_PATTERN.fullmatch(raw_header)
    if match is None:
        fail(f"original GML Content-Type malformed: {raw_header!r}")
    media_type = f"{match.group(1)}/{match.group(2)}"
    if media_type.casefold() != "text/xml":
        fail(f"original GML Content-Type media type: expected 'text/xml', got {media_type!r}")
    remainder = match.group(3)
    parameters: list[tuple[str, str]] = []
    position = 0
    while position < len(remainder):
        parameter = PARAMETER_PATTERN.match(remainder, position)
        if parameter is None:
            fail(f"original GML Content-Type malformed parameters: {raw_header!r}")
        name = parameter.group(1)
        token_value = parameter.group(2)
        quoted_value = parameter.group(3)
        if quoted_value is not None:
            value = re.sub(r"\\([\t -~])", r"\1", quoted_value)
        else:
            value = token_value
        parameters.append((name, value))
        position = parameter.end()
    if len(parameters) > 1:
        charset_count = sum(name.casefold() == "charset" for name, _ in parameters)
        if charset_count > 1:
            fail("original GML Content-Type duplicate charset parameter")
        fail("original GML Content-Type contains unknown or multiple parameters")
    if parameters:
        name, value = parameters[0]
        if name.casefold() != "charset":
            fail(f"original GML Content-Type unknown parameter: {name!r}")
        if value.casefold() != "utf-8":
            fail(f"original GML Content-Type charset: expected UTF-8, got {value!r}")
    return {
        "raw_header": raw_header,
        "media_type": "text/xml",
        "charset": "UTF-8" if parameters else None,
        "parameter_count": len(parameters),
    }


def require_original_gml_http(actual: dict[str, Any]) -> dict[str, Any]:
    """Keep every original exact HTTP gate except AUDIT-007 Content-Type syntax."""
    expected = {
        "requested_url": source.GML_URL,
        "final_url": source.GML_URL,
        "redirect_count": 0,
        "http_status": 200,
        "content_encoding": "",
    }
    for key, value in expected.items():
        if actual.get(key) != value:
            fail(f"original GML HTTP {key}: expected {value!r}, got {actual.get(key)!r}")
    return parse_original_gml_content_type(actual.get("content_type"))


def verify() -> tuple[dict[str, Any], dict[str, Any]]:
    if source.shapely.__version__ != "2.1.1":
        fail(f"Shapely 2.1.1 required, found {source.shapely.__version__}")
    if source.pyproj.__version__ != "3.7.2" or source.pyproj.proj_version_str != "9.5.1":
        fail("pyproj 3.7.2 / PROJ 9.5.1 required")

    cdr_body, cdr_http = source.fetch_exact(source.CDR_METADATA_URL, "text/csv")
    cdr_row = source.verify_cdr_metadata(cdr_body)
    require_http("CDR metadata", cdr_http, source.CDR_METADATA_URL, "text/csv;charset=UTF-8")
    if cdr_row != EXPECTED_CDR_ROW:
        fail(f"CDR metadata selected row mismatch: {cdr_row!r}")

    gml_body, gml_http = source.fetch_exact(
        source.GML_URL, "application/gml+xml, application/xml, text/xml"
    )
    source.verify_gml_last_modified(gml_http)
    gml_content_type = require_original_gml_http(gml_http)
    if gml_http.get("last_modified") != "Fri, 29 Sep 2023 10:15:07 GMT":
        fail(f"original GML Last-Modified mismatch: {gml_http.get('last_modified')!r}")
    gml_geometry, gml_parsed = source.parse_gml_huaih049(gml_body)
    gml_metrics = source.geometry_metrics(gml_geometry)
    require_exact_metrics("original GML", gml_metrics, EXPECTED_GML_METRICS)

    unrounded_body, unrounded_http = source.fetch_exact(
        source.UNROUNDED_URL, "application/geo+json, application/json"
    )
    unrounded_wgs84, unrounded_parsed, _ = source.parse_service(
        "unrounded service", unrounded_body, source.EXPECTED["unrounded"], require_valid=True
    )
    require_http(
        "unrounded service", unrounded_http, source.UNROUNDED_URL,
        "application/geo+json; charset=UTF-8",
    )
    if "geometryPrecision" in source.UNROUNDED_URL:
        fail("operational URL contains forbidden geometryPrecision")
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    unrounded_3035 = transform(transformer.transform, unrounded_wgs84)
    unrounded_metrics = source.geometry_metrics(unrounded_3035)
    require_exact_metrics("unrounded service", unrounded_metrics, EXPECTED_UNROUNDED_METRICS)
    if [float(value) for value in unrounded_wgs84.bounds] != EXPECTED_UNROUNDED_BBOX:
        fail(f"unrounded service bbox mismatch: {list(unrounded_wgs84.bounds)!r}")
    comparison, _ = source.comparison_metrics(gml_geometry, unrounded_3035)
    require_exact_metrics("GML/unrounded cross-check", comparison, EXPECTED_CROSS_CHECK)

    document = json.loads(unrounded_body)
    record = {
        "verification_pass": True,
        "operational_use": "AUDIT-001_only_unrounded_WISE_HUAIH049_2022",
        "coordinate_rounding_applied": False,
        "coordinates_persisted": False,
        "source_documents_persisted": False,
        "requested_url": unrounded_http["requested_url"],
        "final_url": unrounded_http["final_url"],
        "redirect_count": unrounded_http["redirect_count"],
        "status": unrounded_http["http_status"],
        "content_type": unrounded_http["content_type"],
        "content_encoding": unrounded_http["content_encoding"],
        "decompressed_bytes": unrounded_http["bytes"],
        "raw_sha256": unrounded_http["sha256"],
        "canonical_bytes": unrounded_parsed["canonical_bytes"],
        "canonical_sha256": unrounded_parsed["canonical_sha256"],
        "feature_count": len(document["features"]),
        "source_feature_id": unrounded_parsed["feature_id"],
        "geometry_type": unrounded_parsed["geometry_type"],
        "ring_count": 1,
        "coordinate_tuple_count_including_closure": unrounded_parsed[
            "coordinate_tuple_count_including_closure"
        ],
        "ring_is_closed": unrounded_parsed["ring_is_closed"],
        "bbox_wgs84": [float(value) for value in unrounded_wgs84.bounds],
        "geometry_is_valid": unrounded_parsed["is_valid"],
        "geometry_is_simple": unrounded_parsed["is_simple"],
        "thematic_id": unrounded_parsed["properties"]["thematicIdIdentifier"],
        "reporting_year": unrounded_parsed["properties"]["cYear"],
        "size_value": unrounded_parsed["properties"]["sizeValue"],
        "size_uom": unrounded_parsed["properties"]["sizeUom"],
        "properties": unrounded_parsed["properties"],
        "cdr_metadata": {
            "requested_url": cdr_http["requested_url"], "final_url": cdr_http["final_url"],
            "redirect_count": cdr_http["redirect_count"], "status": cdr_http["http_status"],
            "content_type": cdr_http["content_type"],
            "content_encoding": cdr_http["content_encoding"],
            "bytes": cdr_http["bytes"], "sha256": cdr_http["sha256"],
            "selected_row": cdr_row,
        },
        "original_gml": {
            "requested_url": gml_http["requested_url"], "final_url": gml_http["final_url"],
            "redirect_count": gml_http["redirect_count"], "status": gml_http["http_status"],
            "content_type": gml_http["content_type"],
            "content_type_parsed": gml_content_type,
            "content_encoding": gml_http["content_encoding"],
            "last_modified": gml_http["last_modified"],
            "bytes": gml_http["bytes"], "sha256": gml_http["sha256"],
            "parsed": gml_parsed, "metrics_epsg3035": gml_metrics,
        },
        "unrounded_metrics_epsg3035": unrounded_metrics,
        "gml_vs_unrounded_cross_check": {key: comparison[key] for key in EXPECTED_CROSS_CHECK},
        "runtime": {
            "python": source.platform.python_version(), "shapely": source.shapely.__version__,
            "geos": source.shapely.geos_version_string, "pyproj": source.pyproj.__version__,
            "proj": source.pyproj.proj_version_str,
        },
        "seven_decimal_history": {
            "operational_input": False,
            "status": "retained_as_invalid_rounding_failure_evidence_only",
            "self_intersection_wgs84": [18.0186091006542, 47.0275257639479],
        },
    }
    return document["features"][0]["geometry"], record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-ee", action="store_true")
    args = parser.parse_args()
    geometry_json, record = verify()
    print(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False))
    if args.emit_ee:
        print("\n// TRANSIENT VERIFIED UNROUNDED HUAIH049; DO NOT SAVE OR COMMIT.")
        print("var WISE_HUAIH049_SOURCE_RECORD = " +
              json.dumps(record, separators=(",", ":"), ensure_ascii=False) + ";")
        print("var WISE_HUAIH049_WGS84 = ee.Geometry(" +
              json.dumps(geometry_json, separators=(",", ":"), ensure_ascii=False) +
              ", 'EPSG:4326', true);")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
