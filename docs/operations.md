# Operations

## Deployment safety

Keep the active deployment directory and remote backend unchanged. Never copy sample
values over live parameters. Keep `stage = "apps"` after rollout; earlier stages remove
application resources. Never commit state, plans, credentials or actual tfvars.

The original Sweden application stack has been retired. The remote-state storage
may remain in Sweden and is still required by the Swiss deployment. Region alone
is not a reason to delete a resource.

The cloud-only source no longer declares the optional Metabase workload or admin VM.
When deliberately synchronizing it into the existing deployment directory, remove
`admin_access.tf` and the obsolete `admin_*` / `metabase_enabled` / `metabase_image`
inputs there too. Keep backend, image tag, project prefix and remaining real values.
Review a saved plan before applying. This repository cleanup does not deploy changes.

## Run and inspect

Use the container entrypoint wrapper for commands executed in the scheduler; it
constructs database connection settings from the injected secrets. Calling Airflow
without the wrapper can accidentally use a local SQLite database.

```bash
python /opt/project/scripts/container_entrypoint.py airflow dags list
python /opt/project/scripts/container_entrypoint.py airflow dags unpause energy_weather
python /opt/project/scripts/container_entrypoint.py airflow dags list-runs -d energy_weather
```

Check task states and logs before replaying a failure. Azure exec may throttle
connections; respect Retry-After and reuse an interactive shell when possible.
Do not print connection strings, API tokens or environment dumps in shared logs.

Before replacing the scheduler image, pause the DAG, wait for its active work to
finish, deploy, check health and resume. One active DAG run does not guarantee that
a process survives a container replacement.

## Recovery and monitoring

Source requests retry; a failed load transaction rolls back rows and its receipt.
For older gaps, use the DAG interval override and inspect source historical coverage.
Do not assume every provider retains the same history.

Monitor source age, scheduler health, task duration, PostgreSQL CPU credits/storage,
and missing monitoring heartbeats. Blob logs and PostgreSQL backups support diagnosis
and recovery; restoration should be rehearsed before production use.

The API's `/health` checks the process; `/ready` checks PostgreSQL. `/forecasts` and
`/metrics` require `X-API-Key`. A successful HTTP response alone is not proof of fresh
or prospectively valid forecasts.

## Reporting

Refresh the two exported datasets (warehouse analytical rows and forecasts), replace
the files used by Power BI without changing schema or paths, then refresh the report.
Keep timestamp types and zone keys consistent. Forecast and observation joins use
zone and target time, with a filter for the requested target.
