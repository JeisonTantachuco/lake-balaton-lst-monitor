# First MODIS Preprocessing Prototype Specification

## Status and authority

- **Status:** Approved for the first implementation prototype.
- **Specification date:** 2026-08-16.
- **Purpose:** Define the smallest non-UI diagnostic prototype needed to verify four-stream MODIS ingestion, scaling, QA decoding, observation timing, area accounting, missingness, and schema consistency.
- **Implementation authority:** Limited to the prototype and tests explicitly described here and assigned by the coordinator.
- **Scientific authority:** Prototype diagnostics only. This specification does not establish the final scientific QA method, water mask, coverage threshold, climatology, anomaly method, percentile method, classification system, or monthly aggregation method.

The prototype must not create permanent Earth Engine assets, exports, interfaces, deployments, or application folders beyond the implementation and test files explicitly assigned in a later approved task.

## 1. Objectives

The prototype must:

1. Process Terra daytime, Terra nighttime, Aqua daytime, and Aqua nighttime as four separate observation streams.
2. Use one common processing contract and one common output schema for all four streams.
3. Apply the documented MODIS scale factors.
4. Decode all four QA components contained in the day/night QC byte.
5. Preserve QA evidence before applying LST or ancillary-band masks.
6. Retain the source UTC product date and actual per-pixel local-solar view-time metadata.
7. Calculate fixed eligible ROI area, accepted area, and an accepted-area fraction.
8. Expose provisional eligible-water and valid-water aliases only under the explicit test assumption that the entire provisional ROI is open water.
9. Represent accepted clear-sky retrievals, cloud, rejected QA, non-cloud no-retrieval, missing QC, duplicate-source, and no-source-image cases explicitly.
10. Emit one typed diagnostic row for every expected date and stream, including null rows.
11. Avoid interpolation, gap filling, stream combination, and silent mosaicking.

## 2. Explicitly excluded scope

The prototype must not contain:

- user-interface code;
- application deployment;
- Earth Engine asset creation;
- permanent exports;
- climatology;
- anomalies;
- percentiles;
- thermal-status labels;
- formal heatwave detection;
- monthly aggregation;
- a combined multi-sensor indicator;
- authoritative lake or basin geometries;
- permanent water masks;
- permanent coverage thresholds;
- Landsat processing;
- ERA5-Land processing;
- automated refresh;
- production monitoring logic.

## 3. Official datasets and stream configuration

### 3.1 Collections

| Platform | Collection |
|---|---|
| Terra | `MODIS/061/MOD11A1` |
| Aqua | `MODIS/061/MYD11A1` |

Official documentation:

