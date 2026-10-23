"""Render platform charts and GitOps manifests and reject boundary regressions without a cluster."""

import re
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


def load(directory):
    return [item for path in sorted((ROOT / directory).glob("*.yaml"))
            for item in yaml.safe_load_all(path.read_text()) if item]


def check_pods(objects):
    for obj in objects:
        if obj["kind"] == "Service":
            assert obj["spec"].get("type", "ClusterIP") == "ClusterIP", obj["metadata"]["name"]
        if obj["kind"] == "Deployment":
            pod = obj["spec"]["template"]["spec"]
            assert pod["securityContext"]["runAsNonRoot"] is True
            for container in pod["containers"] + pod.get("initContainers", []):
                security = container["securityContext"]
                assert security["allowPrivilegeEscalation"] is False
                assert "ALL" in security["capabilities"]["drop"]


def check_gitops(platform):
    apps = load("deploy/apps")
    projects = {obj["metadata"]["name"]: obj for obj in apps if obj["kind"] == "AppProject"}
    for obj in apps:
        if obj["kind"] == "AppProject":
            continue
        spec = obj["spec"]["template"]["spec"] if obj["kind"] == "ApplicationSet" else obj["spec"]
        project = projects[spec["project"]]
        source = spec["source"]
        assert source["repoURL"] in project["spec"]["sourceRepos"], obj["metadata"]["name"]
        if "chart" in source:  # upstream charts pinned to an exact version
            assert re.fullmatch(r"v?\d+\.\d+\.\d+", source["targetRevision"]), obj["metadata"]["name"]
        else:
            assert source["targetRevision"] == "main", obj["metadata"]["name"]
        namespace = spec["destination"]["namespace"]
        allowed = {d["namespace"] for d in project["spec"]["destinations"]}
        assert namespace in allowed, (obj["metadata"]["name"], namespace)
    assert projects["platform-security"]["spec"]["clusterResourceWhitelist"] == []
    rendered = yaml.safe_dump(apps)
    for forbidden in ("ingress", "LoadBalancer", "cloudflared"):
        assert forbidden not in rendered, f"nothing may be published: found {forbidden}"

    # The admission policy and the Argo Workflows chart must pin the same executor digest.
    workflows = next(obj for obj in apps if obj["metadata"]["name"] == "argo-workflows")
    executor = workflows["spec"]["source"]["helm"]["valuesObject"]["executor"]["image"]["tag"]
    policy = next(obj for obj in platform if obj["kind"] == "ValidatingAdmissionPolicy")
    assert f"quay.io/argoproj/argoexec:{executor}" in yaml.safe_dump(policy), "executor digest drift"

    secured = {d["namespace"] for d in projects["platform-security"]["spec"]["destinations"]}
    policies = load("deploy/network-policies")
    covered = {obj["metadata"]["namespace"] for obj in policies}
    assert covered <= secured
    assert secured - covered == {"openings-catalog"}  # its policies ship with the catalog chart
    egress = next(obj for obj in policies if obj["metadata"]["name"] == "limited-egress")
    world = [rule for rule in egress["spec"]["egress"] if "world" in rule.get("toEntities", [])]
    assert [p["port"] for rule in world for ports in rule["toPorts"] for p in ports["ports"]] == ["443"]


def main():
    secrets = {"secrets.clientId": "fixture", "secrets.tenantId": "fixture",
               "secrets.vaultUrl": "https://fixture.vault.azure.net"}
    catalog = render("catalog", "openings-catalog", {
        **secrets, "catalogClientId": "fixture", "backup.clientId": "fixture",
        "backup.destination": "https://fixture.blob.core.windows.net/catalog-backups"})
    platform = render("platform-base", "openings-research", {"registry": "fixture.azurecr.io"})
    check_pods(catalog)
    databases = [obj for obj in catalog if obj["kind"] == "Cluster"]
    assert len(databases) == 1
    assert databases[0]["spec"]["plugins"][0]["isWALArchiver"] is True
    assert any(obj["kind"] == "ScheduledBackup" for obj in catalog)
    policy = next(obj for obj in platform if obj["kind"] == "ValidatingAdmissionPolicyBinding")
    assert policy["spec"]["validationActions"] == ["Deny"]

    images = {"apiImage": "fixture.azurecr.io/openings-api@sha256:" + "a" * 64,
              "workerImage": "fixture.azurecr.io/openings-worker@sha256:" + "b" * 64,
              "catalogUri": "http://lakekeeper.openings-catalog.svc.cluster.local:8181/catalog"}
    minimal = render("chart", "openings-research", images)
    assert not any(obj["metadata"]["name"] == "catalog-bootstrap" for obj in minimal)
    research = render("chart", "openings-research", {
        **secrets, **images, "secrets.enabled": "true", "storageAccount": "fixture",
        "azureOpenAI.endpoint": "https://oai-fixture.openai.azure.com/",
        "workflowLogs.clientId": "fixture"})
    check_pods(research)
    providers = next(obj for obj in research if obj["kind"] == "ExternalSecret")
    assert {item["secretKey"] for item in providers["spec"]["data"]} == {"TAVILY_API_KEY"}  # model is keyless
    api = next(obj for obj in research if obj["kind"] == "Deployment")
    assert api["spec"]["template"]["metadata"]["labels"]["openings.generops.dev/role"] == "api"
    for container in api["spec"]["template"]["spec"]["containers"]:
        assert not any("secretRef" in ref for ref in container.get("envFrom", []))
    tokens = [v["projected"]["sources"][0]["serviceAccountToken"] for v in api["spec"]["template"]["spec"]["volumes"]
              if "projected" in v]
    assert [t["audience"] for t in tokens] == ["lakekeeper"]  # catalog only; no other credential
    config = next(obj for obj in research if obj["metadata"]["name"] == "openings-config")
    assert config["data"]["OPENINGS_AZURE_OPENAI_ENDPOINT"] == "https://oai-fixture.openai.azure.com/"
    names = {obj["metadata"]["name"] for obj in research}
    assert {"openings-batch", "catalog-bootstrap", "artifact-repositories"} <= names
    worker = next(obj for obj in research if obj["kind"] == "ServiceAccount" and obj["metadata"]["name"] == "openings-worker")
    assert worker["metadata"]["annotations"]["azure.workload.identity/client-id"] == "fixture"

    check_gitops(platform)
    print("Charts, GitOps apps, admission, network policies and catalog backups passed")


if __name__ == "__main__":
    main()
