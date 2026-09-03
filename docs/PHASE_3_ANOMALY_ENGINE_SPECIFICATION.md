# Phase 3 — anomaly engine specification

- **Date:** 2026-09-02
- **Author:** Main Codex coordinator, for the user
- **Status:** approved to build (user, 2026-09). **Implemented:** runner `tools/run_anomaly_engine_ee.py` SHA-256 `f649df317cc0694b8051d608f6040c7b094c706d6f4b5916eb748c1b92a8510b` (`anomaly_engine_python_api_v1_lake_wide_candidate_c`); supervisor `tools/supervise_anomaly_engine.py` (`anomaly_engine_windows_supervisor_v1`, pinning that runner + the AUDIT-010 base supervisor + the WISE source module). Both `--self-test` suites pass. The EEA CDR-metadata provenance endpoint has been 503 since ~2026-09-02; with user approval the engine added a **geometry-only fallback** (see §5a): it fired on the first run, the re-fetched polygon matched the `AUDIT-003` raw and canonical SHA-256 hashes byte-for-byte, and the verified copy is now cached. **The 2003–2022 climatology baseline is built** (2026-09-03; `docs/PHASE_3_CLIMATOLOGY_REPORT.md`; `baseline_rows_sha256 1ff9ca8d…`). An initial run was rejected on inspection for a month-range bug that skipped February–June; `validate_baseline` now fails closed on that signature (> 3 day-of-year per stream with `n = 0`). The **`--daily-records` mode** (monitoring dates 2023 → today → daily anomaly records + monthly summaries) is implemented and self-tested; running it is the remaining Phase 3 step. `ARCH-001` (storage / refresh / serving + the `AUDIT-003` re-verification once the EEA endpoint recovers) follows.
- **Approved inputs this builds on:** `SPACE-001` (lake-wide WISE `HUAIH049` 2022 polygon, 0 m), `QA-002` (candidate-C acceptance rule day + night; `ok`/`low`/`none` confidence tier from valid-water fraction `f`; monthly ≥ 3 valid days; strict/A/B transparency), `METH-001` (± 5-day day-of-year window, 2003–2022, per stream, all four streams), `METH-002` (**report both** the historical median and mean; median-based anomaly is the headline; record `median_minus_mean_c`), `METH-003` (Type-7 percentile; sample gate n ≥ 20 / 10–19 flagged / < 10 anomaly-only / 0 none), `METH-004` (percentile labels), `METH-005` (stream-specific monthly aggregation), `METH-006` (no merged multi-sensor index), `AUDIT-013` (sample availability confirmed), `TERM-001` (terminology), `QA-001` (no interpolation, explicit missing state), `SCOPE-003` (MVP core = this product + app + writing).
- **Boundary:** produces the climatology baseline, the daily anomaly records, and the monthly summaries. It does not build the interface (Phase 4), the validation (Phase 5 / `VAL-001`), or the deployment (`ARCH-001`). It creates no Earth Engine asset, export, or UI until `ARCH-001` is approved — Phase 3 output during development is a local, coordinate-free table.

---

## 1. The daily lake value

For one monitoring date and one stream, over the lake-wide 0 m geometry:

1. Select the MODIS image for that UTC day (`MODIS/061/MOD11A1` for Terra, `MODIS/061/MYD11A1` for Aqua). Require **exactly one** source image; otherwise the day is `no valid observation` (`QA-001`).
2. Apply the approved **candidate-C** acceptance mask (`QA-002`): QC present; provider-range LST (7500–65535), view time (0–240), view angle (0–130); `mandatory_qa ∈ {0,1}`; `data_quality == 0`; `emissivity_error ≤ 1`; `lst_error ≤ 1`.
3. **`daily_lst_c`** = the area-weighted mean of the accepted pixels' LST, converted with the provider scale: `LST_K = DN × 0.02`, `LST_C = LST_K − 273.15`. Area weighting uses `ee.Image.pixelArea()` on the native MODIS grid (equal-area sinusoidal, so this ≈ the simple pixel mean).
4. **`valid_water_fraction` `f`** = accepted pixel-centre count ÷ the lake's eligible pixel-centre count (fixed per stream from the native grid).
5. **`confidence`** = `ok` if `f ≥ 0.15`; `low` if `0 < f < 0.15`; `none` if `f = 0` (→ `no valid observation`). *(The 0.15 cut-off is the `QA-002` provisional value, calibrated once here against the observed distribution and then fixed.)*
6. **Transparency fields** (`QA-002`): the coverage fraction the strict rule, candidate A, and candidate B would each have produced, and the 256-bin QC-byte pixel histogram over the QC-observed area.

