"""Exercise a full week of data for all zones, including a repeat prediction."""
import subprocess
from sqlalchemy import text
from platform_common.database import warehouse_engine
from forecasting.train_predict import main
from ingestion.quality import check_freshness

engine = warehouse_engine()
with engine.begin() as conn:
    conn.execute(text("DELETE FROM public.forecasts WHERE model_version='fixture-missing'"))
    conn.execute(text("""
        INSERT INTO raw.entsoe_raw(zone, period_start, position, resolution_minutes,
                                   quantity, doc_kind, loaded_at)
        SELECT zone, ts, 1, 60, 1000 + 100 * sin(extract(hour from ts)), 'load', now()
        FROM unnest(ARRAY['FR','DE','ES']) zone
        CROSS JOIN generate_series('2026-02-01'::timestamptz, '2026-02-07 23:00'::timestamptz, interval '1 hour') ts
    """))
    conn.execute(text("""
        INSERT INTO raw.entsoe_raw(zone, period_start, position, resolution_minutes,
                                   psr_type, quantity, doc_kind, loaded_at)
        SELECT zone, ts, 1, 60, psr,
               CASE WHEN psr='B16' THEN greatest(0, 50*sin(pi()*(extract(hour from ts)-6)/12))
                    ELSE 100+10*sin(extract(hour from ts)) END, 'generation', now()
        FROM unnest(ARRAY['FR','DE','ES']) zone
        CROSS JOIN unnest(ARRAY['B16','B18','B19']) psr
        CROSS JOIN generate_series('2026-02-01'::timestamptz, '2026-02-07 23:00'::timestamptz, interval '1 hour') ts
    """))
    conn.execute(text("""
        INSERT INTO raw.entsoe_raw(zone, period_start, position, resolution_minutes,
                                   price, doc_kind, loaded_at)
        SELECT zone, ts, 1, 60, 50, 'day_ahead_price', now()
        FROM unnest(ARRAY['FR','DE','ES']) zone
        CROSS JOIN generate_series('2026-02-01'::timestamptz, '2026-02-07 23:00'::timestamptz, interval '1 hour') ts
    """))
    conn.execute(text("""
        INSERT INTO raw.openmeteo_raw(zone, time, temperature_2m, wind_speed_10m, shortwave_radiation, loaded_at)
        SELECT zone, ts, 15 + sin(extract(hour from ts)), 10,
               greatest(0, 300*sin(pi()*(extract(hour from ts)-6)/12)), now()
        FROM unnest(ARRAY['FR','DE','ES']) zone
        CROSS JOIN generate_series('2026-02-01'::timestamptz, '2026-02-08'::timestamptz, interval '1 hour') ts
    """))
check_freshness("2026-02-08T00:00:00+00:00")
try:
    check_freshness("2026-03-01T00:00:00+00:00")
except ValueError:
    pass
else:
    raise AssertionError("Old events with recent loaded_at must fail freshness")
subprocess.run(["dbt", "build", "--project-dir", "/tmp/dbt-ci", "--profiles-dir", "/tmp/dbt-ci"], check=True)
for _ in range(2):
    main(interval_end="2026-02-08T00:00:00+00:00")
with engine.connect() as conn:
    rows = conn.execute(text("SELECT zone, target, ts, predicted_value FROM public.forecasts")).mappings().all()
    assert len(rows) == 9, rows
    assert {(r["zone"], r["target"]) for r in rows} == {
        (zone, target) for zone in ("FR", "DE", "ES") for target in ("demand", "wind_generation", "solar_generation")}
    assert all(r["ts"].isoformat() == "2026-02-08T00:00:00+00:00" for r in rows), rows
    assert all(r["predicted_value"] is not None for r in rows), rows
print("Forecast integration passed: nine zone/target predictions, repeat run is idempotent")
