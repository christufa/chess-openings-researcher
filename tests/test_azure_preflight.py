import copy
import json
from pathlib import Path

from openings_research.azure_preflight import assess, default_capacity, requirements

CAPACITY = json.loads((Path(__file__).resolve().parents[1] / "infra/capacity.json").read_text())


def fixtures():
    usage = [{"name": {"value": "standardDASv5Family"}, "currentValue": "8", "limit": "32"},
             {"name": {"value": "lowPriorityCores"}, "currentValue": 0, "limit": 32},
             {"name": {"value": "cores"}, "currentValue": 14, "limit": 64}]
    skus = [{"name": "Standard_D4as_v5", "family": "standardDASv5Family", "restrictions": [],
             "locationInfo": [{"location": "eastus2", "zones": ["1", "2", "3"]}],
             "capabilities": [{"name": "vCPUs", "value": "4"}]}]
    return usage, skus


def test_requirements_split_on_demand_spot_and_regional_cores():
    assert requirements(CAPACITY) == {
        "standardDASv5Family": {"startup": 4, "maximum": 8, "maximum_with_surge": 12},
        "cores": {"startup": 4, "maximum": 8, "maximum_with_surge": 12},
        "lowPriorityCores": {"startup": 0, "maximum": 4, "maximum_with_surge": 8},
    }
    usage, skus = fixtures()
    assert assess(CAPACITY, usage, skus, "eastus2")["full_capacity_ready"]


def test_spot_quota_shared_with_another_cluster_blocks_full_capacity():
    usage, skus = fixtures()
    usage[1]["currentValue"] = 32  # another cluster's spot pool already at the quota
    report = assess(CAPACITY, usage, skus, "eastus2")
    assert report["startup_capacity_ready"]
    assert not report["full_capacity_ready"]


def test_family_approval_does_not_bypass_regional_quota():
    usage, skus = fixtures()
    usage[2]["limit"] = 16
    report = assess(CAPACITY, usage, skus, "eastus2")
    assert not report["startup_capacity_ready"]
    assert report["quotas"]["cores"]["startup_target_limit"] == 18


def test_two_system_nodes_need_more_than_the_original_family_quota():
    usage, skus = fixtures()
    usage[0].update(currentValue="8", limit="16")  # lichess-delta-kube already uses 8
    assert not assess(CAPACITY, usage, skus, "eastus2")["full_capacity_ready"]
    usage[0]["limit"] = "32"  # after the quota increase
    assert assess(CAPACITY, usage, skus, "eastus2")["full_capacity_ready"]


def test_default_capacity_is_found_from_any_folder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert default_capacity().resolve() == (Path(__file__).resolve().parents[1] / "infra/capacity.json")


def test_location_restriction_blocks_even_with_sufficient_quota():
    usage, skus = fixtures()
    skus[0]["restrictions"] = [{"type": "Location", "reasonCode": "NotAvailableForSubscription",
                                "restrictionInfo": {"locations": ["eastus2"]}}]
    report = assess(CAPACITY, usage, skus, "eastus2")
    assert not report["startup_capacity_ready"]
    assert "NotAvailableForSubscription" in report["sku_issues"][0]


def test_zone_restriction_does_not_block_regional_pools():
    usage, skus = fixtures()
    skus[0]["restrictions"] = [{"type": "Zone", "reasonCode": "NotAvailableForSubscription",
                                "restrictionInfo": {"locations": ["eastus2"], "zones": ["2"]}}]
    assert assess(CAPACITY, usage, skus, "eastus2")["full_capacity_ready"]


def test_missing_data_and_wrong_cpu_counts_fail_closed():
    usage, skus = fixtures()
    assert not assess(CAPACITY, [], skus, "eastus2")["full_capacity_ready"]
    assert not assess(CAPACITY, usage, [], "eastus2")["full_capacity_ready"]
    altered = copy.deepcopy(skus)
    altered[0]["capabilities"][0]["value"] = "2"
    assert not assess(CAPACITY, usage, altered, "eastus2")["startup_capacity_ready"]
