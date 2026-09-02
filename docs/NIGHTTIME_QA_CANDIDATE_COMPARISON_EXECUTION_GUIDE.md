# Nighttime QA candidate comparison execution guide

Status: **complete** — the full v14 supervised run finished 2026-09-02 (exit 0; `NIGHTTIME_QA_CANDIDATE_COMPARISON_COMPLETE`, `"pass": true`, `validation_errors: []`, 245/245 EE phase markers, 15/15 NASA source requests, supervisor terminal re-validation clean). Results in `docs/NIGHTTIME_QA_CANDIDATE_COMPARISON_REPORT.md`; no QA candidate selected. Review- and launch-driven fixes applied through **v14**. Earlier fixes: `_frequency` delegation (v6); date-batched comparison for the 429 concurrency limit (v8); deterministic `Reducer.toList` transient extraction and `.floor()`ed pixel indices (v8); CMR/`echo10` response-format + checksum (v9); 2-date batches for an Earth Engine per-request memory limit (v10). Launch 5 got through all 245 Earth Engine requests + the CMR + `echo10` fetches and failed the authenticated HDF download: LP DAAC Earthdata Cloud answers a bearer-token protected-granule GET with a 302 to a short-lived signed download URL. **v11** made the download follow that redirect (validated, token stripped, `echo10` SHA-256 + byte size still enforced); **v12** — after launch 6 showed the real target is the LP DAAC egress CloudFront distribution `d1nklfio7vscoe.cloudfront.net`, not an S3 host — widened the redirect allowlist to `*.cloudfront.net` / AWS S3 / LP DAAC and allows up to two validated hops. **Launch 7 (v12) then completed all 245 Earth Engine requests + the CMR + `echo10` fetches + the authenticated HDF download and its checksum/byte-size checks**, and failed only in `verify_hdf_bytes` opening the file: the code used SDS name `Night_view_angle`, but the MOD11A1/MYD11A1 HDF-EOS2 name is `Night_view_angl` (truncated, no trailing "e"). **v13** uses the correct name (confirmed against NASA's Earthdata catalog); the Earth-Engine-side band stays `Night_view_angle`. **Launch 8 (v13) then completed the authenticated download + checksum + byte size + HDF open + all five SDS shape checks** and failed only in the final per-pixel `verify_hdf_bytes` cross-check: pyhdf's scalar-index read `selected[row, col]` returns a constant `1` on this file's **uint16** SDS (`LST_Night_1km`, `Clear_night_cov`) — a full-array `selected.get()` returns the true values. A bounded diagnostic against the real `MOD11A1.A2024019.h19v04` granule confirmed the three uint8 SDS already matched Earth Engine exactly (so the tile index and orientation are correct) and that `.get()` makes all five bands match Earth Engine exactly across all eight samples. **v14** reads each SDS once with `.get()` and indexes the NumPy array. All offline `--self-test` suites pass at v14; the 56-batch comparison test, the live CMR + `echo10` parse, and the redirect-reject path are green; and the full v14 supervised run completed cleanly on 2026-09-02.

Pins are runner `0682897404d20498996e7a73742c604ad350ad409cbb6c40b3071111a5d16760` (`nighttime_qa_candidate_comparison_python_api_v14_h19v04_date_batched_comparison`) and supervisor `27c8d71b3d54d2faa4af39be609748263033b053c92d38641c3c2a91d5ce9d55` (`nighttime_qa_candidate_comparison_windows_supervisor_v14_h19v04_date_batched_comparison`).

Expected wall-clock: roughly **85–120 min** — 224 comparison batch requests (~10–15 s each, observed for 2-date batches) plus 8 s pauses, plus 8 fast probes, plus setup and up to eight NASA cmr→echo10→HDF triples. Earth Engine compute time varies with service load (2-date batches have run 8–25 s). The independent 165-minute session ceiling still applies; if the run passes ~2.5 h without a terminal line, stop it. The runner now prints the actual Earth Engine error message on any failure.

The comparison must run only through the pinned Windows supervisor after its runner hash is frozen and independent validation passes. Direct child execution is forbidden because only the supervisor enforces the true monotonic per-request and whole-session limits.

## Local prerequisites

- the existing geometry-audit virtual environment with `requirements-geometry-audit.txt`, including pinned `pyhdf==0.11.7` (confirmed installed in `.venv-geometry-audit` on 2026-08-31, alongside `earthengine-api==1.7.37`, `shapely==2.1.1`, `pyproj==3.7.2`, `pillow==12.3.0`);
- official Earth Engine credentials and an approved project supplied at invocation;
- an Earthdata bearer token supplied only through the process environment as `EARTHDATA_BEARER_TOKEN`.

The runner checks HDF4 support and token shape before Earth Engine initialization. It never prints the token. It derives and requires MODIS sinusoidal `h19v04` from the transient canonical-projection global pixel indices before querying NASA; realistic Lake Balaton `global_x` values are around 23,000 and HDF columns are bounded as `global_x - 19*1200` in `0..1199`. NASA HDF bytes use a unique temporary file; every SDS/file handle is closed and the file is deleted and checked absent in `finally`, including failure paths. No raw raster or source coordinate is retained. The CMR `umm_json` search and the CMR `echo10` checksum fetch disable redirects and require exact final URL identity. The HDF download follows **up to two hops**: LP DAAC 302s a bearer-authenticated protected-granule GET to a signed download URL (observed: the LP DAAC egress CloudFront distribution `*.cloudfront.net`; some DAACs use a pre-signed AWS S3 URL). The runner validates each hop target is `https` on an allowed NASA-egress host (`*.cloudfront.net`, an AWS S3 host, or `data.lpdaac.earthdatacloud.nasa.gov`) whose path still carries the granule `.hdf` file name as a full segment, then re-requests **without** the bearer token (the signed URL authenticates itself). A redirect anywhere else fails closed with a coordinate-free `NIGHTTIME_QA_HDF_REDIRECT_REJECTED` line naming the host and object. The `echo10` XML is read only for the archived `.hdf` file's SHA-256 (or MD5) checksum and its exact `SizeInBytes`, both cross-checked against the downloaded bytes; nothing from it is persisted.

## Offline checks

```powershell
.\.venv-geometry-audit\Scripts\python.exe -m py_compile tools\run_nighttime_qa_candidate_comparison_ee.py tools\supervise_nighttime_qa_candidate_comparison.py
.\.venv-geometry-audit\Scripts\python.exe tools\run_nighttime_qa_candidate_comparison_ee.py --self-test
.\.venv-geometry-audit\Scripts\python.exe tools\supervise_nighttime_qa_candidate_comparison.py --self-test
```

## Request decomposition

The supervised run permits exactly 245 ordered Earth Engine request pairs: four metadata, one runtime fixture, eight projection inventories, eight earliest-anomaly probes, and 224 comparison batch requests (32 window×stream×treatment combinations × seven 2-date batches). A/B/C are simultaneous within every batch. Only the earliest anomalous original-0m date per stream-season may carry a transient bounded sample (extracted deterministically via `Reducer.toList`); other dates remain aggregate-only. After all comparisons pass, the runner may issue a canonical subsequence of up to eight NASA triples — CMR `umm_json` search → CMR `echo10` checksum → authenticated HDF download (up to two validated hops to a NASA-egress host) — in the fixed window×stream order (≤ 24 NASA requests). Every request has one attempt and a hard `480.000`-second wall-clock cutoff; the session has a separate 165-minute ceiling.

After independent validation, the supervisor-only command is:

```powershell
.\.venv-geometry-audit\Scripts\python.exe tools\supervise_nighttime_qa_candidate_comparison.py --project <approved-ee-project>
```

Do not launch it before validation passes.

## Evidence handling

Standard output is coordinate-free JSON. A complete terminal object requires 32 results, 448 treatment records representing 112 separate stream-date observations, full summaries, eight source-verification outcomes, zero validation errors, and `pass: true`. Temporary grid indices and raw values used for HDF equality never enter the terminal object. No checkpoint, asset, export, task, UI, application, or completed audit artifact is read or changed.
