"""Exercise bootstrap with a nonsuperuser admin and externally owned schemas.

This emulates the PostgreSQL permission boundary relevant to Flexible Server;
it does not emulate Azure networking or all Azure-specific role restrictions.
Run only against the isolated CI PostgreSQL instance.
"""
import os
from unittest.mock import patch

from psycopg2 import sql
from sqlalchemy import create_engine

from platform_common.database import database_url
from scripts.bootstrap import main

roles = ("pipeline", "airflow", "metabase", "api_reader", "bi_reader")
databases = {os.environ["WAREHOUSE_DB"]: "pipeline", "airflow": "airflow", "metabase": "metabase"}
root = create_engine(database_url("ADMIN", "postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True)
with root.connect() as conn:
    with conn.connection.cursor() as cur:
        cur.execute("CREATE ROLE ci_schema_owner NOLOGIN")
        cur.execute("CREATE ROLE ci_managed_admin LOGIN CREATEDB CREATEROLE PASSWORD %s", ("ci-only-managed-admin",))
        cur.execute("GRANT ci_schema_owner TO ci_managed_admin")
        for role in roles:
            cur.execute(sql.SQL("GRANT {} TO ci_managed_admin WITH ADMIN TRUE, SET FALSE, INHERIT FALSE").format(sql.Identifier(role)))
        for database in databases:
            cur.execute(sql.SQL("ALTER DATABASE {} OWNER TO ci_managed_admin").format(sql.Identifier(database)))
root.dispose()
for database, owner in databases.items():
    engine = create_engine(database_url("ADMIN", database), hide_parameters=True)
    with engine.begin() as conn:
        with conn.connection.cursor() as cur:
            cur.execute("ALTER SCHEMA public OWNER TO ci_schema_owner")
            cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cur.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(sql.Identifier(owner)))
    engine.dispose()
with patch.dict(os.environ, {"ADMIN_USER": "ci_managed_admin", "ADMIN_PASSWORD": "ci-only-managed-admin"}):
    main()
    main()
for database, owner in databases.items():
    engine = create_engine(database_url("ADMIN", database))
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT rolsuper FROM pg_roles WHERE rolname='ci_managed_admin'").scalar() is False
        assert conn.exec_driver_sql(f"SELECT pg_has_role('ci_managed_admin', '{owner}', 'SET')").scalar() is True
        assert conn.exec_driver_sql(f"SELECT pg_has_role('ci_managed_admin', '{owner}', 'USAGE')").scalar() is True
        assert conn.exec_driver_sql(f"SELECT has_schema_privilege('{owner}', 'public', 'CREATE')").scalar() is True
        for reader in ("api_reader", "bi_reader"):
            assert conn.exec_driver_sql(f"SELECT has_schema_privilege('{reader}', 'public', 'CREATE')").scalar() is False
    engine.dispose()
print("Managed PostgreSQL permission boundary and repeated bootstrap passed")
