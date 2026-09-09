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

// The four satellite passes. The map/pixel bands are the MODIS/061 daily LST
// products; the readout numbers all come from the pre-computed assets.
// Overpass times are the nominal local times for Lake Balaton's latitude — the
// exact minute varies a little day to day.
var STREAMS = {
  terra_day:   {label: 'Terra — morning (about 10:00 local)',        short: 'Terra morning',
                col: 'MODIS/061/MOD11A1', lst: 'LST_Day_1km',   qc: 'QC_Day',
                time: 'Day_view_time',   angle: 'Day_view_angle'},
  aqua_day:    {label: 'Aqua — early afternoon (about 13:00 local)', short: 'Aqua afternoon',
                col: 'MODIS/061/MYD11A1', lst: 'LST_Day_1km',   qc: 'QC_Day',
                time: 'Day_view_time',   angle: 'Day_view_angle'},
  terra_night: {label: 'Terra — late evening (about 22:00 local)',   short: 'Terra evening',
                col: 'MODIS/061/MOD11A1', lst: 'LST_Night_1km', qc: 'QC_Night',
                time: 'Night_view_time', angle: 'Night_view_angle'},
  aqua_night:  {label: 'Aqua — after midnight (about 01:00 local)',  short: 'Aqua night',
                col: 'MODIS/061/MYD11A1', lst: 'LST_Night_1km', qc: 'QC_Night',
                time: 'Night_view_time', angle: 'Night_view_angle'}
};
var STREAM_ORDER = ['terra_day', 'aqua_day', 'terra_night', 'aqua_night'];

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
 * The same clear-sky pixel-acceptance rule the anomaly engine uses, applied to one
 * daily MODIS image so the map can show which pixels went into that day's average.
 */
function acceptedLstC(image, s) {
  var raw = image.select(s.lst);
  var qc  = image.select(s.qc);
  var vt  = image.select(s.time);
  var va  = image.select(s.angle);

  var mandatory   = qc.bitwiseAnd(3);
  var dataQuality = qc.rightShift(2).bitwiseAnd(3);
  var emisError   = qc.rightShift(4).bitwiseAnd(3);
  var lstError    = qc.rightShift(6).bitwiseAnd(3);

  var ok = raw.gte(7500).and(raw.lte(65535))
    .and(vt.gte(0)).and(vt.lte(240))
    .and(va.gte(0)).and(va.lte(130))
    .and(mandatory.lte(1))
    .and(dataQuality.eq(0))
    .and(emisError.lte(1))
    .and(lstError.lte(1));

  return raw.multiply(0.02).subtract(273.15).updateMask(ok).rename('lst_c');
}

/* ---------------------------------------------------------------- UI layout */

ui.root.clear();

var mapPanel = ui.Map();
mapPanel.setOptions('TERRAIN');
mapPanel.setControlVisibility({layerList: true, zoomControl: true, mapTypeControl: false,
                               fullscreenControl: false, scaleControl: true});
mapPanel.centerObject(LAKE_GEOM, 10);

var panel = ui.Panel({style: {width: '410px', padding: '10px'}});
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
  {fontSize: '18px', fontWeight: 'bold', margin: '2px 0'}));
panel.add(ui.Label(
  'Surface temperature of Lake Balaton from the MODIS instruments on NASA’s Terra and '
  + 'Aqua satellites, January 2023 onward, compared with the 2003–2022 record for the '
  + 'same time of year.',
  {fontSize: '11px', color: '#555', margin: '0 0 3px 0'}));
panel.add(ui.Label(
  'Satellite coverage currently runs to ' + LAST_EXPORT_DATE
  + '. New months are added by hand, roughly monthly.',
  {fontSize: '11px', color: '#888', margin: '0 0 8px 0'}));

/* -- controls -- */
var modeSelect = ui.Select({
  items: [{label: 'Single day', value: 'daily'}, {label: 'Whole month', value: 'monthly'}],
  value: 'daily', style: {stretch: 'horizontal'}
});
panel.add(ui.Label('View', {fontWeight: 'bold', margin: '6px 0 2px 0'}));
panel.add(modeSelect);

