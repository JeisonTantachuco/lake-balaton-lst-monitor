"""METH-007 step 3b - offline. Pools the leave-one-year-out historical pixel-first
anomalies (+/-5 days, Feb-29 fold, same as METH-001/003) and ranks each 2023-onward
headline anomaly (step 2) against that pool with the engine's own Type-7 percentile
and label rule. No Earth Engine, no network.
"""
from __future__ import annotations
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from run_anomaly_engine_ee import (fold_day_of_year, window_offsets, type7_percentile_rank,
                                    classify, confidence_from_fraction, PERCENTILE_MIN_N,
                                    PERCENTILE_FULL_N)

STATE = Path(__file__).resolve().parents[1] / "local_run_state" / "phase3_pixelfirst"
HIST = STATE / "historical_pixelfirst.json"
DAILY = STATE / "daily_headline.json"
OUT = STATE / "daily_records_pixelfirst.json"


def doy_of(date_str: str) -> int:
    y, m, d = (int(x) for x in date_str.split("-"))
    return fold_day_of_year(m, d)


def main() -> int:
    hist = json.loads(HIST.read_text(encoding="utf-8"))["rows"]
    daily = json.loads(DAILY.read_text(encoding="utf-8"))
    eligible_by_stream = daily["eligible_pixels_sum"]  # per-stream dict (engine's own _eligible_counts)

    pools: dict[tuple[str, int], list[float]] = {}
    for r in hist:
        d = doy_of(r["date_utc"])
        pools.setdefault((r["stream_id"], d), []).append(r["anomaly_pixel_first_c"])

    def pooled_sample(stream_id: str, doy: int) -> list[float]:
        vals: list[float] = []
        for d in window_offsets(doy):
            vals.extend(pools.get((stream_id, d), []))
        return sorted(vals)

    out_rows = []
    for r in daily["rows"]:
        doy = doy_of(r["date_utc"])
        sample = pooled_sample(r["stream_id"], doy)
        anomaly = r["anomaly_pixel_first_c"]
        if len(sample) >= PERCENTILE_MIN_N:
            pct = type7_percentile_rank(sample, anomaly)
            pct_confidence = "full" if len(sample) >= PERCENTILE_FULL_N else "limited_historical_sample"
        else:
            pct = None
            pct_confidence = "insufficient_history"
        eligible = eligible_by_stream.get(r["stream_id"], 0)
        fraction = (r.get("accepted_pixel_count") or 0) / eligible if eligible else 0.0
        out_rows.append({
            "stream_id": r["stream_id"], "date_utc": r["date_utc"],
            "anomaly_vs_median_c": round(anomaly, 4),
            "historical_percentile": round(pct, 2) if pct is not None else None,
            "percentile_confidence": pct_confidence,
            "classification": classify(pct),
            "historical_n": len(sample),
            "confidence": confidence_from_fraction(fraction),
            "valid_water_fraction": round(fraction, 4),
            "accepted_pixel_count": r.get("accepted_pixel_count"),
            "daily_lst_c": r.get("daily_lst_c"),
        })
    OUT.write_text(json.dumps({"eligible_pixels_sum": eligible_by_stream, "rows": out_rows}, indent=1), encoding="utf-8")
    print(json.dumps({"written": str(OUT), "rows": len(out_rows)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
