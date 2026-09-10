# Why We Did What We Did — Lake Balaton Thermal Monitoring, Explained Plainly

This document exists for one reason: so that **you** can look at any choice this project
made — the historical period, the cloud filter, the lake boundary, the median-vs-mean
question, the app's design — and understand *why* it's the right choice, in your own
words, without needing to decode internal jargon.

Every section below answers three questions: **what did we choose, what were the real
alternatives, and why is our choice the correct one for what this project is trying to
do.** Where a choice is formally recorded, I give its code (e.g. `METH-002`) in
parentheses so you can look up the full, formal wording in `DECISIONS.md` if you ever
need the paper trail — but you should never need to read that file to understand the
reasoning. This document is the reasoning.

A short glossary is at the very end if any statistics term is unfamiliar.

---

## 1. What this project actually is

You're building a tool that answers one question, every day, for Lake Balaton:
**"is the water surface unusually warm (or cold) right now, compared to what's normal
for this exact time of year?"**

That single question drives almost every decision below, because answering it honestly
requires being very careful about what "normal" means, what counts as a trustworthy
measurement, and how to say "warmer than normal" without hiding uncertainty or
overselling the result. (`SCI-001`)

---

## 2. Where the temperature numbers come from

**Choice:** NASA's MODIS instruments on two satellites — **Terra** (crosses Balaton
mid-morning and again in the evening) and **Aqua** (crosses in the pre-dawn hours and
again in the early afternoon). Four passes in all. Each is a *separate* measurement
stream. (`DATA-001`)

**The four passes and when they happen** (Hungarian clock time; winter is about an hour
earlier), in the order they fall on a date:

| Pass | Roughly | Note |
|---|---|---|
| Aqua — pre-dawn | ~03:00 | taken in the small hours *of* that date, so it is the **first** of the four, not the last |
| Terra — mid-morning | ~11:00 | |
| Aqua — early afternoon | ~14:00 | usually the warmest |
| Terra — evening | ~21:30 | |

**Why these two satellites, and why keep them separate:** they're the only sensors that
give a long, consistent, multi-times-daily record of the lake's actual surface temperature
going back over 20 years. Pre-dawn, morning, afternoon and evening conditions are
physically different things — a lake heats up during the day and cools overnight, so mixing
"how warm was it at 2 pm" with "how warm was it at 3 am" into one number would hide the
real signal rather than reveal it. Section 8 explains this in more depth.

