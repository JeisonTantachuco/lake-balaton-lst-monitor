#!/usr/bin/env python3
"""Windows wall-clock / process-tree supervisor for the Phase 3 anomaly engine.

Byte-pins the runner, launches it inside a non-breakaway Windows Job Object, enforces
the 165-minute session ceiling and the per-request 480 s cutoff, forwards runner output
verbatim, terminates the complete child-process tree with no automatic retry, and
re-checks that the mode's terminal object is present and coordinate-free.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tools" / "run_anomaly_engine_ee.py"
BASE_SUPERVISOR_PATH = ROOT / "tools" / "supervise_whole_lake_boundary_shoreline_audit.py"
EXPECTED_RUNNER_SHA256 = "f649df317cc0694b8051d608f6040c7b094c706d6f4b5916eb748c1b92a8510b"
EXPECTED_BASE_SUPERVISOR_SHA256 = "8614de215b21e1722520f482c22516c04dea13950d58ba194ded252e9cfd7064"
IMPLEMENTATION = "anomaly_engine_windows_supervisor_v1"
REQUEST_LIMIT_SECONDS = 480.000
SESSION_LIMIT_SECONDS = 165 * 60
TIMEOUT_EXIT_CODE = 124
PROTOCOL_EXIT_CODE = 125
TERMINAL_KEYS = {
    "build_climatology": "ANOMALY_ENGINE_CLIMATOLOGY_COMPLETE",
    "daily_records": "ANOMALY_ENGINE_DAILY_RECORDS_COMPLETE",
}
MODE_FLAGS = {"build_climatology": "--build-climatology", "daily_records": "--daily-records"}
FAIL_KEY = "ANOMALY_ENGINE_FAILED"
_BASE: Any = None
_RUNNER: Any = None

_FORBIDDEN = re.compile(
    r"(?:^|_)(?:geometry|coordinates?|coords?|bounds?|bbox|extent|envelope|latitude|"
    r"longitude|lat|lon|lng|xmin|xmax|ymin|ymax|minx|maxx|miny|maxy|easting|northing|"
    r"wkt|geojson)(?:_|$)", re.IGNORECASE)
_ALLOWED = {"coordinate_free", "reads_coordinates", "geometry", "geometry_identity_sha256"}


class SupervisorError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path, expected: str, name: str) -> Any:
    if sha256_file(path) != expected:
        raise SupervisorError(name + "_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location(name.casefold(), path)
    if spec is None or spec.loader is None:
        raise SupervisorError(name + "_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_base() -> Any:
    global _BASE
    if _BASE is None:
        _BASE = load_module(BASE_SUPERVISOR_PATH, EXPECTED_BASE_SUPERVISOR_SHA256,
                            "PINNED_WINDOWS_JOB_SUPERVISOR")
    return _BASE


def load_runner() -> Any:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = load_module(RUNNER_PATH, EXPECTED_RUNNER_SHA256, "PINNED_ANOMALY_ENGINE_RUNNER")
    return _RUNNER


def assert_coordinate_free(value: Any) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
                normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").casefold()
                if key not in _ALLOWED and _FORBIDDEN.search(normalized):
                    raise SupervisorError("TERMINAL_COORDINATE_KEY_LEAK:" + str(key))
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
    walk(value)


def validate_climatology_terminal(payload: Any) -> None:
    runner = load_runner()
    if not isinstance(payload, dict):
        raise SupervisorError("TERMINAL_SHAPE_FAILED")
    required = {
        "specification", "implementation", "coordinate_free", "reads_coordinates",
        "historical_daily_value_count", "baseline_row_count", "baseline_rows_sha256",
        "eligible_pixel_counts", "coverage_summary", "pass",
    }
    if set(payload) != required:
        raise SupervisorError("TERMINAL_KEYSET_FAILED")
    if payload["specification"] != runner.SPECIFICATION or \
       payload["implementation"] != runner.IMPLEMENTATION or \
       payload["coordinate_free"] is not True or payload["reads_coordinates"] is not False or \
       payload["pass"] is not True:
        raise SupervisorError("TERMINAL_CONTRACT_FAILED")
    expected_rows = len(runner.STREAM_IDS) * runner.DAYS_IN_YEAR
    if payload["baseline_row_count"] != expected_rows:
        raise SupervisorError("TERMINAL_BASELINE_ROW_COUNT_FAILED")
    if set(payload["eligible_pixel_counts"]) != set(runner.STREAM_IDS) or \
       any(not isinstance(v, int) or v <= 0 for v in payload["eligible_pixel_counts"].values()):
        raise SupervisorError("TERMINAL_ELIGIBLE_COUNT_FAILED")
    # re-validate the written baseline artifact itself
    artifact = runner.STATE_DIR / "climatology_baseline.json"
    if not artifact.exists():
        raise SupervisorError("BASELINE_ARTIFACT_MISSING")
    baseline_payload = json.loads(artifact.read_text(encoding="utf-8"))
    if baseline_payload.get("rows_sha256") != payload["baseline_rows_sha256"]:
        raise SupervisorError("BASELINE_ARTIFACT_HASH_MISMATCH")
    errors = runner.validate_baseline(baseline_payload)
    if errors:
        raise SupervisorError("BASELINE_ARTIFACT_REVALIDATION_FAILED:" + errors[0])
    assert_coordinate_free(payload)
    assert_coordinate_free(baseline_payload)


def validate_daily_records_terminal(payload: Any) -> None:
    runner = load_runner()
    if not isinstance(payload, dict):
        raise SupervisorError("TERMINAL_SHAPE_FAILED")
    required = {
        "specification", "implementation", "coordinate_free", "reads_coordinates",
        "monitoring_period", "daily_record_count", "observed_days_by_stream",
        "daily_records_sha256", "monthly_summary", "monthly_rows_sha256", "pass",
    }
    if set(payload) != required:
        raise SupervisorError("TERMINAL_KEYSET_FAILED")
    if payload["specification"] != runner.SPECIFICATION or \
       payload["implementation"] != runner.IMPLEMENTATION or \
       payload["coordinate_free"] is not True or payload["reads_coordinates"] is not False or \
       payload["pass"] is not True:
        raise SupervisorError("TERMINAL_CONTRACT_FAILED")
    if set(payload["observed_days_by_stream"]) != set(runner.STREAM_IDS) or \
       any(not isinstance(v, int) or v < 0
           for v in payload["observed_days_by_stream"].values()):
        raise SupervisorError("TERMINAL_OBSERVED_DAYS_FAILED")
    for name in ("daily_anomaly_records", "monthly_summaries"):
        artifact = runner.STATE_DIR / (name + ".json")
        if not artifact.exists():
            raise SupervisorError("ARTIFACT_MISSING:" + name)
        assert_coordinate_free(json.loads(artifact.read_text(encoding="utf-8")))
    daily_artifact = json.loads(
        (runner.STATE_DIR / "daily_anomaly_records.json").read_text(encoding="utf-8"))
    if daily_artifact.get("records_sha256") != payload["daily_records_sha256"] or \
       runner.canonical_sha256(daily_artifact["records"]) != payload["daily_records_sha256"]:
        raise SupervisorError("DAILY_ARTIFACT_HASH_MISMATCH")
    if runner.validate_daily_records(daily_artifact["records"]):
        raise SupervisorError("DAILY_ARTIFACT_REVALIDATION_FAILED")
    assert_coordinate_free(payload)


TERMINAL_VALIDATORS = {
    "build_climatology": validate_climatology_terminal,
    "daily_records": validate_daily_records_terminal,
}


def run(project: str, mode: str) -> int:
    if os.name != "nt":
        raise SupervisorError("ANOMALY_ENGINE_SUPERVISOR_REQUIRES_WINDOWS")
    base = load_base()
    load_runner()
    flag = MODE_FLAGS[mode]
    command = [sys.executable, str(RUNNER_PATH), "--project", project, flag]
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    print(json.dumps({"ANOMALY_ENGINE_SUPERVISOR_START": {
        "implementation": IMPLEMENTATION, "mode": mode,
        "supervisor_sha256": sha256_file(Path(__file__).resolve()),
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "request_wall_limit_seconds": REQUEST_LIMIT_SECONDS,
        "session_wall_limit_seconds": SESSION_LIMIT_SECONDS, "automatic_retry": False,
    }}, sort_keys=True), flush=True)
    session_deadline = time.monotonic() + SESSION_LIMIT_SECONDS
    messages: "queue.Queue[tuple[str, float, bytes | None]]" = queue.Queue()
    terminal_seen: dict[str, Any] = {}
    reason: str | None = None
    exit_code = PROTOCOL_EXIT_CODE
    terminal_key = TERMINAL_KEYS[mode]
    with base.WindowsJob() as job:
        process = subprocess.Popen(
            command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        job.assign(process)
        if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
            base.terminate_job(job, process, PROTOCOL_EXIT_CODE)
            raise SupervisorError("RUNNER_POSTLAUNCH_SHA256_MISMATCH")
        threads = [
            threading.Thread(target=base.reader_thread, args=(process.stdout, "stdout", messages), daemon=True),
            threading.Thread(target=base.reader_thread, args=(process.stderr, "stderr", messages), daemon=True),
        ]
        for thread in threads:
            thread.start()
        closed: set[str] = set()
        request_started: float | None = None
        try:
            while len(closed) < 2 or process.poll() is None or not messages.empty():
                if time.monotonic() >= session_deadline:
                    reason, exit_code = "SESSION_WALL_CLOCK_CUTOFF_REACHED", TIMEOUT_EXIT_CODE
                    break
                try:
                    name, observed, line = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    closed.add(name)
                    continue
                if name == "stdout":
                    text = line.decode("utf-8", errors="strict").rstrip("\r\n")
                    try:
                        obj = json.loads(text)
                    except ValueError:
                        obj = None
                    if isinstance(obj, dict) and "PHASE_REQUEST_START" in obj:
                        request_started = observed
                    elif isinstance(obj, dict) and "PHASE_REQUEST_COMPLETE" in obj:
                        elapsed = obj["PHASE_REQUEST_COMPLETE"].get("elapsed_seconds", 0.0)
                        if isinstance(elapsed, (int, float)) and elapsed >= REQUEST_LIMIT_SECONDS:
                            reason, exit_code = "REQUEST_WALL_CLOCK_CUTOFF_REACHED", TIMEOUT_EXIT_CODE
                            break
                        request_started = None
                    elif isinstance(obj, dict) and terminal_key in obj:
                        terminal_seen = obj[terminal_key]
                    elif isinstance(obj, dict) and FAIL_KEY in obj:
                        reason = "RUNNER_REPORTED_FAILURE"
                    if request_started is not None and observed - request_started >= REQUEST_LIMIT_SECONDS:
                        reason, exit_code = "REQUEST_WALL_CLOCK_CUTOFF_REACHED", TIMEOUT_EXIT_CODE
                        break
                dest = sys.stdout.buffer if name == "stdout" else sys.stderr.buffer
                dest.write(line)
                dest.flush()
        except (SupervisorError, UnicodeError) as exc:
            reason = type(exc).__name__ + ":" + str(exc)
        if reason is not None:
            base.terminate_job(job, process, exit_code)
            print(json.dumps({"ANOMALY_ENGINE_SUPERVISOR_STOP": {
                "reason": reason, "complete_child_process_tree_terminated": True,
                "automatic_retry": False}}, sort_keys=True), flush=True)
            return exit_code
        child_code = process.wait()
    if child_code != 0:
        print(json.dumps({"ANOMALY_ENGINE_SUPERVISOR_STOP": {
            "reason": "RUNNER_NONZERO_EXIT", "child_exit_code": child_code,
            "automatic_retry": False}}, sort_keys=True), flush=True)
        return child_code
    if not terminal_seen:
        print(json.dumps({"ANOMALY_ENGINE_SUPERVISOR_STOP": {
            "reason": "CHILD_SUCCESS_WITHOUT_TERMINAL", "automatic_retry": False}},
            sort_keys=True), flush=True)
        return PROTOCOL_EXIT_CODE
    try:
        TERMINAL_VALIDATORS[mode](terminal_seen)
    except SupervisorError as exc:
        print(json.dumps({"ANOMALY_ENGINE_SUPERVISOR_STOP": {
            "reason": "TERMINAL_REVALIDATION_FAILED:" + str(exc), "automatic_retry": False}},
            sort_keys=True), flush=True)
        return PROTOCOL_EXIT_CODE
    completion = {"mode": mode, "terminal_revalidated": True}
    if mode == "build_climatology":
        completion["baseline_row_count"] = terminal_seen["baseline_row_count"]
        completion["baseline_rows_sha256"] = terminal_seen["baseline_rows_sha256"]
    else:
        completion["daily_record_count"] = terminal_seen["daily_record_count"]
        completion["daily_records_sha256"] = terminal_seen["daily_records_sha256"]
        completion["monthly_rows_sha256"] = terminal_seen["monthly_rows_sha256"]
    print(json.dumps({"ANOMALY_ENGINE_SUPERVISOR_COMPLETE": completion},
                     sort_keys=True), flush=True)
    return 0


def self_test() -> int:
    failures: list[str] = []
    if sha256_file(BASE_SUPERVISOR_PATH) != EXPECTED_BASE_SUPERVISOR_SHA256:
        failures.append("base_pin")
    try:
        runner = load_runner()
    except SupervisorError as exc:
        failures.append("runner_pin:" + str(exc))
        runner = None
    if runner is not None:
        try:
            assert_coordinate_free({"bbox": [1, 2]})
            failures.append("coordinate_free_negative")
        except SupervisorError:
            pass
        try:
            assert_coordinate_free({"coordinate_free": True, "reads_coordinates": False})
        except SupervisorError as exc:
            failures.append("coordinate_free_false_positive:" + str(exc))
        # terminal keyset negative
        try:
            validate_climatology_terminal({"specification": "x"})
            failures.append("terminal_keyset_negative")
        except SupervisorError:
            pass
    try:
        job_tree_ok = load_base().offline_job_tree_termination_test()
    except Exception:  # noqa: BLE001
        job_tree_ok = False
        failures.append("windows_job_tree_exception")
    if not job_tree_ok:
        failures.append("windows_job_tree")
    print(json.dumps({"self_test": not failures, "failures": failures,
                      "windows_job_tree_termination_pass": "windows_job_tree" not in failures
                      and "windows_job_tree_exception" not in failures}, sort_keys=True))
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--build-climatology", action="store_true")
    parser.add_argument("--daily-records", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.project:
        parser.error("--project is required unless --self-test is used")
    mode = "build_climatology" if args.build_climatology else \
        "daily_records" if args.daily_records else None
    if mode is None:
        parser.error("choose a mode: --build-climatology or --daily-records")
        return 2
    try:
        return run(args.project, mode)
    except SupervisorError as exc:
        print(json.dumps({"ANOMALY_ENGINE_SUPERVISOR_STOP": {
            "reason": type(exc).__name__ + ":" + str(exc), "automatic_retry": False}},
            sort_keys=True), flush=True)
        return PROTOCOL_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
