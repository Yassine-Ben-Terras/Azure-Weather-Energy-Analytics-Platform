# Contributing

Keep changes focused and include the relevant validation in the pull request.
Application images are built from the repository root. Follow the validation commands
in README.md; Docker Compose is restricted to isolated CI fixtures.

For infrastructure changes, run formatting, validation and mocked Terraform tests
from a clean directory prepared by `scripts/prepare_azure_deployment.ps1`:

```bash
terraform fmt -check
terraform init -backend=false -lockfile=readonly
terraform validate
terraform test
```

Do not run tests from an existing cloud deployment directory: it contains real
parameters and state configuration. Never run `apply` as a code validation step.

Do not commit `.env`, actual tfvars, backend configuration, Terraform plans/state,
private keys, exported customer data or generated dbt output. Keep examples generic.
Update architecture and operations documentation when behavior changes.