var streamSelect = ui.Select({
  items: STREAM_ORDER.map(function (id) { return {label: STREAMS[id].label, value: id}; }),
  value: 'terra_day', style: {stretch: 'horizontal'}
});
panel.add(ui.Label('Satellite pass', {fontWeight: 'bold', margin: '8px 0 2px 0'}));
panel.add(streamSelect);

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
  {fontSize: '10px', color: '#888', margin: '1px 0 0 0'}));
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
var dailyReadout = ui.Panel({style: {margin: '8px 0 4px 0', padding: '7px',
  backgroundColor: '#f6f6f6', border: '1px solid #ddd'}});
var dailyChartPanel = ui.Panel();
var passTablePanel  = ui.Panel({style: {margin: '4px 0'}});
panel.add(dailyReadout);
panel.add(dailyChartPanel);
panel.add(passTablePanel);

/* -- monthly section -- */
var monthlyReadout = ui.Panel({style: {margin: '8px 0 4px 0', padding: '7px',
  backgroundColor: '#f6f6f6', border: '1px solid #ddd'}});
var monthlyChartPanel = ui.Panel();
panel.add(monthlyReadout);
panel.add(monthlyChartPanel);

/* -- about -- */
panel.add(ui.Label('About this tool', {fontWeight: 'bold', fontSize: '12px', margin: '12px 0 2px 0'}));
panel.add(ui.Label(
  'The lake-surface temperature comes from the MODIS instruments on NASA’s Terra and Aqua '
  + 'satellites (1 km pixels). For each satellite pass, the clear-sky pixels over the lake are '
  + 'averaged. "Normal" is the 2003–2022 record for the same time of year (a ±5-day '
  + 'window around the calendar day). Each of the four passes keeps its own separate history and '
  + 'is never mixed with the others — a warm afternoon and a warm night are different things. '
  + 'Days with heavy cloud have no reading.',
  {fontSize: '10px', color: '#888', margin: '0'}));
panel.add(ui.Label(
  'Validated (2026): the monthly averages track independent Landsat surface temperature within '
  + '~0.5 °C over 2003–2024, and every flagged warm anomaly matches the Copernicus European '
  + 'climate record. The tool is validated for spotting unusual readings, not for the exact '
  + 'temperature to a fraction of a degree.',
  {fontSize: '10px', color: '#888', margin: '4px 0 0 0'}));

/* ------------------------------------------------------- readout components */

function kv(key, value, valueColour) {
  var row = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'), style: {margin: '1px 0'}});
  row.add(ui.Label(key, {color: '#666', fontSize: '11px', margin: '0 6px 0 0', width: '150px'}));
  row.add(ui.Label(value, {fontSize: '11px', fontWeight: 'bold', margin: '0',
                           color: valueColour || '#000', stretch: 'horizontal'}));
  return row;
}
function bigLabel(text, colour) {
  return ui.Label(text, {fontSize: '14px', fontWeight: 'bold', color: colour || '#000', margin: '2px 0 4px 0'});
}
function lowCoverageNote() {
  return ui.Label(
    '*  "low coverage" day = fewer than 15% of the lake (about 700 pixels) had a clear, '
    + 'quality-checked view from this satellite pass; cloud, ice or QA masking removed the '
    + 'rest. These days are still counted in the monthly averages above.',
    {fontSize: '9px', color: '#888', margin: '6px 0 0 0'});
}

