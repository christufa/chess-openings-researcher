import copy
import json
from pathlib import Path

from openings_research.azure_preflight import assess, requirements

CAPACITY = json.loads((Path(__file__).resolve().parents[1] / 'infra/foundation/capacity.json').read_text())


def fixtures():
    usage = [{"name": {"value": CAPACITY["family"].lower()}, "currentValue": "0", "limit": "128"},
             {"name": {"value": "cores"}, "currentValue": 14, "limit": 160}]
    skus = [{"name": pool["vm_size"], "family": CAPACITY["family"], "restrictions": [],
             "locationInfo": [{"location": "eastus2", "zones": ["1", "2", "3"]}],
             "capabilities": [{"name": "vCPUs", "value": str(pool["vcpus"])}]}
            for pool in CAPACITY["pools"].values()]
    return usage, list({sku["name"]: sku for sku in skus}.values())


def test_capacity_accounts_for_per_pool_surge_rounding():
    assert requirements(CAPACITY) == {"startup": 20, "maximum": 20, "maximum_with_surge": 28}
    usage, skus = fixtures()
    assert assess(CAPACITY, usage, skus, "eastus2")["full_capacity_ready"]


def test_family_approval_does_not_bypass_regional_quota():
    usage, skus = fixtures()
    usage[1]["limit"] = 32
    report = assess(CAPACITY, usage, skus, "eastus2")
    assert not report["startup_capacity_ready"]
    assert report["quotas"]["cores"]["startup_target_limit"] == 34


def test_startup_quota_is_not_enough_for_autoscaling_and_upgrades():
    usage, skus = fixtures()
    usage[0]["limit"] = 20
    report = assess(CAPACITY, usage, skus, "eastus2")
    assert report["startup_capacity_ready"]
    assert not report["full_capacity_ready"]


def test_zone_restriction_blocks_even_with_sufficient_quota():
    usage, skus = fixtures()
    skus[0]["restrictions"] = [{"type": "Zone", "reasonCode": "NotAvailableForSubscription",
                                "restrictionInfo": {"locations": ["eastus2"], "zones": ["2"]}}]
    report = assess(CAPACITY, usage, skus, "eastus2")
    assert not report["startup_capacity_ready"]
    assert "NotAvailableForSubscription" in report["sku_issues"][0]


def test_missing_data_and_wrong_cpu_counts_fail_closed():
    usage, skus = fixtures()
    assert not assess(CAPACITY, [], skus, "eastus2")["full_capacity_ready"]
    assert not assess(CAPACITY, usage, [], "eastus2")["full_capacity_ready"]
    altered = copy.deepcopy(skus)
    altered[0]["capabilities"][0]["value"] = "2"
    assert not assess(CAPACITY, usage, altered, "eastus2")["startup_capacity_ready"]


def test_reduced_cluster_fits_approved_quota_with_concurrent_surge():
    usage, skus = fixtures()
    usage[0]["limit"] = 28
    usage[1]["limit"] = 64
    report = assess(CAPACITY, usage, skus, "eastus2")
    assert report["full_capacity_ready"]
    assert report["requirements"]["maximum_with_surge"] == 28
