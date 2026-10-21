"""Render platform charts and reject deployment-boundary regressions without a cluster."""

import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(chart, namespace, values=None):
    args = ["helm", "template", "openings-" + chart, str(ROOT / "deploy" / chart), "--namespace", namespace]
    for name, value in (values or {}).items():
        args += ["--set-string", f"{name}={value}"]
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def main():
    cache = ROOT / ".databricks/platform-helm"
    cache.mkdir(parents=True, exist_ok=True)
    repo_args = ["--repository-config", str(cache / "repositories.yaml"), "--repository-cache", str(cache)]
    subprocess.run(["helm", "repo", "add", "lakekeeper", "https://lakekeeper.github.io/lakekeeper-charts",
                    *repo_args], check=True)
    subprocess.run(["helm", "dependency", "build", str(ROOT / "deploy/catalog"), *repo_args], check=True)
    secrets = {"secrets.clientId": "fixture", "secrets.tenantId": "fixture",
               "secrets.vaultUrl": "https://fixture.vault.azure.net"}
    catalog = render("catalog", "openings-catalog", {
        **secrets, "catalogClientId": "fixture", "backup.clientId": "fixture",
        "backup.destination": "https://fixture.blob.core.windows.net/catalog-backups"})
    query = render("query", "openings-query", {
        **secrets, "aksIssuer": "https://issuer.invalid/",
        "bridgeImage": "fixture.azurecr.io/openings-api@sha256:" + "a" * 64})
    platform = render("platform-base", "argocd", {"registry": "fixture.azurecr.io"})
    namespaces = render("namespaces", "default")
    projects = render("gitops", "argocd")
    for ns in namespaces:
        assert ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
    for obj in catalog + query:
        if obj["kind"] == "Service":
            assert obj["spec"].get("type", "ClusterIP") == "ClusterIP", obj["metadata"]["name"]
        if obj["kind"] == "Deployment":
            pod = obj["spec"]["template"]["spec"]
            assert pod["securityContext"]["runAsNonRoot"] is True
            for container in pod["containers"] + pod.get("initContainers", []):
                security = container["securityContext"]
                assert security["allowPrivilegeEscalation"] is False
                assert "ALL" in security["capabilities"]["drop"]
    databases = [obj for obj in catalog if obj["kind"] == "Cluster"]
    assert len(databases) == 2
    for db in databases:
        assert db["spec"]["instances"] == 3
        assert db["spec"]["plugins"][0]["isWALArchiver"] is True
    config = next(obj["data"] for obj in query if obj["kind"] == "ConfigMap")
    rules = json.loads(config["rules.json"])
    assert rules["tables"][0]["privileges"] == ["SELECT"]
    assert rules["catalogs"][-1]["allow"] == "none"
    assert rules["impersonation"][-1]["allow"] is False
    policy = next(obj for obj in platform if obj["kind"] == "ImageValidatingPolicy")
    assert policy["spec"]["failurePolicy"] == "Fail"
    assert policy["spec"]["validationActions"] == ["Deny"]
    assert "ephemeralContainers" in policy["spec"]["images"][0]["expression"]
    for project in (obj for obj in projects if obj["kind"] == "AppProject"):
        assert project["spec"]["clusterResourceWhitelist"] == []
    render("chart", "openings-research", {"apiImage": "fixture/api:test", "workerImage": "fixture/worker:test",
                                          "catalogUri": "https://catalog.invalid/catalog", "trinoHost": "trino.invalid"})
    print("Platform rendering, private services, pod restrictions, backups and access boundaries passed")


if __name__ == "__main__":
    main()
