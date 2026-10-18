# Continuous delivery

The `CD` GitHub Actions workflow implements **manually approved continuous delivery**,
not unattended deployment on every push. It deploys an existing Azure environment;
it does not provision infrastructure or migrate databases.

## Release flow

1. Push a change to `main` and wait for `CI` to pass for that exact commit.
2. Pause `energy_weather` through the Airflow entrypoint wrapper and verify that no
   running/queued DAG runs or task instances remain. Resolve any outstanding retries
   before proceeding. The workflow requires operator confirmation; it does not
   independently inspect the private Airflow database.
3. Confirm the release is compatible with the existing database schema. Releases
   requiring migrations need a separately reviewed maintenance procedure.
4. Dispatch `CD` on `main` with both confirmations selected.
5. GitHub authenticates through Azure OIDC, builds and publishes two uniquely tagged
   images, and resolves their digests. Container Apps receives digest-pinned references.
6. The workflow updates API, webserver, scheduler, monitor and bootstrap templates.
   It waits for each application's requested revision to be running and healthy.
   Bootstrap is **not executed**. Active/unknown job executions block preflight.
7. Verify DAG import, private API readiness and source freshness, then manually resume
   Airflow. The pipeline never resumes the DAG automatically, even on success.

The job uses the Azure control plane, so no public application ingress or administration
VM is required. Hosted runners cannot perform private HTTP/SQL smoke tests without
network connectivity. Azure health probes complement, but do not replace, the final
operator checks. A monitor schedule can overlap rollout; schema compatibility is required.

## One-time activation

The repository contains the workflow and Terraform declarations. **They are not an
already-configured GitHub–Azure connection.** Complete these steps before dispatch:

1. Synchronize the reviewed Terraform source into the existing Swiss deployment
   directory, retaining its backend, real variables, names and current stage.
   Follow the source-transition instructions in `operations.md`; do not initialize
   a new state. Include `github_cd.tf` and the image lifecycle rules from `apps.tf`.
2. Set `github_repository = "Yassine-Ben-Terras/Azure-Weather-Energy-Analytics-Platform"`
   in that deployment's private tfvars. Review and apply the Terraform plan. Expected
   additions are the CD identity, its federation and resource-scoped RBAC assignments;
   no application replacement or data destruction should be accepted.
3. In GitHub Settings → Environments, create **`azure-production`**. Restrict deployment
   branches to `main`. Add required reviewers if supported by the repository plan.
4. Add these **environment variables** (not long-lived Azure client secrets):

| Variable | Value/source |
| --- | --- |
| `AZURE_CLIENT_ID` | `terraform output -raw github_cd_client_id` |
| `AZURE_TENANT_ID` | Tenant of the deployment subscription |
| `AZURE_SUBSCRIPTION_ID` | Deployment subscription ID |
| `AZURE_RESOURCE_GROUP` | `terraform output -raw resource_group_name` |
| `ACR_NAME` | `terraform output -raw acr_name` |
| `APP_PREFIX` | Existing workload prefix, currently `ewplatch-dev-aca` |

The federated subject is bound to the exact repository and `azure-production`
environment. GitHub must issue an OIDC token (`id-token: write`). The identity receives
Reader on the resource group, AcrPush on this registry, and Contributor separately on
the three apps and two jobs. It receives no subscription-wide Contributor, RBAC write,
Key Vault secret-reader or PostgreSQL permission. Workload Contributor can still change
application configuration and deploy code using its managed identity; protect workflow
changes and the GitHub environment accordingly.

References: [Azure OIDC authentication](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect)
and [GitHub OIDC environment protections](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure).

## Terraform ownership

Terraform creates each initial workload using `image_tag`. Afterwards it ignores only
`template[0].container[0].image` on apps and jobs; CD owns that field. Other settings
remain managed by Terraform. Apply this rule in the actual deployment copy before the
first CD release. Setting `image_tag` alone will no longer update existing workloads.
If recreating a workload, explicitly supply a known published image tag.

## Failure and rollback

Concurrency prevents two CD releases from overlapping and never cancels an active
release automatically. A failure stops subsequent updates and leaves the DAG paused.
A release is not atomic: some workloads may already have changed. Download the
`release-<run>-<attempt>` artifact and inspect `release-record.json` for previous and
requested image references. An interrupted update can have taken effect even when its
`updated` flag is false; inspect Azure before recovery.

After verifying database compatibility, restore each affected resource with its
`previous_image` using `az containerapp update --image ...` or
`az containerapp job update --image ...`, then check readiness again. If pre-CD images
were tagged, verify those tags still resolve to the expected image; CD releases use
digests. Never resume Airflow while the release is partially recovered.

The CI suite validates the source commit; CD rebuilds images from that source. This
is not yet promotion of the exact CI-tested image artifact: unpinned transitive build
dependencies can change. Artifact promotion and network-connected smoke tests are
future hardening work.