function differenceSentence(delta) {
  var sign = delta >= 0 ? '+' : '−';
  return sign + fmt(Math.abs(delta)) + ' °C ' + (delta >= 0 ? 'above' : 'below') + ' normal';
}
function rankSentence(pct, n) {
  if (pct >= 99.5) { return 'the warmest of the ' + n + ' readings on record for this time of year'; }
  if (pct <= 0.5)  { return 'the coldest of the ' + n + ' readings on record for this time of year'; }
  return 'warmer than about ' + Math.round(pct) + '% of the ' + n
    + ' readings on record for this time of year';
}
function coverageSentence(confidence, fraction, pixels) {
  var pct = (fraction * 100).toFixed(0);
  if (confidence === 'ok')  {
    return 'Good — ' + pct + '% of the lake had a clear view (' + pixels + ' of ~700 pixels)';
  }
  if (confidence === 'low') {
    return 'LOW — only ' + pct + '% of the lake had a clear view (' + pixels
      + ' of ~700 pixels); treat this reading with caution';
  }
  return 'No clear view of the lake';
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

  drawDailyMap(streamId, dstr);

  dailyReadout.clear();
  dailyReadout.add(ui.Label('Loading…', {color: '#999', fontSize: '11px'}));
  passTablePanel.clear();
  passTablePanel.add(ui.Label('Loading…', {color: '#999', fontSize: '11px'}));
  dailyChartPanel.clear();
  dailyChartPanel.add(ui.Label('Loading…', {color: '#999', fontSize: '11px'}));

  loadMonth(ym, function (byStream) {
    fillDailyReadout(streamId, dstr, dayName, byStream[streamId].byDate[dstr]);
    fillPassTable(dstr, byStream);
    drawSeriesChart(dailyChartPanel, byStream[streamId].list,
      ymLabel(ym) + ' — ' + STREAMS[streamId].short, dstr);
  });
}

function drawDailyMap(streamId, dstr) {
  var s = STREAMS[streamId];
  var start = ee.Date(dstr);
  var col = ee.ImageCollection(s.col).filterDate(start, start.advance(1, 'day'));
  col.size().evaluate(function (n) {
    if (!n) { setPixelLayer(null); updateLegend(null); return; }
    var lstC = acceptedLstC(ee.Image(col.first()), s).clip(LAKE_GEOM);
    setPixelLayer(lstC, s.short + ' — ' + dstr);   // fixed LST_VIS colour scale
    computeLstRange(lstC, updateLegend);           // informational range only
  });
}

function fillDailyReadout(streamId, dstr, dayName, p) {
  dailyReadout.clear();
  dailyReadout.add(ui.Label(STREAMS[streamId].short + '  ·  ' + dstr,
    {fontWeight: 'bold', fontSize: '12px', margin: '0 0 4px 0'}));

  if (!p) {
    dailyReadout.add(bigLabel('No reading for this day', '#999'));
    dailyReadout.add(ui.Label(
      dstr > LAST_EXPORT_DATE
        ? 'Later than the last data update (' + LAST_EXPORT_DATE + ').'
        : 'The lake was too cloudy on this pass for a reliable reading.',
      {fontSize: '10px', color: '#666'}));
    return;
  }

  var raw = p.classification;
  // Both reference values are the 2003-2022 record for this calendar day AND the
  // 5 days either side of it (about 110-195 past readings) — never just this one
  // date — so the readout says so every time, not just in the footer.
  var windowNote = dayName + ' ± 5 days, 2003–2022';

  dailyReadout.add(bigLabel(LABEL_DISPLAY[raw] || raw, LABEL_COLOUR[raw] || '#000'));
  // The label is a threshold band; show the percentile next to it so a reading that
  // sits close to a 90 / 95 / 99 boundary reads as borderline, not as a hard fact.
  dailyReadout.add(ui.Label(
    percentileText(p.historical_percentile)
    + (p.percentile_confidence && p.percentile_confidence !== 'full'
        ? ' (from a small sample — less certain)' : ''),
    {fontSize: '10px', color: '#666', margin: '0 0 4px 0'}));
  dailyReadout.add(kv('Lake-surface temperature', fmt(p.daily_lst_c) + ' °C'));
  dailyReadout.add(kv('Compared with normal', differenceSentence(p.anomaly_vs_median_c)));
  dailyReadout.add(kv('', 'measured − median of the ' + windowNote + ' record ('
    + fmt(p.reference_median_lst_c) + ' °C)', '#888'));
  dailyReadout.add(kv('Also vs. the mean', differenceSentence(p.anomaly_vs_mean_c)));
  dailyReadout.add(kv('', 'measured − mean of the same ' + windowNote + ' record ('
    + fmt(p.reference_mean_lst_c) + ' °C)', '#888'));
  dailyReadout.add(kv('Where it ranks',
    rankSentence(p.historical_percentile, p.historical_n)));
  dailyReadout.add(kv('Clear-sky coverage',
    coverageSentence(p.confidence, p.valid_water_fraction, p.accepted_pixel_count),
    p.confidence === 'ok' ? '#2e7d32' : '#cc4c02'));
}

