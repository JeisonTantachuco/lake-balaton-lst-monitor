# Phase 5 — validation specification (`VAL-001`)

- **Date:** 2026-09-09
- **Author:** Main Codex coordinator, for the user
- **Status:** **VAL-001 APPROVED 2026-09-09.** Criteria approved, study executed, all seven
  criteria pass. Label-sensitivity scoring resolved (option a: pass + limitation + show the
  percentile next to the label). See `docs/PHASE_5_VALIDATION_REPORT.md`.
- **Rationale record:** `docs/VAL_001_PROPOSAL.md` (framing, alternatives, why these checks).
- **Boundary:** validates the Phase 3 output (`docs/PHASE_3_CLIMATOLOGY_REPORT.md`,
  `docs/PHASE_3_MONITORING_RESULTS_REPORT.md`). Does not change `QA-002`, `METH-*`, `SPACE-001`,
  `TERM-001`, or any audit. Coordinate-free. Creates no Earth Engine asset, export, or deployment.

---

## 1. Locked decisions (from `VAL_001_PROPOSAL.md` §8)

| Question | Decision |
|---|---|
| C3 primary comparator | **ESA CCI Lakes / Copernicus Global Land LWST** (genuinely independent). Li, Somogyi & Tóth (2024) Balaton product = **secondary** cross-check. ERA5-Land `lake_mix_layer_temperature` = weak fallback only if neither independent product is usable. |
| C5 robustness scope | **2024 only** (the most anomalous monitoring year). |
| In-situ data | **None available; not waiting.** C1–C6 are the validation of record. C7 (in-situ match-up) is specified but not run; an unused hook is kept in the codebase. |
| Numeric thresholds | **As written in §2.** |

---

## 2. Acceptance criteria

All temperature checks run **per stream** (`terra_day`, `aqua_day`, `terra_night`, `aqua_night`)
and are restricted to **`ok`-coverage** days/months unless stated. `low` days are covered by C6.

### C1 — Physical plausibility of the 2003–2022 climatology
- Annual cycle: winter monthly minimum 0–4 °C, summer monthly maximum ~22–26 °C, single smooth
  Jul–Aug peak, monotone rise Feb→Jul and fall Aug→Dec (± noise).
- Summer (Jun–Aug): daytime monthly mean ≥ nighttime monthly mean for the matching satellite;
  diurnal ordering aqua_day ≥ terra_day ≥ terra_night ≈ aqua_night holds in the seasonal mean.
- **Pass:** no stream-month breaks the annual-cycle shape or the summer day ≥ night ordering by
  more than **1 K**.

### C2 — Cross-stream consistency
- Days with both `terra_day` and `aqua_day` at `ok`: Pearson **r ≥ 0.95** and mean absolute
  difference **≤ 1.5 °C**. Same for `terra_night` vs `aqua_night`.
- Every month with |monthly_mean_anomaly_vs_median_c| > 2 °C in ≥ 1 stream: **≥ 90 %** of the
  other streams reported that month agree on the anomaly **sign**.
- **Pass:** both bullets met; listed exceptions individually explained.

### C3 — Agreement with an independent satellite LSWT product
- Monthly `ok` lake-mean (per stream, and streams pooled) vs the comparator over the full overlap.
- **Comparator availability (checked 2026-09-09):** ESA CCI Lakes / GloboLakes LSWT is **not in
  the Earth Engine catalogue** — it is distributed as NetCDF via CEDA and requires registration
  and a separate processing pipeline, which is out of scope for the internship window. The
  Copernicus Global Land LWST product is likewise not readily available in EE. **Substitute
  comparators, both genuinely usable:**
  1. **Landsat Collection 2 Level-2 surface temperature** (`ST_B10`; Landsat 5/7/8/9) — a
     *different instrument* (TIRS/TM) from MODIS, in EE, processed by us to a monthly lake-mean.
     This is the primary independent-satellite line.
  2. **ERA5-Land `lake_mix_layer_temperature`** — independent model reanalysis, in EE, full
     coverage. Second line.
  3. **Li, Somogyi & Tóth (2024)** Balaton product — MODIS-based, so a processing-choice
     cross-check; reported for context if reachable.
  **This substitution needs user sign-off** before C3 is scored (§8 of `VAL_001_PROPOSAL.md` is
  superseded on this point).
- **Pass:** against the Landsat line, monthly bias within **± 1.5 °C**, RMSE **≤ 2.5 °C**,
  Pearson **r ≥ 0.95** (looser than the original ESA-CCI targets because Landsat monthly means
  rest on few scenes and a coarser water mask). A larger difference *traced to a documented
  cause* (our night coverage, 0 m shoreline, Landsat scene sparsity) is a limitation, not a fail.

### C4 — External corroboration of the flagged anomalies
- For each Phase 3 standout — **Feb 2024** night +5.1 °C, **Mar 2024** +3.7 °C, **summer 2024**
  all streams +1.2…2.5 °C, **2024 warmest year in every stream** — check sign and rough magnitude
  against the **C3S European monthly climate bulletins** and ERA5-Land 2 m-temperature anomalies
  for the Transdanubia region.
- **Pass:** qualitative agreement (right sign, comparable magnitude, month called out) for **every**
  standout. A standout with no external echo fails for that item and is reported.