**Two more data sources are approved for *later*, not yet built into the app:**
- **Landsat** (`DATA-002`) — sharper images (30 m instead of MODIS's 1 km) for zooming
  into a specific hot day, once the core product is finished.
- **ERA5-Land weather reanalysis** (`DATA-003`) — air temperature, wind, sunlight, as
  *context* for interpreting a reading, never as a replacement for the actual satellite
  measurement.
- **Any field/in-situ temperature measurements**, if ever obtained, would only be used as
  an optional cross-check (`DATA-004`), since a thermometer in the water measures
  something subtly different from what a satellite sees from orbit (see the glossary:
  *skin temperature*).

---

## 3. Defining "normal": why the historical baseline is fixed at 2003–2022

This is the question you asked directly, so here it is in full, because it's one of the
most important design choices in the whole project. (`TIME-001`)

**Choice:** one "normal" is worked out **once**, from **1 Jan 2003 through 31 Dec 2022**
(20 full years), and it **never changes**. Every day from 1 Jan 2023 onward — including
today, and every day after this internship ends — is compared against that exact same,
frozen reference. It's a fixed ruler, not one that gets redrawn every year.

**2003 specifically** is the first full calendar year where *both* Terra and Aqua were
already up and running, so it's the earliest point where all four measurement streams
(morning, afternoon, two nighttime passes) have a complete, comparable record.

**Why not let the baseline grow every year, so 2026 is judged against 2003–2025?**
That was your first alternative. The problem: 2024, for instance, turned out to be the
warmest year on record for every single satellite pass (see the Phase 3 results). If you
fold 2024's heat into the "normal" used to judge 2026, you are quietly using an
already-warm year to raise the bar for what counts as warm — so real long-term warming
gets partly absorbed into "normal" instead of being detected. This effect has a name in
climate science: **shifting baseline**. It's a well-documented way of accidentally hiding
a trend you're trying to measure. There's a second, more mechanical problem too: 2023
would be judged against 20 years of history, 2026 against 23 years — different sample
sizes, so you could no longer honestly say "2026 was more anomalous than 2023," because
they were measured with two different rulers.

**Why not use a rolling window instead — always the trailing 20 years, so 2026 is judged
against 2006–2025?** That was your second alternative, and it's a real technique used
elsewhere, but it has the same core flaw in a subtler form: the window keeps sliding
forward, always dropping the oldest (typically cooler) years and adding the newest
(typically warmer) ones, so the "normal" keeps drifting upward right alongside the real
warming. That's the right tool for a different question — "was last month unusual
compared to recent experience" — but the wrong tool for this project's actual question,
which is "is the lake trending warmer compared to an untouched past."

**Why the fixed baseline is the scientifically correct choice for this project, not just
a preference:** this exact pattern — one fixed multi-decade reference period, deliberately
never updated year-to-year — is how meteorological agencies define "climate normals"
(the WMO uses fixed 30-year windows, only redefined once per decade). It's fixed on
purpose so that:
1. **Every monitoring year is judged by the same ruler**, so anomalies are honestly
   comparable across years.
2. **A real warming trend stays visible** instead of being chased and absorbed by a
   moving reference.
3. **The statistics behind every percentile stay stable and well-defined** (see Section
   7), instead of the sample size growing every year and making year-to-year comparisons
   apples-to-oranges.

If the baseline is ever updated in the future, the correct way to do it is a deliberate,
periodic redefinition (e.g. once a full new decade of data exists) — never something
that creeps forward every single year.

---

## 4. Deciding which satellite readings to trust (the cloud/quality filter)

**The problem:** clouds, thin haze, and edge-of-lake pixels can make a MODIS pixel report
a temperature that isn't really the lake's surface. Every MODIS pixel comes with quality
flags, and the strictest possible reading of those flags is the "textbook safe" choice.
But that strict rule turned out to be unworkable for this specific lake.

This section is longer than the others because it's the part people ask about most —
*"why does the daily map have holes in it?"* The short answer: most holes are clouds that
NASA removed before we ever saw the data, and the rest are pixels we chose not to trust.
The rest of this section is that answer in slow motion.

### 4.1 The picture you're actually working with

Each satellite pass is **one snapshot**, taken in about 5 minutes as the satellite flies
over Hungary — not a blended or "best of the day" picture. Whatever the sky is doing in
those 5 minutes is what you get. There's no waiting for a better moment.

*Example:* if a band of cloud is drifting across the western basin at 10:02 when Terra
passes, the western basin is missing from that day's Terra-morning image — even if it was
perfectly clear an hour earlier.

- **Plain:** one photo per satellite per pass, ~5 minutes, not a composite.
- **Formal:** the `MOD11A1` (Terra) / `MYD11A1` (Aqua) daily 1 km LST product — one
  instantaneous overpass per satellite per day, *not* a temporal composite.

### 4.2 Clouds are removed before we ever see the data

Before this project touches anything, NASA has already run its own cloud detector on the
image. Any pixel it judges cloudy is left **blank** — NASA doesn't even try to compute a
temperature there. So **most holes in the daily map are simply "there was a cloud here,"
decided upstream, not by us.**

*Example:* on a day with scattered fair-weather cumulus you get a Swiss-cheese pattern —
many small blank dots. On a day with a weather front you get a clean diagonal edge: clear
on one side, blank on the other.

- **Plain:** cloudy pixels never arrive with a number attached.
- **Formal:** NASA's `MOD35` cloud mask, applied upstream. In the pixel's quality byte
  this appears as **mandatory QA = 2** — *"LST not produced due to cloud."* A related
  code, **mandatory QA = 3**, means *"not produced for another reason"* (thin cloud,
  aerosol, a missing atmospheric-correction input) — also blank, also not our decision.

### 4.3 The four-grade report card on every surviving pixel

For the pixels that *do* come with a temperature, MODIS attaches a one-byte "report card"
carrying four separate grades. Each grade is a small number from 0 (best) to 3 (worst):

| Report-card grade | Plain-language question it answers | Formal field |
|---|---|---|
| **Was a value produced, and roughly how good?** | "Did the photo come out at all?" | `mandatory_qa` |
| **Solid retrieval or a shaky one?** | "Is it in focus?" | `data_quality` |
| **Do we know what this surface is made of?** | "Did we guess the material right — open water vs. reed vs. mud?" | `emissivity_error` |
| **How many degrees might we be off?** | "±1 K? ±2 K? ±3 K?" | `lst_error` |

All four grades are packed into a single 8-bit number, which is why the code uses
bit-shifting (`bitwiseAnd`, `rightShift`) — that's just unpacking the four grades back
out of the one byte.

**What "emissivity error" means, since it's the least obvious one:** MODIS never measures
temperature directly. It measures **how much thermal infrared light the surface is glowing
with**, then converts that glow into a temperature. That conversion needs one assumption —
**how efficiently does this surface radiate?** — and that efficiency is called
*emissivity*. Water radiates very efficiently and very *consistently* (about 0.99), so
MODIS's assumption for open water is almost always right. Reed beds, wet mud and dry shore
soil each radiate differently, and MODIS has to guess which one it's looking at from a
land-cover map. The `emissivity_error` grade is MODIS saying *"how sure am I that I used
the right radiating efficiency here?"* For Balaton this is the **least** worrying of the
four grades — most of our pixels are clean open water — but it's exactly the grade that
degrades along the shoreline, where a pixel is half water, half reed.

- **Plain:** in focus, right material, small degree-error.
- **Formal:** the `QC_Day` / `QC_Night` science dataset, decoded into `data_quality`,
  `emissivity_error`, `lst_error`.

### 4.4 Our own sanity checks

On top of MODIS's report card we add three cheap "is the housekeeping intact" checks —
these mostly catch fill values and corrupt metadata, not bad weather:

- **raw temperature value** in a physically possible range (rejects the fill value 0 and
  impossible numbers) — formally, raw DN in `[7500, 65535]`.
- **overpass time present and sane** — formally, view time in `[0, 240]`.
- **viewing angle present and sane** — formally, view angle in `[0, 130]`. This one also
  carries real meaning: a pixel seen from the far edge of the satellite's swath is viewed
  through a long slanted slice of atmosphere and its footprint is smeared larger, so an
  extreme angle is genuinely lower quality. Our rule just checks the angle is present and
  in range rather than penalising oblique views directly.

### 4.5 The pass mark we set — and why not stricter

MODIS grades each pixel; **we** decide which grades we'll accept. Our rule keeps a pixel
only if it has a real temperature (not cloud, not "failed for another reason"), the
retrieval is **in focus** (best `data_quality`), the material is known to within ~2%
(`emissivity_error` at best-or-second-best), the reading is accurate to **within about
2 K** (`lst_error` at best-or-second-best), and the three housekeeping checks pass.
Everything else we discard — which turns it into a hole on *our* map even though MODIS
gave us a number.

**Why not demand a perfect reading?** Because it was tested (`AUDIT-011`, `AUDIT-012`):
with the strictest possible rule (every grade must be 0 — "within 1 K", "material known
to within 1%"), **Lake Balaton has essentially zero usable nighttime readings** — 0%
coverage, every single night, for an entire year of test dates. Allowing the "within 2 K"
tier recovers about **99% nighttime coverage**, and almost every one of those recovered
pixels carries the *exact same* quality code:

- **Formal:** at night, **98.7%** of valid-water pixels have quality byte **65**, which
  decodes to `mandatory_qa = 1` (produced, flagged for a closer look) / `data_quality = 0`
  (good) / `emissivity_error = 0` (≤ 0.02) / `lst_error = 1` (≤ 2 K). The accepted rule
  ("candidate C") is: `mandatory_qa ≤ 1 AND data_quality == 0 AND emissivity_error ≤ 1
  AND lst_error ≤ 1`, plus the provider-range validity checks from §4.4.

The rule is applied **identically to day and night** (`QA-002`). Daytime pixels already
clear the strict bar easily, so using the same rule for both costs daytime nothing, and
one rule is simpler to explain and audit than two.

**Why loosen it instead of just accepting "no nighttime data"?** Nighttime lake
temperature is scientifically important — it's often where the most interesting anomalies
show up (the Phase 3 report: February 2024 nights were +5.1°C above normal). Reporting
"no data, forever, every night" would make the whole nighttime half of the product
useless for no real gain in accuracy — the discarded pixels aren't actually bad
measurements, they just don't meet an overly strict paperwork threshold.

### 4.6 The kinds of holes, with an everyday example for each

| What you see on the map | Everyday cause | Formal category |
|---|---|---|
| Big blank regions, clean edges | Thick cloud over that part of the lake | `mandatory_qa == 2` (upstream, dominant) |
| Blank patches on a "clear-looking" day | Thin haze / aerosol / a missing correction input — NASA couldn't retrieve | `mandatory_qa == 3` |
| The lake cut off along one straight line | The satellite's swath edge clipped the lake, or there was no pass at all that day | no / partial overpass |
| Scattered single missing pixels on an otherwise full lake | Individual pixels we rejected as too noisy | fails `data_quality` / `emissivity_error` / `lst_error` (~1% at night) |
| Rare stray gaps | Missing quality byte, or a fill value in the temperature/time/angle | missing QC / provider-range failure |

### 4.7 What the leftover pixels produce — and the honesty flag

We average **whatever accepted pixels remain** into that pass's lake temperature — even
if only a handful survived. Then we label how much of the lake we actually saw:

- saw **0 pixels** → *"no reading"* (`none`)
- saw **less than 15%** of the lake (under ~100 of ~700 lake pixels) → **`low`
  coverage**, the value is still shown but marked with a warning (the `*` in the app)
- saw **15% or more** → shown normally (`ok`)

*Example:* an August Terra-evening pass with only 25 clear pixels out of ~700 → 3.6% of
the lake → a temperature is still reported, but flagged `low`, because 3.6% of the lake
isn't really "the lake."

- **Plain:** a number is always produced if even one pixel survives; the flag tells you
  how much of the lake stood behind it.
- **Formal:** `valid_water_fraction` = accepted pixels ÷ ~700; tiers `none` / `low`
  (`< 0.15`) / `ok`. Night passes are *structurally* low here — averaging only ~10% of
  the lake even on good nights — which is why the `*` appears so often on the pre-dawn and
  evening rows.

**The honesty condition that comes with all of this:** every nighttime reading in the
underlying data explicitly carries what coverage the strict rule *would* have given, so
nothing is hidden — a future user or reviewer can always see exactly how much looser this
rule is than the textbook one.

---

## 5. What area counts as "the lake"

**Choice (`SPACE-001`):** the whole lake, as **one single polygon** — no basin
subdivision (Keszthely / Szigliget / Szemes / Siófok), and **no inward shrinking** of the
shoreline (0 m buffer).

**Why not split into basins?** Because there's no official, agreed-upon Hungarian basin
boundary to use — this was checked directly with the academic supervisor, who couldn't
point to one either. Inventing a boundary (e.g. "just draw lines at the narrow points")
would be a real scientific choice requiring its own justification, and there wasn't time
to do that properly in a six-week internship. So it's documented as a legitimate future
extension, not silently skipped.

**Why not shrink the shoreline inward, to avoid "mixed" pixels that are part-land,
part-water?** This was actually tested (`AUDIT-001`/`AUDIT-012`) across four different
shrink distances (0 m, 463 m, 500 m, 927 m). Shrinking inward *reduces* the
already-scarce nighttime coverage further (by about 1–1.5 percentage points), and Lake
Balaton is narrow enough that aggressive shrinking would cut out entire cross-sections of
open water. Crucially, because this is an **anomaly** product (today vs. the 20-year
normal for the same pixels), any land-mixing bias in a shoreline pixel is present in
*both* the historical baseline and today's reading — so it mostly cancels out rather than
biasing the anomaly number. If a validation check later finds a specific artifact (e.g. an
unrealistic daytime warm bias near the shore), this choice will be revisited — it isn't
locked in forever, just currently the best-evidenced option.

---

## 6. How a single day's anomaly number is actually built

For one satellite pass, on one day, three numbers get compared:

1. **What was actually measured today** (the clear-sky pixels over the lake, averaged).
2. **What's "typical" for this calendar day**, computed from history.
3. **The difference between them** — the anomaly.

**The historical "typical" value (`METH-001`):** built from every year 2003–2022, using
not just the exact same calendar day but a **±5-day window** around it (e.g. for 19
February, every 14–24 February from 2003 through 2022). This was checked directly
(`AUDIT-013`): at ±5 days, essentially every calendar day of the year has a full 20 years
of history behind it and 110–195 individual daily readings feeding the statistic — a
solid, reliable sample. A single exact calendar day alone (no window) would have far
fewer data points and be noisier; a much wider window (e.g. ±15 days) would start
blending genuinely different parts of the season together. ±5 days was the point that
gave a robust sample without blurring the season.

**Median vs. mean — which "typical" value, and why both are computed (`METH-002`):**
you asked this directly too, and it's worth spelling out. The **median** — literally
"half of past years were warmer, half were cooler, on this kind of day" — is the
**headline** number the app leads with. The **mean** (plain average) is also computed and
shown, but as a secondary reference, not the headline. Why median first: a plain average
gets pulled around by occasional bad points (thin cloud edges, mixed pixels) and by
skewed distributions — and the Phase 3 data confirmed Balaton's nighttime readings *are*
skewed (a long cold tail), enough that the median sits up to 2.6°C *above* the mean on
about 60% of the year. If the mean were used as the headline, nighttime anomalies would
read systematically "too warm" simply due to that statistical skew, not due to anything
actually happening at the lake. The mean is still reported because a big gap between the
median and the mean is itself a useful signal — it tells you that particular day's history
is unusually skewed, worth a second look.

**The sign / direction (also asked directly):**

> **anomaly = today's measured temperature − the historical value (median or mean)**

A **positive** number means today was **warmer** than normal; **negative** means
**colder**. This is why the app now writes it out explicitly as "+6.1°C warmer than
normal" with a sub-line spelling out "measured minus the 2003–2022 median for 13 April
±5 days," rather than a bare, ambiguous "anomaly vs. median: 6.1°C."

---

## 7. Turning the anomaly into a percentile and a plain-language label

A raw °C difference doesn't tell you how *unusual* it is on its own — "+2°C" could be
completely ordinary in one season and remarkable in another. So the app also works out
**where today's reading ranks** among all the historical readings for that time of year.

**Choice (`METH-003`):** a standard statistical method (called "Type 7") ranks today's
value against the full historical sample for that ±5-day window (the same 110–195
readings from Section 6). The result is a **percentile** — e.g. "warmer than 92% of
historical readings for this time of year." Because Balaton's real sample sizes (110–195)
are always comfortably large, a set of minimum-sample-size safety rules exist in the
method (e.g. "don't report a percentile from fewer than 10 historical readings") purely
as a guardrail for an unusual data gap — in practice, on the current lake-wide product,
they essentially never trigger.

**Turning a percentile into one label (`METH-004`):** exactly **one** plain-language
label per reading, chosen from: *below normal, within normal range, warm, unusually
warm, extreme warm observation* — based on which percentile band the reading falls into
(below the 10th percentile, 10th–90th, 90th–95th, 95th–99th, above 99th). Deliberately
**not** called a "heatwave" or "thermal event" (`TERM-001`) unless a properly validated
method for detecting sustained multi-day events is built and approved — a single warm day
is not the same scientific claim as a persistent heatwave, and the wording is chosen to
never overstate what one day's reading can support.

**The label is a hard cut, so the app also shows the percentile.** Validation (`VAL-001`,
Section 11) found that about 7 % of well-observed days sit right on a band boundary — e.g.
at the 94.8th percentile, one notch below the "unusually warm" line. A small, legitimate
change to the method (a ±3-day window instead of ±5) can nudge such a day across, flipping
its word-label even though its temperature barely moved. It is always a *single* notch,
never a jump. To keep the label from reading as a hard fact, the app now prints the
percentile next to it ("95th percentile · unusually warm"), so a borderline reading looks
borderline. The bands themselves (`METH-004`) were not changed.

---

## 8. Why the four satellite passes are never merged into one number

**Choice (`METH-006`):** Aqua-pre-dawn, Terra-morning, Aqua-afternoon and Terra-evening
are always shown **side by side**, each with its own temperature, its own anomaly, its own
percentile, and its own label. There is **no** single combined "the lake's temperature
today" number.

**Why not average them together?** They aren't measuring the same thing. A lake's surface
genuinely warms through the day and cools at night — a mild, unremarkable afternoon and a
genuinely unusual, warm night are two different physical stories, and averaging them
would blur both. Keeping them separate is also simply more honest about what each
satellite pass can and can't tell you. A combined, carefully-designed index is listed as
a possible *future* extension, but only if it can be built without hiding this distinction
— not for this six-week core product.

---

## 9. How monthly summaries are built

**Choice (`METH-005`):** a month's summary (mean temperature, mean anomaly, warmest
day, biggest single-day jump, count of "warm-or-above" days) is computed **per satellite
pass** (never merging streams, for the same reason as Section 8) and **only from days
that already passed the quality-confidence check in Section 4** at `low` or better.

**The minimum-data rule:** a month needs **at least 3 qualifying days** before it reports
a summary at all; otherwise it explicitly says "insufficient valid observations" rather
than quietly computing a number from, say, one lucky clear day. Nothing is ever filled in
or guessed for a missing day (`QA-001`) — a cloudy month just has fewer data points behind
its summary, visibly.

---

## 10. Building the public app (Phase 4) — and why it looks the way it does

The scientific method above (Sections 3–9) is what the app *shows*; a separate set of
engineering/UX decisions were made about *how* it shows it, refined directly from your
feedback while testing it:

- **The app reads pre-computed results, it never recalculates 20 years of history live**
  (`PERF-001`, `ARCH-001`) — otherwise every click would be painfully slow. The
  climatology baseline (Section 3) is computed once and stored as a permanent Earth
  Engine table; only new days/months get appended over time, in a manual monthly refresh.
- **A calendar-style date picker**, not a slider showing raw numbers, because that's a far
  more natural way to jump to a specific day — with the underlying recalculation
  deliberately **debounced** so quickly scrubbing through many days triggers one
  calculation at the end, not one per day passed over.
- **The whole-month view uses its own Month selector**, separate from the daily
  calendar, because every day inside one month gives the *same* monthly summary — there
  was no reason to force a day-level choice onto a month-level question.
- **Client-side caching by month and by year**: once a month's (or year's) data has been
  fetched from Earth Engine, browsing within that same month/year re-uses it instantly
  instead of re-querying — only the actual satellite image on the map still needs a fresh
  request per day, since that's a genuinely different picture every time.
