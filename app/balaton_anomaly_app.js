/**
 * Lake Balaton — water-surface temperature monitor (Phase 4 Earth Engine App).
 *
 * Published as a Google Earth Engine App from the Code Editor (Apps -> Publish).
 * A new, separate application; it does not modify the reference Li et al. (2024) app.
 *
 * It reads the four Earth Engine assets produced by the Phase 3 anomaly engine and
 * does no history recomputation:
 *
 *   projects/ee-jtantaroman/assets/balaton_anomaly/lake_boundary          (1 polygon)
 *   projects/ee-jtantaroman/assets/balaton_anomaly/climatology_baseline   (1,464 rows)
 *   projects/ee-jtantaroman/assets/balaton_anomaly/daily_anomaly_records  (3,608 rows, grows)
 *   projects/ee-jtantaroman/assets/balaton_anomaly/monthly_summaries      (176 rows, grows)
 *
 * The user-facing text is deliberately plain language — no internal decision codes.
 *
 * Known limitation of this version: it shows data only up to the last export
 * (LAST_EXPORT_DATE below). A later date shows "no reading yet" rather than
 * computing the value live.
 */

/* ------------------------------------------------------------------ constants */

var ASSET_ROOT   = 'projects/ee-jtantaroman/assets/balaton_anomaly/';
var LAKE         = ee.FeatureCollection(ASSET_ROOT + 'lake_boundary');
var CLIMATOLOGY  = ee.FeatureCollection(ASSET_ROOT + 'climatology_baseline');
var DAILY        = ee.FeatureCollection(ASSET_ROOT + 'daily_anomaly_records');
var MONTHLY      = ee.FeatureCollection(ASSET_ROOT + 'monthly_summaries');
var LAKE_GEOM    = LAKE.geometry();

var LAST_EXPORT_DATE = '2026-08-30';   // updated each time the monthly refresh runs
var FIRST_YEAR = 2023;
var LAST_YEAR  = 2026;

// ERA5-Land reanalysis — weather context only (DATA-003 / DATA-006). Never a
// measurement of the lake surface; it explains conditions, it does not replace the
// satellite reading. ~9 km grid, roughly one week behind real time. Air temperature
// and wind are taken from the HOURLY product at the pass's overpass hour; sunshine
// and rain are whole-day totals from the DAILY product.
var ERA5_DAILY  = 'ECMWF/ERA5_LAND/DAILY_AGGR';
var ERA5_HOURLY = 'ECMWF/ERA5_LAND/HOURLY';

// The four satellite passes, in the order they actually happen during a calendar
// date. Times are Hungarian clock time (CET in winter, CEST in summer — one hour
// later); they are the mean measured overpass times over the lake, and the exact
// minute varies a little day to day. `utcHour` is used only to match the ERA5-Land
// weather to the pass. NOTE: "Aqua pre-dawn" for date D is taken in the small
// hours OF D (~03:00), i.e. it is the FIRST reading of that date, not the last.
var STREAMS = {
  aqua_night:  {short: 'Aqua pre-dawn', clock: '~02:30–03:30 Hungarian time (summer)',
                clockWinter: '~01:30–02:30 Hungarian time (winter)',
                col: 'MODIS/061/MYD11A1', lst: 'LST_Night_1km', qc: 'QC_Night',
                time: 'Night_view_time', angle: 'Night_view_angle', utcHour: 1},
  terra_day:   {short: 'Terra morning', clock: '~11:30–12:30 Hungarian time (summer)',
                clockWinter: '~10:30–11:30 Hungarian time (winter)',
                col: 'MODIS/061/MOD11A1', lst: 'LST_Day_1km',   qc: 'QC_Day',
                time: 'Day_view_time',   angle: 'Day_view_angle', utcHour: 10},
  aqua_day:    {short: 'Aqua afternoon', clock: '~13:30–14:30 Hungarian time (summer)',
                clockWinter: '~12:30–13:30 Hungarian time (winter)',
                col: 'MODIS/061/MYD11A1', lst: 'LST_Day_1km',   qc: 'QC_Day',
                time: 'Day_view_time',   angle: 'Day_view_angle', utcHour: 12},
  terra_night: {short: 'Terra evening', clock: '~22:30–23:30 Hungarian time (summer)',
                clockWinter: '~21:30–22:30 Hungarian time (winter)',
                col: 'MODIS/061/MOD11A1', lst: 'LST_Night_1km', qc: 'QC_Night',
                time: 'Night_view_time', angle: 'Night_view_angle', utcHour: 21}
};
var STREAM_ORDER = ['aqua_night', 'terra_day', 'aqua_day', 'terra_night'];

// The four windows above are the real measured overpass times in CEST (summer clock);
// CET (winter) is exactly one hour earlier (`clockWinter`), per the standing note that
// Hungarian clock time is CET in winter, CEST in summer. EU summer time runs from the
// last Sunday in March 01:00 UTC to the last Sunday in October 01:00 UTC.
function isHungarianSummerTime(iso) {
  var probe = new Date(iso + 'T12:00:00Z');   // midday UTC, safely clear of the 01:00 switch
  var year = probe.getUTCFullYear();
  function lastSundayAt1amUtc(monthIndex) {   // monthIndex is 0-based (2 = March, 9 = October)
    var d = new Date(Date.UTC(year, monthIndex + 1, 0, 1, 0, 0));   // last day of monthIndex, 01:00 UTC
    d.setUTCDate(d.getUTCDate() - d.getUTCDay());                   // back up to that day's Sunday
    return d;
  }
  return probe >= lastSundayAt1amUtc(2) && probe < lastSundayAt1amUtc(9);
}
// The clock window to display for one pass on one specific date — summer or winter,
// picked for the date actually on screen rather than shown as one blended estimate.
function passClockWindow(streamId, iso) {
  var s = STREAMS[streamId];
  return isHungarianSummerTime(iso) ? s.clock : s.clockWinter;
}
// Two earlier attempts at a season-aware clock in the "Satellite pass" dropdown itself
// both broke the dropdown (rebuilding its items — even restoring the value right after —
// left it showing "select value" until clicked twice). The dropdown's own items are back
// to static, clock-free text (built once, below); the actual date-specific clock window
// is shown in a separate plain label next to it instead, which only ever has its text
// replaced (`.setValue`) — never its selection state — so there is nothing to break.

var LST_VIS = {min: -5, max: 32,
               palette: ['#2166ac', '#67a9cf', '#d1e5f0', '#fddbc7', '#ef8a62', '#b2182b']};

// Raw asset label -> colour and display text.
var LABEL_COLOUR = {
  'below normal':             '#2c7fb8',
  'within normal range':      '#41ab5d',
  'warm':                     '#fe9929',
  'unusually warm':           '#ec7014',
  'extreme warm observation': '#cc4c02'
};
var LABEL_DISPLAY = {
  'below normal':             'Below normal for the time of year',
  'within normal range':      'Within the normal range',
  'warm':                     'Warm for the time of year',
  'unusually warm':           'Unusually warm',
  'extreme warm observation': 'Extreme warm reading'
};

var MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December'];

/* ------------------------------------------------------------- small helpers */

