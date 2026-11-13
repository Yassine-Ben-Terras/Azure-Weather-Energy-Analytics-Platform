"""Check event time, not just the time at which old data was loaded."""
import os
import logging
from datetime import datetime, timedelta
from sqlalchemy import text
from platform_common.database import warehouse_engine

from platform_common.zones import ZONES

logger = logging.getLogger(__name__)


class StaleSourceError(ValueError):
    """Required source data is stale or missing."""


def check_freshness(interval_end, zones=None):
    end = datetime.fromisoformat(interval_end)
    cutoff = end - timedelta(hours=int(os.getenv("MAX_SOURCE_AGE_HOURS", "24")))
    with warehouse_engine().connect() as conn:
        for zone in ZONES if zones is None else zones:
            for kind in ("load", "generation", "day_ahead_price"):
                last = conn.execute(text("""
                    SELECT max(period_start + (position - 1) * resolution_minutes * interval '1 minute')
                    FROM raw.entsoe_raw WHERE zone=:zone AND doc_kind=:kind
                      AND period_start + (position - 1) * resolution_minutes * interval '1 minute' < :end
                """), {"zone": zone, "kind": kind, "end": end}).scalar()
                if last is None or last < cutoff:
                    if kind == "day_ahead_price":
                        logger.warning("Optional day-ahead prices are stale or missing for %s (latest observation: %s)", zone, last)
                        continue
                    raise StaleSourceError(f"Stale or missing {kind} for {zone}")
            last = conn.execute(text("SELECT max(time) FROM raw.openmeteo_raw WHERE zone=:zone AND time < :end"),
                                {"zone": zone, "end": end}).scalar()
            if last is None or last < cutoff:
                raise StaleSourceError(f"Stale or missing weather for {zone}")
    print("PIPELINE_FRESHNESS_OK")
