#!/usr/bin/env python3
"""Offline tests for the narrow AUDIT-007 original-GML Content-Type gate."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_wise_huaih049.py")
SPEC = importlib.util.spec_from_file_location("wise_audit_003_verifier_test", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load verifier")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class Audit007ContentTypeTests(unittest.TestCase):
    def test_accepts_exact_media_type_without_parameters(self) -> None:
        for raw in ("text/xml", "TEXT/XML", " Text/Xml ", "\ttext/xml\t"):
            with self.subTest(raw=raw):
                parsed = module.parse_original_gml_content_type(raw)
                self.assertEqual(parsed["raw_header"], raw)
                self.assertEqual(parsed["media_type"], "text/xml")
                self.assertIsNone(parsed["charset"])
                self.assertEqual(parsed["parameter_count"], 0)

    def test_accepts_exactly_one_case_insensitive_utf8_charset(self) -> None:
        accepted = (
            "text/xml;charset=UTF-8",
            "TEXT/XML; CHARSET=utf-8",
            "text/xml ; charset = Utf-8",
            'text/xml; charset="UTF-8"',
            'text/xml;charset="utf\\-8"',
        )
        for raw in accepted:
            with self.subTest(raw=raw):
                parsed = module.parse_original_gml_content_type(raw)
                self.assertEqual(parsed["raw_header"], raw)
                self.assertEqual(parsed["charset"], "UTF-8")
                self.assertEqual(parsed["parameter_count"], 1)

    def test_rejects_wrong_media_type_and_charset(self) -> None:
        rejected = (
            "application/xml",
            "text/plain",
            "text/xml;charset=latin-1",
            "text/xml;charset=utf8",
            'text/xml;charset="UTF-16"',
        )
        for raw in rejected:
            with self.subTest(raw=raw), self.assertRaisesRegex(
                    RuntimeError, "WISE_UNROUNDED_SOURCE_VERIFICATION_FAILED"):
                module.parse_original_gml_content_type(raw)

    def test_rejects_duplicate_and_unknown_parameters(self) -> None:
        rejected = (
            "text/xml;charset=UTF-8;charset=UTF-8",
            "text/xml;CHARSET=UTF-8;charset=utf-8",
            "text/xml;boundary=x",
            "text/xml;charset=UTF-8;boundary=x",
            "text/xml;boundary=x;charset=UTF-8",
        )
        for raw in rejected:
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                module.parse_original_gml_content_type(raw)

    def test_rejects_malformed_syntax(self) -> None:
        rejected = (
            None, "", "textxml", "text/", "/xml", "text/xml;",
            "text/xml;charset", "text/xml;charset=", "text/xml;=UTF-8",
            'text/xml;charset="UTF-8', "text/xml, charset=UTF-8",
            "text/xml\r\ncharset=UTF-8", "text/xml;;charset=UTF-8",
        )
        for raw in rejected:
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                module.parse_original_gml_content_type(raw)

    def test_original_gml_http_retains_all_other_exact_gates(self) -> None:
        observed = {
            "requested_url": module.source.GML_URL,
            "final_url": module.source.GML_URL,
            "redirect_count": 0,
            "http_status": 200,
            "content_type": "text/xml; charset=utf-8",
            "content_encoding": "",
        }
        parsed = module.require_original_gml_http(observed)
        self.assertEqual(parsed["raw_header"], observed["content_type"])
        for field, bad_value in (
                ("requested_url", "https://invalid.example/changed"),
                ("final_url", "https://invalid.example/redirect"),
                ("redirect_count", 1), ("http_status", 206),
                ("content_encoding", "gzip")):
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                module.require_original_gml_http({**observed, field: bad_value})


if __name__ == "__main__":
    unittest.main(verbosity=2)
