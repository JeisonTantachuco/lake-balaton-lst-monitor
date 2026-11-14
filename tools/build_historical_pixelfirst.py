"""METH-007 step 3a - 2003-2022 per-pixel-first anomalies, using leave-one-year-out
normals (each year ranked against a normal built from the other 19 years), so a year
never judges itself. Area-weighted, on MODIS's own native grid throughout (same fix as
build_headline_daily.py step 2).

SPACE-003: the same already-computed per-pixel LOYO anomaly image is reduced over the 4
basins in ONE grouped reduceRegion call per image (run_anomaly_engine_ee.
region_class_image), the same Earth Engine cost as the pre-SPACE-003 single-region code;
"whole lake" is the sum of the 4 basins, taken client-side. Coordinate-free output.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "local_run_state" / "phase3_pixelfirst" / "historical_pixelfirst.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_anomaly_engine_ee import _init_ee, retry_getinfo, region_class_image  # noqa: E402
from build_headline_daily import BASIN_LABELS  # noqa: E402

MIN_N = 10
YEARS = range(2003, 2023)
STREAMS = {
    "terra_day":   ("MODIS/061/MOD11A1", "LST_Day_1km",   "QC_Day"),
    "terra_night": ("MODIS/061/MOD11A1", "LST_Night_1km", "QC_Night"),
    "aqua_day":    ("MODIS/061/MYD11A1", "LST_Day_1km",   "QC_Day"),
    "aqua_night":  ("MODIS/061/MYD11A1", "LST_Night_1km", "QC_Night"),
}
VALUE_BANDS = ("anom_w", "anom_a", "anom_count")


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


def _grouped_region_values(reduced_groups):
    per_region = {}
    for g in reduced_groups or []:
        label = BASIN_LABELS[int(g["region_num"]) - 1]
        per_region[label] = dict(zip(VALUE_BANDS, g["sum"]))
    whole = {band: 0.0 for band in VALUE_BANDS}
    for label in BASIN_LABELS:
        for band, v in per_region.get(label, {}).items():
            whole[band] += v
    per_region["whole_lake"] = whole
    return per_region


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    args = ap.parse_args()
    import ee
    ee.Initialize(project=args.project)
    _ee, _audit010, runner, _gj, context = _init_ee(args.project)
    root = "projects/%s/assets/balaton_anomaly/" % args.project
    regions_fc = ee.FeatureCollection(root + "basin_boundaries")
    region_img = region_class_image(ee, regions_fc)
    geom = context["geometry"]
    rows = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        rows = json.loads(OUT.read_text(encoding="utf-8"))["rows"]
    done = {(r["stream_id"], r["year"]) for r in rows if r.get("region_id") == "whole_lake"}

    for sid, (col_id, lb, qb) in STREAMS.items():
        ctx = runner.contexts[sid]
        for y in YEARS:
            if (sid, y) in done:
                continue
            normal = ee.Image(root + "pixel_normal_" + sid + "_excl%d" % y)
            col = ee.ImageCollection(col_id).filterDate("%d-01-01" % y, "%d-01-01" % (y + 1))
            area = ee.Image.pixelArea()

            # Only `img` is a parameter here -- see build_headline_daily.py's per_image
            # for why the lb=lb/normal=normal default-arg trick breaks under ee.List.map().
            def per_image(img):
                img = ee.Image(img)
                date = ee.Date(img.get("system:time_start"))
                mmdd = date.format("MMdd")
                mmdd = ee.String(ee.Algorithms.If(mmdd.equals("0229"), "0228", mmdd))
                tn = normal.select(ee.String("d").cat(mmdd).cat("_med"))
                nn = normal.select(ee.String("d").cat(mmdd).cat("_n"))
                today = lst_masked(ee, img, lb, qb)
                anom = today.subtract(tn).updateMask(nn.gte(MIN_N))
                stats_img = ee.Image.cat([
                    anom.multiply(area).rename("anom_w"),
                    area.updateMask(anom.mask()).rename("anom_a"),
                    ee.Image.constant(1).updateMask(anom.mask()).rename("anom_count"),
                ])
                stacked = ee.Image.cat([stats_img, region_img])
                reducer = ee.Reducer.sum().repeat(len(VALUE_BANDS)).group(
                    groupField=len(VALUE_BANDS), groupName="region_num")
                reduced = stacked.reduceRegion(
                    reducer=reducer, geometry=geom, crs=ctx["crs"], crsTransform=ctx["transform"],
                    bestEffort=False, maxPixels=2_000_000, tileScale=1)
                return ee.Feature(None, {"date_utc": date.format("YYYY-MM-dd"),
                                          "groups": reduced.get("groups")})

            feats = retry_getinfo(ee.FeatureCollection(col.map(per_image)).getInfo)
            n = 0
            for f in feats.get("features", []):
                p = f["properties"]
                by_region = _grouped_region_values(p.get("groups"))
                for region_id, b in by_region.items():
                    # Same exclusion rule as step 2 / the pre-METH-007 engine: a day whose
                    # rounded pixel count is 0 (a sliver of a single border pixel) is not
                    # part of the history at all, not a near-zero data point.
                    if int(b.get("anom_count") or 0) <= 0:
                        continue
                    if not b.get("anom_a"):
                        continue
                    rows.append({"stream_id": sid, "region_id": region_id, "year": y,
                                 "date_utc": p["date_utc"],
                                 "anomaly_pixel_first_c": b["anom_w"] / b["anom_a"]})
                    n += 1
            print(json.dumps({"stream": sid, "year": y, "rows": n}), flush=True)
            OUT.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    print(json.dumps({"written": str(OUT), "rows": len(rows), "HIST_DONE": True}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
