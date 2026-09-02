# AUDIT-013 — historical observation-availability probe specification

- **Date:** 2026-09-02
- **Author:** Main Codex coordinator, for the user
- **Status:** **complete (2026-09).** Supervised run exit 0, 192 cells, terminal re-validated; results in `docs/HISTORICAL_OBSERVATION_AVAILABILITY_REPORT.md`. Implemented and pinned: runner `tools/run_historical_observation_availability_ee.py` SHA-256 `514242b69646c0e981cba59a00821de3705fb0388ea08650b4fb14665de45e75` (`historical_observation_availability_python_api_v1_h19v04_candidate_c_counts`); supervisor `tools/supervise_historical_observation_availability.py` (`historical_observation_availability_windows_supervisor_v1`), pinning that runner SHA and the AUDIT-010 base supervisor `8614de21…`. Both `--self-test` suites pass. A live single-block probe (2026-09) confirmed the Earth Engine graph and timing (~9 s per 5-year block).
- **Purpose:** Measure, from the real MODIS archive, how many usable historical observations actually sit behind a percentile — so `METH-001` (seasonal window width) and `METH-003` (minimum-sample thresholds) are fixed from data, not guesses. Raised by the user: the nominal ± 5-day × 20-year sample is ~220, but clouds and the QA rule cut it down, badly at night.
- **Authority and boundary:** This is a **bounded, read-only, coordinate-free counting diagnostic.** It computes no anomaly, climatology, percentile, or classification, selects no `METH-*` value, changes no completed audit or approved decision, and creates no Earth Engine asset, export, task, UI, or deployment. It reads only observation *counts*, never temperatures, never coordinates.

---

## 1. What it counts

For the approved lake-wide geometry and the approved `QA-002` acceptance rule, over the historical reference period **2003–2022 (20 calendar years)**:

For each **stream** (`terra_day`, `terra_night`, `aqua_day`, `aqua_night`), each **probe calendar date**, and each **window half-width** `W ∈ {5, 7, 10, 15}` days, report:

| Metric | Meaning |
|---|---|
| `years_with_any_accepted_observation` | of the 20 historical years, how many have **≥ 1** accepted valid-water pixel on **any** date within ± `W` days of the probe day-of-year |
| `total_accepted_daily_observations` | total count of distinct historical dates in that ± `W` window (across all 20 years) that produced ≥ 1 accepted valid-water pixel |
| `accepted_daily_observations_per_year` | the 20 per-year counts (list), so the median / min / spread is visible |
| `median_accepted_pixel_count_on_positive_days` | typical spatial coverage on the days that do produce data (an integer pixel count, not an area, not a temperature) |

A daily observation is "accepted" when it satisfies the approved `QA-002` candidate-C rule: exactly one source image that day; QC unmasked; provider-range valid LST, view time, and view angle; `mandatory_qa ∈ {0,1}`; `data_quality == 0`; `emissivity_error ≤ 1`; `lst_error ≤ 1`.

## 2. Probe calendar dates

The **15th of each of the 12 months** (mid-month), giving a full seasonal picture of the annual cycle without scanning all 365 days. 29 February never arises. (12 dates × 4 streams × 4 window widths = 192 reported cells.)

## 3. Geometry and QA — reuse the approved, verified path

- **Geometry:** the verified unrounded WISE WFD `HUAIH049` (2022) whole-lake polygon at **0 m** (no inward erosion) — exactly as approved in `SPACE-001`. Retrieved through the existing fail-closed WISE verifier; coordinates held in process memory only and **never persisted** in the repository, an Earth Engine asset, or an export (`AUDIT-003` / `AUDIT-006`).
- **QA mask:** the approved `QA-002` candidate-C rule. The probe runner byte-pins and reuses the mask/validity/QC-decoding code already implemented and verified in the `AUDIT-012` runner (`tools/run_nighttime_qa_candidate_comparison_ee.py`), so the counting uses exactly the accepted rule with no re-implementation.
- **Collections:** `MODIS/061/MOD11A1` (Terra), `MODIS/061/MYD11A1` (Aqua); the `LST_*`, `QC_*`, `*_view_time`, `*_view_angl` bands for the day / night phase, per the `PROTO-001` stream table.

## 4. Bounding — same guardrails as AUDIT-011 / AUDIT-012

- Coordinate-free runner + Windows Job Object process supervisor. Byte-pinned runner; the supervisor pins the runner SHA-256 and validates the lifecycle and terminal evidence.
- **Per Earth Engine request:** hard `480.000`-second wall-clock cutoff, exactly one attempt, no automatic retry, complete child-process-tree termination.
- **Whole session:** 165-minute ceiling.
- **Request plan:** a fixed, bounded, sequential set of Earth Engine reductions. Each reduction counts accepted daily observations for one (stream, probe-date) over the widest window (± 15 days) across a bounded slice of the 20 historical years; all four window widths and every §1 metric are then derived in Python from those counts. The exact year/date batching (as in `AUDIT-012`'s date-batched design) is tuned during implementation to stay under the Earth Engine per-request compute limit; the total is expected to be on the order of 150–250 bounded requests. The runner declares its exact request decomposition in a preflight line, and the supervisor checks the observed count against it.
- No NASA CMR / Earthdata / HDF access — this probe never leaves Earth Engine, so there is no source-verification sub-phase.

## 5. Output

A single coordinate-free terminal object: the 192 cells of §1, plus the probe configuration (streams, probe dates, window widths, geometry identity hash, pinned `AUDIT-012` mask SHA-256), a per-cell derivation so the numbers are reproducible, and pass/validation evidence. No temperatures, no coordinates, no per-pixel data, no raster bytes. Logs are coordinate-free.

## 6. How the result is used

- **`METH-001`:** for each stream, read off the smallest window width `W` at which `years_with_any_accepted_observation` reaches the `METH-003` minimum on ≥ 90 % of the 12 probe dates. If ± 5 already clears it (expected for daytime), keep ± 5; otherwise widen that stream's window.
- **`METH-003`:** check whether the proposed 10 / 20 minimum-sample thresholds are actually reachable, and on what fraction of the year; adjust the thresholds or accept that some winter nighttime dates will carry "insufficient history for a percentile".
- **`METH-005` / `QA-002` monthly minimum:** see how often the ≥ 3-valid-day monthly rule will actually be met, per stream, per season.
- It does **not** by itself select any `METH-*` value; it supplies the numbers, and the `METH-001 … 006` decision is then finalised and recorded.

## 7. Offline validation before any authenticated run

`--self-test` (no Earth Engine, no network): the fixed request decomposition arithmetic; the year/date-window derivation (that all four `W` values and the four §1 metrics reconstruct correctly from a stubbed per-date count table); the pinned `AUDIT-012` mask hash; coordinate-free screening of the terminal object; lifecycle ordering and cutoff rejection in the supervisor; Windows complete-child-tree termination.

## 8. What this is not

- Not a QA-rule comparison (that was `AUDIT-012`, complete) and not a daytime QA candidate comparison.
- Not a climatology or anomaly computation.
- Not authorization for any `METH-*` value, any Phase 3 implementation, any asset/export/UI, or any change to a completed audit.
