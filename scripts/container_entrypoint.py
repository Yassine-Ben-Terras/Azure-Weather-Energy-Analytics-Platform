"""Construct the Airflow SQL URL without shell escaping passwords."""
import os
import sys
from platform_common.database import database_url

if os.getenv("AIRFLOW_DB_PASSWORD"):
    os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = database_url("AIRFLOW_DB").render_as_string(hide_password=False)
os.execvp(sys.argv[1], sys.argv[1:])
