"""Render platform charts and reject deployment-boundary regressions without a cluster."""

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
    cache = ROOT / ".cache/platform-helm"
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
    platform = render("platform-base", "argocd", {"registry": "fixture.azurecr.io"})
    for obj in catalog:
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
    assert len(databases) == 1
    assert databases[0]["spec"]["plugins"][0]["isWALArchiver"] is True
    assert any(obj["kind"] == "ScheduledBackup" for obj in catalog)
    policy = next(obj for obj in platform if obj["kind"] == "ValidatingAdmissionPolicyBinding")
    assert policy["spec"]["validationActions"] == ["Deny"]
    render("chart", "openings-research", {"apiImage": "fixture/api:test", "workerImage": "fixture/worker:test",
                                          "catalogUri": "https://catalog.invalid/catalog", "trinoHost": "trino.invalid"})
    research = render("chart", "openings-research", {
        **secrets, "secrets.enabled": "true", "apiImage": "fixture/api:test", "workerImage": "fixture/worker:test",
        "catalogUri": "https://catalog.invalid/catalog", "trinoHost": "trino.invalid"})
    providers = next(obj for obj in research if obj["kind"] == "ExternalSecret")
    assert {item["secretKey"] for item in providers["spec"]["data"]} == {"OPENAI_API_KEY", "TAVILY_API_KEY"}
    api = next(obj for obj in research if obj["kind"] == "Deployment")
    for container in api["spec"]["template"]["spec"]["containers"]:
        assert not any("secretRef" in ref for ref in container.get("envFrom", []))
    print("Platform rendering, private services, pod restrictions and catalog backups passed")


if __name__ == "__main__":
    main()
