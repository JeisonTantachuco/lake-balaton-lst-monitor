#!/usr/bin/env python3
"""AUDIT-002: compare immutable authoritative HUAIH049 representations.

All source documents are held in memory. Only the approved derived JSON record
and PNG figures are written. No geometry repair operation is performed.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import io
import json
import math
import platform
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import PIL
from PIL import Image, ImageDraw, ImageFont
import pyproj
import shapely
from pyproj import Transformer
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.ops import transform
from shapely.validation import explain_validity


CDR_METADATA_URL = (
    "https://sdi.eea.europa.eu/datashare/public.php/dav/files/"
    "dfCFqcjkNYEK7wY/CDR_metadata.csv"
)
GML_URL = (
    "https://cdr.eionet.europa.eu/hu/eu/wfd2022/spatial/envzrahxw/"
    "SurfaceWaterBody_HU_20220322.gml"
)
SERVICE_BASE = (
    "https://water.discomap.eea.europa.eu/arcgis/rest/services/WISE_WFD/"
    "WFD2022_SurfaceWaterBody_WM/MapServer/17/query?"
    "where=thematicIdIdentifier%3D%27HUAIH049%27%20AND%20cYear%3D2022"
    "&outFields=OBJECTID%2CinspireIdLocalId%2CinspireIdNamespace%2C"
    "inspireIdVersionId%2CthematicIdIdentifier%2CthematicIdIdentifierScheme%2C"
    "nameTextInternational%2CnameText%2CnameLanguage%2CsizeValue%2CsizeUom%2C"
    "meanDepth%2Clat%2Clon%2CcYear%2CcountryCode%2Clink"
    "&returnGeometry=true&outSR=4326"
)
UNROUNDED_URL = SERVICE_BASE + "&f=geojson"
P7_URL = SERVICE_BASE + "&geometryPrecision=7&f=geojson"

EXPECTED = {
    "cdr": {
        "bytes": 1_994_517,
        "sha256": "79663d602b8c20e64d97f59061766dc22a86e02063729b3a752f09c033875006",
    },
    "gml": {
        "bytes": 4_735_017,
        "sha256": "0604c6c3073dfb06faf98d0bce5b093be834c5de5a9ad78b326b30f094e809f2",
        "last_modified_date": "2023-09-29",
        "coordinate_tuple_count": 11_012,
    },
    "unrounded": {
        "bytes": 438_617,
        "sha256": "5d5f9c8edfced710fcc8657a6aceb398f14cd815d1c5e41a7df9f00601f312d8",
        "canonical_bytes": 427_942,
        "canonical_sha256": "394a929617bb975d2f3e3aa627abe26dbcc98f42fa48fe038757b3e734c35020",
    },
    "p7": {
        "bytes": 262_390,
        "sha256": "dddb4ffa9b8d3c0139292a94659fad0608003af87c4607b99843320013491e92",
        "canonical_bytes": 262_354,
        "canonical_sha256": "ae8feed16ebfd763acddd29e23275b9e61a89ddf2f9e2efe8d9b86b8dd767f19",
        "invalid_location_wgs84": [18.0186091006542, 47.0275257639479],
    },
    "reproducibility": {
        "gml_unrounded_area_difference_m2": 0.0590,
        "gml_unrounded_area_difference_percent": 9.93e-9,
        "symmetric_difference_m2": 11.5035,
        "symmetric_difference_percent": 1.936e-6,
        "hausdorff_distance_m": 0.0000994,
        "p7_max_coordinate_perturbation_degrees_upper_bound": 4.99993e-8,
    },
}

SERVICE_PROPERTIES = {
    "OBJECTID": 28586,
    "inspireIdLocalId": "HUAIH049",
    "inspireIdNamespace": "HU",
    "inspireIdVersionId": "v1.0",
    "thematicIdIdentifier": "HUAIH049",
    "thematicIdIdentifierScheme": "euSurfaceWaterBodyCode",
    "nameTextInternational": "LAKE BALATON",
    "nameText": "BALATON",
    "nameLanguage": "hun",
    "sizeValue": 594.327,
    "sizeUom": "km2",
    "meanDepth": 3.4,
    "lat": 46.8832,
    "lon": 17.84576,
    "cYear": 2022,
    "countryCode": "HU",
    "link": "http://www.vizeink.hu",
}

GML_IDENTITY = {
    "inspireIdLocalId": "HUAIH049",
    "inspireIdNamespace": "HU",
    "inspireIdVersionId": "v1.0",
    "thematicIdIdentifier": "HUAIH049",
    "thematicIdIdentifierScheme": "euSurfaceWaterBodyCode",
    "wiseEvolutionType": "noChange",
    "nameTextInternational": "Lake Balaton",
    "nameText": "Balaton",
    "nameLanguage": "hun",
    "specialisedZoneType": "lakeWaterBody",
    "sizeValue": "594.265",
    "sizeUom": "km2",
    "meanDepth": "3.4",
    "link": "http://www.vizeink.hu",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def fail(message: str) -> None:
    raise RuntimeError("AUDIT_002_FAIL_CLOSED: " + message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def fetch_exact(url: str, accept: str) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Accept-Encoding": "identity",
            "User-Agent": "lake-balaton-audit-002/1.0",
        },
    )
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(request, timeout=120) as response:
            body = response.read()
            record = {
                "requested_url": url,
                "final_url": response.geturl(),
                "redirect_count": 0,
                "http_status": response.status,
                "content_type": response.headers.get("Content-Type", ""),
                "content_encoding": response.headers.get("Content-Encoding", ""),
                "last_modified": response.headers.get("Last-Modified", ""),
                "bytes": len(body),
                "sha256": sha256(body),
            }
            if response.status != 200 or response.geturl() != url:
                fail(f"HTTP identity mismatch for {url}")
            if record["content_encoding"].lower() not in ("", "identity"):
                fail(f"encoded response forbidden for {url}: {record['content_encoding']}")
            return body, record
    except urllib.error.HTTPError as exc:
        fail(f"HTTP {exc.code} for {url}; redirects are forbidden")


def verify_bytes(label: str, body: bytes, expected: dict[str, Any]) -> None:
    if len(body) != expected["bytes"] or sha256(body) != expected["sha256"]:
        fail(f"{label} byte/hash mismatch: {len(body)} / {sha256(body)}")


def verify_cdr_metadata(body: bytes) -> dict[str, str]:
    verify_bytes("CDR metadata", body, EXPECTED["cdr"])
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
    matches = [
        row for row in rows
        if row["cYear"] == "2022" and row["countryCode"] == "HU"
        and row["dataset"] == "SurfaceWaterBody" and row["fileUrl"] == GML_URL
    ]
    if len(matches) != 1:
        fail(f"CDR metadata expected one exact HU/2022 SurfaceWaterBody row, got {len(matches)}")
    row = matches[0]
    required = {
        "isRestricted": "0",
        "useLimitation": "no conditions apply to access and use",
        "accessConstraints": "otherRestrictions",
    }
    for key, value in required.items():
        if row.get(key) != value:
            fail(f"CDR metadata {key} mismatch: {row.get(key)!r}")
    limitations = row.get("otherConstraints", "")
    for phrase in (
        "no conditions to access and use",
        "no limitations to public access",
        "no limitations on public access",
    ):
        if phrase not in limitations:
            fail(f"CDR metadata missing limitation phrase: {phrase}")
    return {key: row[key] for key in (
        "cYear", "countryCode", "dataset", "envUrl", "metadataUrl", "fileUrl",
        "isRestricted", "title", "useLimitation", "accessConstraints", "otherConstraints"
    )}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(feature: ET.Element, name: str) -> str | None:
    for element in feature.iter():
        if local_name(element.tag) == name:
            return element.text.strip() if element.text else ""
    return None


def epsg3035_gml_northing_easting_to_xy(values: list[float]) -> list[tuple[float, float]]:
    if len(values) % 2:
        fail("GML posList has odd coordinate count")
    return [(values[i + 1], values[i]) for i in range(0, len(values), 2)]


def parse_gml_huaih049(body: bytes) -> tuple[Polygon, dict[str, Any]]:
    verify_bytes("original GML", body, EXPECTED["gml"])
    root = ET.fromstring(body)
    candidates = []
    for element in root.iter():
        if local_name(element.tag) == "SurfaceWaterBody" and (
            child_text(element, "inspireIdLocalId") == "HUAIH049"
        ):
            candidates.append(element)
    if len(candidates) != 1:
        fail(f"GML expected one HUAIH049 feature, got {len(candidates)}")
    feature = candidates[0]
    identity = {key: child_text(feature, key) for key in GML_IDENTITY}
    if identity != GML_IDENTITY:
        fail(f"GML identity mismatch: {identity!r}")
    multisurfaces = [e for e in feature.iter() if local_name(e.tag) == "MultiSurface"]
    surfaces = [e for e in feature.iter() if local_name(e.tag) == "Surface"]
    polygon_patches = [e for e in feature.iter() if local_name(e.tag) == "PolygonPatch"]
    if len(multisurfaces) != 1 or len(surfaces) != 1 or len(polygon_patches) != 1:
        fail("GML structure must be one MultiSurface, one Surface, one PolygonPatch")
    crs_elements = [
        element for element in (multisurfaces[0], surfaces[0])
        if element.attrib.get("srsName") or element.attrib.get("srsDimension")
    ]
    if len(crs_elements) != 1:
        fail(f"GML expected one CRS-bearing MultiSurface/Surface, got {len(crs_elements)}")
    srs_name = crs_elements[0].attrib.get("srsName")
    srs_dimension = crs_elements[0].attrib.get("srsDimension")
    if srs_name != "urn:ogc:def:crs:EPSG::3035" or srs_dimension != "2":
        fail(f"GML CRS/dimension mismatch: {srs_name!r}/{srs_dimension!r}")
    exteriors = [e for e in polygon_patches[0].iter() if local_name(e.tag) == "exterior"]
    interiors = [e for e in polygon_patches[0].iter() if local_name(e.tag) == "interior"]
    if len(exteriors) != 1 or interiors:
        fail(f"GML expected one exterior and no holes, got {len(exteriors)}/{len(interiors)}")
    pos_lists = [e for e in exteriors[0].iter() if local_name(e.tag) == "posList"]
    if len(pos_lists) != 1 or not pos_lists[0].text:
        fail("GML exterior must contain one posList")
    values = [float(value) for value in pos_lists[0].text.split()]
    # EPSG:3035 is northing/easting in this GML. Shapely requires x/y, so swap.
    coordinates = epsg3035_gml_northing_easting_to_xy(values)
    if len(coordinates) != EXPECTED["gml"]["coordinate_tuple_count"]:
        fail(f"GML coordinate tuple count {len(coordinates)}")
    if coordinates[0] != coordinates[-1]:
        fail("GML ring is not closed")
    geometry = Polygon(coordinates)
    if geometry.is_empty or not geometry.is_valid or not geometry.is_simple:
        fail(f"GML authoritative geometry invalid: {explain_validity(geometry)}")
    record = {
        "identity": identity,
        "srs_name": srs_name,
        "srs_dimension": srs_dimension,
        "crs_bearing_element": local_name(crs_elements[0].tag),
        "axis_order_in_document": "northing_easting",
        "shapely_coordinate_order": "easting_northing",
        "axis_swap_applied": True,
        "geometry_type": geometry.geom_type,
        "part_count": 1,
        "hole_count": len(geometry.interiors),
        "coordinate_tuple_count_including_closure": len(coordinates),
        "is_empty": geometry.is_empty,
        "is_valid": geometry.is_valid,
        "is_simple": geometry.is_simple,
    }
    return geometry, record


def verify_gml_last_modified(record: dict[str, Any]) -> None:
    text = record["last_modified"]
    try:
        parsed = email.utils.parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        fail(f"GML Last-Modified is unparsable: {text!r}")
    if parsed != EXPECTED["gml"]["last_modified_date"]:
        fail(f"GML Last-Modified date mismatch: {parsed}")


def parse_service(
    label: str, body: bytes, expected: dict[str, Any], require_valid: bool
) -> tuple[Polygon, dict[str, Any], list[list[float]]]:
    verify_bytes(label, body, expected)
    document = json.loads(body)
    canonical = canonical_json_bytes(document)
    if len(canonical) != expected["canonical_bytes"] or sha256(canonical) != expected["canonical_sha256"]:
        fail(f"{label} canonical byte/hash mismatch")
    features = document.get("features", [])
    if len(features) != 1:
        fail(f"{label} expected one feature")
    feature = features[0]
    if feature.get("id") != 28586 or feature.get("properties") != SERVICE_PROPERTIES:
        fail(f"{label} identity/property mismatch")
    geometry_json = feature.get("geometry", {})
    coordinates = geometry_json.get("coordinates", [])
    if geometry_json.get("type") != "Polygon" or len(coordinates) != 1:
        fail(f"{label} expected Polygon with one ring")
    ring = coordinates[0]
    if len(ring) != 11_012 or ring[0] != ring[-1]:
        fail(f"{label} ring structure mismatch")
    geometry = shape(geometry_json)
    if require_valid and (geometry.is_empty or not geometry.is_valid or not geometry.is_simple):
        fail(f"{label} authoritative geometry invalid: {explain_validity(geometry)}")
    record = {
        "feature_id": feature["id"],
        "properties": feature["properties"],
        "geometry_type": geometry.geom_type,
        "part_count": 1,
        "hole_count": len(geometry.interiors),
        "coordinate_tuple_count_including_closure": len(ring),
        "ring_is_closed": ring[0] == ring[-1],
        "is_empty": geometry.is_empty,
        "is_valid": geometry.is_valid,
        "is_simple": geometry.is_simple,
        "validity_explanation": explain_validity(geometry),
        "canonical_bytes": len(canonical),
        "canonical_sha256": sha256(canonical),
    }
    return geometry, record, ring


def polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        result: list[Polygon] = []
        for part in geometry.geoms:
            result.extend(polygon_parts(part))
        return result
    return []


def vertex_count(geometry: Any) -> int:
    total = 0
    for polygon in polygon_parts(geometry):
        total += len(polygon.exterior.coords)
        total += sum(len(ring.coords) for ring in polygon.interiors)
    return total


def geometry_metrics(geometry: Any) -> dict[str, Any]:
    parts = polygon_parts(geometry)
    return {
        "geometry_type": geometry.geom_type,
        "part_count": len(parts),
        "hole_count": sum(len(part.interiors) for part in parts),
        "vertex_count_including_ring_closure": vertex_count(geometry),
        "is_empty": geometry.is_empty,
        "is_valid": geometry.is_valid,
        "is_simple": geometry.is_simple,
        "validity_explanation": explain_validity(geometry),
        "area_m2": float(geometry.area),
        "perimeter_m": float(geometry.length),
        "bounds_epsg3035": [float(value) for value in geometry.bounds],
    }


def coordinate_rounding_diagnostics(
    unrounded_ring: list[list[float]], p7_ring: list[list[float]]
) -> dict[str, Any]:
    if len(unrounded_ring) != len(p7_ring):
        fail("unrounded/p7 coordinate tuple counts differ")
    exact_round_match = True
    max_axis_perturbation = 0.0
    max_euclidean_perturbation = 0.0
    changed_tuples = 0
    for full, rounded in zip(unrounded_ring, p7_ring):
        if [round(full[0], 7), round(full[1], 7)] != rounded:
            exact_round_match = False
        dx = abs(full[0] - rounded[0])
        dy = abs(full[1] - rounded[1])
        max_axis_perturbation = max(max_axis_perturbation, dx, dy)
        max_euclidean_perturbation = max(max_euclidean_perturbation, math.hypot(dx, dy))
        if dx or dy:
            changed_tuples += 1
    if not exact_round_match:
        fail("p7 coordinates do not exactly equal unrounded coordinates rounded to seven decimals")
    return {
        "p7_equals_unrounded_rounded_to_7_decimals": exact_round_match,
        "changed_coordinate_tuple_count": changed_tuples,
        "max_axis_perturbation_degrees": max_axis_perturbation,
        "max_euclidean_perturbation_degrees": max_euclidean_perturbation,
        "expected_max_axis_upper_bound_degrees":
            EXPECTED["reproducibility"]["p7_max_coordinate_perturbation_degrees_upper_bound"],
        "max_axis_deviation_from_expected_upper_bound_degrees":
            max_axis_perturbation
            - EXPECTED["reproducibility"]["p7_max_coordinate_perturbation_degrees_upper_bound"],
    }


def comparison_metrics(gml: Polygon, service_3035: Polygon) -> tuple[dict[str, Any], Any]:
    symmetric = gml.symmetric_difference(service_3035)
    gml_only = gml.difference(service_3035)
    service_only = service_3035.difference(gml)
    intersection = gml.intersection(service_3035)
    area_difference = abs(gml.area - service_3035.area)
    symmetric_area = symmetric.area
    gml_area = gml.area
    hausdorff = gml.hausdorff_distance(service_3035)
    expected = EXPECTED["reproducibility"]
    metrics = {
        "absolute_area_difference_m2": area_difference,
        "absolute_area_difference_percent_of_gml": area_difference / gml_area * 100,
        "symmetric_difference_m2": symmetric_area,
        "symmetric_difference_percent_of_gml": symmetric_area / gml_area * 100,
        "hausdorff_distance_m": hausdorff,
        "intersection_area_m2": intersection.area,
        "gml_only_area_m2": gml_only.area,
        "unrounded_service_only_area_m2": service_only.area,
        "symmetric_difference_part_count": len(polygon_parts(symmetric)),
        "gml_only_part_count": len(polygon_parts(gml_only)),
        "unrounded_service_only_part_count": len(polygon_parts(service_only)),
        "unexpected_land_classification_performed": False,
        "unexpected_land_note": (
            "No independent land mask is approved; land interpretation is limited to visual review."
        ),
        "expected_reproducibility_values": expected,
        "deviations_from_expected": {
            "area_difference_m2": area_difference - expected["gml_unrounded_area_difference_m2"],
            "area_difference_percent": area_difference / gml_area * 100
            - expected["gml_unrounded_area_difference_percent"],
            "symmetric_difference_m2": symmetric_area - expected["symmetric_difference_m2"],
            "symmetric_difference_percent": symmetric_area / gml_area * 100
            - expected["symmetric_difference_percent"],
            "hausdorff_distance_m": hausdorff - expected["hausdorff_distance_m"],
        },
    }
    return metrics, symmetric


COLORS = {
    "background": "#f7f7f3",
    "gml": "#0066cc",
    "service": "#e34a33",
    "p7": "#202020",
    "symmetric": "#984ea3",
    "marker": "#ffcc00",
    "text": "#111111",
}


def geometry_lines(geometry: Any) -> Iterable[list[tuple[float, float]]]:
    for polygon in polygon_parts(geometry):
        yield list(polygon.exterior.coords)
        for interior in polygon.interiors:
            yield list(interior.coords)


def draw_geometries(
    draw: ImageDraw.ImageDraw,
    geometries: list[tuple[Any, str, int]],
    box: tuple[int, int, int, int],
    bounds: tuple[float, float, float, float],
) -> None:
    left, top, right, bottom = box
    minx, miny, maxx, maxy = bounds
    dx = max(maxx - minx, 1e-12)
    dy = max(maxy - miny, 1e-12)
    margin = 0.04
    scale = min((right - left) * (1 - 2 * margin) / dx,
                (bottom - top) * (1 - 2 * margin) / dy)
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2

    def pixel(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return ((left + right) / 2 + (x - cx) * scale,
                (top + bottom) / 2 - (y - cy) * scale)

    for geometry, color, width in geometries:
        for line in geometry_lines(geometry):
            if len(line) >= 2:
                draw.line([pixel(point) for point in line], fill=color, width=width, joint="curve")


def draw_geometries_clipped(
    image: Image.Image,
    geometries: list[tuple[Any, str, int]],
    box: tuple[int, int, int, int],
    bounds: tuple[float, float, float, float],
) -> None:
    """Render into an isolated panel so geometry outside `box` is clipped."""
    left, top, right, bottom = box
    panel = Image.new("RGB", (right - left, bottom - top), COLORS["background"])
    panel_draw = ImageDraw.Draw(panel)
    draw_geometries(
        panel_draw, geometries, (0, 0, panel.width, panel.height), bounds
    )
    image.paste(panel, (left, top))
    ImageDraw.Draw(image).rectangle(box, outline="#cccccc", width=1)


def title(draw: ImageDraw.ImageDraw, text: str, y: int) -> None:
    draw.text((30, y), text, fill=COLORS["text"], font=ImageFont.load_default(size=20))


def save_self_intersection_figure(
    path: Path, p7_3035: Polygon, intersection_3035: tuple[float, float], explanation: str
) -> None:
    image = Image.new("RGB", (1800, 1000), COLORS["background"])
    draw = ImageDraw.Draw(image)
    title(draw, "WISE HUAIH049: seven-decimal service self-intersection", 20)
    x, y = intersection_3035
    radius = 25
    bounds = (x - radius, y - radius, x + radius, y + radius)
    draw_geometries(draw, [(p7_3035, COLORS["p7"], 4)], (30, 80, 1770, 900), bounds)
    left, top, right, bottom = (30, 80, 1770, 900)
    px, py = (left + right) / 2, (top + bottom) / 2
    draw.ellipse((px - 16, py - 16, px + 16, py + 16),
                 outline="#cc0000", width=4)
    draw.line((px - 24, py, px + 24, py), fill="#cc0000", width=2)
    draw.line((px, py - 24, px, py + 24), fill="#cc0000", width=2)
    draw.text((30, 915),
              "Location map only: the ±25 m view does not visually resolve the sub-centimetre crossing.",
              fill=COLORS["text"], font=ImageFont.load_default(size=16))
    draw.text((30, 945), explanation, fill=COLORS["text"], font=ImageFont.load_default(size=16))
    image.save(path, format="PNG")


def save_authoritative_comparison(path: Path, gml: Polygon, service: Polygon) -> None:
    image = Image.new("RGB", (1800, 1000), COLORS["background"])
    draw = ImageDraw.Draw(image)
    title(draw, "HUAIH049 authoritative source representations (EPSG:3035)", 20)
    bounds = gml.union(service).bounds
    draw_geometries(draw, [(gml, COLORS["gml"], 5), (service, COLORS["service"], 2)],
                    (30, 80, 1770, 900), bounds)
    draw.text((30, 925), "Blue: original CDR GML   Red: unrounded WISE service",
              fill=COLORS["text"], font=ImageFont.load_default(size=18))
    image.save(path, format="PNG")


def save_symmetric_difference(path: Path, gml: Polygon, service: Polygon, symmetric: Any) -> None:
    image = Image.new("RGB", (1800, 1000), COLORS["background"])
    draw = ImageDraw.Draw(image)
    title(draw, "GML versus unrounded service: symmetric-difference evidence", 20)
    draw_geometries_clipped(
        image,
        [(gml, COLORS["gml"], 2), (service, COLORS["service"], 1),
         (symmetric, COLORS["symmetric"], 3)],
        (30, 80, 880, 880), gml.union(service).bounds
    )
    parts = sorted(polygon_parts(symmetric), key=lambda part: part.area, reverse=True)
    if parts:
        minx, miny, maxx, maxy = parts[0].bounds
        pad = max(maxx - minx, maxy - miny, 0.01) * 0.08
        zoom = ((minx + maxx) / 2 - pad, (miny + maxy) / 2 - pad,
                (minx + maxx) / 2 + pad, (miny + maxy) / 2 + pad)
        draw_geometries_clipped(
            image,
            [(gml, COLORS["gml"], 2), (service, COLORS["service"], 1),
             (parts[0], COLORS["symmetric"], 5)],
            (920, 80, 1770, 880), zoom
        )
    draw.text((30, 900),
              "Purple: symmetric difference. Right: largest component clipped to its padded bounds.",
              fill=COLORS["text"], font=ImageFont.load_default(size=16))
    draw.text((30, 935),
              "Difference strokes are symbolically exaggerated for visibility and are not to scale.",
              fill=COLORS["text"], font=ImageFont.load_default(size=18))
    image.save(path, format="PNG")


def analyze(output_record: Path, figures_dir: Path) -> dict[str, Any]:
    if shapely.__version__ != "2.1.1":
        fail(f"Shapely 2.1.1 required, found {shapely.__version__}")
    if pyproj.__version__ != "3.7.2":
        fail(f"pyproj 3.7.2 required, found {pyproj.__version__}")
    if PIL.__version__ != "12.3.0":
        fail(f"Pillow 12.3.0 required, found {PIL.__version__}")

    cdr_body, cdr_http = fetch_exact(CDR_METADATA_URL, "text/csv")
    cdr_row = verify_cdr_metadata(cdr_body)
    gml_body, gml_http = fetch_exact(GML_URL, "application/gml+xml, application/xml, text/xml")
    verify_gml_last_modified(gml_http)
    gml_geometry, gml_record = parse_gml_huaih049(gml_body)
    unrounded_body, unrounded_http = fetch_exact(
        UNROUNDED_URL, "application/geo+json, application/json"
    )
    unrounded_wgs84, unrounded_record, unrounded_ring = parse_service(
        "unrounded service", unrounded_body, EXPECTED["unrounded"], require_valid=True
    )
    p7_body, p7_http = fetch_exact(P7_URL, "application/geo+json, application/json")
    p7_wgs84, p7_record, p7_ring = parse_service(
        "seven-decimal service", p7_body, EXPECTED["p7"], require_valid=False
    )
    if p7_wgs84.is_valid or p7_wgs84.is_simple:
        fail("seven-decimal evidence unexpectedly became valid/simple")
    expected_location = EXPECTED["p7"]["invalid_location_wgs84"]
    if not all(token in p7_record["validity_explanation"] for token in
               (str(expected_location[0]), str(expected_location[1]))):
        fail(f"p7 invalidity location changed: {p7_record['validity_explanation']}")

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    unrounded_3035 = transform(transformer.transform, unrounded_wgs84)
    p7_3035 = transform(transformer.transform, p7_wgs84)
    if unrounded_3035.is_empty or not unrounded_3035.is_valid or not unrounded_3035.is_simple:
        fail("transformed unrounded authoritative geometry invalid")
    comparison, symmetric = comparison_metrics(gml_geometry, unrounded_3035)
    rounding = coordinate_rounding_diagnostics(unrounded_ring, p7_ring)
    intersection_xy = transformer.transform(*expected_location)

    figures_dir.mkdir(parents=True, exist_ok=True)
    figure_paths = {
        "p7_self_intersection": figures_dir / "wise_huaih049_self_intersection.png",
        "authoritative_comparison": figures_dir / "wise_huaih049_authoritative_comparison.png",
        "symmetric_difference": figures_dir / "wise_huaih049_symmetric_difference.png",
    }
    save_self_intersection_figure(
        figure_paths["p7_self_intersection"], p7_3035, intersection_xy,
        p7_record["validity_explanation"]
    )
    save_authoritative_comparison(
        figure_paths["authoritative_comparison"], gml_geometry, unrounded_3035
    )
    save_symmetric_difference(
        figure_paths["symmetric_difference"], gml_geometry, unrounded_3035, symmetric
    )

    record = {
        "audit_id": "AUDIT-002",
        "analysis_status": "completed_read_only_source_representation_comparison",
        "analysis_date_utc": dt.date.today().isoformat(),
        "source_documents_persisted": False,
        "geometry_repair_performed": False,
        "earth_engine_run_performed": False,
        "runtime": {
            "python": platform.python_version(),
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
            "pyproj": pyproj.__version__,
            "proj": pyproj.proj_version_str,
            "pillow": PIL.__version__,
        },
        "cdr_metadata": {"http": cdr_http, "selected_row": cdr_row},
        "original_gml": {
            "http": gml_http,
            "parsed": gml_record,
            "metrics_epsg3035": geometry_metrics(gml_geometry),
        },
        "unrounded_service": {
            "http": unrounded_http,
            "parsed": unrounded_record,
            "metrics_epsg3035": geometry_metrics(unrounded_3035),
        },
        "seven_decimal_service": {
            "http": p7_http,
            "parsed": p7_record,
            "metrics_epsg3035_unrepaired_invalid_evidence": geometry_metrics(p7_3035),
            "self_intersection_wgs84": expected_location,
            "rounding_diagnostics": rounding,
        },
        "gml_vs_unrounded_service": comparison,
        "fragment_overlap_diagnostics": {
            "source_part_count_gml": 1,
            "source_part_count_unrounded_service": 1,
            "symmetric_difference_part_count": comparison["symmetric_difference_part_count"],
            "gml_only_part_count": comparison["gml_only_part_count"],
            "unrounded_service_only_part_count": comparison[
                "unrounded_service_only_part_count"
            ],
            "intersection_area_m2": comparison["intersection_area_m2"],
            "gml_only_area_m2": comparison["gml_only_area_m2"],
            "unrounded_service_only_area_m2": comparison[
                "unrounded_service_only_area_m2"
            ],
            "unexpected_land_classification_performed": False,
            "interpretation_limit": (
                "No independent land mask is approved; unexpected-land interpretation is visual only."
            ),
        },
        "figures": {key: str(value.as_posix()) for key, value in figure_paths.items()},
    }
    output_record.parent.mkdir(parents=True, exist_ok=True)
    output_record.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-record",
        type=Path,
        default=Path("docs/WHOLE_LAKE_GEOMETRY_REPAIR_SENSITIVITY_SOURCE_RECORD.json"),
    )
    parser.add_argument("--figures-dir", type=Path, default=Path("docs/figures"))
    args = parser.parse_args()
    record = analyze(args.output_record, args.figures_dir)
    print(json.dumps({
        "analysis_status": record["analysis_status"],
        "output_record": str(args.output_record),
        "figures": record["figures"],
        "gml_vs_unrounded_service": record["gml_vs_unrounded_service"],
        "seven_decimal_validity": record["seven_decimal_service"]["parsed"][
            "validity_explanation"
        ],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
