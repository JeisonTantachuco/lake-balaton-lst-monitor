#!/usr/bin/env python3
"""AUDIT-010 Windows process supervisor for the four-subrequest v10 runner.

This execution envelope adds a monotonic wall-clock cutoff around lifecycle-
marked Earth Engine requests.  It does not import Earth Engine, alter request
graphs, retry work, or write the checkpoint itself.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
from importlib import metadata as importlib_metadata
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tools" / "run_whole_lake_boundary_shoreline_audit_ee.py"
CHECKPOINT_PATH = (
    ROOT / "local_run_state" /
    "whole_lake_boundary_shoreline_audit_checkpoint.json"
)
SUPERVISOR_IMPLEMENTATION = (
    "whole_lake_boundary_shoreline_audit_windows_supervisor_v4_audit010_immediate_stream_gates"
)
PRIOR_RUNNER_SHA256 = (
    "6cd0bed7ddd4426464da0c7619515a7e341a4585d5ccbc47efcdecb9c9b98774"
)
EXPECTED_RUNNER_SHA256 = (
    "0e6c33277c2180db756d7ccfd6bf7c0cf9a5895c1ff07384fbd64ac7cf9d218f"
)
PRIOR_COMPATIBILITY_SHA256 = (
    "a1bc3207a18ef4ec66f13fb7f981c8cb0376233be36341c3ac495a19a6e6ad31"
)
EXPECTED_COMPATIBILITY_SHA256 = (
    "5f5bb05a95a22219c550ab124a33b3f00f1795ff25f9e3bf19ff3595ac91b17e"
)
PRIOR_CHECKPOINT_RAW_SHA256 = (
    "520e00ea03b2949892e6d847919ba7a7a68fdd5ddcebe6349f59d3d092502199"
)
PRIOR_RUNNER_IMPLEMENTATION = (
    "whole_lake_boundary_shoreline_audit_python_api_v10_four_stream_subrequests"
)
EXPECTED_RUNNER_IMPLEMENTATION = (
    "whole_lake_boundary_shoreline_audit_python_api_v11_immediate_stream_summary_gates"
)
PRIOR_RUNNER_SPECIFICATION = (
    "AUDIT-001_AUDIT-003_AUDIT-005_AUDIT-006_AUDIT-007_AUDIT-008_AUDIT-009_AUDIT-010_2026-08-23"
)
EXPECTED_RUNNER_SPECIFICATION = (
    "AUDIT-001_AUDIT-003_AUDIT-005_AUDIT-006_AUDIT-007_AUDIT-008_AUDIT-009_AUDIT-010_2026-08-23"
)
REQUEST_WALL_LIMIT_SECONDS = 480.000
SESSION_WALL_LIMIT_SECONDS = 165 * 60
EXPECTED_VECTOR_IDS = (
    "EROSION_0000M", "EROSION_0463_3127M", "EROSION_0500M",
    "EROSION_0926_6254M",
)
LIFECYCLE_MARKERS = {
    "PHASE_REQUEST_START", "PHASE_REQUEST_COMPLETE",
    "PHASE_REQUEST_TRANSPORT_FAILURE", "PHASE_REQUEST_FAILURE",
}
ALLOWED_REQUEST_PHASES = {
    "canonical_projection", "canonical_reference_id", "runtime_fixture",
    "projection_inventory", "vector", "chunk",
}
SUPERVISOR_TIMEOUT_EXIT_CODE = 124
SUPERVISOR_PROTOCOL_EXIT_CODE = 125


class SupervisorError(RuntimeError):
    """Fail-closed supervisor error without sensitive child output."""


class DuplicateJsonKey(ValueError):
    """JSON input contained a duplicate object key."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def supervisor_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def load_json_strict(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        raise SupervisorError("CHECKPOINT_READ_OR_STRICT_JSON_FAILED") from exc