function fillPassTable(dstr, byStream) {
  passTablePanel.clear();
  passTablePanel.add(ui.Label('The same day seen by each satellite pass',
    {fontWeight: 'bold', fontSize: '12px', margin: '4px 0 1px 0'}));
  passTablePanel.add(ui.Label(
    'Each pass is measured and judged on its own — they are never averaged together.',
    {fontSize: '10px', color: '#888', margin: '0 0 3px 0'}));

  // Every cell — header and body — sets margin:'0' and the same width, so the
  // columns line up. (Leaving the header labels on the default label margin was
  // why "temp" / "vs normal" sat shifted right of the numbers under them.)
  var C_PASS = '92px', C_COV = '34px', C_TEMP = '44px', C_NORM = '50px';
  function cell(text, w, extra) {
    var st = {fontSize: '10px', margin: '0'};
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

  var anyLow = false;
  STREAM_ORDER.forEach(function (id) {
    var p = byStream[id].byDate[dstr];
    var low = !!(p && p.confidence === 'low');
    if (low) { anyLow = true; }
    var row = ui.Panel({layout: ui.Panel.Layout.flow('horizontal'), style: {margin: '1px 0'}});
    // The low-coverage marker belongs to the pass, not to the difference — it is
    // about how much of the lake that overpass saw, not about the number itself.
    row.add(cell(STREAMS[id].short + (low ? ' *' : ''), C_PASS,
      low ? {color: '#cc4c02'} : null));
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
    '"lake" = share of the lake this pass had a clear, quality-checked view of. '
    + '"rank" is where the reading sits among the 2003–2022 record for this time of year — '
    + 'the verdict is a band around the 90th / 95th / 99th percentile, so a rank near a '
    + 'boundary can sit either side.'
    + (anyLow ? '  *  below 15% ("low coverage") — the reading is shown but is less certain.' : ''),
    {fontSize: '9px', color: '#888', margin: '4px 0 0 0'}));
}

/* ------------------------------------------------------------ monthly view */

function updateMonthly() {
  var streamId = streamSelect.getValue();
  var ym = monthYearSelect.getValue();
  var year = ym.slice(0, 4);
  var monthName = ymLabel(ym);

  monthlyReadout.clear();
  monthlyReadout.add(ui.Label('Loading…', {color: '#999', fontSize: '11px'}));
  monthlyChartPanel.clear();
  monthlyChartPanel.add(ui.Label('Loading…', {color: '#999', fontSize: '11px'}));

  loadYear(year, function (byStream) {
    var p = byStream[streamId].byMonth[ym];
    fillMonthlyReadout(streamId, monthName, p);
    drawMonthlyMap(streamId, p);
    drawMonthlySeriesChart(monthlyChartPanel, byStream[streamId].list,
      year + ' — ' + STREAMS[streamId].short, ym);
  });
}

function fillMonthlyReadout(streamId, monthName, p) {
  monthlyReadout.clear();
  monthlyReadout.add(ui.Label(STREAMS[streamId].short + '  ·  ' + monthName,
    {fontWeight: 'bold', fontSize: '12px', margin: '0 0 4px 0'}));

  if (!p) { monthlyReadout.add(bigLabel('No summary for this month', '#999')); return; }
  if (p.state !== 'reported') {
    monthlyReadout.add(bigLabel('Not enough clear days to summarise', '#cc4c02'));
    monthlyReadout.add(kv('Clear days', p.valid_day_count + ' of ' + p.calendar_day_count
      + (p.low_coverage_day_count > 0
          ? '  (' + p.low_coverage_day_count + ' low coverage*)' : '')));
    if (p.low_coverage_day_count > 0) { monthlyReadout.add(lowCoverageNote()); }
    return;
  }
  monthlyReadout.add(kv('Average lake-surface temp', fmt(p.monthly_mean_lst_c) + ' °C'));
  monthlyReadout.add(kv('Compared with normal',
    (p.monthly_mean_anomaly_vs_median_c >= 0 ? '+' : '−')
    + fmt(Math.abs(p.monthly_mean_anomaly_vs_median_c))
    + ' °C vs the 2003–2022 median for this month'));
  monthlyReadout.add(kv('', '(vs the mean: '
    + (p.monthly_mean_anomaly_vs_mean_c >= 0 ? '+' : '−')
    + fmt(Math.abs(p.monthly_mean_anomaly_vs_mean_c)) + ' °C)', '#888'));
  monthlyReadout.add(kv('Clear days used',
    p.valid_day_count + ' of ' + p.calendar_day_count
    + (p.low_coverage_day_count > 0
        ? ' — ' + p.low_coverage_day_count + ' of them low coverage*' : '')
    + '  (' + (p.missing_or_cloud_fraction * 100).toFixed(0) + '% missing or cloudy)'));
  if (typeof p.mean_valid_water_fraction === 'number') {
    monthlyReadout.add(kv('', 'On a clear day about '
      + (p.mean_valid_water_fraction * 100).toFixed(0)
      + '% of the lake was seen, on average', '#888'));
  }
  if (p.low_coverage_day_count >= p.valid_day_count && p.valid_day_count > 0) {
    monthlyReadout.add(ui.Label(
      'Every clear day this month saw less than 15% of the lake — this monthly '
      + 'summary rests on very thin coverage; treat it with caution.',
      {fontSize: '10px', color: '#cc4c02', margin: '2px 0 4px 0'}));
  }
  monthlyReadout.add(kv('Warm-or-above days', String(p.warm_observation_count)));
  monthlyReadout.add(kv('Warmest reading',
    fmt(p.hottest_observation_lst_c) + ' °C on ' + p.hottest_observation_date));
  monthlyReadout.add(kv('Biggest single-day jump',
    '+' + fmt(p.max_anomaly_vs_median_c) + ' °C on ' + p.max_anomaly_vs_median_date));
  if (p.low_coverage_day_count > 0) { monthlyReadout.add(lowCoverageNote()); }
}

function drawMonthlyMap(streamId, p) {
  var d = p && p.hottest_observation_date;
  if (!d) { setPixelLayer(null); updateLegend(null); return; }
  var s = STREAMS[streamId];
  var start = ee.Date(d);
  var col = ee.ImageCollection(s.col).filterDate(start, start.advance(1, 'day'));
  col.size().evaluate(function (m) {
    if (!m) { setPixelLayer(null); updateLegend(null); return; }
    var lstC = acceptedLstC(ee.Image(col.first()), s).clip(LAKE_GEOM);
    setPixelLayer(lstC, s.short + ' — warmest day ' + d);   // fixed LST_VIS colour scale
    computeLstRange(lstC, updateLegend);                    // informational range only
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
    ? ['Date', 'Measured', 'Typical (2003–2022 median)', 'Selected day']
    : ['Date', 'Measured', 'Typical (2003–2022 median)']];
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
    height: 210,
    interpolateNulls: false,
    series: series,
    hAxis: {slantedText: true, slantedTextAngle: 60, textStyle: {fontSize: 8}},
    vAxis: {title: 'Lake-surface temperature (°C)', titleTextStyle: {fontSize: 10}},
    legend: {position: 'top', textStyle: {fontSize: 10}},
    chartArea: {left: 45, right: 12, top: 40, bottom: 55}
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
    {fontSize: '10px', color: '#777', margin: '2px 0 8px 0'}));
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
    ? ['Month', 'Measured', 'Typical (2003–2022 median)', 'Selected month']
    : ['Month', 'Measured', 'Typical (2003–2022 median)']];
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
    height: 210,
    interpolateNulls: false,
    series: series,
    hAxis: {slantedText: true, slantedTextAngle: 60, textStyle: {fontSize: 9}},
    vAxis: {title: 'Lake-surface temperature (°C)', titleTextStyle: {fontSize: 10}},
    legend: {position: 'top', textStyle: {fontSize: 10}},
    chartArea: {left: 45, right: 12, top: 40, bottom: 45}
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
    {fontSize: '10px', color: '#777', margin: '2px 0 8px 0'}));
}

