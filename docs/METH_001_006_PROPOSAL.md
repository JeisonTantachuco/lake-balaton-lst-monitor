# METH-001 … METH-006 proposal — the anomaly / climatology method

- **Date:** 2026-09-02
- **Author:** Main Codex coordinator, for the user
- **Decisions addressed:** `METH-001` (seasonal window), `METH-002` (reference statistic), `METH-003` (percentile estimator + minimum sample), `METH-004` (classification thresholds + labels), `METH-005` (monthly aggregation with missing streams/days), `METH-006` (standardized multi-sensor indicator). All from `PROJECT_CONTEXT.md` open decisions 1–4, 7, 8.
- **Status:** **APPROVED (2026-09).** `METH-001` … `METH-006` are recorded as approved in `DECISIONS.md`. The §4 sample-sufficiency check was run (`docs/HISTORICAL_OBSERVATION_AVAILABILITY_REPORT.md`, `AUDIT-013`): it confirmed ± 5 days for all four streams (no nighttime widening) and that the `METH-003` minimum-sample thresholds essentially never bind on the lake-wide product. Approval provenance: the user reviewed the recommendations and the `AUDIT-013` result, asked clarifying questions about summer-night coverage and basin structure, and confirmed "ok, everything looks good" / "ok, I understand let's proceed with the phases".
- **Evidence base:** `AUDIT-011` and `AUDIT-012` (nighttime coverage is structurally sparse); `QA-001` (approved — no interpolation, explicit missing state); `QA-002` (approved — accepted-pixel rule = candidate C, day and night); `SPACE-001` (approved — lake-wide geometry, 0 m shoreline, basins deferred); `TERM-001` (approved — terminology); the reference work Li, Somogyi & Tóth (2024); standard climatology / marine-heatwave practice (Hobday et al. 2016).

---

## 1. What these six decisions are

They are **not six competing methods to choose between.** They are six separate parts of **one** calculation, and all six must be settled. The calculation is:

> For each observation from the monitoring period (2023 → present): find the matching history in **2003–2022** — same **spatial unit**, same **time of year**, same **satellite**, same **day/night stream** — and express how unusual the observation is, as an anomaly in °C and as a historical percentile.

The six decisions fill in the blanks:

| Decision | Fills in |
|---|---|
| METH-001 | "same time of year" — how wide a window around the calendar date |
| METH-002 | the single "normal" value the observation is compared against (for the °C anomaly) |
| METH-003 | how the percentile is computed, and the minimum amount of history required before a percentile is trustworthy |
| METH-004 | where the "unusually warm" line sits, and the exact labels |
| METH-005 | how a monthly number is built when days or a satellite are missing |
| METH-006 | whether the four streams are ever combined into one number |

Unlike `QA-002`, most of these do **not** need a satellite experiment — they are choices guided by the reference paper, standard practice, and what the data can support. The one place the data genuinely constrains the answer is the **historical sample size at night** (§2.2), and §4 proposes a small check for it.

---

## 2. Two structural points first (raised in review)

### 2.1 Spatial unit — whole lake only for the MVP; basins are not worth it here

`SPACE-001` already approved the lake-wide geometry with basins deferred. The review raised a concrete reason this is the right call for the *method*, not just the geometry:

- MODIS pixels are ~1 km. Lake Balaton is long and narrow (a few km wide in places, ~1 km at the Tihany strait). A four-basin split puts a large fraction of pixels **on or near a basin border**, where assigning a pixel to one basin is arbitrary and small shifts in the boundary move observations between basins.
- Under the approved candidate-C rule, a single nighttime date often has only a handful of valid water pixels **for the whole lake**. Splitting that four ways leaves small basins with **zero or one** valid pixel on most nights — not enough for a stable daily value, let alone a percentile.
- Splitting the history four ways makes the sample-size problem in §2.2 roughly four times worse.

**Recommendation:** all `METH-*` calculations operate on the **whole-lake unit only**. Basin-level output is a documented optional extension, possible only if (a) an authoritative basin polygon set is obtained and (b) a sample-sufficiency check (§4) shows the basins can support it. This does not remove "basin comparison" from the project's ambitions — it defers it honestly rather than shipping unreliable basin numbers.

### 2.2 How much history a single observation actually has

For a given calendar date and stream, the matched history is: **that day-of-year ± W days, across 2003–2022 (20 years)**.

- With **W = 5**: `(2 × 5 + 1) × 20 = 220` *potential* historical observations.
- But most are removed by cloud cover and by the QA-002 acceptance rule. `AUDIT-011` and `AUDIT-012` showed that in the four sampled 2024 windows, **many nighttime dates have zero valid water pixels at all**, and nighttime daily coverage averages only ~10 % of the lake even when it is non-zero.

