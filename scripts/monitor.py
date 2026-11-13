"""Independent probe: failure is observable even when the warehouse is down."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from platform_common.database import warehouse_engine

from platform_common.zones import ZONES

with warehouse_engine().connect() as conn:
    rows = conn.execute(text("""SELECT zone, max(ts) AS observed_at FROM marts.fct_demand_weather GROUP BY zone""")).mappings().all()
    rows = [row for row in rows if row["zone"] in ZONES]
    if {r["zone"] for r in rows} != set(ZONES):
        raise RuntimeError("Missing zones")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    if any(r["observed_at"] < cutoff for r in rows):
        raise RuntimeError("Stale source data")
    predictions = conn.execute(text("""SELECT zone, target, max(predicted_at) AS updated_at
        FROM public.forecasts GROUP BY zone, target""")).mappings().all()
    predictions = [row for row in predictions if row["zone"] in ZONES]
    expected = {(zone, target) for zone in ZONES
                for target in ("demand", "wind_generation", "solar_generation")}
    if {(r["zone"], r["target"]) for r in predictions} != expected or any(r["updated_at"] < datetime.now(timezone.utc) - timedelta(hours=3) for r in predictions):
        raise RuntimeError("Forecast pipeline stalled or warming up")
print("PLATFORM_HEALTH_OK", flush=True)