/* ------------------------------------------------------------------- legend */

// Builds the legend bar image for the window [lo, hi] °C, but always colours it
// using the FIXED -5..32 stretch (LST_VIS.min/max) — so the bar shows exactly the
// slice of the true colour ramp that this window occupies, not a rescaled copy of
// the whole ramp. A view of 5-10 °C, for instance, sits near the pale middle of
// the -5..32 ramp, so its legend bar should look pale, not fully blue-to-red.
function legendRampImage(lo, hi) {
  return ee.Image.pixelLonLat().select('longitude')
    .multiply((hi - lo) / 100).add(lo)
    .visualize({min: LST_VIS.min, max: LST_VIS.max, palette: LST_VIS.palette});
}

// A fixed pixel width shared by the bar and every row under it, so a long caption
// wraps onto a second line instead of forcing the panel (and the gap after the
// ramp image) wider than the ramp itself — that mismatch was why the bar looked
// like it stopped short of the "max" label instead of reaching it.
var LEGEND_WIDTH = '140px';

var legend = ui.Panel({style: {position: 'bottom-left', padding: '6px 8px', width: '156px'}});
legend.add(ui.Label('Lake-surface temperature (°C)',
  {fontWeight: 'bold', fontSize: '10px', margin: '0 0 3px 0'}));