- **The temperature color scale on the map is fixed** (−5°C to 32°C), not rescaled to
  each day's own min/max — otherwise a mild day and a genuinely extreme day would look
  equally "red," which would visually lie about how unusual a reading actually is. The
  small legend bar in the corner *is* cropped to show only the slice of that fixed scale
  the current view actually occupies (so you can see at a glance whether today's colors
  sit near the cold end, the warm end, or the pale middle of the full range) — but the
  colors themselves are never renormalized.
- **All internal decision codes (`METH-006`, `QA-002`, etc.) were deliberately stripped
  from the user-facing app text** — they're useful for this document and for `DECISIONS.md`,
  but meaningless to anyone opening the public app, so the app instead explains things in
  the same plain language used throughout this document.
- **The classification label always appears with its percentile next to it**, and the
  four-pass table shows, for every pass, what share of the lake that pass actually saw —
  both added after validation (Section 11) so a reading near a threshold, or one built
  from thin coverage, is visibly so rather than presented as a clean fact.
- **The four passes are shown in the order they actually happen** — Aqua pre-dawn (~03:00
  Hungarian time, the *first* reading of the date, not the last), Terra mid-morning
  (~11:00), Aqua early afternoon (~14:00), Terra evening (~21:30). Times are the mean
  measured overpass times over the lake, in Hungarian clock time (an hour earlier in
  winter); the old labels were rounded nominals and off by up to ~1.5 h.
