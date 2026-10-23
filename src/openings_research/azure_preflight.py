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
    """vCPUs needed per quota: each pool's own quota, plus regional cores for on-demand pools."""
    needed = {}
    for pool in capacity["pools"].values():
        surge = math.ceil(pool["max_count"] * capacity["surge_percent"] / 100)
        names = [pool["quota"]] + ([] if pool["spot"] else ["cores"])
        for name in names:
            row = needed.setdefault(name, {"startup": 0, "maximum": 0, "maximum_with_surge": 0})
            row["startup"] += pool["min_count"] * pool["vcpus"]
            row["maximum"] += pool["max_count"] * pool["vcpus"]
            row["maximum_with_surge"] += (pool["max_count"] + surge) * pool["vcpus"]
    return needed


def assess(capacity, usage, skus, region):
    needed = requirements(capacity)
    issues = []
    quotas = {}
    for name, need in needed.items():
        matches = [row for row in usage if row["name"]["value"].lower() == name.lower()]
        if len(matches) != 1:
            issues.append(f"Missing or ambiguous quota: {name}")
            continue
        row = matches[0]
        used, limit = int(row["currentValue"]), int(row["limit"])
        quotas[name] = {"used": used, "limit": limit, "available": max(0, limit - used),
                        "startup_target_limit": used + need["startup"],
                        "full_target_limit": used + need["maximum_with_surge"]}
    for pool in capacity["pools"].values():
        name = pool["vm_size"]
        matches = [sku for sku in skus if sku["name"] == name]
        if len(matches) != 1:
            issues.append(f"Missing or ambiguous SKU: {name}")
            continue
        sku = matches[0]
        if not any(item["location"].lower() == region.lower() for item in sku.get("locationInfo", [])):
            issues.append(f"{name}: not offered in {region}")
        if not pool["spot"] and sku.get("family", "").lower() != pool["quota"].lower():
            issues.append(f"{name}: unexpected or missing quota family")
        cpus = next((item["value"] for item in sku.get("capabilities", []) if item["name"] == "vCPUs"), None)
        if cpus is None or int(cpus) != pool["vcpus"]:
            issues.append(f"{name}: vCPU count differs from capacity configuration")
        # Pools are regional (no zones), so only whole-region restrictions block them.
        for restriction in sku.get("restrictions", []):
            info = restriction.get("restrictionInfo", {})
            regions = info.get("locations", restriction.get("values", []))
            if restriction.get("type") == "Location" and region.lower() in [value.lower() for value in regions]:
                issues.append(f"{name}: Location restriction: {restriction.get('reasonCode', 'unknown')}")
    complete = not issues and len(quotas) == len(needed)
    startup = complete and all(quotas[n]["available"] >= needed[n]["startup"] for n in needed)
    full = complete and all(quotas[n]["available"] >= needed[n]["maximum_with_surge"] for n in needed)
    return {"region": region, "scope": "additional capacity for first deployment",
            "requirements": needed, "quotas": quotas, "sku_issues": issues,
            "startup_capacity_ready": startup, "full_capacity_ready": full}


def default_capacity():
    """infra/capacity.json of this checkout, wherever the command is run from."""
    checkout = Path(__file__).resolve().parents[2] / "infra" / "capacity.json"
    return checkout if checkout.exists() else Path("infra/capacity.json")


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
    parser.add_argument("--capacity", type=Path, default=default_capacity())
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
