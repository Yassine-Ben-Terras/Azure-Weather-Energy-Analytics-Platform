import os

from sqlalchemy import create_engine
from sqlalchemy.engine import URL


def database_url(prefix="WAREHOUSE", database=None):
    query = {"sslmode": os.getenv(f"{prefix}_SSLMODE", "verify-full")}
    if query["sslmode"] == "verify-full":
        query["sslrootcert"] = os.getenv(f"{prefix}_SSLROOTCERT", "/etc/ssl/certs/ca-certificates.crt")
    return URL.create(
        "postgresql+psycopg2", username=os.environ[f"{prefix}_USER"],
        password=os.environ[f"{prefix}_PASSWORD"], host=os.environ[f"{prefix}_HOST"],
        port=int(os.getenv(f"{prefix}_PORT", "5432")),
        database=database or os.environ[f"{prefix}_DB"], query=query,
    )

''
def warehouse_engine():
    return create_engine(database_url(), pool_pre_ping=True, future=True, hide_parameters=True)




