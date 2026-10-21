"""Prepare an atomic, reviewable GitOps release. Never contact or mutate a cluster."""

import argparse
import json
import re
import subprocess
from pathlib import Path

REPOSITORY = "https://github.com/christufa/openings-researcher.git"
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
    from urllib.parse import urlsplit

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
                    "valuesObject": {**values, "apiImage": api_image, "workerImage": worker_image},
                },
            },
            "destination": {"server": "https://kubernetes.default.svc", "namespace": "openings-research"},
            # Explicit activation follows real infrastructure and signature-admission checks.
            "syncPolicy": {"syncOptions": ["FailOnSharedResource=true"]},
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--values", type=Path, required=True, help="Nonsecret JSON runtime settings")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    manifest = application(
        args.revision, args.api_image, args.worker_image, json.loads(args.values.read_text())
    )
    # Fetch first so an outdated local main cannot be mistaken for approval.
    remote = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=args.repository, text=True
    ).strip()
    if remote not in (REPOSITORY, REPOSITORY.removesuffix(".git"),
                      "git@github.com:christufa/openings-researcher.git"):
        raise ValueError("Expected the openings-researcher origin")
    subprocess.run(["git", "fetch", "origin", "main"], cwd=args.repository, check=True)
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", args.revision, "origin/main"],
        cwd=args.repository, check=True,
    )
    destination = args.repository / "deploy/environments/production"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "research.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (destination / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - research.json\n"
    )
    print("Prepared production release files. Review and promote through a PR to main.")


if __name__ == "__main__":
    main()
