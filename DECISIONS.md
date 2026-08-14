# Lake Balaton Thermal Monitoring Decision Register

## Authority and use

This is the authoritative, versioned register for scientific, methodological, governance, and scope decisions in this project.

- Valid statuses are **proposed**, **approved**, **rejected**, and **superseded**.
- A chat-only proposal is not approved until the user explicitly approves it and the approval is recorded here.
- When decisions conflict, the newest approved, non-superseded decision controls.
- Material scientific or scope decisions and changes still require explicit user approval through the main coordinator.
- A superseded entry remains in this register and identifies the decision that replaced it.

## Approved decisions

### GOV-001 — Decision authority and agent roles

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** The main Codex task is the coordinator and the only interface for user approval. Scientific research and independent validation are read-only. Only the GEE application engineer may edit implementation files, and only when the coordinator assigns those files under an approved specification. No agent may commit, push, publish, deploy, create Earth Engine assets, or materially expand scope without explicit user authorization.
- **Rationale:** Centralized approval and separated research, implementation, and validation responsibilities reduce silent scope changes and conflicts.
- **Evidence or source:** Attached “Thesis Methodology Guidance” conversation as summarized in `PROJECT_CONTEXT.md`; `AGENTS.md`; explicit user governance approval on 2026-08-13.
- **Approval provenance:** Explicitly approved by the user through the main coordinator on 2026-08-13; strengthened governance wording explicitly approved in the current task.
- **Affected files or components:** `AGENTS.md`, `PROJECT_CONTEXT.md`, `DECISIONS.md`, `.codex/config.toml`, `.codex/agents/*.toml`, all future implementation and deployment work.
- **Superseded decision:** None.

### GOV-002 — Decision-register authority

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** `DECISIONS.md` is the authoritative versioned decision register. Approved scientific and scope decisions must be recorded here; chat-only proposals are not approved; and the newest approved, non-superseded decision controls.
- **Rationale:** A durable repository record makes approval provenance reviewable across tasks and prevents proposals or stale chat context from being mistaken for approved rules.
- **Evidence or source:** Explicit user instruction in the current task.
- **Approval provenance:** Explicitly approved by the user through the main coordinator on 2026-08-13.
- **Affected files or components:** `DECISIONS.md`, `AGENTS.md`, all scientific specifications and implementation tasks.
- **Superseded decision:** None.

### SCI-001 — Project purpose and scientific contribution

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** The internship will develop a Google Earth Engine application for satellite-derived surface-water-temperature anomalies and unusually warm observations in Lake Balaton. It must extend rather than merely reproduce Li, Somogyi, and Tóth (2024), with multi-sensor anomaly monitoring, basin comparison, day/night context, explicit data-quality reporting, and high-resolution inspection.
- **Rationale:** The project needs a distinct contemporary monitoring contribution rather than only a longer retrospective archive.
- **Evidence or source:** Attached conversation as summarized in `PROJECT_CONTEXT.md`, “Purpose and contribution.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as established scope approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Scientific methodology, GEE application requirements, reports, presentation, user guidance.
- **Superseded decision:** None.

### SCI-002 — Core comparison principle

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** An observation is evaluated against historical conditions for the same spatial unit, seasonal period, satellite, and observation stream.
- **Rationale:** This avoids mixing observations with different spatial, seasonal, platform, or day/night characteristics.
- **Evidence or source:** `PROJECT_CONTEXT.md`, core question and established analytical principles.
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as established methodology approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Climatology, anomaly, percentile, classification, daily and monthly summaries.
- **Superseded decision:** None.

### DATA-001 — MODIS datasets and separate observation streams

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** Use Terra MODIS `MODIS/061/MOD11A1` for daily morning and nighttime lake-surface-temperature observations and Aqua MODIS `MODIS/061/MYD11A1` for daily afternoon and nighttime observations. Aqua daytime is the primary candidate for afternoon warm extremes. Terra daytime, Aqua daytime, Terra nighttime, and Aqua nighttime are separate streams; each is compared only with its matching historical stream and they are not directly averaged. Any combined indicator requires a separately proposed and approved method.
- **Rationale:** Platform and day/night streams have distinct observation timing and characteristics and must not be conflated.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Established datasets and roles.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as an established dataset and sensor-role decision approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** MODIS ingestion, preprocessing, climatologies, anomaly calculations, summaries, interface labels, downloads.
- **Superseded decision:** None.

