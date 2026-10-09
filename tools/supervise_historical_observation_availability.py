#!/usr/bin/env python3
"""Windows wall-clock / process-tree supervisor for AUDIT-013 (historical
observation-availability probe).

Byte-pins the runner, launches it inside a non-breakaway Windows Job Object,
enforces the 165-minute session ceiling and the per-request 480 s cutoff (a
completion observed at or after 480.000 s is rejected), forwards runner output
verbatim, terminates the complete child-process tree with no automatic retry,
and independently re-checks that the terminal object is present, coordinate-free,
and internally consistent.
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
RUNNER_PATH = ROOT / "tools" / "run_historical_observation_availability_ee.py"
BASE_SUPERVISOR_PATH = ROOT / "tools" / "supervise_whole_lake_boundary_shoreline_audit.py"
EXPECTED_RUNNER_SHA256 = "514242b69646c0e981cba59a00821de3705fb0388ea08650b4fb14665de45e75"
EXPECTED_BASE_SUPERVISOR_SHA256 = "8614de215b21e1722520f482c22516c04dea13950d58ba194ded252e9cfd7064"
IMPLEMENTATION = "historical_observation_availability_windows_supervisor_v1"
REQUEST_LIMIT_SECONDS = 480.000
SESSION_LIMIT_SECONDS = 165 * 60
TIMEOUT_EXIT_CODE = 124
PROTOCOL_EXIT_CODE = 125
TERMINAL_KEY = "HISTORICAL_OBSERVATION_AVAILABILITY_COMPLETE"
FAIL_KEY = "HISTORICAL_OBSERVATION_AVAILABILITY_FAILED"
_BASE: Any = None
_RUNNER: Any = None


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
        _RUNNER = load_module(RUNNER_PATH, EXPECTED_RUNNER_SHA256, "PINNED_AUDIT013_RUNNER")
    return _RUNNER


_COORDINATE_FREE_FORBIDDEN = re.compile(
    r"(?:^|_)(?:geometry|coordinates?|coords?|bounds?|bbox|extent|envelope|"
    r"latitude|longitude|lat|lon|lng|xmin|xmax|ymin|ymax|minx|maxx|miny|maxy|"
    r"easting|northing|wkt|geojson|temperature|kelvin|celsius)(?:_|$)",
    re.IGNORECASE,
)
_COORDINATE_FREE_ALLOWED = {
    "coordinate_free", "reads_coordinates", "reads_temperatures", "geometry",
    "geometry_identity_sha256",
}


def assert_coordinate_free(value: Any) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
                normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").casefold()
                if key not in _COORDINATE_FREE_ALLOWED and \
                   _COORDINATE_FREE_FORBIDDEN.search(normalized):
                    raise SupervisorError("TERMINAL_COORDINATE_KEY_LEAK:" + str(key))
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
    walk(value)


def validate_terminal(payload: Any) -> None:
    runner = load_runner()
    if not isinstance(payload, dict):
        raise SupervisorError("TERMINAL_SHAPE_FAILED")
    required = {
        "specification", "implementation", "coordinate_free", "reads_temperatures",
        "reads_coordinates", "acceptance_rule", "geometry", "geometry_identity_sha256",
        "historical_reference_period", "request_decomposition", "cell_count", "cells",
        "cells_sha256", "validation_errors", "pass", "scientific_interpretation",
    }
    if set(payload) != required:
        raise SupervisorError("TERMINAL_KEYSET_FAILED")
    if payload["specification"] != runner.SPECIFICATION or \
       payload["implementation"] != runner.IMPLEMENTATION or \
       payload["coordinate_free"] is not True or payload["reads_temperatures"] is not False or \
       payload["reads_coordinates"] is not False or \
       payload["acceptance_rule"] != "qa_002_candidate_c" or \
       payload["validation_errors"] != [] or payload["pass"] is not True:
        raise SupervisorError("TERMINAL_CONTRACT_FAILED")
    expected_cells = (len(runner.STREAM_IDS) * len(runner.PROBE_MONTHS)
                      * len(runner.WINDOW_HALF_WIDTHS))
    cells = payload["cells"]
    if not isinstance(cells, list) or len(cells) != expected_cells or \
       payload["cell_count"] != expected_cells:
        raise SupervisorError("TERMINAL_CELL_COUNT_FAILED")
    if runner.canonical_sha256(cells) != payload["cells_sha256"]:
        raise SupervisorError("TERMINAL_CELLS_HASH_FAILED")
    for cell in cells:
        if runner.validate_cell(cell):
            raise SupervisorError("TERMINAL_CELL_REVALIDATION_FAILED")
    if payload["request_decomposition"] != runner.REQUEST_DECOMPOSITION:
        raise SupervisorError("TERMINAL_DECOMPOSITION_FAILED")
    assert_coordinate_free(payload)


def run(project: str) -> int:
    if os.name != "nt":
        raise SupervisorError("AUDIT013_SUPERVISOR_REQUIRES_WINDOWS")
    base = load_base()
    load_runner()
    command = [sys.executable, str(RUNNER_PATH), "--project", project]
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    print(json.dumps({"AUDIT013_SUPERVISOR_START": {
        "implementation": IMPLEMENTATION,
        "supervisor_sha256": sha256_file(Path(__file__).resolve()),
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "request_wall_limit_seconds": REQUEST_LIMIT_SECONDS,
        "session_wall_limit_seconds": SESSION_LIMIT_SECONDS,
        "automatic_retry": False,
    }}, sort_keys=True), flush=True)
    session_deadline = time.monotonic() + SESSION_LIMIT_SECONDS
    messages: "queue.Queue[tuple[str, float, bytes | None]]" = queue.Queue()
    terminal_seen: dict[str, Any] = {}
    reason: str | None = None
    exit_code = PROTOCOL_EXIT_CODE
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
                    elif isinstance(obj, dict) and TERMINAL_KEY in obj:
                        terminal_seen = obj[TERMINAL_KEY]
                    elif isinstance(obj, dict) and FAIL_KEY in obj:
                        reason = "RUNNER_REPORTED_FAILURE"
                    if request_started is not None and \
                       observed - request_started >= REQUEST_LIMIT_SECONDS:
                        reason, exit_code = "REQUEST_WALL_CLOCK_CUTOFF_REACHED", TIMEOUT_EXIT_CODE
                        break
                dest = sys.stdout.buffer if name == "stdout" else sys.stderr.buffer
                dest.write(line)
                dest.flush()
        except (SupervisorError, UnicodeError) as exc:
            reason = type(exc).__name__ + ":" + str(exc)
        if reason is not None:
            base.terminate_job(job, process, exit_code)
            print(json.dumps({"AUDIT013_SUPERVISOR_STOP": {
                "reason": reason, "complete_child_process_tree_terminated": True,
                "automatic_retry": False, "acceptance_claimed": False}}, sort_keys=True), flush=True)
            return exit_code
        child_code = process.wait()
    if child_code != 0:
        print(json.dumps({"AUDIT013_SUPERVISOR_STOP": {
            "reason": "RUNNER_NONZERO_EXIT", "child_exit_code": child_code,
            "automatic_retry": False, "acceptance_claimed": False}}, sort_keys=True), flush=True)
        return child_code
    if not terminal_seen:
        print(json.dumps({"AUDIT013_SUPERVISOR_STOP": {
            "reason": "CHILD_SUCCESS_WITHOUT_TERMINAL", "automatic_retry": False}},
            sort_keys=True), flush=True)
        return PROTOCOL_EXIT_CODE
    try:
        validate_terminal(terminal_seen)
    except SupervisorError as exc:
        print(json.dumps({"AUDIT013_SUPERVISOR_STOP": {
            "reason": "TERMINAL_REVALIDATION_FAILED:" + str(exc),
            "automatic_retry": False, "acceptance_claimed": False}}, sort_keys=True), flush=True)
        return PROTOCOL_EXIT_CODE
    print(json.dumps({"AUDIT013_SUPERVISOR_COMPLETE": {
        "terminal_revalidated": True, "cell_count": terminal_seen["cell_count"],
        "cells_sha256": terminal_seen["cells_sha256"]}}, sort_keys=True), flush=True)
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
            assert_coordinate_free({"cells": [{"temperature_c": 3}]})
            failures.append("coordinate_free_negative")
        except SupervisorError:
            pass
        # positive terminal fixture from the runner's own assembly path
        cells = []
        for stream_id in runner.STREAM_IDS:
            for month in runner.PROBE_MONTHS:
                cells.extend(runner.assemble_cell(
                    [{"year": 2003, "doy": runner.dt_probe_doy(month), "count": 4}],
                    month, stream_id))
        payload = {
            "specification": runner.SPECIFICATION, "implementation": runner.IMPLEMENTATION,
            "coordinate_free": True, "reads_temperatures": False, "reads_coordinates": False,
            "acceptance_rule": "qa_002_candidate_c",
            "geometry": "wise_wfd_v1_9_huaih049_2022_unrounded_lake_wide_0m",
            "geometry_identity_sha256": "0" * 64,
            "historical_reference_period": [2003, 2022],
            "request_decomposition": runner.REQUEST_DECOMPOSITION,
            "cell_count": len(cells), "cells": cells,
            "cells_sha256": runner.canonical_sha256(cells),
            "validation_errors": [], "pass": True,
            "scientific_interpretation": (
                "Bounded read-only historical observation-count diagnostic only. It selects no "
                "METH-* value and computes no anomaly, climatology, or percentile."),
        }
        try:
            validate_terminal(payload)
        except SupervisorError as exc:
            failures.append("terminal_positive:" + str(exc))
        bad = json.loads(json.dumps(payload))
        bad["pass"] = False
        try:
            validate_terminal(bad)
            failures.append("terminal_negative_pass")
        except SupervisorError:
            pass
        bad2 = json.loads(json.dumps(payload))
        bad2["cells"] = bad2["cells"][:-1]
        try:
            validate_terminal(bad2)
            failures.append("terminal_negative_count")
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
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.project:
        parser.error("--project is required unless --self-test is used")
    try:
        return run(args.project)
    except SupervisorError as exc:
        print(json.dumps({"AUDIT013_SUPERVISOR_STOP": {
            "reason": type(exc).__name__ + ":" + str(exc), "automatic_retry": False}},
            sort_keys=True), flush=True)
        return PROTOCOL_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