The same steps 1–5 define a **historical daily value** for any date 2003–2022.

## 2. The climatology baseline

For each stream and each **day-of-year** `D` in 1–366 (29 Feb folded onto 28 Feb):

- Collect every historical daily value (§1) from 2003–2022 whose date is within **± 5 days** of `D`, with `confidence ≠ none`.
- Store, coordinate-free:
  - `n` — the count of contributing historical daily values;
  - the **sorted list** of their `daily_lst_c` (this is what Type-7 percentiles are computed against — `METH-003`, no hidden default);
  - `median_lst_c`, `mean_lst_c`, `sd_lst_c`, and `median_minus_mean_c` (`METH-002` — both reference statistics plus their divergence);
  - `n_by_year` — the count per historical year (so the spread is auditable);
  - `median_valid_water_fraction` among the contributing days (context for interpretation).

**How it is computed:** Earth Engine returns one **per-day lake value** for every day 2003–2022 (§1, steps 1–5, area-weighted mean LST + accepted pixel count) — one pass over the archive, date-batched by half-year per stream (~160 bounded requests, like `AUDIT-013`). The 366 day-of-year baselines are then assembled **in Python** by grouping that per-day table with the ± 5-day wrap-around window — no separate Earth Engine query per day-of-year. The per-day table (date, stream, `daily_lst_c`, accepted pixel count) is itself a coordinate-free artefact and is retained so the baseline is fully reproducible offline.

The baseline is small: 366 × 4 streams × (a few scalars + a list of ≤ ~500 numbers). It is built once and, because the reference period 2003–2022 is fixed, never recomputed — only extended forward as monitoring days accrue (those do **not** enter the baseline).

## 3. The daily anomaly record

For a monitoring date + stream, combine §1 with the §2 baseline for that day-of-year:

| Field | Definition |
|---|---|
| `daily_lst_c`, `valid_water_fraction`, `confidence` | from §1 |
| `historical_n` | the baseline `n` |
| `reference_median_lst_c`, `reference_mean_lst_c`, `reference_sd_lst_c` | baseline `METH-002` statistics |
| `anomaly_vs_median_c` | `daily_lst_c − reference_median_lst_c` — **the headline anomaly** |
| `anomaly_vs_mean_c` | `daily_lst_c − reference_mean_lst_c` — shown alongside |
| `reference_median_minus_mean_c` | baseline diagnostic; large ⇒ that day-of-year's distribution is skewed |
| `historical_percentile` | Type-7 rank of `daily_lst_c` within the baseline sorted list — **only if `historical_n ≥ 10`**, else `null` |
| `percentile_confidence` | `full` if `historical_n ≥ 20`; `limited_historical_sample` if `10 ≤ historical_n < 20`; `insufficient_history` if `historical_n < 10` |
| `classification` | **the single thermal-status label**, from `historical_percentile` (`METH-004`) — *not* from the median or the mean: `< 10th` below normal · `10–90th` within normal range · `90–95th` warm · `95–99th` unusually warm · `≥ 99th` extreme warm observation. If `percentile_confidence = insufficient_history` → `historical context unavailable` (anomaly shown, no label). If `confidence = none` → `no valid observation`. |
| transparency fields | from §1 |

**Median vs mean in the application (`METH-002`):** there is **one** label per observation, and it comes from the percentile above. The two anomaly numbers are just that — numbers, not labels. The **daily view headline** is `anomaly_vs_median_c` plus the single percentile label; `anomaly_vs_mean_c` and `reference_median_minus_mean_c` live in a details panel / the download / the report. The median is the headline because the `PHASE-3` climatology confirmed the nighttime distributions are skewed (median ~0.6 °C, up to 2.6 °C above the mean on ~60 % of the year), so mean-based anomalies would read systematically warm at night.

The monitoring observation is never added to its own baseline. Streams are recorded separately and never combined (`METH-006`).

## 4. Monthly summary

Per stream, per calendar month, per the lake-wide unit, from the §3 daily records with `confidence` `low` or better and requiring **≥ 3** such days (`QA-002`, `METH-005`):

`monthly_mean_lst_c`, `monthly_mean_anomaly_vs_median_c`, `monthly_mean_anomaly_vs_mean_c`, `hottest_observation` (date + `daily_lst_c`), `max_anomaly_vs_median_c` (date + value), `warm_observation_count` (days with `historical_percentile ≥ 90` — and how many of the qualifying days had a percentile at all), `valid_day_count`, `calendar_day_count`, `missing_or_cloud_fraction` = 1 − valid_day_count ÷ calendar_day_count.

