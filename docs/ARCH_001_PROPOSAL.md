# ARCH-001 proposal — precomputation, storage, refresh, and deployment

- **Date:** 2026-09-03
- **Author:** Main Codex coordinator, for the user
- **Decision addressed:** `ARCH-001` — "Define the precomputation asset/table schema, refresh cadence, ownership, storage/export destination, and GEE deployment strategy."
- **Status:** **approved (2026-09-03).** The user approved the storage/refresh shape and the §4 geometry-asset supersession ("yes, upload to earth engine the lake outline"). Recorded in `DECISIONS.md`.
- **Context:** Phase 3 is built. The four outputs already exist as local coordinate-free JSON under `local_run_state/phase3/` — the 2003–2022 climatology baseline, the historical daily values, the 2023 → 2026-09 daily anomaly records, and the monthly summaries. This decision is only about how they are stored, kept current, and served to the app.

---

## 1. The principle (approved)

- **The past is immutable.** The 2003–2022 baseline is a fixed reference period; it is computed once and **never** recomputed. A daily anomaly record, once written, does not change.
- **Only new days are added.** Each new calendar month brings new MODIS observations. Bringing them in is an **append** — run the daily step, which recomputes nothing old, only the new dates, against the same fixed baseline.
- **Refresh is a manual, documented step**, not an automated pipeline. For the internship the record is snapshotted "current as of submission"; the procedure is for whoever maintains the app afterwards.

## 2. Storage — Earth Engine assets, in the user's project

The outputs are tiny (~4 MB total). They are published as **Earth Engine `FeatureCollection` tables** under `projects/ee-jtantaroman/assets/balaton_anomaly/`:

| Asset | Rows | One row = | Key fields |
|---|---|---|---|
| `climatology_baseline` | 1,464 | stream × day-of-year | `n`, `median_lst_c`, `mean_lst_c`, `sd_lst_c`, `median_minus_mean_c`, `sorted_daily_lst_c` (list), `n_by_year` (list) |
| `daily_anomaly_records` | 3,608 (grows) | stream × date | `daily_lst_c`, `valid_water_fraction`, `confidence`, `anomaly_vs_median_c`, `anomaly_vs_mean_c`, `historical_percentile`, `percentile_confidence`, `classification` |
| `monthly_summaries` | 176 (grows) | stream × month | monthly mean, mean anomaly (both), hottest observation, warm-day count, valid-day count, missing/cloud fraction |

Each asset carries, as feature or asset properties, the method-parameter block and the SHA-256 of the source JSON it was built from, so the app and any reviewer can confirm which run produced it. The three data tables are **non-spatial** — their properties are dates, temperatures, and counts, no lat/lon. Earth Engine table assets nonetheless require a geometry on every feature, so each data-table feature carries the **null-island sentinel point `[0, 0]`** — a recognised "no location" marker, *not* a source coordinate. Only `lake_boundary` carries a real geometry.

Earth Engine table-asset properties must be **scalars — no lists**. So the `climatology_baseline` asset stores, per row, the scalar summary statistics plus a fixed set of **percentile break-points as separate scalar columns** — `pctl_p01_c`, `pctl_p05_c`, `pctl_p10_c`, `pctl_p25_c`, `pctl_p50_c`, `pctl_p75_c`, `pctl_p90_c`, `pctl_p95_c`, `pctl_p99_c` (the Type-7 quantile at those percentiles, covering the `METH-004` label boundaries 10 / 90 / 95 / 99 plus context). The full sorted list and `n_by_year` stay only in the local `climatology_baseline.json` artefact (the reproducible source of truth). These nine break-points are all the app needs to place a new "today" observation on the historical distribution and assign its label.

The build tool gains an `--export-assets` mode: it validates the local JSON artefacts, then writes the three tables (overwriting the daily and monthly assets, leaving the baseline asset untouched once created). Table upload is a bounded Earth Engine `export` — the first `export` this project has used, authorized here.

## 3. The app reads the assets directly

