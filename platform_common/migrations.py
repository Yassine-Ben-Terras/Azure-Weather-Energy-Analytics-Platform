"""Idempotent bootstrap, before dbt can reference application tables."""
from sqlalchemy import text


def migrate(engine):
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(8472190)"))
        for schema in ("raw", "staging", "marts"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.forecasts (
                zone TEXT, ts TIMESTAMPTZ, target TEXT, predicted_value DOUBLE PRECISION,
                model_version TEXT, predicted_at TIMESTAMPTZ,
                PRIMARY KEY (zone, ts, target, model_version))
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.pipeline_alerts (
                id SERIAL PRIMARY KEY, dag_id TEXT, task_id TEXT, run_id TEXT,
                logical_date TIMESTAMPTZ, error_message TEXT, failed_at TIMESTAMPTZ)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw.ingestion_objects (
                container TEXT NOT NULL, name TEXT NOT NULL, etag TEXT NOT NULL,
                source_modified_at TIMESTAMPTZ NOT NULL,
                loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (container, name))
        """))
