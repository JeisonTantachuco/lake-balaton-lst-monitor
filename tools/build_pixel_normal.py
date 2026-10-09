"""METH-007 step 1 - per-pixel historical normal, one image per stream.

For every calendar day (365 non-leap days; 29 Feb uses the 28 Feb band, the same
fold as the existing engine) the per-pixel median of accepted (QA-002 candidate C)
readings over 2003-2022 within +/-5 days, and the per-pixel count of those readings.
Output: one multi-band image asset per stream, bands d<MMDD>_med and d<MMDD>_n.

Exported on MODIS's own native sinusoidal grid (runner.contexts[stream]['crs'] /
['transform']), the same grid run_anomaly_engine_ee.py always reduces on -- not a
separately-chosen grid. An earlier version of this script exported on a generic
EPSG:3035 1000 m grid instead; every later subtraction against a live MODIS image
then silently reprojected one side, which can blur values near the (now narrow,
eroded) shoreline. That version's assets were deleted and are rebuilt here.
"""
from __future__ import annotations
import argparse, datetime as dt, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_anomaly_engine_ee import _init_ee  # noqa: E402

HALF_WINDOW = 5
YEARS = range(2003, 2023)
STREAMS = {
    "terra_day":   ("MODIS/061/MOD11A1", "LST_Day_1km",   "QC_Day"),
    "terra_night": ("MODIS/061/MOD11A1", "LST_Night_1km", "QC_Night"),
    "aqua_day":    ("MODIS/061/MYD11A1", "LST_Day_1km",   "QC_Day"),
    "aqua_night":  ("MODIS/061/MYD11A1", "LST_Night_1km", "QC_Night"),
}
NON_LEAP = [dt.date(2001, 1, 1) + dt.timedelta(days=i) for i in range(365)]


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


def window_filter(ee, day: dt.date, exclude_year=None):
    filters = []
    for y in YEARS:
        if y == exclude_year:
            continue
        d = day.replace(year=y) if not (day.month == 2 and day.day == 29) else dt.date(y, 2, 28)
        c = ee.Date.fromYMD(d.year, d.month, d.day)
        filters.append(ee.Filter.date(c.advance(-HALF_WINDOW, "day"), c.advance(HALF_WINDOW + 1, "day")))
    return ee.Filter.Or(*filters)


def build_stream_image(ee, stream_id, exclude_year=None):
    col_id, lb, qb = STREAMS[stream_id]
    bands = []
    for day in NON_LEAP:
        base = (ee.ImageCollection(col_id).filter(window_filter(ee, day, exclude_year))
                .map(lambda i: lst_masked(ee, i, lb, qb)))
        name = "d%02d%02d" % (day.month, day.day)
        med = base.reduce(ee.Reducer.median()).rename(name + "_med")
        n = base.map(lambda i: i.mask().rename("m")).reduce(ee.Reducer.sum()).rename(name + "_n")
        bands.append(med.addBands(n))
    return ee.Image.cat(bands)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--stream", required=True, choices=sorted(STREAMS))
    ap.add_argument("--exclude-year", type=int, default=None)
    args = ap.parse_args()
    import ee
    ee.Initialize(project=args.project)
    _ee, _audit010, runner, _gj, context = _init_ee(args.project)
    ctx = runner.contexts[args.stream]
    geom = context["geometry"]
    image = build_stream_image(ee, args.stream, args.exclude_year).clip(geom)
    root = "projects/%s/assets/balaton_anomaly/" % args.project
    suffix = "" if args.exclude_year is None else "_excl%d" % args.exclude_year
    asset_id = root + "pixel_normal_" + args.stream + suffix
    task = ee.batch.Export.image.toAsset(
        image=image, description="balaton_pixel_normal_" + args.stream + suffix,
        assetId=asset_id, region=geom, crs=ctx["crs"], crsTransform=ctx["transform"],
        maxPixels=1e10)
    task.start()
    print(json.dumps({"started": task.id, "asset_id": asset_id, "bands": 730}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
