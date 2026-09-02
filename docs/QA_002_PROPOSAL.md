# QA-002 proposal — valid-water coverage and MODIS QA acceptance thresholds

- **Date:** 2026-09-02
- **Author:** Main Codex coordinator, for the user
- **Decision addressed:** `QA-002` (proposed; `PROJECT_CONTEXT.md` open decision 6) — "Select minimum valid-water coverage and other QA acceptance thresholds for daily and monthly reporting."
- **Status:** **proposal only.** This document does not approve anything, does not change any completed audit (`AUDIT-001` … `AUDIT-012`) or the prototype's strict engineering rule, and does not resolve `SPACE-001`, `SCOPE-003`, or any `METH-*`/`DATA-*` decision. Approval requires an explicit user decision recorded in `DECISIONS.md`; the natural approval point is the early-September supervisor consultation (briefing section C).
- **Evidence base:** `AUDIT-011` (`docs/NIGHTTIME_GATE_ATTRIBUTION_DIAGNOSTIC_REPORT.md`), `AUDIT-012` (`docs/NIGHTTIME_QA_CANDIDATE_COMPARISON_REPORT.md`), the prototype QC decoding and strict rule (`docs/FIRST_PROTOTYPE_SPECIFICATION.md` §7–8), `QA-001` (approved), and the MOD11A1/MYD11A1 Collection 6.1 QC-byte definitions.

---

## 1. What QA-002 has to settle

Three linked choices, for the MODIS side of the product:

1. **The per-pixel QA acceptance rule** — which decoded QC-byte states count as an accepted valid-water LST retrieval, separately for the daytime and nighttime streams.
2. **The minimum valid-water coverage** a daily observation needs before its value is reported with confidence (vs. reported with a low-confidence flag, vs. shown as no valid observation).
3. **The minimum valid-observation count and coverage** a monthly summary needs before a monthly value is reported.

`QA-001` (approved) already fixes the surrounding behaviour: never invent or interpolate a missing observation; always report valid-water coverage and observation counts; provide an explicit "no valid observation" state. QA-002 therefore sets *thresholds and a per-pixel rule inside that frame* — it does not decide whether to interpolate (that is settled: no).

Landsat and ERA5-Land QA are **out of scope** here and belong to `DATA-005` / `DATA-006`.

---

## 2. Evidence

### 2.1 The current strict engineering rule collapses at night

The prototype's strict acceptance rule (`docs/FIRST_PROTOTYPE_SPECIFICATION.md` §8.4) is, in effect, **decoded QC byte == 0** plus provider-range validity of LST, view time, and view angle:

```
accepted = E && Q && L && Vt && Va
        && mandatory_qa == 0 && data_quality == 0
        && emissivity_error == 0 && lst_error == 0
```

`AUDIT-011` ran the declared-order gate waterfall for this rule over both nighttime streams, the original 0 m polygon, and the four approved 14-day 2024 windows (112 nighttime observations). Result:

| Stream | Valid-temperature coverage (mean; positive dates) | After mandatory QA | After the data-quality flag → final |
|---|---|---|---|
| Terra night | 42.68 % on 42 / 56 dates | ~0.03 % on 3 dates | **0 % on every date** |
| Aqua night | 48.58 % on 47 / 56 dates | ~0.07 % on 9 dates | **0 % on every date** |

The strict rule yields **zero final nighttime coverage on all 8 window-streams and all 56 dates per stream**. Order-independent (standalone / leave-one-out / exclusive-failure) evidence showed the only positive exclusive-failure gate was the `data_quality` flag; the other detailed gates are not independently empty, but no pixel clears all of them together at the strict setting.

### 2.2 The nighttime QC structure is essentially one byte

`AUDIT-012` compared three candidate rules over the same 112 nighttime observations, all four shoreline treatments, and both streams (completed 2026-09-02, `"pass": true`). Conditional on common validity `V` (exactly one image; unmasked QC; provider-range LST, view time, view angle), over the four windows × Terra/Aqua night at 0 m:

- **Only five distinct QC bytes** occur in the entire valid-water nighttime dataset (8 284 px): **65, 8, 17, 73, 81**.
- **98.7 %** are byte **65 = `M1 / D0 / E0 / T1`**: mandatory "other quality", good data quality, emissivity error ≤ 0.01, **average LST error ≤ 2 K** (the `T=1` tier — not the strict `T=0` "≤ 1 K").
- **No byte present has `D=0 & E=0 & T=0`.**

| Candidate | Rule | Positive days / 112 | Coverage vs `V` |
|---|---|---|---|
| — | strict rule (§2.1) | ~0 | ~0 % |
| **A** | `V & mandatory_qa == 0` | 12 | **~0.5 %** |
| **B** | `V & mandatory_qa ∈ {0,1} & D=0 & E=0 & T=0` | 0 | **0 %** |
| **C** | `V & mandatory_qa ∈ {0,1} & D=0 & E≤1 & T≤1` | 88 | **~99 %** |

