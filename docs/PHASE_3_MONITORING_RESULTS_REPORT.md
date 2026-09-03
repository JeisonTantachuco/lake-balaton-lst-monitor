# Phase 3 — monitoring anomaly results (2023 → 2026-09)

- **Date:** 2026-09-03
- **Status:** the daily anomaly records and the monthly summaries are built. Supervised run exit 0, `ANOMALY_ENGINE_SUPERVISOR_COMPLETE`, `terminal_revalidated: true`. Artefacts (git-ignored, coordinate-free): `local_run_state/phase3/daily_anomaly_records.json` (`records_sha256 dfbd4f13…`), `local_run_state/phase3/monthly_summaries.json` (`rows_sha256 8e69b45d…`). Log: `$HOME/phase3_daily_records.log`.
- **What this is:** for every day from 2023-01-01 to 2026-09-03, per stream, the accepted lake-average temperature compared to the 2003–2022 climatology baseline (`docs/PHASE_3_CLIMATOLOGY_REPORT.md`) — anomaly in °C, Type-7 percentile, thermal-status label (`METH-004`), and the `QA-002` `ok`/`low` coverage-confidence flag.
- **Boundary:** this is the engine output, not a validated scientific result. It selects nothing and adopts nothing; `VAL-001` still has to check it.

---

## 1. Volume

| | Count |
|---|---|
| Daily anomaly records | 3,608 (observed days only) |
| — Terra day / Aqua day / Terra night / Aqua night | 951 / 953 / 837 / 867 |
| Monthly summary rows | 176 (every stream-month has ≥ 3 valid days — 0 withheld) |
| Days at confidence `ok` (`f ≥ 0.15`) | 2,275 (63 %) |
| Days at confidence `low` (`0 < f < 0.15`) | 1,333 (37 %) |

## 2. The coverage-confidence flag is doing real work

The eight most extreme daily "anomalies" — +7.6 to +16.1 °C — are **all `low` confidence**, built from **1 to 5 pixels** on near-fully-clouded days:

| Date | Stream | "lake" value | anomaly | `f` | pixels |
|---|---|---|---|---|---|
| 2023-10-07 | Aqua day | 30.9 °C | +16.1 | 0.00 | 3 |
| 2025-01-09 | Terra night | 5.3 °C | +8.2 | 0.00 | 1 |
| 2024-07-16 | Terra night | 27.8 °C | +7.7 | 0.00 | 1 |

On a mostly-clouded day the handful of pixels that survive are often near the (warmer) shore or over a warm patch, so the "lake average" is wildly unrepresentative. **Without the `low` flag, a "warmest days" list would be dominated by these cloud artefacts.** This confirms the `QA-002` confidence tier is essential, and it makes low-coverage handling a `VAL-001` priority — the app should down-weight or hide `low`-confidence days.

The most extreme **`ok`-confidence** days are believable: 2026-06-29 Aqua day at 31.9 °C (689 pixels, 99 % coverage); early-March 2024 at +7 °C (well observed) — March 2024 was the warmest March on record in Europe.

## 3. Classification of the monitoring period

Among the 2,275 well-observed (`ok`) days, against the 2003–2022 baseline:

| Label | Share |
|---|---|
| within normal range | 78.8 % |
| warm (90–95th pct) | 8.6 % |
| unusually warm (95–99th) | 6.4 % |
| extreme warm observation (≥ 99th) | 5.0 % |
| below normal (< 10th) | 1.2 % |

The monitoring window is **strongly warm-skewed** — ~20 % of well-observed days sit above the 90th historical percentile, against ~10 % by definition in the baseline, and only 1.2 % below the 10th. Consistent with 2023–2024 being the warmest years in the instrumental record.

## 4. Yearly mean anomaly vs the median (°C)

| Year | Terra day | Aqua day | Terra night | Aqua night |
|---|---|---|---|---|
| 2023 | +0.41 | +0.89 | +0.93 | +0.89 |
| **2024** | **+0.93** | **+1.41** | **+1.15** | +0.88 |
| 2025 | +0.01 | +0.79 | +0.20 | −0.11 |
| 2026 (to Sep) | +0.43 | +1.79 | +0.83 | −0.21 |

**2024 is the warmest year in every stream.** 2023 is clearly warm. 2025 is close to the 2003–2022 normal. The Aqua afternoon stream shows the strongest warming signal.

## 5. Standout warm months

| Month | Stream | monthly mean | anomaly vs median | warm days |
|---|---|---|---|---|
| **2024-02** | Terra night | 2.5 °C | **+5.13** | 14 / 17 |
| 2023-10 | Aqua day | 17.1 °C | +3.76 | 10 / 20 |
| 2024-03 | Terra night | 5.5 °C | +3.68 | 11 / 20 |
| 2026-08 | Aqua day | 27.6 °C | +3.46 | 16 / 26 |
| 2023-09 | Aqua day | 22.7 °C | +3.18 | 13 / 23 |

**February 2024** stands out — Central Europe had essentially no winter that month, and the lake's night-time surface ran ~5 °C above its 2003–2022 median.

**Summer 2024** (Jul–Aug): every stream +1.2 to +2.5 °C, with Aqua day at +2.0 (July) and +2.5 (August) and 12–13 warm days each month.

## 6. What this tells the project

- The engine produces coherent, physically sensible output end to end.
- The `low`-confidence flag is not optional — it separates real anomalies from partial-coverage artefacts, exactly as `QA-002` intended.
- `VAL-001` should focus on: (a) the `low`-coverage days (exclude / flag), (b) a cross-stream consistency check (do Terra-day and Aqua-day agree on the big monthly anomalies? — they broadly do), and (c) comparison of the 2024 anomalies against the published European temperature record.
- Next: `ARCH-001` (how the baseline + records are stored, refreshed monthly, and served) and Phase 4 (the app).