`< 3` qualifying days → `insufficient valid observations` (counts still shown). A month with no qualifying day in any stream → explicit missing state. No zero-fill, no interpolation (`QA-001`).

## 5. Output — coordinate-free

Four local artefacts, all coordinate-free (no coordinates, no per-pixel arrays, no raster bytes; the same recursive screen used by `AUDIT-011`/`AUDIT-012`/`AUDIT-013`):

0. `historical_daily_values` — the per-day lake value for every day 2003–2022, per stream (the raw material the baseline is grouped from).
1. `climatology_baseline` — §2, per stream × day-of-year.
2. `daily_anomaly_records` — §3, per stream × monitoring date (2023 → present).
3. `monthly_summaries` — §4, per stream × month.

Each carries: the approved decision identifiers and pinned diagnostic hashes it depends on, the geometry identity hash, the exact method parameters (window ± 5, median, Type-7, the label thresholds, the confidence and monthly cut-offs), and a validation-pass block. Malformed output fails closed.

## 5a. Verified geometry — hash-pinned local cache

The approved geometry (`SPACE-001` / `AUDIT-003`) has a fixed, recorded identity: raw SHA-256 `5d5f9c8e…`, canonical SHA-256 `394a9296…`, 427,942 canonical bytes, 11,012 coordinate tuples. The anomaly engine verifies the geometry **once** and then caches `(geometry_json, source_record)` locally under `local_run_state/phase3/` (git-ignored). Later runs load the cache only if its recorded geometry identity matches the `AUDIT-003` pins and the geometry still hashes to the cached value; otherwise they re-verify or fail closed.

The first verification is:

1. **Full `AUDIT-003` provenance chain** via the byte-pinned `verify_wise_huaih049.py` (CDR metadata + GML + WISE geometry service + all cross-checks).
2. **Geometry-only fallback (user-approved 2026-09), used only if step 1 fails because the EEA CDR-metadata endpoint is unreachable** (`sdi.eea.europa.eu/datashare/…/CDR_metadata.csv` has been 503 since ~2026-09-02, while the geometry service and GML endpoint are up). The engine re-fetches the polygon from the WISE geometry service and re-checks it with the byte-pinned `analyze_wise_huaih049_source_representations.py` parser against the `AUDIT-003` **expected raw + canonical SHA-256, canonical byte count, tuple count, and Polygon validity** — skipping only the CDR-metadata and GML provenance cross-checks, which *established* rather than *confirm* the pinned identity. Any mismatch fails closed. On the first run this fired and the re-fetched polygon matched the `AUDIT-003` raw and canonical hashes byte-for-byte; the cache now carries `verification_mode: geometry_only_pinned_hash_fallback_cdr_endpoint_unreachable`.

This removes a repeated dependency on the sometimes-unavailable EEA provenance servers from a production path without weakening the geometry-identity guarantee — the pinned SHA-256 *is* the approved identity.

## 6. Bounded, reproducible execution

Same guardrails as the diagnostics: a coordinate-free runner with an offline `--self-test`, byte-pinned dependencies, and — for authenticated Earth Engine work — the `480.000`-second per-request cutoff, one attempt / no automatic retry, the 165-minute session ceiling, and the Windows Job Object process supervisor. The climatology build is the heaviest step (20 years × 366 day-of-year windows × 4 streams of daily reductions); it is date-batched like `AUDIT-012` and, because the baseline is fixed, is a one-time run whose output is checkpointed.

## 7. Offline validation (`--self-test`, before any authenticated run)

The Type-7 formula `h = (n−1)p` with linear interpolation against hand-computed fixtures (including `n < 10` → no percentile, `n = 0` → none); the ± 5-day day-of-year windowing including the 29 Feb fold and the year-boundary wrap; the classification-label thresholds at every boundary; the confidence-tier and monthly-minimum logic; the "monitoring observation excluded from its own baseline" rule; the exact output schema and its coordinate-free screen; fail-closed behaviour on a malformed baseline, a short month, and a duplicate source image.

## 8. What Phase 3 does **not** do

- No interface, map rendering, or user interaction (Phase 4).
- No validation study or acceptance decision (Phase 5 / `VAL-001`).
- No Earth Engine asset, export, task, precomputation table, refresh workflow, or deployment (`ARCH-001`).
- No Landsat or ERA5-Land processing (`DATA-005` / `DATA-006`).
- No change to any completed audit, prototype, or approved decision.