- **A "Weather" panel** (single-day view) shows the ERA5-Land reanalysis conditions for
  the selected pass — air temperature and wind at the overpass hour, plus the whole day's
  sunshine and rain. It is context to help explain *why* a reading was unusual (calm and
  sunny lets the surface skin run hot or, before dawn, cold; wind mixes it away; cloud and
  cold air pull it toward the air). It is **never** a measurement of the water and never
  replaces the satellite value (`DATA-003`). Sunshine is shown as **"% of a clear day"**
  (see the glossary) so it is comparable between a dull July day and a bright February one.

---

## 11. How the product was validated (`VAL-001`)

No thermometer-in-the-water (in-situ) data for Lake Balaton was available, so the product
was checked seven other ways (full detail in `docs/PHASE_5_VALIDATION_REPORT.md`). All
seven passed, and `VAL-001` was **approved in September 2026**.

- **It behaves like a real lake.** The 2003–2022 "normal" is a smooth annual cycle — near
  0 °C in winter, ~24 °C in July — and daytime is warmer than night in summer for every
  satellite. The four passes agree with each other where physics says they should
  (correlation ≥ 0.98).
- **An independent instrument agrees with it.** Our monthly averages were compared against
  **Landsat** surface temperature — a *different* thermal sensor — for every month from
  2003 to 2024 (258 months). The two agree to within about **0.5 °C on average** and move
  together at **99 % correlation**. A weather model (ERA5-Land) tracks it too. (Landsat and
  ERA5-Land were used here only as measuring sticks — they are not part of the product;
  that would be `DATA-005` / `DATA-006` below.)
