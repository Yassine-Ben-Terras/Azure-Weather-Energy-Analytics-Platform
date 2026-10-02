"""Read-only Azure subscription and region preflight; never creates resources."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import subprocess
import sys


def az_json(*args):
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Install Azure CLI and run az login first.")
    result = subprocess.run([executable, *args, "--output", "json"], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", default="switzerlandnorth")
    args = parser.parse_args()
    account = az_json("account", "show")
    services = ["Microsoft.App", "Microsoft.DBforPostgreSQL", "Microsoft.Storage", "Microsoft.ContainerRegistry", "Microsoft.KeyVault", "Microsoft.OperationalInsights", "Microsoft.Insights", "Microsoft.Network", "Microsoft.ManagedIdentity"]
    def provider(namespace):
        value = az_json("provider", "show", "--namespace", namespace)
        types = {item["resourceType"]: item for item in value.get("resourceTypes", [])}
        return namespace, value.get("registrationState"), types
    with ThreadPoolExecutor(max_workers=4) as pool:
        providers = list(pool.map(provider, services))
    print("Subscription:", account["name"])
    print("Region:", args.location)
    policies = az_json("policy", "assignment", "list")
    region_lists = [policy.get("parameters", {}).get("listOfAllowedLocations", {}).get("value") for policy in policies]
    for allowed in filter(None, region_lists):
        print("Policy allowed regions:", ", ".join(allowed))
        if args.location not in allowed:
            raise RuntimeError("This subscription policy excludes the requested region.")
    for namespace, state, _ in providers:
        print(f"{namespace}: {state}")
    missing = [namespace for namespace, state, _ in providers if state != "Registered"]
    if missing:
        print("Register before deployment:", ", ".join(missing))
    app_types = next(types for namespace, _, types in providers if namespace == "Microsoft.App")
    regions = app_types.get("managedEnvironments", {}).get("locations", [])
    available = args.location.lower() in {region.lower().replace(" ", "") for region in regions}
    print("Container Apps region listed:", available)
    capabilities = az_json("postgres", "flexible-server", "list-skus", "--location", args.location)
    matches = [item for item in walk(capabilities) if item.get("name") in ("Standard_B2s", "B_Standard_B2s")]
    print("PostgreSQL B2s catalog entries:", json.dumps(matches, ensure_ascii=False))
    print("Catalog availability is not a reservation of capacity or a quota/deployment validation.")
    if not available or not matches:
        raise RuntimeError("Required regional service or PostgreSQL SKU not found; inspect Azure availability before planning.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
