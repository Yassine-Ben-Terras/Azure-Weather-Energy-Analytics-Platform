# Public access deployment (new subscription only)

This module is separate from infra/azure. Do not migrate the old private state into it.
Pin subscription_id to the intended account and initialize a NEW Azure backend/state key.

## Network

No customer VNet, subnet, private DNS, NAT gateway or private endpoint. Container Apps uses Azure-managed networking. PostgreSQL has public access with individual IPv4 firewall entries only. No 0.0.0.0 Azure-wide rule. API and Airflow webserver ingress permit operator /32 addresses only, plus their normal application authentication. Scheduler has no ingress.

Blob Storage, Key Vault and ACR retain authenticated public endpoints and scoped managed identities; they are not IP-filtered by this module. Do not describe all infrastructure as IP allowlisted.

For changing client networks, set `restrict_app_ingress_to_operator_ips=false` to
make the HTTPS login/API endpoints reachable independently of the client IP.
Airflow still requires its database-backed login; `/forecasts` and `/metrics`
still require the API key. Health endpoints and the login page are public.
PostgreSQL remains IP allowlisted and encrypted, and Power BI uses `bi_reader`.
Use strong unique credentials stored in Key Vault. This simple development option
does not add MFA; Microsoft Entra authentication is a separate possible upgrade.

## Ordered deployment

1. Select and verify the new subscription, region, provider registration and quotas. Prepare ignored tfvars with explicit subscription_id, operator_ipv4_addresses, emails and ENTSO-E token. Create a separate state backend.
2. Apply stage=foundation. PostgreSQL initially admits only operator IPs; runtime allowlist may be empty. Record Azure's assigned availability zone in postgres_zone before the next plan to avoid zone drift.
3. Build/push Airflow and API images to the new ACR.
4. Discover outbound IPv4 addresses from the new environment using a temporary manual probe job that does not need PostgreSQL. Verify the addresses used by apps AND jobs; do not use the ingress/static IP as an egress address. Record the verified set in runtime_ipv4_addresses and apply firewall rules.
5. Apply stage=bootstrap, execute bootstrap job and verify success. Apply stage=apps. Check database connectivity for scheduler, API and monitor; adjust exact egress addresses if required. Do not open broad ranges as a workaround.
6. Connect Power BI Desktop PostgreSQL connector to postgres_fqdn:5432, database energy_weather, role bi_reader and secret bi-db from Key Vault. Require encrypted connectivity with certificate validation. Use marts tables and public.forecasts. Verify writes fail for bi_reader.
7. Validate one complete DAG run, refresh Power BI, check monitor logs. Set enable_network_probe=false and apply the reviewed plan to delete the temporary probe after capturing results.

## Operational limits

ACA outbound IPs may change over time. Refresh the allowlist after changes and on connectivity failures. An IP allowlist is not a workload identity: database credentials and least privilege remain necessary. A stable egress guarantee would require revisiting the no-VNet constraint (for example VNet + NAT).

Azure can report a large set of possible outbound addresses. Provisioning each PostgreSQL firewall rule with the AzureRM provider can be slow because server updates are serialized. Never substitute a broad Internet or Azure-wide rule to shorten deployment. If rules are created through Azure directly, reconcile them with declarative Terraform imports and review the resulting plan before continuing.

The bi_reader role already receives SELECT and default SELECT privileges on marts in bootstrap.py. Power BI Service connectivity and refresh require a separate decision; Desktop connectivity does not automatically configure Service access. Later private networking can require replacing resources, not just switching a flag.

Do not publish tfvars, passwords, tokens or state. A stopped PostgreSQL server can restart automatically after seven days; storage/registry costs remain while the subscription is active.

## Budget development profile
Default PostgreSQL: B1ms (1 vCore, 2 GiB), 32 GiB provisioned storage, 7-day backups, no HA. Storage auto-growth is disabled: monitor disk usage before it fills. Airflow parallelism and dbt threads are limited to 1, with one web worker and small metadata connection pools. The scheduler keeps one replica; HTTP-facing webserver and API can scale to zero when unused, at the cost of a cold start on the next request. This is a low-cost starting configuration, not a performance guarantee for concurrent dashboard refresh and ingestion. Measure full DAG duration, database connections, CPU credits and memory before increasing concurrency. ACR Basic, logs and the always-on Airflow scheduler also incur costs; the PostgreSQL size alone does not determine the project bill.

