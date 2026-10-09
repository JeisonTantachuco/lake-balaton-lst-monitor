"""METH-007 step 2 - per-pixel-first headline daily anomaly, 2023 onward.

For each monitoring day and stream: each accepted (QA-002 candidate C) pixel's reading
minus that pixel's own normal for the same calendar day (pixel_normal_<stream>, median
over 2003-2022 +/-5 days, pixel count >= 10), area-weighted over the lake polygon inset
by one MODIS pixel (SPACE-002), on MODIS's own native grid throughout -- the normal
asset, the live image and the reduceRegion all use runner.contexts[stream]['crs']/
['transform'], so nothing is silently reprojected. The daily_lst_c / accepted_pixel_count
/ valid_water_fraction figures are produced by the engine's own _per_day_feature, so they
are identical to the pre-METH-007 lake-mean numbers -- only the anomaly is new.
Coordinate-free output.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "local_run_state" / "phase3_pixelfirst" / "daily_headline.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_anomaly_engine_ee import _init_ee, _per_day_feature, _eligible_counts  # noqa: E402

MIN_N = 10
START, END = "2023-01-01", "2026-08-30"
STREAMS = {
    "terra_day":   ("MODIS/061/MOD11A1", "LST_Day_1km",   "QC_Day"),
    "terra_night": ("MODIS/061/MOD11A1", "LST_Night_1km", "QC_Night"),
    "aqua_day":    ("MODIS/061/MYD11A1", "LST_Day_1km",   "QC_Day"),
    "aqua_night":  ("MODIS/061/MYD11A1", "LST_Night_1km", "QC_Night"),
}
CHUNKS = [("2023-01-01", "2023-07-01"), ("2023-07-01", "2024-01-01"), ("2024-01-01", "2024-07-01"),
          ("2024-07-01", "2025-01-01"), ("2025-01-01", "2025-07-01"), ("2025-07-01", "2026-01-01"),
          ("2026-01-01", "2026-07-01"), ("2026-07-01", "2026-08-31")]


def lst_masked(ee, img, lb, qb):
    raw = img.select(lb)
    qc = img.select(qb)
    mand = qc.bitwiseAnd(3)
    dq = qc.rightShift(2).bitwiseAnd(3)
    em = qc.rightShift(4).bitwiseAnd(3)
    le = qc.rightShift(6).bitwiseAnd(3)
    ok = (raw.gte(7500).And(raw.lte(65535)).And(mand.lte(1))
          .And(dq.eq(0)).And(em.lte(1)).And(le.lte(1)))
    return raw.multiply(0.02).subtract(273.15).updateMask(ok).rename("lst")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    args = ap.parse_args()
    import ee
    ee.Initialize(project=args.project)
    _ee, audit010, runner, _gj, context = _init_ee(args.project)
    root = "projects/%s/assets/balaton_anomaly/" % args.project
    geom = context["geometry"]
    eligible = _eligible_counts(context)
    result = {"eligible_pixels_sum": eligible, "rows": []}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for sid, (col_id, lb, qb) in STREAMS.items():
        ctx = runner.contexts[sid]
        stream = context["stream_by_id"][sid]
        normal = ee.Image(root + "pixel_normal_" + sid)
        for c0, c1 in CHUNKS:
            col = ee.ImageCollection(col_id).filterDate(c0, c1)
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
                # Same exclusion rule the pre-METH-007 engine always used (run_anomaly_engine_ee.py
                # _collect_daily_values: `count <= 0: continue`) -- a day whose rounded pixel count
                # is 0 is not reported at all, rather than shown with a real-looking temperature or
                # anomaly built from a sliver of a single border pixel. An earlier version of this
                # script dropped that check when the pixel-first calculation was added, which let a
                # handful of sub-one-pixel days through with a reading but "0 px" coverage shown.
                if int(p.get("accepted_count") or 0) <= 0 or int(p.get("anom_count") or 0) <= 0:
                    continue
                if not p.get("anom_a") or not p.get("area_sum"):
                    continue
                result["rows"].append({
                    "stream_id": sid, "date_utc": p["date_utc"],
                    "anomaly_pixel_first_c": p["anom_w"] / p["anom_a"],
                    "daily_lst_c": p["weighted_sum"] / p["area_sum"],
                    "accepted_pixel_count": p["accepted_count"],
                })
                n += 1
            print(json.dumps({"stream": sid, "chunk": c0, "rows": n}), flush=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"written": str(OUT), "rows": len(result["rows"])}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
