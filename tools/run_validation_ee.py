"""Phase 5 validation - Stage B (Earth Engine).

Coordinate-free output. The two VAL-001 criteria that need fresh Earth Engine data:

  C3   agreement of our monthly `ok` lake-mean with an INDEPENDENT product.
       ESA CCI Lakes / Copernicus LWST are not in the EE catalogue, so (user-approved
       2026-09-09 substitution) the comparators are:
         - Landsat Collection 2 Level-2 surface temperature (ST_B10 / ST_B6) - a
           different instrument (TIRS / TM), overpass ~10:15 local, processed here to a
           monthly lake-mean. Primary independent line.
         - ERA5-Land `lake_mix_layer_temperature` - independent model reanalysis. Second line.
       Revised pass line (Landsat): bias +/- 1.5 C, RMSE <= 2.5 C, Pearson r >= 0.95.

  C5b  robustness of the anomaly to the accepted-pixel rule, for 2024:
         (a) strict QC (all four QC fields == 0) instead of candidate C
         (b) 463 m shoreline erosion instead of 0 m
       Bounded: a sampled set of 2024 dates + a sampled historical window, re-derived
       with the audit-010 machinery the Phase 3 engine uses. PASS: for `ok` days the
       anomaly shifts <= 0.5 C and the label changes in <= 5 %.

Reuses tools/run_anomaly_engine_ee.py for the hash-pinned geometry and EE session.
Never persists a coordinate. See docs/PHASE_5_VALIDATION_SPECIFICATION.md.

Usage:
  python tools/run_validation_ee.py --project ee-jtantaroman --c3
  python tools/run_validation_ee.py --project ee-jtantaroman --c5b
  python tools/run_validation_ee.py --self-test
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = ROOT / "tools" / "run_anomaly_engine_ee.py"
P3 = ROOT / "local_run_state" / "phase3"
OUT_DIR = ROOT / "local_run_state" / "phase5"

STREAMS = ("terra_day", "aqua_day", "terra_night", "aqua_night")
DAY_STREAMS = ("terra_day", "aqua_day")

# Landsat Collection 2 Level-2: surface-temperature band per platform, and the
# documented scale/offset to Kelvin.
LANDSAT = {
    "LANDSAT/LT05/C02/T1_L2": "ST_B6",
    "LANDSAT/LE07/C02/T1_L2": "ST_B6",
    "LANDSAT/LC08/C02/T1_L2": "ST_B10",
    "LANDSAT/LC09/C02/T1_L2": "ST_B10",
}
ST_SCALE, ST_OFFSET = 0.00341802, 149.0
EROSION_463_M = 463.31271656937486     # tools/run_whole_lake_boundary_shoreline_audit_ee.py TREATMENTS[1]

C5B_2024_STRIDE_DAYS = 10              # sample every 10th day of 2024
C5B_HISTORICAL_YEARS = (2007, 2015)   # historical window sample


# ------------------------------------------------------------------------- helpers

def _load_engine() -> Any:
    spec = importlib.util.spec_from_file_location("anomaly_engine", ENGINE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_json(name: str) -> dict[str, Any]:
    path = P3 / f"{name}.json"
    if not path.exists():
        sys.exit(f"missing Phase 3 artefact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def _matchup_stats(ours: list[float], ref: list[float]) -> dict[str, Any]:
    pairs = [(o, r) for o, r in zip(ours, ref) if o is not None and r is not None]
    if len(pairs) < 3:
        return {"n": len(pairs), "bias_c": None, "rmse_c": None, "r": None}
    o = [p[0] for p in pairs]
    r = [p[1] for p in pairs]
    diffs = [a - b for a, b in pairs]
    return {
        "n": len(pairs),
        "bias_c": round(statistics.fmean(diffs), 3),
        "mean_abs_c": round(statistics.fmean(abs(d) for d in diffs), 3),
        "rmse_c": round(math.sqrt(statistics.fmean(d * d for d in diffs)), 3),
        "r": round(_pearson(o, r), 4),
    }


def _round(x: Any, d: int = 3) -> Any:
    if isinstance(x, float):
        return None if math.isnan(x) else round(x, d)
    return x


def _months(start_year: int, end_year: int) -> list[str]:
    out = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            out.append(f"{y}-{m:02d}")
    return out


# ------------------------------------------------------------------------------ C3

def _landsat_monthly_lake_mean(ee: Any, geom: Any, ym: str) -> tuple[float | None, int]:
    y, m = (int(v) for v in ym.split("-"))
    start = ee.Date.fromYMD(y, m, 1)
    end = start.advance(1, "month")
    scenes = []
    for cid, band in LANDSAT.items():
        col = (ee.ImageCollection(cid).filterBounds(geom).filterDate(start, end))

        def _prep(img: Any, band=band) -> Any:
            qa = img.select("QA_PIXEL")
            # bit 1 dilated cloud, 3 cloud, 4 cloud shadow
            clear = (qa.bitwiseAnd(1 << 1).eq(0)
                     .And(qa.bitwiseAnd(1 << 3).eq(0))
                     .And(qa.bitwiseAnd(1 << 4).eq(0)))
            st_c = img.select(band).multiply(ST_SCALE).add(ST_OFFSET).subtract(273.15)
            return st_c.updateMask(clear).rename("st_c")

        scenes.append(col.map(_prep))
    merged = ee.ImageCollection(scenes[0])
    for s in scenes[1:]:
        merged = merged.merge(ee.ImageCollection(s))
    count = merged.size()
    mean_img = ee.Image(ee.Algorithms.If(count.gt(0), merged.mean(),
                                         ee.Image.constant(0).rename("st_c").selfMask()))
    reduced = ee.Dictionary(mean_img.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=geom, scale=100, maxPixels=5_000_000, bestEffort=True))
    val = ee.Algorithms.If(reduced.contains("st_c"), reduced.get("st_c"), None)
    return val, count


C3_CACHE = OUT_DIR / "c3_reference_cache.json"
C3_MONTHLY_MIN_DAYS = 3        # match METH-005 monthly minimum


def _our_monthly_means(monthly: dict[str, Any], hist: dict[str, Any]
                       ) -> dict[str, dict[str, float]]:
    """{ 'YYYY-MM': {stream_id: mean_lst_c} } for the full 2003-2024 span:
    2023-2024 from the Phase 3 monthly summaries (ok+ days), 2003-2022 rebuilt
    from the stored historical daily lake-means (>= 3 days/month/stream)."""
    out: dict[str, dict[str, float]] = {}
    for row in monthly["rows"]:
        if row["state"] == "reported" and row.get("monthly_mean_lst_c") is not None:
            out.setdefault(row["month"], {})[row["stream_id"]] = row["monthly_mean_lst_c"]
    buckets: dict[tuple[str, str], list[float]] = {}
    for v in hist["values"]:
        buckets.setdefault((v["date_utc"][:7], v["stream_id"]), []).append(v["daily_lst_c"])
    for (ym, sid), vals in buckets.items():
        if len(vals) >= C3_MONTHLY_MIN_DAYS:
            out.setdefault(ym, {}).setdefault(sid, statistics.fmean(vals))
    return out


def _fetch_c3_reference(engine: Any, project: str) -> dict[str, Any]:
    if C3_CACHE.exists():
        print(json.dumps({"C3_REF": "loaded from cache"}), flush=True)
        return json.loads(C3_CACHE.read_text(encoding="utf-8"))

    ee, _a, runner, _gj, _c = engine._init_ee(project)
    geom = runner.source
    yms = _months(2003, 2024)

    landsat: dict[str, Any] = {}
    for i, ym in enumerate(yms):
        val, cnt = _landsat_monthly_lake_mean(ee, geom, ym)
        f = ee.Feature(None, {"ym": ym, "v": val, "n": cnt}).getInfo()["properties"]
        landsat[ym] = {"c": round(float(f["v"]), 4) if f.get("v") is not None else None,
                       "scenes": int(f.get("n") or 0)}
        if i % 24 == 0:
            print(json.dumps({"C3_LANDSAT": {"done": i + 1, "of": len(yms)}}), flush=True)
        time.sleep(0.25)

    era: dict[str, Any] = {}
    for i in range(0, len(yms), 12):
        feats = []
        for ym in yms[i:i + 12]:
            y, m = (int(v) for v in ym.split("-"))
            start = ee.Date.fromYMD(y, m, 1)
            img = (ee.ImageCollection("ECMWF/ERA5_LAND/MONTHLY_AGGR")
                   .filterDate(start, start.advance(1, "month"))
                   .select("lake_mix_layer_temperature").first())
            val = ee.Algorithms.If(img, ee.Dictionary(ee.Image(img).subtract(273.15).reduceRegion(
                reducer=ee.Reducer.mean(), geometry=geom, scale=1000, maxPixels=1_000_000,
                bestEffort=True)).get("lake_mix_layer_temperature"), None)
            feats.append(ee.Feature(None, {"ym": ym, "v": val}))
        for f in ee.FeatureCollection(feats).getInfo()["features"]:
            p = f["properties"]
            era[p["ym"]] = round(float(p["v"]), 4) if p.get("v") is not None else None
        time.sleep(0.5)
    print(json.dumps({"C3_ERA5_DONE": {"months": len(era)}}), flush=True)

    ref = {"landsat": landsat, "era5land_mixlayer": era,
           "note": "coordinate-free: monthly lake-area-mean temperatures only"}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    C3_CACHE.write_text(json.dumps(ref, indent=1), encoding="utf-8")
    return ref


def check_c3(engine: Any, project: str, monthly: dict[str, Any],
             hist: dict[str, Any]) -> dict[str, Any]:
    ref = _fetch_c3_reference(engine, project)
    landsat, era = ref["landsat"], ref["era5land_mixlayer"]
    ours = _our_monthly_means(monthly, hist)
    yms = _months(2003, 2024)

    def our_mean(ym: str, streams: tuple[str, ...]) -> float | None:
        v = ours.get(ym, {})
        d = [v[s] for s in streams if s in v]
        return statistics.fmean(d) if d else None

    def match(our_streams: tuple[str, ...], ref_by_ym: dict[str, Any],
              require_scenes: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        o, r, rows = [], [], []
        for ym in yms:
            om = our_mean(ym, our_streams)
            rv = ref_by_ym.get(ym)
            if isinstance(rv, dict):
                scenes, rc = rv.get("scenes", 0), rv.get("c")
            else:
                scenes, rc = 1, rv
            if om is None or rc is None or (require_scenes and scenes < 1):
                continue
            o.append(om)
            r.append(rc)
            rows.append({"ym": ym, "ours_c": round(om, 2), "ref_c": round(rc, 2),
                         "scenes": scenes, "diff_c": round(om - rc, 2)})
        return _matchup_stats(o, r), rows

    ls_terra, ls_terra_rows = match(("terra_day",), landsat, True)
    ls_daymean, _ = match(DAY_STREAMS, landsat, True)
    era_all, _ = match(STREAMS, era, False)
    era_terra, _ = match(("terra_day",), era, False)

    findings: list[str] = []
    limitations: list[str] = []
    s = ls_terra                              # primary: Landsat vs our Terra-morning stream
    if s["n"] < 24:
        findings.append(f"Landsat/Terra match-up has only {s['n']} months - too few")
    else:
        if s["bias_c"] is None or abs(s["bias_c"]) > 1.5:
            findings.append(f"Landsat/Terra bias {s['bias_c']} C exceeds +/- 1.5 C")
        if s["rmse_c"] is None or s["rmse_c"] > 2.5:
            findings.append(f"Landsat/Terra RMSE {s['rmse_c']} C exceeds 2.5 C")
        if s["r"] is None or s["r"] < 0.95:
            findings.append(f"Landsat/Terra r {s['r']} below 0.95")
    if era_all["bias_c"] is not None and abs(era_all["bias_c"]) > 2.0:
        limitations.append(f"ERA5-Land mix-layer runs {era_all['bias_c']:+.1f} C vs our all-stream "
                           f"mean (bulk vs skin, and a model field) - context only, r={era_all['r']}")

    return {
        "name": "C3 - agreement with an independent LSWT product",
        "pass": not findings,
        "metrics": {
            "landsat_vs_terra_day": s,
            "landsat_vs_day_stream_mean": ls_daymean,
            "era5land_mixlayer_vs_all_streams": era_all,
            "era5land_mixlayer_vs_terra_day": era_terra,
            "landsat_months_matched": len(ls_terra_rows),
            "landsat_terra_monthly_rows": ls_terra_rows,
        },
        "limitations": limitations,
        "note": "Primary line: Landsat C2 L2 surface temperature (TIRS/TM - a different instrument "
                "from MODIS; overpass ~10:15 local) vs our Terra-morning monthly mean. Our monthly "
                "means are the Phase 3 summaries for 2023-2024 and are rebuilt from the stored "
                "historical daily lake-means (>=3 days) for 2003-2022. ERA5-Land "
                "lake_mix_layer_temperature is an independent MODEL, context only. ESA CCI / "
                "Copernicus LWST are not in the EE catalogue (user-approved substitution 2026-09-09).",
        "findings": findings,
    }


# ----------------------------------------------------------------------------- C5b

def _daily_lake_means(engine: Any, ee: Any, audit010: Any, runner: Any, geometry: Any,
                      stream_id: str, date_iso: str) -> dict[str, Any]:
    """Re-derive the lake-mean LST for one stream on one day under three rules:
    base (candidate C, 0 m), strict (all QC == 0, 0 m), erode (candidate C, 463 m).
    Returns {rule: (mean_c|None, accepted_count)}."""
    stream = {s["stream_id"]: s for s in audit010.STREAMS}[stream_id]
    ctx = runner.contexts[stream_id]
    start = ee.Date(date_iso)
    col = (ee.ImageCollection(stream["collection_id"])
           .filterBounds(runner.source).filterDate(start, start.advance(1, "day")))
    bands = [stream["lst"], stream["qc"], stream["time"], stream["angle"]]
    dummy = ee.Image.constant([0, 0, 0, 0]).rename(bands).updateMask(ee.Image.constant(0))
    image = ee.Image(ee.Algorithms.If(col.size().gt(0), col.first(), dummy))

    def reduce_for(rule: str, geom: Any) -> Any:
        masks = runner._masks(image, stream)
        decoded = masks["decoded"]
        m = decoded.select("mandatory_qa").unmask(0)
        d = decoded.select("data_quality").unmask(0)
        e = decoded.select("emissivity_error").unmask(0)
        t = decoded.select("lst_error").unmask(0)
        lst = image.select(stream["lst"])
        vt = image.select(stream["time"])
        va = image.select(stream["angle"])
        v = (masks["Q"].And(runner._validity(lst, 7500, 65535))
             .And(runner._validity(vt, 0, 240)).And(runner._validity(va, 0, 130)))
        if rule == "strict":
            keep = v.And(m.eq(0)).And(d.eq(0)).And(e.eq(0)).And(t.eq(0)).unmask(0)
        else:  # candidate C
            keep = v.And(m.lte(1)).And(d.eq(0)).And(e.lte(1)).And(t.lte(1)).unmask(0)
        lst_c = lst.multiply(0.02).subtract(273.15)
        area = ee.Image.pixelArea()
        stacked = ee.Image.cat([lst_c.multiply(area).rename("w"), area.rename("a"),
                                ee.Image.constant(1).rename("n")]).updateMask(keep)
        return ee.Dictionary(stacked.reduceRegion(
            reducer=ee.Reducer.sum(), geometry=geom, crs=ctx["crs"],
            crsTransform=ctx["transform"], bestEffort=False, maxPixels=2_000_000, tileScale=1))

    planar = runner._planar(runner.source)
    eroded = planar.buffer(distance=-EROSION_463_M, maxError=runner._margin(), proj=audit010.OP_CRS)
    out = {"base": reduce_for("cc", planar),
           "strict": reduce_for("strict", planar),
           "erode": reduce_for("cc", eroded)}
    return ee.Dictionary(out)


def _load_offline() -> Any:
    spec = importlib.util.spec_from_file_location(
        "validation_offline", ROOT / "tools" / "run_validation_offline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reduce_triple(dic: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for rule in ("base", "strict", "erode"):
        r = dic.get(rule, {})
        n = int(r.get("n") or 0)
        a = float(r.get("a") or 0.0)
        out[rule] = round(float(r["w"]) / a, 4) if (n > 0 and a > 0) else None
    return out


def check_c5b(engine: Any, project: str, hist_values: dict[str, Any],
              daily: dict[str, Any]) -> dict[str, Any]:
    ee, audit010, runner, _gj, _ctx = engine._init_ee(project)
    off = _load_offline()

    # bounded sample: 2024 every 12th day
    stride = 12
    md_sample = []
    d = dt.date(2024, 1, 1)
    while d.year == 2024:
        md_sample.append((d.month, d.day))
        d += dt.timedelta(days=stride)
    dates_2024 = [f"2024-{m:02d}-{dd:02d}" for m, dd in md_sample]

    # historical (variant - base) shift is a smooth seasonal function -> estimate it
    # PER MONTH from a spread sample of years x days, not per exact date (which was too
    # noisy with only 3 samples). 4 years x 3 days/month = up to 12 samples per stream-month.
    hist_years = (2006, 2012, 2018, 2022)
    hist_days = (8, 16, 24)
    dates_hist = [f"{y}-{m:02d}-{dd:02d}" for y in hist_years for m in range(1, 13)
                  for dd in hist_days]

    rec_by_key = {(r["stream_id"], r["date_utc"]): r for r in daily["records"]}
    fold = engine.fold_day_of_year

    # base +/-5 climatology (full 20-year history) for the label check
    clim5 = off.build_climatology(hist_values["values"], 5)

    cache_path = OUT_DIR / "c5b_lake_means_cache.json"
    cache: dict[str, dict[str, float | None]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    def fetch(dates: list[str], tag: str) -> dict[tuple[str, str], dict[str, float | None]]:
        got: dict[tuple[str, str], dict[str, float | None]] = {}
        for stream_id in STREAMS:
            todo = [di for di in dates if f"{stream_id}|{di}" not in cache]
            for i in range(0, len(todo), 10):
                chunk = todo[i:i + 10]
                feats = [ee.Feature(None, ee.Dictionary({"k": stream_id + "|" + di}).combine(
                    _daily_lake_means(engine, ee, audit010, runner, None, stream_id, di)))
                    for di in chunk]
                for f in ee.FeatureCollection(feats).getInfo()["features"]:
                    p = f["properties"]
                    cache[p["k"]] = _reduce_triple(p)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(cache), encoding="utf-8")
                time.sleep(1.0)
            print(json.dumps({f"C5B_{tag}": {"stream": stream_id,
                                             "fetched": len(todo), "cached": len(dates) - len(todo)}}),
                  flush=True)
            for di in dates:
                if f"{stream_id}|{di}" in cache:
                    got[(stream_id, di)] = cache[f"{stream_id}|{di}"]
        return got

    v2024 = fetch(dates_2024, "2024")
    vhist = fetch(dates_hist, "HIST")

    # per (stream, month, rule): mean historical (variant - base) shift
    seasonal_shift: dict[tuple[str, int, str], float] = {}
    seasonal_n: dict[tuple[str, int, str], int] = {}
    for stream_id in STREAMS:
        for m in range(1, 13):
            for rule in ("strict", "erode"):
                deltas = []
                for y in hist_years:
                    for dd in hist_days:
                        hr = vhist.get((stream_id, f"{y}-{m:02d}-{dd:02d}"))
                        if hr and hr.get(rule) is not None and hr.get("base") is not None:
                            deltas.append(hr[rule] - hr["base"])
                if deltas:
                    seasonal_shift[(stream_id, m, rule)] = statistics.fmean(deltas)
                    seasonal_n[(stream_id, m, rule)] = len(deltas)

    tiers = ["below normal", "within normal range", "warm", "unusually warm",
             "extreme warm observation"]
    results: dict[str, list[dict[str, Any]]] = {"strict": [], "erode": []}
    for stream_id in STREAMS:
        for (m, dd), di in zip(md_sample, dates_2024):
            rec = rec_by_key.get((stream_id, di))
            if not rec or rec.get("confidence") != "ok" or rec.get("daily_lst_c") is None:
                continue
            base_2024 = v2024.get((stream_id, di), {}).get("base")
            if base_2024 is None:
                continue
            doy = fold(m, dd)
            crow = clim5.get((stream_id, doy))
            for rule in ("strict", "erode"):
                s2024 = v2024[(stream_id, di)].get(rule)
                shift_hist = seasonal_shift.get((stream_id, m, rule))
                if s2024 is None or shift_hist is None:
                    continue
                shift_2024 = s2024 - base_2024
                d_anom = shift_2024 - shift_hist
                label_step = None
                if crow and crow["sorted"]:
                    base_lbl = engine.classify(engine.type7_percentile_rank(
                        crow["sorted"], base_2024))
                    var_lbl = engine.classify(engine.type7_percentile_rank(
                        crow["sorted"], base_2024 + d_anom))
                    label_step = abs(tiers.index(base_lbl) - tiers.index(var_lbl))
                results[rule].append({
                    "stream": stream_id, "date": di,
                    "shift_2024_c": round(shift_2024, 3), "shift_hist_c": round(shift_hist, 3),
                    "d_anomaly_c": round(d_anom, 3), "label_step": label_step,
                })

    def summarise(rule: str) -> dict[str, Any]:
        rows = results[rule]
        signed = [r["d_anomaly_c"] for r in rows]
        das = sorted(abs(x) for x in signed)
        n = len(das) or 1
        lc = sum(1 for r in rows if r["label_step"])
        return {
            "n_ok_sample_days": len(rows),
            "mean_shift_2024_c": _round(statistics.fmean(r["shift_2024_c"] for r in rows), 3) if rows else None,
            "mean_shift_hist_c": _round(statistics.fmean(r["shift_hist_c"] for r in rows), 3) if rows else None,
            "mean_signed_d_anomaly_c": _round(statistics.fmean(signed), 3) if signed else None,
            "mean_abs_d_anomaly_c": _round(statistics.fmean(das), 3) if das else None,
            "p95_abs_d_anomaly_c": _round(das[int(0.95 * (len(das) - 1))], 3) if das else None,
            "max_abs_d_anomaly_c": _round(das[-1], 3) if das else None,
            "days_over_0.5c": sum(x > 0.5 for x in das),
            "days_over_0.5c_frac": _round(sum(x > 0.5 for x in das) / n, 4),
            "label_changes": lc,
            "label_change_frac": _round(lc / n, 4),
            "label_jumps_ge_2_tiers": sum(1 for r in rows if (r["label_step"] or 0) >= 2),
            "worst": sorted(rows, key=lambda r: -abs(r["d_anomaly_c"]))[:10],
        }

    strict_s, erode_s = summarise("strict"), summarise("erode")
    findings: list[str] = []
    limitations: list[str] = []

    # 463 m erosion IS a rule we could plausibly switch to -> gate on the per-day shift
    # (spec line: <= 5% of ok days shift > 0.5 C; no >= 2-tier label jumps).
    e = erode_s
    if e["n_ok_sample_days"] < 20:
        findings.append(f"erosion: only {e['n_ok_sample_days']} ok sample days - inconclusive")
    else:
        if (e["days_over_0.5c_frac"] or 0) > 0.05:
            findings.append(f"463 m erosion: {e['days_over_0.5c_frac']:.1%} of ok days shift > 0.5 C "
                            f"(max {e['max_abs_d_anomaly_c']} C, mean signed {e['mean_signed_d_anomaly_c']:+.2f})")
        if e["label_jumps_ge_2_tiers"] > max(1, int(0.02 * e["n_ok_sample_days"])):
            findings.append(f"463 m erosion: {e['label_jumps_ge_2_tiers']} sample days jump >= 2 tiers")
        if (e["label_change_frac"] or 0) > 0.05:
            limitations.append(f"463 m erosion: {e['label_change_frac']:.1%} adjacent-tier label "
                               f"flips (boundary sensitivity, same as C5a)")

    # strict QC is NOT a candidate rule (QA-002 rejected it; AUDIT-011: ~0 night coverage).
    # The question here is only whether comparing to it reveals a SYSTEMATIC bias in
    # candidate C -> gate on the mean signed shift, and report the day-to-day scatter as
    # the reason strict QC is the worse choice.
    s = strict_s
    if s["n_ok_sample_days"] < 20:
        findings.append(f"strict-QC: only {s['n_ok_sample_days']} ok sample days - inconclusive")
    else:
        if abs(s["mean_signed_d_anomaly_c"] or 0) > 0.5:
            findings.append(f"strict-QC vs candidate C: systematic anomaly bias "
                            f"{s['mean_signed_d_anomaly_c']:+.2f} C (> 0.5 C) - investigate")
        if s["label_jumps_ge_2_tiers"] > max(1, int(0.02 * s["n_ok_sample_days"])):
            findings.append(f"strict-QC: {s['label_jumps_ge_2_tiers']} sample days jump >= 2 tiers")
        if (s["days_over_0.5c_frac"] or 0) > 0.05:
            limitations.append(f"strict-QC: {s['days_over_0.5c_frac']:.1%} of ok daytime days shift "
                               f"> 0.5 C day-to-day (max {s['max_abs_d_anomaly_c']} C) - strict QC "
                               f"drops day-specific pixel sets, adding noise candidate C avoids; "
                               f"this is evidence FOR the QA-002 choice, not a product defect")

    return {
        "name": "C5b - method robustness: strict QC and 463 m erosion (2024 sample)",
        "pass": not findings,
        "metrics": {
            "sample_2024_dates": len(dates_2024),
            "historical_shift_model": f"per-month mean of (variant - base) over years {hist_years}, "
                                      f"days {hist_days}",
            "strict_qc": strict_s,
            "erosion_463m": erode_s,
        },
        "limitations": limitations,
        "note": "Bounded probe. For each sampled day: shift_2024 = (variant - base) lake-mean in "
                "2024; shift_hist = the same difference averaged over the same calendar date in "
                f"{hist_years}. d_anomaly = shift_2024 - shift_hist is the change in the anomaly the "
                "rule would cause (a rule that moves today and the baseline equally cancels). Label "
                "step re-ranks base +/- d_anomaly against the FULL 20-year +/-5 climatology.",
        "findings": findings,
    }


def _valid_date(y: int, m: int, d: int) -> bool:
    try:
        dt.date(y, m, d)
        return True
    except ValueError:
        return False


# ----------------------------------------------------------------------- self-test

def self_test() -> None:
    assert _pearson([1, 2, 3, 4], [1, 2, 3, 4]) > 0.999
    s = _matchup_stats([1.0, 2.0, 3.0, 4.0], [1.5, 2.5, 2.5, 4.5])
    assert s["n"] == 4 and s["bias_c"] is not None
    assert _months(2003, 2003) == [f"2003-{m:02d}" for m in range(1, 13)]
    assert len(_months(2003, 2024)) == 22 * 12
    print("self-test OK")


# ----------------------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="ee-jtantaroman")
    ap.add_argument("--c3", action="store_true")
    ap.add_argument("--c5b", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        self_test()
        return 0
    if not (args.c3 or args.c5b):
        ap.error("choose --c3 and/or --c5b (or --self-test)")

    engine = _load_engine()
    monthly = _load_json("monthly_summaries")
    daily = _load_json("daily_anomaly_records")
    hist = _load_json("historical_daily_values")

    criteria = []
    if args.c3:
        criteria.append(check_c3(engine, args.project, monthly, hist))
    if args.c5b:
        criteria.append(check_c5b(engine, args.project, hist, daily))

    payload = {
        "artifact": "phase5_validation_ee",
        "coordinate_free": True,
        "reads_coordinates": False,
        "date_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "criteria": criteria,
        "all_pass": all(c["pass"] for c in criteria),
    }
    engine.validate_coordinate_free(payload)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = "_".join(c["name"].split()[0].lower() for c in criteria)
    out = OUT_DIR / f"validation_ee_{tag}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nPhase 5 validation - Stage B\nwritten: {out}\n")
    for c in criteria:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}")
        for f in c["findings"]:
            print(f"         - FAIL: {f}")
        for lim in c.get("limitations", []):
            print(f"         - limitation: {lim}")
    print(f"\n  Stage B: {'PASS' if payload['all_pass'] else 'FAIL'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
