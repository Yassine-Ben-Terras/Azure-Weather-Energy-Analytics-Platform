# Security

Do not publish credentials, Terraform states or plans, private keys, exported datasets,
or logs containing secrets. Terraform sensitive values are still stored in state;
restrict backend access and retain recovery protection.

Use Key Vault and managed identities for cloud workloads. Application ingress and
PostgreSQL are private by design. Do not expose databases or disable TLS to troubleshoot.

For a suspected vulnerability, contact the repository owner privately through their
GitHub profile. Do not include working secrets or exploit details in a public issue.
If a credential is exposed, revoke/rotate it first; removing a file does not remove it
from Git history.

This portfolio deployment has not been certified for production use. Dependency
upgrades, access reviews, restore tests and forecasting validation remain necessary.