- **The flagged anomalies match the official record.** Every standout the product found —
  February 2024, March 2024, summer 2024, 2024 as the warmest year — lines up with the
  Copernicus Climate Change Service's European climate bulletins.
- **The result doesn't depend on arbitrary choices.** Re-running with a ±3 or ±7-day
  window instead of ±5, or a stricter pixel filter, or a trimmed shoreline, moves the
  anomaly by only a fraction of a degree.
- **The coverage flag works.** Every one of the ~200 wild single-day spikes built from a
  handful of cloud-gap pixels is correctly marked "low coverage".

**What the product is validated *for*:** telling you whether a reading is unusual for its
time of year, and how much to trust it — a *relative* claim. It is **not** calibrated to
give the exact temperature to a fraction of a degree; that would need in-situ data.

**Documented limitations that travel with it:** about 7 % of well-observed days sit right
on a percentile boundary, so their word-label ("warm" vs "unusually warm") could tip
either way — which is why the app now shows the percentile number next to the label. A
handful of borderline-coverage days (0.25 % of the record) are flagged for a manual look.
And the strict pixel filter, tested here, is confirmed to be the wrong choice for this
lake — exactly as `QA-002` decided.

---

## 11b. What's still open, and what's explicitly future work

Being upfront about what this project does *not* yet claim:

