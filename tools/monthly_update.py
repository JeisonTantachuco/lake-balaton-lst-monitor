"""METH-007 monthly refresh - incremental, scheduled.

Extends the published pixel-first daily records and monthly summaries through
yesterday (UTC), reusing the existing per-pixel normals and the existing
leave-one-year-out historical pool (both fixed, year-independent -- they do not
need rebuilding on a monthly refresh, only the 2023-onward daily readings do).
The historical pool is read from the published historical_pixelfirst_pool asset,
not a local file, so this script needs nothing beyond this repository checkout.

This is the recurring counterpart to build_headline_daily.py / assemble_pixelfirst_
records.py / assemble_monthly_pixelfirst.py / export_pixelfirst_assets.py, which were
one-off full-history backfill scripts. Running those directly on a schedule would
silently replace the pixel-first published data with a fresh, correct recompute each
time -- harmless but needlessly expensive (hours of Earth Engine compute monthly for
data that mostly already exists). This script instead reads what is already published,
computes only the new days, and re-exports the merged whole.

Usage: python tools/monthly_update.py --project ee-jtantaroman
Auth (for the scheduled CI run; local runs omit these and use interactive credentials):
  EE_SERVICE_ACCOUNT_KEY_FILE, EE_SERVICE_ACCOUNT_EMAIL
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
import time as time_mod
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_anomaly_engine_ee import (  # noqa: E402
    _init_ee, _per_day_feature, _eligible_counts, _feature_collection, _run_table_exports,
    fold_day_of_year, window_offsets, type7_percentile_rank, classify,
    confidence_from_fraction, PERCENTILE_MIN_N, PERCENTILE_FULL_N,
    MONTHLY_MIN_VALID_DAYS, WARM_PERCENTILE,
)
from build_headline_daily import lst_masked, STREAMS, MIN_N  # noqa: E402


def list_all_features(ee, asset_id):
    """ee.FeatureCollection(...).getInfo() aborts above 5000 features; page through
    ee.data.listFeatures instead, which this project's other large tables never
    needed (all under 5000) but historical_pixelfirst_pool (17,602 rows) does."""
    out = []
    page_token = None
    while True:
        params = {"assetId": asset_id, "pageSize": 5000}
        if page_token:
            params["pageToken"] = page_token
        resp = ee.data.listFeatures(params)
        out.extend(resp.get("features", []))
        page_token = resp.get("next_page_token")
        if not page_token:
            break
    return out


def doy_of(date_str):
    y, m, d = (int(x) for x in date_str.split("-"))
    return fold_day_of_year(m, d)


def load_published_daily(ee, root):
    fc = ee.FeatureCollection(root + "daily_anomaly_records")
    return fc.getInfo()["features"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--through", default=None,
                     help="YYYY-MM-DD, inclusive; default yesterday (UTC)")
    args = ap.parse_args()

    _ee, audit010, runner, _gj, context = _init_ee(args.project)
    ee = _ee
    root = "projects/%s/assets/balaton_anomaly/" % args.project
    geom = context["geometry"]
    eligible = _eligible_counts(context)

    published = load_published_daily(ee, root)
    existing_rows = [f["properties"] for f in published]
    last_by_stream = {}
    for r in existing_rows:
        sid = r["stream_id"]
        if sid not in last_by_stream or r["date_utc"] > last_by_stream[sid]:
            last_by_stream[sid] = r["date_utc"]
    through = args.through or (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    print(json.dumps({"existing_rows": len(existing_rows), "last_by_stream": last_by_stream,
                       "through": through}))

    hist = [f["properties"] for f in list_all_features(ee, root + "historical_pixelfirst_pool")]
    pools = {}
    for r in hist:
        pools.setdefault((r["stream_id"], doy_of(r["date_utc"])), []).append(r["anomaly_pixel_first_c"])

    def pooled_sample(stream_id, doy):
        vals = []
        for d in window_offsets(doy):
            vals.extend(pools.get((stream_id, d), []))
        return sorted(vals)

    new_rows = []
    for sid, (col_id, lb, qb) in STREAMS.items():
        ctx = runner.contexts[sid]
        stream = context["stream_by_id"][sid]
        normal = ee.Image(root + "pixel_normal_" + sid)
        start = (dt.date.fromisoformat(last_by_stream[sid]) + dt.timedelta(days=1)).isoformat()
        if start > through:
            print(json.dumps({"stream": sid, "skip": "already current", "start": start}))
            continue
        col = ee.ImageCollection(col_id).filterDate(
            start, (dt.date.fromisoformat(through) + dt.timedelta(days=1)).isoformat())
        area = ee.Image.pixelArea()

        def per_image(img, lb=lb, qb=qb, normal=normal, ctx=ctx, stream=stream):
            date = ee.Date(img.get("system:time_start"))
            mmdd = date.format("MMdd")
            mmdd = ee.String(ee.Algorithms.If(mmdd.equals("0229"), "0228", mmdd))
            tn = normal.select(ee.String("d").cat(mmdd).cat("_med"))
            nn = normal.select(ee.String("d").cat(mmdd).cat("_n"))
            today = lst_masked(ee, img, lb, qb)
            anom = today.subtract(tn).updateMask(nn.gte(MIN_N))
            anom_stats = ee.Image.cat([
                anom.multiply(area).rename("anom_w"),
                area.updateMask(anom.mask()).rename("anom_a"),
                ee.Image.constant(1).updateMask(anom.mask()).rename("anom_count"),
            ]).reduceRegion(reducer=ee.Reducer.sum(), geometry=geom,
                             crs=ctx["crs"], crsTransform=ctx["transform"],
                             bestEffort=False, maxPixels=2_000_000, tileScale=1)
            lake_feat = _per_day_feature(audit010, runner, ee, img, stream, geom, ctx)
            return ee.Feature(None, {
                "date_utc": date.format("YYYY-MM-dd"),
                "anom_w": anom_stats.get("anom_w"), "anom_a": anom_stats.get("anom_a"),
                "anom_count": ee.Number(anom_stats.get("anom_count", 0)).toInt64(),
                "weighted_sum": lake_feat.get("weighted_sum"), "area_sum": lake_feat.get("area_sum"),
                "accepted_count": lake_feat.get("accepted_count"),
            })

        feats = ee.FeatureCollection(col.map(per_image)).getInfo()
        n = 0
        for f in feats.get("features", []):
            p = f["properties"]
            if int(p.get("accepted_count") or 0) <= 0 or int(p.get("anom_count") or 0) <= 0:
                continue
            if not p.get("anom_a") or not p.get("area_sum"):
                continue
            anomaly = p["anom_w"] / p["anom_a"]
            doy = doy_of(p["date_utc"])
            sample = pooled_sample(sid, doy)
            if len(sample) >= PERCENTILE_MIN_N:
                pct = type7_percentile_rank(sample, anomaly)
                pct_conf = "full" if len(sample) >= PERCENTILE_FULL_N else "limited_historical_sample"
            else:
                pct, pct_conf = None, "insufficient_history"
            acc = p["accepted_count"]
            fraction = acc / eligible[sid] if eligible.get(sid) else 0.0
            new_rows.append({
                "stream_id": sid, "date_utc": p["date_utc"],
                "anomaly_vs_median_c": round(anomaly, 4),
                "historical_percentile": round(pct, 2) if pct is not None else None,
                "percentile_confidence": pct_conf,
                "classification": classify(pct),
                "historical_n": len(sample),
                "confidence": confidence_from_fraction(fraction),
                "valid_water_fraction": round(fraction, 4),
                "accepted_pixel_count": acc,
                "daily_lst_c": p["weighted_sum"] / p["area_sum"],
            })
            n += 1
        print(json.dumps({"stream": sid, "new_rows": n, "from": start, "through": through}))

    if not new_rows:
        print(json.dumps({"NOTHING_NEW": True}))
        return 0

    all_rows = existing_rows + new_rows
    import statistics
    groups = {}
    for r in all_rows:
        groups.setdefault((r["stream_id"], r["date_utc"][:7]), []).append(r)
    monthly_rows = []
    for (stream_id, month_key), recs in sorted(groups.items()):
        year, month = int(month_key[:4]), int(month_key[5:7])
        calendar_days = (dt.date(year + (month == 12), (month % 12) + 1, 1)
                         - dt.date(year, month, 1)).days
        qualifying = [r for r in recs if r["confidence"] in ("ok", "low") and r["daily_lst_c"] is not None]
        low_days = [r for r in qualifying if r["confidence"] == "low"]
        row = {
            "stream_id": stream_id, "month": month_key,
            "calendar_day_count": calendar_days,
            "valid_day_count": len(qualifying),
            "low_coverage_day_count": len(low_days),
            "mean_valid_water_fraction": (
                round(statistics.fmean(r["valid_water_fraction"] for r in qualifying), 4)
                if qualifying else None),
            "missing_or_cloud_fraction": round(1 - len(qualifying) / calendar_days, 4),
        }
        if len(qualifying) < MONTHLY_MIN_VALID_DAYS:
            row["state"] = "insufficient valid observations"
            monthly_rows.append(row)
            continue
        temps = [r["daily_lst_c"] for r in qualifying]
        anomalies = [r["anomaly_vs_median_c"] for r in qualifying]
        with_pct = [r for r in qualifying if r["historical_percentile"] is not None]
        warm = [r for r in with_pct if r["historical_percentile"] >= WARM_PERCENTILE]
        hottest = max(qualifying, key=lambda r: r["daily_lst_c"])
        peak = max(qualifying, key=lambda r: r["anomaly_vs_median_c"])
        row.update({
            "state": "reported",
            "monthly_mean_lst_c": round(statistics.fmean(temps), 4),
            "monthly_mean_anomaly_vs_median_c": round(statistics.fmean(anomalies), 4),
            "hottest_observation_date": hottest["date_utc"],
            "hottest_observation_lst_c": hottest["daily_lst_c"],
            "warm_observation_count": len(warm),
            "days_with_a_percentile": len(with_pct),
            "max_anomaly_vs_median_date": peak["date_utc"],
            "max_anomaly_vs_median_c": peak["anomaly_vs_median_c"],
        })
        monthly_rows.append(row)

    jobs = [
        {"asset_id": root + "daily_anomaly_records", "description": "balaton_daily_anomaly_records",
         "overwrite": True, "collection": _feature_collection(ee, all_rows)},
        {"asset_id": root + "monthly_summaries", "description": "balaton_monthly_summaries",
         "overwrite": True, "collection": _feature_collection(ee, monthly_rows)},
    ]
    _run_table_exports(ee, jobs, time_mod.monotonic() + 3000)
    for job in jobs:
        ee.data.setAssetAcl(job["asset_id"], {"all_users_can_read": True})
    print(json.dumps({"MONTHLY_UPDATE_DONE": True, "new_rows": len(new_rows),
                       "total_daily_rows": len(all_rows), "total_monthly_rows": len(monthly_rows)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