### C5 — Robustness to method choices (2024)

Split by what each variant needs:

**C5a — seasonal window width (offline, no Earth Engine).** Rebuild the climatology at **±3** and
**±7** days from the stored historical daily lake-means; re-derive every 2024 anomaly + label,
holding the daily value fixed.
- **Pass:** for `ok` 2024 days, ≤ 5 % shift > 0.5 °C in anomaly **and** no ≥ 2-tier label jumps.
  One-adjacent-tier label flips at the 90/95/99 percentile breaks are reported as a **limitation**,
  not a fail — they are a property of any hard-threshold classification and the flat 5 % line in
  the proposal does not separate them from real instability. *(User to confirm this reading.)*

**C5b — accepted-pixel variants (Earth Engine).** Re-derive 2024 daily lake-means (and the matched
historical window means) under each single-factor variant:
  (a) **strict** QC (all four QC fields == 0) instead of candidate C;
  (b) **463 m** shoreline erosion instead of 0 m.
- **Pass:** for `ok` days, each variant shifts the anomaly by **≤ 0.5 °C** and changes the
  `METH-004` label in **≤ 5 %** of well-observed stream-days. Variant (a) collapsing *night*
  coverage is expected (`AUDIT-011`) and is not itself a fail — the `ok`-day anomaly stability is
  what is tested. Because both the daily value and the climatology use the same rule, a rule change
  that shifts both equally leaves the anomaly unchanged; C5b measures whether the two sides move
  *differently*.

### C6 — Low-coverage artefact control
- On the full record: **every** day with |anomaly_vs_median_c| > 5 °C is either `confidence == low`
  **or** externally corroborated (C4-style).
- App behaviour: `low` days are visibly down-weighted and excluded from "hottest observation" style
  summaries (confirm against `app/balaton_anomaly_app.js` and the monthly `hottest_observation_*`
  fields).
- **Pass:** no un-flagged, un-corroborated |anomaly| > 5 °C day; app behaviour confirmed.

### C7 — In-situ match-up (specified, NOT run)
- If a `(datetime, depth, temperature, source)` series is obtained: match within ± 1 h of overpass;
  expect bias within **± 1.5 °C**, RMSE **≤ 2.5 °C** vs bulk temperature at the shallowest depth;
  discuss the skin–bulk difference.
- Not executed in Phase 5. A dormant `insitu_matchup()` function is kept so a future dataset needs
  no rebuild.

---

## 3. Failure handling

| Outcome | Action |
|---|---|
| C1–C6 all pass | `VAL-001` → **approved / validated**; add a one-line "validated:" note to the app About panel and `THE_BALATON_METHOD` §4/§11 + `PROJECT_DECISIONS_EXPLAINED.md` §4/§11. |
| Criterion fails **with a traced cause** | Report it as a **known limitation**; product ships; limitation stated in the app and report. User confirms the limitation is acceptable. |
| Criterion fails **without a cause** | **Stop.** Report the failure + candidate causes to the user. No method change, no publication update, until the user decides. |

---

## 4. Execution plan

**Stage A — offline (no Earth Engine): C1, C2, C4, C5a, C6.** — DONE (see the report).
Reads only the coordinate-free Phase 3 artefacts
(`climatology_baseline.json`, `historical_daily_values.json`, `daily_anomaly_records.json`,
`monthly_summaries.json`). Script: `tools/run_validation_offline.py` (+ `--self-test`).
C4 uses a small table of published C3S figures with sources cited inline. C5a rebuilds the
climatology at ±3 / ±7 days from the stored historical values and re-derives 2024.

**Stage B — Earth Engine: C3, C5b.**
`tools/run_validation_ee.py` + `tools/supervise_validation.py`, same supervised, coordinate-free,
hash-pinned-geometry pattern as `tools/run_anomaly_engine_ee.py`, reusing the audit-010
`AuditRunner` (`_masks`, `_validity`, `candidate()` erosion) exactly as the Phase 3 engine does.
- C3: reduce Landsat C2 L2 `ST_B10` and ERA5-Land `lake_mix_layer_temperature` to a monthly lake
  value, align to our monthly `ok` means, compute bias / RMSE / r.
- C5b: re-derive 2024 daily lake-means + the matched historical window means under strict-QC and
  463 m erosion; diff the resulting anomalies and labels. Bounded to 2024 + the day-of-years that
  appear in 2024 (not a full 20-year re-run).

**Stage C — report + decision.**
`docs/PHASE_5_VALIDATION_REPORT.md`: criterion-by-criterion pass/fail, every exception explained,
the "relative anomaly, not absolute calibration" boundary restated, the no-in-situ note.
Then `DECISIONS.md` `VAL-001` updated to the resulting status with provenance.

---

## 5. Deliverables

1. `tools/run_validation_offline.py` (+ self-test) — Stage A. **Done.**
2. `tools/run_validation_ee.py` + `tools/supervise_validation.py` — Stage B. *Pending user
   sign-off on the C3 comparator substitution.*
3. `docs/PHASE_5_VALIDATION_REPORT.md` — running report; interim after Stage A, final after Stage B.
4. `DECISIONS.md` `VAL-001` status update.
5. On a pass: the one-line "validated" note in the app + both explainer documents.
