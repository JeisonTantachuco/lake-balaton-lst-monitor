"""METH-007 step 5 - export the pixel-first daily records and monthly summaries,
overwriting the published assets. The lake-mean versions are backed up first to
balaton_anomaly_backup_lakewide/ (not deleted). Coordinate-free (null-island points).
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "local_run_state" / "phase3_pixelfirst"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_anomaly_engine_ee import _feature_collection, _run_table_exports  # noqa: E402


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    args = ap.parse_args()
    import ee
    ee.Initialize(project=args.project)
    root = "projects/%s/assets/balaton_anomaly/" % args.project
    backup_root = "projects/%s/assets/balaton_anomaly_backup_lakewide/" % args.project

    try:
        ee.data.getAsset(backup_root.rstrip("/"))
    except Exception:
        ee.data.createAsset({"type": "FOLDER"}, backup_root.rstrip("/"))
    for name in ("daily_anomaly_records", "monthly_summaries"):
        src = root + name
        dst = backup_root + name
        try:
            ee.data.getAsset(dst)
            print(json.dumps({"backup_exists": name}))
        except Exception:
            ee.data.copyAsset(src, dst)
            print(json.dumps({"backed_up": name}))

    daily_rows = json.loads((STATE / "daily_records_pixelfirst.json").read_text(encoding="utf-8"))["rows"]
    monthly_rows = json.loads((STATE / "monthly_summaries_pixelfirst.json").read_text(encoding="utf-8"))

    jobs = [
        {"asset_id": root + "daily_anomaly_records", "description": "balaton_daily_anomaly_records",
         "overwrite": True, "collection": _feature_collection(ee, daily_rows)},
        {"asset_id": root + "monthly_summaries", "description": "balaton_monthly_summaries",
         "overwrite": True, "collection": _feature_collection(ee, monthly_rows)},
    ]
    session_deadline = time.monotonic() + 3000
    _run_table_exports(ee, jobs, session_deadline)
    for name in ("daily_anomaly_records", "monthly_summaries"):
        ee.data.setAssetAcl(root + name, {"all_users_can_read": True})
    print(json.dumps({"EXPORT_DONE": True, "daily_rows": len(daily_rows), "monthly_rows": len(monthly_rows)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
