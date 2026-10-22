"""Prepare an atomic, reviewable GitOps release. Never contact or mutate a cluster."""

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

REPOSITORY = "https://github.com/christufa/chess-openings-researcher.git"
SHA = re.compile(r"[0-9a-f]{40}")
IMAGE = re.compile(r"([a-z0-9]+\.azurecr\.io)/openings-(api|worker)@sha256:[0-9a-f]{64}")
ALLOWED_VALUES = {
    "catalogUri", "warehouse", "catalog", "fileIO", "catalogTokenAudience", "trinoHost",
    "trinoPort", "trinoCatalog", "trinoUser", "trinoTokenAudience", "caConfigMap", "providerSecret",
}


def application(revision: str, api_image: str, worker_image: str, values: dict) -> dict:
    if not SHA.fullmatch(revision):
        raise ValueError("Release source must be a full Git commit SHA")
    api = IMAGE.fullmatch(api_image)
    worker = IMAGE.fullmatch(worker_image)
    if not api or api[2] != "api" or not worker or worker[2] != "worker" or api[1] != worker[1]:
        raise ValueError("Use API and worker SHA256 digests from the same Azure registry")
    if set(values) - ALLOWED_VALUES:
        raise ValueError("Unknown release values; credentials and Helm overrides are not accepted")
    if not all(isinstance(value, str) for value in values.values()):
        raise ValueError("Release settings must be strings")
    uri = urlsplit(values.get("catalogUri", ""))
    if uri.scheme != "https" or not uri.hostname or uri.username or uri.password or uri.query or uri.fragment:
        raise ValueError("Production catalog must use HTTPS without credentials or query parameters")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", values.get("trinoHost", "")):
        raise ValueError("A Trino hostname is required")
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": "openings-research", "namespace": "argocd"},
        "spec": {
            "project": "openings-research",
            "source": {
                "repoURL": REPOSITORY, "targetRevision": revision, "path": "deploy/chart",
                "helm": {
                    "releaseName": "openings-research",
                    "valuesObject": {
                        **values, "apiImage": api_image, "workerImage": worker_image, "catalogPrivateCA": True,
                    },
                },
            },
            "destination": {"server": "https://kubernetes.default.svc", "namespace": "openings-research"},
            # Explicit activation follows real infrastructure and signature-admission checks.
            "syncPolicy": {"syncOptions": ["FailOnSharedResource=true"]},
        },
    }


PLATFORM_FIELDS = {
    "catalogClientId", "backupClientId", "secretsClientId", "tenantId",
    "storageAccount", "vaultName", "aksIssuer",
}


def data_applications(revision: str, api_image: str, values: dict) -> dict:
    """Accept only nonsecret deployment identifiers, never arbitrary Helm overrides."""
    if not SHA.fullmatch(revision):
        raise ValueError("Release source must be a full Git commit SHA")
    image = IMAGE.fullmatch(api_image)
    if not image or image[2] != "api":
        raise ValueError("The query bridge requires an API image digest in ACR")
    if set(values) != PLATFORM_FIELDS or not all(isinstance(v, str) for v in values.values()):
        raise ValueError("Platform settings require exactly the documented nonsecret identifiers")
    for key in ("catalogClientId", "backupClientId", "secretsClientId", "tenantId"):
        if str(UUID(values[key])) != values[key]:
            raise ValueError("Identity IDs must be canonical UUIDs")
    if not re.fullmatch(r"[a-z0-9]{3,24}", values["storageAccount"]):
        raise ValueError("Invalid storage account name")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]", values["vaultName"]):
        raise ValueError("Invalid vault name")
    issuer = urlsplit(values["aksIssuer"])
    if (issuer.scheme != "https" or not issuer.hostname or issuer.username or issuer.password
            or issuer.query or issuer.fragment or issuer.port or not issuer.path.endswith("/")
            or not issuer.hostname.endswith(".oic.prod-aks.azure.com")):
        raise ValueError("Use the Azure AKS OIDC issuer URL with its trailing slash")
    secrets = {"clientId": values["secretsClientId"], "tenantId": values["tenantId"],
               "vaultUrl": "https://" + values["vaultName"] + ".vault.azure.net"}
    settings = {
        "catalog": {"catalogClientId": values["catalogClientId"], "secrets": secrets,
                    "backup": {"clientId": values["backupClientId"],
                               "destination": "https://" + values["storageAccount"]
                               + ".blob.core.windows.net/catalog-backups"}},
        "query": {"secrets": secrets, "aksIssuer": values["aksIssuer"], "bridgeImage": api_image},
    }
    return {name: {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": "openings-" + name, "namespace": "argocd"},
        "spec": {
            "project": "openings-data",
            "source": {"repoURL": REPOSITORY, "targetRevision": revision, "path": "deploy/" + name,
                       "helm": {"releaseName": "openings-" + name, "valuesObject": settings[name]}},
            "destination": {"server": "https://kubernetes.default.svc", "namespace": "openings-" + name},
            "syncPolicy": {"syncOptions": ["FailOnSharedResource=true"]},
        },
    } for name in settings}


