# DATA-006 proposal — ERA5-Land weather-context panel

- **Date:** 2026-09-09
- **Author:** Main Codex coordinator, for the user
- **Decision addressed:** `DATA-006` (ERA5-Land variables, temporal aggregation, and how latency
  is communicated) — `PROJECT_CONTEXT.md` open decision 10.
- **Status:** **v1 BUILT, awaiting user review.** Implemented in `app/balaton_anomaly_app.js`
  (`loadWeather`, `fillWeatherPanel`, `weatherPanel`, `utcHour`/`clock` on `STREAMS`). Also in
  this change: the four passes were **reordered to true chronological order** (Aqua pre-dawn
  first) and their time labels corrected to measured values in Hungarian clock time — see §3a.
  Not yet re-published to Earth Engine.
- **Scope basis:** `SCOPE-003` (ERA5-Land context panel is an approved extension, to come first);
  `DATA-003` (ERA5-Land is *context only* — air temperature, wind, solar radiation — and must
  never replace the observed satellite lake-surface temperature).

---

## 1. What it is

A small **"Weather — <pass>"** panel in the single-day view, below the four-pass table. It shows
the background weather over the lake, framed explicitly as context — *"not a measurement of the
water"* — to help a user understand *why* a reading was unusual (calm + sunny lets the surface
skin run hot by day and cold before dawn; wind mixes that away; cloud and cold air pull it toward
the air temperature).

It is **stream-aware**: air temperature and wind are for the **selected pass's overpass hour**,
because the four passes happen at very different times (pre-dawn ~03:00, mid-morning ~11:00,
early afternoon ~14:00, evening ~21:30 Hungarian time) and the air can differ by 5–8 °C between
them on the same date. Sunshine and rain are whole-day totals.

It is **daily-view only** for v1, a separate Earth Engine call (different collections from the
anomaly records), cached per date + pass, so the reading and pass table appear first and the
weather fills in a moment later.

## 2. Source and variables

| Panel row | Collection / band(s) | Transform | Why it matters |
|---|---|---|---|
| Air temperature **at the pass** | `ECMWF/ERA5_LAND/HOURLY` `temperature_2m` at the overpass hour | − 273.15 → °C | the primary driver; matched to when the satellite actually looked |
| Wind **at the pass** | `HOURLY` `u_/v_component_of_wind_10m` at the overpass hour | √(u²+v²) → m/s | wind mixes the warm/cold surface skin back into the bulk water |
| That day overall — sun | `DAILY_AGGR` `surface_solar_radiation_downwards_sum` | ÷ 3.6 × 10⁶ → kWh/m²/day | clear-sky heating; clear Balaton summer day ≈ 7–8, overcast winter day < 1 |
| That day overall — rain | `DAILY_AGGR` `total_precipitation_sum` | × 1000 → mm | context |
| That day overall — air range | `DAILY_AGGR` `temperature_2m_min` / `_max` | − 273.15 → °C | the day's swing |

All reduced to a **lake-area mean** over the deployed `lake_boundary` polygon at ~9 km scale.

- **Overpass hours (UTC)** used to pick the hourly image, per stream:
  `aqua_night` 01, `terra_day` 09, `aqua_day` 12, `terra_night` 20 — the mean measured MODIS
  view times over the lake (`Night_view_time` / `Day_view_time`), converted from local solar
  time to UTC.
- **Plain-language descriptors** accompany wind (`calm / light air / breezy / windy`) and sunshine
  (`very overcast / mostly cloudy / part sun / bright, mostly clear`), calibrated to the values
  ERA5-Land actually produces over this small lake.

## 3. Temporal aggregation

- **Air temperature and wind:** the single ERA5-Land **hourly** image at the pass's overpass hour
  (instantaneous — no daily averaging).
- **Sunshine and rain:** whole-day totals from `DAILY_AGGR`, labelled "that day overall".
- **Known limitation stated in the panel:** ERA5-Land is a ~9 km model grid, so wind over this
  small lake runs a little low in absolute terms (calm hours ≈ 1.5–2 m/s, blowy hours ≈ 4+).

## 3a. Pass ordering and time labels (bundled fix)

Building the stream-aware panel surfaced that the app's pass times and order were wrong:

- The **Aqua night** pass for date D is taken at ~01:30 UTC (~03:00 Hungarian clock) — the small
  hours *of* D, i.e. chronologically the **first** of the four readings, not the last. The app
  listed it 4th (grouped "day passes, then night passes"), which reads as "next day".
- The label times were rounded nominals, off by up to ~1.5 h for the night passes.

**Fixed:** `STREAM_ORDER` is now `['aqua_night','terra_day','aqua_day','terra_night']` (true
chronological order). Labels are the mean **measured** overpass times over the lake, in Hungarian
clock time (CET winter / CEST summer, ~1 h apart), and the pass table + About panel note that
"Aqua pre-dawn" is the first reading of the date, not the last. `short` names: *Aqua pre-dawn,
Terra morning, Aqua afternoon, Terra evening*.

| Pass | Local solar (MODIS) | UTC | Hungarian clock |
|---|---|---|---|
| Aqua pre-dawn | ~2.6 h | ~01:30 | ~02:30–03:30 |
| Terra morning | ~10.5 h | ~09:20 | ~10:20–11:20 |
| Aqua afternoon | ~13.6 h | ~12:20 | ~13:20–14:20 |
| Terra evening | ~21.2 h | ~20:00 | ~21:00–22:00 |

## 4. Latency

- `ECMWF/ERA5_LAND/DAILY_AGGR` in Earth Engine currently runs **about one week behind real time**
  (checked 2026-09-09: latest available date 2026-09-02).
- The satellite product itself only goes to `LAST_EXPORT_DATE` (2026-08-30) and is refreshed by
  hand roughly monthly, so in normal use ERA5-Land data exists for every date the app can show.
- If a selected date has no ERA5-Land image yet (possible for the few days between a monthly
  refresh and the ERA5-Land lag), the panel says plainly:
  *"Not available for this day yet — ERA5-Land runs about a week behind real time."*
  Dates past `LAST_EXPORT_DATE` show nothing extra (there is no satellite reading there anyway).

## 5. What v1 does **not** do (candidate v2)

- **No "vs normal" for the weather.** v1 shows the day's raw values. Showing *"air was +3 °C
  above the 2003–2022 average for this date"* would directly parallel the lake anomaly and make
  the panel far more explanatory, but needs a second Earth Engine call (a ±5-day, 20-year
  ERA5-Land climatology over the lake, cached by day-of-year). Proposed as v2.
- **No monthly weather.** The whole-month view has no weather panel yet; a monthly mean
  temperature / mean wind / total sun / total rain block is a straightforward v2 addition.
- **No auto-generated interpretation sentence** (e.g. "calm and sunny — conditions that let the
  surface warm strongly"). v1 gives the facts plus one fixed explanatory footnote; a
  data-driven sentence is deferred until the "vs normal" values exist to key it off.

## 5a. Bundled: sunshine shown season-aware, and a general text trim

- **Sunshine** is shown as **"% of a clear day"** (measured ÷ a clear-sky estimate from the
  date and the lake's latitude, FAO-56), because a raw "6 kWh/m²" is a bright winter day and a
  dull July one — the absolute number alone misled. Helper `clearSkyKwh(dstr)`.
- The **daily readout was tightened** on user feedback ("too much text, resaying things twice"):
  the percentile now appears once (next to the verdict, replacing the separate "Where it ranks"
  row); median and mean anomalies are one line; the ±5-day-window note is one short grey line;
  the coverage line is shorter. The monthly readout and the About panel were trimmed the same way.
- **"That day overall"** (sun / rain / air range) sits in its own small framed box rather than a
  long run-on sentence.

## 6. What this proposal does **not** change

- No change to `QA-002`, `METH-*`, `SPACE-001`, `VAL-001`, or the MODIS product in any way.
- ERA5-Land is never averaged, blended, or compared into the lake-surface-temperature value.
- No Earth Engine asset, export, or new deployment — one extra read-only query per selected day.

## 7. Open questions for the user

1. Is the daily-view-only, raw-values v1 enough to ship, or do you want the **"vs normal"**
   weather anomaly (v2) before it goes live?
2. Add the **monthly** weather block now or later?
3. Wind: keep the daily-mean figure with the honesty label, or drop the number and show only the
   descriptor word?