- **The ERA5-Land weather panel** (`DATA-006`) is now **built** (v1 — see Section 10 and
  `docs/DATA_006_PROPOSAL.md`); a "vs normal" weather comparison and a monthly weather
  block are the obvious next additions.
- **Landsat hotspot inspection** (`DATA-005`) is still an approved *extension*, not started
  — sharper 30 m thermal images to zoom into a specific hot day. (Section 11 used Landsat
  only to *check* the product; this would build it in as a feature.)
- **Basin-level (not whole-lake) results, littoral/pelagic zones, and any multi-day
  "heatwave" detector** are documented as legitimate future work, explicitly not claimed
  now, because the geometry or the validated method they'd need doesn't exist yet.
- **This internship's satellite-temperature work is scientifically separate from your
  MSc thesis** (1978–1989 sediment chemistry) — the two must never be presented as
  explaining each other or as covering the same time period (`SCOPE-001`).

---

## 12. Quick glossary

- **Anomaly** — how far today's measurement is from what's "typical" for that time of
  year (measured minus typical; positive = warmer than normal).
- **Median** — the middle value of a sorted list (half above, half below). Robust to a
  few extreme/bad readings.
- **Mean** — the plain average. Sensitive to extreme values and to a skewed distribution.
- **Percentile** — where a value ranks among a historical group, from 0 (coldest on
  record) to 100 (warmest on record).
