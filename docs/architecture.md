# Cloud architecture

## Runtime

The only deployment implementation is Terraform in `infra/azure`, targeting
Switzerland North by default. There is no AKS cluster, Kubernetes manifest or
on-premises deployment requirement.

| Component | Responsibility |
| --- | --- |
| Airflow scheduler | LocalExecutor; executes ingestion, dbt and forecasting inside the scheduler container |
| Airflow webserver | Workflow visibility; separate Container App |
| FastAPI | Read-only warehouse access with API-key authentication |
| Bootstrap job | Database roles, schemas, migrations and Airflow initialization |
| Monitor job | Warehouse freshness checks and health signals for Azure Monitor |
| PostgreSQL Flexible Server | Application warehouse and Airflow metadata |
| Blob Storage | Raw source objects and remote Airflow task logs |
| ACR | Versioned Airflow and API container images |
| Key Vault / managed identities | Secrets and scoped service permissions |
| Power BI | Reporting from exported datasets in the current deployment |

Bronze objects are kept in Blob; raw tables, dbt staging and analytical marts live
in PostgreSQL. The forecast baseline uses available history and timestamp-aligned lags.

## Access boundaries

Container Apps ingress and PostgreSQL are private. Operators need connectivity and
DNS resolution into the VNet. PostgreSQL clients use TLS with certificate verification.
Blob and Key Vault use authenticated HTTPS endpoints; these are not private endpoints.
Application identities have scoped Blob, registry and secret permissions.

The scheduler remains running; no Kubernetes worker fleet is needed for this workload.
Each app has one replica. This is a portfolio/MVP deployment, not a high-availability
or disaster-recovery guarantee.

## Reporting and retained compatibility

Metabase and the abandoned administration VM are no longer application components.
The existing Metabase metadata database and bootstrap credentials are retained to
avoid destructive SQL changes in the shared server. They are not an active BI service.

The [LinkedIn illustration](WeatherEnergy_LinkedIn_PowerBI.png) is a **target architecture**
communication asset: its Power BI link does not mean a direct private connection is
configured. Current reporting uses dataset exports. The README diagram describes that
actual flow.

## Quality and forecast limitations

Late source revisions are reloaded using Blob ETags and transactional load receipts.
Freshness is measured using source timestamps. Missing values are not equivalent to
zero production. Retry success demonstrates recovery, not completeness of upstream data.

Forecast targets are latest observation plus one hour. If observations arrive late,
these are historical estimates rather than future predictions at issuance. MAE and
MAPE from matched observations are descriptive; a leakage-aware rolling backtest is
needed to assess forecast skill. One weather point per zone is a simplification.
