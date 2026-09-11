# Observed pixel artefacts: cloud-edge contamination and a likely fog signature

- **Date:** 2026-09-11
- **Author:** Main Codex coordinator, for the user
- **Status:** **Observational note — not a methodology change.** Nothing here alters `QA-002`,
  the accepted-pixel rule, or any Phase 3 output. It records two visual patterns spotted while
  reviewing the app, the evidence gathered for each, and the one product response taken (a
  fog-risk reading added to the weather panel). Intended as a discussion document for the
  academic supervisor.
- **How the evidence was gathered:** ad hoc Earth Engine queries run interactively against the
  live MODIS/ERA5-Land/ERA5 collections during this session — not saved as a script or a repo
  artefact, and no coordinates were persisted anywhere. The numbers below are the record of what
  those queries returned.

---

## 1. Cloud-edge contamination — pixels next to a data gap read too cold

### What was noticed

Looking at the single-day pixel map (e.g. **28 August 2026, Terra morning**, 67–68 % lake
coverage), the pixels immediately bordering the cloud-masked "hole" in the north-east of the lake
were visibly colder than pixels a few cells further away — a cold rim around the gap, rather than
a flat temperature right up to the mask edge.

### Why it happens

A MODIS pixel is a ~1 km footprint; a cloud edge does not line up with pixel boundaries. A pixel
that is mostly clear water but *partly* cloud can still pass NASA's cloud test (`MOD35`) as
"clear" if the contamination is below its detection threshold — especially right at a cloud's
edge, where the cloud thins out gradually rather than stopping abruptly. Cloud tops are far colder
than the lake surface, so even a small contaminating fraction pulls a pixel's apparent temperature
down. This is a documented limitation of MODIS LST products in general, not something specific to
our processing — and `QA-002`'s pixel filter runs *after* `MOD35`'s cloud decision, so it cannot
catch contamination in a pixel `MOD35` already called clear.

### Evidence — four dates checked

For each date: pixels touching a cloud-flagged gap ("near-hole") vs. pixels at least 3 cells from
any gap ("interior"), both restricted to the lake polygon, Terra-morning stream.

| Date | Lake coverage | Gap pixels | Near-hole mean | Interior mean | **Difference** |
|---|---|---|---|---|---|
| 22 Mar 2026 | 85 % | 121 | 5.36 °C | 8.41 °C | **−3.05 °C** |
| 28 Aug 2026 (NE box near Balatonfüzfő/Siófok/Balatonakarattya) | 82 % (that box) | 51 | 20.76 °C | 22.48 °C | **−1.72 °C** |
| 28 Aug 2026 (whole lake) | 68 % | — | 21.04 °C | 22.67 °C | **−1.63 °C** |
| 12 Oct 2025 | 97 % | 23 | 12.80 °C | 13.64 °C | **−0.84 °C** |
| 28 May 2026 (control — almost no cloud) | 98 % | 2 (NE box) | 22.15 °C | 21.02 °C | +1.13 °C (n too small to mean anything) |

The effect appears reliably whenever there is a **moderate, well-defined** gap (roughly 15–85 %
coverage). On very clear days there is no meaningful gap to test; on very clouded days there is
too little "interior" left far from any gap to compare against — the test becomes uninformative
at both extremes, not because the effect disappears.

### What was (and wasn't) done about it

Nothing changed in the pixel-acceptance rule. Tightening the filter to exclude "risky" pixels near
a cloud edge would shrink coverage further — and `QA-002` already rejected that trade-off once,
for the same reason (the strict rule was rejected specifically because it destroys nighttime
coverage; a shore/edge buffer would cut further into an already-thin record). This is recorded as
a known, accepted limitation, not something the product currently corrects for.

---

## 2. Pre-dawn "salt-and-pepper" pattern — a likely fog signature

### What was noticed

On **18 August 2026, Aqua pre-dawn (~02:30–03:30 Hungarian time)**, the accepted pixels didn't
form one gap with a smooth cold rim (as in Section 1) — instead, temperature jumped from pixel to
pixel with no clear spatial pattern, and coverage was very low (22 % of the lake).

### Testing three explanations

**a) Is it just noisier than a normal cloud edge?** Yes, measurably. Average difference between
neighbouring accepted pixels:

