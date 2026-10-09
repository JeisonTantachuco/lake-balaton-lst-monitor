#!/usr/bin/env python3
"""Windows wall-clock/process-tree supervisor for AUDIT-012."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tools" / "run_nighttime_qa_candidate_comparison_ee.py"
BASE_SUPERVISOR_PATH = ROOT / "tools" / "supervise_whole_lake_boundary_shoreline_audit.py"
EXPECTED_RUNNER_SHA256 = "0682897404d20498996e7a73742c604ad350ad409cbb6c40b3071111a5d16760"
EXPECTED_BASE_SUPERVISOR_SHA256 = "8614de215b21e1722520f482c22516c04dea13950d58ba194ded252e9cfd7064"
IMPLEMENTATION = "nighttime_qa_candidate_comparison_windows_supervisor_v14_h19v04_date_batched_comparison"
REQUEST_LIMIT_SECONDS = 480.000
SESSION_LIMIT_SECONDS = 165 * 60
TIMEOUT_EXIT_CODE = 124
PROTOCOL_EXIT_CODE = 125
WINDOWS = ("winter_2024", "spring_2024", "summer_2024", "autumn_2024")
STREAMS = ("terra_night", "aqua_night")
TREATMENTS = ("EROSION_0000M", "EROSION_0463_3127M", "EROSION_0500M", "EROSION_0926_6254M")
# 8 earliest-anomaly probes + 32 (window x stream x treatment) comparisons each
# split into 7 two-date batches -> 8 + 224 tail requests, all category-normalized
# to "unclassified_phase".
EARLIEST_ANOMALY_PROBE_REQUESTS = 8
COMPARISON_BATCHES_PER_TREATMENT = 7
EE_SEQUENCE = (
    "canonical_projection", "canonical_reference_id",
    "canonical_projection", "canonical_reference_id", "runtime_fixture",
) + ("projection_inventory",) * 8 + ("unclassified_phase",) * (
    EARLIEST_ANOMALY_PROBE_REQUESTS + 32 * COMPARISON_BATCHES_PER_TREATMENT)
SOURCE_IDENTITIES = tuple((window, stream) for window in WINDOWS for stream in STREAMS)
TERMINAL_KEY = "NIGHTTIME_QA_CANDIDATE_COMPARISON_COMPLETE"
_RUNNER_CONTRACT: Any = None
_BASE_CONTRACT: Any = None


class SupervisorError(RuntimeError):
    pass


class DuplicateKey(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(path: Path, expected: str, name: str) -> Any:
    if sha256_file(path) != expected:
        raise SupervisorError(name + "_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location(name.casefold(), path)
    if spec is None or spec.loader is None:
        raise SupervisorError(name + "_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runner() -> Any:
    global _RUNNER_CONTRACT
    if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
        raise SupervisorError("PINNED_AUDIT012_RUNNER_SHA256_MISMATCH")
    if _RUNNER_CONTRACT is None:
        _RUNNER_CONTRACT = load_module(
            RUNNER_PATH, EXPECTED_RUNNER_SHA256, "PINNED_AUDIT012_RUNNER")
    return _RUNNER_CONTRACT


def load_base() -> Any:
    global _BASE_CONTRACT
    if sha256_file(BASE_SUPERVISOR_PATH) != EXPECTED_BASE_SUPERVISOR_SHA256:
        raise SupervisorError("PINNED_WINDOWS_JOB_SUPERVISOR_SHA256_MISMATCH")
    if _BASE_CONTRACT is None:
        _BASE_CONTRACT = load_module(
            BASE_SUPERVISOR_PATH, EXPECTED_BASE_SUPERVISOR_SHA256,
            "PINNED_WINDOWS_JOB_SUPERVISOR")
    return _BASE_CONTRACT


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result


def strict_json(line: str) -> Any:
    try:
        return json.loads(line, object_pairs_hook=reject_duplicates,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except Exception as exc:
        raise SupervisorError("MARKED_JSON_MALFORMED") from exc


def parse_marker(line: str) -> tuple[str, dict[str, Any]] | None:
    names = {"PHASE_REQUEST_START", "PHASE_REQUEST_COMPLETE", "PHASE_REQUEST_FAILED",
             "SOURCE_REQUEST_START", "SOURCE_REQUEST_COMPLETE", "SOURCE_REQUEST_FAILED"}
    if not any(name in line for name in names):
        return None
    value = strict_json(line)
    if not isinstance(value, dict) or len(value) != 1 or next(iter(value)) not in names:
        raise SupervisorError("MARKER_WRAPPER_FAILED")
    marker, event = next(iter(value.items()))
    if not isinstance(event, dict):
        raise SupervisorError("MARKER_EVENT_FAILED")
    if marker.endswith("START"):
        if set(event) != {"phase", "attempt", "max_attempts", "request_deadline_seconds"} or \
           event["attempt"] != 1 or event["max_attempts"] != 1 or \
           event["request_deadline_seconds"] != 480:
            raise SupervisorError("MARKER_START_CONTRACT_FAILED")
    elif marker.endswith("COMPLETE"):
        if set(event) != {"phase", "attempt", "elapsed_seconds"} or event["attempt"] != 1:
            raise SupervisorError("MARKER_COMPLETE_CONTRACT_FAILED")
    else:
        expected = {"phase", "attempt", "elapsed_seconds", "exception_category"}
        if set(event) != expected or event["attempt"] != 1 or not isinstance(
                event["exception_category"], str):
            raise SupervisorError("MARKER_FAILURE_CONTRACT_FAILED")
    if not isinstance(event.get("phase"), str) or not event["phase"]:
        raise SupervisorError("MARKER_PHASE_FAILED")
    if not marker.endswith("START"):
        elapsed = event["elapsed_seconds"]
        if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or \
           not math.isfinite(elapsed) or elapsed < 0:
            raise SupervisorError("MARKER_ELAPSED_FAILED")
    return marker, event


def parse_terminal(line: str) -> dict[str, Any] | None:
    if TERMINAL_KEY not in line:
        return None
    value = strict_json(line)
    if not isinstance(value, dict) or set(value) != {TERMINAL_KEY}:
        raise SupervisorError("TERMINAL_WRAPPER_FAILED")
    payload = value[TERMINAL_KEY]
    runner = load_runner()
    expected_keys = {
        "specification", "implementation", "coordinate_free",
        "source_coordinate_arrays_included", "candidate_definitions",
        "candidate_ordering_interpretation", "joint_qc_table_encoding",
        "request_decomposition", "projection_certification_digests", "observation_count",
        "treatment_record_count", "result_count", "results",
        "seasonal_candidate_summaries", "shoreline_sensitivity_summaries",
        "temperature_and_ancillary_selectivity", "original_nasa_hdf_source_verification",
        "nasa_network_transaction_count",
        "validation_errors", "pass", "scientific_interpretation",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys or \
       payload["specification"] != runner.SPECIFICATION or \
       payload["implementation"] != runner.IMPLEMENTATION or \
       payload["coordinate_free"] is not True or \
       payload["source_coordinate_arrays_included"] is not False or \
       payload["candidate_definitions"] != runner.CANDIDATES or \
       payload["request_decomposition"] != runner.REQUEST_DECOMPOSITION or \
       payload["observation_count"] != 112 or payload["treatment_record_count"] != 448 or \
       payload["result_count"] != 32 or payload["validation_errors"] != [] or \
       payload["pass"] is not True:
        raise SupervisorError("TERMINAL_CONTRACT_FAILED")
    if payload["candidate_ordering_interpretation"] != (
            "A is non-nested with B and C; B is an exact subset of C; no candidate is selected") or \
       payload["joint_qc_table_encoding"] != (
            "fixed arrays indexed by raw QC byte q=0..255; M=q&3,D=(q>>2)&3,E=(q>>4)&3,T=(q>>6)&3") or \
       payload["scientific_interpretation"] != (
            "Bounded simultaneous A/B/C diagnostic comparison only. It selects no QA rule and "
            "does not change or relax the completed strict audit mask."):
        raise SupervisorError("TERMINAL_INTERPRETATION_FAILED")
    results = payload["results"]
    expected = [(window, stream, treatment) for window in runner.WINDOWS
                for stream in [item for item in runner.load_audit().STREAMS
                               if item["stream_id"] in runner.NIGHT_STREAM_IDS]
                for treatment in runner.load_audit().TREATMENTS]
    if not isinstance(results, list) or len(results) != 32:
        raise SupervisorError("TERMINAL_RESULT_COUNT_FAILED")
    for result, (window, stream, treatment) in zip(results, expected):
        errors, transient = runner.validate_result(copy.deepcopy(result), window, stream, treatment)
        if errors or transient:
            raise SupervisorError("TERMINAL_RESULT_REVALIDATION_FAILED")
    seasonal, shoreline = runner.build_summaries(results)
    if payload["seasonal_candidate_summaries"] != seasonal or \
       payload["shoreline_sensitivity_summaries"] != shoreline or \
       payload["temperature_and_ancillary_selectivity"] != runner.temperature_selectivity(results):
        raise SupervisorError("TERMINAL_SUMMARY_REVALIDATION_FAILED")
    digests = payload["projection_certification_digests"]
    expected_digest_ids = [(window, stream) for window in WINDOWS for stream in STREAMS]
    if not isinstance(digests, list) or len(digests) != 8 or [
            (item.get("window_id"), item.get("stream_id")) for item in digests
            if isinstance(item, dict)] != expected_digest_ids or any(
                set(item) != {"window_id", "stream_id", "record_count",
                              "source_image_ids_sha256", "projection_inventory_sha256", "pass"} or
                item["record_count"] != 14 or item["pass"] is not True or
                not re.fullmatch(r"[0-9a-f]{64}", item["source_image_ids_sha256"]) or
                not re.fullmatch(r"[0-9a-f]{64}", item["projection_inventory_sha256"])
                for item in digests):
        raise SupervisorError("TERMINAL_PROJECTION_DIGEST_FAILED")
    evidence = payload["original_nasa_hdf_source_verification"]
    if not isinstance(evidence, list) or len(evidence) != 8 or [
            (item.get("window_id"), item.get("stream_id")) for item in evidence] != list(SOURCE_IDENTITIES):
        raise SupervisorError("TERMINAL_SOURCE_EVIDENCE_GRID_FAILED")
    original_results = {(result["window_id"], result["stream_id"]): result
                        for result in results if result["erosion_id"] == "EROSION_0000M"}
    for item in evidence:
        identity = (item.get("window_id"), item.get("stream_id"))
        anomalous = [record for record in original_results[identity]["records"]
                     if runner.metric_map(record)["M0_D_gt0"]["pixel_center_count"] > 0]
        if runner.validate_source_evidence_item(
                item, identity[0], identity[1], anomalous[0] if anomalous else None):
            raise SupervisorError("TERMINAL_SOURCE_EVIDENCE_REVALIDATION_FAILED")
    verified_count = sum(item["status"] == "verified_exact_original_hdf_samples"
                         for item in evidence)
    if payload["nasa_network_transaction_count"] != verified_count * 3 or \
       not 0 <= payload["nasa_network_transaction_count"] <= 24:
        raise SupervisorError("TERMINAL_NETWORK_TRANSACTION_COUNT_FAILED")
    try:
        runner.validate_coordinate_free(payload)
    except Exception as exc:
        raise SupervisorError("TERMINAL_COORDINATE_FREE_FAILED") from exc
    return payload


class Lifecycle:
    def __init__(self) -> None:
        self.active: tuple[str, str] | None = None
        self.started: float | None = None
        self.deadline: float | None = None
        self.ee_completed = 0
        self.source_pairs: list[tuple[str, str]] = []
        self.source_candidate: tuple[str, str] | None = None
        self.source_stage: str | None = None
        self.failed = False
        self.terminal = False

    def consume(self, marker: str, event: dict[str, Any], observed: float) -> None:
        family = "ee" if marker.startswith("PHASE_") else "source"
        terminal = marker.endswith("COMPLETE") or marker.endswith("FAILED")
        if marker.endswith("START"):
            if self.active is not None or self.failed or self.terminal:
                raise SupervisorError("OVERLAPPING_OR_LATE_REQUEST")
            if family == "ee":
                if self.ee_completed >= len(EE_SEQUENCE) or event["phase"] != EE_SEQUENCE[self.ee_completed]:
                    raise SupervisorError("EE_PHASE_ORDER_FAILED")
            else:
                if self.ee_completed != len(EE_SEQUENCE):
                    raise SupervisorError("SOURCE_BEFORE_EE_COMPLETE")
                match = re.fullmatch(r"nasa_(cmr|meta|hdf)_(winter_2024|spring_2024|summer_2024|autumn_2024)_"
                                     r"(terra_night|aqua_night)", event["phase"])
                if match is None:
                    raise SupervisorError("SOURCE_PHASE_IDENTITY_FAILED")
                kind, window, stream = match.groups()
                identity = (window, stream)
                # Per anomaly identity the source requests must run in the exact
                # order cmr (umm_json search) -> meta (echo10 checksum) -> hdf
                # (authenticated download), and identities must advance in the
                # fixed window x stream order with no repeats.  The hdf phase is
                # a single supervised request even though it follows one
                # validated LP DAAC -> AWS S3 redirect internally; that hop is
                # recorded in the runner's hdf_transaction evidence and
                # revalidated by validate_source_evidence_item.
                if kind == "cmr":
                    if self.source_candidate is not None or identity in self.source_pairs or \
                       (self.source_pairs and SOURCE_IDENTITIES.index(identity) <=
                        SOURCE_IDENTITIES.index(self.source_pairs[-1])):
                        raise SupervisorError("SOURCE_ORDER_FAILED")
                    self.source_candidate = identity
                    self.source_stage = "cmr"
                elif kind == "meta":
                    if self.source_candidate != identity or self.source_stage != "cmr":
                        raise SupervisorError("SOURCE_META_WITHOUT_CMR")
                    self.source_stage = "meta"
                else:
                    if self.source_candidate != identity or self.source_stage != "meta":
                        raise SupervisorError("SOURCE_HDF_WITHOUT_META")
            self.active = (family, event["phase"])
            self.started, self.deadline = observed, observed + REQUEST_LIMIT_SECONDS
            return
        if not terminal or self.active != (family, event["phase"]) or self.started is None or \
           self.deadline is None:
            raise SupervisorError("REQUEST_END_WITHOUT_START")
        if observed >= self.deadline or observed - self.started >= REQUEST_LIMIT_SECONDS or \
           event["elapsed_seconds"] >= REQUEST_LIMIT_SECONDS:
            raise SupervisorError("REQUEST_WALL_CLOCK_CUTOFF_REACHED")
        self.active, self.started, self.deadline = None, None, None
        if marker.endswith("FAILED"):
            self.failed = True
        elif family == "ee":
            self.ee_completed += 1
        elif event["phase"].startswith("nasa_hdf_"):
            assert self.source_candidate is not None and self.source_stage == "meta"
            self.source_pairs.append(self.source_candidate)
            self.source_candidate = None
            self.source_stage = None

    def consume_terminal(self, payload: dict[str, Any]) -> None:
        if self.terminal or self.failed or self.active is not None or self.source_candidate is not None or \
           self.ee_completed != len(EE_SEQUENCE):
            raise SupervisorError("TERMINAL_PREMATURE_OR_DUPLICATE")
        verified = [(item["window_id"], item["stream_id"])
                    for item in payload["original_nasa_hdf_source_verification"]
                    if item["status"] == "verified_exact_original_hdf_samples"]
        if verified != self.source_pairs:
            raise SupervisorError("TERMINAL_SOURCE_LIFECYCLE_MISMATCH")
        self.terminal = True

    def complete(self) -> bool:
        return self.ee_completed == len(EE_SEQUENCE) and self.active is None and \
            self.source_candidate is None and not self.failed and self.terminal


def run(project: str) -> int:
    if os.name != "nt":
        raise SupervisorError("AUDIT012_SUPERVISOR_REQUIRES_WINDOWS")
    runner = load_runner()
    base = load_base()
    command = [sys.executable, str(RUNNER_PATH), "--project", project]
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    print(json.dumps({"AUDIT012_SUPERVISOR_START": {
        "implementation": IMPLEMENTATION, "supervisor_sha256": sha256_file(Path(__file__).resolve()),
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "request_wall_limit_seconds": REQUEST_LIMIT_SECONDS,
        "session_wall_limit_seconds": SESSION_LIMIT_SECONDS, "automatic_retry": False,
        "expected_earth_engine_requests": len(EE_SEQUENCE),
        "maximum_nasa_source_requests": runner.REQUEST_DECOMPOSITION["nasa_source_requests_max"],
        "completed_audit_checkpoint_read_or_written": False,
    }}, sort_keys=True), flush=True)
    session_deadline = time.monotonic() + SESSION_LIMIT_SECONDS
    messages: queue.Queue[tuple[str, float, bytes | None]] = queue.Queue()
    lifecycle = Lifecycle()
    with base.WindowsJob() as job:
        process = subprocess.Popen(
            command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        job.assign(process)
        if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
            base.terminate_job(job, process, PROTOCOL_EXIT_CODE)
            raise SupervisorError("RUNNER_POSTLAUNCH_SHA256_MISMATCH")
        assert process.stdout is not None and process.stderr is not None
        threads = [
            threading.Thread(target=base.reader_thread,
                             args=(process.stdout, "stdout", messages), daemon=True),
            threading.Thread(target=base.reader_thread,
                             args=(process.stderr, "stderr", messages), daemon=True),
        ]
        for thread in threads:
            thread.start()
        closed: set[str] = set()
        reason: str | None = None
        exit_code = PROTOCOL_EXIT_CODE
        try:
            while len(closed) < 2 or process.poll() is None or not messages.empty():
                now = time.monotonic()
                if now >= session_deadline:
                    reason, exit_code = "SESSION_WALL_CLOCK_CUTOFF_REACHED", TIMEOUT_EXIT_CODE
                    break
                if lifecycle.deadline is not None and now >= lifecycle.deadline:
                    reason, exit_code = "REQUEST_WALL_CLOCK_CUTOFF_REACHED", TIMEOUT_EXIT_CODE
                    break
                nearest = min(session_deadline, lifecycle.deadline or session_deadline)
                try:
                    stream_name, observed, line = messages.get(
                        timeout=max(0.0, min(0.05, nearest - now)))
                except queue.Empty:
                    continue
                if line is None:
                    closed.add(stream_name)
                    continue
                if stream_name == "stdout":
                    decoded = line.decode("utf-8", errors="strict").rstrip("\r\n")
                    marker = parse_marker(decoded)
                    if marker is not None:
                        lifecycle.consume(marker[0], marker[1], observed)
                    terminal = parse_terminal(decoded)
                    if terminal is not None:
                        lifecycle.consume_terminal(terminal)
                destination = sys.stdout.buffer if stream_name == "stdout" else sys.stderr.buffer
                destination.write(line)
                destination.flush()
        except (SupervisorError, UnicodeError) as exc:
            reason = type(exc).__name__ + ":" + str(exc)
        except KeyboardInterrupt:
            reason, exit_code = "SUPERVISOR_INTERRUPTED", 130
        if reason is not None:
            base.terminate_job(job, process, exit_code)
            print(json.dumps({"AUDIT012_SUPERVISOR_STOP": {
                "reason": reason, "complete_child_process_tree_terminated": True,
                "automatic_retry": False, "acceptance_claimed": False,
                "completed_audit_checkpoint_modified": False,
            }}, sort_keys=True), flush=True)
            return exit_code
        child_code = process.wait()
        if child_code == 0 and not lifecycle.complete():
            print(json.dumps({"AUDIT012_SUPERVISOR_STOP": {
                "reason": "CHILD_SUCCESS_WITHOUT_EXACT_COMPLETE_PROTOCOL",
                "automatic_retry": False, "acceptance_claimed": False,
            }}, sort_keys=True), flush=True)
            return PROTOCOL_EXIT_CODE
        return child_code


def self_test() -> int:
    failures: list[str] = []
    if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
        failures.append("runner_pin")
    if sha256_file(BASE_SUPERVISOR_PATH) != EXPECTED_BASE_SUPERVISOR_SHA256:
        failures.append("base_pin")
    expected_sequence_length = 5 + 8 + EARLIEST_ANOMALY_PROBE_REQUESTS + 32 * COMPARISON_BATCHES_PER_TREATMENT
    if len(EE_SEQUENCE) != expected_sequence_length or \
       len(EE_SEQUENCE) != load_runner().REQUEST_DECOMPOSITION["earth_engine_requests"] or \
       REQUEST_LIMIT_SECONDS != 480.000 or SESSION_LIMIT_SECONDS != 9900:
        failures.append("limits_or_decomposition")
    state = Lifecycle()
    clock = 0.0
    for phase in EE_SEQUENCE:
        start = parse_marker(json.dumps({"PHASE_REQUEST_START": {
            "phase": phase, "attempt": 1, "max_attempts": 1,
            "request_deadline_seconds": 480}}))
        complete = parse_marker(json.dumps({"PHASE_REQUEST_COMPLETE": {
            "phase": phase, "attempt": 1, "elapsed_seconds": 1.0}}))
        assert start is not None and complete is not None
        state.consume(*start, clock)
        state.consume(*complete, clock + 1.0)
        clock += 2.0
    for kind in ("cmr", "meta", "hdf"):
        marker = "SOURCE_REQUEST_START"
        start = parse_marker(json.dumps({marker: {
            "phase": f"nasa_{kind}_winter_2024_terra_night", "attempt": 1,
            "max_attempts": 1, "request_deadline_seconds": 480}}))
        end = parse_marker(json.dumps({"SOURCE_REQUEST_COMPLETE": {
            "phase": f"nasa_{kind}_winter_2024_terra_night", "attempt": 1,
            "elapsed_seconds": 1.0}}))
        assert start is not None and end is not None
        state.consume(*start, clock)
        state.consume(*end, clock + 1.0)
        clock += 2
    if state.ee_completed != len(EE_SEQUENCE) or \
       state.source_pairs != [("winter_2024", "terra_night")]:
        failures.append("lifecycle_positive")
    for name, lines in {
            "skip_ee": EE_SEQUENCE[1:],
            "duplicate_ee": (EE_SEQUENCE[0], EE_SEQUENCE[0]),
    }.items():
        fixture = Lifecycle()
        try:
            for phase in lines:
                fixture.consume("PHASE_REQUEST_START", {"phase": phase}, 0.0)
                fixture.consume("PHASE_REQUEST_COMPLETE", {"phase": phase,
                                "elapsed_seconds": 1.0}, 1.0)
            failures.append(name)
        except SupervisorError:
            pass
    cutoff = Lifecycle()
    try:
        cutoff.consume("PHASE_REQUEST_START", {"phase": EE_SEQUENCE[0]}, 0.0)
        cutoff.consume("PHASE_REQUEST_COMPLETE", {"phase": EE_SEQUENCE[0],
                       "elapsed_seconds": 480.0}, 479.9)
        failures.append("cutoff")
    except SupervisorError:
        pass
    for malformed in (
            '{"PHASE_REQUEST_START":{"phase":"runtime_fixture","attempt":1,"attempt":1,"max_attempts":1,"request_deadline_seconds":480}}',
            json.dumps({"PHASE_REQUEST_START": {"phase": "runtime_fixture", "attempt": 1,
                        "max_attempts": 2, "request_deadline_seconds": 480}}),
            json.dumps({"outer": {"PHASE_REQUEST_START": {"phase": "runtime_fixture"}}}),
    ):
        try:
            parsed = parse_marker(malformed)
            if parsed is not None:
                failures.append("spoof_or_malformed")
        except SupervisorError:
            pass
    try:
        terminal_fixture = load_runner().synthetic_terminal_payload()
        if parse_terminal(json.dumps({TERMINAL_KEY: terminal_fixture},
                                     sort_keys=True, separators=(",", ":"))) is None:
            failures.append("terminal_positive")
    except Exception:
        failures.append("terminal_positive_exception")
        terminal_fixture = None
    if terminal_fixture is not None:
        terminal_mutations = {
            "reader": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "hdf_reader", "wrong"),
            "hdf_hash": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "hdf_sha256", "bad"),
            "checksum": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "declared_checksum", "bad"),
            "sds_name": lambda x: x["original_nasa_hdf_source_verification"][0][
                "sds_names"].__setitem__(0, "wrong"),
            "sds_shape": lambda x: x["original_nasa_hdf_source_verification"][0][
                "sds_shapes"]["QC_Night"].__setitem__(0, 1),
            "concept": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "cmr_concept_id", "bad"),
            "granule": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "producer_granule_id", "bad.hdf"),
            "sample_hash": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "hdf_sample_values_sha256", "9" * 64),
            "identity": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "ee_image_id", "2024_01_16"),
            "tile_id": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "modis_sinusoidal_tile_id", "h18v04"),
            "tile_h": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "modis_sinusoidal_horizontal_tile", 18),
            "tile_v": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "modis_sinusoidal_vertical_tile", 5),
            "tile_derivation": lambda x: x["original_nasa_hdf_source_verification"][
                0].__setitem__("tile_identity_derived_from_transient_samples", False),
            "redirect": lambda x: x["original_nasa_hdf_source_verification"][0][
                "cmr_transaction"].__setitem__("redirect_count", 1),
            "temp_residue": lambda x: x["original_nasa_hdf_source_verification"][0].__setitem__(
                "temporary_hdf_persisted", True),
            "transaction_total": lambda x: x.__setitem__("nasa_network_transaction_count", 15),
        }
        for name, mutate in terminal_mutations.items():
            fixture = copy.deepcopy(terminal_fixture)
            mutate(fixture)
            try:
                parse_terminal(json.dumps({TERMINAL_KEY: fixture},
                                          sort_keys=True, separators=(",", ":")))
                failures.append("terminal_negative_" + name)
            except SupervisorError:
                pass
    try:
        if not load_base().offline_job_tree_termination_test():
            failures.append("windows_job_tree")
    except Exception:
        failures.append("windows_job_tree_exception")
    print(json.dumps({"self_test": not failures, "failures": failures,
                      "windows_job_tree_termination_pass":
                      "windows_job_tree" not in failures and
                      "windows_job_tree_exception" not in failures}, sort_keys=True))
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
        return run(args.project)
    except Exception as exc:
        print(json.dumps({"AUDIT012_SUPERVISOR_FAILED": True,
                          "exception_class": type(exc).__name__,
                          "acceptance_claimed": False}), flush=True)
        return PROTOCOL_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
