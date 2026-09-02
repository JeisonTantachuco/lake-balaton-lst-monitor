# Lake Balaton Thermal-Anomaly Monitoring — Project Status Report

- **Date:** 2026-08-31
- **Author:** Main Codex coordinator, for the user
- **Purpose:** Brief snapshot of all project phases — what is done, what is missing, and where work currently stands.
- **Authority note:** This is a status summary only. It approves nothing and changes no decision. `PROJECT_CONTEXT.md` and `DECISIONS.md` remain authoritative.

## 1. Governance context

Every material scientific or scope decision is gated on explicit user approval and recorded in `DECISIONS.md`. By design, the project has so far produced only small, individually approved, non-UI diagnostics. There is **no GEE application, UI, Earth Engine asset, export, permanent precomputation, or deployment** yet.

## 2. Six-week delivery frame (SCOPE-002)

| # | Phase | Status |
|---|-------|--------|
| 1 | Audit and reproduce the prior study, application, shared code, and data behavior | **Done** — Phase 1 scientific and technical audit complete; it underpins every later specification |
| 2 | Establish approved Terra/Aqua MODIS and Landsat 8/9 preprocessing and QA | **In progress — current phase** (all four MODIS diagnostics complete as of 2026-09-02; Landsat and ERA5-Land untouched; QA thresholds still to be proposed and approved) |
| 3 | Implement approved climatology, anomaly, percentile, and data-quality methods | **Not started** — blocked on proposed decisions |
| 4 | Build approved basin comparisons and daily/monthly interface outputs | **Not started** |
| 5 | Validate formulas, sensor separation, clouds, coverage, shoreline pixels, consistency, reproducibility | **Not started** (only prototype-level engineering validation so far) |
| 6 | Finalize application, documented code, user guidance, technical report, and presentation | **Not started** |

## 3. Phase 2 detail — the diagnostics chain

Phase 2 has been run as a sequence of bounded, approved, coordinate-free diagnostics. Each one gathers evidence; none of them selects a final scientific rule.

| Diagnostic | Decision(s) | Status |
|---|---|---|
| First MODIS preprocessing diagnostic prototype | PROTO-001, PROTO-002 | **Complete** — engineering-validated 2026-08-17; 56/56 rows passed. Confirmed collection access, 4-stream separation (Terra/Aqua × day/night), scale factors, full QC decoding, masking, timing metadata, area accounting, and the sparse null-by-omission schema |
| Whole-lake boundary and shoreline sensitivity audit | AUDIT-001 → AUDIT-010 | **Complete** — authenticated supervised run finished with exit code 0; all 896 date-stream-treatment rows, 80 coverage summaries, and 4 shoreline treatments passed with zero failures. Established WISE WFD v1.9 `HUAIH049` (2022) polygon provenance and shoreline mixed-pixel sensitivity |
| Nighttime gate-attribution diagnostic | AUDIT-011 | **Complete** — all 21 lifecycle phases passed, terminal `pass: true`; attributed nighttime coverage loss across the QA gates over 112 nighttime observations |
| Nighttime QA candidate A/B/C comparison | AUDIT-012 | **Complete** — the full v14 supervised run finished 2026-09-02 with exit 0: `NIGHTTIME_QA_CANDIDATE_COMPARISON_COMPLETE`, `"pass": true`, `validation_errors: []`, 245/245 Earth Engine phase markers, 15/15 NASA source requests, 32 results / 448 treatment records, supervisor terminal re-validation clean. 5 of 8 `(window, stream)` returned `verified_exact_original_hdf_samples` (checksum + byte size + all EE values/masks exact); 3 had no M0,D>0 pixel. **Result** (feeds `QA-002`, selects nothing): 98.7 % of valid-water nighttime pixels are QC byte 65 (`M1/D0/E0/T1` — LST error ≤ 2 K, not ≤ 1 K); candidate A keeps ~0.5 % of common validity, **candidate B keeps 0 %** (nothing at night has `T=0`), candidate C keeps ~99 %; shoreline erosion lowers C's coverage fraction ~0.9–1.5 pp at 460–925 m. Full numbers in `docs/NIGHTTIME_QA_CANDIDATE_COMPARISON_REPORT.md`. Independent review + eight authenticated launches + targeted authenticated tests (2026-08-31 … 09-02) drove fail-closed fixes through **v14** (`…_date_batched_comparison`); all offline `--self-test` suites green. v6 fixed a missing `_frequency` delegation. v8 introduced date-batched comparisons (concurrency 429 fix) + an earliest-anomaly probe per window/stream, replaced random `Image.sample` with deterministic `Reducer.toList`, floored `pixelCoordinates` to integer grid indices. Launch 4 completed the full EE phase then failed the first NASA CMR search: the parser assumed a UMM-G shape MOD11A1/MYD11A1 .061 lacks (no `.hdf` on `GranuleUR`, extra URL path segment, no per-file checksum). **v9** reads UMM-G as it is and fetches the SHA-256 checksum + exact byte size from CMR's legacy `echo10` metadata (cmr → echo10 → HDF; NASA ceiling 16 → 24; live-confirmed against the five real anomaly granules). A v10 launch then hit `Earth Engine memory capacity exceeded` on a 5-date batch — so **v10** uses 2-date batches (224 comparison requests, 245 EE requests, pause 8 s; authenticated 56-batch test clean). Launches 5–6 got through all 245 EE requests + CMR + `echo10` and failed the HDF download: LP DAAC 302-redirects a bearer-token protected-granule GET to its egress CloudFront distribution `d1nklfio7vscoe.cloudfront.net`. **v11** made the download follow the redirect (validated, token stripped, `echo10` checksum + size still enforced; operator-approved relaxation of the "zero redirects" rule for the HDF download only); **v12** widened the allowlist to `*.cloudfront.net` / AWS S3 / LP DAAC and allows up to two hops. Launch 7 (v12) then completed the authenticated download + checksum + byte-size checks — the first end-to-end download — and failed only on a wrong HDF SDS name (`Night_view_angle` vs the truncated `Night_view_angl`); **v13** uses the correct name. Launch 8 (v13) completed the download, checksum, byte size, HDF open, and all five SDS shape checks and failed only in the final per-pixel `verify_hdf_bytes` cross-check — a pyhdf scalar-index bug that returns a constant `1` on this file's uint16 SDS (`LST_Night_1km`, `Clear_night_cov`); **v14** reads each SDS with `.get()` and indexes the NumPy array. Launch 9 (v14, 2026-09-02) completed the whole diagnostic end to end. No QA candidate has been selected |

