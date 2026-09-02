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
| 2 | Establish approved Terra/Aqua MODIS and Landsat 8/9 preprocessing and QA | **MODIS side complete** (four diagnostics + `AUDIT-013`; `SPACE-001`, `QA-002`, `METH-001`…`006` approved 2026-09). Landsat and ERA5-Land preprocessing not started (scoped as extensions — see `SCOPE-003`) |
| 3 | Implement approved climatology, anomaly, percentile, and data-quality methods | **In progress** — anomaly-engine runner + supervisor implemented and self-tested (`tools/run_anomaly_engine_ee.py` / `…supervise_anomaly_engine.py`, spec `docs/PHASE_3_ANOMALY_ENGINE_SPECIFICATION.md`). The one-time 2003–2022 climatology build is queued, waiting on a transient EEA provenance-server 503 |
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

After the 2026-09 supervisor consultation, `SPACE-001` (lake-wide geometry + 0 m shoreline treatment) and `QA-002` (per-pixel acceptance rule day/night, confidence tier, monthly minimum) are approved. The remaining application-level decisions are still open and continue to block Phases 3–6:

| Decision | Topic |
|---|---|
| `SPACE-001` | **Approved for lake-wide (2026-09):** geometry = the verified WISE `HUAIH049` (2022) whole-lake polygon already used in AUDIT-001…012; **shoreline treatment = 0 m** (full polygon, no inward erosion). No authoritative Hungarian basin boundary exists; basin subdivision and littoral/pelagic zones deferred to `SCOPE-003` (and the 1 km MODIS pixel + narrow-lake geometry makes reliable basin-level nighttime output unlikely regardless) |
| `QA-002` | **Approved (2026-09).** Per-pixel acceptance rule, day and night = **candidate C** (`mandatory_qa ∈ {0,1}, data_quality == 0, emissivity_error ≤ 1, lst_error ≤ 1` — accept the "LST error ≤ 2 K" tier), because AUDIT-011 + AUDIT-012 showed the strict rule and candidates A/B give ~0 nighttime coverage. Binding transparency condition: every daily record also reports strict/A/B coverage + the QC-byte histogram. Daily confidence tier = 3-level `ok`/`low`/`none` flag (never suppress on coverage; exact `f` cut-off calibrated in Phase 3–4). Monthly value needs ≥ 3 valid days/stream/unit. Detail in `docs/QA_002_PROPOSAL.md` and the `DECISIONS.md` QA-002 entry |
| `SCOPE-003` | **Proposal drafted (`docs/SCOPE_003_PROPOSAL.md`, 2026-09-02).** MVP core = the MODIS anomaly product (4 streams, lake-wide, daily + monthly) + deployed GEE app + written deliverables + MVP validation. ERA5-Land and Landsat are extensions; four-basin products are future work. Two choices (ERA5-Land / Landsat: core vs extension) await the user |
| `METH-001` … `METH-006` | **Approved (2026-09)** on the basis of `docs/METH_001_006_PROPOSAL.md` + `AUDIT-013`: ±5-day day-of-year window for all four streams; median reference; Type-7 percentile with the sample gate (≥20 full / 10–19 flagged / <10 anomaly-only); percentile-based warm labels; stream-specific monthly summaries at ≥3 valid days; no combined multi-sensor index |
| `AUDIT-013` | Historical observation-availability probe — **complete (2026-09)**, supervised run exit 0, 192 cells, terminal re-validated. **Result:** at ± 5 days every stream × month has 20/20 historical years covered (110–195 daily observations behind every percentile) — the historical sample is not thin; what thins is per-night spatial coverage (summer nights: ~6–9 % of the lake). Confirms `METH-001` = ± 5 days for all streams and that `METH-003`'s minimum rarely binds. `docs/HISTORICAL_OBSERVATION_AVAILABILITY_REPORT.md` |
| `DATA-005` | Detailed Landsat role, date selection, mixed-pixel treatment (not started) |
| `DATA-006` | ERA5-Land variables, aggregation, latency communication (not started) |
| `ARCH-001` | Precomputation asset/table schema, refresh cadence, deployment strategy |
| `VAL-001` | Validation acceptance criteria and the in-situ fallback |

Only `PROTO`/`AUDIT` engineering decisions have been approved beyond the original 13 August 2026 governance and scope baseline.

## 5. Other notes

- **Version control:** the AUDIT-012 + QA-002 work is committed (`6060ecc`). The three governance commits plus that one are the repo history; all other prototype/audit code (`src/`, the AUDIT-010/011 and prototype tools) and their docs are still uncommitted.
- **Supervisor consultation (2026-09):** held. The supervisor gave **no specific methodological recommendation** and confirmed **no authoritative Hungarian lake/basin boundary** is available. Decisions are therefore taken directly from the diagnostic evidence. Outcomes: `SPACE-001` lake-wide geometry approved (the WISE `HUAIH049` whole-lake polygon; basins deferred); `QA-002` nighttime acceptance rule approved (candidate C).
- **Next step:** run the queued climatology build once the EEA provenance endpoint recovers (~40 min), review the baseline coverage summary, then add the daily-record and monthly modes to the anomaly engine (light — they read the baseline). Then `ARCH-001` (precomputation + deployment) and Phase 4 (interface). ERA5-Land is the first extension after the MVP core; Landsat second.

## 6. One-paragraph summary

Phase 1 (audit) is done. The MODIS side of Phase 2 is complete: the four diagnostics plus `AUDIT-013`, and — after the 2026-09 supervisor consultation, at which the supervisor deferred to the evidence — the approved decisions `SPACE-001` (lake-wide geometry, 0 m), `QA-002` (candidate-C acceptance rule day + night, confidence tier, monthly minimum), and `METH-001` … `METH-006` (± 5-day window, median reference, Type-7 percentile with a sample gate, percentile labels, stream-specific monthly summaries, no merged index). `SCOPE-003` (the six-week MVP list) is proposed with two choices open, and the Phase 3 anomaly-engine specification is drafted. Landsat and ERA5-Land are scoped as extensions. Phase 3 (the climatology + anomaly + percentile + classification + monthly engine) is ready to build on approval; Phases 4–6 (interface, validation, finalisation) follow, with `ARCH-001` and `VAL-001` decided as Phase 3 output stabilises.
