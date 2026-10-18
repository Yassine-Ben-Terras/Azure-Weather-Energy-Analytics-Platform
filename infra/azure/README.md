# Deploy WeatherEnergy on Azure

Terraform provisions a private Container Apps environment in **Switzerland North**,
PostgreSQL Flexible Server, Blob Storage, ACR, Key Vault, identities and monitoring.
Application workloads are Airflow scheduler, Airflow webserver and FastAPI, plus
bootstrap and monitoring jobs. Reporting uses Power BI outside Container Apps.

## Prerequisites

Install Azure CLI, Terraform >= 1.7 and < 2, Docker and PowerShell. Obtain an ENTSO-E
token. The deployer needs resource-creation and RBAC-assignment permissions, and
access to the storage and vault data endpoints. Check subscription quotas and region
policy; a listed SKU does not guarantee allocation capacity.

```powershell
az login
az account show --query "{name:name,id:id}" -o table
python scripts/check_azure_region.py --location switzerlandnorth
```

Register the Azure providers reported as missing by the preflight script before
provisioning. Every cloud deployment can incur charges.

## Prepare an isolated directory and backend

For a **new deployment** only:

```powershell
./scripts/prepare_azure_deployment.ps1 -Destination '.azure-deploy/new-swiss-dev'
Set-Location '.azure-deploy/new-swiss-dev'
```

The helper copies source and examples, never existing state, `.terraform` or actual
credentials. Edit `terraform.tfvars` and `backend.hcl` in that directory. Use a unique
project prefix and backend key. Set contact emails, region and database sizing.

Provision a separate Storage account and private `tfstate` container for the backend,
with Entra/RBAC access, versioning and soft deletion. Grant the deployer
`Storage Blob Data Contributor`. The backend example contains placeholders; replace
them with your existing backend account and container. Do not put account keys in Git.
State contains secrets even when Terraform output marks them sensitive.

Provide `TF_VAR_entsoe_api_token` in the process environment through your secret
manager or a private prompt. Do not paste it into shell history or public logs.

```powershell
terraform init -backend-config=backend.hcl
terraform validate
terraform plan -out=foundation.tfplan
terraform apply foundation.tfplan
```

Inspect the saved plan first: a new foundation should not destroy another deployment.
If using the existing environment, keep its original backend and parameters instead
of following the new-deployment setup.

## Publish images

From the deployment directory, read `terraform output -raw acr_name` and
`terraform output -raw acr_login_server`. From the repository root, substitute those
values and an immutable tag in the following commands:

```bash
az acr login --name <acr-name>
docker build -t <registry>/airflow:<tag> -f airflow/Dockerfile .
docker build -t <registry>/api:<tag> -f api/Dockerfile .
docker push <registry>/airflow:<tag>
docker push <registry>/api:<tag>
```

Use the same tag for both images. Keep the tested digest for release traceability.

## Bootstrap and start applications

In the deployment tfvars, set `image_tag` and `stage = "bootstrap"`. Plan and apply.
Read the `bootstrap_job_name` and `resource_group_name` outputs:

```bash
az containerapp job start --resource-group <group> --name <bootstrap-job>
az containerapp job execution list --resource-group <group> --name <bootstrap-job> -o table
```

Wait for **Succeeded**, then set `stage = "apps"`, plan and apply. Keep that stage
persistently; downgrading removes apps. Initial RBAC propagation can delay access.

The bootstrap retains the existing Metabase database/role for compatibility with the
shared database; no Metabase service or administration VM is deployed.

## Verify and operate

Confirm app readiness, bootstrap success, DAG import and a complete `energy_weather`
run. Inspect dbt results, source timestamps, forecasts and API responses. Application
URLs and PostgreSQL are private: use an approved VNet connectivity path with DNS.
This configuration does not provision a VPN or a public jump host.

See [operations](../../docs/operations.md) for CLI usage, retries, reporting and
safe scheduler upgrades. The source does not provision a direct Power BI connection.

## Tests and teardown

Run `terraform fmt -check`, `init -backend=false -lockfile=readonly`, `validate` and
`test` in a clean copy without actual tfvars. GitHub Actions performs the same checks.
Mocks validate configuration logic, not subscription capacity or network access.

Storage and databases have `prevent_destroy`. For a deliberate teardown, back up data,
review retention obligations, adjust protection only for the retired deployment and
inspect its destruction plan. Preserve any backend still used by another deployment.

## Application releases

After initial provisioning, CD owns workload image versions; Terraform ignores that
single image field to prevent reverting releases. See the [CD activation guide](../../docs/continuous-delivery.md)
for the optional OIDC identity, scoped roles and operational prerequisites.
