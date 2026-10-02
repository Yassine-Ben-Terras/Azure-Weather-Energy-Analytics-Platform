# Infrastructure

[`azure/`](azure/README.md) is the only supported deployment implementation:
Azure Container Apps, PostgreSQL Flexible Server, Blob Storage, ACR, Key Vault
and Azure Monitor. Default application region: Switzerland North.

Runtime code and test fixtures live outside this directory. Actual deployment values,
state and plans are private operational files and must not be committed.
