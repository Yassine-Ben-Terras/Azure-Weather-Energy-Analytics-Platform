#!/usr/bin/env bash
set -euo pipefail
python /workspace/scripts/bootstrap.py
python /workspace/scripts/bootstrap.py # repeatability
python /workspace/.github/ci/verify_managed_postgres.py
python -m unittest discover -s tests -p test_pipeline.py -v
python - <<'PY'
from pathlib import Path
from platform_common.database import warehouse_engine
with warehouse_engine().begin() as conn:
    conn.exec_driver_sql(Path('.github/ci/seed_fixture.sql').read_text())
PY
cp -R /workspace/dbt /tmp/dbt-ci
cd /tmp/dbt-ci
dbt build --profiles-dir .
cd /workspace
python .github/ci/verify_fixture.py
python .github/ci/verify_forecast.py
python - <<'PY'
from airflow.models import DagBag
bag = DagBag('/workspace/airflow/dags', include_examples=False)
assert not bag.import_errors, bag.import_errors
assert set(bag.dags) == {'energy_weather'}, set(bag.dags)
assert bag.dags['energy_weather'].max_active_runs == 1
print('DAG import and bootstrap checks passed')
PY