So the *real* number of usable historical observations behind a nighttime percentile could be a small fraction of 220 — possibly single digits on the worst calendar dates. Daytime will be much better (more cloud-free passes, more valid pixels), but this has not been measured either.

This is the central constraint on `METH-001` (window width) and `METH-003` (minimum sample). The proposal below handles it in three layers: start from the standard window, **measure** the real sample counts (§4), and **widen the window or withhold the percentile** only where the data forces it.

> **`AUDIT-013` result (2026-09):** the fear above is only half right. At ± 5 days, every stream × month has **20/20 historical years covered** (one cell 19/20) with **110–195 total daily observations** behind every percentile — the number of *days* with an observation is not thin. What *is* thin is the **spatial coverage on a summer night**: a median of ~35–50 accepted pixels (≈ 6–9 % of the lake), versus ~130 on a winter night and 300–640 by day. So ± 5 days holds for all streams, `METH-003`'s minimum rarely binds, and the real reliability signal is the per-day coverage — already carried by the approved `QA-002` confidence tier. Full detail: `docs/HISTORICAL_OBSERVATION_AVAILABILITY_REPORT.md`.

---

## 3. Recommendations

### METH-001 — Historical seasonal window

- **Base rule:** a **day-of-year window of ± 5 calendar days** (an 11-day window), matched across all 20 historical years, per stream. This matches the inherited candidate and standard marine-climatology practice (Hobday et al. use an 11-day window).
- **Data-driven exception:** if the §4 sufficiency check shows a stream cannot reach the `METH-003` minimum sample on a material share of monitoring dates with ± 5 days, widen that stream's window to **± 7**, then **± 10**, then **± 15**, choosing the smallest width that clears the minimum on ≥ 90 % of monitoring dates. Expect this to bite for the nighttime streams and not for daytime.
- 29 February is merged with 28 February for windowing (no separate leap-day climatology).
- **Not chosen for the MVP:** a smoothed harmonic/LOESS seasonal climatology. It uses all data more efficiently and removes the window-width question, but it is more complex, harder to explain in the report, and harder to attach an empirical percentile to. Recorded as a documented future improvement.

### METH-002 — Historical reference statistic *(approved: report both)*

- **Compute and report both** the historical **median** and the historical **mean** (per date, stream, whole-lake unit), plus the standard deviation. The daily record carries `anomaly_vs_median_c` and `anomaly_vs_mean_c`.
- **The median-based anomaly is the headline** number. Rationale: LST samples are right-skewed and carry occasional bad values (thin cloud, mixed pixels, retrieval error); with the small summer-night samples a single outlier distorts the mean, and the median is robust to that; it is also the standard choice in modern climate-anomaly and marine-heatwave work. The mean-based anomaly is shown alongside so any divergence is visible.
- The climatology baseline records **`median_minus_mean_c`** per stream × day-of-year. Where it is large, that day-of-year's historical distribution is skewed — useful diagnostic information, and the divergence is surfaced rather than hidden by a single choice.
- `METH-002` only affects the °C-anomaly number. The "unusually warm" judgement uses the full empirical distribution, not the mean or median (`METH-003` / `METH-004`).

### METH-003 — Percentile estimator and minimum sample

- **Estimator:** the **Type 7** quantile (Hyndman–Fan definition 7, linear interpolation) — already used in `AUDIT-010` and `AUDIT-012`, the NumPy/R default, and well documented. The observation's percentile is its rank within the matched historical sample by the same Type-7 convention.
- **Minimum sample (`n` = count of valid historical observations in the matched window, same stream, whole-lake unit):**

  | `n` | What is reported |
  |---|---|
  | `n ≥ 20` | Full result: °C anomaly **and** historical percentile **and** classification label. |
  | `10 ≤ n < 20` | °C anomaly and percentile and label, all carrying a **"limited historical sample"** flag. |
  | `n < 10` | °C anomaly only (observation − median), with **"insufficient history for a percentile"** — no percentile, no warm/normal label. |
  | `n = 0` | No historical context; observation shown with its value and coverage only. |

- Rationale: a 90th/95th percentile estimated from fewer than ~10–20 points is not meaningful; making that explicit (rather than showing a false-precision number) is consistent with `QA-001`'s honesty principle. The exact cut-offs (10 / 20) are candidates for adjustment after §4.
- The **monitoring observation itself is never added to its own historical sample.**

### METH-004 — Classification thresholds and labels

- Percentile-based, computed against the matched historical distribution, applied only when `METH-003` reports a percentile:

  | Historical percentile of the observation | Label |
  |---|---|
  | < 10th | `below normal` |
  | 10th – 90th | `within normal range` |
  | 90th – 95th | `warm` |
  | 95th – 99th | `unusually warm` |
  | ≥ 99th | `extreme warm observation` |

