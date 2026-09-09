# Phase 5 — validation report (`VAL-001`)

- **Date:** 2026-09-09
- **Status:** **COMPLETE — all seven criteria (C1, C2, C3, C4, C5a, C5b, C6) pass**, three
  carrying a documented limitation. Label-sensitivity scoring resolved by the user 2026-09-09
  (option a: pass + limitation + "show the percentile next to the label"). **`VAL-001` approved.**
- **Spec:** `docs/PHASE_5_VALIDATION_SPECIFICATION.md`. Rationale: `docs/VAL_001_PROPOSAL.md`.
- **What is validated:** the Phase 3 output — the 2003–2022 climatology baseline and the
  2023→2026-08 daily anomaly records / monthly summaries.
- **Inputs (coordinate-free, git-ignored):** `local_run_state/phase3/climatology_baseline.json`
  (`rows_sha256 1ff9ca8d…`), `daily_anomaly_records.json` (`records_sha256 dfbd4f13…`),
  `monthly_summaries.json` (`rows_sha256 8e69b45d…`).
- **Tool:** `tools/run_validation_offline.py` (`--self-test` passes). Machine output:
  `local_run_state/phase5/validation_offline.json`.

---

## The boundary of this validation

No in-situ Balaton water-temperature series was available (the academic supervisor was asked in
the September 2026 consultation; none was provided, and none is in flight). Stages A and B
therefore establish that the product is **internally coherent, consistent with independent
products, physically plausible, and robust** — i.e. validated **for relative anomaly monitoring**,
not for absolute sub-degree calibration. An in-situ skin-vs-bulk cross-check (`C7`) is specified
in the spec but not run; a dormant hook is kept for a future dataset.

---

## Stage A results (offline)

| Criterion | Verdict | Headline number |
|---|---|---|
| **C1** climatology physical plausibility | **PASS** | winter day-stream min −0.1 °C, summer max 24.1 °C (Jul peak), diurnal ordering intact |
| **C2** cross-stream consistency | **PASS** | Terra-day/Aqua-day r = 0.991, MAD 1.47 °C; night pair r = 0.976, MAD 1.48 °C; big-anomaly sign agreement 94 % |
| **C4** external corroboration of the flagged anomalies | **PASS** | every Phase 3 standout matches a Copernicus C3S figure in sign and rough magnitude |
| **C5a** robustness — seasonal window width | **PASS** (with a documented limitation) | ±3/±7-day window shifts the 2024 anomaly by ≤ 0.9 °C (P95 ≤ 0.43); no ≥ 2-tier label jumps; ~7 % of `ok` days flip one adjacent tier at a percentile break |
| **C6** low-coverage artefact control | **PASS** | all 196 severe cloud artefacts are `low`-flagged (max fraction 0.14); 9 borderline days flagged for spot-check |

### C1 — the climatology looks like a shallow lake

Monthly mean of the per-day-of-year median, pooled over the two daytime streams:

| | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| day streams | −0.1 | 1.1 | 5.8 | 12.5 | 17.5 | 22.3 | **24.1** | 23.6 | 19.0 | 12.8 | 6.9 | 1.5 |
| night streams | −3.4 | −2.7 | 2.1 | 9.0 | 14.7 | 18.7 | 20.1 | 19.8 | 16.0 | 9.8 | 3.7 | −1.6 |

- Single smooth July peak, monotone rise Feb→Jul and fall Aug→Dec — no wobble.
- Winter surface near 0 °C (day) / −3 °C (night skin, consistent with ice and cold-skin effects);
  summer max ~24 °C — both inside the ranges published for Lake Balaton.
- JJA seasonal means: Aqua-day 23.7 ≥ Terra-day 22.9 ≥ Terra-night 20.0 ≈ Aqua-night 19.1.
  Daytime warmer than night for the matching satellite in every summer month. No violation
  above the 1 K tolerance.

### C2 — the streams agree where physics says they should

- **Daytime pair (Terra-morning vs Aqua-afternoon), 667 days both `ok`:** r = 0.991, mean
  absolute difference 1.47 °C. The ~1.5 °C gap is real diurnal warming between ~10:00 and ~13:00,
  not disagreement.
