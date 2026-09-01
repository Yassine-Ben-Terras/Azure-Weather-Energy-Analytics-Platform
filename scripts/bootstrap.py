"""Run once as DB administrator, locally or as an Azure Container Apps Job.

No passwords in SQL logs/CLI arguments. All role names are fixed by this module.
"""
import os
import subprocess

from psycopg2 import sql
from sqlalchemy import create_engine

from platform_common.database import database_url, warehouse_engine
from platform_common.migrations import migrate


def main():
    admin = create_engine(database_url("ADMIN", "postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True)
    roles = {
        "pipeline": "WAREHOUSE_PASSWORD", "airflow": "AIRFLOW_DB_PASSWORD",
        "metabase": "METABASE_DB_PASSWORD", "api_reader": "API_DB_PASSWORD",
        "bi_reader": "BI_DB_PASSWORD",
    }
    databases = {os.environ["WAREHOUSE_DB"]: "pipeline", "airflow": "airflow", "metabase": "metabase"}
    with admin.connect() as conn:
        with conn.connection.cursor() as cur:
            for role, key in roles.items():
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cur.fetchone() is None:
                    cur.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
                cur.execute(sql.SQL("ALTER ROLE {} PASSWORD %s").format(sql.Identifier(role)), (os.environ[key],))
                # Required to transfer ownership on Flexible Server (admin is not superuser).
                # PostgreSQL 16's automatic creator membership has SET/INHERIT
                # disabled. Enable both explicitly for ownership transfers.
                # Creator ADMIN rights already exist. Granting ADMIN back to
                # oneself can create a forbidden circular grant in PostgreSQL.
                cur.execute(sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET TRUE").format(sql.Identifier(role), sql.Identifier(os.environ["ADMIN_USER"])))
            for database, owner in databases.items():
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
                if cur.fetchone() is None:
                    cur.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(database), sql.Identifier(owner)))
                cur.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(sql.Identifier(database), sql.Identifier(owner)))
                cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
                if owner == "pipeline":
                    cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO api_reader, bi_reader").format(sql.Identifier(database)))
    admin.dispose()
    # Azure's public schema belongs to azure_pg_admin even after ALTER DATABASE
    # OWNER. Only the administrative connection can revoke its PUBLIC grants.
    # Grant CREATE explicitly to each application owner before any migrations.
    for database, owner in databases.items():
        schema_admin = create_engine(database_url("ADMIN", database), hide_parameters=True)
        try:
            with schema_admin.begin() as conn:
                with conn.connection.cursor() as cur:
                    cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                    cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(owner)))
        finally:
            schema_admin.dispose()
    engine = warehouse_engine()
    migrate(engine)
    from ingestion.load_to_warehouse import _ensure_tables
    _ensure_tables(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("GRANT USAGE ON SCHEMA public, marts TO api_reader, bi_reader")
        conn.exec_driver_sql("GRANT SELECT ON public.forecasts, public.pipeline_alerts TO api_reader, bi_reader")
        conn.exec_driver_sql("GRANT SELECT ON ALL TABLES IN SCHEMA marts TO api_reader, bi_reader")
        conn.exec_driver_sql("ALTER DEFAULT PRIVILEGES FOR ROLE pipeline IN SCHEMA marts GRANT SELECT ON TABLES TO api_reader, bi_reader")
    if os.getenv("BOOTSTRAP_STORAGE", "true").lower() == "true":
        from azure.core.exceptions import ResourceExistsError
        from ingestion.state import get_client
        client = get_client()
        for name in (os.environ["AZURE_STORAGE_CONTAINER"], "airflow-logs"):
            try:
                client.create_container(name)
            except ResourceExistsError:
                pass
    subprocess.run(["airflow", "db", "migrate"], check=True)
    # Use FAB API so credentials never become command-line arguments. Existing users stay intact.
    from airflow.www.app import create_app
    with create_app().app_context() as ctx:
        sm = ctx.app.appbuilder.sm
        username = os.getenv("AIRFLOW_ADMIN_USER", "admin")
        if not sm.find_user(username=username):
            user = sm.add_user(username, "Platform", "Admin", os.environ["AIRFLOW_ADMIN_EMAIL"],
                               sm.find_role("Admin"), os.environ["AIRFLOW_ADMIN_PASSWORD"])
            if not user:
                raise RuntimeError("Airflow admin creation failed")


if __name__ == "__main__":
    main()
