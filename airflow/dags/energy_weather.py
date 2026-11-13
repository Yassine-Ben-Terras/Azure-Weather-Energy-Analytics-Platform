import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator, ShortCircuitOperator
from ingestion.entsoe_fetcher import run as entsoe
from ingestion.openmeteo_fetcher import run as weather
from ingestion.load_to_warehouse import run as load
from ingestion.alerting import log_failure_to_warehouse
from ingestion.quality import StaleSourceError, check_freshness
from forecasting.train_predict import main as forecast

ZONES = [
    ("FR", "10YFR-RTE------C", 48.8566, 2.3522),
    ("DE", "10Y1001A1001A82H", 51.1657, 10.4515),
    ("ES", "10YES-REE------0", 40.4168, -3.7038),
]

def zone_is_fresh(interval_end, zone):
    try:
        check_freshness(interval_end, zones=(zone,))
    except StaleSourceError as exc:
        logging.getLogger(__name__).warning("Skipping forecasts for %s: %s", zone, exc)
        return False
    return True


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
    transform = BashOperator(task_id="dbt_run", bash_command="cd /opt/dbt && dbt run --profiles-dir /opt/dbt --exclude forecasts_vs_actuals")
    test = BashOperator(task_id="dbt_test", bash_command="cd /opt/dbt && dbt test --profiles-dir /opt/dbt --exclude forecasts_vs_actuals")
    compare = BashOperator(task_id="compare", trigger_rule="none_failed_min_one_success", bash_command="cd /opt/dbt && dbt build --profiles-dir /opt/dbt --select forecasts_vs_actuals")
    ingestions >> loader >> transform >> test
    for label, _, _, _ in ZONES:
        fresh = ShortCircuitOperator(
            task_id=f"freshness_{label}", python_callable=zone_is_fresh,
            op_kwargs={"interval_end": end, "zone": label},
            ignore_downstream_trigger_rules=False,
        )
        predict = PythonOperator(
            task_id=f"forecast_{label}", python_callable=forecast,
            op_kwargs={"interval_end": end, "zone": label},
        )
        test >> fresh >> predict >> compare