Nearly every `M=0` night pixel also has `D>0`, so even candidate A's ~0.5 % is "good mandatory tier / poor data quality". Candidate B is empty for the same reason the strict rule is: nothing at night clears the strict `T=0` LST-error tier with `E=0` and `D=0`. Candidate C recovers ~99 % of common validity, entirely through byte 65 (`C_minus_B_M0 = 0` everywhere; per `(window, stream)` `C / V` ranges 0.978–1.000).

**Shoreline sensitivity (candidate C):** eroding the polygon lowers the daily coverage fraction by ~0.9 pp at ~460 m, ~1.0 pp at 500 m, ~1.5 pp at ~925 m; candidate A is unaffected at the noise level; B stays zero. (Shoreline treatment itself is a separate open choice; the erosion evidence is `AUDIT-001…010`.)

### 2.3 Nighttime coverage magnitude (candidate C, 0 m, lake-wide)

Daily valid-water fraction: **mean ≈ 0.106, maximum ≈ 0.75**, with roughly **24 of 112** window-dates at exactly zero. Per `(window, stream)`, C's mean daily coverage runs ~0.05 (summer) to ~0.19 (winter). Nighttime coverage on Lake Balaton is **structurally low** — a high fixed coverage threshold would suppress most nights even under the permissive rule.

### 2.4 Daytime

`AUDIT-011` and `AUDIT-012` are **nighttime-only**. There is no daytime A/B/C comparison and no compiled daytime coverage distribution under a fixed rule. `AUDIT-011`'s framing (the strict rule "produced zero *final nighttime* coverage") implies daytime is not identically degenerate, but this has not been measured. The daytime rule is proposed **provisionally** below, with a recommended confirmation diagnostic.

---

## 3. Proposal

### 3.1 Nighttime MODIS QA acceptance rule — adopt candidate C

Accept a nighttime valid-water LST pixel when:

```
accepted_night = E && Q && L && Vt && Va
              && mandatory_qa ∈ {0, 1}
              && data_quality == 0
              && emissivity_error <= 1        # average emissivity error ≤ 0.02
              && lst_error <= 1               # average LST error ≤ 2 K
```

`E` = eligible (spatial) mask; `Q` = QC unmasked; `L` = LST present and in provider raw range; `Vt`, `Va` = view time / angle present and in range. QC comparisons remain gated on `Q` and computed from the QC band's own valid mask (unchanged from the prototype ordering rule).

**Why C:**

- It is the **only tested rule that yields a usable nighttime record** (~99 % of common validity vs ~0 % for the strict rule and candidate B, ~0.5 % for candidate A). Choosing anything stricter is choosing to have **no nighttime product** for Lake Balaton.
- Its tolerances stay inside MODIS's own documented tiers and match common MOD11 practice for inland-water work: mandatory ∈ {good, other quality}, data quality strict, emissivity error ≤ 0.02, **LST error ≤ 2 K**. Requiring the ≤ 1 K tier over a small lake is unusually strict and, here, empty.
- Keeping **`data_quality == 0` strict costs almost nothing** (the only `D>0` bytes present, 8 and 73, are ~0.8 % combined) while preserving a real quality guarantee.
- The recovered area is not a marginal tail: it is one dominant, well-defined QC state (byte 65), not a scatter of borderline pixels.

**Transparency conditions (mandatory regardless of the rule chosen):**

1. Every daily record reports, alongside the accepted coverage, the coverage that **would** result from the strict rule, from candidate A, and from candidate B, plus the QC-byte histogram over the QC-observed area. The composition of every reported number stays visible and the rule stays reversible without re-running anything.
2. Product metadata and the technical report state plainly that the **nighttime record rests on the "average LST error ≤ 2 K" tier**, and that `M=0` "good quality" nighttime retrievals are effectively absent on Lake Balaton.

### 3.2 Alternatives (for the consultation to weigh)

| Option | Rule | Effect | Assessment |
|---|---|---|---|
| **C** *(recommended)* | as §3.1 | ~99 % of `V` at night | Usable product; honest about the tier it rests on. |
| **C′** *(minimal relaxation)* | keep `emissivity_error == 0`, only `lst_error <= 1` | ~99 % minus ~0.5 % (bytes 17, 81) | Acceptable fallback if the supervisor wants the least possible relaxation; keeps emissivity strict, still admits byte 65. |
| **A / strict** | `mandatory_qa == 0` (or byte == 0) | ~0.5 % / ~0 % at night | Legitimate but severe: **accept that Balaton has no nighttime thermal-anomaly product** and state so. |
| **Looser** | e.g. drop the detailed-flag gate, accept `mandatory_qa <= 1` alone; or allow `data_quality <= 1` | +negligible coverage here | Not recommended — adds nothing measurable on this lake and weakens the quality claim. |

### 3.3 Daytime MODIS QA acceptance rule — provisional, pending a bounded check