- Wording follows `TERM-001`: no use of "heatwave" or event language; these are single-observation descriptors.
- The cold side (`below normal`) is included for completeness of the anomaly picture but is not elaborated — the product's focus is warm extremes.
- When `METH-003` gives `n < 10`, the label field reads `historical context unavailable` and only the °C anomaly is shown.
- The 90th/95th cut-offs match the inherited candidate; if the supervisor or later validation prefers a single "unusually warm ≥ 95th" scheme, the table collapses trivially.

### METH-005 — Monthly aggregation with missing streams / days

- Monthly summaries are **always stream-specific** — Terra-day, Aqua-day, Terra-night, Aqua-night are never merged or averaged together (core project principle; see `METH-006`).
- Per stream, per month, per the whole-lake unit, computed **only from daily observations that passed `QA-002`** (confidence tier `low` or better) and requiring **≥ 3** such days (the `QA-002` monthly minimum):
  - **monthly mean temperature** = mean of those daily temperatures;
  - **monthly mean anomaly** = mean of those daily °C anomalies;
  - **hottest valid observation** = the date and value of the maximum among them;
  - **maximum anomaly** = the largest daily °C anomaly among them;
  - **warm-observation count** = number of those days at ≥ 90th percentile (`METH-004`), reported alongside how many of the qualifying days had a percentile at all.
- If a stream has **< 3** qualifying days in the month → that stream's monthly cell reads **"insufficient valid observations"**, with the valid-day count and mean coverage still shown.
- Missing days are never zero-filled or interpolated (`QA-001`). A month with no qualifying day in any stream is shown as an explicit missing state.
- The **missing / cloud-obscured proportion** for the month (valid days ÷ calendar days, per stream) is always reported.

### METH-006 — Standardized multi-sensor indicator

- **No combined multi-sensor index for the MVP.** The four streams observe the lake at different local times, sun angles, and atmospheric states; direct averaging is explicitly excluded by the project's founding principle, and a defensible standardized indicator would need its own justification and validation.
- What the product does instead: **show the four streams side by side** for the same date/month, each with its own anomaly, percentile, and label, so the user can see where the streams agree and where they diverge.
- A documented optional extension: a per-stream standardized anomaly (e.g. `(observation − historical median) ÷ historical IQR` or a robust z-score), reported **per stream** and compared, never collapsed into one temperature. Only if time allows and `METH-002`'s mean/SD metadata proves stable enough.

---

## 4. Recommended bounded check before METH-001 / METH-003 are fixed

A small, read-only, coordinate-free diagnostic — call it a **historical sample-sufficiency probe** — over the approved lake-wide 0 m geometry and the approved `QA-002` acceptance rule:

- For each of the four streams and a representative set of calendar dates spanning the year, count how many of the 20 historical years (2003–2022) contain **at least one accepted valid-water observation** within ± 5, ± 7, ± 10, and ± 15 days.
- Output (coordinate-free): for each stream and window width, the distribution across calendar dates of that count — how often it clears 10, clears 20, or is near zero.
- This directly answers the review's concern (nominal 220 vs. the real number) and tells us:
  1. whether ± 5 days is viable at night or must be widened (`METH-001`), and
  2. whether the 10 / 20 minimum-sample thresholds are realistic (`METH-003`), and
  3. whether monthly summaries will regularly hit the ≥ 3-day minimum in winter.

It reuses the completed `AUDIT-010`/`PROTO` processing path, adds no new scientific rule, writes nothing permanent, and would be specified and approved as a bounded diagnostic like `AUDIT-011` / `AUDIT-012` (but lighter — it only counts, with no NASA source verification). Estimated as a handful of bounded Earth Engine requests.

---

## 5. What this proposal does **not** do

- It does not change `QA-001`, `QA-002`, `SPACE-001`, `TERM-001`, or any completed audit.
- It does not decide the interface layout, the download formats, the deployment approach (`ARCH-001`), the validation criteria (`VAL-001`), or the Landsat / ERA5-Land methods (`DATA-005`, `DATA-006`).
- It does not set the six-week minimum output list (`SCOPE-003`) — though it assumes the lake-wide, per-stream, daily + monthly outputs described in the consultation briefing.
- It does not create any application, asset, export, task, UI, or deployment.

---

## 6. If approved

On explicit user approval:

1. Record `METH-001` … `METH-006` as approved in `DECISIONS.md` with the exact rules and the reasoning.
2. If the §4 check is approved, draft its bounded coordinate-free specification for separate sign-off, run it, and fold its result back into the `METH-001` window and the `METH-003` thresholds before implementation.
3. Settle `SCOPE-003` (the concrete six-week output list) alongside these.
4. Begin Phase 3: implement the climatology (2003–2022 matched history), the °C anomaly, the Type-7 percentile with the sample-sufficiency gate, the classification, and the monthly aggregation — all per stream, on the whole-lake unit.
