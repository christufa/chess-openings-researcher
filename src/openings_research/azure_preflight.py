"""Read-only Azure capacity preflight for this project's first deployment."""

import argparse
import json
import math
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID


def requirements(capacity):
    pools = capacity["pools"].values()
    return {
        "startup": sum(pool["min_count"] * pool["vcpus"] for pool in pools),
        "maximum": sum(pool["max_count"] * pool["vcpus"] for pool in pools),
        "maximum_with_surge": sum(
            (pool["max_count"] + math.ceil(pool["max_count"] * capacity["surge_percent"] / 100))
            * pool["vcpus"] for pool in pools
        ),
    }


def assess(capacity, usage, skus, region):
    needed = requirements(capacity)
    issues = []
    quotas = {}
    for name in (capacity["family"], "cores"):
        matches = [row for row in usage if row["name"]["value"].lower() == name.lower()]
        if len(matches) != 1:
            issues.append(f"Missing or ambiguous quota: {name}")
            continue
        row = matches[0]
        used, limit = int(row["currentValue"]), int(row["limit"])
        quotas[name] = {"used": used, "limit": limit, "available": max(0, limit - used),
                        "startup_target_limit": used + needed["startup"],
                        "full_target_limit": used + needed["maximum_with_surge"]}
    for pool in capacity["pools"].values():
        name = pool["vm_size"]
        matches = [sku for sku in skus if sku["name"] == name]
        if len(matches) != 1:
            issues.append(f"Missing or ambiguous SKU: {name}")
            continue
        sku = matches[0]
        locations = [item for item in sku.get("locationInfo", []) if item["location"].lower() == region.lower()]
        zones = set().union(*(set(item.get("zones", [])) for item in locations))
        missing = set(capacity["zones"]) - zones
        if missing:
            issues.append(f"{name}: zones not advertised: {', '.join(sorted(missing))}")
        if sku.get("family", "").lower() != capacity["family"].lower():
            issues.append(f"{name}: unexpected or missing quota family")
        cpus = next((item["value"] for item in sku.get("capabilities", []) if item["name"] == "vCPUs"), None)
        if cpus is None or int(cpus) != pool["vcpus"]:
            issues.append(f"{name}: vCPU count differs from capacity configuration")
        for restriction in sku.get("restrictions", []):
            info = restriction.get("restrictionInfo", {})
            regions = info.get("locations", restriction.get("values", []))
            if regions and region.lower() not in [value.lower() for value in regions]:
                continue
            kind = restriction.get("type")
            restricted_zones = set(info.get("zones", []))
            if kind != "Zone" or not restricted_zones or restricted_zones.intersection(capacity["zones"]):
                issues.append(f"{name}: {kind} restriction: {restriction.get('reasonCode', 'unknown')}")
    startup = not issues and len(quotas) == 2 and all(q["available"] >= needed["startup"] for q in quotas.values())
    full = not issues and len(quotas) == 2 and all(q["available"] >= needed["maximum_with_surge"] for q in quotas.values())
    return {"region": region, "scope": "additional capacity for first deployment",
            "requirements": needed, "quotas": quotas, "sku_issues": issues,
            "startup_capacity_ready": startup, "full_capacity_ready": full}


def azure(*args):
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is not installed or is not on PATH")
    result = subprocess.run([executable, *args, "--only-show-errors", "-o", "json"],
                            capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError("Azure capacity lookup failed; check CLI login and subscription access")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--region", default="eastus2")
    parser.add_argument("--capacity", type=Path, default=Path("infra/foundation/capacity.json"))
    args = parser.parse_args()
    args.subscription = str(UUID(args.subscription))
    if not re.fullmatch(r"[a-z0-9]+", args.region):
        parser.error("Use an Azure region name such as eastus2")
    capacity = json.loads(args.capacity.read_text())
    common = ["--location", args.region, "--subscription", args.subscription]
    with ThreadPoolExecutor(max_workers=2) as executor:
        usage = executor.submit(azure, "vm", "list-usage", *common)
        skus = executor.submit(azure, "vm", "list-skus", *common,
                               "--resource-type", "virtualMachines", "--size", "Standard_D", "--all")
        report = assess(capacity, usage.result(), skus.result(), args.region)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["full_capacity_ready"] else 2)


if __name__ == "__main__":
    main()
