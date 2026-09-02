# AUDIT-013 — historical observation-availability probe report

- **Date:** 2026-09-02
- **Status:** complete. The supervised run finished with exit 0; the supervisor independently re-validated the terminal object (`AUDIT013_SUPERVISOR_COMPLETE`, `terminal_revalidated: true`, 192 cells, `cells_sha256 97cdf82e…`). Log: `$HOME/audit013_run.log`. Pins: runner `514242b69646c0e981cba59a00821de3705fb0388ea08650b4fb14665de45e75`, supervisor `historical_observation_availability_windows_supervisor_v1`.
- **Purpose:** measure the real historical sample behind a percentile, to fix `METH-001` (seasonal window width) and `METH-003` (minimum-sample thresholds) from data. See `docs/HISTORICAL_OBSERVATION_AVAILABILITY_SPECIFICATION.md` and `DECISIONS.md` AUDIT-013.
- **Scope:** counts only — no temperature, no coordinate, no raster byte was read; no anomaly, climatology, percentile, or classification was computed; no `METH-*` value is selected. Approved lake-wide WISE `HUAIH049` (2022) geometry at 0 m; approved `QA-002` candidate-C acceptance rule; historical reference period 2003–2022 (20 years); probe dates the 15th of each month; window half-widths 5, 7, 10, 15 days.

---

## 1. Headline result — the historical sample is *not* thin

**At a ± 5-day window, every stream and every month has essentially all 20 historical years covered**, with a comfortable pool of daily observations behind every percentile.

| Metric (± 5 days) | Range across the 48 stream × month combinations |
|---|---|
| Years (of 20) with at least one accepted observation within ± 5 days | **20 in 47 of 48 combinations; 19 in one** (Terra-night, mid-October) |
| Total accepted daily observations across the 20 years | **110 – 195** |
| Lowest observed | Aqua-day mid-December: 110 · Terra-day mid-December: 114 · Terra-night mid-September: 124 |

Every one of the 192 cells (4 streams × 12 months × 4 window widths) clears the proposed `METH-003` minimum-sample thresholds (10 / 20) many times over. The concern that cloud cover would leave single-digit historical samples at night **does not hold**: clouds thin the *spatial coverage on a given day*, not the *number of days that produce an observation*.

Per-year counts are modest but positive — a typical year contributes ~6 daily observations to a ± 5-day window; the leanest years contribute 1–2 (one Terra-night October year contributed 0). The pool is spread across years, not carried by a handful.

## 2. Where the data actually thins — spatial coverage per night

The split is between day and night, not between seasons of sample count:

| Median accepted pixels on a positive day (lake ≈ 590 1 km pixels), ± 15-day window | Jan | Apr | Jul | Aug | Oct |
|---|---|---|---|---|---|
| Terra-day | 340 | 588 | 638 | 617 | 600 |
| Aqua-day | 354 | 512 | 598 | 580 | 593 |
| Terra-night | 137 | 85 | **41** | **33** | 61 |
| Aqua-night | 127 | 98 | **48** | **43** | 61 |

- **Daytime** typically sees 50–100 % of the lake — rich, near-complete coverage, best in summer.
- **Nighttime** sees far less: a median of ~130 pixels (≈ 22 %) on winter nights, dropping to **~35–50 pixels (≈ 6–9 %) on summer nights**. Some individual nights produce a lake "average" from a single pixel.

So a summer-night daily value is a real observation with plenty of historical company for a percentile, but it is a spatial sample of a small — and possibly cloud-selected — part of the lake.

## 3. What this fixes

### METH-001 — keep ± 5 days, all four streams

The `METH-001` proposal kept ± 5 days as the base and would have widened the nighttime window only if the data forced it. **It does not.** ± 5 days already gives 20/20 historical years (19/20 in one cell) and 110–195 daily observations for every stream and month. Widening to ± 7/10/15 adds pool size but is unnecessary and would blur the seasonal match. Recommendation: **± 5 days for all four streams**, matching the inherited candidate and the standard 11-day climatology window. A smoothed seasonal climatology is likewise unnecessary for the MVP — the raw window has ample data.

### METH-003 — thresholds stay as a guardrail, but they will rarely bind

With real pools of 110–195 at ± 5 days, essentially every percentile will be computed in the "full confidence" (`n ≥ 20`) regime. The proposed `n ≥ 20` full / `10 ≤ n < 20` flagged / `n < 10` anomaly-only structure is retained as cheap insurance against unusual gaps (a stream outage, a specific basin later), but it is not the operative constraint on this lake. The Type-7 estimator and the "monitoring observation never in its own history" rule are unchanged.

### The real quality signal is per-day coverage — already handled by QA-002

What the probe shows is that the reliability concern for this product is not "is there enough history" but "how much of the lake did we see on this particular night". That is exactly what the approved `QA-002` confidence tier (`ok` / `low` / `none`, from the valid-water fraction `f`) captures: a summer-night value from 35 pixels (`f ≈ 0.06`) is flagged `low`. No new mechanism is needed.

## 4. Caveat to carry into the report and `VAL-001`

Summer nighttime lake-surface-temperature values represent only ~6–9 % of the lake and may be biased toward the portion that stays cloud-free and passes QA (clear-sky bias, partial-coverage bias). This is most acute for the two nighttime streams in July–September. It does not undermine the anomaly comparison — the same bias is present in the historical baseline and largely cancels — but it must be stated plainly, and `VAL-001` should check for a near-shore or partial-coverage artifact in the summer nighttime product.

## 5. Boundary

This probe selects no `METH-*` value and authorizes no Phase 3 implementation. It supplies the observation counts; the `METH-001` … `METH-006` decision is finalised in `DECISIONS.md` on the basis of them.