- [Terra MOD11A1.061](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD11A1)
- [Aqua MYD11A1.061](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MYD11A1)
- [MOD11 Collection 6.1 User Guide](https://lpdaac.usgs.gov/documents/715/MOD11_User_Guide_V61.pdf)

The products are daily Level-3 gridded products on the MODIS sinusoidal grid. The nominal Earth Engine pixel size is 1,000 m; the underlying 1 km MODIS grid is approximately 0.928 km by 0.928 km.

### 3.2 Stream-to-band mapping

| Stream ID | Platform | Phase | LST band | QC band | View-time band | View-angle band | Clear-coverage band |
|---|---|---|---|---|---|---|---|
| `terra_day` | Terra | day | `LST_Day_1km` | `QC_Day` | `Day_view_time` | `Day_view_angle` | `Clear_day_cov` |
| `terra_night` | Terra | night | `LST_Night_1km` | `QC_Night` | `Night_view_time` | `Night_view_angle` | `Clear_night_cov` |
| `aqua_day` | Aqua | day | `LST_Day_1km` | `QC_Day` | `Day_view_time` | `Day_view_angle` | `Clear_day_cov` |
| `aqua_night` | Aqua | night | `LST_Night_1km` | `QC_Night` | `Night_view_time` | `Night_view_angle` | `Clear_night_cov` |

The NASA HDF documentation abbreviates the angle-band suffix as `angl` in some tables. The exact Earth Engine identifiers used here end in `_angle`.

### 3.3 Scale factors, offsets, and raw ranges

#### Lake-surface temperature

- Documented raw range: `7500–65535`
- Fill value: `0`
- Kelvin:

  `temperature_k = raw_lst × 0.02`

- Celsius:

  `temperature_c = raw_lst × 0.02 − 273.15`

No additional physical-plausibility threshold is approved for this prototype. The documented provider range must be followed and unusual converted values retained diagnostically rather than silently removed.

#### View time

- Documented raw range: `0–240`
- Fill value: `255`
- Unit: local solar hour
- Conversion:

  `view_time_local_solar_hour = raw_view_time × 0.1`

View time must not be presented as a unique satellite overpass timestamp. The product is a daily gridded Level-3 result, and official descriptions differ on how multiple qualifying observations above 30° latitude are selected or combined.

#### View angle

- Documented raw range: `0–130`
- Fill value: `255`
- Unit: degrees
- Conversion:

  `view_angle_degrees = raw_view_angle − 65`

Negative values indicate viewing from the east; magnitude represents view zenith angle.

#### Clear-sky coverage diagnostic

- Documented raw range: `1–65535`
- Fill value: `0`
- Conversion:

  `clear_coverage_scaled = raw_clear_coverage × 0.0005`

`Clear_day_cov` and `Clear_night_cov` must remain uninterpreted unitless diagnostics. They must not be described or used as:

- percent;
- probability;
- a 0–1 fraction;
- a water mask;
- eligible-water area;
- valid-water coverage;
- a QA acceptance threshold.

## 4. Provisional date fixture

Use the half-open UTC product-date interval:

- **Start, inclusive:** `2024-07-01`
- **End, exclusive:** `2024-07-15`

This gives:

- 14 expected UTC product dates;
- 4 separate streams per date;
- exactly 56 expected diagnostic rows.

This interval is a short, reproducible summer fixture within the approved monitoring era. It is not claimed to contain every diagnostic state naturally. Synthetic fixtures must cover states absent from the natural interval.

The source image/product date remains `date_utc`. The prototype must not construct a local observation date or datetime from the UTC product date and local-solar view time. A local-solar calendar day may differ from the UTC product date, and no rollover rule has been approved.

## 5. Provisional test geometry

### 5.1 Definition

Use:

- **Geometry ID:** `szemesi_station_250m_v0`
- **Center longitude:** `17.7498611`
- **Center latitude:** `46.8516944`
- **Radius:** `250 m`
- **Construction:**

  `ee.Geometry.Point([17.7498611, 46.8516944]).buffer(250)`

- **Geodesic:** yes

The coordinate was normalized from a published Szemesi-basin sampling station reported as:

`46°50′66.1″ N, 17°44′59.5″ E`

with a reported depth of 3.5 m.

Source: [Blix et al. (2018)](https://doi.org/10.3390/w10101428).

### 5.2 Required caveats

The source latitude uses noncanonical arc seconds. Normalizing `46°50′66.1″` produces `46.8516944°`.

Before implementation use, the point must be visually checked against current imagery and the normalization must be documented.

This geometry is:

- a provisional presumed-open-water engineering fixture;
- not an authoritative Lake Balaton boundary;
- not an authoritative basin geometry;
- not a permanent water mask;
- not a 250 m-resolution thermal measurement;
- not suitable for station-scale validation;
- not sufficient to validate application-grade basin or lake water coverage.

At MODIS resolution, the ROI intersects fractional portions of one or a few native grid cells whose complete footprints extend beyond the 250 m circle.

## 6. Eligible area and provisional water-area semantics

### 6.1 Authoritative prototype denominator

Calculate:

`eligible_roi_area_m2`

as the pixel-area-weighted intersection of the fixed ROI with the exact native MODIS sinusoidal grid.

Requirements:

- use the exact source LST-band CRS and affine transform;
- use `ee.Image.pixelArea()`;
- use the fixed geometry;
- use no LST, QC, cloud, clear-sky, or date-dependent mask;
- set `bestEffort: false`;
- record the CRS, transform, reducer parameters, and resampling policy;
- keep the denominator constant within each stream across all dates;
- compare denominators among the four streams and report any difference.

Before date iteration, resolve one canonical native projection for each stream by sorting the configured collection by `system:time_start` and selecting the first image deterministically. Record:

- `projection_reference_image_id`;
- the selected LST band's CRS;
- the selected LST band's six-element affine transform.

This canonical projection must remain available when a particular date has no source image. For every exactly-one-source row, the selected source LST band's CRS and six-element affine transform must equal the stream's canonical values before processing. A mismatch is a hard validation error: do not silently reproject, resample, or compute scientific diagnostics. The projection-reference image or configuration identifier must be part of versioned provenance.

Calculate `geometry_area_m2` once as the geodesic vector area of the fixed 250 m ROI, using a maximum geometry error of 1 m, and copy it to every row. It does not depend on a raster grid or source mask.

Calculate `eligible_roi_area_m2` as the pixel-area-weighted raster integration of that ROI in the stream's canonical MODIS CRS and affine transform, and copy it to every row for that stream. It may differ from `geometry_area_m2` because it is grid-based. Neither field is an authoritative Lake Balaton water area; their difference is a rasterization diagnostic.

Calculate:

`accepted_area_m2`

from the pixels meeting the strict prototype acceptance rule.

Calculate:

`accepted_roi_fraction = accepted_area_m2 / eligible_roi_area_m2`

No minimum accepted fraction is imposed.

### 6.2 Provisional water aliases required by the prototype brief

Because the ROI is provisionally assumed to be entirely open water, the schema may also expose:

- `provisional_eligible_water_area_m2`
- `provisional_valid_water_area_m2`
- `provisional_valid_water_coverage_fraction`

with:

- `provisional_eligible_water_area_m2 = eligible_roi_area_m2`
- `provisional_valid_water_area_m2 = accepted_area_m2`
- `provisional_valid_water_coverage_fraction = accepted_roi_fraction`

Every such field must include or inherit:

`water_area_semantics = "provisional_geometry_proxy_not_authoritative_water_mask"`

These aliases are engineering diagnostics only. They must not be reported as validated Lake Balaton water coverage and do not resolve `SPACE-001` or `QA-002`.

### 6.3 Counts

Area is authoritative for the prototype.

Any count must state its semantics explicitly. Preferred names include:

- `qc_observed_pixel_center_count`
- `accepted_pixel_center_count`
- `cloud_pixel_center_count`
- `produced_rejected_pixel_center_count`

An ordinary unweighted count generally represents pixel centers included by the reducer, not every native grid cell geometrically intersecting the ROI. A positive area with a zero pixel-center count is therefore possible for the 250 m fixture and is not automatically an error.

## 7. QA-bit decoding

Let the unsigned raw QC byte be `q`.

Decode:

- `mandatory_qa = q & 3`
- `data_quality = (q >> 2) & 3`
- `emissivity_error = (q >> 4) & 3`
- `lst_error = (q >> 6) & 3`

### 7.1 Mandatory QA, bits 0–1

| Code | Meaning |
|---:|---|
| 0 | LST produced, good quality |
| 1 | LST produced, other quality; inspect detailed QA |
| 2 | LST not produced due to cloud |
| 3 | LST not produced primarily for a non-cloud reason |

### 7.2 Data quality, bits 2–3

| Code | Meaning |
|---:|---|
| 0 | Good data quality |
| 1 | Other quality |
| 2 | To be determined |
| 3 | To be determined |

### 7.3 Emissivity error, bits 4–5

| Code | Meaning |
|---:|---|
| 0 | Average emissivity error ≤ 0.01 |
| 1 | Average emissivity error ≤ 0.02 |
| 2 | Average emissivity error ≤ 0.04 |
| 3 | Average emissivity error > 0.04 |

### 7.4 LST error, bits 6–7

| Code | Meaning |
|---:|---|
| 0 | Average LST error ≤ 1 K |
| 1 | Average LST error ≤ 2 K |
| 2 | Average LST error ≤ 3 K |
| 3 | Average LST error > 3 K |

## 8. QA diagnostic and acceptance rules

### 8.1 Mask ordering

QA diagnostics must be computed from the QC band using the QC band’s own valid mask.

The implementation must not first intersect QC with the LST, view-time, view-angle, or clear-coverage masks. Doing so could erase cloud and no-retrieval evidence.

`Clear_*_cov` must never gate acceptance.

### 8.2 Strict prototype acceptance rule

A pixel is accepted only if all the following are true:

1. `LST_*_1km` is unmasked.
2. `QC_*` is unmasked.
3. `*_view_time` is unmasked.
4. `*_view_angle` is unmasked.
5. Raw LST is in `7500–65535`, inclusive.
6. Raw view time is in `0–240`, inclusive.
7. Raw view angle is in `0–130`, inclusive.
8. `mandatory_qa == 0`.
9. `data_quality == 0`.
10. `emissivity_error == 0`.
11. `lst_error == 0`.

Equivalently, the decoded QC byte must be zero and every required measurement/ancillary value must be present and within its documented raw range.

This is an intentionally strict engineering rule. It is not approved as the final scientific QA rule.

### 8.3 Disjoint diagnostic areas

All logical masks must be total, unmasked Boolean images over the eligible mask `E`. Derive every band-validity predicate from that band's mask and documented raw range, then unmask the predicate to `false` within `E`. Gate every QC comparison with `Q`; never apply a comparison to a missing QC value.

Define:

- `E`: the fixed eligible ROI mask in the canonical stream grid;
- `Q`: QC is unmasked;
- `L`: LST is unmasked and raw LST is in `7500–65535`, inclusive;
- `Vt`: view time is unmasked and raw view time is in `0–240`, inclusive;
- `Va`: view angle is unmasked and raw view angle is in `0–130`, inclusive.

Then define the total, disjoint diagnostic masks:

- `produced_lst = E && Q && (mandatory_qa == 0 || mandatory_qa == 1) && L`
- `accepted = produced_lst && Vt && Va && mandatory_qa == 0 && data_quality == 0 && emissivity_error == 0 && lst_error == 0`
- `produced_rejected = produced_lst && !accepted`
- `cloud = E && Q && mandatory_qa == 2`
- `noncloud_no_retrieval = E && Q && !produced_lst && mandatory_qa != 2`
- `missing_qc = E && !Q`

These five category masks must be mutually exclusive and exhaustive over `E`. Calculate their areas using `ee.Image.pixelArea()` in one reduction with identical geometry, canonical CRS, canonical affine transform, and reducer settings.

Define:

- `produced_lst_area_m2 = accepted_area_m2 + produced_rejected_area_m2`, within the tolerance below;
- `area_partition_sum_m2 = accepted_area_m2 + produced_rejected_area_m2 + cloud_area_m2 + noncloud_no_retrieval_area_m2 + missing_qc_area_m2`;
- `area_partition_residual_m2 = eligible_roi_area_m2 - area_partition_sum_m2`;
- `area_partition_absolute_error_m2 = abs(area_partition_residual_m2)`;
- `area_partition_relative_error = area_partition_absolute_error_m2 / eligible_roi_area_m2` when `eligible_roi_area_m2 > 0`, otherwise null;
- `area_partition_tolerance_m2 = max(1.0, eligible_roi_area_m2 × 0.000001)`;
- `area_partition_pass = eligible_roi_area_m2 > 0 && area_partition_absolute_error_m2 <= area_partition_tolerance_m2`;
- `unclassified_area_m2 = max(area_partition_residual_m2, 0)`;
- `overlap_excess_area_m2 = max(-area_partition_residual_m2, 0)`.

The tolerance is a reproducible engineering audit threshold, not a scientific uncertainty, a universal Earth Engine numerical bound, or permission for logical gaps and overlaps. Exact synthetic Boolean-membership tests must independently establish disjointness and exhaustiveness. A residual above tolerance is a validation error.

Partition metrics apply only when exactly one source image exists and `eligible_roi_area_m2 > 0`. For source count zero or greater than one, all partition metrics are null. For an exactly-one-source row with `eligible_roi_area_m2 <= 0`, all partition metrics, including `area_partition_pass`, are null and a hard validation error is emitted.

### 8.4 QA histograms

For each row, retain:

- the raw QC-byte histogram for values 0–255;
- four-bin count and area histograms for `mandatory_qa`;
- four-bin count and area histograms for `data_quality`;
- four-bin count and area histograms for `emissivity_error`;
- four-bin count and area histograms for `lst_error`.

Histograms must be computed over the QC-observed area, not only accepted pixels. Count histograms must use an explicitly unweighted pixel-center frequency reducer and must be cast to integer-valued outputs. Area histograms must sum `ee.Image.pixelArea()` by code using the same canonical projection and geometry.

The serialization convention must be deterministic and versioned as specified in Section 11.10.

## 9. Row-state rules

### 9.1 Source-image cardinality

For each UTC product date and stream:

- source image count `0`: emit a null diagnostic row;
- source image count `1`: process normally;
- source image count greater than `1`: fail validation for that date-stream key.

Duplicate images must not be mosaicked, averaged, or silently reduced.

### 9.2 Mutually exclusive primary states

Apply this precedence:

1. `NO_SOURCE_IMAGE`
   - Source image count is zero.

2. `DUPLICATE_SOURCE_IMAGES`
   - Source image count is greater than one.
   - This is a hard validation failure, not a scientific result.

3. `ACCEPTED`
   - Accepted area is greater than zero.

4. `SOURCE_PRESENT_REJECTED_QA`
   - Accepted area is zero;
   - but a produced/retrieved LST area is present.

5. `SOURCE_PRESENT_CLOUD`
   - Accepted area is zero;
   - cloud area is greater than zero;
   - non-cloud no-retrieval area is zero;
   - and no produced/retrieved LST area is present.

6. `SOURCE_PRESENT_NO_RETRIEVAL`
   - All remaining single-source, source-present cases.

Each row must also include:

- `has_cloud`
- `has_rejected_qa`
- `has_noncloud_no_retrieval`
- `has_missing_qc`
- `failure_reason_count`
- `has_mixed_failure_reasons`

The primary state must not erase mixed diagnostic causes.

For exactly-one-source rows, define:

- `has_cloud = cloud_area_m2 > 0`;
- `has_rejected_qa = produced_rejected_area_m2 > 0`;
- `has_noncloud_no_retrieval = noncloud_no_retrieval_area_m2 > 0`;
- `has_missing_qc = missing_qc_area_m2 > 0`;
- `failure_reason_count = int(has_cloud) + int(has_rejected_qa) + int(has_noncloud_no_retrieval) + int(has_missing_qc)`;
- `has_mixed_failure_reasons = failure_reason_count >= 2`.

`unclassified_area_m2`, `overlap_excess_area_m2`, and a failed area partition are accounting or validation diagnostics, not observational failure reasons, and must not affect `failure_reason_count` or `has_mixed_failure_reasons`. A failed partition must instead appear in `validation_errors`.

For `NO_SOURCE_IMAGE` and `DUPLICATE_SOURCE_IMAGES`, all six fields above are null because observational reasons were not evaluated.

### 9.3 Required explicit cases

The schema therefore represents:

- **clear/accepted:** `ACCEPTED`;
- **cloudy:** `SOURCE_PRESENT_CLOUD` or `has_cloud = true`;
- **rejected:** `SOURCE_PRESENT_REJECTED_QA` or `has_rejected_qa = true`;
- **no observation:** `NO_SOURCE_IMAGE`;
- **source but no usable retrieval:** `SOURCE_PRESENT_NO_RETRIEVAL`;
- **invalid duplicate source:** `DUPLICATE_SOURCE_IMAGES`.

## 10. Processing functions

The implementation should expose the following logical functions. Exact filenames and language structure will be assigned separately.

### 10.1 `getStreamConfigurations()`

Returns the four immutable stream configurations containing:

- stream ID;
- platform;
- phase;
- collection ID;
- LST band;
- QC band;
- view-time band;
- view-angle band;
- clear-coverage band;
- scale/offset metadata.

### 10.2 `buildExpectedDateStreamKeys(start, end, streamConfigs)`

Creates the complete expected key grid before accessing source imagery.

Output:

- 14 UTC dates;
- 4 streams;
- 56 unique keys.

This expected-key grid ensures missing source images still produce rows.

### 10.3 `selectSourceImage(dateUtc, streamConfig)`

Filters the configured collection using a one-day half-open UTC interval:

`[dateUtc, dateUtc + 1 day)`

Returns:

- source image count;
- image identity if exactly one exists;
- validation error metadata if more than one exists.

It must not mosaic duplicate results.

### 10.4 `decodeQc(qcBand)`

Produces integer diagnostic bands for:

- `mandatory_qa`;
- `data_quality`;
- `emissivity_error`;
- `lst_error`.

The QC band’s original mask must be preserved for QA-observed and missing-QC accounting.

### 10.5 `buildDiagnosticMasks(image, streamConfig)`

Builds disjoint masks for:

- accepted;
- produced but rejected;
- cloud;
- non-cloud no retrieval;
- missing or unknown QC;
- residual/unclassified area.

QA masks must be developed before any common-band mask is applied.

### 10.6 `convertPhysicalBands(image, streamConfig)`

Produces:

- temperature K;
- temperature °C;
- local-solar view time in hours;
- signed view angle in degrees;
- uninterpreted scaled clear-coverage diagnostic.

Raw values must remain available for validation.

### 10.7 `summarizeDateStream(dateUtc, streamConfig, geometry)`

Produces exactly one typed output feature using:

- the fixed geometry;
- the source band’s exact native CRS and transform;
- area-weighted reductions;
- `bestEffort: false`;
- documented reducer parameters.

### 10.8 `classifyRowState(summary)`

Applies the source-cardinality and row-state precedence rules without changing diagnostic counts or areas.

### 10.9 `runPrototypeDiagnostics()`

Generates:

- the 56-row natural diagnostic collection;
- validation summaries;
- schema-consistency results;
- test failures.

It must not call `Export.*`, create assets, deploy an app, or construct UI widgets.

## 11. Uniform diagnostic output schema

Every expected row must contain the same fields and types. Missing scientific values must be typed nulls, never zero-filled or interpolated.

Normative logical types are:

- `string`;
- `int64`;
- `float64`;
- `boolean`;
- `list<string>`;
- `list<float64>[6]`;
- `list<int64>[4]`;
- `list<float64>[4]`;
- `list<int64>[256]`.

`nullable<T>` means that the property must remain present with value null when it is not applicable. Numeric fields must never contain `NaN` or infinity. Zero is permitted only for an evaluated, measured zero; it must not stand for unavailable or unprocessed data.

A **nonprocessed row** has source image count zero or greater than one. For nonprocessed rows:

- key, configuration, geometry, and canonical-projection fields remain populated;
- row state, source count, validation diagnostics, and provenance remain populated;
- all source-dependent scientific areas, fractions, counts, statistics, histograms, partition metrics, `failure_reason_count`, and observational flags are null.

Exactly-one-source rows follow the field types and nullability below.

| Field group | Normative type and nullability |
|---|---|
| Schema, rule, specification, implementation, geometry, and histogram versions | `string` |
| `run_timestamp_utc` | RFC 3339 UTC `string` |
| `date_utc` | ISO `YYYY-MM-DD` `string` |
| Stream, platform, phase, collection, and band identifiers | `string` |
| `projection_reference_image_id` | `string` |
| `source_image_count` | `int64` |
| `source_image_id` | `nullable<string>` |
| `source_system_time_start` | `nullable<int64>` epoch milliseconds |
| `source_image_ids_if_duplicate` | nonnull, lexicographically sorted `list<string>`; empty unless duplicate |
| Geometry identifiers, status, citation, and normalization note | `string` |
| `geometry_area_m2`, `eligible_roi_area_m2`, and `provisional_eligible_water_area_m2` | nonnull `float64` |
| `source_crs` | `string` |
| `source_crs_transform`, `reducer_scale_or_transform` | `list<float64>[6]` |
| `nominal_scale_m` | `float64` |
| `best_effort` | `boolean` |
| `resampling_policy` | `string` |
| Source-dependent area, fraction, and partition fields | `nullable<float64>` |
| Source-dependent pixel-center counts | `nullable<int64>` |
| Temperature, view-time, view-angle, and clear-coverage statistics | `nullable<float64>` |
| `provider_numeric_range_only` | `boolean` |
| View-time, clear-coverage, and water-area semantics | `string` |
| QA and component count histograms | `nullable<list<int64>[256]>` or `nullable<list<int64>[4]>`, as specified |
| Component area histograms | `nullable<list<float64>[4]>` |
| `row_state`, `state_reason` | `string` |
| Observational flags and `area_partition_pass` | `nullable<boolean>` |
| `failure_reason_count` | `nullable<int64>` |
| `null_reason`, `notes` | `nullable<string>` |
| `validation_errors`, `validation_warnings` | nonnull, sorted, unique `list<string>` |

`reducer_scale_or_transform` is always the recorded six-element affine transform used by the reducer; it is never a scalar scale value.

### 11.1 Identity and provenance

- `schema_version`
- `rule_version`
- `specification_version`
- `implementation_version_or_hash`
- `run_timestamp_utc`
- `date_utc`
- `stream_id`
- `platform`
- `phase`
- `collection_id`
- `lst_band`
- `qc_band`
- `view_time_band`
- `view_angle_band`
- `clear_coverage_band`
- `projection_reference_image_id`
- `source_image_count`
- `source_image_id`
- `source_system_time_start`
- `source_image_ids_if_duplicate`

### 11.2 Geometry and projection

- `geometry_id`
- `geometry_status`
- `geometry_source_citation`
- `geometry_coordinate_normalization_note`
- `geometry_area_m2`
- `source_crs`
- `source_crs_transform`
- `nominal_scale_m`
- `reducer_scale_or_transform`
- `best_effort`
- `resampling_policy`

### 11.3 Eligible and provisional water-area fields

- `eligible_roi_area_m2`
- `accepted_roi_fraction`
- `provisional_eligible_water_area_m2`
- `provisional_valid_water_area_m2`
- `provisional_valid_water_coverage_fraction`
- `water_area_semantics`

### 11.4 Diagnostic areas

- `qc_observed_area_m2`
- `produced_lst_area_m2`
- `accepted_area_m2`
- `produced_rejected_area_m2`
- `cloud_area_m2`
- `noncloud_no_retrieval_area_m2`
- `missing_qc_area_m2`
- `unclassified_area_m2`
- `overlap_excess_area_m2`
- `area_partition_sum_m2`
- `area_partition_residual_m2`
- `area_partition_absolute_error_m2`
- `area_partition_relative_error`
- `area_partition_tolerance_m2`
- `area_partition_pass`

### 11.5 Diagnostic counts

Counts must use names that identify their inclusion semantics:

- `eligible_pixel_center_count`
- `qc_observed_pixel_center_count`
- `produced_lst_pixel_center_count`
- `accepted_pixel_center_count`
- `produced_rejected_pixel_center_count`
- `cloud_pixel_center_count`
- `noncloud_no_retrieval_pixel_center_count`
- `missing_qc_pixel_center_count`

### 11.6 Temperature statistics for accepted pixels

- `temperature_k_mean`
- `temperature_k_min`
- `temperature_k_max`
- `temperature_c_mean`
- `temperature_c_min`
- `temperature_c_max`
- `provider_numeric_range_only`

No additional physical-temperature rejection threshold is applied.

### 11.7 View-time statistics for accepted pixels

- `view_time_basis = "local_solar_hour"`
- `view_time_local_solar_hour_area_weighted_mean`
- `view_time_local_solar_hour_min`
- `view_time_local_solar_hour_max`

No local datetime is constructed.

### 11.8 View-angle statistics for accepted pixels

- `view_angle_degrees_area_weighted_mean`
- `view_angle_degrees_min`
- `view_angle_degrees_max`

### 11.9 Clear-coverage diagnostics

- `clear_coverage_semantics = "scaled_unitless_uninterpreted"`
- `clear_coverage_scaled_mean`
- `clear_coverage_scaled_min`
- `clear_coverage_scaled_max`

### 11.10 QA histograms

- `qc_byte_histogram`
- `mandatory_qa_count_histogram`
- `mandatory_qa_area_histogram_m2`
- `data_quality_count_histogram`
- `data_quality_area_histogram_m2`
- `emissivity_error_count_histogram`
- `emissivity_error_area_histogram_m2`
- `lst_error_count_histogram`
- `lst_error_area_histogram_m2`
- `histogram_serialization_version`

Use `histogram_serialization_version = "fixed_index_array_v1"`.

- `qc_byte_histogram` is `list<int64>[256]`; array index equals raw QC byte `0–255`.
- Each component count histogram is `list<int64>[4]`; array index equals decoded component code `0–3`.
- Each component area histogram is `list<float64>[4]`; array index equals decoded component code `0–3`.
- Dictionaries and implementation-dependent key ordering are forbidden in output rows.
- All histogram arrays are null for nonprocessed rows.
- All-zero histogram arrays are permitted only for an exactly-one-source row with measured `qc_observed_area_m2 == 0`; they must never represent a nonprocessed row.
- The sum of `qc_byte_histogram` and of every component count histogram must equal `qc_observed_pixel_center_count` exactly.
- The sum of every component area histogram must equal `qc_observed_area_m2` within `area_partition_tolerance_m2`.

### 11.11 State and diagnostics

- `row_state`
- `state_reason`
- `has_cloud`
- `has_rejected_qa`
- `has_noncloud_no_retrieval`
- `has_missing_qc`
- `failure_reason_count`
- `has_mixed_failure_reasons`
- `null_reason`
- `validation_errors`
- `validation_warnings`
- `notes`

## 12. Test cases

### 12.1 Configuration and key-grid tests

1. Exactly four stream configurations exist.
2. Terra streams use only `MODIS/061/MOD11A1`.
3. Aqua streams use only `MODIS/061/MYD11A1`.
4. Day and night bands match the configuration table.
5. The half-open date range contains exactly 14 UTC dates.
6. The expected key grid contains exactly 56 unique date-stream keys.
7. No cross-stream averaging, joining, or combination occurs.
8. Every stream resolves and records a deterministic `projection_reference_image_id`.
9. Every exactly-one-source LST band matches its stream's canonical CRS and six-element affine transform.
10. A projection mismatch produces a hard validation error, no silent reprojection or resampling, and no scientific diagnostics.

### 12.2 Scale and offset tests

Synthetic values must verify:

- LST raw `15000` → `300 K` → `26.85 °C`.
- View-time raw `135` → `13.5 local solar hours`.
- View-angle raw `0` → `−65°`.
- View-angle raw `65` → `0°`.
- View-angle raw `130` → `+65°`.
- Clear-coverage raw `2000` → scaled diagnostic `1.0`, without describing that value as 100%.

The documented maximum LST raw value must also be tested:

- raw `65535` → `1310.70 K` → `1037.55 °C`.

The test must confirm that the provider-range-only rule retains this synthetic value if QA and required ancillary values pass, while emitting an explicit warning that no physical-plausibility threshold is applied.

### 12.3 Exhaustive QA extraction test

For every unsigned byte value `q = 0–255`:

- verify all four extraction formulas;
- verify each two-bit component takes values `0–3`;
- verify each component code occurs exactly 64 times;
- verify strict acceptance occurs only for `q == 0`, assuming other requirements pass.

### 12.4 State fixtures

Use synthetic images when natural dates do not provide a deterministic case.

Required fixtures:

1. **Accepted**
   - Source count one;
   - QC byte zero;
   - valid LST, view time, and view angle.

2. **Cloud**
   - Source count one;
   - mandatory QA code two;
   - no valid LST required.

3. **Rejected QA**
   - Source count one;
   - produced LST;
   - one or more decoded QC components nonzero.

4. **No source image**
   - Empty filtered collection;
   - output row retained with source count zero and typed null scientific values.

5. **Source present, no retrieval**
   - Source exists;
   - no accepted or produced LST area;
   - cloud is not the sole cause.

6. **Missing QC**
   - Eligible area with absent QC evidence;
   - missing-QC area retained rather than dropped.

7. **Duplicate source**
   - Source count greater than one;
   - hard validation failure;
   - no mosaic or scientific result.

8. **Mixed failure**
   - Cloud and non-cloud rejection reasons coexist;
   - primary state follows precedence;
   - all reason areas and mixed-reason flag remain visible.

9. **Projection mismatch**
   - Source count one;
   - selected LST-band CRS or affine transform differs from the canonical stream projection;
   - hard validation error;
   - no reprojection, resampling, or scientific diagnostics.

10. **Nonpositive eligible area**
    - Source count one;
    - `eligible_roi_area_m2 <= 0` is forced synthetically;
    - partition metrics, including `area_partition_pass`, are null;
    - a hard validation error is emitted.

### 12.5 Area and coverage tests

1. `eligible_roi_area_m2 > 0`.
2. The denominator is constant across all dates within a stream.
3. Differences among streams are measured and explained.
4. Every reason area is nonnegative.
5. `accepted_area_m2 <= eligible_roi_area_m2`.
6. `0 <= accepted_roi_fraction <= 1`.
7. The provisional water aliases equal the corresponding ROI fields.
8. The water-semantics warning is present in every row.
9. Cloud and rejected masks change only numerator/reason areas, never the denominator.
10. Every logical predicate is total and unmasked over `E`; missing band evidence evaluates to false in its validity predicate.
11. Exact synthetic Boolean-membership tests prove the five category masks mutually exclusive and exhaustive over `E`.
12. `produced_lst_area_m2` equals `accepted_area_m2 + produced_rejected_area_m2` within `area_partition_tolerance_m2`.
13. `area_partition_residual_m2` equals `eligible_roi_area_m2 - area_partition_sum_m2`.
14. Absolute and relative partition errors follow the formulas in Section 8.3, and relative error is null when eligible area is nonpositive.
15. `area_partition_tolerance_m2` equals `max(1.0, eligible_roi_area_m2 × 0.000001)` exactly.
16. `area_partition_pass` is true if and only if eligible area is positive and absolute error is no greater than tolerance.
17. Residual above tolerance appears in `validation_errors`.
18. Partition residual, unclassified area, and overlap excess do not affect `failure_reason_count` or `has_mixed_failure_reasons`.
19. Count histograms use unweighted pixel-center frequencies and integer values.
20. Each QC/component count-histogram sum equals `qc_observed_pixel_center_count` exactly.
21. Each component area-histogram sum equals `qc_observed_area_m2` within `area_partition_tolerance_m2`.
22. Pixel-center counts are not assumed to equal intersecting-cell counts.
23. `bestEffort` is false.
24. Exact CRS, six-element affine transform, reducer settings, and projection-reference identifier are recorded.

### 12.6 Mask-order tests

1. QC histograms are computed on the QC band’s own mask.
2. Cloud QC evidence remains observable where LST is masked, when the product exposes it.
3. Common-band acceptance masking does not alter raw QA histograms.
4. If the product masks QC evidence for a condition, the area is classified as missing/unknown rather than falsely assigned.
5. Natural-product masking behavior is documented for all four streams.

### 12.7 Time tests

1. Source `date_utc` remains unchanged.
2. Local-solar view-time statistics remain separate from UTC date.
3. No local observation date or datetime is constructed.
4. Day and night view-time bands are never exchanged.
5. View-time fill value `255` is rejected.
6. The audit records the official ambiguity concerning multiple qualifying daily observations above 30° latitude.

### 12.8 Null and schema tests

1. All 56 natural rows share the exact same field set.
2. Corresponding fields have consistent types across all streams.
3. No-source and no-retrieval rows contain typed null scientific statistics.
4. Missing observations are never represented as zero temperature or zero view time.
5. No row is silently omitted.
6. Histogram serialization is deterministic.
7. Every row includes schema, rule, implementation, and geometry versions.
8. No numeric field contains `NaN` or infinity.
9. Nonprocessed rows follow the exact null contract in Section 11.
10. All-zero histogram arrays occur only for exactly-one-source rows with measured zero QC-observed area.
11. Histogram arrays have exact lengths 256 or 4 and use the fixed-index serialization.
12. Duplicate-image identifiers and validation lists are sorted deterministically; validation lists contain unique values.
13. `source_crs_transform` and `reducer_scale_or_transform` are each six-element float arrays, never scalar values.
14. Projection-reference provenance and all schema/version fields are populated on every row.

### 12.9 Scope tests

The prototype fails scope validation if it contains:

- UI widgets;
- map panels;
- charts;
- `Export.*`;
- asset creation;
- deployment logic;
- climatology;
- anomaly calculations;
- percentiles;
- classification labels;
- monthly summaries;
- Landsat;
- ERA5-Land;
- cross-stream combination.

## 13. Acceptance criteria

The prototype is accepted only if:

1. It produces exactly 56 unique natural diagnostic rows.
2. It uses the correct collection and band mapping for every stream.
3. All four streams execute through the same generic processing contract.
4. Stream outputs have identical typed schemas.
5. All scale/offset tests pass.
6. Exhaustive QC extraction for `0–255` passes.
7. QA diagnostics are computed before common-band masking.
8. Strict acceptance uses the exact provisional rule in this specification.
9. Clear-coverage bands remain diagnostic-only.
10. All required state fixtures pass.
11. Source count greater than one produces a hard failure and no mosaic.
12. Fixed-denominator and area-partition invariants pass using the exact formulas and tolerance in Section 8.3.
13. UTC product date and local-solar view time remain distinct.
14. Missing observations remain explicit null rows.
15. No values are interpolated or invented.
16. No stream is averaged or combined with another.
17. The geometry and water-proxy warnings appear in every row.
18. No permanent asset, export, deployment, application interface, or out-of-scope analysis is created.
19. The complete run is reproducible from recorded collection IDs, dates, geometry, projection, reducer parameters, versions, and tests.
20. Any natural-data behavior that contradicts the documented assumptions is reported as a failed or unresolved test rather than silently accommodated.

Passing this prototype validates only its engineering contract. It does not validate the final Lake Balaton scientific method.

## 14. Provisional assumptions

The following assumptions are made only for this prototype:

1. The normalized published coordinate identifies the intended Szemesi-basin sampling station.
2. A 250 m buffer around that point is sufficiently located in presumed open water for a smoke test.
3. The entire ROI can be treated as a provisional water proxy solely to exercise area fields.
4. The ROI is not scientifically representative of the basin or lake.
5. The 14-day interval is sufficient for pipeline diagnostics.
6. Synthetic images may supply missing deterministic state cases.
7. Requiring all four decoded QA components to equal zero is an acceptable strict engineering rule.
8. View time and view angle are required for acceptance in this prototype.
9. `Clear_*_cov` is diagnostic-only.
10. Provider numeric ranges are followed without an extra physical-temperature threshold.
11. Area is authoritative; pixel-center counts are secondary diagnostics.
12. No minimum accepted-area fraction is required.
13. The product UTC date is retained without local-date reconstruction.
14. The prototype’s performance does not represent archive-scale performance.

## 15. Approved prototype choices and unresolved application decisions

The user approved the following choices for this prototype only:

1. This complete prototype specification and its implementation scope.
2. The exact provisional geometry and normalized coordinate.
3. The exact 250 m buffer.
4. The exact 2024-07-01 to 2024-07-15 interval.
5. The strict QA acceptance rule.
6. Requiring view time and view angle for acceptance.
7. The disjoint QA-reason definitions.
8. The row-state precedence.
9. The duplicate-source hard-failure rule.
10. The fixed ROI-area denominator.
11. The provisional water-area aliases and mandatory warning.
12. The uniform schema and version metadata.
13. The provider-range-only LST treatment.
14. The use of synthetic fixtures.
15. The acceptance tests and acceptance criteria.

This specification does not resolve the application-level decisions:

- `METH-001`
- `METH-002`
- `METH-003`
- `METH-004`
- `SPACE-001`
- `QA-002`
- `METH-005`
- `METH-006`
- `DATA-005`
- `DATA-006`
- `ARCH-001`
- `VAL-001`
- `SCOPE-003`

In particular, it does not approve an authoritative water geometry, scientific valid-water coverage definition, minimum coverage threshold, climatology, percentile, classification, validation-release criterion, or production architecture.
