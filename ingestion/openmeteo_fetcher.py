"""
Pulls hourly temperature, wind speed, and solar radiation from the free
Open-Meteo API and lands raw JSON in Azure Blob Storage (or Azurite for
local dev), partitioned by source/zone/date.

Docs: https://open-meteo.com/en/docs

Run standalone for local testing:
    python -m ingestion.openmeteo_fetcher --lat 48.85 --lon 2.35 --zone-label FR

Called from Airflow via airflow/dags/ingest_openmeteo.py.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import requests

from ingestion.state import get_client

OPENMETEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE_NAME = "openmeteo"
HOURLY_VARS = "temperature_2m,wind_speed_10m,shortwave_radiation"


def fetch_window(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HOURLY_VARS,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "UTC",
    }
    resp = requests.get(OPENMETEO_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def run(lat: float, lon: float, zone_label: str, interval_end: str | None = None) -> None:
    container = os.environ["AZURE_STORAGE_CONTAINER"]
    client = get_client()

    now = (datetime.fromisoformat(interval_end) if interval_end else datetime.now(timezone.utc)).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    # Re-read recent periods for late publications/corrections. Older gaps use a backfill run.
    period_start = now - timedelta(days=int(os.getenv("INGEST_LOOKBACK_DAYS", "7")))

    if period_start.date() > now.date():
        print(f"[{SOURCE_NAME}/{zone_label}] already up to date.")
        return

    day = period_start.replace(hour=0)
    while day <= now:
        date = day.strftime("%Y-%m-%d")
        payload = fetch_window(lat, lon, date, date)
        object_name = f"{SOURCE_NAME}/{zone_label}/{date}/weather_{day:%Y%m%d}.json"
        client.get_container_client(container).upload_blob(
            name=object_name, data=json.dumps(payload).encode(), overwrite=True)
        print(f"[{SOURCE_NAME}/{zone_label}] wrote {object_name}")
        day += timedelta(days=1)



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat", type=float, default=48.8566, help="Latitude (default: Paris)")
    parser.add_argument("--lon", type=float, default=2.3522, help="Longitude (default: Paris)")
    parser.add_argument("--zone-label", default="FR", help="Short label used in the storage path")
    args = parser.parse_args()
    run(args.lat, args.lon, args.zone_label)