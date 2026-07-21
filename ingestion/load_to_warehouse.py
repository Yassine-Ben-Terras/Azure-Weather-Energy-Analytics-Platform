"""Load each Blob version and its receipt in one PostgreSQL transaction.
Changed versions replace their own raw rows; a crash rolls both changes back.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from azure.core import MatchConditions
from platform_common.database import warehouse_engine
from platform_common.migrations import migrate

from ingestion.state import get_client


# Matches the fixed timestamp suffix entsoe_fetcher.py appends to every
# filename (e.g. "..._20260912T1900_20260914T1800.xml"), so whatever's left
# after stripping it is the true doc_kind -- unlike a naive split("_")[0],
# this correctly keeps multi-word kinds like "day_ahead_price" intact.
_DOC_KIND_SUFFIX_RE = re.compile(r"_\d{8}T\d{4}_\d{8}T\d{4}\.xml$")

# Reject missing/unknown resolutions instead of silently shifting observation times.
_RESOLUTION_RE = re.compile(r"PT(\d+)M")


def _resolution_to_minutes(resolution: str | None) -> int:
    if resolution:
        match = _RESOLUTION_RE.match(resolution)
        if match:
            return int(match.group(1))
        if resolution == "PT1H":
            return 60
    if resolution is None:
        raise ValueError("Missing ENTSO-E resolution")
    raise ValueError(f"Unsupported ENTSO-E resolution: {resolution}")


_warehouse_engine = warehouse_engine


def _ensure_tables(engine) -> None:
    migrate(engine)
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(8472190)"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw.entsoe_raw (
                zone TEXT,
                period_start TIMESTAMPTZ,
                position INTEGER,
                resolution_minutes INTEGER,
                psr_type TEXT,
                quantity DOUBLE PRECISION,
                price DOUBLE PRECISION,
                doc_kind TEXT,
                loaded_at TIMESTAMPTZ
            )
        """))
        # ALTER for anyone re-running against a table created before this
        # column existed -- harmless no-op if it's already there.
        conn.execute(text("""
            ALTER TABLE raw.entsoe_raw ADD COLUMN IF NOT EXISTS resolution_minutes INTEGER
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw.openmeteo_raw (
                zone TEXT,
                time TIMESTAMPTZ,
                temperature_2m DOUBLE PRECISION,
                wind_speed_10m DOUBLE PRECISION,
                shortwave_radiation DOUBLE PRECISION,
                loaded_at TIMESTAMPTZ
            )
        """))

        for table in ("entsoe_raw", "openmeteo_raw"):
            conn.execute(text(f"ALTER TABLE raw.{table} ADD COLUMN IF NOT EXISTS source_blob TEXT"))
            conn.execute(text(f"ALTER TABLE raw.{table} ADD COLUMN IF NOT EXISTS source_container TEXT"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {table}_blob_idx ON raw.{table}(source_container, source_blob)"))


def _insert_rows(conn, table: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    # Swap pandas NaN for real None so psycopg2 doesn't choke binding NaN
    # into non-float columns (e.g. psr_type, doc_kind).
    df = df.astype(object).where(pd.notnull(df), None)
    records = df.to_dict(orient="records")
    columns = list(records[0].keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    stmt = text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})")
    conn.execute(stmt, records)


def _parse_entsoe_xml(content: bytes, doc_kind: str, zone_label: str) -> pd.DataFrame:
    """
    Minimal ENTSO-E GL_MarketDocument parser: flattens <Point> elements
    (position/quantity, or position/price.amount) into rows. Extend as needed
    for multi-TimeSeries documents (e.g. generation split by psr type).

    Each Period carries its own <resolution> (commonly PT15M for generation,
    sometimes PT60M elsewhere) -- position is an index within that Period at
    that resolution, NOT a fixed 1-hour step. resolution_minutes is captured
    per row so downstream ts computation (in dbt) can convert position to a
    real timestamp correctly instead of assuming hourly steps universally.
    """
    root = ET.fromstring(content)
    rows = []
    for ts in root.iter():
        if ts.tag.endswith("TimeSeries"):
            psr_type = None
            for psr in ts.iter():
                if psr.tag.endswith("psrType"):
                    psr_type = psr.text
            for period in ts.iter():
                if period.tag.endswith("Period"):
                    start = None
                    resolution = None
                    for s in period.iter():
                        if s.tag.endswith("start"):
                            start = s.text
                        elif s.tag.endswith("resolution"):
                            resolution = s.text
                    resolution_minutes = _resolution_to_minutes(resolution)
                    for point in period.iter():
                        if point.tag.endswith("Point"):
                            position = quantity = price = None
                            for child in point:
                                tag = child.tag.split("}")[-1]
                                if tag == "position":
                                    position = int(child.text)
                                elif tag == "quantity":
                                    quantity = float(child.text)
                                elif tag == "price.amount":
                                    price = float(child.text)
                            rows.append({
                                "zone": zone_label,
                                "period_start": start,
                                "position": position,
                                "resolution_minutes": resolution_minutes,
                                "psr_type": psr_type,
                                "quantity": quantity,
                                "price": price,
                            })
    if not rows:
        raise ValueError("ENTSO-E response contains no observations")
    df = pd.DataFrame(rows)
    df["doc_kind"] = doc_kind
    df["loaded_at"] = datetime.now(timezone.utc)
    return df


def _parse_openmeteo_json(content: bytes, zone_label: str) -> pd.DataFrame:
    payload = json.loads(content)
    hourly = payload["hourly"]
    columns = ("time", "temperature_2m", "wind_speed_10m", "shortwave_radiation")
    df = pd.DataFrame({column: hourly[column] for column in columns})
    if df.empty:
        raise ValueError("Weather response contains no observations")
    df["zone"] = zone_label
    df["loaded_at"] = datetime.now(timezone.utc)
    return df


def load_blob(conn, container_client, container, blob):
    source = blob.name.split("/")[0]
    if source not in ("entsoe", "openmeteo"):
        return False
    suffix = ".xml" if source == "entsoe" else ".json"
    if not blob.name.endswith(suffix):
        return False
    receipt = conn.execute(text("SELECT etag FROM raw.ingestion_objects WHERE container=:c AND name=:n"),
                           {"c": container, "n": blob.name}).scalar()
    if receipt == blob.etag:
        return False
    # If replaced after listing, fail and retry rather than record the wrong ETag.
    content = container_client.download_blob(blob.name, etag=blob.etag,
                                             match_condition=MatchConditions.IfNotModified).readall()
    zone = blob.name.split("/")[1]
    if source == "entsoe":
        kind = _DOC_KIND_SUFFIX_RE.sub("", blob.name.split("/")[-1])
        if kind not in ("load", "generation", "day_ahead_price"):
            raise ValueError(f"Unexpected ENTSO-E object: {blob.name}")
        df = _parse_entsoe_xml(content, kind, zone)
    else:
        df = _parse_openmeteo_json(content, zone)
    df["loaded_at"] = blob.last_modified
    df["source_blob"] = blob.name
    df["source_container"] = container
    table = f"raw.{source}_raw"
    conn.execute(text(f"DELETE FROM {table} WHERE source_container=:c AND source_blob=:n"),
                 {"c": container, "n": blob.name})
    _insert_rows(conn, table, df)
    conn.execute(text("""
        INSERT INTO raw.ingestion_objects(container, name, etag, source_modified_at)
        VALUES (:c, :n, :e, :m)
        ON CONFLICT (container, name) DO UPDATE SET etag=excluded.etag,
            source_modified_at=excluded.source_modified_at, loaded_at=now()
    """), {"c": container, "n": blob.name, "e": blob.etag, "m": blob.last_modified})
    return True


def run() -> None:
    container = os.environ["AZURE_STORAGE_CONTAINER"]
    client = get_client().get_container_client(container)
    engine = _warehouse_engine()
    _ensure_tables(engine)
    # Session lock serializes complete loaders, including manual/revision overlap.
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(8472191)"))
        conn.commit()
        try:
            loaded = 0
            for source in ("entsoe", "openmeteo"):
                for blob in client.list_blobs(name_starts_with=f"{source}/"):
                    with conn.begin():
                        loaded += int(load_blob(conn, client, container, blob))
            print(f"[load_to_warehouse] loaded {loaded} new or changed objects")
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(8472191)"))
            conn.commit()


if __name__ == "__main__":
    run()