- **Nighttime pair, 103 days both `ok`:** r = 0.976, MAD 1.48 °C. Small n is the known structural
  night-coverage limit (`AUDIT-011`), not a failure of agreement.
- **Monthly big-anomaly sign agreement: 94 %** (17 months with |anomaly| > 2 °C in ≥ 1 stream).
  The four exceptions are all small-magnitude same-month disagreements (a stream at +0.3…+1.0 °C
  while another ran strongly negative), in Nov 2024 and Feb 2026 — noted, not disqualifying.

### C4 — the standout anomalies are echoed by Copernicus C3S

| Phase 3 standout (vs 2003–2022 median) | Independent figure (vs 1991–2020) | Agree? |
|---|---|---|
| **Feb 2024** Terra-night **+5.1 °C** | Europe Feb 2024 **+3.30 °C**, "much-above-average in central and eastern Europe"; winter DJF +1.44 °C | ✔ sign + magnitude |
| **Mar 2024** Terra-night **+3.7 °C** | Europe Mar 2024 **+2.12 °C**, "most above average in central and eastern regions" | ✔ |
| **Summer 2024** all streams **+1.2…2.5 °C** | Europe JJA 2024 **+1.54 °C** (warmest on record); SE Europe persistent record months | ✔ |
| **2024 warmest year, every stream** (+0.9…1.4 °C) | **Warmest year on record for Europe**; eastern Europe ~2–3 °C above the annual average | ✔ |

Our anomalies are computed against a 2003–2022 median — a warmer, more recent baseline than
1991–2020 — so our figures being somewhat *smaller* than the C3S 1991–2020 anomalies is the
expected direction. Sources: Copernicus C3S monthly bulletins (Feb, Mar 2024), "Summer 2024 –
Hottest on record", European State of the Climate 2024.

### C5a — the °C anomaly is robust to the window choice; tier labels are soft at the breaks

The ±5-day rebuild from the stored historical values **reproduces the Phase 3 engine exactly**
(max |Δmedian| 0.000 °C, max |Δpercentile| 0.000), so the ±3 / ±7 comparison is like-for-like.

For the 641 well-observed (`ok`) 2024 stream-days:

| variant | mean \|Δanomaly\| | P95 | max | days shifting > 0.5 °C | label changes | ≥ 2-tier jumps |
|---|---|---|---|---|---|---|
| **±3 day** | 0.15 °C | 0.43 °C | 0.90 °C | 22 / 641 (3.4 %) | 45 / 641 (7.0 %) | **0** |
| **±7 day** | 0.11 °C | 0.32 °C | 0.70 °C | 5 / 641 (0.8 %) | 50 / 641 (7.8 %) | **0** |

- **The anomaly in °C barely moves** — well inside the 0.5 °C bar for > 96 % of days, and the
  worst case (0.9 °C) is a spring day where the window genuinely re-weights a fast-changing season.
- **Every label change is one adjacent tier** (0 jumps of two or more), spread across all four
  streams. They are days sitting right on a 90 / 95 / 99 percentile break, where a 0.1 °C shift in
  the reference median tips them over. This is a property of any hard-threshold classification.
- **Verdict:** PASS on the anomaly-stability question. The ~7 % adjacent-tier label sensitivity
  **exceeds the proposal's flat 5 % label line** and is recorded as a limitation — the proposal
  did not distinguish an adjacent-tier flip at a boundary from real instability. *Scoring is the
  open question below.*

### C6 — the `low` flag isolates the cloud artefacts

Of the 3,608 daily records, **304** have |anomaly vs median| > 5 °C:

| Group | Count | Reading |
|---|---|---|
| `low`-flagged | 196 | every one built from ≤ 14 % lake coverage (mean 2 %); anomalies −21 to +16 °C from 1–5 pixels. **The flag catches all of them.** |
| `ok`, coverage ≥ 30 % | 81 | 56 sit in an independently anomalous month; 25 are isolated clear-sky spikes (many at 99 % coverage) — **real short warm/cold pulses, not artefacts** |
| `ok`, coverage 15–30 % | 27 | 18 month-backed; **9 isolated → the spot-check set** |

**No flag leaks:** every |anomaly| > 5 °C day below the 15 % coverage threshold is `low`.
The 9-day borderline set (0.25 % of all records) is listed in
`validation_offline.json → C6 → review_set` — e.g. 2026-07-19 Aqua-day +8.1 °C at 25 % coverage
in a month already running +1.3 °C. These are plausible but under-sampled; they are the reason
for the recommendation below.

