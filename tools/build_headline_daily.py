"""METH-007 step 2 - per-pixel-first headline daily anomaly, 2023 onward.

For each monitoring day and stream: each accepted (QA-002 candidate C) pixel's reading
minus that pixel's own normal for the same calendar day (pixel_normal_<stream>, median
over 2003-2022 +/-5 days, pixel count >= 10), area-weighted over the lake polygon inset
by one MODIS pixel (SPACE-002), on MODIS's own native grid throughout -- the normal
asset, the live image and the reduceRegion all use runner.contexts[stream]['crs']/
['transform'], so nothing is silently reprojected. The daily_lst_c / accepted_pixel_count
/ valid_water_fraction figures use the engine's own masked lake-stat bands, so they are
identical to the pre-METH-007 lake-mean numbers -- only the anomaly is new.

SPACE-003: every day's already-computed per-pixel anomaly/lake-stat image is reduced over
the 4 basins (from `basin_boundaries`) in ONE grouped reduceRegion call per image (see
run_anomaly_engine_ee.region_class_image), the same Earth Engine cost as the
pre-SPACE-003 single-region code; "whole lake" is simply the sum of the 4 basins, taken
client-side. An earlier version used reduceRegions (one call per region) instead, which
reliably hit Earth Engine's "too many concurrent aggregations" throttle because it
counts as one aggregation per region per image, not one per image -- it is not used here.
Coordinate-free output.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "local_run_state" / "phase3_pixelfirst" / "daily_headline.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_anomaly_engine_ee import (  # noqa: E402
    _init_ee, _masked_lake_stat_image, _eligible_counts, retry_getinfo, region_class_image)

MIN_N = 10
START, END = "2023-01-01", "2026-10-31"
STREAMS = {
    "terra_day":   ("MODIS/061/MOD11A1", "LST_Day_1km",   "QC_Day"),
    "terra_night": ("MODIS/061/MOD11A1", "LST_Night_1km", "QC_Night"),
    "aqua_day":    ("MODIS/061/MYD11A1", "LST_Day_1km",   "QC_Day"),
    "aqua_night":  ("MODIS/061/MYD11A1", "LST_Night_1km", "QC_Night"),
}
BASIN_LABELS = ("I", "II", "III", "IV")
# Value bands reduced per group, in this exact order -- region_class_image's painted
# band is appended after these as the (unrepeated) group field.
VALUE_BANDS = ("anom_w", "anom_a", "anom_count", "weighted_sum", "area_sum", "accepted_count")


def _month_chunks(start: str, end: str) -> list[tuple[str, str]]:
    """Monthly (not half-yearly) sub-ranges, kept modest-sized for safety even though
    the grouped-reducer approach no longer needs this for the concurrency limit (that
    was only an issue with the reduceRegions-per-region approach this replaced).
    `start` need not fall on the 1st (monthly_update.py calls this with "day after the
    last published date") -- only the first chunk keeps that exact start day; every
    later chunk boundary is the 1st of its month, as usual."""
    y0, m0 = int(start[:4]), int(start[5:7])
    y1, m1 = int(end[:4]), int(end[5:7])
    out = []
    y, m = y0, m0
    c0 = start
    while (y, m) < (y1, m1) or (y == y1 and m == m1 and end[8:10] != "01"):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        c1 = min(end, "%04d-%02d-01" % (ny, nm))
        out.append((c0, c1))
        if c1 == end:
            break
        y, m = ny, nm
        c0 = "%04d-%02d-01" % (y, m)
    return out


CHUNKS = [("2023-01-01", "2023-07-01"), ("2023-07-01", "2024-01-01"), ("2024-01-01", "2024-07-01"),
          ("2024-07-01", "2025-01-01"), ("2025-01-01", "2025-07-01"), ("2025-07-01", "2026-01-01"),
          ("2026-01-01", "2026-07-01"), ("2026-07-01", "2026-11-01")]


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


def _eligible_counts_by_region(ee, runner, regions_fc, geometry, stream_ids):
    """Per-basin (SPACE-003) analogue of the engine's own _eligible_counts: how many
    pixels of each stream's native grid fall inside each basin, for valid_water_fraction.
    One grouped reduceRegion per stream (not reduceRegions), same reasoning as above."""
    region_img = region_class_image(ee, regions_fc)
    out: dict[str, dict[str, int]] = {"whole_lake": {}}
    for sid in stream_ids:
        ctx = runner.contexts[sid]
        stacked = ee.Image.cat([ee.Image.constant(1).rename("eligible"), region_img])
        reducer = ee.Reducer.sum().repeat(1).group(groupField=1, groupName="region_num")
        reduced = retry_getinfo(lambda stacked=stacked, reducer=reducer, ctx=ctx: stacked.reduceRegion(
            reducer=reducer, geometry=geometry, crs=ctx["crs"], crsTransform=ctx["transform"],
            bestEffort=False, maxPixels=2_000_000, tileScale=1).getInfo())
        total = 0
        for g in reduced.get("groups", []):
            region_id = BASIN_LABELS[int(g["region_num"]) - 1]
            n = round((g["sum"][0] if isinstance(g["sum"], list) else g["sum"]) or 0)
            out.setdefault(region_id, {})[sid] = n
            total += n
        out["whole_lake"][sid] = total
    return out


def _grouped_region_stats(ee, reduced_dict_getinfo_result, whole_vals=None):
    """Parse one reduceRegion().getInfo() result (from the repeat(6).group(...) reducer)
    into {region_label: {band_name: value}}. 'whole_lake' is `whole_vals` -- a direct,
    independent reduceRegion over the lake's own geometry (not a sum of the 4 basins):
    summing the 4 basins undercounts, because Earth Engine's per-pixel area weighting
    for one big polygon doesn't exactly match the weighting for 4 separate polygons
    added together, even though the 4 basin shapes do add up to the lake shape (SPACE-003
    verified this geometrically). A basin absent from `groups` (no accepted pixels there
    that day) is simply missing from the output, same as the pre-SPACE-003 "no reading"
    convention."""
    per_region: dict[str, dict[str, float]] = {}
    for g in reduced_dict_getinfo_result.get("groups", []):
        label = BASIN_LABELS[int(g["region_num"]) - 1]
        vals = g["sum"]
        per_region[label] = dict(zip(VALUE_BANDS, vals))
    per_region["whole_lake"] = {band: (whole_vals.get(band) or 0.0) for band in VALUE_BANDS} \
        if whole_vals is not None else {band: 0.0 for band in VALUE_BANDS}
    return per_region


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    args = ap.parse_args()
    import ee
    ee.Initialize(project=args.project)
    _ee, audit010, runner, _gj, context = _init_ee(args.project)
    root = "projects/%s/assets/balaton_anomaly/" % args.project
    regions_fc = ee.FeatureCollection(root + "basin_boundaries")
    region_img = region_class_image(ee, regions_fc)
    geom = context["geometry"]
    eligible = _eligible_counts(context)  # whole-lake only, kept for the non-region baseline
    eligible_by_region = _eligible_counts_by_region(
        ee, runner, regions_fc, context["geometry"], STREAMS.keys())
    result = {"eligible_pixels_sum": eligible, "eligible_pixels_by_region": eligible_by_region, "rows": []}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for sid, (col_id, lb, qb) in STREAMS.items():
        ctx = runner.contexts[sid]
        stream = context["stream_by_id"][sid]
        normal = ee.Image(root + "pixel_normal_" + sid)
        for c0, c1 in CHUNKS:
            col = ee.ImageCollection(col_id).filterDate(c0, c1)
            area = ee.Image.pixelArea()

            # Deliberately only `img` is a parameter here, not the usual lb=lb/normal=normal
            # default-arg trick -- ee.List.map() (unlike ImageCollection.map()) counts every
            # declared parameter, default or not, to build its CustomFunction signature, so
            # a defaulted extra parameter gets silently overwritten with a placeholder and
            # loses its real value (AttributeError: 'ComputedObject' has no attribute 'select').
            # lb/qb/normal/ctx/stream are closed over instead -- safe because per_image() is
            # built and consumed within the same loop iteration, never deferred.
            def per_image(img):
                img = ee.Image(img)
                date = ee.Date(img.get("system:time_start"))
                mmdd = date.format("MMdd")
                mmdd = ee.String(ee.Algorithms.If(mmdd.equals("0229"), "0228", mmdd))
                tn = normal.select(ee.String("d").cat(mmdd).cat("_med"))
                nn = normal.select(ee.String("d").cat(mmdd).cat("_n"))
                today = lst_masked(ee, img, lb, qb)
                anom = today.subtract(tn).updateMask(nn.gte(MIN_N))
                anom_img = ee.Image.cat([
                    anom.multiply(area).rename("anom_w"),
                    area.updateMask(anom.mask()).rename("anom_a"),
                    ee.Image.constant(1).updateMask(anom.mask()).rename("anom_count"),
                ])
                lake_img = _masked_lake_stat_image(runner, ee, img, stream)
                value_img = ee.Image.cat([anom_img, lake_img])
                stacked = ee.Image.cat([value_img, region_img])
                reducer = ee.Reducer.sum().repeat(len(VALUE_BANDS)).group(
                    groupField=len(VALUE_BANDS), groupName="region_num")
                reduced = stacked.reduceRegion(
                    reducer=reducer, geometry=geom, crs=ctx["crs"], crsTransform=ctx["transform"],
                    bestEffort=False, maxPixels=2_000_000, tileScale=1)
                # Independent whole-lake reduction (not a sum of the 4 basins -- see
                # _grouped_region_stats' docstring for why that undercounts).
                whole = value_img.reduceRegion(
                    reducer=ee.Reducer.sum(), geometry=geom, crs=ctx["crs"],
                    crsTransform=ctx["transform"], bestEffort=False, maxPixels=2_000_000,
                    tileScale=1)
                props = {"date_utc": date.format("YYYY-MM-dd"), "groups": reduced.get("groups")}
                for b in VALUE_BANDS:
                    props["whole_" + b] = whole.get(b)
                return ee.Feature(None, props)

            feats = retry_getinfo(ee.FeatureCollection(col.map(per_image)).getInfo)
            n = 0
            for f in feats.get("features", []):
                p = f["properties"]
                date_utc = p["date_utc"]
                whole_vals = {b: p.get("whole_" + b) for b in VALUE_BANDS}
                by_region = _grouped_region_stats(ee, {"groups": p.get("groups") or []}, whole_vals)
                for region_id, b in by_region.items():
                    # Same exclusion rule the pre-METH-007 engine always used
                    # (run_anomaly_engine_ee.py _collect_daily_values: `count <= 0: continue`) --
                    # a day whose rounded pixel count is 0 is not reported at all, rather than
                    # shown with a real-looking temperature or anomaly from a sliver of a single
                    # border pixel. An earlier version dropped this check when the pixel-first
                    # calculation was added, letting a handful of sub-one-pixel days through.
                    if int(b.get("accepted_count") or 0) <= 0 or int(b.get("anom_count") or 0) <= 0:
                        continue
                    if not b.get("anom_a") or not b.get("area_sum"):
                        continue
                    result["rows"].append({
                        "stream_id": sid, "region_id": region_id, "date_utc": date_utc,
                        "anomaly_pixel_first_c": b["anom_w"] / b["anom_a"],
                        "daily_lst_c": b["weighted_sum"] / b["area_sum"],
                        "accepted_pixel_count": round(b["accepted_count"]),
                    })
                    n += 1
            print(json.dumps({"stream": sid, "chunk": c0, "rows": n}), flush=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"written": str(OUT), "rows": len(result["rows"])}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
