#!/usr/bin/env python3
"""Windows wall-clock supervisor for the AUDIT-011 diagnostic runner."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tools" / "run_nighttime_gate_attribution_diagnostic_ee.py"
BASE_SUPERVISOR_PATH = ROOT / "tools" / "supervise_whole_lake_boundary_shoreline_audit.py"
EXPECTED_RUNNER_SHA256 = "437c1b03f73cfec2a11eb50b86b236b0fe64574aa2e79c4b012a0d16f377bb9a"
EXPECTED_BASE_SUPERVISOR_SHA256 = "8614de215b21e1722520f482c22516c04dea13950d58ba194ded252e9cfd7064"
IMPLEMENTATION = "nighttime_gate_attribution_windows_supervisor_v6_boolean_source_identity_pin"
REQUEST_LIMIT_SECONDS = 480.000
SESSION_LIMIT_SECONDS = 165 * 60
TIMEOUT_EXIT_CODE = 124
PROTOCOL_EXIT_CODE = 125
MARKERS = {
    "PHASE_REQUEST_START", "PHASE_REQUEST_COMPLETE",
    "PHASE_REQUEST_TRANSPORT_FAILURE", "PHASE_REQUEST_FAILURE",
}
WINDOWS = ("winter_2024", "spring_2024", "summer_2024", "autumn_2024")
STREAMS = ("terra_night", "aqua_night")
GATE_ORDER = (
    "valid_temperature_data", "mandatory_qa", "data_quality",
    "emissivity_error", "lst_error", "view_time_validity",
    "view_angle_validity",
)
ALLOWED_PHASES = frozenset({
    "canonical_projection", "canonical_reference_id", "runtime_fixture",
    "projection_inventory", "unclassified_phase",
})
EXPECTED_PHASE_SEQUENCE = tuple(
    [item for stream in STREAMS for item in (
        "canonical_projection", "canonical_reference_id")]
    + ["runtime_fixture"]
    + ["projection_inventory" for window in WINDOWS for stream in STREAMS]
    + ["unclassified_phase" for window in WINDOWS for stream in STREAMS]
)
TERMINAL_KEY = "NIGHTTIME_GATE_ATTRIBUTION_DIAGNOSTIC_COMPLETE"
EXPECTED_REQUEST_DECOMPOSITION = {
    "canonical_metadata_requests": 4, "runtime_fixture_requests": 1,
    "projection_inventory_requests": 8, "attribution_requests": 8,
    "total_ee_requests": 21, "attribution_rows_per_request": 14,
    "stream_order": list(STREAMS), "window_order": list(WINDOWS),
    "sequential": True, "automatic_retry": False,
}
RESULT_KEYS = {
    "specification", "implementation", "window_id", "season", "stream_id",
    "geometry_id", "date_count", "records", "coordinate_free",
    "declared_gate_order", "attribution_interpretation", "validation_errors",
}
RECORD_KEYS = {
    "date_utc", "window_id", "stream_id", "source_image_count",
    "source_image_id", "source_identity_matches_projection_inventory",
    "eligible_area_m2", "eligible_pixel_center_count", "standalone_pass_area_m2",
    "cumulative_waterfall_area_m2", "leave_one_out_area_m2",
    "exclusive_failure_area_m2", "pairwise_failure_overlap_area_m2",
    "final_accepted_area_m2", "final_accepted_coverage_fraction",
    "audit_mask_accepted_area_m2", "audit_mask_accepted_coverage_fraction",
    "final_mask_identity_symmetric_difference_area_m2", "validation_errors",
}
DIGEST_KEYS = {
    "window_id", "stream_id", "record_count", "source_image_counts",
    "source_image_ids_sha256", "projection_inventory_sha256", "pass",
}
ATTRIBUTION_INTERPRETATION = (
    "descriptive logical gate attribution; cumulative losses depend on declared order; "
    "standalone, leave-one-out, exclusive-failure, and pairwise-overlap evidence is "
    "order-independent; not causal"
)
SCIENTIFIC_INTERPRETATION = (
    "Diagnostic attribution only. Cumulative differences are declared-order bookkeeping; "
    "overlap-aware logical evidence is descriptive and must not be interpreted as causal."
)


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


def load_base_supervisor() -> Any:
    if sha256_file(BASE_SUPERVISOR_PATH) != EXPECTED_BASE_SUPERVISOR_SHA256:
        raise SupervisorError("PINNED_BASE_SUPERVISOR_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location("pinned_audit010_supervisor", BASE_SUPERVISOR_PATH)
    if spec is None or spec.loader is None:
        raise SupervisorError("PINNED_BASE_SUPERVISOR_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if sha256_file(BASE_SUPERVISOR_PATH) != EXPECTED_BASE_SUPERVISOR_SHA256:
        raise SupervisorError("PINNED_BASE_SUPERVISOR_CHANGED_DURING_IMPORT")
    return module


def load_runner_contract() -> Any:
    if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
        raise SupervisorError("PINNED_DIAGNOSTIC_RUNNER_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location("pinned_audit011_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise SupervisorError("PINNED_DIAGNOSTIC_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
        raise SupervisorError("PINNED_DIAGNOSTIC_RUNNER_CHANGED_DURING_IMPORT")
    return module


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result


def parse_lifecycle_line(line: str) -> tuple[str, dict[str, Any]] | None:
    try:
        value = json.loads(line, object_pairs_hook=reject_duplicates)
    except DuplicateKey as exc:
        if "PHASE_REQUEST_" in line:
            raise SupervisorError("LIFECYCLE_DUPLICATE_JSON_KEY") from exc
        return None
    except json.JSONDecodeError as exc:
        if "PHASE_REQUEST_" in line:
            raise SupervisorError("LIFECYCLE_MALFORMED_MARKER_LINE") from exc
        return None
    if not isinstance(value, dict):
        return None
    present = set(value).intersection(MARKERS)
    unknown = {key for key in value if isinstance(key, str) and
               key.startswith("PHASE_REQUEST_") and key not in MARKERS}
    if unknown:
        raise SupervisorError("LIFECYCLE_UNKNOWN_MARKER")
    if not present:
        return None
    if len(value) != 1 or len(present) != 1:
        raise SupervisorError("LIFECYCLE_TOP_LEVEL_SHAPE_FAILED")
    marker = next(iter(present))
    event = value[marker]
    if not isinstance(event, dict) or event.get("phase") not in ALLOWED_PHASES:
        raise SupervisorError("LIFECYCLE_EVENT_OR_PHASE_FAILED")
    if marker == "PHASE_REQUEST_START":
        if set(event) != {"phase", "attempt", "max_attempts", "request_deadline_seconds"} or \
           event["attempt"] != 1 or event["max_attempts"] != 1 or \
           event["request_deadline_seconds"] != REQUEST_LIMIT_SECONDS:
            raise SupervisorError("LIFECYCLE_START_CONTRACT_FAILED")
    elif marker == "PHASE_REQUEST_COMPLETE":
        if set(event) != {"phase", "attempt", "elapsed_seconds"} or event["attempt"] != 1 or \
           not isinstance(event["elapsed_seconds"], (int, float)) or isinstance(
               event["elapsed_seconds"], bool):
            raise SupervisorError("LIFECYCLE_COMPLETE_CONTRACT_FAILED")
    elif marker == "PHASE_REQUEST_TRANSPORT_FAILURE":
        if set(event) != {"phase", "attempt", "elapsed_seconds", "exception_class",
                          "failure_class", "will_retry"} or event["attempt"] != 1 or \
           event["will_retry"] is not False:
            raise SupervisorError("LIFECYCLE_TRANSPORT_FAILURE_CONTRACT_FAILED")
    else:
        if set(event) != {"phase", "elapsed_seconds", "exception_class", "exception_category"}:
            raise SupervisorError("LIFECYCLE_FAILURE_CONTRACT_FAILED")
    elapsed = event.get("elapsed_seconds")
    if marker != "PHASE_REQUEST_START" and (
            not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or
            not math.isfinite(elapsed) or elapsed < 0):
        raise SupervisorError("LIFECYCLE_ELAPSED_NOT_FINITE_NONNEGATIVE")
    return marker, event


def parse_terminal_line(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, DuplicateKey) as exc:
        if TERMINAL_KEY in line:
            raise SupervisorError("TERMINAL_MALFORMED_OR_DUPLICATE_JSON") from exc
        return None
    if not isinstance(value, dict) or TERMINAL_KEY not in value:
        return None
    if set(value) != {TERMINAL_KEY} or not isinstance(value[TERMINAL_KEY], dict):
        raise SupervisorError("TERMINAL_TOP_LEVEL_SHAPE_FAILED")
    payload = value[TERMINAL_KEY]
    required = {
        "specification", "implementation", "coordinate_free",
        "source_coordinate_arrays_included", "geometry_id",
        "request_decomposition", "projection_certification_digests",
        "result_count", "results", "validation_errors", "pass",
        "scientific_interpretation",
    }
    if set(payload) != required or payload["specification"] != "AUDIT-011_2026-08-23" or \
       payload["implementation"] != "nighttime_gate_attribution_diagnostic_python_api_v5_boolean_source_identity" or \
       payload["coordinate_free"] is not True or \
       payload["source_coordinate_arrays_included"] is not False or \
       payload["geometry_id"] != "wise_wfd_v1_9_huaih049_2022_unrounded__erosion_0000m" or \
       payload["request_decomposition"] != EXPECTED_REQUEST_DECOMPOSITION or \
       payload["result_count"] != 8 or payload["validation_errors"] != [] or \
       payload["pass"] is not True or \
       payload["scientific_interpretation"] != SCIENTIFIC_INTERPRETATION:
        raise SupervisorError("TERMINAL_ACCEPTANCE_CONTRACT_FAILED")
    results = payload["results"]
    digests = payload["projection_certification_digests"]
    expected_pairs = [(window, stream) for window in WINDOWS for stream in STREAMS]
    runner_contract = load_runner_contract()
    window_contracts = {item["window_id"]: item for item in runner_contract.WINDOWS}
    stream_contracts = {
        item["stream_id"]: item for item in runner_contract.load_audit_runner().STREAMS
        if item["stream_id"] in STREAMS
    }
    if not isinstance(results, list) or len(results) != 8 or not isinstance(digests, list) or \
       len(digests) != 8:
        raise SupervisorError("TERMINAL_RESULT_COUNT_FAILED")
    for index, (window, stream) in enumerate(expected_pairs):
        result = results[index]
        digest = digests[index]
        if not isinstance(result, dict) or set(result) != RESULT_KEYS or \
           result.get("window_id") != window or \
           result.get("stream_id") != stream or result.get("coordinate_free") is not True or \
           result.get("specification") != "AUDIT-011_2026-08-23" or \
           result.get("implementation") != "nighttime_gate_attribution_diagnostic_python_api_v5_boolean_source_identity" or \
           result.get("geometry_id") != "wise_wfd_v1_9_huaih049_2022_unrounded__erosion_0000m" or \
           result.get("declared_gate_order") != list(GATE_ORDER) or \
           result.get("date_count") != 14 or not isinstance(result.get("records"), list) or \
           len(result["records"]) != 14 or result.get("validation_errors") != [] or \
           result.get("attribution_interpretation") != ATTRIBUTION_INTERPRETATION:
            raise SupervisorError("TERMINAL_RESULT_IDENTITY_FAILED")
        if runner_contract.validate_request_result(
                result, window_contracts[window], stream_contracts[stream]):
            raise SupervisorError("TERMINAL_RESULT_CONTRACT_REVALIDATION_FAILED")
        window_start = {"winter_2024": "2024-01-15", "spring_2024": "2024-04-15",
                        "summer_2024": "2024-07-15", "autumn_2024": "2024-10-15"}[window]
        start_date = dt.date.fromisoformat(window_start)
        expected_dates = [(start_date + dt.timedelta(days=offset)).isoformat()
                          for offset in range(14)]
        for date_utc, record in zip(expected_dates, result["records"]):
            if not isinstance(record, dict) or set(record) != RECORD_KEYS or \
               record.get("date_utc") != date_utc or record.get("window_id") != window or \
               record.get("stream_id") != stream or record.get("source_image_count") != 1 or \
               not isinstance(record.get("source_image_id"), str) or not record["source_image_id"] or \
               record.get("source_identity_matches_projection_inventory") is not True or \
               record.get("validation_errors") != []:
                raise SupervisorError("TERMINAL_DATE_ACCEPTANCE_FAILED")
        if not isinstance(digest, dict) or set(digest) != DIGEST_KEYS or \
           digest.get("window_id") != window or \
           digest.get("stream_id") != stream or digest.get("record_count") != 14 or \
           digest.get("source_image_counts") != [1] * 14 or digest.get("pass") is not True:
            raise SupervisorError("TERMINAL_PROJECTION_DIGEST_FAILED")
    return payload


class Lifecycle:
    def __init__(self) -> None:
        self.phase: str | None = None
        self.started: float | None = None
        self.deadline: float | None = None
        self.completed_count = 0
        self.failed = False
        self.terminal_seen = False

    def consume(self, marker: str, event: dict[str, Any], observed: float) -> None:
        if marker == "PHASE_REQUEST_START":
            if self.phase is not None or self.failed or self.terminal_seen:
                raise SupervisorError("LIFECYCLE_OVERLAPPING_REQUESTS")
            if self.completed_count >= len(EXPECTED_PHASE_SEQUENCE) or \
               event["phase"] != EXPECTED_PHASE_SEQUENCE[self.completed_count]:
                raise SupervisorError("LIFECYCLE_PHASE_ORDER_FAILED")
            self.phase = event["phase"]
            self.started = observed
            self.deadline = observed + REQUEST_LIMIT_SECONDS
            return
        if self.phase != event["phase"] or self.started is None or self.deadline is None:
            raise SupervisorError("LIFECYCLE_TERMINAL_WITHOUT_MATCHING_START")
        elapsed = event.get("elapsed_seconds")
        if observed >= self.deadline or observed - self.started >= REQUEST_LIMIT_SECONDS or \
           (isinstance(elapsed, (int, float)) and elapsed >= REQUEST_LIMIT_SECONDS):
            raise SupervisorError("REQUEST_WALL_CLOCK_CUTOFF_REACHED")
        self.phase = self.started = self.deadline = None
        if marker == "PHASE_REQUEST_COMPLETE":
            self.completed_count += 1
        else:
            self.failed = True

    def consume_terminal(self, payload: dict[str, Any]) -> None:
        if self.terminal_seen:
            raise SupervisorError("TERMINAL_DUPLICATE")
        if self.phase is not None or self.failed or \
           self.completed_count != len(EXPECTED_PHASE_SEQUENCE):
            raise SupervisorError("TERMINAL_PREMATURE")
        self.terminal_seen = True

    def success_protocol_complete(self) -> bool:
        return self.phase is None and not self.failed and self.terminal_seen and \
            self.completed_count == len(EXPECTED_PHASE_SEQUENCE)


def synthetic_terminal_line() -> str:
    runner_contract = load_runner_contract()
    seasons = {"winter_2024": "winter", "spring_2024": "spring",
               "summer_2024": "summer", "autumn_2024": "autumn"}
    starts = {"winter_2024": "2024-01-15", "spring_2024": "2024-04-15",
              "summer_2024": "2024-07-15", "autumn_2024": "2024-10-15"}
    results: list[dict[str, Any]] = []
    digests: list[dict[str, Any]] = []
    for window in WINDOWS:
        for stream in STREAMS:
            start = dt.date.fromisoformat(starts[window])
            records = []
            for offset in range(14):
                record = copy.deepcopy(runner_contract.synthetic_record())
                record["date_utc"] = (start + dt.timedelta(days=offset)).isoformat()
                record["window_id"] = window
                record["stream_id"] = stream
                records.append(record)
            results.append({
                "specification": "AUDIT-011_2026-08-23",
                "implementation": "nighttime_gate_attribution_diagnostic_python_api_v5_boolean_source_identity",
                "window_id": window, "season": seasons[window], "stream_id": stream,
                "geometry_id": "wise_wfd_v1_9_huaih049_2022_unrounded__erosion_0000m",
                "date_count": 14, "records": records, "coordinate_free": True,
                "declared_gate_order": list(GATE_ORDER),
                "attribution_interpretation": ATTRIBUTION_INTERPRETATION,
                "validation_errors": [],
            })
            digests.append({
                "window_id": window, "stream_id": stream, "record_count": 14,
                "source_image_counts": [1] * 14,
                "source_image_ids_sha256": "0" * 64,
                "projection_inventory_sha256": "1" * 64, "pass": True,
            })
    payload = {
        "specification": "AUDIT-011_2026-08-23",
        "implementation": "nighttime_gate_attribution_diagnostic_python_api_v5_boolean_source_identity",
        "coordinate_free": True, "source_coordinate_arrays_included": False,
        "geometry_id": "wise_wfd_v1_9_huaih049_2022_unrounded__erosion_0000m",
        "request_decomposition": EXPECTED_REQUEST_DECOMPOSITION,
        "projection_certification_digests": digests, "result_count": 8,
        "results": results, "validation_errors": [], "pass": True,
        "scientific_interpretation": SCIENTIFIC_INTERPRETATION,
    }
    return json.dumps({TERMINAL_KEY: payload}, sort_keys=True, separators=(",", ":"))


def run(project: str) -> int:
    if os.name != "nt":
        raise SupervisorError("AUDIT011_SUPERVISOR_REQUIRES_WINDOWS")
    if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
        raise SupervisorError("PINNED_DIAGNOSTIC_RUNNER_SHA256_MISMATCH")
    base = load_base_supervisor()
    command = [sys.executable, str(RUNNER_PATH), "--project", project]
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    print(json.dumps({"AUDIT011_SUPERVISOR_START": {
        "implementation": IMPLEMENTATION,
        "supervisor_sha256": sha256_file(Path(__file__).resolve()),
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "request_wall_limit_seconds": REQUEST_LIMIT_SECONDS,
        "session_wall_limit_seconds": SESSION_LIMIT_SECONDS,
        "automatic_retry": False,
        "completed_audit_checkpoint_read_or_written_by_supervisor": False,
    }}, sort_keys=True), flush=True)
    started = time.monotonic()
    session_deadline = started + SESSION_LIMIT_SECONDS
    messages: queue.Queue[tuple[str, float, bytes | None]] = queue.Queue()
    lifecycle = Lifecycle()
    with base.WindowsJob() as job:
        process = subprocess.Popen(
            command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            job.assign(process)
            if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
                base.terminate_job(job, process, PROTOCOL_EXIT_CODE)
                raise SupervisorError("PINNED_DIAGNOSTIC_RUNNER_POSTLAUNCH_SHA256_MISMATCH")
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            raise
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
                    parsed = parse_lifecycle_line(decoded)
                    if parsed is not None:
                        lifecycle.consume(parsed[0], parsed[1], observed)
                    terminal = parse_terminal_line(decoded)
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
            print(json.dumps({"AUDIT011_SUPERVISOR_STOP": {
                "reason": reason, "complete_child_process_tree_terminated": True,
                "automatic_retry": False, "acceptance_claimed": False,
                "completed_audit_checkpoint_modified": False,
            }}, sort_keys=True), flush=True)
            return exit_code
        child_code = process.wait()
        if lifecycle.phase is not None or (child_code == 0 and
                                           not lifecycle.success_protocol_complete()):
            print(json.dumps({"AUDIT011_SUPERVISOR_STOP": {
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
        failures.append("base_supervisor_pin")
    if len(ALLOWED_PHASES) != 5 or len(EXPECTED_PHASE_SEQUENCE) != 21:
        failures.append("phase_count")
    try:
        audit_contract = load_runner_contract().load_audit_runner()
        normalization_fixtures = {
            "canonical_projection_terra_night": "canonical_projection",
            "canonical_reference_id_terra_night": "canonical_reference_id",
            "runtime_fixture": "runtime_fixture",
            "projection_inventory_winter_2024_terra_night": "projection_inventory",
            "nighttime_gate_attribution_winter_2024_terra_night": "unclassified_phase",
        }
        if any(audit_contract.safe_phase_category(raw) != normalized
               for raw, normalized in normalization_fixtures.items()):
            failures.append("pinned_lifecycle_phase_normalization")
    except Exception:
        failures.append("pinned_lifecycle_phase_normalization_exception")
    try:
        if not load_base_supervisor().offline_job_tree_termination_test():
            failures.append("windows_job_tree_termination")
    except Exception:
        failures.append("windows_job_tree_termination_exception")
    state = Lifecycle()
    for phase in EXPECTED_PHASE_SEQUENCE:
        start = json.dumps({"PHASE_REQUEST_START": {
            "phase": phase, "attempt": 1, "max_attempts": 1,
            "request_deadline_seconds": 480}})
        complete = json.dumps({"PHASE_REQUEST_COMPLETE": {
            "phase": phase, "attempt": 1, "elapsed_seconds": 479.999}})
        parsed_start = parse_lifecycle_line(start)
        parsed_complete = parse_lifecycle_line(complete)
        if parsed_start is None or parsed_complete is None:
            failures.append("valid_parse:" + phase)
            continue
        observed_start = state.completed_count * 10.0
        state.consume(*parsed_start, observed_start)
        state.consume(*parsed_complete, observed_start + 1.0)
    if state.completed_count != 21:
        failures.append("ordered_sequence_positive")
    for name, sequence in {
            "skip": EXPECTED_PHASE_SEQUENCE[1:],
            "duplicate": (EXPECTED_PHASE_SEQUENCE[0], EXPECTED_PHASE_SEQUENCE[0]),
            "out_of_order": (EXPECTED_PHASE_SEQUENCE[1], EXPECTED_PHASE_SEQUENCE[0]),
            "skip_repeated_projection": (
                EXPECTED_PHASE_SEQUENCE[:6] + EXPECTED_PHASE_SEQUENCE[7:]),
            "duplicate_repeated_projection": (
                EXPECTED_PHASE_SEQUENCE[:6] + ("projection_inventory",) +
                EXPECTED_PHASE_SEQUENCE[6:]),
    }.items():
        fixture_state = Lifecycle()
        try:
            for phase in sequence:
                fixture_state.consume("PHASE_REQUEST_START", {
                    "phase": phase, "attempt": 1, "max_attempts": 1,
                    "request_deadline_seconds": 480}, 0.0)
                fixture_state.consume("PHASE_REQUEST_COMPLETE", {
                    "phase": phase, "attempt": 1, "elapsed_seconds": 1.0}, 1.0)
            failures.append("sequence_rejection:" + name)
        except SupervisorError:
            pass
    try:
        terminal = parse_terminal_line(synthetic_terminal_line())
        if terminal is None:
            failures.append("terminal_positive_parse")
        else:
            state.consume_terminal(terminal)
            if not state.terminal_seen:
                failures.append("terminal_positive_state")
            if not state.success_protocol_complete():
                failures.append("terminal_positive_acceptance")
    except SupervisorError:
        failures.append("terminal_positive_exception")
    for name, mutate in {
            "premature": lambda terminal_state, payload: terminal_state.consume_terminal(payload),
            "duplicate": lambda terminal_state, payload: (
                terminal_state.consume_terminal(payload), terminal_state.consume_terminal(payload)),
    }.items():
        fixture_state = Lifecycle()
        if name == "duplicate":
            fixture_state.completed_count = 21
        try:
            payload = parse_terminal_line(synthetic_terminal_line())
            assert payload is not None
            mutate(fixture_state, payload)
            failures.append("terminal_state_rejection:" + name)
        except SupervisorError:
            pass
    terminal_mutations = {
        "failed_pass": lambda value: value[TERMINAL_KEY].__setitem__("pass", False),
        "missing_result": lambda value: value[TERMINAL_KEY]["results"].pop(),
        "missing_source": lambda value: value[TERMINAL_KEY]["results"][0]["records"][0].__setitem__(
            "source_image_count", 0),
        "duplicate_source": lambda value: value[TERMINAL_KEY]["results"][0]["records"][0].__setitem__(
            "source_image_count", 2),
        "exclusive_plus_pairwise": lambda value: value[TERMINAL_KEY]["results"][0][
            "records"][0]["pairwise_failure_overlap_area_m2"][0].update(
                {"area_m2": 9.0, "coverage_fraction": 0.09}),
    }
    for name, mutate in terminal_mutations.items():
        fixture = json.loads(synthetic_terminal_line())
        mutate(fixture)
        try:
            parse_terminal_line(json.dumps(fixture, separators=(",", ":")))
            failures.append("terminal_payload_rejection:" + name)
        except SupervisorError:
            pass
    for index, malformed in enumerate((
            '{"NIGHTTIME_GATE_ATTRIBUTION_DIAGNOSTIC_COMPLETE":',
            '{"NIGHTTIME_GATE_ATTRIBUTION_DIAGNOSTIC_COMPLETE":{},'
            '"NIGHTTIME_GATE_ATTRIBUTION_DIAGNOSTIC_COMPLETE":{}}')):
        try:
            parse_terminal_line(malformed)
            failures.append("terminal_malformed_rejection:" + str(index))
        except SupervisorError:
            pass
    incomplete_success_states = {
        "no_phases": Lifecycle(),
        "all_phases_no_terminal": Lifecycle(),
    }
    incomplete_success_states["all_phases_no_terminal"].completed_count = 21
    for name, fixture_state in incomplete_success_states.items():
        if fixture_state.success_protocol_complete():
            failures.append("success_without_terminal_rejection:" + name)
    for index, elapsed in enumerate((-1.0, float("nan"), float("inf"))):
        line = json.dumps({"PHASE_REQUEST_COMPLETE": {
            "phase": EXPECTED_PHASE_SEQUENCE[0], "attempt": 1,
            "elapsed_seconds": elapsed}})
        try:
            parse_lifecycle_line(line)
            failures.append("elapsed_rejection:" + str(index))
        except SupervisorError:
            pass
    rejected = [
        json.dumps({"PHASE_REQUEST_START": {"phase": "unknown", "attempt": 1,
                    "max_attempts": 1, "request_deadline_seconds": 480}}),
        '{"PHASE_REQUEST_START":{"phase":"runtime_fixture","attempt":1,"attempt":1,"max_attempts":1,"request_deadline_seconds":480}}',
        json.dumps({"wrapper": {"PHASE_REQUEST_START": {"phase": "runtime_fixture"}}}),
        json.dumps({"PHASE_REQUEST_START": {"phase": "runtime_fixture", "attempt": 1,
                    "max_attempts": 2, "request_deadline_seconds": 480}}),
    ]
    for index, line in enumerate(rejected):
        try:
            parsed = parse_lifecycle_line(line)
            if index != 2 or parsed is not None:
                failures.append("spoof_rejection:" + str(index))
        except SupervisorError:
            pass
    state = Lifecycle()
    start = parse_lifecycle_line(json.dumps({"PHASE_REQUEST_START": {
        "phase": EXPECTED_PHASE_SEQUENCE[0], "attempt": 1, "max_attempts": 1,
        "request_deadline_seconds": 480}}))
    complete = parse_lifecycle_line(json.dumps({"PHASE_REQUEST_COMPLETE": {
        "phase": EXPECTED_PHASE_SEQUENCE[0], "attempt": 1, "elapsed_seconds": 480}}))
    try:
        assert start is not None and complete is not None
        state.consume(*start, 0.0)
        state.consume(*complete, 479.999)
        failures.append("reported_cutoff")
    except SupervisorError:
        pass
    print(json.dumps({"self_test": not failures, "failures": failures,
                      "windows_job_tree_termination_pass":
                      "windows_job_tree_termination" not in failures and
                      "windows_job_tree_termination_exception" not in failures}, sort_keys=True))
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
        print(json.dumps({"AUDIT011_SUPERVISOR_FAILED": True,
                          "exception_class": type(exc).__name__,
                          "acceptance_claimed": False}), flush=True)
        return PROTOCOL_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
