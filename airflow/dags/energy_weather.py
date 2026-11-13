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

from platform_common.zones import ZONES


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
    for label, zone in ZONES.items():
        ingestions.append(PythonOperator(task_id=f"entsoe_{label}", python_callable=entsoe,
            op_kwargs={"zone_eic": zone["entsoe_eic"], "zone_label": label, "interval_end": end}))
        ingestions.append(PythonOperator(task_id=f"weather_{label}", python_callable=weather,
            op_kwargs={"lat": zone["latitude"], "lon": zone["longitude"], "zone_label": label, "interval_end": end}))
    loader = PythonOperator(task_id="load", python_callable=load, trigger_rule="all_done")
    transform = BashOperator(task_id="dbt_run", bash_command="cd /opt/dbt && dbt run --profiles-dir /opt/dbt --exclude forecasts_vs_actuals+")
    test = BashOperator(task_id="dbt_test", bash_command="cd /opt/dbt && dbt test --profiles-dir /opt/dbt --exclude forecasts_vs_actuals+")
    compare = BashOperator(task_id="compare", trigger_rule="none_failed", bash_command="cd /opt/dbt && dbt build --profiles-dir /opt/dbt --select forecasts_vs_actuals+")
    ingestions >> loader >> transform >> test
    for label in ZONES:
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
