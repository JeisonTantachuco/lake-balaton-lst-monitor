# VAL-001 proposal — validation acceptance criteria

- **Date:** 2026-09-09
- **Author:** Main Codex coordinator, for the user
- **Decision addressed:** `VAL-001` (validation acceptance criteria, and the response if in-situ
  data cannot be obtained) — `PROJECT_CONTEXT.md` open decision 12.
- **Status:** **criteria APPROVED 2026-09-09.** The user answered every §8 question with the
  recommended option: C3 primary = ESA CCI / Copernicus LWST (Li et al. secondary); C5 scope =
  2024 only; no in-situ data, proceed with C1–C6 now; thresholds as written. Promoted to
  `docs/PHASE_5_VALIDATION_SPECIFICATION.md`. This document is retained as the rationale record.
- **Evidence base:** `docs/PHASE_3_CLIMATOLOGY_REPORT.md`, `docs/PHASE_3_MONITORING_RESULTS_REPORT.md`
  (§6 names the three priorities), `AUDIT-011`/`AUDIT-012`/`AUDIT-013`, `QA-002`, `METH-001…006`,
  `SPACE-001`; the reference work Li, Somogyi & Tóth (2024); standard LSWT-validation practice.

---

## 1. What VAL-001 has to settle

Phase 3 produced the climatology baseline and the 2023→2026 anomaly records. They are **engine
output, not a validated result** — Phase 3 explicitly says so. VAL-001 decides:

1. **By what falsifiable checks** we judge the product good enough to publish as a monitoring tool.
2. **What we do given that no in-situ Balaton water-temperature data has been obtained** (the
   supervisor was asked in the 2026-09 consultation; none was provided).
3. **What happens when a check fails** — so a failure produces a decision, not a silent edit.

VAL-001 does **not** re-open `QA-002`, `METH-*`, or `SPACE-001`. If a check fails, the failure is
reported to the user with options; the method changes only on explicit approval.

---

## 2. The honest framing: what this product can and cannot be validated *for*

Without in-situ data we cannot calibrate **absolute** skin temperature to sub-degree accuracy.
We *can* establish that the product is:

- **internally coherent** (streams agree where physics says they should),
- **consistent with independent satellite LSWT products** for Balaton within their combined
  uncertainty,
- **physically plausible** against the known limnology of a large shallow lake, and
- **robust** — the anomalies and labels do not depend on arbitrary method choices.

That supports the product's actual claim (*"is this observation unusual for its matched
history, and how much can you trust it"*) — a **relative anomaly** claim, not an absolute
calibration claim. The validation report will state this boundary explicitly.

---

## 3. Proposed acceptance criteria

Each is falsifiable, with a stated pass line. All temperature checks are run **per stream** and
restricted to **`ok`-coverage** days/months unless noted (`low` days are already flagged and are
handled by C6).

### C1 — Physical plausibility of the climatology
- The 2003–2022 monthly climatology follows the expected annual cycle for a large shallow lake:
  winter minimum near 0–4 °C, summer maximum ~22–26 °C, single smooth peak in Jul–Aug.
- In summer months, **daytime mean ≥ nighttime mean** for the matching satellite; the diurnal
  ordering (Aqua-day warmest, night streams coolest) holds.
- **Pass:** no stream-month violates the annual-cycle shape or the summer day ≥ night ordering by
  more than 1 K (≈ the MOD11 LST error tier the product accepts).

### C2 — Cross-stream consistency
- On `ok` days with both Terra-day and Aqua-day present: Pearson **r ≥ 0.95**, mean absolute
  difference **≤ 1.5 °C** (the ~3 h overpass gap explains a real part of any gap). Same test for
  the two night streams.
- For every month with |anomaly vs median| > 2 °C in at least one stream: **≥ 90 %** of the other
  streams present that month agree on the **sign** of the anomaly.
- **Pass:** both bullets met; any exception individually explained in the report.

### C3 — Agreement with an independent satellite LSWT product
- Compare the monthly `ok` lake-mean against **at least one** independent LSWT product covering
  Balaton over an overlapping period. Candidate references, in preference order (availability
  confirmed at the start of Phase 5):
  1. **ESA CCI Lakes** Lake Water Surface Temperature (LWST), ~1992–2020, includes Balaton.
  2. **Copernicus Global Land** Lake Surface Water Temperature product.
  3. The **Li, Somogyi & Tóth (2024)** Balaton LSWT product (Zenodo `10013292`, shared EE repo) —
     same MODIS source, so this is a *processing-choice* cross-check rather than a fully
     independent one, but it is the closest published comparator.
  4. **ERA5-Land** `lake_mix_layer_temperature` — a model field, weakly independent, used only as
     a supporting line if 1–3 are unavailable.
- **Pass:** against the best available independent product (1 or 2), monthly bias within
  **± 1.0 °C**, RMSE **≤ 2.0 °C**, r **≥ 0.97**. A larger but *explained* difference (e.g. our
  night coverage, our 0 m shoreline, their cloud handling) is documented and does not by itself
  fail the product — it fails only if the difference is large **and** unexplained.