function fmt(x, d) {
  if (x === null || x === undefined) { return '–'; }
  return Number(x).toFixed(d === undefined ? 1 : d);
}
function pad2(n) { return (n < 10 ? '0' : '') + n; }
function isoOf(dateLike) {
  var d = new Date(dateLike);   // accepts a Date, a millisecond number, or an ISO string
  return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate());
}
function isoPlusDays(iso, k) {
  var d = new Date(iso + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + k);
  return isoOf(d);
}
function ymLabel(ym) {
  var p = ym.split('-');
  return MONTH_NAMES[Number(p[1]) - 1] + ' ' + p[0];
}
function ordinal(n) {
  n = Math.round(n);
  var v = n % 100, s = ['th', 'st', 'nd', 'rd'];
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
// Compact "where it ranks" text for placing next to the classification label. The
// label is a threshold band (90 / 95 / 99th percentile) — showing the percentile
// beside it makes a borderline reading visibly borderline rather than a hard fact.
function percentileText(pct) {
  if (pct === null || pct === undefined) { return ''; }
  if (pct >= 99.5) { return 'record high for the time of year'; }
  if (pct <= 0.5)  { return 'record low for the time of year'; }
  return ordinal(pct) + ' percentile for the time of year';
}

/* ----------------------------------------------- candidate quality pixel map */

/**
 * The same clear-sky pixel-acceptance rule the anomaly engine uses, as a reusable mask —
 * shared by the pixel map (`acceptedLstC`) and the actual-overpass-time readout
 * (`drawDailyMap`'s view-time reduction), so both agree on exactly which pixels count.
 */
function qaMask(image, s) {
  var raw = image.select(s.lst);
  var qc  = image.select(s.qc);
  var vt  = image.select(s.time);
  var va  = image.select(s.angle);

  var mandatory   = qc.bitwiseAnd(3);
  var dataQuality = qc.rightShift(2).bitwiseAnd(3);
  var emisError   = qc.rightShift(4).bitwiseAnd(3);
  var lstError    = qc.rightShift(6).bitwiseAnd(3);

  return raw.gte(7500).and(raw.lte(65535))
    .and(vt.gte(0)).and(vt.lte(240))
    .and(va.gte(0)).and(va.lte(130))
    .and(mandatory.lte(1))
    .and(dataQuality.eq(0))
    .and(emisError.lte(1))
    .and(lstError.lte(1));
}

/**
 * The accepted-pixel LST image for one daily MODIS scene, so the map can show which
 * pixels went into that day's average.
 */
function acceptedLstC(image, s) {
  var raw = image.select(s.lst);
  return raw.multiply(0.02).subtract(273.15).updateMask(qaMask(image, s)).rename('lst_c');
}

/* ------------------------------------------------------------ per-pixel anomaly map */

// Same ±5-day window and 2003-2022 baseline as the approved lake-wide method (METH-001),
// computed live per pixel instead of precomputed as one lake-wide number. Built from real
// per-year calendar dates (not Earth Engine's native dayOfYear filter) so leap years never
// misalign the window by a day — 29 Feb folds onto 28 Feb in a non-leap year, matching the
// existing engine's fold_day_of_year rule.
var BASELINE_FIRST_YEAR = 2003;
var BASELINE_LAST_YEAR = 2022;
var ANOMALY_WINDOW_HALF_WIDTH_DAYS = 5;
var ANOMALY_MIN_HISTORICAL_N = 10;   // METH-003's existing minimum-sample guardrail, reused per pixel

function isLeapYear(y) { return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0; }

function historicalWindowFilter(targetIso) {
  var mm = Number(targetIso.slice(5, 7)), dd = Number(targetIso.slice(8, 10));
  var filters = [];
  for (var y = BASELINE_FIRST_YEAR; y <= BASELINE_LAST_YEAR; y++) {
    var day = dd;
    if (mm === 2 && dd === 29 && !isLeapYear(y)) { day = 28; }
    var ref = new Date(Date.UTC(y, mm - 1, day));
    var start = new Date(ref); start.setUTCDate(start.getUTCDate() - ANOMALY_WINDOW_HALF_WIDTH_DAYS);
    var end = new Date(ref); end.setUTCDate(end.getUTCDate() + ANOMALY_WINDOW_HALF_WIDTH_DAYS + 1);
    filters.push(ee.Filter.date(isoOf(start), isoOf(end)));
  }
  return ee.Filter.or.apply(null, filters);
}

// Per-pixel historical median + observation count for one stream, over the ±5-day/20-year
// window around `targetIso` — the "normal" map, built live (no precomputed asset), the same
// way the monthly bias-corrected map already reduces a filtered collection on the fly.
function pixelClimatology(streamId, targetIso) {
  var s = STREAMS[streamId];
  var col = ee.ImageCollection(s.col).filter(historicalWindowFilter(targetIso));
  var maskedCol = col.map(function (img) { return acceptedLstC(img, s); });
  var median = maskedCol.reduce(ee.Reducer.median()).rename('hist_median');
  var nObs = maskedCol.map(function (img) { return img.mask(); }).reduce(ee.Reducer.sum()).rename('n_obs');
  return median.addBands(nObs);
}

// Today's reading minus that SAME PIXEL's own historical normal — not minus the single
// lake-wide normal, because different parts of the lake have genuinely different normal
// temperatures (shallow vs. deep water), so a lake-wide reference would misread ordinary
// geography as a false anomaly. A pixel is only drawn when BOTH today's own QA-002 check
// passes AND that pixel has at least `ANOMALY_MIN_HISTORICAL_N` historical observations —
// otherwise blank, same "never guess" principle as the rest of this product (QA-001).
// Takes the climatology already built by the caller — this is the expensive ~220-image
// reduction, and it must only be built once per map draw, not once for the map layer and
// again for the coverage numbers (that duplication was the main cause of slow rendering).
function pixelAnomaly(image, streamId, clim) {
  var s = STREAMS[streamId];
  var todayLstC = acceptedLstC(image, s);
  var histOk = clim.select('n_obs').gte(ANOMALY_MIN_HISTORICAL_N);
  return todayLstC.subtract(clim.select('hist_median')).updateMask(histOk).rename('anomaly_c');
}

// Range checked against the real anomaly record, not guessed: across the full 2023+
// monitoring record (~900 readings per stream), the 5th-95th percentile of lake-wide
// anomalies is roughly -5..+5 degC for most streams. +-9 (an earlier choice, sized to
// never clip even the single most extreme known event, 18 Feb 2024) left almost every
// ORDINARY day crammed into the pale middle third of the scale, hard to tell apart --
// exactly the problem being fixed here. Narrowed to +-6, which comfortably covers the
// 95th-99th percentile for most streams: typical days now use the full colour range,
// and the rare truly extreme day (Feb 2024 included) simply shows as fully saturated
// red/blue instead of its own unique shade -- standard practice for a long-tailed
// distribution, and itself meaningful ("at or beyond the extreme end"), not a flaw.
// Deliberately NOT a seasonal scale (checked and rejected): winter nights do have a
// measurably wider COLD tail than summer (5th percentile -8.4 degC vs -2.4 degC for
// Aqua pre-dawn), but the WARM side barely differs by season -- the effect is
// asymmetric and stream-specific, not a clean "narrower in one season" story, and a
// seasonal scale would make the same anomaly value look more or less dramatic purely
// because of when it happened, undermining the point of an anomaly map. A seasonal
// scale remains reasonable for the raw TEMPERATURE map (a fixed -5..32 degC range
// looks washed out within any one season) but not for anomaly, which is already
// normalised to each day's own seasonal baseline by construction.
var ANOMALY_VIS = {min: -6, max: 6,
                   palette: ['#2166ac', '#67a9cf', '#d1e5f0', '#f7f7f7', '#fddbc7', '#ef8a62', '#b2182b']};

/* ---------------------------------------------------------------- UI layout */

ui.root.clear();

var mapPanel = ui.Map();
mapPanel.setOptions('TERRAIN');
mapPanel.setControlVisibility({layerList: true, zoomControl: true, mapTypeControl: false,
                               fullscreenControl: false, scaleControl: true});
mapPanel.centerObject(LAKE_GEOM, 10);

var panel = ui.Panel({style: {width: '470px', padding: '12px'}});
ui.root.add(panel);
ui.root.add(mapPanel);

// The lake outline is added exactly once and never touched again, so if the
// viewer switches it off in the layer list it stays off.
var outlineLayer = mapPanel.addLayer(
  ee.Image().byte().paint(LAKE_GEOM, 1, 2), {palette: ['#111111']}, 'Lake outline');
var pixelLayer = null;
function setPixelLayer(image, name, visParams) {
  if (pixelLayer) { mapPanel.layers().remove(pixelLayer); pixelLayer = null; }
  if (image) { pixelLayer = mapPanel.addLayer(image, visParams || LST_VIS, name); }
}

/**
 * Reads the min/max of the accepted lake pixels for the image just shown, so the
 * legend bar can be cropped to that window (see legendRampImage/updateLegend
 * below). The map layer itself always uses the fixed LST_VIS (-5..32 °C) colour
 * stretch — never this range — so a given temperature always renders as the same
 * colour and different days/months stay visually comparable. If the map were
 * rescaled to each image's own min/max instead, a mild day (say -2 to 13 °C)
 * would get stretched across the full blue-to-red range and look just as extreme
 * as a genuinely hot day reaching 32 °C, which is misleading.
 */
function computeLstRange(lstImage, callback) {
  lstImage.reduceRegion({
    reducer: ee.Reducer.minMax(),
    geometry: LAKE_GEOM,
    scale: 1000,
    maxPixels: 1e9,
    bestEffort: true
  }).evaluate(function (s) {
    if (!s || s.lst_c_min === null || s.lst_c_min === undefined
        || s.lst_c_max === null || s.lst_c_max === undefined) {
      callback(null);
      return;
    }
    callback({min: s.lst_c_min, max: s.lst_c_max});
  });
}

/* -- header -- */
panel.add(ui.Label('Lake Balaton — water-surface temperature monitor',
  {fontSize: '20px', fontWeight: 'bold', margin: '2px 0'}));
panel.add(ui.Label(
  'Surface temperature of Lake Balaton from the MODIS instruments on NASA’s Terra and '
  + 'Aqua satellites, January 2023 onward, compared with the 2003–2022 record for the '
  + 'same time of year.',
  {fontSize: '13px', color: '#555', margin: '0 0 3px 0'}));
panel.add(ui.Label(
  'Satellite coverage currently runs to ' + LAST_EXPORT_DATE
  + '. New months are added by hand, roughly monthly.',
  {fontSize: '13px', color: '#888', margin: '0 0 8px 0'}));

/* -- controls -- */
var modeSelect = ui.Select({
  items: [{label: 'Single day', value: 'daily'}, {label: 'Whole month', value: 'monthly'}],
  value: 'daily', style: {stretch: 'horizontal'}
});
panel.add(ui.Label('View', {fontWeight: 'bold', margin: '6px 0 2px 0'}));
panel.add(modeSelect);

// One item's dropdown text: the pass name plus that specific date's own clock window,
// e.g. "Terra morning  ~09:30–10:30 Hungarian time (winter)" — the same text used
// everywhere else in the app for this pass, so nothing is worded two different ways.
function streamItemLabel(streamId, iso) {
  return STREAMS[streamId].short + '  ' + passClockWindow(streamId, iso);
}
var streamSelect = ui.Select({
  items: STREAM_ORDER.map(function (id) { return {label: streamItemLabel(id, LAST_EXPORT_DATE), value: id}; }),
  value: 'terra_day', style: {stretch: 'horizontal'}
});
panel.add(ui.Label('Satellite pass', {fontWeight: 'bold', margin: '8px 0 2px 0'}));
// Wrapped in its own panel so the dropdown can be swapped out wholesale when the season
// changes (see `rebuildStreamSelect` below) without disturbing anything around it.
var streamSelectPanel = ui.Panel();
streamSelectPanel.add(streamSelect);
panel.add(streamSelectPanel);
// The real, measured overpass time for the selected day/pass (filled by
// `fillOverpassPanel`, daily view only) — kept right next to the pass picker itself,
// not buried further down the page, since it is a direct comment on the clock window
// shown just above it.
var overpassPanel = ui.Panel({style: {margin: '1px 0 4px 0'}});
panel.add(overpassPanel);
// Two earlier attempts put the clock text inside the dropdown by mutating its existing
// items in place (`streamSelect.items().reset(...)`) — both left the dropdown showing
// "select value" until clicked twice, an apparent Earth Engine UI quirk with mutating a
// live Select's items and immediately restoring its value. Rebuilding the widget from
// scratch instead — exactly how the dropdown is built the first time, above, which has
// never had this problem — sidesteps that quirk entirely: the new widget's `value` is
// correct from the moment it's constructed, nothing is "restored" after the fact.
function rebuildStreamSelect(iso) {
  var current = streamSelect.getValue();
  var fresh = ui.Select({
    items: STREAM_ORDER.map(function (id) { return {label: streamItemLabel(id, iso), value: id}; }),
    value: current, style: {stretch: 'horizontal'}
  });
  fresh.onChange(refresh);
  streamSelectPanel.clear();
  streamSelectPanel.add(fresh);
  streamSelect = fresh;
}

// Single-day map mode: plain temperature (the original map), or the new per-pixel
// anomaly map (today's reading minus that same pixel's own 2003-2022 normal).
var mapModeSelect = ui.Select({
  items: [{label: 'Temperature', value: 'temp'}, {label: 'Anomaly', value: 'anomaly'}],
  value: 'temp', style: {stretch: 'horizontal'}
});
var mapModeLabel = ui.Label('Map shows', {fontWeight: 'bold', margin: '8px 0 2px 0'});
panel.add(mapModeLabel);
panel.add(mapModeSelect);
mapModeSelect.onChange(refresh);
// Filled only in anomaly mode: the three coverage numbers needed to explain a blank pixel
// (today's own cloud cover vs. that pixel's own historical data being too thin), plus the
// map's own colour-scale legend text.
var anomalyCoveragePanel = ui.Panel({style: {margin: '1px 0 4px 0'}});
panel.add(anomalyCoveragePanel);

// Single-day view: a date field that opens a month/year calendar when clicked
// (drag the handle underneath for quick day-by-day scrubbing).
var dateSlider = ui.DateSlider({
  start: FIRST_YEAR + '-01-01',
  end: isoPlusDays(LAST_EXPORT_DATE, 1),
  value: LAST_EXPORT_DATE,   // replaced on load by the most recent day that has a reading
  period: 1,
  style: {stretch: 'horizontal'}
});
var dateGroup = ui.Panel();
dateGroup.add(ui.Label('Date  —  click the date to open a calendar',
  {fontWeight: 'bold', margin: '8px 0 2px 0'}));
dateGroup.add(dateSlider);
dateGroup.add(ui.Label(
  'The slider under the date steps one day at a time; use the calendar to jump further.',
  {fontSize: '12px', color: '#888', margin: '1px 0 0 0'}));
panel.add(dateGroup);

// Whole-month view: a plain Month dropdown. Every day inside one month gives the
// same monthly summary, so there is no point re-picking a day for it — this is a
// deliberately different, coarser control from the daily view's calendar above.
var monthPickItems = [];
(function () {
  var last = LAST_EXPORT_DATE.slice(0, 7);
  for (var yy = FIRST_YEAR; yy <= LAST_YEAR; yy++) {
    for (var mm = 1; mm <= 12; mm++) {
      var ym = yy + '-' + pad2(mm);
      if (ym > last) { break; }
      monthPickItems.push({label: MONTH_NAMES[mm - 1] + ' ' + yy, value: ym});
    }
  }
})();

// A faster way into the day slider than dragging through 3+ years of days — jumps
// straight to the 1st of the chosen month, reusing the same month list built above.
// This control's own selection is never read back anywhere — it only ever writes to
// the date slider — so there is no shared-state risk like the "Satellite pass" picker
// had.
var dateJumpSelect = ui.Select({
  items: monthPickItems, placeholder: 'Jump to a month…', style: {stretch: 'horizontal'}
});
dateJumpSelect.onChange(function (ym) {
  dateSlider.setValue(ym + '-01', false);
  refresh();
});
dateGroup.add(ui.Label('Jump to a month', {fontSize: '12px', color: '#888', margin: '4px 0 1px 0'}));
dateGroup.add(dateJumpSelect);

var monthYearSelect = ui.Select({
  items: monthPickItems,
  value: monthPickItems[monthPickItems.length - 1].value,   // most recent month with data
  style: {stretch: 'horizontal'}
});
var monthGroup = ui.Panel();
monthGroup.add(ui.Label('Month', {fontWeight: 'bold', margin: '8px 0 2px 0'}));
monthGroup.add(monthYearSelect);
panel.add(monthGroup);

/* -- daily section -- */
var dailyReadout = ui.Panel({style: {margin: '9px 0 5px 0', padding: '9px',
  backgroundColor: '#f6f6f6', border: '1px solid #ddd'}});
var dailyChartPanel = ui.Panel();
var passTablePanel  = ui.Panel({style: {margin: '4px 0'}});
var weatherPanel    = ui.Panel({style: {margin: '4px 0'}});
panel.add(dailyReadout);
panel.add(dailyChartPanel);
panel.add(passTablePanel);
panel.add(weatherPanel);

/* -- monthly section -- */
var monthlyReadout = ui.Panel({style: {margin: '9px 0 5px 0', padding: '9px',
  backgroundColor: '#f6f6f6', border: '1px solid #ddd'}});
var monthlyChartPanel = ui.Panel();
panel.add(monthlyReadout);
panel.add(monthlyChartPanel);

/* -- about -- */
panel.add(ui.Label('About this tool', {fontWeight: 'bold', fontSize: '14px', margin: '12px 0 2px 0'}));
panel.add(ui.Label(
  'Lake-surface temperature from NASA MODIS (Terra + Aqua, 1 km). Each of the four daily passes '
  + '(Aqua ~03:00, Terra ~11:30, Aqua ~14:00, Terra ~22:00 Hungarian time) is averaged over the '
  + 'clear-sky lake pixels and compared to its own 2003–2022 history for the same time of year '
  + '(±5-day window). The passes are never merged. Heavy cloud = no reading.',
  {fontSize: '12px', color: '#888', margin: '0'}));
panel.add(ui.Label(
  'Validated: over 2003–2024, our monthly average sits within ~0.5 °C of Landsat’s (a different '
  + 'satellite) reading for the same month on average, and the lake’s standout months (Feb 2024, '
  + 'summer 2024, 2024 as the warmest year) line up with the official Copernicus Climate Change '
  + 'Service bulletins for those periods — see the project’s methodology write-up for the exact '
  + 'comparison and sources. Reliable for spotting unusual readings, not calibrated to the exact '
  + 'degree. The "Weather" panel is ERA5-Land reanalysis — context, never a measurement of the water.',
  {fontSize: '12px', color: '#888', margin: '4px 0 0 0'}));

/* ------------------------------------------------------- readout components */

function kv(key, value, valueColour) {
  var row = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'), style: {margin: '1px 0'}});
  row.add(ui.Label(key, {color: '#666', fontSize: '13px', margin: '0 7px 0 0', width: '165px'}));
  row.add(ui.Label(value, {fontSize: '13px', fontWeight: 'bold', margin: '0',
                           color: valueColour || '#000', stretch: 'horizontal'}));
  return row;
}
function bigLabel(text, colour) {
  return ui.Label(text, {fontSize: '16px', fontWeight: 'bold', color: colour || '#000', margin: '2px 0 4px 0'});
}

function signed(x) { return (x >= 0 ? '+' : '−') + fmt(Math.abs(x)); }

// Clear-sky daily solar radiation for Lake Balaton's latitude on this date
// (FAO-56: extraterrestrial radiation x 0.75). Lets the sunshine reading be shown
// as a season-aware fraction — "6 kWh/m²" is a bright winter day and a dull July
// one, so the absolute number alone is misleading.
function clearSkyKwh(dstr) {
  var d = new Date(dstr + 'T00:00:00Z');
  var J = Math.round((d - Date.UTC(d.getUTCFullYear(), 0, 0)) / 864e5);
  var phi = 46.83 * Math.PI / 180;
  var dr = 1 + 0.033 * Math.cos(2 * Math.PI / 365 * J);
  var dec = 0.409 * Math.sin(2 * Math.PI / 365 * J - 1.39);
  var ws = Math.acos(-Math.tan(phi) * Math.tan(dec));
  var Ra = (1440 / Math.PI) * 0.082 * dr
    * (ws * Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.sin(ws));
  return 0.75 * Ra / 3.6;
}
function sunWordPct(frac) {
  return frac < 0.25 ? 'very overcast' : frac < 0.55 ? 'cloudy'
       : frac < 0.8 ? 'part sun' : frac < 0.95 ? 'mostly clear' : 'clear';
}
// ERA5-Land hourly 10 m wind speed at the overpass hour. Runs low in absolute
// terms over this small lake on a ~9 km grid, but separates a calm hour (~1.5–2)
// from a blowy one (~4+). Bands set to that.
function windWord(ms) {
  return ms < 1.5 ? 'calm' : ms < 2.5 ? 'light air' : ms < 4 ? 'breezy' : 'windy';
}
// How close the air is to saturation (air temperature minus dew point). A small
// gap means fog is plausible — this is the one weather signal that works at
// night too, unlike sunshine, which needs daylight to mean anything. Bands are
// set from a tested comparison: a night with visible MODIS fog-like dropouts
// measured ~3 C; clean nights measured 6.6-11.7 C.
function fogWord(depC) {
  return depC < 2.5 ? 'fog likely' : depC < 5 ? 'fog possible' : 'fog unlikely';
}

/* -------------------------------------------------------- month data cache */

// One EE call per calendar month fetches every stream's daily records for that
// month. Moving between days inside the same month then reuses it — the readout,
// the four-pass table and the chart are all rebuilt client-side, instantly, with
// no new Earth Engine request. Only the pixel map (a different satellite scene
// each day) still needs a fresh request per day.
var monthCache = {};   // 'YYYY-MM' -> {streamId: {byDate: {date: props}, list: [props,...]}}

function loadMonth(ym, callback) {
  if (monthCache[ym]) { callback(monthCache[ym]); return; }
  DAILY.filter(ee.Filter.stringStartsWith('date_utc', ym)).sort('date_utc')
    .evaluate(function (fc) {
      var byStream = {};
      STREAM_ORDER.forEach(function (id) { byStream[id] = {byDate: {}, list: []}; });
      var feats = (fc && fc.features) || [];
      feats.forEach(function (f) {
        var p = f.properties;
        var b = byStream[p.stream_id];
        if (!b) { return; }
        b.byDate[p.date_utc] = p;
        b.list.push(p);
      });
      monthCache[ym] = byStream;
      callback(byStream);
    });
}

/* ------------------------------------------------------- weather (ERA5-Land) */

// Weather context for one date + one pass: air temperature and wind from the
// ERA5-Land HOURLY product at that pass's overpass hour (UTC), plus whole-day
// sunshine and rain from the DAILY product. Cached per date+pass. `null` = no
// ERA5-Land data for that date yet (it runs ~a week behind).
var weatherCache = {};   // 'YYYY-MM-DD|streamId' -> {tPass,wind,tMin,tMax,solarKwh,rainMm} | null

function loadWeather(dstr, streamId, callback) {
  var key = dstr + '|' + streamId;
  if (weatherCache.hasOwnProperty(key)) { callback(weatherCache[key]); return; }

  var utcHour = STREAMS[streamId].utcHour;
  var passStart = ee.Date(dstr).advance(utcHour, 'hour');
  // mosaic() of a 0-or-1 image collection is empty-safe: a band-less image, and
  // reduceRegion on it (no .select() first — that would throw) returns {}.
  var hourly = ee.Image(ee.ImageCollection(ERA5_HOURLY)
    .filterDate(passStart, passStart.advance(1, 'hour')).mosaic());
  var daily = ee.Image(ee.ImageCollection(ERA5_DAILY)
    .filterDate(dstr, isoPlusDays(dstr, 1)).mosaic());

  var opts = {reducer: ee.Reducer.mean(), geometry: LAKE_GEOM, scale: 9000,
              maxPixels: 1e7, bestEffort: true};
  // Keep the two reductions separate so the pass-hour temperature/wind come
  // unambiguously from the HOURLY image, never from the DAILY mean.
  ee.Dictionary({h: ee.Dictionary(hourly.reduceRegion(opts)),
                 d: ee.Dictionary(daily.reduceRegion(opts))})
    .evaluate(function (r) {
      var h = (r && r.h) || {}, d = (r && r.d) || {};
      if (h.temperature_2m === undefined || h.temperature_2m === null) {
        weatherCache[key] = null; callback(null); return;
      }
      var u = h.u_component_of_wind_10m, v = h.v_component_of_wind_10m;
      var num = function (x, f) { return (x === undefined || x === null) ? null : f(x); };
      weatherCache[key] = {
        tPass: h.temperature_2m - 273.15,
        wind: Math.sqrt(u * u + v * v),
        // Kelvin difference == Celsius difference, no conversion needed.
        dewDepC: num(h.dewpoint_temperature_2m, function (x) { return h.temperature_2m - x; }),
        tMin: num(d.temperature_2m_min, function (x) { return x - 273.15; }),
        tMax: num(d.temperature_2m_max, function (x) { return x - 273.15; }),
        solarKwh: num(d.surface_solar_radiation_downwards_sum, function (x) { return x / 3.6e6; }),
        rainMm: num(d.total_precipitation_sum, function (x) { return x * 1000; })
      };
      callback(weatherCache[key]);
    });
}

/* --------------------------------------------------------- year data cache */

// Same idea, one level up, for the whole-month view: one EE call per calendar
// year fetches every stream's monthly summaries for that year. Picking a
// different month in the SAME year reuses it — nothing to recompute, since a
// month's summary never depends on which month is currently on screen.
var yearCache = {};   // 'YYYY' -> {streamId: {byMonth: {'YYYY-MM': props}, list: [props,...]}}

function loadYear(year, callback) {
  if (yearCache[year]) { callback(yearCache[year]); return; }
  MONTHLY.filter(ee.Filter.stringStartsWith('month', year)).sort('month')
    .evaluate(function (fc) {
      var byStream = {};
      STREAM_ORDER.forEach(function (id) { byStream[id] = {byMonth: {}, list: []}; });
      var feats = (fc && fc.features) || [];
      feats.forEach(function (f) {
        var p = f.properties;
        var b = byStream[p.stream_id];
        if (!b) { return; }
        b.byMonth[p.month] = p;
        b.list.push(p);
      });
      yearCache[year] = byStream;
      callback(byStream);
    });
}

/* -------------------------------------------------------------- daily view */

function currentDate() {
  var v = dateSlider.getValue();          // [start, end] of the 1-day range
  return isoOf(v && v.length ? v[0] : v);
}

function updateDaily() {
  var streamId = streamSelect.getValue();
  var dstr = currentDate();
  var ym = dstr.slice(0, 7);
  var dayName = Number(dstr.slice(8, 10)) + ' ' + MONTH_NAMES[Number(dstr.slice(5, 7)) - 1];

  rebuildStreamSelect(dstr);

  // Clear any previous day's map immediately rather than leaving it on screen while the
  // new day loads — it is redrawn below, once we know whether this day/pass actually has
  // an accepted reading at all.
  setPixelLayer(null);
  updateLegend(null);
  overpassPanel.clear();

  dailyReadout.clear();
  dailyReadout.add(ui.Label('Loading…', {color: '#999', fontSize: '13px'}));
  passTablePanel.clear();
  passTablePanel.add(ui.Label('Loading…', {color: '#999', fontSize: '13px'}));
  dailyChartPanel.clear();
  dailyChartPanel.add(ui.Label('Loading…', {color: '#999', fontSize: '13px'}));
  weatherPanel.clear();
  weatherPanel.add(ui.Label('Loading weather…', {color: '#999', fontSize: '13px'}));

  loadMonth(ym, function (byStream) {
    var p = byStream[streamId].byDate[dstr];
    fillDailyReadout(streamId, dstr, dayName, p);
    fillPassTable(dstr, byStream);
    drawSeriesChart(dailyChartPanel, byStream[streamId].list,
      ymLabel(ym) + ' — ' + STREAMS[streamId].short, dstr);
    // Only fetch/draw the pixel map when there is an actual accepted reading for this
    // pass and date — matching the readout exactly, rather than checking separately
    // whether *a* MODIS scene exists that day (which can be true even on a day this
    // pass's reading was rejected outright, and previously left a pixel map on screen
    // for a "No reading for this day" pass).
    if (p) { drawDailyMap(streamId, dstr, p); } else { setPixelLayer(null); updateLegend(null); overpassPanel.clear(); }
  });

  // Weather is its own fetch (a different collection from the anomaly records) —
  // the reading and pass table land first, weather fills in a moment later. It is
  // matched to the SELECTED pass's overpass hour.
  if (dstr <= LAST_EXPORT_DATE) {
    loadWeather(dstr, streamId, function (w) { fillWeatherPanel(dstr, streamId, w); });
  } else {
    fillWeatherPanel(dstr, streamId, null);
  }
}

function drawDailyMap(streamId, dstr, p) {
  var s = STREAMS[streamId];
  var start = ee.Date(dstr);
  var col = ee.ImageCollection(s.col).filterDate(start, start.advance(1, 'day'));
  var mode = mapModeSelect.getValue();
  col.size().evaluate(function (n) {
    if (!n) {
      setPixelLayer(null); updateLegend(null); fillOverpassPanel(streamId, dstr, null);
      anomalyCoveragePanel.clear();
      return;
    }
    var image = ee.Image(col.first());

    if (mode === 'anomaly') {
      drawAnomalyMap(image, streamId, dstr, p);
    } else {
      anomalyCoveragePanel.clear();
      var lstC = acceptedLstC(image, s).clip(LAKE_GEOM);
      setPixelLayer(lstC, s.short + ' — ' + dstr);   // fixed LST_VIS colour scale
      computeLstRange(lstC, updateLegend);           // informational range only
    }

    // The actual overpass time for THIS day, from the image's own view-time band —
    // Terra and Aqua have drifted in their orbits since 2003, so this can differ from
    // the long-run nominal window shown elsewhere. The band itself is LOCAL SOLAR TIME
    // (per the official MOD11A1 product documentation: GMT + longitude/15°), not UTC —
    // it must be converted using the lake's own longitude (read live from LAKE_GEOM,
    // never a hardcoded coordinate) before it means anything in UTC or Hungarian clock
    // time. Averaged over the same accepted pixels as the map above.
    var lakeLonDeg = ee.Number(LAKE_GEOM.centroid({maxError: 1000}).coordinates().get(0));
    var vtUtcHours = image.select(s.time).multiply(0.1).subtract(lakeLonDeg.divide(15))
      .add(24).mod(24)
      .updateMask(qaMask(image, s)).rename('vt_h');
    vtUtcHours.reduceRegion({
      reducer: ee.Reducer.mean(), geometry: LAKE_GEOM, scale: 1000, maxPixels: 1e9, bestEffort: true
    }).get('vt_h').evaluate(function (meanUtcHour) {
      fillOverpassPanel(streamId, dstr, meanUtcHour === null ? null : meanUtcHour);
    });
  });
}

// Draws the per-pixel anomaly layer, its own diverging legend (`showAnomalyLegend`,
// separate from the temperature legend), and the coverage caption below it.
//
// Coverage is deliberately computed via `count()` on properly masked numeric bands, never
// `mean()` on a derived boolean image — an earlier version did the latter and silently
// produced impossible numbers (a "coverage fraction" of exactly 1.0, with a pixel SUM
// greater than the pixel COUNT behind it — a sign `reduceRegion`'s scale/bestEffort
// resampling was interpolating the 0/1 mask image rather than sampling it directly).
// "Today's own coverage" reuses the already-correct, already-displayed
// `p.valid_water_fraction` from the precomputed daily record instead of recomputing it.
function drawAnomalyMap(image, streamId, dstr, p) {
  var s = STREAMS[streamId];
  var clim = pixelClimatology(streamId, dstr);   // the expensive part — built exactly once
  var anomaly = pixelAnomaly(image, streamId, clim).clip(LAKE_GEOM).rename('anomaly_ok');
  setPixelLayer(anomaly, s.short + ' — ' + dstr + ' anomaly vs 2003–2022', ANOMALY_VIS);
  showAnomalyLegend();

  var nObs = clim.select('n_obs');
  var histOk = nObs.updateMask(nObs.gte(ANOMALY_MIN_HISTORICAL_N)).rename('hist_ok');
  var combo = ee.Image.cat([nObs.rename('lake_total'), histOk, anomaly]);
  combo.reduceRegion({
    reducer: ee.Reducer.count(), geometry: LAKE_GEOM, scale: 1000, maxPixels: 1e9, bestEffort: true
  }).evaluate(function (counts) { fillAnomalyCoveragePanel(counts, p); });
}

function fillAnomalyCoveragePanel(counts, p) {
  anomalyCoveragePanel.clear();
  if (!counts || !counts.lake_total) { return; }
  var total = counts.lake_total;
  var todayPct = Math.round((p.valid_water_fraction || 0) * 100);
  var histPct = Math.round(((counts.hist_ok || 0) / total) * 100);
  var bothPct = Math.round(((counts.anomaly_ok || 0) / total) * 100);
  anomalyCoveragePanel.add(ui.Label('Anomaly map coverage: ~' + bothPct + '% of the lake',
    {fontSize: '12px', fontWeight: 'bold', color: '#555', margin: '0'}));
  anomalyCoveragePanel.add(ui.Label(
    'Needs both: today’s own clear-sky reading (' + todayPct + '% of the lake today, the exact '
    + 'figure used elsewhere on this page) AND a reliable historical normal for that exact '
    + 'pixel (~' + histPct + '% of the lake has at least ' + ANOMALY_MIN_HISTORICAL_N
    + ' historical readings for this time of year). A blank pixel can be missing for either '
    + 'reason, or both, and there is no way to tell which from the map alone. The ~ figures '
    + 'are approximate, computed live at whatever grid resolution Earth Engine happens to '
    + 'pick for this specific view — the same approximation already used for other live map '
    + 'statistics in this app, not a new source of imprecision.',
    {fontSize: '11px', color: '#888', margin: '1px 0 0 0'}));
  anomalyCoveragePanel.add(ui.Label(
    'This map is new, and computed live — not yet independently reviewed the way the rest '
    + 'of this product has been.',
    {fontSize: '11px', color: '#cc4c02', margin: '2px 0 0 0'}));
}

// Converts a UTC decimal hour (e.g. 9.23) into a Hungarian local "HH:MM" clock string
// for the given date, applying the same summer/winter offset as `passClockWindow`.
function formatHungarianClock(utcHour, iso) {
  var offset = isHungarianSummerTime(iso) ? 2 : 1;
  var localHour = ((utcHour + offset) % 24 + 24) % 24;
  var h = Math.floor(localHour);
  var m = Math.round((localHour - h) * 60);
  if (m === 60) { m = 0; h = (h + 1) % 24; }
  return pad2(h) + ':' + pad2(m);
}

// The systematic-bias MECHANISM a drifted pass time can cause — described in words only,
// no specific target clock time quoted (chasing an exact number here was a repeated
// source of confusion; the real vs. nominal comparison above already shows the size and
// direction for this specific day). Named only for the two passes where the direction is
// actually established.
function driftBiasNote(streamId) {
  if (streamId === 'terra_day') {
    return 'When this pass happens earlier than its own historical nominal window, it samples '
      + 'the lake before as much of the day’s warming has occurred, which can read '
      + 'systematically ‘too cool’ — a sensor-timing effect, not a real anomaly.';
  }
  if (streamId === 'aqua_day') {
    return 'When this pass happens later than its own historical nominal window, it samples the '
      + 'lake closer to the day’s peak heat, which can read systematically ‘too warm’ '
      + '— a sensor-timing effect, not a real anomaly.';
  }
  return '';
}

function fillOverpassPanel(streamId, dstr, meanUtcHour) {
  overpassPanel.clear();
  if (meanUtcHour === null || meanUtcHour === undefined) { return; }
  var actual = formatHungarianClock(meanUtcHour, dstr);
  overpassPanel.add(ui.Label(
    'MODIS’s own timestamp for this image: ~' + actual + ' Hungarian time',
    {fontSize: '12px', fontWeight: 'bold', color: '#555', margin: '0'}));
  overpassPanel.add(ui.Label(
    'Averaged over the accepted pixels — compare to the long-run nominal window shown above ('
    + passClockWindow(streamId, dstr) + '), itself measured from the 2003–2022 historical '
    + 'record. Terra and Aqua have both drifted in their orbits since 2023, so a given day’s '
    + 'real pass time can differ from that nominal window — both numbers are real, measured '
    + 'values, so comparing them directly already tells the full story.',
    {fontSize: '11px', color: '#888', margin: '1px 0 0 0'}));
  var biasNote = driftBiasNote(streamId);
  if (biasNote) {
    overpassPanel.add(ui.Label(
      biasNote + ' This is a known, described limitation — not yet corrected for, and its '
      + 'exact size for Balaton has not yet been estimated.',
      {fontSize: '11px', color: '#cc4c02', margin: '2px 0 0 0'}));
  }
}

function fillDailyReadout(streamId, dstr, dayName, p) {
  dailyReadout.clear();
  dailyReadout.add(ui.Label(
    STREAMS[streamId].short + '  ·  ' + dayName + ' ' + dstr.slice(0, 4),
    {fontWeight: 'bold', fontSize: '14px', margin: '0 0 4px 0'}));

  if (!p) {
    dailyReadout.add(bigLabel('No reading for this day', '#999'));
    dailyReadout.add(ui.Label(
      dstr > LAST_EXPORT_DATE
        ? 'Later than the last data update (' + LAST_EXPORT_DATE + ').'
        : 'The lake was too cloudy on this pass for a reliable reading.',
      {fontSize: '12px', color: '#666'}));
    return;
  }

  var raw = p.classification;

  // Verdict + its percentile on one line — the label is a threshold band, so the
  // percentile beside it shows whether a reading sits near a boundary.
  dailyReadout.add(bigLabel(LABEL_DISPLAY[raw] || raw, LABEL_COLOUR[raw] || '#000'));
  dailyReadout.add(ui.Label(
    percentileText(p.historical_percentile) + '  ·  ' + p.historical_n + ' past readings'
    + (p.percentile_confidence && p.percentile_confidence !== 'full' ? '  ·  small sample' : ''),
    {fontSize: '12px', color: '#666', margin: '0 0 5px 0'}));

  dailyReadout.add(kv('Lake surface', fmt(p.daily_lst_c) + ' °C'));
  dailyReadout.add(kv('vs normal', signed(p.anomaly_vs_median_c) + ' °C   (median '
    + fmt(p.reference_median_lst_c) + ' °C;  the mean gives ' + signed(p.anomaly_vs_mean_c) + ' °C)'));
  dailyReadout.add(ui.Label('"normal" = the 2003–2022 record for ' + dayName + ' ± 5 days',
    {fontSize: '11px', color: '#999', margin: '1px 0 4px 0'}));
  dailyReadout.add(kv('Clear-sky view',
    Math.round(p.valid_water_fraction * 100) + '% of the lake (' + p.accepted_pixel_count
    + ' px) — ' + (p.confidence === 'ok' ? 'good' : 'low; treat with caution'),
    p.confidence === 'ok' ? '#2e7d32' : '#cc4c02'));
}

function fillPassTable(dstr, byStream) {
  passTablePanel.clear();
  passTablePanel.add(ui.Label('The same date seen by each satellite pass',
    {fontWeight: 'bold', fontSize: '14px', margin: '4px 0 1px 0'}));
  passTablePanel.add(ui.Label(
    'Each pass is measured and judged on its own — they are never averaged together.',
    {fontSize: '12px', color: '#888', margin: '0 0 3px 0'}));

  // Every cell — header and body — sets margin:'0' and the same width, so the
  // columns line up. (Leaving the header labels on the default label margin was
  // why "temp" / "vs normal" sat shifted right of the numbers under them.)
  var C_PASS = '112px', C_COV = '40px', C_TEMP = '52px', C_NORM = '58px';
  function cell(text, w, extra) {
    var st = {fontSize: '12px', margin: '0'};
    if (w) { st.width = w; } else { st.stretch = 'horizontal'; }
    for (var k in (extra || {})) { st[k] = extra[k]; }
    return ui.Label(text, st);
  }
  var LABEL_SHORT = {
    'below normal': 'below normal', 'within normal range': 'within normal',
    'warm': 'warm', 'unusually warm': 'unusually warm',
    'extreme warm observation': 'extreme warm'
  };

  var header = ui.Panel({layout: ui.Panel.Layout.flow('horizontal')});
  header.add(cell('pass', C_PASS, {color: '#888'}));
  header.add(cell('lake', C_COV, {color: '#888'}));
  header.add(cell('temp', C_TEMP, {color: '#888'}));
  header.add(cell('vs norm', C_NORM, {color: '#888'}));
  header.add(cell('verdict  ·  rank', null, {color: '#888'}));
  passTablePanel.add(header);

  STREAM_ORDER.forEach(function (id) {
    var p = byStream[id].byDate[dstr];
    var low = !!(p && p.confidence === 'low');
    var row = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'), style: {margin: '1px 0'}});
    // A low-coverage row is coloured orange — the "lake" % already shows why, so
    // there is no separate marker.
    row.add(cell(STREAMS[id].short, C_PASS, low ? {color: '#cc4c02'} : null));
    if (!p) {
      row.add(cell('–', C_COV, {color: '#bbb'}));
      row.add(cell('–', C_TEMP, {color: '#bbb'}));
      row.add(cell('', C_NORM));
      row.add(cell('', null));
    } else {
      // "lake" column = how much of the lake this pass actually saw — shown for
      // every row, not only the low ones, so a 16%-coverage `ok` day is visible.
      row.add(cell(Math.round(p.valid_water_fraction * 100) + '%', C_COV,
        {color: low ? '#cc4c02' : '#888'}));
      row.add(cell(fmt(p.daily_lst_c) + '°', C_TEMP));
      row.add(cell((p.anomaly_vs_median_c >= 0 ? '+' : '−')
        + fmt(Math.abs(p.anomaly_vs_median_c)) + '°', C_NORM));
      row.add(cell((LABEL_SHORT[p.classification] || p.classification)
        + '  ·  ' + (p.historical_percentile >= 99.5 ? 'record'
            : p.historical_percentile <= 0.5 ? 'record low'
            : ordinal(p.historical_percentile) + ' pct'),
        null, {color: LABEL_COLOUR[p.classification] || '#000'}));
    }
    passTablePanel.add(row);
  });

  passTablePanel.add(ui.Label(
    '"lake" = share of the lake seen clearly (orange = under 15%, less certain).',
    {fontSize: '11px', color: '#888', margin: '4px 0 0 0'}));
  passTablePanel.add(ui.Label(
    '"rank" = where the reading sits in the 2003–2022 record; the verdict bands are at the '
    + '90th / 95th / 99th percentile, so a rank near a line can go either way.',
    {fontSize: '11px', color: '#888', margin: '1px 0 0 0'}));
}

// Weather context for the selected date and pass — ERA5-Land reanalysis,
// background conditions only. It never replaces the satellite reading (DATA-003);
// it helps explain WHY a reading was unusual. Air temperature and wind are for the
// pass's overpass hour; sunshine and rain are whole-day totals.
function fillWeatherPanel(dstr, streamId, w) {
  weatherPanel.clear();
  weatherPanel.add(ui.Label('Weather — ' + STREAMS[streamId].short + ', ' + passClockWindow(streamId, dstr),
    {fontWeight: 'bold', fontSize: '14px', margin: '8px 0 1px 0'}));
  weatherPanel.add(ui.Label(
    'ERA5-Land reanalysis — context for the reading, not a measurement of the water.',
    {fontSize: '12px', color: '#888', margin: '0 0 3px 0'}));

  if (dstr > LAST_EXPORT_DATE) { return; }
  if (!w) {
    weatherPanel.add(ui.Label('Not available for this date yet (ERA5-Land is ~a week behind).',
      {fontSize: '12px', color: '#999', margin: '0'}));
    return;
  }

  weatherPanel.add(kv('Air at the pass', fmt(w.tPass) + ' °C'));
  weatherPanel.add(kv('Wind at the pass', fmt(w.wind) + ' m/s — ' + windWord(w.wind)));
  // Sunshine only means something in daylight, so it can't tell you whether a
  // night pass was clear. Dew-point gap works at any hour — how close the air
  // was to saturation, i.e. how plausible fog was right then.
  if (w.dewDepC !== null) {
    weatherPanel.add(kv('Air vs dew point', fmt(w.dewDepC) + ' °C — ' + fogWord(w.dewDepC)));
  }

  // "That day overall" in its own framed box so it doesn't read as one long line.
  // Sun is shown as a fraction of the cloudless maximum for this date + latitude,
  // clamped to 100 (a genuinely clear day can compute a touch over).
  var sunFrac = w.solarKwh === null ? null : w.solarKwh / clearSkyKwh(dstr);
  var sunPct = sunFrac === null ? null : Math.min(100, Math.round(100 * sunFrac));
  var frame = ui.Panel({style: {margin: '4px 0 0 0', padding: '6px 9px',
    backgroundColor: '#f0f0f0', border: '1px solid #e0e0e0'}});
  frame.add(ui.Label('That day overall', {fontSize: '11px', color: '#888', margin: '0 0 1px 0'}));
  frame.add(ui.Label(
    'Sun ' + (sunPct === null ? '–' : sunPct + '% of a clear day (' + sunWordPct(sunFrac) + ')')
    + '   ·   Rain ' + (w.rainMm === null ? '–' : (w.rainMm < 0.1 ? 'none' : fmt(w.rainMm) + ' mm'))
    + (w.tMin !== null ? '   ·   Air range ' + fmt(w.tMin) + ' to ' + fmt(w.tMax) + ' °C' : ''),
    {fontSize: '12px', color: '#444', margin: '0'}));
  weatherPanel.add(frame);

  weatherPanel.add(ui.Label(
    'Calm, sunny weather lets the surface skin run hot by day and cold before dawn; wind mixes it '
    + 'away, cloud and cold air pull it toward the air. "% of a clear day" = the day\'s sunshine '
    + '÷ the cloudless maximum for this date and latitude (Sun geometry, less ~25% for a clean '
    + 'atmosphere) — only meaningful in daylight. "Air vs dew point" is a rough fog-risk reading '
    + 'that works at any hour, including the two night passes. ERA5-Land\'s ~9 km grid is coarse '
    + 'next to the lake, so its wind runs a little low.',
    {fontSize: '11px', color: '#888', margin: '4px 0 0 0'}));
}

/* ------------------------------------------------------------ monthly view */

function updateMonthly() {
  var streamId = streamSelect.getValue();
  var ym = monthYearSelect.getValue();
  var year = ym.slice(0, 4);
  var monthName = ymLabel(ym);

  // Mid-month is an arbitrary but reasonable stand-in for "which season is this
  // month" — the only months where it could matter (March, October) already switch
  // partway through, so any single representative day is a judgement call.
  rebuildStreamSelect(ym + '-15');

  monthlyReadout.clear();
  monthlyReadout.add(ui.Label('Loading…', {color: '#999', fontSize: '13px'}));
  monthlyChartPanel.clear();
  monthlyChartPanel.add(ui.Label('Loading…', {color: '#999', fontSize: '13px'}));

  loadYear(year, function (byStream) {
    var p = byStream[streamId].byMonth[ym];
    fillMonthlyReadout(streamId, monthName, p);
    drawMonthlySeriesChart(monthlyChartPanel, byStream[streamId].list,
      year + ' — ' + STREAMS[streamId].short, ym);

    if (!p || p.state !== 'reported') { drawMonthlyMap(streamId, ym, null, null); return; }
    // The bias-corrected map needs each day's own lake-average (see drawMonthlyMap).
    // Reuse the daily records already computed by the Phase 3 engine (loadMonth is
    // cached — free if this month was already opened in the single-day view) rather
    // than recomputing a fresh pixel reduction per image — that recomputation was
    // the main reason the monthly view got slower.
    loadMonth(ym, function (dailyByStream) {
      var dayMeans = {};
      var byDate = dailyByStream[streamId].byDate;
      for (var d in byDate) {
        if (typeof byDate[d].daily_lst_c === 'number') { dayMeans[d] = byDate[d].daily_lst_c; }
      }
      drawMonthlyMap(streamId, ym, p.monthly_mean_lst_c, dayMeans);
    });
  });
}

function fillMonthlyReadout(streamId, monthName, p) {
  monthlyReadout.clear();
  monthlyReadout.add(ui.Label(STREAMS[streamId].short + '  ·  ' + monthName,
    {fontWeight: 'bold', fontSize: '14px', margin: '0 0 4px 0'}));

  if (!p) { monthlyReadout.add(bigLabel('No summary for this month', '#999')); return; }
  if (p.state !== 'reported') {
    monthlyReadout.add(bigLabel('Not enough clear days to summarise', '#cc4c02'));
    monthlyReadout.add(kv('Clear days', p.valid_day_count + ' of ' + p.calendar_day_count
      + (p.low_coverage_day_count > 0 ? '  (' + p.low_coverage_day_count + ' low coverage)' : '')
      + ' — a summary needs at least 3'));
    return;
  }
  monthlyReadout.add(kv('Average lake surface', fmt(p.monthly_mean_lst_c) + ' °C'));
  monthlyReadout.add(kv('vs normal', signed(p.monthly_mean_anomaly_vs_median_c)
    + ' °C   (median;  the mean gives ' + signed(p.monthly_mean_anomaly_vs_mean_c) + ' °C)'));
  monthlyReadout.add(ui.Label('"normal" = the 2003–2022 median for this calendar month',
    {fontSize: '11px', color: '#999', margin: '1px 0 4px 0'}));
  // Two different things: how many DAYS of the month had a reading (temporal),
  // and how much of the LAKE those readings covered on average (spatial).
  monthlyReadout.add(kv('Days with a reading', p.valid_day_count + ' of ' + p.calendar_day_count
    + (p.low_coverage_day_count > 0 ? '   ·   ' + p.low_coverage_day_count + ' low-coverage' : '')));
  if (typeof p.mean_valid_water_fraction === 'number') {
    monthlyReadout.add(kv('Lake seen, per reading',
      '~' + (p.mean_valid_water_fraction * 100).toFixed(0)
      + '% of the ~700 pixels, averaged over those days'));
  }
  if (p.low_coverage_day_count >= p.valid_day_count && p.valid_day_count > 0) {
    monthlyReadout.add(ui.Label(
      'Every clear day this month saw under 15% of the lake — this summary rests on very thin '
      + 'coverage; treat it with caution.',
      {fontSize: '12px', color: '#cc4c02', margin: '2px 0 4px 0'}));
  }
  monthlyReadout.add(kv('Warm-or-above days', String(p.warm_observation_count)));
  monthlyReadout.add(kv('Warmest reading',
    fmt(p.hottest_observation_lst_c) + ' °C on ' + p.hottest_observation_date));
  monthlyReadout.add(kv('Biggest single-day jump',
    '+' + fmt(p.max_anomaly_vs_median_c) + ' °C on ' + p.max_anomaly_vs_median_date));
  monthlyReadout.add(ui.Label(
    'Map: this month pixel by pixel — where the lake ran warmer or cooler. Rescaled so its level '
    + 'matches the figure above: a plain pixel average runs ~0.5 °C warm because warm days are the '
    + 'clearer ones ("clear-sky bias"). Blank areas were never seen clearly.',
    {fontSize: '11px', color: '#999', margin: '3px 0 0 0'}));
}

// Whole-month view: a per-pixel monthly mean of every clear, quality-checked day
// of the month — but rescaled so its overall level equals the day-weighted figure
// on the left, not the pixel-weighted composite (which runs ~0.5 °C warm because
// warm days are clearer and contribute more pixels). Method: for each day, remove
// that day's own lake mean so only each pixel's position relative to the lake is
// left; composite those; add the day-weighted monthly figure back. Blank = a pixel
// never seen clearly.
//
// Each day's lake mean is looked up from `dayMeans` (the already-fetched Phase 3
// daily records — see updateMonthly) instead of being recomputed pixel by pixel:
// a fresh reduceRegion per image was the main reason this view got noticeably
// slower once the bias correction was added.
function drawMonthlyMap(streamId, ym, monthlyMeanC, dayMeans) {
  if (monthlyMeanC === null || monthlyMeanC === undefined) {
    setPixelLayer(null); updateLegend(null); return;
  }
  var s = STREAMS[streamId];
  var start = ee.Date(ym + '-01');
  var col = ee.ImageCollection(s.col).filterDate(start, start.advance(1, 'month'));
  var dayMeanDict = ee.Dictionary(dayMeans || {});
  col.size().evaluate(function (n) {
    if (!n) { setPixelLayer(null); updateLegend(null); return; }
    var pattern = col.map(function (img) {
      img = ee.Image(img);
      var lstC = acceptedLstC(img, s);
      // A date missing from dayMeans (no accepted pixels that day) defaults to 0 —
      // harmless, since lstC is then fully masked and contributes nothing anyway.
      var dayMean = ee.Number(dayMeanDict.get(img.date().format('YYYY-MM-dd'), 0));
      return lstC.subtract(dayMean).toFloat().rename('lst_c');
    }).mean();
    var meanC = pattern.add(monthlyMeanC).toFloat().clip(LAKE_GEOM);
    setPixelLayer(meanC, s.short + ' — ' + ymLabel(ym) + ' mean');   // fixed LST_VIS scale
    computeLstRange(meanC, updateLegend);
  });
}

/* -------------------------------------------------------- shared line chart */

/**
 * Draws the month-long series chart from already-fetched records (see loadMonth
 * above) — no Earth Engine call happens here, so re-drawing just to move the
 * highlighted day is instant.
 *   rows          - array of daily_anomaly_records properties for one stream, one month
 *   highlightDate - 'YYYY-MM-DD' to mark with a yellow dot (single-day view), or
 *                   null/undefined for the whole-month view (no highlight, not clickable)
 */
function drawSeriesChart(target, rows, title, highlightDate) {
  target.clear();
  var clickable = !!highlightDate;
  // Only add the highlight column when the selected day actually has a measurement.
  // A column that is null for every row (e.g. the selected day was too cloudy, so
  // no row matches it at all) breaks Google Charts with "All series on a given
  // axis must be of the same data type" — this is what caused that error.
  var hlRow = clickable && rows.filter(function (p) { return p.date_utc === highlightDate; })[0];
  var hasHl = !!hlRow;

  var data = [hasHl
    ? ['Date', 'Measured', 'Typical (median)', 'Selected day']
    : ['Date', 'Measured', 'Typical (median)']];
  rows.forEach(function (p) {
    var row = [p.date_utc, p.daily_lst_c, p.reference_median_lst_c];
    if (hasHl) { row.push(p.date_utc === highlightDate ? p.daily_lst_c : null); }
    data.push(row);
  });

  var series = {0: {lineWidth: 0, pointSize: 4, color: '#b2182b'},
                1: {lineWidth: 2, pointSize: 0, color: '#4575b4'}};
  // A bit bigger than the red "measured" dots and a bright colour, so the current
  // day stands out without swallowing the point underneath it.
  if (hasHl) { series[2] = {lineWidth: 0, pointSize: 7, color: '#ffd600'}; }

  var chart = ui.Chart(data, 'LineChart', {
    title: title,
    height: 235,
    interpolateNulls: false,
    series: series,
    hAxis: {slantedText: true, slantedTextAngle: 60, textStyle: {fontSize: 10}},
    vAxis: {title: 'Lake-surface temperature (°C)', titleTextStyle: {fontSize: 12}},
    legend: {position: 'top', textStyle: {fontSize: 12}},
    chartArea: {left: 52, right: 14, top: 42, bottom: 62}
  });
  if (clickable) {
    chart.onClick(function (dateStr) {
      if (!dateStr) { return; }
      dateSlider.setValue(isoOf(dateStr), false);
      refresh();
    });
  }
  target.add(chart);
  target.add(ui.Label(
    'One point per day of the chosen month. Red dots: the measured lake-surface temperature '
    + 'on days clear enough to see. Blue line: the typical value for that calendar day '
    + '(2003–2022 median, from the ±5-day window around it). A gap means that day was too '
    + 'cloudy for a reading. The vertical distance between a dot and the blue line is how far '
    + 'that day was above or below normal — look for the dots furthest from the line.'
    + (hasHl ? ' The yellow dot is the day shown above; click any red dot to jump to it.'
             : (clickable ? ' Click any red dot to jump to that day.' : '')),
    {fontSize: '12px', color: '#777', margin: '2px 0 8px 0'}));
}

/**
 * The whole-month view's chart: one point per MONTH of the selected year (not per
 * day), from already-fetched monthly summaries (see loadYear above) — no Earth
 * Engine call happens here, so switching months within the same year is instant.
 *   rows          - array of monthly_summaries properties for one stream, one year
 *   highlightMonth - 'YYYY-MM' to mark with a yellow dot
 */
function drawMonthlySeriesChart(target, rows, title, highlightMonth) {
  target.clear();
  var hlRow = rows.filter(function (p) {
    return p.month === highlightMonth
      && p.monthly_mean_lst_c !== undefined && p.monthly_mean_lst_c !== null;
  })[0];
  var hasHl = !!hlRow;

  var data = [hasHl
    ? ['Month', 'Measured', 'Typical (median)', 'Selected month']
    : ['Month', 'Measured', 'Typical (median)']];
  rows.forEach(function (p) {
    var measured = (p.monthly_mean_lst_c === undefined) ? null : p.monthly_mean_lst_c;
    var typical = (measured !== null
      && p.monthly_mean_anomaly_vs_median_c !== undefined
      && p.monthly_mean_anomaly_vs_median_c !== null)
      ? measured - p.monthly_mean_anomaly_vs_median_c
      : null;
    var row = [p.month, measured, typical];
    if (hasHl) { row.push(p.month === highlightMonth ? measured : null); }
    data.push(row);
  });

  var series = {0: {lineWidth: 2, pointSize: 5, color: '#b2182b'},
                1: {lineWidth: 2, pointSize: 0, color: '#4575b4'}};
  if (hasHl) { series[2] = {lineWidth: 0, pointSize: 8, color: '#ffd600'}; }

  var chart = ui.Chart(data, 'LineChart', {
    title: title,
    height: 235,
    interpolateNulls: false,
    series: series,
    hAxis: {slantedText: true, slantedTextAngle: 60, textStyle: {fontSize: 11}},
    vAxis: {title: 'Lake-surface temperature (°C)', titleTextStyle: {fontSize: 12}},
    legend: {position: 'top', textStyle: {fontSize: 12}},
    chartArea: {left: 52, right: 14, top: 42, bottom: 52}
  });
  chart.onClick(function (monthStr) {
    if (!monthStr) { return; }
    var mm = String(monthStr).slice(0, 7);
    var known = monthPickItems.some(function (it) { return it.value === mm; });
    if (known) { monthYearSelect.setValue(mm, false); refresh(); }
  });
  target.add(chart);
  target.add(ui.Label(
    'One point per month of the selected year. Red: that month\'s average lake-surface '
    + 'temperature. Blue line: the typical value for that calendar month (2003–2022 median). '
    + 'A gap means too few clear days that month to report a value. '
    + (hasHl ? 'The yellow dot is the month shown above; click any red point to jump to it.'
             : 'Click any red point to jump to that month.'),
    {fontSize: '12px', color: '#777', margin: '2px 0 8px 0'}));
}

/* ------------------------------------------------------------------- legend */

// Builds the legend bar image for the window [lo, hi] °C, coloured using the FIXED
// stretch of whichever `vis` object is passed (LST_VIS or ANOMALY_VIS) — so the bar
// shows exactly the slice of the true colour ramp that this window occupies, not a
// rescaled copy of the whole ramp. A view of 5-10 °C, for instance, sits near the
// pale middle of the -5..32 temperature ramp, so its legend bar should look pale,
// not fully blue-to-red.
function legendRampImage(lo, hi, vis) {
  return ee.Image.pixelLonLat().select('longitude')
    .multiply((hi - lo) / 100).add(lo)
    .visualize({min: vis.min, max: vis.max, palette: vis.palette});
}

// A fixed pixel width shared by the bar and every row under it, so a long caption
// wraps onto a second line instead of forcing the panel (and the gap after the
// ramp image) wider than the ramp itself — that mismatch was why the bar looked
// like it stopped short of the "max" label instead of reaching it.
var LEGEND_WIDTH = '160px';

var legend = ui.Panel({style: {position: 'bottom-left', padding: '7px 9px', width: '182px'}});
var legendTitle = ui.Label('Lake-surface temperature (°C)',
  {fontWeight: 'bold', fontSize: '12px', margin: '0 0 3px 0'});
legend.add(legendTitle);
var legendBar = ui.Thumbnail({
  image: legendRampImage(LST_VIS.min, LST_VIS.max, LST_VIS),
  params: {bbox: [0, 0, 100, 8], dimensions: '160x14'},
  style: {margin: '0', padding: '0', width: LEGEND_WIDTH, height: '14px'}
});
legend.add(legendBar);
var legendMinLabel = ui.Label(fmt(LST_VIS.min) + '°', {fontSize: '11px', stretch: 'horizontal', margin: '0'});
var legendMaxLabel = ui.Label(fmt(LST_VIS.max) + '°', {fontSize: '11px', margin: '0'});
var scaleRow = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'), style: {width: LEGEND_WIDTH, margin: '0'}});
scaleRow.add(legendMinLabel);
scaleRow.add(legendMaxLabel);
legend.add(scaleRow);
var legendCaption = ui.Label('this view\'s own range',
  {fontSize: '11px', color: '#999', margin: '2px 0 0 0', width: LEGEND_WIDTH});
legend.add(legendCaption);
mapPanel.add(legend);

// Called after every temperature-mode map layer redraw with that layer's actual
// min/max. The map itself always uses the fixed LST_VIS colour stretch (untouched
// here); this only re-crops the legend bar to the window that's actually on screen
// right now, and relabels its endpoints to match — the bar's colours stay absolute
// throughout.
function updateLegend(range) {
  legendTitle.setValue('Lake-surface temperature (°C)');
  var lo = range ? range.min : LST_VIS.min;
  var hi = range ? range.max : LST_VIS.max;
  legendBar.setImage(legendRampImage(lo, hi, LST_VIS));
  legendMinLabel.setValue(range ? fmt(lo) + '°' : '–');
  legendMaxLabel.setValue(range ? fmt(hi) + '°' : '–');
  legendCaption.setValue('this view\'s own range');
}

// Anomaly mode's legend is always the full fixed diverging scale, never cropped to
// the day's own range — unlike temperature, the centre (0 = normal) is itself the
// whole point, so narrowing the bar to what's on screen would hide where "normal"
// sits.
function showAnomalyLegend() {
  legendTitle.setValue('Anomaly vs. 2003–2022 normal (°C)');
  legendBar.setImage(legendRampImage(ANOMALY_VIS.min, ANOMALY_VIS.max, ANOMALY_VIS));
  // "<=" / ">=" rather than a bare number — values beyond the scale are real (e.g. the
  // 18 Feb 2024 event), they just show at the same full colour as the endpoint itself
  // rather than a further, uniquely extreme shade.
  legendMinLabel.setValue('≤' + signed(ANOMALY_VIS.min) + '°');
  legendMaxLabel.setValue('≥' + signed(ANOMALY_VIS.max) + '°');
  legendCaption.setValue('blue = colder than normal, red = warmer, pale = near normal');
}

/* --------------------------------------------------------------- wiring up */

function refresh() {
  var mode = modeSelect.getValue();
  var isDaily = mode === 'daily';
  dateGroup.style().set('shown', isDaily);
  dailyReadout.style().set('shown', isDaily);
  dailyChartPanel.style().set('shown', isDaily);
  passTablePanel.style().set('shown', isDaily);
  weatherPanel.style().set('shown', isDaily);
  overpassPanel.style().set('shown', isDaily);
  mapModeLabel.style().set('shown', isDaily);
  mapModeSelect.style().set('shown', isDaily);
  anomalyCoveragePanel.style().set('shown', isDaily);
  monthGroup.style().set('shown', !isDaily);
  monthlyReadout.style().set('shown', !isDaily);
  monthlyChartPanel.style().set('shown', !isDaily);
  if (isDaily) { updateDaily(); } else { updateMonthly(); }
}

modeSelect.onChange(refresh);
streamSelect.onChange(refresh);
// Debounced: dragging or scrolling the date through many days now recomputes only
// once, after you stop, instead of once per day passed over.
dateSlider.onChange(ui.util.debounce(refresh, 450));
monthYearSelect.onChange(refresh);

/* --------------------------------------------------------- initial landing */

// Open on the most recent day that actually has a Terra-morning reading, not on a
// fixed calendar date. A fixed date can fall on a heavily clouded pass, and a
// first-time visitor who lands on "No reading for this day" reasonably assumes the
// app is broken or has no data. One small Earth Engine call at start-up finds the
// latest day with data; if it fails, the slider keeps its LAST_EXPORT_DATE value.
DAILY.filter(ee.Filter.eq('stream_id', 'terra_day'))
  .sort('date_utc', false)
  .limit(1)
  .evaluate(function (fc) {
    var feats = (fc && fc.features) || [];
    if (feats.length && feats[0].properties && feats[0].properties.date_utc) {
      dateSlider.setValue(feats[0].properties.date_utc, false);
    }
    refresh();
  });
