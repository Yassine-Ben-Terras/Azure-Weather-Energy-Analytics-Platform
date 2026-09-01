from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from ingestion.entsoe_fetcher import run as entsoe
from ingestion.openmeteo_fetcher import run as weather
from ingestion.load_to_warehouse import run as load
from ingestion.alerting import log_failure_to_warehouse
from ingestion.quality import check_freshness
from forecasting.train_predict import main as forecast

ZONES = [
    ("FR", "10YFR-RTE------C", 48.8566, 2.3522),
    ("DE", "10Y1001A1001A82H", 51.1657, 10.4515),
    ("ES", "10YES-REE------0", 40.4168, -3.7038),
]

with DAG(
    "energy_weather", schedule="@hourly", start_date=datetime(2024, 1, 1),
    catchup=False, max_active_runs=1, max_active_tasks=3,
    dagrun_timeout=timedelta(hours=2),
    default_args={"owner": "energy-weather", "retries": 3,
                  "retry_delay": timedelta(minutes=5), "execution_timeout": timedelta(minutes=45),
                  "on_failure_callback": log_failure_to_warehouse},
) as dag:
    # Manual backfills use dag_run.conf.interval_end; every task shares the same window.
    end = "{{ dag_run.conf.get('interval_end', data_interval_end.isoformat()) }}"
    ingestions = []
    for label, eic, lat, lon in ZONES:
        ingestions.append(PythonOperator(task_id=f"entsoe_{label}", python_callable=entsoe,
            op_kwargs={"zone_eic": eic, "zone_label": label, "interval_end": end}))
        ingestions.append(PythonOperator(task_id=f"weather_{label}", python_callable=weather,
            op_kwargs={"lat": lat, "lon": lon, "zone_label": label, "interval_end": end}))
    loader = PythonOperator(task_id="load", python_callable=load)
    fresh = PythonOperator(task_id="freshness", python_callable=check_freshness,
                           op_kwargs={"interval_end": end})
    transform = BashOperator(task_id="dbt_run", bash_command="cd /opt/dbt && dbt run --profiles-dir /opt/dbt --exclude forecasts_vs_actuals")
    test = BashOperator(task_id="dbt_test", bash_command="cd /opt/dbt && dbt test --profiles-dir /opt/dbt --exclude forecasts_vs_actuals")
    predict = PythonOperator(task_id="forecast", python_callable=forecast,
                             op_kwargs={"interval_end": end})
    compare = BashOperator(task_id="compare", bash_command="cd /opt/dbt && dbt build --profiles-dir /opt/dbt --select forecasts_vs_actuals")
    ingestions >> loader >> fresh >> transform >> test >> predict >> compare
