"""
Pulls load, generation-by-type, and day-ahead prices from the ENTSO-E
Transparency Platform API and lands them as raw XML in Azure Blob
Storage (or Azurite for local dev), partitioned by source/zone/date.

Docs: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html

Run standalone for local testing:
    python -m ingestion.entsoe_fetcher --zone-eic 10YFR-RTE------C

Called from Airflow via airflow/dags/ingest_entsoe.py.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

import requests

from ingestion.state import get_client

ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
SOURCE_NAME = "entsoe"

# ENTSO-E documentType codes and the domain/processType params each one expects.
# ENTSO-E is picky here: sending in_Domain/out_Domain to the load or generation
# endpoints (instead of outBiddingZone_Domain / in_Domain respectively) returns
# a 400 Bad Request rather than a helpful error message.
DOC_TYPES = {
    "load": {
        "documentType": "A65",
        "processType": "A16",  # realised
        "domain_params": lambda zone: {"outBiddingZone_Domain": zone},
    },
    "generation": {
        "documentType": "A75",
        "processType": "A16",  # realised
        "domain_params": lambda zone: {"in_Domain": zone},
    },
    "day_ahead_price": {
        "documentType": "A44",
        "domain_params": lambda zone: {"in_Domain": zone, "out_Domain": zone},
    },
}


def fetch_window(token: str, doc_config: dict, zone_eic: str, period_start: datetime, period_end: datetime) -> bytes:
    params = {
        "securityToken": token,
        "documentType": doc_config["documentType"],
        "periodStart": period_start.strftime("%Y%m%d%H%M"),
        "periodEnd": period_end.strftime("%Y%m%d%H%M"),
        **doc_config["domain_params"](zone_eic),
    }
    if "processType" in doc_config:
        params["processType"] = doc_config["processType"]
    resp = requests.get(ENTSOE_BASE_URL, params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"ENTSO-E returned HTTP {resp.status_code}") # Never log token-bearing URL
    return resp.content  # raw XML from ENTSO-E


def run(zone_eic: str, zone_label: str, interval_end: str | None = None) -> None:
    token = os.environ["ENTSOE_API_TOKEN"]
    container = os.environ["AZURE_STORAGE_CONTAINER"]
    client = get_client()

    now = (datetime.fromisoformat(interval_end) if interval_end else datetime.now(timezone.utc)).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    # Re-read recent periods for late publications/corrections. Older gaps use a backfill run.
    period_start = now - timedelta(days=int(os.getenv("INGEST_LOOKBACK_DAYS", "7")))
    period_end = now

    if period_start >= period_end:
        print(f"[{SOURCE_NAME}/{zone_label}] already up to date.")
        return

    # Stable daily keys avoid storing a new overlapping seven-day snapshot every hour.
    day = period_start.replace(hour=0)
    while day < period_end:
        next_day = day + timedelta(days=1)
        for name, doc_config in DOC_TYPES.items():
            content = fetch_window(token, doc_config, zone_eic, day, min(next_day, period_end))
            object_name = f"{SOURCE_NAME}/{zone_label}/{day:%Y-%m-%d}/{name}_{day:%Y%m%dT%H%M}_{next_day:%Y%m%dT%H%M}.xml"
            client.get_container_client(container).upload_blob(name=object_name, data=content, overwrite=True)
            print(f"[{SOURCE_NAME}/{zone_label}] wrote {object_name}")
        day = next_day



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone-eic", default="10YFR-RTE------C", help="ENTSO-E EIC bidding zone code")
    parser.add_argument("--zone-label", default="FR", help="Short label used in the storage path")
    args = parser.parse_args()
    run(args.zone_eic, args.zone_label)