### DATA-002 — Landsat role

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** Landsat 8/9 Collection 2 Level 2 is used for detailed hotspot inspection on selected clear-sky dates. Its surface-temperature product is delivered on a 30 m grid, but its thermal information must not be described as an independent native 30 m measurement.
- **Rationale:** Landsat adds spatial detail while requiring accurate communication of the thermal product’s effective information content.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Established datasets and roles.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as an established dataset-role decision approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Landsat preprocessing, hotspot maps, documentation, interface wording.
- **Superseded decision:** None.

### DATA-003 — ERA5-Land role

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** ERA5-Land daily aggregates may provide weather context such as air temperature, wind, and solar radiation, but reanalysis is contextual and must not replace observed satellite lake-surface temperature.
- **Rationale:** Meteorological context can help interpret observations without being misrepresented as the lake-surface-temperature observation itself.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Established datasets and roles.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as an established dataset-role decision approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Contextual data processing, charts, interface, downloads, documentation.
- **Superseded decision:** None.

### DATA-004 — Optional in-situ validation role

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** In-situ measurements, if obtained, are optional validation data. Their measurement depth and timing may not match satellite skin temperature or satellite overpass time and must be interpreted accordingly.
- **Rationale:** Validation must acknowledge representativeness differences between field and satellite observations.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Established datasets and roles.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as an established validation-role decision approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Validation methodology, reports, uncertainty statements.
- **Superseded decision:** None.

### TIME-001 — Historical, monitoring, and archive periods

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** The historical reference period is 1 January 2003 through 31 December 2022; monitoring begins 1 January 2023 and continues through the latest valid available observation; the user-explorable archive begins in 2003. The reference starts in 2003 because it is the first complete calendar year shared by Terra and Aqua.
- **Rationale:** These periods provide a shared complete Terra/Aqua baseline and a distinct monitoring era.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Established periods.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as established periods approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Dataset filters, climatology, monitoring views, metadata, validation.
- **Superseded decision:** None.

### QA-001 — Missing observations and data-quality reporting

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** Do not invent or interpolate a satellite observation solely because cloud or QA masking leaves a date without valid data. Report valid-water coverage and observation counts, and provide an explicit no-valid-observation state when appropriate.
- **Rationale:** Users must be able to distinguish observed values from missing data and judge reliability.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Established analytical principles” and “Daily observation view.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as established analytical and output requirements approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** QA masking, daily and monthly summaries, interface states, downloads, validation.
- **Superseded decision:** None.

### TERM-001 — Thermal-event terminology

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** Use terms such as “unusually warm observation,” “extreme warm observation,” or “observed extreme thermal episode” unless a validated method supports a stronger term. Do not claim a formal lake heatwave without an approved, scientifically supported method for consecutive exceedances and missing daily observations. Hobday et al. (2016) is a scientific starting point, not an approved operational method.
- **Rationale:** Terminology must not imply event persistence or formal heatwave detection that the approved method has not established.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Established analytical principles”; Hobday et al. (2016), https://doi.org/10.1016/j.pocean.2015.12.014.
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as established terminology constraints approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Classification labels, interface text, reports, presentation, downloads.
- **Superseded decision:** None.

### OUT-001 — Required output categories

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** The intended product includes daily observation, monthly summary, detailed Landsat hotspot, approved spatial comparison, ERA5-Land context, and downloadable summary views with the fields described in `PROJECT_CONTEXT.md`. Exact definitions and interface layout remain unresolved where they depend on proposed methodological decisions.
- **Rationale:** These categories define the intended monitoring product while preserving approval gates for analytical definitions and UI details.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Intended outputs.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as intended product requirements approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Interface, summaries, maps, charts, tables, downloads, documentation.
- **Superseded decision:** None.

### PERF-001 — Performance architecture principle

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** The interface must not recompute the full 2003–2022 archive after every user interaction. Processing must filter early by date, sensor, and region and reuse approved precomputed climatologies, percentiles, and basin summaries for expensive historical operations. Asset schema, storage/export destination, refresh process, and deployment remain proposed.
- **Rationale:** Interactive performance requires avoiding repeated archive-wide computation.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Performance strategy.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as an established architecture principle approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Data architecture, callbacks, precomputation, exports, deployment planning.
- **Superseded decision:** None.

