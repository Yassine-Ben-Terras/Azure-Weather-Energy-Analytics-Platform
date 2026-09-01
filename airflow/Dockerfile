FROM apache/airflow:2.9.3-python3.11
USER root
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
USER airflow
COPY airflow/requirements.txt /requirements.txt
RUN pip install --no-cache-dir "apache-airflow==2.9.3" -r /requirements.txt
RUN pip uninstall -y apache-airflow-providers-google apache-airflow-providers-snowflake && pip check
COPY --chown=airflow:root ingestion /opt/project/ingestion
COPY --chown=airflow:root forecasting /opt/project/forecasting
COPY --chown=airflow:root platform_common /opt/project/platform_common
COPY --chown=airflow:root scripts /opt/project/scripts
COPY --chown=airflow:root airflow/dags /opt/airflow/dags
COPY --chown=airflow:root dbt /opt/dbt
ENV PYTHONPATH=/opt/project DBT_PROFILES_DIR=/opt/dbt
# Delegate to the upstream entrypoint after safely constructing the metadata URL.
ENTRYPOINT ["/usr/bin/dumb-init", "--", "python", "/opt/project/scripts/container_entrypoint.py", "/entrypoint"]