The application never recomputes history. It loads the three `FeatureCollection`s and filters by date / stream / month. A daily-view lookup is one `filter` on `daily_anomaly_records`; a monthly view is one `filter` on `monthly_summaries`; the "normal" band shown on a chart comes from `climatology_baseline`. This is fast and cheap, and matches the approved performance principle (`PROJECT_CONTEXT.md` "Performance strategy").

Computing the value for **today** (a date newer than the last export) is the only live computation the app might do — one `candidate-C` reduction over the lake for one image, identical to the engine's per-day step.

## 4. The lake geometry — one hash-pinned Earth Engine asset (needs explicit approval)

`AUDIT-002`/`003`/`004`/`006` require the lake polygon to stay **transient** — never persisted in the repository or an Earth Engine asset. That rule was right for the diagnostic phase (keep source coordinates out of version control and out of shared assets). **A deployed monitoring app cannot run without its region of interest**: it needs the polygon to draw the lake on the map and to compute the value for new dates.

**Proposal:** create **one** Earth Engine asset, `projects/ee-jtantaroman/assets/balaton_anomaly/lake_boundary`, holding the verified `AUDIT-003` WISE `HUAIH049` (2022) polygon, with the asset properties recording its pinned raw SHA-256 `5d5f9c8e…`, canonical SHA-256 `394a9296…`, and 11,012-tuple structure. This is a **narrow, deliberate supersession** of the transient-only rule, **for the production system only**:

- The coordinate-free discipline **stays** for every diagnostic runner, every log, every checkpoint, and the git repository — nothing there changes.
- The asset is the exact approved geometry, hash-verified before upload; it is not a new or modified boundary (`SPACE-001` is unchanged).
- It is created once and never modified.

Without this, the app would have to re-fetch the polygon from the (flaky) WISE servers on every load, or embed 11,012 coordinates as a literal in the app code — both worse.

## 5. Refresh procedure (manual, monthly)

Documented for the maintainer. Once a month (or whenever new data is wanted):

1. `python tools/run_anomaly_engine_ee.py --project ee-jtantaroman --daily-records` — recomputes the daily records and monthly summaries through today, against the unchanged baseline.
2. `python tools/run_anomaly_engine_ee.py --project ee-jtantaroman --export-assets` — re-exports the `daily_anomaly_records` and `monthly_summaries` tables (the `climatology_baseline` and `lake_boundary` assets are left alone).
3. The app picks up the new data automatically on its next load.

No recomputation of history, no baseline change, no code change. MODIS has ~1–2 day latency, so "current" means through roughly two days ago.

## 6. Deployment

A **published Google Earth Engine App** from the Code Editor (`Apps → Publish`), the same hosting the reference Li et al. (2024) Balaton app uses — free, no server, a public URL. The app is a new, separate application (`SCOPE-003` MVP), not a modification of the existing one.

The app source lives in the repository as reference JavaScript (like the prototype's), even though it is published through the Code Editor.

## 7. The `AUDIT-003` provenance re-verification

The engine currently verifies the geometry through the hash-pinned fallback because the EEA CDR-metadata endpoint has been down since ~2026-09-02. **When that endpoint recovers, run the full `verify_wise_huaih049.py` once**, confirm it still matches the pins, and record the confirmation in `DECISIONS.md`. The `lake_boundary` asset does not need rebuilding — it is already the hash-verified polygon — but the full provenance chain should be re-run once for the record before the internship is submitted.

## 8. What this does **not** do

- No automated / scheduled pipeline, no server, no database.
- No new science, no basins (`SPACE-001`), no Landsat / ERA5-Land (`DATA-005/006`).
- No change to any completed audit, the prototype, or the Phase 3 method.
- The only new Earth Engine capabilities authorized are: four assets under one folder, and the `export` operations that write them.

## 9. If approved

1. Record `ARCH-001` as approved in `DECISIONS.md`, including the §4 geometry-asset supersession.
2. Add the `--export-assets` mode to `tools/run_anomaly_engine_ee.py` (validate local artefacts → write the four assets), with an offline `--self-test` for the schema mapping.
3. Create the `lake_boundary` and `climatology_baseline` assets once; export `daily_anomaly_records` and `monthly_summaries`.
4. Proceed to Phase 4 (the app), which reads these assets.