### C4 — External corroboration of the flagged anomalies
- The standout warm periods from the Phase 3 report — **Feb 2024** (night +5.1 °C), **Mar 2024**
  (+3.7 °C), **summer 2024** (all streams +1.2…2.5 °C), **2024 warmest year in every stream** —
  are checked for sign and rough magnitude against the **Copernicus Climate Change Service (C3S)
  European monthly climate bulletins** and ERA5-Land 2 m-temperature anomalies for the
  Transdanubia region.
- **Pass:** qualitative agreement (right sign, comparable magnitude, same months called out) for
  **every** standout period. A standout period with no external echo is a fail for that period and
  is reported.

### C5 — Robustness to method choices
- Re-run the climatology and **one** monitoring year (2024, the most anomalous) under each variant,
  changing one factor at a time:
  - (a) **strict** QC instead of candidate C;
  - (b) **463 m** shoreline erosion instead of 0 m;
  - (c) **±3-day** and **±7-day** day-of-year windows instead of ±5.
- **Pass:** for `ok` days, each variant shifts the monthly anomaly by **≤ 0.5 °C** and changes the
  `METH-004` label in **≤ 5 %** of well-observed stream-days. `low` days may change freely.
  Variant (a) is expected to shrink night coverage sharply — that is the `AUDIT-011` result, not a
  failure; what matters is that the *`ok`-day anomalies* are stable.

### C6 — Low-coverage artefact control
- Confirm the Phase 3 finding holds on the full record: **every** daily |anomaly| > 5 °C is either
  `low`-flagged **or** independently corroborated (C4-style).
- Confirm the app's handling: `low`-confidence days are visibly down-weighted / excluded from
  "warmest day" style summaries (Phase 3 report §6).
- **Pass:** no un-flagged, un-corroborated |anomaly| > 5 °C day; app behaviour confirmed.

---

## 4. Response if in-situ data cannot be obtained

**This is the expected case.** The plan:

- C1–C6 **are** the validation of record. They do not require in-situ data.
- The validation report states plainly: no in-situ Balaton water-temperature series was available;
  the product is validated for **relative anomaly monitoring**, not absolute calibration; an
  in-situ skin-vs-bulk cross-check remains documented **post-internship** work.
- A single "validation hook" is kept in the codebase: a small function that, given a CSV of
  `(datetime, depth, temperature, source)`, would produce the match-up statistics — so a future
  in-situ dataset can be checked without rebuilding anything. It is **not run** now.
- If in-situ data *does* arrive before the internship ends, add **C7**: match-up within ± 1 h of
  overpass, expect bias within ± 1.5 °C and RMSE ≤ 2.5 °C against bulk temperature at the
  shallowest available depth, with the skin–bulk difference discussed.

---

## 5. What a failure triggers

| Outcome | Action |
|---|---|
| All of C1–C6 pass | VAL-001 → **approved**; product declared validated for anomaly monitoring; one-line "validated:" note added to the app's About panel and to `THE_BALATON_METHOD` §11 / §4. |
| A criterion **fails with an explanation** (e.g. C3 night bias traced to coverage) | Report documents it as a **known limitation**; product still ships; the limitation is stated in the app and the report. User decides whether the limitation is acceptable. |
| A criterion **fails without explanation** | **Stop.** Report the failure and candidate causes to the user. No method change, no publication update, until the user chooses a direction. |

---

## 6. Deliverables

1. `docs/PHASE_5_VALIDATION_SPECIFICATION.md` — this proposal, promoted, with the reference
   products fixed once availability is confirmed.
2. `tools/run_validation_ee.py` — supervised (pattern of the existing audit runners),
   **coordinate-free** output, geometry via the same hash-pinned lake asset / fallback as Phase 3.
   Emits a JSON results block (git-ignored) + a text summary.
3. `tools/supervise_validation.py` — the supervisor wrapper, matching the house pattern.
4. `docs/PHASE_5_VALIDATION_REPORT.md` — criterion-by-criterion pass/fail, every exception
   explained, the §2 boundary restated, the §4 in-situ note.
5. `DECISIONS.md` `VAL-001` updated from *proposed* to the resulting status, with approval
   provenance.
6. If validated: the one-line "validated" note in `app/balaton_anomaly_app.js` (About panel) and
   in `docs/PROJECT_DECISIONS_EXPLAINED.md` / `docs/THE_BALATON_METHOD.html`.

---

## 7. What this proposal does **not** do

- It does not change `QA-002`, `METH-*`, `SPACE-001`, `TERM-001`, or any completed audit.
- It does not start Landsat or ERA5-Land as data products (`DATA-005` / `DATA-006`) — ERA5-Land
  appears here only as a validation comparator, read live, not preprocessed or stored.
- It does not create any Earth Engine asset, export, or deployment.
- It does not decide the app's visual treatment of the "validated" note beyond one line of text.

---

## 8. Open questions for the user — RESOLVED 2026-09-09

1. **Reference product for C3** — ESA CCI Lakes / Copernicus LWST as primary independent
   comparator; Li et al. (2024) as secondary. ✔
2. **C5 scope** — 2024 only. ✔
3. **Pass lines** — thresholds in §3 accepted as written. ✔
4. **In-situ** — none available, none in flight; proceed with C1–C6 now, C7 specified but dormant. ✔
