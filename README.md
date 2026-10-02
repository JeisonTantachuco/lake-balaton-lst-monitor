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
docs/   the methods and validation report, and the user guide
```

## How the data behind the app is produced

The historical baseline (2003–2022) and the ongoing monitoring record (2023–present) are
computed once in Google Earth Engine and published as Earth Engine table assets, which
the app reads directly — the app itself never recomputes history, so it stays fast. The
monitoring record is extended by a manual refresh, not a live/automatic process. The full
methodology — how the baseline is built, the pixel quality rule, how an anomaly becomes a
percentile and a label, and the independent validation checks — is described in
[`docs/METHODS_AND_VALIDATION_REPORT.docx`](docs/METHODS_AND_VALIDATION_REPORT.docx).

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