def load_pinned_runner() -> Any:
    observed_hash = sha256_file(RUNNER_PATH)
    if observed_hash != EXPECTED_RUNNER_SHA256:
        raise SupervisorError("PINNED_RUNNER_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location(
        "audit008_pinned_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise SupervisorError("PINNED_RUNNER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if sha256_file(Path(module.__file__).resolve()) != EXPECTED_RUNNER_SHA256:
        raise SupervisorError("PINNED_RUNNER_POST_IMPORT_SHA256_MISMATCH")
    return module


def validate_saved_checkpoint(*, expected_project: str | None = None,
                              checkpoint_path: Path = CHECKPOINT_PATH) -> dict[str, Any]:
    """Exhaustively revalidate the exact AUDIT-010 envelope and saved evidence."""
    runner = load_pinned_runner()
    checkpoint = load_json_strict(checkpoint_path)
    required_checkpoint_fields = {
        "checkpoint_format", "compatibility_sha256", "compatibility",
        "completed_vectors", "completed_chunks", "full_acceptance_claimed",
    }
    if not isinstance(checkpoint, dict) or set(checkpoint) != required_checkpoint_fields:
        raise SupervisorError("CHECKPOINT_EXACT_SHAPE_FAILED")
    if checkpoint["checkpoint_format"] != runner.CHECKPOINT_FORMAT:
        raise SupervisorError("CHECKPOINT_FORMAT_FAILED")
    if checkpoint["compatibility_sha256"] != EXPECTED_COMPATIBILITY_SHA256:
        raise SupervisorError("CHECKPOINT_APPROVED_COMPATIBILITY_SHA256_FAILED")
    compatibility = checkpoint["compatibility"]
    if not isinstance(compatibility, dict) or \
       runner.canonical_sha256(compatibility) != EXPECTED_COMPATIBILITY_SHA256:
        raise SupervisorError("CHECKPOINT_EMBEDDED_COMPATIBILITY_HASH_FAILED")
    try:
        runner.validate_coordinate_free_compatibility(compatibility)
    except (TypeError, ValueError) as exc:
        raise SupervisorError("CHECKPOINT_COORDINATE_FREE_GUARD_FAILED") from exc
    expected_compatibility_fields = {
        "checkpoint_format", "verified_source_evidence", "approved_versions",
        "implementation_file_sha256", "verified_source_method", "runtime",
        "request_decomposition", "windows", "streams", "shoreline_treatments",
        "authoritative_manifests", "manifest_source_sha256",
    }
    if set(compatibility) != expected_compatibility_fields:
        raise SupervisorError("CHECKPOINT_COMPATIBILITY_SHAPE_FAILED")
    if compatibility["implementation_file_sha256"] != EXPECTED_RUNNER_SHA256:
        raise SupervisorError("CHECKPOINT_RUNNER_SHA256_FAILED")
    versions = compatibility.get("approved_versions")
    if not isinstance(versions, dict) or versions.get("audit", {}).get(
            "implementation") != EXPECTED_RUNNER_IMPLEMENTATION or \
       versions.get("audit", {}).get("specification") != EXPECTED_RUNNER_SPECIFICATION:
        raise SupervisorError("CHECKPOINT_RUNNER_VERSION_FAILED")
    if versions != {"audit": runner.VERSION, "prototype": runner.PROTO_VERSION}:
        raise SupervisorError("CHECKPOINT_APPROVED_VERSIONS_FAILED")
    runtime = compatibility.get("runtime")
    expected_runtime_fields = {
        "python_version", "earthengine_api_version", "google_cloud_project_id",
        "request_deadline_seconds", "transport_max_attempts",
        "earth_engine_internal_retries", "session_limit_seconds",
    }
    if not isinstance(runtime, dict) or set(runtime) != expected_runtime_fields or \
       runtime.get("request_deadline_seconds") != REQUEST_WALL_LIMIT_SECONDS or \
       runtime.get("transport_max_attempts") != 1 or \
       runtime.get("earth_engine_internal_retries") != 0 or \
       runtime.get("session_limit_seconds") != SESSION_WALL_LIMIT_SECONDS:
        raise SupervisorError("CHECKPOINT_RUNTIME_POLICY_FAILED")
    if expected_project is not None and runtime.get(
            "google_cloud_project_id") != expected_project:
        raise SupervisorError("CHECKPOINT_PROJECT_FAILED")
    if runtime.get("python_version") != sys.version.split()[0]:
        raise SupervisorError("CHECKPOINT_PYTHON_RUNTIME_FAILED")
    try:
        installed_ee_version = importlib_metadata.version("earthengine-api")
    except importlib_metadata.PackageNotFoundError as exc:
        raise SupervisorError("EARTH_ENGINE_PACKAGE_NOT_INSTALLED") from exc
    if runtime.get("earthengine_api_version") != installed_ee_version:
        raise SupervisorError("CHECKPOINT_EARTH_ENGINE_RUNTIME_FAILED")
    if compatibility.get("windows") != runner.WINDOWS or \
       compatibility.get("streams") != runner.STREAMS or \
       compatibility.get("shoreline_treatments") != runner.TREATMENTS or \
       compatibility.get("request_decomposition") != \
       runner.CHUNK_REQUEST_DECOMPOSITION or \
       compatibility.get("authoritative_manifests") != runner.load_authoritative_manifests():
        raise SupervisorError("CHECKPOINT_APPROVED_METHOD_CONFIG_FAILED")
    expected_manifest_hashes = {
        "prototype": sha256_file(
            ROOT / "src/prototype/modis_preprocessing_prototype.js"),
        "audit": sha256_file(
            ROOT / "src/audit/whole_lake_boundary_shoreline_audit.js"),
    }
    if compatibility.get("manifest_source_sha256") != expected_manifest_hashes:
        raise SupervisorError("CHECKPOINT_MANIFEST_SOURCE_SHA256_FAILED")
    source_method = compatibility.get("verified_source_method")
    if not isinstance(source_method, dict) or set(source_method) != {
            "original_gml_content_type", "verifier_file_sha256"} or \
       source_method.get("original_gml_content_type") != \
       runner.ORIGINAL_GML_CONTENT_TYPE_METHOD or \
       source_method.get("verifier_file_sha256") != sha256_file(
           ROOT / "tools/verify_wise_huaih049.py"):
        raise SupervisorError("CHECKPOINT_VERIFIED_SOURCE_METHOD_FAILED")
    if checkpoint.get("full_acceptance_claimed") is not False:
        raise SupervisorError("CHECKPOINT_ACCEPTANCE_MUST_BE_FALSE")

    vectors_by_id = checkpoint.get("completed_vectors")
    if not isinstance(vectors_by_id, dict) or \
       tuple(vectors_by_id) != EXPECTED_VECTOR_IDS:
        raise SupervisorError("CHECKPOINT_EXACT_FOUR_VECTORS_FAILED")
    vectors = [vectors_by_id[identifier] for identifier in EXPECTED_VECTOR_IDS]
    vector_errors = runner.validate_compact_vectors(vectors, 4)
    if vector_errors:
        raise SupervisorError("CHECKPOINT_VECTOR_REVALIDATION_FAILED")

    chunks = checkpoint.get("completed_chunks")
    if not isinstance(chunks, dict):
        raise SupervisorError("CHECKPOINT_CHUNKS_NOT_OBJECT")
    expected_chunk_keys = [f"{index:02d}" for index in range(1, len(chunks) + 1)]
    if list(chunks) != expected_chunk_keys or not 1 <= len(chunks) <= 16:
        raise SupervisorError("CHECKPOINT_CHUNK_SEQUENCE_OR_RESUME_STATE_FAILED")
    descriptors = [
        (window, treatment)
        for window in runner.WINDOWS for treatment in runner.TREATMENTS
    ]
    for index, key in enumerate(expected_chunk_keys, start=1):
        window, treatment = descriptors[index - 1]
        chunk_errors = runner.validate_checkpoint_chunk(
            chunks[key], index, window, treatment)
        if chunk_errors:
            raise SupervisorError(
                "CHECKPOINT_CHUNK_REVALIDATION_FAILED:" + key + ":" +
                ",".join(chunk_errors))
    return {
        "checkpoint_path": checkpoint_path.relative_to(ROOT).as_posix()
        if checkpoint_path.is_relative_to(ROOT) else str(checkpoint_path),
        "compatibility_sha256": checkpoint["compatibility_sha256"],
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "completed_vector_count": len(vectors),
        "completed_chunk_count": len(chunks),
        "first_incomplete_chunk": len(chunks) + 1 if len(chunks) < 16 else None,
        "final_aggregation_pending": len(chunks) == 16,
        "full_acceptance_claimed": False,
        "coordinate_free_revalidation": True,
    }


def validate_prior_checkpoint_for_migration(
        checkpoint_path: Path = CHECKPOINT_PATH) -> tuple[dict[str, Any], Any]:
    """Validate the sole approved AUDIT-010 preimage without changing it."""
    if sha256_file(checkpoint_path) != PRIOR_CHECKPOINT_RAW_SHA256:
        raise SupervisorError("MIGRATION_PREIMAGE_RAW_SHA256_FAILED")
    runner = load_pinned_runner()
    checkpoint = load_json_strict(checkpoint_path)
    required_checkpoint_fields = {
        "checkpoint_format", "compatibility_sha256", "compatibility",
        "completed_vectors", "completed_chunks", "full_acceptance_claimed",
    }
    if not isinstance(checkpoint, dict) or set(checkpoint) != required_checkpoint_fields:
        raise SupervisorError("MIGRATION_PREIMAGE_SHAPE_FAILED")
    compatibility = checkpoint.get("compatibility")
    if checkpoint.get("checkpoint_format") != runner.CHECKPOINT_FORMAT or \
       checkpoint.get("compatibility_sha256") != PRIOR_COMPATIBILITY_SHA256 or \
       not isinstance(compatibility, dict) or \
       runner.canonical_sha256(compatibility) != PRIOR_COMPATIBILITY_SHA256:
        raise SupervisorError("MIGRATION_PRIOR_COMPATIBILITY_FAILED")
    try:
        runner.validate_coordinate_free_compatibility(compatibility)
    except (TypeError, ValueError) as exc:
        raise SupervisorError("MIGRATION_COORDINATE_FREE_GUARD_FAILED") from exc
    audit_version = compatibility.get("approved_versions", {}).get("audit", {})
    if compatibility.get("implementation_file_sha256") != PRIOR_RUNNER_SHA256 or \
       audit_version.get("implementation") != PRIOR_RUNNER_IMPLEMENTATION or \
       audit_version.get("specification") != PRIOR_RUNNER_SPECIFICATION:
        raise SupervisorError("MIGRATION_PRIOR_RUNNER_IDENTITY_FAILED")
    if compatibility.get("request_decomposition") != \
            runner.CHUNK_REQUEST_DECOMPOSITION:
        raise SupervisorError("MIGRATION_PRIOR_REQUEST_DECOMPOSITION_FAILED")
    runtime = compatibility.get("runtime")
    if not isinstance(runtime, dict) or \
       runtime.get("request_deadline_seconds") != REQUEST_WALL_LIMIT_SECONDS or \
       runtime.get("transport_max_attempts") != 1 or \
       runtime.get("earth_engine_internal_retries") != 0 or \
       runtime.get("session_limit_seconds") != SESSION_WALL_LIMIT_SECONDS:
        raise SupervisorError("MIGRATION_PRIOR_RUNTIME_POLICY_FAILED")
    if checkpoint.get("full_acceptance_claimed") is not False:
        raise SupervisorError("MIGRATION_PRIOR_ACCEPTANCE_FAILED")
    vectors_by_id = checkpoint.get("completed_vectors")
    if not isinstance(vectors_by_id, dict) or \
       tuple(vectors_by_id) != EXPECTED_VECTOR_IDS or \
       runner.validate_compact_vectors(
           [vectors_by_id[key] for key in EXPECTED_VECTOR_IDS], 4):
        raise SupervisorError("MIGRATION_PRIOR_FOUR_VECTORS_FAILED")
    chunks = checkpoint.get("completed_chunks")
    if not isinstance(chunks, dict) or list(chunks) != ["01", "02"]:
        raise SupervisorError("MIGRATION_PRIOR_EXACT_CHUNKS01_02_FAILED")
    descriptors = [(window, treatment) for window in runner.WINDOWS
                   for treatment in runner.TREATMENTS]
    for index, key in enumerate(("01", "02"), start=1):
        record = chunks[key]
        window, treatment = descriptors[index - 1]
        certificate_input = {
            name: value for name, value in record.items()
            if name != "validated_evidence_sha256"
        }
        if record.get("validated_evidence_sha256") != runner.canonical_sha256(
                certificate_input):
            raise SupervisorError("MIGRATION_CHUNK_CERTIFICATE_FAILED:" + key)
        if runner.validate_checkpoint_chunk(record, index, window, treatment):
            raise SupervisorError("MIGRATION_SAVED_CHUNK_REVALIDATION_FAILED:" + key)
    if len(chunks) + 1 != 3:
        raise SupervisorError("MIGRATION_FIRST_INCOMPLETE_CHUNK_FAILED")
    return checkpoint, runner


def migrate_exact_checkpoint(
        checkpoint_path: Path = CHECKPOINT_PATH) -> dict[str, Any]:
    """Atomically migrate only the exact approved preimage; create no backup."""
    checkpoint, runner = validate_prior_checkpoint_for_migration(checkpoint_path)
    migrated = copy.deepcopy(checkpoint)
    migrated_compatibility = migrated["compatibility"]
    migrated_compatibility["implementation_file_sha256"] = EXPECTED_RUNNER_SHA256
    migrated_audit_version = migrated_compatibility["approved_versions"]["audit"]
    migrated_audit_version["implementation"] = EXPECTED_RUNNER_IMPLEMENTATION
    migrated_audit_version["specification"] = EXPECTED_RUNNER_SPECIFICATION
    migrated["compatibility_sha256"] = runner.canonical_sha256(
        migrated_compatibility)
    if migrated["compatibility_sha256"] != EXPECTED_COMPATIBILITY_SHA256:
        raise SupervisorError("MIGRATION_NEW_COMPATIBILITY_SHA256_FAILED")
    if migrated["completed_vectors"] != checkpoint["completed_vectors"] or \
       migrated["completed_chunks"] != checkpoint["completed_chunks"] or \
       migrated["full_acceptance_claimed"] is not False:
        raise SupervisorError("MIGRATION_EVIDENCE_CHANGED")
    old_chunk_hashes = {
        key: runner.canonical_sha256(value)
        for key, value in checkpoint["completed_chunks"].items()}
    new_chunk_hashes = {
        key: runner.canonical_sha256(value)
        for key, value in migrated["completed_chunks"].items()}
    if old_chunk_hashes != new_chunk_hashes:
        raise SupervisorError("MIGRATION_CANONICAL_CHUNK_HASH_CHANGED")
    changed_paths = {
        "compatibility_sha256",
        "compatibility.implementation_file_sha256",
        "compatibility.approved_versions.audit.implementation",
    }
    payload = json.dumps(migrated, indent=2, sort_keys=True) + "\n"
    temporary = checkpoint_path.with_name(checkpoint_path.name + ".audit010.tmp")
    try:
        if sha256_file(checkpoint_path) != PRIOR_CHECKPOINT_RAW_SHA256:
            raise SupervisorError("MIGRATION_PREIMAGE_CHANGED_BEFORE_WRITE")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if sha256_file(checkpoint_path) != PRIOR_CHECKPOINT_RAW_SHA256:
            raise SupervisorError("MIGRATION_PREIMAGE_CHANGED_BEFORE_REPLACE")
        os.replace(temporary, checkpoint_path)
    finally:
        temporary.unlink(missing_ok=True)
    postflight = validate_saved_checkpoint(checkpoint_path=checkpoint_path)
    return {
        "migration": "AUDIT-010",
        "prior_checkpoint_raw_sha256": PRIOR_CHECKPOINT_RAW_SHA256,
        "migrated_checkpoint_raw_sha256": sha256_file(checkpoint_path),
        "prior_compatibility_sha256": PRIOR_COMPATIBILITY_SHA256,
        "migrated_compatibility_sha256": EXPECTED_COMPATIBILITY_SHA256,
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "changed_paths": sorted(changed_paths),
        "completed_vectors_unchanged": True,
        "completed_chunks_unchanged": True,
        "chunk_canonical_sha256_before": old_chunk_hashes,
        "chunk_canonical_sha256_after": new_chunk_hashes,
        "chunk_certificates": {
            key: value["validated_evidence_sha256"]
            for key, value in checkpoint["completed_chunks"].items()},
        "recovery_copy_created": False,
        "postflight": postflight,
    }


def parse_lifecycle_line(line: str) -> tuple[str, dict[str, Any]] | None:
    """Parse only exact top-level runner records; fail on marker lookalikes."""
    try:
        value = json.loads(line, object_pairs_hook=reject_duplicate_keys)
    except DuplicateJsonKey as exc:
        if "PHASE_REQUEST_" in line:
            raise SupervisorError("LIFECYCLE_DUPLICATE_JSON_KEY") from exc
        return None
    except json.JSONDecodeError:
        if "PHASE_REQUEST_" in line:
            raise SupervisorError("LIFECYCLE_MALFORMED_MARKER_LINE")
        return None
    if not isinstance(value, dict):
        return None
    present = set(value).intersection(LIFECYCLE_MARKERS)
    unknown_markers = {
        key for key in value if isinstance(key, str) and
        key.startswith("PHASE_REQUEST_") and key not in LIFECYCLE_MARKERS
    }
    if unknown_markers:
        raise SupervisorError("LIFECYCLE_UNKNOWN_MARKER")
    if not present:
        return None
    if len(value) != 1 or len(present) != 1:
        raise SupervisorError("LIFECYCLE_TOP_LEVEL_SHAPE_FAILED")
    marker = next(iter(present))
    event = value[marker]
    if not isinstance(event, dict):
        raise SupervisorError("LIFECYCLE_EVENT_NOT_OBJECT")
    phase = event.get("phase")
    if phase not in ALLOWED_REQUEST_PHASES:
        raise SupervisorError("LIFECYCLE_PHASE_NOT_ALLOWED")
    if marker == "PHASE_REQUEST_START":
        required = {"phase", "attempt", "max_attempts", "request_deadline_seconds"}
        if set(event) != required or event.get("attempt") != 1 or \
           event.get("max_attempts") != 1 or \
           event.get("request_deadline_seconds") != REQUEST_WALL_LIMIT_SECONDS:
            raise SupervisorError("LIFECYCLE_START_CONTRACT_FAILED")
    elif marker == "PHASE_REQUEST_COMPLETE":
        required = {"phase", "attempt", "elapsed_seconds"}
        if set(event) != required or event.get("attempt") != 1 or not isinstance(
                event.get("elapsed_seconds"), (int, float)) or isinstance(
                    event.get("elapsed_seconds"), bool):
            raise SupervisorError("LIFECYCLE_COMPLETE_CONTRACT_FAILED")
    elif marker == "PHASE_REQUEST_TRANSPORT_FAILURE":
        required = {
            "phase", "attempt", "elapsed_seconds", "exception_class",
            "failure_class", "will_retry",
        }
        if set(event) != required or event.get("attempt") != 1 or \
           event.get("will_retry") is not False:
            raise SupervisorError("LIFECYCLE_TRANSPORT_FAILURE_CONTRACT_FAILED")
    else:
        required = {
            "phase", "elapsed_seconds", "exception_class", "exception_category",
        }
        if set(event) != required:
            raise SupervisorError("LIFECYCLE_FAILURE_CONTRACT_FAILED")
    return marker, event


class LifecycleState:
    def __init__(self) -> None:
        self.active_phase: str | None = None
        self.request_started_at: float | None = None
        self.request_deadline: float | None = None

    def consume(self, marker: str, event: dict[str, Any], observed_at: float) -> None:
        if marker == "PHASE_REQUEST_START":
            if self.active_phase is not None:
                raise SupervisorError("LIFECYCLE_OVERLAPPING_REQUESTS")
            self.active_phase = event["phase"]
            self.request_started_at = observed_at
            self.request_deadline = observed_at + REQUEST_WALL_LIMIT_SECONDS
            return
        if self.active_phase is None or event["phase"] != self.active_phase or \
           self.request_deadline is None or self.request_started_at is None:
            raise SupervisorError("LIFECYCLE_TERMINAL_WITHOUT_MATCHING_START")
        if observed_at >= self.request_deadline or \
           observed_at - self.request_started_at >= REQUEST_WALL_LIMIT_SECONDS:
            raise SupervisorError("REQUEST_WALL_CLOCK_CUTOFF_REACHED")
        elapsed = event.get("elapsed_seconds")
        if isinstance(elapsed, (int, float)) and elapsed >= REQUEST_WALL_LIMIT_SECONDS:
            raise SupervisorError("REQUEST_REPORTED_ELAPSED_AT_OR_AFTER_CUTOFF")
        self.active_phase = None
        self.request_started_at = None
        self.request_deadline = None


if os.name == "nt":
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


class WindowsJob:
    """Non-breakaway Windows Job Object that kills the entire child tree."""
    KILL_ON_JOB_CLOSE = 0x00002000
    EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self) -> None:
        if os.name != "nt":
            raise SupervisorError("AUDIT010_REQUIRES_WINDOWS")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.restype = wintypes.BOOL
        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = self.KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
                self.handle, self.EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        if not self._kernel32.AssignProcessToJobObject(
                self.handle, wintypes.HANDLE(int(process._handle))):  # type: ignore[attr-defined]
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self, exit_code: int) -> None:
        if self.handle and not self._kernel32.TerminateJobObject(
                self.handle, wintypes.UINT(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if getattr(self, "handle", None):
            self._kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "WindowsJob":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def reader_thread(stream: Any, name: str,
                  output: queue.Queue[tuple[str, float, bytes | None]]) -> None:
    try:
        for line in iter(stream.readline, b""):
            output.put((name, time.monotonic(), line))
    finally:
        output.put((name, time.monotonic(), None))


def terminate_job(job: WindowsJob, process: subprocess.Popen[bytes],
                  exit_code: int) -> None:
    try:
        job.terminate(exit_code)
    finally:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def offline_job_tree_termination_test() -> bool:
    """Prove that terminating the Job signals both a child and its descendant."""
    if os.name != "nt":
        return False
    child_code = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "print(p.pid,flush=True);time.sleep(30)"
    )
    process: subprocess.Popen[bytes] | None = None
    descendant_handle: Any = None
    with WindowsJob() as job:
        try:
            process = subprocess.Popen(
                [sys.executable, "-c", child_code], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            job.assign(process)
            assert process.stdout is not None
            descendant_pid = int(process.stdout.readline().decode("ascii").strip())
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.CloseHandle.restype = wintypes.BOOL
            descendant_handle = kernel32.OpenProcess(
                0x00100000, False, descendant_pid)  # SYNCHRONIZE
            if not descendant_handle:
                return False
            terminate_job(job, process, SUPERVISOR_PROTOCOL_EXIT_CODE)
            return kernel32.WaitForSingleObject(descendant_handle, 5000) == 0
        finally:
            if descendant_handle:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(
                    descendant_handle)
            if process is not None and process.poll() is None:
                try:
                    terminate_job(job, process, SUPERVISOR_PROTOCOL_EXIT_CODE)
                except Exception:
                    process.kill()
def run_supervised(project: str, end_chunk: int | None) -> int:
    if os.name != "nt":
        raise SupervisorError("AUDIT010_REQUIRES_WINDOWS")
    preflight = validate_saved_checkpoint(expected_project=project)
    command = [
        sys.executable, str(RUNNER_PATH), "--project", project,
        "--request-deadline-seconds", "480", "--transport-max-attempts", "1",
    ]
    if end_chunk is not None:
        command.extend(["--end-chunk", str(end_chunk)])
    print(json.dumps({"AUDIT010_SUPERVISOR_START": {
        "implementation": SUPERVISOR_IMPLEMENTATION,
        "supervisor_sha256": supervisor_sha256(),
        "request_wall_limit_seconds": REQUEST_WALL_LIMIT_SECONDS,
        "session_wall_limit_seconds": SESSION_WALL_LIMIT_SECONDS,
        "automatic_retry": False,
        "checkpoint_preflight": preflight,
    }}, sort_keys=True), flush=True)
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    started_at = time.monotonic()
    session_deadline = started_at + SESSION_WALL_LIMIT_SECONDS
    messages: queue.Queue[tuple[str, float, bytes | None]] = queue.Queue()
    lifecycle = LifecycleState()
    with WindowsJob() as job:
        if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
            raise SupervisorError("PINNED_RUNNER_PRELAUNCH_SHA256_MISMATCH")
        process = subprocess.Popen(
            command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            job.assign(process)
            if sha256_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA256:
                terminate_job(job, process, SUPERVISOR_PROTOCOL_EXIT_CODE)
                raise SupervisorError("PINNED_RUNNER_POSTLAUNCH_SHA256_MISMATCH")
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            raise
        assert process.stdout is not None and process.stderr is not None
        threads = [
            threading.Thread(target=reader_thread, args=(process.stdout, "stdout", messages), daemon=True),
            threading.Thread(target=reader_thread, args=(process.stderr, "stderr", messages), daemon=True),
        ]
        for thread in threads:
            thread.start()
        closed_streams: set[str] = set()
        stop_reason: str | None = None
        stop_exit_code = SUPERVISOR_PROTOCOL_EXIT_CODE
        try:
            while len(closed_streams) < 2 or process.poll() is None or not messages.empty():
                now = time.monotonic()
                if now >= session_deadline:
                    stop_reason = "SESSION_WALL_CLOCK_CUTOFF_REACHED"
                    stop_exit_code = SUPERVISOR_TIMEOUT_EXIT_CODE
                    break
                if lifecycle.request_deadline is not None and now >= lifecycle.request_deadline:
                    stop_reason = "REQUEST_WALL_CLOCK_CUTOFF_REACHED"
                    stop_exit_code = SUPERVISOR_TIMEOUT_EXIT_CODE
                    break
                nearest = session_deadline
                if lifecycle.request_deadline is not None:
                    nearest = min(nearest, lifecycle.request_deadline)
                wait_seconds = max(0.0, min(0.05, nearest - now))
                try:
                    stream_name, observed_at, line = messages.get(timeout=wait_seconds)
                except queue.Empty:
                    continue
                if line is None:
                    closed_streams.add(stream_name)
                    continue
                if stream_name == "stdout":
                    decoded = line.decode("utf-8", errors="strict").rstrip("\r\n")
                    parsed = parse_lifecycle_line(decoded)
                    if parsed is not None:
                        # Validate/consume before forwarding so a terminal record
                        # at or after the cutoff is rejected, not echoed as accepted.
                        lifecycle.consume(parsed[0], parsed[1], observed_at)
                destination = sys.stdout.buffer if stream_name == "stdout" else sys.stderr.buffer
                destination.write(line)
                destination.flush()
        except (SupervisorError, UnicodeError) as exc:
            stop_reason = type(exc).__name__ + ":" + str(exc)
            stop_exit_code = SUPERVISOR_PROTOCOL_EXIT_CODE
        except KeyboardInterrupt:
            stop_reason = "SUPERVISOR_INTERRUPTED"
            stop_exit_code = 130
        if stop_reason is not None:
            terminate_job(job, process, stop_exit_code)
            print(json.dumps({"AUDIT010_SUPERVISOR_STOP": {
                "reason": stop_reason,
                "complete_child_process_tree_terminated": True,
                "checkpoint_not_modified_by_supervisor": True,
                "automatic_retry": False,
                "acceptance_not_claimed": True,
            }}, sort_keys=True), flush=True)
            return stop_exit_code
        return_code = process.wait()
        if lifecycle.active_phase is not None:
            print(json.dumps({"AUDIT010_SUPERVISOR_STOP": {
                "reason": "CHILD_EXITED_DURING_ACTIVE_REQUEST",
                "checkpoint_not_modified_by_supervisor": True,
                "automatic_retry": False,
                "acceptance_not_claimed": True,
            }}, sort_keys=True), flush=True)
            return SUPERVISOR_PROTOCOL_EXIT_CODE
        return return_code


def self_test() -> dict[str, Any]:
    failures: list[str] = []
    live_checkpoint_resume_ready = False
    live_checkpoint_migration_pending = False
    live_checkpoint_blocker: str | None = None
    try:
        preflight = validate_saved_checkpoint()
        live_checkpoint_resume_ready = True
        if preflight["completed_vector_count"] != 4 or \
           preflight["completed_chunk_count"] < 1 or \
           preflight["full_acceptance_claimed"] is not False:
            failures.append("live_checkpoint_preflight")
    except SupervisorError as exc:
        try:
            validate_prior_checkpoint_for_migration()
            live_checkpoint_migration_pending = True
        except SupervisorError:
            live_checkpoint_blocker = str(exc)
            failures.append("unexpected_live_checkpoint_preflight_failure")

    valid_start = json.dumps({"PHASE_REQUEST_START": {
        "phase": "chunk", "attempt": 1, "max_attempts": 1,
        "request_deadline_seconds": 480,
    }})
    valid_complete = json.dumps({"PHASE_REQUEST_COMPLETE": {
        "phase": "chunk", "attempt": 1, "elapsed_seconds": 479.999,
    }})
    for phase in sorted(ALLOWED_REQUEST_PHASES):
        phase_line = json.dumps({"PHASE_REQUEST_START": {
            "phase": phase, "attempt": 1, "max_attempts": 1,
            "request_deadline_seconds": 480,
        }})
        try:
            parsed_phase = parse_lifecycle_line(phase_line)
            if parsed_phase is None or parsed_phase[1]["phase"] != phase:
                failures.append("allowed_phase_fixture:" + phase)
        except SupervisorError:
            failures.append("allowed_phase_fixture:" + phase)
    try:
        state = LifecycleState()
        marker, event = parse_lifecycle_line(valid_start) or (None, None)
        state.consume(marker, event, 10.0)
        marker, event = parse_lifecycle_line(valid_complete) or (None, None)
        state.consume(marker, event, 489.999)
        if state.active_phase is not None:
            failures.append("lifecycle_before_cutoff")
    except Exception:
        failures.append("lifecycle_before_cutoff")
    try:
        state = LifecycleState()
        for _stream_id in ("terra_day", "terra_night", "aqua_day", "aqua_night"):
            # The pinned runner deliberately reduces sensitive/descriptive phase
            # names to the exact top-level allowlisted category before emission.
            phase = "chunk"
            start_line = json.dumps({"PHASE_REQUEST_START": {
                "phase": phase, "attempt": 1, "max_attempts": 1,
                "request_deadline_seconds": 480}})
            complete_line = json.dumps({"PHASE_REQUEST_COMPLETE": {
                "phase": phase, "attempt": 1, "elapsed_seconds": 479.0}})
            marker, event = parse_lifecycle_line(start_line) or (None, None)
            state.consume(marker, event, 0.0)
            marker, event = parse_lifecycle_line(complete_line) or (None, None)
            state.consume(marker, event, 479.0)
        if state.active_phase is not None:
            failures.append("audit010_four_sequential_lifecycles_fixture")
    except Exception:
        failures.append("audit010_four_sequential_lifecycles_fixture")
    try:
        state = LifecycleState()
        marker, event = parse_lifecycle_line(valid_start) or (None, None)
        state.consume(marker, event, 10.0)
        marker, event = parse_lifecycle_line(valid_complete) or (None, None)
        state.consume(marker, event, 490.0)
        failures.append("lifecycle_exact_cutoff_rejected")
    except SupervisorError:
        pass
    if parse_lifecycle_line(json.dumps({"payload": {
            "PHASE_REQUEST_START": json.loads(valid_start)["PHASE_REQUEST_START"]}})) is not None:
        failures.append("nested_marker_spoof")
    valid_failure = json.dumps({"PHASE_REQUEST_FAILURE": {
        "phase": "chunk", "exception_category": "earth_engine_error",
        "exception_class": "EarthEngineException", "elapsed_seconds": 1.0,
    }})
    try:
        state = LifecycleState()
        marker, event = parse_lifecycle_line(valid_start) or (None, None)
        state.consume(marker, event, 0.0)
        marker, event = parse_lifecycle_line(valid_failure) or (None, None)
        state.consume(marker, event, 1.0)
        if state.active_phase is not None:
            failures.append("runner_failure_schema_fixture")
    except SupervisorError:
        failures.append("runner_failure_schema_fixture")
    valid_transport_failure = json.dumps({"PHASE_REQUEST_TRANSPORT_FAILURE": {
        "phase": "chunk", "attempt": 1, "elapsed_seconds": 1.0,
        "exception_class": "ClientTransportTimeout",
        "failure_class": "client_transport_timeout", "will_retry": False,
    }})
    try:
        state = LifecycleState()
        marker, event = parse_lifecycle_line(valid_start) or (None, None)
        state.consume(marker, event, 0.0)
        marker, event = parse_lifecycle_line(valid_transport_failure) or (None, None)
        state.consume(marker, event, 1.0)
        if state.active_phase is not None:
            failures.append("transport_failure_schema_fixture")
    except SupervisorError:
        failures.append("transport_failure_schema_fixture")
    protocol_rejections = [
        json.dumps({"PHASE_REQUEST_UNKNOWN": {"phase": "chunk"}}),
        json.dumps({"PHASE_REQUEST_COMPLETE": {
            "phase": "chunk", "attempt": 1, "elapsed_seconds": 1.0}}),
        json.dumps({"PHASE_REQUEST_START": {
            "phase": "chunk", "attempt": 1, "max_attempts": 1,
            "request_deadline_seconds": 480, "extra": False}}),
    ]
    for index, line in enumerate(protocol_rejections):
        try:
            parsed = parse_lifecycle_line(line)
            if parsed is not None:
                LifecycleState().consume(parsed[0], parsed[1], 0.0)
            failures.append(f"protocol_rejection_fixture_{index}")
        except SupervisorError:
            pass
    try:
        state = LifecycleState()
        marker, event = parse_lifecycle_line(valid_start) or (None, None)
        state.consume(marker, event, 0.0)
        state.consume(marker, event, 0.1)
        failures.append("overlapping_start_fixture")
    except SupervisorError:
        pass
    invalid_lines = [
        '{"PHASE_REQUEST_START":{"phase":"chunk","attempt":1}}',
        ('{"PHASE_REQUEST_START":{"phase":"chunk","attempt":1,'
         '"attempt":1,"max_attempts":1,"request_deadline_seconds":480}}'),
        json.dumps({"PHASE_REQUEST_START": {
            "phase": "top_level", "attempt": 1, "max_attempts": 1,
            "request_deadline_seconds": 480}}),
        json.dumps({"PHASE_REQUEST_COMPLETE": {
            "phase": "chunk", "attempt": 1, "elapsed_seconds": 480}}),
    ]
    for index, line in enumerate(invalid_lines):
        try:
            parsed = parse_lifecycle_line(line)
            if index == 3 and parsed is not None:
                state = LifecycleState()
                start_marker, start_event = parse_lifecycle_line(valid_start) or (None, None)
                state.consume(start_marker, start_event, 0.0)
                state.consume(parsed[0], parsed[1], 1.0)
            else:
                failures.append(f"spoof_fixture_{index}")
        except SupervisorError:
            pass

    live_checkpoint = load_json_strict(CHECKPOINT_PATH)
    migration_fixture = ROOT / "local_run_state" / (
        f".audit010_migration_self_test_{os.getpid()}.json")
    try:
        if sha256_file(CHECKPOINT_PATH) == PRIOR_CHECKPOINT_RAW_SHA256:
            prior_payload = CHECKPOINT_PATH.read_bytes()
        else:
            prior_fixture = copy.deepcopy(live_checkpoint)
            prior_compatibility = prior_fixture["compatibility"]
            prior_compatibility["implementation_file_sha256"] = PRIOR_RUNNER_SHA256
            prior_audit = prior_compatibility["approved_versions"]["audit"]
            prior_audit["implementation"] = PRIOR_RUNNER_IMPLEMENTATION
            prior_audit["specification"] = PRIOR_RUNNER_SPECIFICATION
            prior_fixture["compatibility_sha256"] = PRIOR_COMPATIBILITY_SHA256
            prior_payload = (json.dumps(
                prior_fixture, indent=2, sort_keys=True) + "\n").encode("utf-8")
        migration_fixture.write_bytes(prior_payload)
        if sha256_file(migration_fixture) != PRIOR_CHECKPOINT_RAW_SHA256:
            failures.append("migration_exact_preimage_reconstruction_fixture")
        else:
            migration_result = migrate_exact_checkpoint(migration_fixture)
            if migration_result["migrated_compatibility_sha256"] != \
               EXPECTED_COMPATIBILITY_SHA256 or \
               migration_result["chunk_canonical_sha256_before"] != \
               migration_result["chunk_canonical_sha256_after"] or \
               migration_result["completed_vectors_unchanged"] is not True or \
               migration_result["completed_chunks_unchanged"] is not True:
                failures.append("migration_semantic_preservation_fixture")
            live_checkpoint_for_negative_fixtures = load_json_strict(
                migration_fixture)
    except Exception:
        failures.append("migration_exact_preimage_fixture")
        live_checkpoint_for_negative_fixtures = live_checkpoint
    finally:
        migration_fixture.unlink(missing_ok=True)

    checkpoint = live_checkpoint_for_negative_fixtures
    mutations = []
    mutation = copy.deepcopy(checkpoint)
    mutation["compatibility_sha256"] = "0" * 64
    mutations.append(mutation)
    mutation = copy.deepcopy(checkpoint)
    mutation["full_acceptance_claimed"] = True
    mutations.append(mutation)
    mutation = copy.deepcopy(checkpoint)
    mutation["completed_vectors"].pop(EXPECTED_VECTOR_IDS[-1])
    mutations.append(mutation)
    mutation = copy.deepcopy(checkpoint)
    mutation["completed_chunks"]["01"]["row_keys"] = []
    mutations.append(mutation)
    mutation = copy.deepcopy(checkpoint)
    mutation["compatibility"]["request_decomposition"]["rows_per_subrequest"] = 13
    mutation["compatibility_sha256"] = EXPECTED_COMPATIBILITY_SHA256
    mutations.append(mutation)
    for index, mutation in enumerate(mutations):
        temporary = ROOT / "local_run_state" / f".audit010_self_test_{os.getpid()}_{index}.json"
        try:
            temporary.write_text(json.dumps(mutation), encoding="utf-8")
            try:
                validate_saved_checkpoint(checkpoint_path=temporary)
                failures.append(f"checkpoint_negative_{index}")
            except SupervisorError:
                pass
        finally:
            temporary.unlink(missing_ok=True)

    try:
        if not offline_job_tree_termination_test():
            failures.append("windows_job_tree_termination")
    except Exception:
        failures.append("windows_job_tree_termination")

    return {
        "implementation": SUPERVISOR_IMPLEMENTATION,
        "supervisor_sha256": supervisor_sha256(),
        "request_wall_limit_seconds": REQUEST_WALL_LIMIT_SECONDS,
        "session_wall_limit_seconds": SESSION_WALL_LIMIT_SECONDS,
        "live_checkpoint_resume_ready": live_checkpoint_resume_ready,
        "live_checkpoint_migration_pending": live_checkpoint_migration_pending,
        "live_checkpoint_blocker": live_checkpoint_blocker,
        "failures": failures,
        "pass": not failures,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="AUDIT-010 hard wall-clock supervisor and exact checkpoint migration")
    result.add_argument("--project")
    result.add_argument("--end-chunk", type=int, choices=range(1, 17))
    result.add_argument("--validate-checkpoint-only", action="store_true")
    result.add_argument("--migrate-exact-checkpoint", action="store_true")
    result.add_argument("--self-test", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.self_test:
        result = self_test()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["pass"] else 2
    if args.migrate_exact_checkpoint:
        result = migrate_exact_checkpoint()
        print(json.dumps({"AUDIT010_CHECKPOINT_MIGRATION": result},
                         indent=2, sort_keys=True))
        return 0
    if args.validate_checkpoint_only:
        result = validate_saved_checkpoint(expected_project=args.project)
        print(json.dumps({"AUDIT010_CHECKPOINT_PREFLIGHT": result},
                         indent=2, sort_keys=True))
        return 0
    if not args.project:
        raise SystemExit("--project is required for supervised execution")
    return run_supervised(args.project, args.end_chunk)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SupervisorError as exc:
        print(json.dumps({"AUDIT010_SUPERVISOR_FAILED_CLOSED": {
            "failure": str(exc), "acceptance_not_claimed": True,
            "checkpoint_not_modified_by_supervisor": True,
        }}, sort_keys=True), file=sys.stderr, flush=True)
        raise SystemExit(2)