- **Skin temperature** — what a satellite thermal sensor actually measures: the very
  top, sub-millimeter surface layer. It can differ slightly from a thermometer dipped a
  few centimeters into the water (in-situ measurement), which is why the two aren't
  treated as interchangeable.
- **QC / quality flags** — extra information a satellite product ships alongside every
  pixel, describing how trustworthy that specific pixel's reading is (e.g. was it
  cloud-free, was the sensor viewing at a bad angle). In MODIS LST this is a single byte
  packing four 0–3 grades: `mandatory_qa`, `data_quality`, `emissivity_error`,
  `lst_error` (see Section 4.3).
- **Emissivity** — how efficiently a surface radiates thermal infrared light compared to
  a perfect radiator (which would be 1.0). A satellite measures the *glow*, then needs an
  assumed emissivity to turn that glow into a temperature. Water's emissivity is high
  (~0.99) and very stable, so it's well known; mixed land/water shoreline pixels are
  where the assumption gets shaky. `emissivity_error` is MODIS's own estimate of that
  uncertainty.
- **LST** — Land Surface Temperature; for a lake, the temperature of the water *skin*
  (see *skin temperature*). MODIS's daily products are `MOD11A1` (Terra) and `MYD11A1`
  (Aqua).
- **Coverage / valid-water fraction** — the share of the lake's ~700 pixels that gave an
  accepted reading on a given pass. Drives the `none` / `low` / `ok` confidence flag.