def write_release(destination: Path, manifests: dict):
    """Maintain a complete release set; never silently orphan previously promoted services."""
    destination.mkdir(parents=True, exist_ok=True)
    if set(manifests) != {"research", "catalog", "query"}:
        if any((destination / (name + ".json")).exists() for name in ("catalog", "query")):
            raise ValueError("An existing data platform requires --platform-values for coordinated promotion")
    existing = destination / "kustomization.yaml"
    if existing.exists():
        lines = [line.strip() for line in existing.read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        expected_header = ["apiVersion: kustomize.config.k8s.io/v1beta1", "kind: Kustomization"]
        if (lines[:2] != expected_header or len(lines) < 3
                or lines[2] not in ("resources:", "resources: []")
                or any(line not in {"- research.json", "- catalog.json", "- query.json"} for line in lines[3:])):
            raise ValueError("Custom production Kustomization requires manual review; refusing to overwrite")
        if any(line.removeprefix("- ").removesuffix(".json") not in manifests for line in lines[3:]):
            raise ValueError("Release would remove an existing application")
    for name, manifest in manifests.items():
        (destination / (name + ".json")).write_text(json.dumps(manifest, indent=2) + "\n")
    resources = "".join("  - " + name + ".json\n" for name in sorted(manifests))
    (destination / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n" + resources
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--values", type=Path, required=True, help="Nonsecret JSON runtime settings")
    parser.add_argument("--platform-values", type=Path, help="Nonsecret JSON platform identifiers")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    manifest = application(
        args.revision, args.api_image, args.worker_image, json.loads(args.values.read_text())
    )
    manifests = {"research": manifest}
    if args.platform_values:
        runtime = manifest["spec"]["source"]["helm"]["valuesObject"]
        required_runtime = {
            "catalogUri": "https://catalog-tls.openings-catalog.svc.cluster.local:8443/catalog",
            "trinoHost": "trino.openings-query.svc.cluster.local",
            "warehouse": "openings-research", "catalog": "research", "trinoCatalog": "research",
            "trinoPort": "8443", "trinoUser": "openings-api", "caConfigMap": "internal-ca",
            "catalogTokenAudience": "lakekeeper", "trinoTokenAudience": "trino",
        }
        if any(runtime.get(key, value) != value for key, value in required_runtime.items()):
            raise ValueError("Runtime settings must match the coordinated private platform")
        manifests.update(data_applications(
            args.revision, args.api_image, json.loads(args.platform_values.read_text())
        ))
        runtime["secrets"] = {
            **manifests["catalog"]["spec"]["source"]["helm"]["valuesObject"]["secrets"], "enabled": True,
        }
    # Fetch first so an outdated local main cannot be mistaken for approval.
    remote = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=args.repository, text=True
    ).strip()
    if remote not in (REPOSITORY, REPOSITORY.removesuffix(".git"),
                      "git@github.com:christufa/chess-openings-researcher.git"):
        raise ValueError("Expected the chess-openings-researcher origin")
    subprocess.run(["git", "fetch", "origin", "main"], cwd=args.repository, check=True)
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", args.revision, "origin/main"],
        cwd=args.repository, check=True,
    )
    destination = args.repository / "deploy/environments/production"
    write_release(destination, manifests)
    print("Prepared production release files. Review and promote through a PR to main.")


if __name__ == "__main__":
    main()
