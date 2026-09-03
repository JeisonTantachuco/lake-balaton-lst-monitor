# Phase 3 — climatology baseline report

- **Date:** 2026-09-03
- **Status:** the 2003–2022 climatology baseline is built. Supervised run exit 0, `ANOMALY_ENGINE_SUPERVISOR_COMPLETE`, `terminal_revalidated: true`, 1,464 rows (4 streams × 366 day-of-year), `baseline_rows_sha256 1ff9ca8d…`. Artefacts: `local_run_state/phase3/climatology_baseline.json`, `local_run_state/phase3/historical_daily_values.json` (git-ignored, coordinate-free). Log: `$HOME/phase3_climatology_build.log`.
- **Method:** `SPACE-001` lake-wide 0 m geometry (verified via the geometry-only hash-pinned fallback — the EEA CDR endpoint is still 503), `QA-002` candidate-C acceptance rule, `METH-001` ± 5-day day-of-year window, `METH-002` both median and mean, all four streams (`METH-006`). See `docs/PHASE_3_ANOMALY_ENGINE_SPECIFICATION.md`.
- **First run was rejected:** the initial build only fetched January + July–December (a month-range typo, `((1,1),(7,12))` instead of `((1,6),(7,12))`); February–June came back empty. Caught on inspection, then permanently guarded by a new `validate_baseline` check that fails closed when > 3 day-of-year per stream have `n = 0` or > 12 have `n < 10`. The corrected run passes that check.

---

## 1. Historical data volume

**19,508 daily lake-average temperatures** over 2003–2022, from the ~29,220 possible stream-days:

| Stream | Daily values | Share of days | °C range |
|---|---|---|---|
| Terra day | 5,032 | 69 % | −16.8 … 30.0 |
| Aqua day | 5,071 | 69 % | −14.5 … 33.7 |
| Terra night | 4,595 | 63 % | −23.3 … 27.6 |
| Aqua night | 4,810 | 66 % | −26.8 … 27.7 |

The lake is ~696 MODIS pixels; each daily value is the area-weighted mean of the accepted (candidate-C) pixels that day.

## 2. Baseline coverage — the sample behind every percentile

| Stream | `n` min | `n` median | `n` max | day-of-year with `n < 10` | with `n < 20` |
|---|---|---|---|---|---|
| Terra day | 102 | 160 | 186 | 0 | 0 |
| Aqua day | 101 | 158 | 194 | 0 | 0 |
| Terra night | 117 | 138 | 162 | 0 | 0 |
| Aqua night | 122 | 145 | 168 | 0 | 0 |

**Every one of the 1,464 day-of-year × stream cells has `n ≥ 100`.** The `METH-003` sample gate (`n ≥ 20` for a full-confidence percentile) never binds on the lake-wide product — exactly as `AUDIT-013` predicted. Every percentile will be computed at full confidence.

## 3. Median vs mean — the skew signal (`METH-002`)

| Stream | median \|median − mean\| | mean \|median − mean\| | max | day-of-year with \|diff\| > 0.5 °C |
|---|---|---|---|---|
| Terra day | 0.22 °C | 0.28 °C | 1.16 °C | 58 / 366 |
| Aqua day | 0.16 °C | 0.20 °C | 0.90 °C | 18 / 366 |
| **Terra night** | **0.59 °C** | 0.64 °C | **2.16 °C** | **209 / 366** |
| **Aqua night** | **0.62 °C** | 0.71 °C | **2.60 °C** | **222 / 366** |

Daytime: median and mean are close (near-symmetric distributions). **Nighttime: they diverge on ~60 % of the year**, and by up to 2.6 °C. The night distributions have a long **cold tail** — clear, calm nights radiate heat away and the water surface gets much colder than a typical night, dragging the mean down while the median stays near the typical value.

Worst divergence is **early-to-mid February nights** (day-of-year 38–43):

| | `n` | median | mean | SD |
|---|---|---|---|---|
| Terra night, ~Feb 8 | 132 | −2.9 °C | −5.0 °C | 5.6 °C |
| Aqua night, ~Feb 11 | 151 | −2.5 °C | −5.1 °C | 6.1 °C |

**This is why reporting both matters.** On a normal clear February night the water is ~−2.7 °C. Measured against the **median** that is "within normal range"; measured against the **mean** (−5 °C) it would look "+2 °C warm" — a false alarm on every calm winter night. The median is the correct headline; the mean and `median_minus_mean_c` are kept alongside so the skew is visible.

## 4. Seasonal reference temperatures (median °C, mid-month)

| Stream | Jan 15 | Apr 15 | Jul 15 | Oct 15 |
|---|---|---|---|---|
| Terra day (morning) | −0.1 | 11.4 | 23.2 | 13.0 |
| Aqua day (afternoon) | 0.2 | 12.2 | 24.1 | 13.7 |
| Terra night | −2.6 | 8.8 | 19.9 | 10.0 |
| Aqua night | −3.4 | 8.0 | 19.2 | 9.9 |

Physically consistent: the Aqua afternoon pass is ~0.5–1 °C warmer than the Terra morning pass (afternoon is closer to the daily maximum); nights run ~3–5 °C cooler than days; the seasonal cycle spans ~24 °C.

## 5. What is next

The baseline is ready. The remaining Phase 3 pieces:

1. Wire the **daily anomaly record** mode to Earth Engine — compute the accepted lake value for each monitoring date (2023 → present) and combine it with the baseline (`anomaly_vs_median_c`, `anomaly_vs_mean_c`, Type-7 percentile, label, `QA-002` confidence flag).
2. The **monthly summary** mode (Python only — reads the daily records).
3. `ARCH-001` — how the baseline and the monitoring outputs are stored, refreshed, and served, and the `AUDIT-003` provenance re-verification once the EEA endpoint recovers.

The Phase 3 method and the daily/monthly Python logic are already implemented and self-tested; only the monitoring-date Earth Engine fetch and a short run remain.