- **"% of a clear day"** (weather panel, sunshine) — the day's measured solar energy at
  the ground (from ERA5-Land) divided by the *cloudless maximum* for that date and the
  lake's latitude, then ×100. The cloudless maximum is calculated, not measured: from Sun
  geometry (latitude + day of year → energy at the top of the atmosphere over the day),
  then × 0.75 for what a clean, cloudless atmosphere lets through — the standard FAO-56
  clear-sky formula. So "74%" means clouds blocked about a quarter of the available
  sunshine that day. Comparable across seasons, unlike the raw kWh/m². Clamped to 100 % in
  the app (a genuinely clear day can compute a little over). Rough by ±a few %, not a
  measurement.
- **Shifting baseline** — the problem where a reference ("normal") that keeps updating
  itself with recent, already-changed conditions gradually hides the very change you're
  trying to measure.

---

## 13. Where the formal paper trail lives

Every decision above has a fuller, formally-worded twin entry in `DECISIONS.md` at the
repository root, identified by the code shown in parentheses throughout this document
(e.g. `METH-002`, `QA-002`, `ARCH-001`). That file is the authoritative, dated,
approval-tracked register — the version a supervisor or examiner would want to audit.
This document is the same set of decisions, explained so *you* can confidently explain
them yourself, in your own words, to anyone who asks.
