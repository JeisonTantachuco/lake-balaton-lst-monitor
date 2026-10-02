# Lake Balaton Surface-Temperature Monitor

A satellite-based tool that answers one question, every day: **is Lake Balaton's water
surface unusually warm or cold right now, compared to what's normal for this exact time
of year?**

**Live app:** https://jtantaroman.users.earthengine.app/view/lake-balaton-lst-monitor

---

## What it does

- Reads surface temperature from NASA's **Terra and Aqua MODIS** instruments, four
  separate daily passes (pre-dawn, mid-morning, early afternoon, evening), from January
  2023 to the present.
- Compares each reading against a fixed **2003–2022 historical baseline** for the same
  time of year, and reports how unusual it is as a percentile and a plain-language label
  (e.g. "warm", "unusually warm").
- Keeps the four daily passes **separate, never averaged together** — the lake behaves
  differently at 3 a.m. than at 2 p.m., and merging them would hide that.
- Flags, for every reading, how much of the lake was actually seen clearly that pass
  (cloud cover varies day to day), so a reading built from a handful of pixels is never
  presented as equivalent to one built from the whole lake.
- Shows **ERA5-Land weather reanalysis** (air temperature, wind, sunshine, fog risk) as
  context for interpreting a reading — never as a replacement for the satellite
  measurement itself.

The full methodology, validation results and known limitations are in
[`docs/METHODS_AND_VALIDATION_REPORT.docx`](docs/METHODS_AND_VALIDATION_REPORT.docx);
a guide to using the app itself is in
[`docs/USER_GUIDE.docx`](docs/USER_GUIDE.docx).

## Repository layout

```
app/    the Earth Engine App source (balaton_anomaly_app.js) — what runs at the live URL
tools/  the Python data pipeline: builds the historical baseline, computes daily/monthly
        anomaly records, and the independent validation checks
docs/   the methods and validation report, and the user guide
```

## How the pipeline works

1. **Baseline** — `tools/run_anomaly_engine_ee.py --build-climatology` computes one
   lake-average temperature per day for every day 2003–2022 (one line of code calling
   Earth Engine, not a download), for each of the four satellite passes, then derives a
   ±5-day-window historical baseline (median, mean, and full sample) for every calendar
   day.
2. **Monitoring** — `--daily-records` computes each new day's reading against that
   baseline (anomaly, percentile, confidence label) and rolls them up into monthly
   summaries. This is run by hand roughly monthly to extend the record; it does not run
   automatically.
3. **Export** — `--export-assets` publishes the baseline and the monitoring records as
   Earth Engine table assets, which the app reads directly — the app itself never
   recomputes history, so it stays fast.
4. **Validation** — `tools/run_validation_offline.py` and `tools/run_validation_ee.py`
   independently check the method: physical plausibility, cross-stream consistency,
   agreement with an independent satellite instrument (Landsat) and a reanalysis model,
   corroboration against published European climate bulletins, and robustness to
   reasonable method variations (window width, stricter cloud filtering, shoreline
   treatment).

Every script supports `--self-test` (no Earth Engine, no network) to check its own logic
before running against live data.

## Data sources

- **MODIS Terra/Aqua Land Surface Temperature** (`MOD11A1` / `MYD11A1`, Collection 6.1) — NASA/USGS, via Google Earth Engine.
- **ERA5-Land reanalysis** — ECMWF/Copernicus Climate Change Service, via Google Earth Engine.
- **Landsat Collection 2 Level-2** and **Copernicus Climate Change Service climate bulletins** — used only as independent checks during validation, not as part of the live product.

## Status

Internship project, actively developed. Validated for **relative anomaly monitoring**
(is this reading unusual?) — not for absolute, degree-precise calibration. Known
limitations and open questions are documented in
[`docs/METHODS_AND_VALIDATION_REPORT.docx`](docs/METHODS_AND_VALIDATION_REPORT.docx).

## Author

Jeison Tantachuco — internship project, Lake Balaton thermal monitoring.