| | Mean neighbour-to-neighbour jump | Coverage |
|---|---|---|
| **18 Aug 2026, Aqua pre-dawn** | **0.97 °C** | 22 % |
| 22 Mar 2026, Terra morning (one real cloud edge, for comparison) | 0.45 °C | 85 % |

Roughly twice as jumpy — consistent with many small, scattered dropouts rather than one coherent
cloud mass with a clean edge.

**b) Is it large-scale cloud, the same as the daytime cases?** Checked against ECMWF's regional
weather model (`ECMWF/ERA5/HOURLY`, `total_cloud_cover`, ~31 km grid) for the same hour:

| | ERA5 regional cloud cover | MODIS lake coverage that pass |
|---|---|---|
| 18 Aug pre-dawn | **13 %** (model says mostly clear) | 22 % accepted |
| 22 Mar morning (−3.05 °C day) | 95 % | 85 % accepted |
| 12 Oct morning (−0.84 °C day) | 45 % | 97 % accepted |
| 28 May pre-dawn (control) | 5 % | 99 % accepted |

On the daytime cases, MODIS's exclusions track the regional cloud fraction sensibly. On 18 August
pre-dawn they don't: the weather model says the regional sky was mostly clear, yet MODIS still
rejected most of the lake. **That mismatch points away from large-scale cloud** — the model can't
be wrong by that much on a synoptic scale, so whatever MODIS is seeing is smaller than the model's
~31 km cells.

**c) Is it fog?** Fog forms when near-surface air is close to its dew point (near saturation),
typically on calm, clear nights after hours of radiative cooling — exactly the pre-dawn window.
Checked the air-temperature/dew-point gap from ERA5-Land (`ECMWF/ERA5_LAND/HOURLY`, ~9 km grid,
the same collection already used for the app's weather panel):

| Night | Air temp | Dew point | **Gap** | Wind |
|---|---|---|---|---|
| **18 Aug pre-dawn** | 19.1 °C | 16.0 °C | **3.2 °C** | 4.2 m/s |
| 28 May pre-dawn (control) | 19.8 °C | 13.2 °C | 6.6 °C | 3.0 m/s |
| 5 Aug pre-dawn (control) | 27.3 °C | 15.6 °C | 11.7 °C | 1.4 m/s |
| 25 Aug pre-dawn (control) | 21.1 °C | 11.0 °C | 10.1 °C | 2.6 m/s |

18 August's air was roughly a third as far from saturation as the three comparison nights —
a real, meaningful gap, not noise. A light breeze that night (4.2 m/s) is also enough to break a
fog layer into drifting patches rather than one smooth sheet, which would explain the "random"
pixel-to-pixel pattern rather than a clean-edged hole.

### Working conclusion

The evidence points to **shallow lake fog** at pre-dawn: small-scale, sub-pixel, broken up by a
light breeze, invisible to a regional weather model, but caught (correctly, if noisily) by
MODIS's own thermal cloud test. This is a hypothesis supported by three independent lines of
evidence (pixel roughness, the ERA5-vs-MODIS mismatch, and the dew-point gap), not a certainty —
a single satellite snapshot can't fully confirm it.

### Product response

Added a **fog-risk reading to the weather panel** — the air-temperature-minus-dew-point gap, at
the same ~9 km resolution already used for the rest of the panel, shown for every pass (it is the
one weather signal that means something at night, since sunshine requires daylight to be
meaningful at all). Bands (`< 2.5 °C` fog likely, `< 5 °C` fog possible, else unlikely) are set
directly from the spread measured above. No change to the pixel-acceptance rule or to any Phase 3
output.

---

## 3. Open questions for the supervisor

1. Is there a standard technique in the LST literature for handling cloud-edge contamination
   (e.g. a documented buffer distance around a cloud mask) that would be worth citing, even if not
   adopted here?
2. Does published or local knowledge of Balaton's microclimate support or contradict the pre-dawn
   fog hypothesis — is lake fog a known, common occurrence there?
3. Is this worth a dedicated, systematic investigation (e.g. sweeping every pre-dawn pass for a
   season and correlating dew-point gap against coverage) as a small side-study, or is documenting
   it as a known, accepted limitation sufficient for this internship's scope?
