# Lake Balaton Thermal-Anomaly Monitoring

## Status and authority

This document preserves the project scope inherited from the attached “Thesis Methodology Guidance” conversation and the governance approved on 13 August 2026. It is the shared context for future Codex tasks.

The internship proposal was sent to academic supervisor Dr. Pál Márton on 28 July 2026. On 12 August 2026, he responded: “The topic looks promising! It is suitable for completing the internship.” This constitutes academic approval of the broad internship topic as suitable. The approved concept is a GEE application extending the existing Lake Balaton application with thermal-status or anomaly interpretation, daily observations, and basin-level monthly summaries.

The supervisor’s approval does not approve all detailed methodological choices in the 13 open decisions below. Those decisions remain unresolved and subject to the project’s explicit user-approval process. The scope may be refined during the proposed consultation at the beginning of September 2026.

Established decisions below constrain implementation. Items under **Open decisions** are not approved. Any material change to an established decision, or resolution of an open scientific decision, requires explicit user approval through the main coordinator.

No GEE application has been implemented in this repository yet.

## Purpose and contribution

The internship will develop a Google Earth Engine application for satellite-derived surface-water-temperature anomalies and unusually warm observations in Lake Balaton. It must extend rather than merely reproduce the existing retrospective temperature application described by Li, Somogyi, and Tóth (2024).

The core question is:

> Is an observed lake-surface temperature unusual for the same part of the lake, season, satellite, and observation stream?

The intended contribution is multi-sensor anomaly monitoring, basin comparison, day/night context, explicit data-quality reporting, and high-resolution inspection—not simply extending the existing archive by several years.

## Established datasets and roles

| Dataset | Established role | Important constraint |
|---|---|---|
| Terra MODIS `MODIS/061/MOD11A1` | Daily morning and nighttime lake-surface-temperature observations | Compare each Terra stream only with its matching historical Terra stream |
| Aqua MODIS `MODIS/061/MYD11A1` | Daily afternoon and nighttime observations; daytime is the primary candidate for afternoon warm extremes | Compare each Aqua stream only with its matching historical Aqua stream |
| Landsat 8/9 Collection 2 Level 2 | Detailed hotspot inspection on selected clear-sky dates | The surface-temperature product is delivered on a 30 m grid, but thermal information is not an independent native 30 m measurement |
| ERA5-Land daily aggregates | Weather context such as air temperature, wind, and solar radiation | Reanalysis is contextual and must not replace observed lake-surface temperature |
| In-situ measurements, if obtained | Optional validation | Their measurement depth and timing may not match satellite skin temperature or overpass time |

Terra daytime, Aqua daytime, Terra nighttime, and Aqua nighttime are separate observation streams. They must not be directly averaged. Any combined index requires a separately proposed and approved method.

Official dataset documentation:

- [Terra MOD11A1](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD11A1)
- [Aqua MYD11A1](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MYD11A1)
- [Landsat 8 Level 2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2)
- [Landsat 9 Level 2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC09_C02_T1_L2)
- [ERA5-Land daily aggregates](https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_DAILY_AGGR)

## Established periods

- Historical reference: **1 January 2003 through 31 December 2022**.
- Monitoring: **1 January 2023 through the latest valid available observation**.
- User-explorable archive: **2003 onward**.

The reference begins in 2003 because it is the first complete calendar year shared by Terra and Aqua. A material change to any period requires user approval.

## Established analytical principles