var legendBar = ui.Thumbnail({
  image: legendRampImage(LST_VIS.min, LST_VIS.max),
  params: {bbox: [0, 0, 100, 8], dimensions: '140x12'},
  style: {margin: '0', padding: '0', width: LEGEND_WIDTH, height: '12px'}
});
legend.add(legendBar);
var legendMinLabel = ui.Label(fmt(LST_VIS.min) + '°', {fontSize: '9px', stretch: 'horizontal', margin: '0'});
var legendMaxLabel = ui.Label(fmt(LST_VIS.max) + '°', {fontSize: '9px', margin: '0'});
var scaleRow = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'), style: {width: LEGEND_WIDTH, margin: '0'}});
scaleRow.add(legendMinLabel);
scaleRow.add(legendMaxLabel);
legend.add(scaleRow);
legend.add(ui.Label('this view\'s own range',
  {fontSize: '9px', color: '#999', margin: '2px 0 0 0', width: LEGEND_WIDTH}));
mapPanel.add(legend);

// Called after every map layer redraw with that layer's actual min/max. The map
// itself always uses the fixed LST_VIS colour stretch (untouched here); this only
// re-crops the legend bar to the window that's actually on screen right now, and
// relabels its endpoints to match — the bar's colours stay absolute throughout.
function updateLegend(range) {
  var lo = range ? range.min : LST_VIS.min;
  var hi = range ? range.max : LST_VIS.max;
  legendBar.setImage(legendRampImage(lo, hi));
  legendMinLabel.setValue(range ? fmt(lo) + '°' : '–');
  legendMaxLabel.setValue(range ? fmt(hi) + '°' : '–');
}

/* --------------------------------------------------------------- wiring up */

function refresh() {
  var mode = modeSelect.getValue();
  var isDaily = mode === 'daily';
  dateGroup.style().set('shown', isDaily);
  dailyReadout.style().set('shown', isDaily);
  dailyChartPanel.style().set('shown', isDaily);
  passTablePanel.style().set('shown', isDaily);
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