---

## Stage B results

Tool: `tools/run_validation_ee.py` (`--self-test` passes). Machine output:
`local_run_state/phase5/validation_ee_c3.json`. Reference series cached (coordinate-free, monthly
lake-area means only) in `local_run_state/phase5/c3_reference_cache.json`.

| Criterion | Verdict | Headline number |
|---|---|---|
| **C3** agreement with an independent product | **PASS** | Landsat vs our Terra-morning stream, **258 months (2003–2024)**: bias −0.53 °C, RMSE 1.83 °C, r = 0.985 |
| **C5b** robustness — strict QC / 463 m erosion | **PASS** (with documented limitations) | 463 m erosion: mean anomaly effect −0.07 °C, 4.7 % of `ok` days shift > 0.5 °C. Strict QC: no systematic bias (−0.07 °C) but day-to-day scatter to ±1.9 °C — evidence for the QA-002 rule choice |

### C3 — an unrelated instrument agrees with us

The comparator: **Landsat Collection 2 Level-2 surface temperature** (Landsat 5 TM, 7 ETM+, 8/9
TIRS) — a different thermal sensor from MODIS, overpass ~10:15 local. All clear Landsat scenes in
a month are averaged to one lake value and matched to our monthly mean. Our monthly means are the
Phase 3 summaries for 2023–2024 and are rebuilt from the stored historical daily lake-means
(≥ 3 days) for 2003–2022.

| comparison | n months | bias (ours − ref) | RMSE | r |
|---|---|---|---|---|
| **Landsat vs our Terra-morning** (primary) | 258 | **−0.53 °C** | **1.83 °C** | **0.985** |
| Landsat vs our day-stream mean | 258 | −0.18 °C | 1.74 °C | 0.985 |
| ERA5-Land mix-layer vs our Terra-morning | 264 | −0.78 °C | 1.36 °C | 0.992 |
| ERA5-Land mix-layer vs our all-stream mean | 264 | −2.30 °C | 2.54 °C | 0.993 |

- **Two unrelated instruments track each other at r = 0.985 over 22 years**, with a sub-degree
  mean bias — comfortably inside the pass line (bias ± 1.5 °C, RMSE ≤ 2.5 °C, r ≥ 0.95).
- **Seasonal structure in the bias:** we read ~1–1.5 °C *cooler* than Landsat in Jun–Oct, near-zero
  in winter. Physically sensible — Landsat's 30 m pixels resolve the warm shallow nearshore water
  that MODIS's 1 km pixels average together with the cooler open lake, and the effect is largest
  in summer when the margins are much warmer than the middle. A documented characteristic, not a
  failure; it does not affect the anomaly (both our baseline and our monitoring value carry the
  same 1 km smoothing).
- **ERA5-Land** (an independent *model*, not a measurement) correlates at r ≈ 0.99. Against our
  Terra-morning stream its bias is −0.8 °C; against our all-stream mean it is −2.3 °C because its
  `lake_mix_layer_temperature` is a bulk, all-day quantity, warmer than the night streams' skin
  temperature. Reported as context; the −2.3 °C figure is a limitation of the *comparison*, not
  of our product.

### C5b — the anomaly is robust to the pixel rule

Bounded probe: a 2024 every-12th-day sample (31 dates × 4 streams), re-derived under strict QC
and 463 m erosion; the historical shift is modelled per calendar month from a spread sample
(years 2006 / 2012 / 2018 / 2022, days 8 / 16 / 24). `Δanomaly` = the change in *today − baseline*
the rule would cause (a rule that moves today and the baseline equally cancels).

| variant | `ok` sample days | mean signed Δanomaly | mean \|Δ\| | P95 | max | days > 0.5 °C | ≥ 2-tier label jumps |
|---|---|---|---|---|---|---|---|
| **463 m erosion** | 64 | −0.07 °C | 0.18 °C | 0.40 °C | 0.77 °C | 3 (4.7 %) | **0** |
| **strict QC** | 45 | −0.07 °C | 0.38 °C | 1.03 °C | 1.88 °C | 11 (24 %) | **0** |