### What AUDIT-012 is doing

It compares three nighttime QA interpretations (A, B, C) simultaneously over the same 112 nighttime observations and all four shoreline treatments, without choosing one:

- **A = `V & M=0`** — common validity plus mandatory QA flag zero; the three detailed quality flags (data quality, emissivity error, LST error) are reported but do not gate.
- **B = `V & M∈{0,1} & D=0 & E=0 & T=0`** — allows "good" and "other quality" mandatory tiers, but requires all three detailed flags to be zero.
- **C = `V & M∈{0,1} & D=0 & E≤1 & T≤1`** — same as B but tolerates one level of emissivity and LST error.

A is *not* nested with B or C; B is a strict subset of C. The comparison quantifies the coverage, missing-date, seasonal, selectivity, and shoreline consequences of each, as input to the still-unresolved `QA-002`.

## 4. What is still missing

Twelve of the thirteen application-level decisions remain **proposed** (not approved), which blocks Phases 3–6:

| Decision | Topic |
|---|---|
| `SPACE-001` | Authoritative lake / basin geometries and spatial units (shoreline audit produced the evidence but does not auto-select) |
| `QA-002` | Minimum valid-water coverage and QA acceptance thresholds — evidence complete (`AUDIT-011` + `AUDIT-012`) and the **full proposal is drafted** (`docs/QA_002_PROPOSAL.md`, 2026-09-02): recommends candidate C for the nighttime rule (strict rule and candidates A/B yield ~0 nighttime coverage; 98.7 % of valid-water night pixels are QC byte 65 = `M1/D0/E0/T1`), a provisional symmetric daytime rule pending a bounded daytime check, a per-observation confidence tier instead of coverage-based suppression, and a ≥ 3-valid-day monthly minimum. Awaiting the supervisor consultation |
| `SCOPE-003` | The six-week minimum viable output set vs. optional extensions |
| `METH-001` | Historical seasonal window (±5 days or other) |
| `METH-002` | Historical reference statistic (mean / median / smoothed climatology) |
| `METH-003` | Percentile estimator and minimum historical sample count |
| `METH-004` | Classification thresholds and exact thermal-status labels |
| `METH-005` | Monthly aggregation rules when streams or days are missing |
| `METH-006` | Whether any standardized multi-sensor indicator is created (direct averaging excluded) |
| `DATA-005` | Detailed Landsat role, date selection, mixed-pixel treatment (not started) |
| `DATA-006` | ERA5-Land variables, aggregation, latency communication (not started) |
| `ARCH-001` | Precomputation asset/table schema, refresh cadence, deployment strategy |
| `VAL-001` | Validation acceptance criteria and the in-situ fallback |

Only `PROTO`/`AUDIT` engineering decisions have been approved beyond the original 13 August 2026 governance and scope baseline.

## 5. Other notes

- **Version control:** only the three governance commits are committed. All prototype and audit code (`src/`, `tools/`) and every diagnostic specification, execution guide, and report in `docs/` is currently uncommitted (untracked or modified).
- **Timeline:** the supervisor consultation was expected at "the beginning of September 2026" — i.e. imminent. That consultation is the natural point to resolve `SPACE-001`, `QA-002`, and `SCOPE-003` and thereby unblock Phases 3 and 4.
- **Next step (2026-09-02):** all four MODIS Phase-2 diagnostics are complete and the `QA-002` proposal is drafted (`docs/QA_002_PROPOSAL.md`). Remaining before Phase 3: user/supervisor decision on `QA-002`, `SPACE-001`, and `SCOPE-003` at the consultation; drafting the other proposed decisions the consultation needs; and starting the Landsat (`DATA-005`) and ERA5-Land (`DATA-006`) work, which has not begun. An optional bounded daytime QA candidate comparison ("`AUDIT-013`") is recommended in the `QA-002` proposal before the daytime rule is fixed.

## 6. One-paragraph summary

Phase 1 (audit) is done. Phase 2 (preprocessing and QA) is complete on the MODIS side — all four approved diagnostics finished, `AUDIT-012` on 2026-09-02 — while the Landsat and ERA5-Land parts of Phase 2 have not begun and the QA acceptance thresholds themselves are still to be proposed and approved. Phases 3 through 6 (analytical methods, interface, validation, finalization) are blocked pending roughly twelve unresolved scientific and scope decisions that the early-September supervisor consultation is expected to unlock; the `AUDIT-012` result makes clear that the nighttime QA threshold cannot require the strict LST-error tier without discarding essentially all nighttime data.