- **Provisionally** apply the same structure as §3.1 to the daytime streams (`terra_day`, `aqua_day`) — symmetric rule, one definition to document.
- **Recommended before it is fixed:** a bounded coordinate-free daytime QA candidate comparison (a small "`AUDIT-013`", the daytime analogue of `AUDIT-012`) over the same four windows, to check whether the daytime QC distribution is degenerate in the same way. If daytime coverage under the **strict** rule is already adequate, the daytime rule may legitimately stay stricter than the nighttime rule — the four streams are independent by design (briefing §2), so an asymmetric rule is acceptable if each side is stated.
- This is an open item for the consultation: *symmetric C day and night, or a stricter daytime rule confirmed by a daytime diagnostic?*

### 3.4 Minimum valid-water coverage — per-observation confidence tier, not suppression

Consistent with `QA-001` (always report coverage and counts; explicit no-observation state), a daily observation is **not suppressed on coverage alone**. Instead each daily observation carries a confidence tier derived from its accepted valid-water fraction `f` within the reporting spatial unit:

| Tier | Condition | Meaning |
|---|---|---|
| `full` | `f ≥ 0.50` | Most of the unit observed. |
| `good` | `0.20 ≤ f < 0.50` | Substantial coverage. |
| `partial` | `0.05 ≤ f < 0.20` | Limited coverage; value shown, flagged. |
| `sparse` | `0 < f < 0.05` | Very limited; value shown, strongly flagged. |
| `none` | `f = 0` | Explicit "no valid observation" state (`QA-001`). |

These cut-offs are **candidates for the consultation to set**. The evidence (§2.3) shows nighttime `f` rarely exceeds 0.5, so `full` nights will be rare; the supervisor may prefer a night-specific scale or lower cut-offs. The tier is descriptive metadata attached to the observation — it does not alter the reported temperature.

### 3.5 Monthly summary minimum

A monthly summary value (per spatial unit, per stream) is reported only when the month contains **≥ 3 days at tier `partial` or better** (`f ≥ 0.05`); otherwise the monthly value is withheld with an explicit "insufficient valid observations" state, and the valid-day count and mean coverage are still shown.

- `≥ 3` days is a candidate minimum, tunable at the consultation.
- The **arithmetic** of monthly aggregation when streams or days are missing is `METH-005`, not QA-002. QA-002 sets only the coverage/count floor for reporting a monthly value at all.

### 3.6 Spatial-unit note

All fractions in this document are lake-wide at the 0 m polygon, for illustration. The thresholds in §3.4–3.5 apply **per reporting spatial unit** (lake-wide and/or the four basins) once `SPACE-001` fixes the geometry and `AUDIT-001…010`'s shoreline-treatment choice is made. Small basins will have coarser MODIS coverage granularity; the consultation should note that a fixed `f` scale behaves differently for a basin than for the whole lake.

---

## 4. What this proposal does **not** do

- It does not set classification thresholds or thermal-status labels (`METH-004`), the climatology window or reference statistic (`METH-001`, `METH-002`), the percentile estimator or minimum historical sample count (`METH-003`), or the monthly-aggregation arithmetic (`METH-005`).
- It does not choose the lake or basin geometry or spatial units (`SPACE-001`), or the shoreline erosion treatment.
- It does not address Landsat or ERA5-Land QA (`DATA-005`, `DATA-006`).
- It does not modify or relax any completed audit (`AUDIT-001` … `AUDIT-012`) or the prototype specification. The prototype's strict rule remains the documented engineering reference; QA-002 defines the **product** acceptance rule used from Phase 3 onward.
- It does not create any application, asset, export, task, UI, or deployment.

---

## 5. Questions for the supervisor consultation (briefing section C)

1. **Accept the `lst_error ≤ 2 K` tier for the nighttime product** (candidate C or C′)? If not, confirm that Lake Balaton will have **no nighttime thermal-anomaly product** and that this is stated as a finding.
2. **Symmetric day/night rule**, or allow the daytime rule to remain stricter pending a bounded daytime QA comparison (`AUDIT-013`)?
3. **Confidence-tier cut-offs** (§3.4) — keep the proposed `f` scale, adopt a night-specific scale, or other values?
4. **Monthly minimum** — is "≥ 3 days at `partial` or better" the right floor, or stricter/looser?
5. Do the **four basins plus lake-wide** need separate coverage scales given their different MODIS granularity?

---

## 6. If approved

On explicit user approval (ideally after the consultation), the coordinator will:

1. Update the `QA-002` entry in `DECISIONS.md` to **approved**, recording the exact rule, the tier cut-offs, the monthly minimum, the daytime decision, and the approval provenance.
2. Record the transparency conditions (§3.1) as binding output requirements.
3. If a daytime diagnostic is requested, draft its bounded coordinate-free specification for separate approval before implementation.
4. Carry the approved rule and thresholds into the Phase 3 climatology / anomaly / percentile implementation, where they gate every historical and monitoring observation.
