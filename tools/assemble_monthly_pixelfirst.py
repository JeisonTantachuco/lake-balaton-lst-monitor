"""METH-007 step 4a - offline. Monthly summaries from the pixel-first daily records,
same calendar-day / minimum-valid-days / warm-percentile rules as assemble_monthly()
in run_anomaly_engine_ee.py (METH-005), applied to the single pixel-first anomaly
(the per-pixel reference is already the median, so there is no separate mean variant).
"""
from __future__ import annotations
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from run_anomaly_engine_ee import MONTHLY_MIN_VALID_DAYS, WARM_PERCENTILE

STATE = Path(__file__).resolve().parents[1] / "local_run_state" / "phase3_pixelfirst"
DAILY = STATE / "daily_records_pixelfirst.json"
OUT = STATE / "monthly_summaries_pixelfirst.json"


def main() -> int:
    records = json.loads(DAILY.read_text(encoding="utf-8"))["rows"]
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        groups.setdefault((r["stream_id"], r["date_utc"][:7]), []).append(r)
    rows = []
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
            rows.append(row)
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
        rows.append(row)
    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(json.dumps({"written": str(OUT), "rows": len(rows)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