### SCOPE-001 — Thesis–internship separation

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** The MSc thesis concerns historical 1978–1989 Lake Balaton sediment chemistry, spatial autocorrelation, anisotropy, variography, and interpolation. The internship concerns contemporary satellite-derived lake-surface-temperature monitoring and GEE application development. The internship must not claim that current thermal observations explain historical sediment concentrations, directly correlate the mismatched periods as contemporaneous, or present historical sediment conditions as current.
- **Rationale:** The workstreams use different phenomena and time periods and must remain scientifically distinct.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Thesis–internship separation.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as an established scope boundary approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Scientific scope, analysis, reports, presentation, application narrative.
- **Superseded decision:** None.

### SCOPE-002 — Six-week delivery sequence

- **Date:** 2026-08-13
- **Status:** approved
- **Decision:** Follow the six-week sequence in `PROJECT_CONTEXT.md`: audit the prior study/application; establish approved preprocessing and QA; implement approved analytical methods; build approved comparisons and outputs; validate; and finalize the application and documentation. This sequence does not approve any unresolved methodology.
- **Rationale:** The sequence organizes delivery while retaining scientific approval gates.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Six-week delivery frame.”
- **Approval provenance:** Recorded in `PROJECT_CONTEXT.md` as the established delivery frame approved by the user on 2026-08-13; reaffirmed for registration in the current task.
- **Affected files or components:** Project planning, research, implementation, validation, documentation, presentation.
- **Superseded decision:** None.

### SCOPE-004 — Academic approval of broad internship topic

- **Date:** 2026-08-12
- **Status:** approved
- **Decision:** Academic supervisor Dr. Pál Márton approved the broad internship topic as suitable. The approved concept is a GEE application extending the existing Lake Balaton application with thermal-status or anomaly interpretation, daily observations, and basin-level monthly summaries. This academic approval does not approve all detailed methodological choices represented by the 13 proposed decisions in this register. The scope may be refined during the proposed consultation at the beginning of September 2026.
- **Rationale:** The supervisor confirmed that the proposed topic is suitable for completing the internship while leaving detailed methodology and possible scope refinement for subsequent consultation and approval.
- **Evidence or source:** User-provided correspondence evidence: proposal sent on 28 July 2026; supervisor response dated 12 August 2026 stating, “The topic looks promising! It is suitable for completing the internship.”
- **Approval provenance:** Academic suitability approval provided by Dr. Pál Márton on 12 August 2026 and supplied by the user for inclusion in the project record. This is distinct from project approval of detailed methodological choices.
- **Affected files or components:** Broad internship scope, project documentation, consultation planning, and the conceptual requirements for thermal-status or anomaly interpretation, daily observations, and basin-level monthly summaries. It does not authorize implementation of unresolved methodological choices.
- **Superseded decision:** None.

## Proposed decisions requiring explicit user approval

The following entries are unresolved. Their presence here does not authorize implementation.

### METH-001 — Historical seasonal window

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Decide whether to retain the inherited candidate of ±5 calendar days or use another window or smoother.
- **Rationale:** A seasonal matching rule is required to construct historical comparisons.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 1.
- **Approval provenance:** Not approved; carried forward as an open proposal from the attached conversation.
- **Affected files or components:** Climatology, anomaly, percentile calculations.
- **Superseded decision:** None.

### METH-002 — Historical reference statistic

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Select the historical reference statistic: mean, median, smoothed seasonal climatology, or another estimator.
- **Rationale:** An explicit estimator is required before anomalies can be implemented.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 2.
- **Approval provenance:** Not approved.
- **Affected files or components:** Climatology and anomaly calculations, metadata.
- **Superseded decision:** None.

### METH-003 — Percentile estimator and sample requirement

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Select the percentile estimator and minimum historical sample count per spatial unit and observation stream.
- **Rationale:** Percentiles and their reliability depend on estimator and sample sufficiency.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 3.
- **Approval provenance:** Not approved.
- **Affected files or components:** Percentile calculations, QA, classification, reporting.
- **Superseded decision:** None.

