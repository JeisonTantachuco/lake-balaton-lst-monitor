#!/usr/bin/env python3
"""Offline tests for the deterministic AUDIT-002 source comparison."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import unittest
from pathlib import Path

from shapely.geometry import Polygon


SCRIPT = Path(__file__).with_name("analyze_wise_huaih049_source_representations.py")
SPEC = importlib.util.spec_from_file_location("wise_audit_002", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load analysis module")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class Audit002Tests(unittest.TestCase):
    def test_exact_source_constants(self) -> None:
        self.assertEqual(module.EXPECTED["cdr"]["bytes"], 1_994_517)
        self.assertEqual(module.EXPECTED["gml"]["bytes"], 4_735_017)
        self.assertEqual(module.EXPECTED["unrounded"]["bytes"], 438_617)
        self.assertEqual(module.EXPECTED["p7"]["bytes"], 262_390)
        self.assertNotIn("geometryPrecision", module.UNROUNDED_URL)
        self.assertIn("geometryPrecision=7", module.P7_URL)

    def test_canonical_json_is_sorted_compact_utf8(self) -> None:
        value = {"z": [2, 1], "a": {"é": True}}
        expected = '{"a":{"é":true},"z":[2,1]}'.encode("utf-8")
        self.assertEqual(module.canonical_json_bytes(value), expected)

    def test_epsg3035_axis_swap(self) -> None:
        self.assertEqual(
            module.epsg3035_gml_northing_easting_to_xy(
                [2_693_665.2907, 4_930_719.6068, 2_693_589.0576, 4_930_717.3129]
            ),
            [(4_930_719.6068, 2_693_665.2907), (4_930_717.3129, 2_693_589.0576)],
        )
        with self.assertRaisesRegex(RuntimeError, "odd coordinate count"):
            module.epsg3035_gml_northing_easting_to_xy([1.0, 2.0, 3.0])

    def test_geometry_metrics_parts_holes_vertices(self) -> None:
        polygon = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
            holes=[[(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]],
        )
        metrics = module.geometry_metrics(polygon)
        self.assertEqual(metrics["geometry_type"], "Polygon")
        self.assertEqual(metrics["part_count"], 1)
        self.assertEqual(metrics["hole_count"], 1)
        self.assertEqual(metrics["vertex_count_including_ring_closure"], 10)
        self.assertAlmostEqual(metrics["area_m2"], 96.0)
        self.assertAlmostEqual(metrics["perimeter_m"], 48.0)

    def test_comparison_metrics_without_repair(self) -> None:
        left = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
        right = Polygon([(1, 0), (11, 0), (11, 10), (1, 10), (1, 0)])
        metrics, symmetric = module.comparison_metrics(left, right)
        self.assertAlmostEqual(metrics["absolute_area_difference_m2"], 0.0)
        self.assertAlmostEqual(metrics["symmetric_difference_m2"], 20.0)
        self.assertAlmostEqual(metrics["intersection_area_m2"], 90.0)
        self.assertAlmostEqual(metrics["gml_only_area_m2"], 10.0)
        self.assertAlmostEqual(metrics["unrounded_service_only_area_m2"], 10.0)
        self.assertAlmostEqual(metrics["hausdorff_distance_m"], 1.0)
        self.assertFalse(symmetric.is_empty)
        self.assertFalse(metrics["unexpected_land_classification_performed"])

    def test_rounding_diagnostics(self) -> None:
        full = [[18.123456749, 47.123456751], [18.0, 47.0]]
        rounded = [[18.1234567, 47.1234568], [18.0, 47.0]]
        result = module.coordinate_rounding_diagnostics(full, rounded)
        self.assertTrue(result["p7_equals_unrounded_rounded_to_7_decimals"])
        self.assertEqual(result["changed_coordinate_tuple_count"], 1)
        self.assertLessEqual(result["max_axis_perturbation_degrees"], 5e-8)

    def test_no_geometry_repair_invocation(self) -> None:
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        forbidden_attributes = {"make_valid"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, forbidden_attributes)
                if node.func.attr == "buffer" and node.args:
                    first = node.args[0]
                    self.assertFalse(
                        isinstance(first, ast.Constant) and first.value == 0,
                        "zero-distance buffer repair is forbidden",
                    )

    def test_generated_record_and_figures_contract(self) -> None:
        record_path = Path("docs/WHOLE_LAKE_GEOMETRY_REPAIR_SENSITIVITY_SOURCE_RECORD.json")
        self.assertTrue(record_path.is_file())
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertFalse(record["source_documents_persisted"])
        self.assertFalse(record["geometry_repair_performed"])
        self.assertFalse(record["earth_engine_run_performed"])
        self.assertTrue(record["original_gml"]["metrics_epsg3035"]["is_valid"])
        self.assertTrue(record["unrounded_service"]["metrics_epsg3035"]["is_valid"])
        self.assertFalse(record["seven_decimal_service"]["parsed"]["is_valid"])
        self.assertAlmostEqual(
            record["gml_vs_unrounded_service"]["symmetric_difference_m2"],
            11.503473830219795,
            places=9,
        )

        def keys(value: object) -> set[str]:
            if isinstance(value, dict):
                result = set(value)
                for child in value.values():
                    result.update(keys(child))
                return result
            if isinstance(value, list):
                result: set[str] = set()
                for child in value:
                    result.update(keys(child))
                return result
            return set()

        self.assertTrue({"coordinates", "raw_gml", "raw_geojson"}.isdisjoint(keys(record)))
        for figure in record["figures"].values():
            path = Path(figure)
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 10_000)

    def test_figure_and_report_caveats(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        report = Path("docs/WHOLE_LAKE_GEOMETRY_REPAIR_SENSITIVITY_REPORT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("symbolically exaggerated", script)
        self.assertIn("not to scale", script)
        self.assertIn("±25 m view does not visually resolve", script)
        self.assertIn("symbolically exaggerated", report)
        self.assertIn("not to scale", report)
        self.assertIn("coordinate order is preserved", report)
        self.assertNotIn("collapses or reorders", report)

if __name__ == "__main__":
    unittest.main(verbosity=2)