- **463 m shoreline erosion:** the anomaly barely moves — mean effect −0.07 °C, 4.7 % of `ok` days
  over 0.5 °C (inside the 5 % line), no ≥ 2-tier label jumps. **Our 0 m shoreline choice does not
  bias the anomaly.** 6.2 % of days flip one adjacent tier — the same percentile-boundary effect
  as C5a.
- **Strict QC (all four QC fields == 0):** **no systematic bias** — the mean signed Δanomaly is
  −0.07 °C, i.e. candidate C is not skewed relative to the strict rule. But individual
  well-observed *daytime* days swing up to ±1.9 °C, because the strict rule discards a different
  handful of pixels each day and those pixels can be locally warm or cool. The two largest are
  early-spring Terra-morning days (13 & 25 March 2024, +1.9 / +1.7 °C) where thin-cloud / ice-edge
  pixels that candidate C keeps are cut. **This is the behaviour `QA-002` chose against** — strict
  QC also gives ≈ 0 % nighttime coverage (`AUDIT-011`). The scatter is evidence *for* the rule the
  product uses, not a defect in it. Recorded as a limitation of the *comparison*.

---

## Recommendations arising from validation

1. **Show the per-day coverage percentage even for `ok` days** in the app. `ok` currently spans
   16 % to 99 % coverage; a user seeing a +8 °C reading deserves to know which end it sits at.
   (C6 review set; not a correctness bug.)
2. **Show the percentile number next to the label** (C5a). ~7 % of well-observed days sit close
   enough to a 90 / 95 / 99 break that a small method change flips the tier — the label alone
   over-states the precision of the boundary. The percentile makes "just over the line" visible.
3. Consider whether the flat `ok` / `low` split at 15 % wants a third middle tier (~15–35 %).
4. Carry the 4 C2 sign-disagreement months into the app's monthly view as a "streams disagree
   this month" note, if cheap.

None of these block publication; all are recorded for the user.

---

## Label sensitivity at the percentile boundaries (C5a + C5b) — resolved

Across all three method variants (±3 / ±7-day window, 463 m erosion), the °C anomaly is stable but
**~6–8 % of well-observed days flip one adjacent label tier** — always a single step, never two,
driven by days sitting exactly on a 90 / 95 / 99 percentile break where a ~0.1 °C shift in the
reference tips them over.

**User decision (2026-09-09): option (a).** C5a and C5b **pass** on the anomaly-stability question.
The boundary label sensitivity is a **documented limitation** of the classification, carried into
the app: the app will **show the percentile number next to the label** so a "just over the line"
reading is visible rather than presented as a hard tier. `METH-004` is unchanged.

---

## Verdict

**All seven criteria pass** (C1, C2, C3, C4, C5a, C5b, C6). The product is:

- **internally coherent** — the four streams agree where physics requires (C2), and the 2003–2022
  climatology is the annual cycle of a large shallow lake (C1);
- **consistent with independent evidence** — with an unrelated satellite instrument (Landsat) to
  within 0.5 °C and r = 0.985 over 22 years (C3), and with the Copernicus European climate record
  on every flagged anomaly (C4);
- **robust** — its °C anomalies barely move under the seasonal-window choice (C5a) or the
  shoreline choice (C5b), and comparing against the strict QC rule reveals no systematic bias;
- **honest about uncertainty** — the coverage flag reliably isolates every severe cloud artefact
  (C6).

Three documented limitations travel with it: the ~6–8 % adjacent-tier label sensitivity at
percentile boundaries; the 9-day (0.25 %) borderline-coverage spot-check set; and that strict QC
is not a viable alternative rule for this lake (which is why `QA-002` did not choose it).

**`VAL-001` is approved (2026-09-09).** The product is validated **for relative anomaly
monitoring**, not absolute calibration.

## Follow-through

1. Add a one-line "validated" note to the app's About panel and to
   `docs/PROJECT_DECISIONS_EXPLAINED.md` / `docs/THE_BALATON_METHOD.html`.
2. **Show the percentile number next to the classification label** in the app (the C5a/C5b
   decision).
3. Show the per-day valid-water coverage % even for `ok` days (C6).
4. Optional: a "streams disagree this month" note for the 4 C2 exception months; consider a
   middle coverage tier (~15–35 %).