### METH-004 — Classification thresholds and labels

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Select classification thresholds and exact labels. The inherited 90th/95th-percentile scheme remains only a proposal.
- **Rationale:** Thresholds and labels materially determine reported thermal status.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 4.
- **Approval provenance:** Not approved.
- **Affected files or components:** Classification logic, interface, summaries, documentation.
- **Superseded decision:** None.

### SPACE-001 — Spatial units and authoritative geometries

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Select authoritative geometries and spatial units, including four basins, a lake-wide boundary, and whether littoral/pelagic zones belong in the six-week minimum scope.
- **Rationale:** Spatial comparisons and coverage metrics require approved boundaries.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 5.
- **Approval provenance:** Not approved.
- **Affected files or components:** Geometry assets, masks, summaries, maps, scope.
- **Superseded decision:** None.

### QA-002 — Valid-water coverage and QA thresholds

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Select minimum valid-water coverage and other QA acceptance thresholds for daily and monthly reporting.
- **Rationale:** Acceptance thresholds determine when an observation or summary is sufficiently reliable to report.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 6.
- **Approval provenance:** Not approved.
- **Affected files or components:** QA masks, acceptance logic, daily/monthly views, downloads.
- **Superseded decision:** None.

### METH-005 — Monthly aggregation and missing streams

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Define monthly aggregation when Terra/Aqua streams or days are missing, including whether monthly summaries remain stream-specific.
- **Rationale:** Monthly statistics must not silently mix streams or handle missingness inconsistently.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 7.
- **Approval provenance:** Not approved.
- **Affected files or components:** Monthly summaries, missingness metrics, interface, downloads.
- **Superseded decision:** None.

### METH-006 — Standardized multi-sensor indicator

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Decide whether to create a standardized multi-sensor indicator. Direct averaging of the four observation streams remains excluded.
- **Rationale:** Any combined indicator needs a defensible method that preserves stream differences.
- **Evidence or source:** `PROJECT_CONTEXT.md`, established stream separation and open decision 8.
- **Approval provenance:** Not approved.
- **Affected files or components:** Derived indicators, summaries, interface, documentation.
- **Superseded decision:** None.

### DATA-005 — Detailed Landsat method

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Define the exact Landsat role, date-selection rules, and shoreline/mixed-pixel treatment within the approved inspection role.
- **Rationale:** Reproducible hotspot inspection requires explicit selection and pixel-treatment rules.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 9.
- **Approval provenance:** Not approved.
- **Affected files or components:** Landsat preprocessing, hotspot maps, QA, documentation.
- **Superseded decision:** None.

### DATA-006 — ERA5-Land variables, aggregation, and latency

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Select ERA5-Land variables and temporal aggregation and define how data latency will be communicated.
- **Rationale:** Context variables and timing must be explicit and reproducible.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 10.
- **Approval provenance:** Not approved.
- **Affected files or components:** ERA5-Land processing, contextual views, metadata.
- **Superseded decision:** None.

### ARCH-001 — Precomputation and deployment strategy

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Define the precomputation asset/table schema, refresh cadence, ownership, storage/export destination, and GEE deployment strategy.
- **Rationale:** The approved performance principle requires an operational architecture before implementation or asset creation.
- **Evidence or source:** `PROJECT_CONTEXT.md`, “Performance strategy” and open decision 11.
- **Approval provenance:** Not approved.
- **Affected files or components:** GEE assets, tables, exports, refresh workflow, deployment.
- **Superseded decision:** None.

### VAL-001 — Validation acceptance criteria

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Define validation acceptance criteria and the response if in-situ data cannot be obtained.
- **Rationale:** Completion and scientific confidence require explicit acceptance rules.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 12.
- **Approval provenance:** Not approved.
- **Affected files or components:** Validation plan, tests, reports, release criteria.
- **Superseded decision:** None.

### SCOPE-003 — Six-week minimum viable outputs

- **Date:** 2026-08-13
- **Status:** proposed
- **Decision:** Select minimum viable outputs for the six-week delivery period and distinguish them from optional extensions.
- **Rationale:** Delivery scope must match the available time without silently dropping required outputs or adopting optional work.
- **Evidence or source:** `PROJECT_CONTEXT.md`, open decision 13.
- **Approval provenance:** Not approved.
- **Affected files or components:** Project plan, implementation scope, validation, documentation, presentation.
- **Superseded decision:** None.
