# SCOPE-003 proposal — the six-week minimum viable product

- **Date:** 2026-09-02
- **Author:** Main Codex coordinator, for the user
- **Decision addressed:** `SCOPE-003` — "Select minimum viable outputs for the six-week delivery period and distinguish them from optional extensions."
- **Status:** **approved (2026-09).** The user confirmed both ERA5-Land and Landsat are **extensions** ("Both are extensions, let's try to finish first the core proposal, and then we can try to introduce ERA5-Land and then Landsat") — MVP core first, ERA5-Land attempted before Landsat, only after the core is delivered.
- **Context:** Phase 1 (audit) and the MODIS side of Phase 2 are complete. `SPACE-001` (lake-wide geometry, 0 m), `QA-002` (candidate-C acceptance rule + confidence tiers + monthly minimum), and `METH-001` … `METH-006` (anomaly method) are approved. `AUDIT-013` confirmed the historical sample supports the method. Phases 3–6 remain, in roughly three of the six weeks.

---

## 1. Recommended MVP (must be delivered)

### 1.1 The MODIS anomaly product

For each of the four streams (Terra-day, Aqua-day, Terra-night, Aqua-night), on the lake-wide unit, for every monitoring date 2023 → present (and the full 2003 → present archive for browsing):

- observed lake-average LST (°C), from accepted candidate-C pixels;
- valid-water coverage fraction and pixel count, and the `ok` / `low` / `none` confidence flag;
- historical reference = the median of the matched ± 5-day, 2003–2022, same-stream sample (`METH-001`, `METH-002`);
- **anomaly** = observed − historical median (°C);
- **historical percentile** (Type-7) and the classification label (`below normal` / `within normal range` / `warm` / `unusually warm` / `extreme warm observation`), with the `METH-003` sample gate (percentile shown only at `n ≥ 10`; flagged at `10 ≤ n < 20`);
- the strict-rule / candidate-A / candidate-B coverage and the QC-byte histogram (the `QA-002` transparency requirement).

Streams are never merged (`METH-006`); the four are shown side by side.

### 1.2 Daily observation view

Pick a date and stream → the numbers in §1.1, plus a **map of the accepted temperature pixels** for that date (the spatial pattern is visible; cloud gaps are visible), and an explicit "no valid observation" state when applicable.

### 1.3 Monthly summary view

Per stream, per month: monthly mean temperature, monthly mean anomaly, hottest valid observation (date + value), maximum anomaly, warm-observation count (days ≥ 90th percentile), valid-day count, and missing/cloud-obscured proportion — computed only from days at confidence `low` or better, requiring ≥ 3 such days, else "insufficient valid observations" (`METH-005`, `QA-002`).

### 1.4 A deployed Google Earth Engine application

The daily and monthly views above, as a working, hosted GEE app.

### 1.5 Written deliverables

Documented code, a technical report (method, decisions, limitations — including the summer-nighttime partial-coverage caveat from `AUDIT-013`), user guidance, and the internship presentation.

### 1.6 Validation appropriate to the MVP (`VAL-001`, to be detailed separately)

Without in-situ data: cross-stream consistency checks (Terra-day vs Aqua-day; the two night streams), comparison against the Li et al. (2024) product and the published literature range, provider-range sanity, and internal reproducibility. If in-situ Lake Balaton data is obtained, a direct skin-vs-bulk comparison is added.

## 2. Optional extensions — build only if the MVP core is on track by roughly week 4

| Extension | Effort | Note |
|---|---|---|
| **ERA5-Land weather context** (`DATA-006`) | Moderate | Air temperature, wind, solar radiation as a context panel beside the satellite value — never mixed into it. Lighter than Landsat; the first extension to attempt. |
| **Landsat 8/9 hotspot inspection** (`DATA-005`) | Large | A separate 30 m preprocessing pipeline for selected clear-sky dates. Realistically an extension, not core. |
| **Per-pixel anomaly map** | Moderate | Each pixel coloured by its own deviation from its own historical median, where the pixel has enough history — shows *where* the warmth is. |
| **Coarse west / centre / east zonal split (daytime streams)** | Moderate | Using the Tihany and Szigliget narrows, not a formal basin polygon; gives a per-zone verdict where daytime pixel counts allow. Needs a small approved zone definition. |

## 3. Documented as future work (not attempted in the six weeks)

- Formal four-basin (Keszthely / Szigliget / Szemes / Siófok) products — no authoritative geometry, and MODIS nighttime pixel counts do not support them (`SPACE-001`, `AUDIT-013`).
- Littoral / pelagic zonation.
- A marine-heatwave-style (Hobday et al.) consecutive-exceedance detector — missing daily observations make it unreliable (`METH-004` keeps single-observation language).
- Any standardized multi-sensor index beyond side-by-side display (`METH-006`).

## 4. The two choices for the user to confirm

1. **ERA5-Land context** — in the MVP core, or an extension? *(Coordinator recommends: extension — attempt it first among the extensions, but do not let it delay the MODIS product or the app.)*
2. **Landsat hotspot inspection** — an extension, or documented future work? *(Coordinator recommends: extension, low priority — it is a full second pipeline and the internship's core value is the anomaly product.)*

## 5. What this decides and does not decide

- It sets which outputs are in the six weeks. It does not re-open `SPACE-001`, `QA-002`, or `METH-*`.
- The precomputation and deployment mechanics are `ARCH-001` (to be decided when Phase 3 output stabilises — the 2003–2022 baseline is small and fixed, so the architecture can be simple).
- The validation specifics are `VAL-001`.