- Compare an observation with historical conditions for the same spatial unit, seasonal period, satellite, and day/night stream.
- Report absolute temperature, anomaly in degrees Celsius, historical percentile, observation identity, and data-quality information.
- Never invent or interpolate an observation merely because cloud or QA masking leaves a date without valid satellite data.
- Report valid-water coverage and observation counts so users can judge reliability.
- Use language such as **unusually warm observation**, **extreme warm observation**, or **observed extreme thermal episode** unless a validated method supports a stronger term.
- Do not claim a formal lake heatwave without an approved, scientifically supported method for consecutive exceedances and missing daily observations. The inherited scientific starting point is the seasonally varying percentile framework described by [Hobday et al. (2016)](https://doi.org/10.1016/j.pocean.2015.12.014), but its operational adaptation remains subject to approval.

## Intended outputs

### Daily observation view

- exact valid observation date and actual observation time when available;
- lake basin or other approved spatial unit;
- satellite and day/night stream;
- observed temperature;
- historical reference value;
- anomaly and percentile;
- approved thermal-status label;
- valid-water coverage and QA information;
- an explicit no-valid-observation state when appropriate.

### Monthly summary view

- monthly mean temperature and anomaly;
- hottest valid observation date;
- maximum anomaly;
- count of observations meeting an approved warm threshold;
- valid-observation count;
- missing or cloud-obscured proportion.

### Detailed and contextual views

- Landsat 8/9 hotspot maps for selected clear-sky dates;
- comparisons among approved Lake Balaton spatial units;
- ERA5-Land weather context clearly distinguished from satellite lake-surface temperature;
- downloadable summaries with sensor, method, coverage, and QA metadata.

These are intended product requirements. Exact definitions and interface layout remain subject to the open decisions below.

## Performance strategy

The interface must not recompute the full 2003–2022 archive after every user interaction. The intended architecture is to filter early by date, sensor, and region and to reuse approved precomputed climatologies, percentiles, and basin summaries for expensive historical operations. The storage/export destination, asset schema, refresh process, and deployment approach require approval before implementation.

## Thesis–internship separation

- **MSc thesis:** historical 1978–1989 Lake Balaton sediment chemistry, spatial autocorrelation, anisotropy, variography, and interpolation.
- **Internship:** contemporary satellite-derived lake-surface-temperature monitoring and GEE application development.

The internship must not claim that current thermal observations explain the historical sediment concentrations, directly correlate the mismatched periods as if contemporaneous, or present historical sediment conditions as current.

## Six-week delivery frame

1. Audit and reproduce the existing paper, application, shared code, and data behavior.
2. Establish approved Terra/Aqua MODIS and Landsat 8/9 preprocessing and QA.
3. Implement the approved climatology, anomaly, percentile, and data-quality methods.
4. Build approved basin comparisons and daily/monthly interface outputs.
5. Validate formulas, sensor separation, clouds, coverage, shoreline pixels, consistency, and reproducibility.
6. Finalize the application, documented code, user guidance, technical report, and presentation.

Reference application context:

- Li, Somogyi, and Tóth (2024), *Exploring spatiotemporal features of surface water temperature for Lake Balaton in the 21st century based on Google Earth Engine*.
- [Published GEE application](https://lihuan.users.earthengine.app/view/balaton)
- [Shared Earth Engine repository](https://code.earthengine.google.com/?accept_repo=users/lihuan/Share_LakeBalaton)
- [Associated Zenodo record](https://zenodo.org/records/10013292)

## Collaboration and permissions

- The main Codex task coordinates work, reconciles results, and requests user decisions.
- The thermal remote-sensing researcher is read-only and separates sourced evidence, inference, recommendation, and uncertainty.
- The GEE application engineer owns implementation but may act only from an approved methodology or task specification.
- The scientific validator is read-only and reports findings rather than silently changing files.
- Independent research and validation may run in parallel. Production edits remain with one engineer.
- No agent may commit, publish, deploy, or materially expand scope without explicit user authorization.

## Open decisions requiring user approval

Before analytical implementation, decide:

1. Historical seasonal window: retain the inherited candidate of ±5 calendar days or use another window/smoother.
2. Historical reference statistic: mean, median, smoothed seasonal climatology, or another estimator.
3. Percentile estimator and minimum historical sample count per spatial unit and stream.
4. Classification thresholds and exact labels; the inherited 90th/95th-percentile scheme is a proposal, not yet an approved implementation rule.
5. Spatial units and authoritative geometries: four basins, lake-wide boundary, and whether littoral/pelagic zones belong in the six-week minimum scope.
6. Minimum valid-water coverage and other QA acceptance thresholds for daily and monthly reporting.
7. Monthly aggregation rules when Terra/Aqua streams or days are missing, including whether summaries remain stream-specific.
8. Whether any standardized multi-sensor indicator will be created; direct averaging is excluded.
9. Exact Landsat role, date-selection rules, and shoreline/mixed-pixel treatment.
10. ERA5-Land variables, temporal aggregation, and how latency will be communicated.
11. Precomputation asset/table schema, refresh cadence, ownership, and GEE deployment strategy.
12. Validation acceptance criteria and what to do if in-situ data cannot be obtained.
13. Minimum viable outputs for six weeks versus optional extensions.
