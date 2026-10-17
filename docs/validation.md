# Repository validation

Validation performed on 17 October 2026 after removing obsolete deployment files.
These checks concern the repository and synthetic test fixtures; they do not deploy
to Azure or certify production readiness.

| Check | Result |
| --- | --- |
| Airflow and API image builds | Passed |
| Terraform formatting and validation | Passed |
| Mocked foundation, bootstrap and application plans | 3 passed |
| Pipeline regression tests | 9 passed |
| API authentication, probes and outage behavior | 3 passed |
| dbt build | 33 tests and 6 models passed |
| Repeated bootstrap and managed PostgreSQL permission boundary | Passed |
| Forecast integration | 9 zone/target outputs; repeated run idempotent |
| Airflow DAG import | Passed; one active run configured |
| Python syntax and relative documentation links | Passed |
| Publishable-file checks | No state, plans, actual tfvars or private-key files included |

Terraform tests used a clean directory, mocked providers and no remote backend.
Docker integration checks used an explicitly selected CI environment file and
isolated PostgreSQL/Azurite containers. See README.md for reproducible commands.

The former AKS manifests, local deployment entrypoint and optional administration
VM source have been removed. Historical reports and graphics are retained only in
an ignored local archive. Operational deployment directories and private recovery
files remain excluded from Git. No Azure resources were changed during this cleanup.
