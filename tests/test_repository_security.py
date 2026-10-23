"""Guard public-contribution and production boundaries in reviewed configuration."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_main_requires_real_ci_without_bypass():
    policy = json.loads((ROOT / ".github/policies/main-ruleset.json").read_text(encoding="utf-8-sig"))
    assert policy["enforcement"] == "active"
    assert policy["bypass_actors"] == []
    assert policy["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    rules = {rule["type"]: rule.get("parameters", {}) for rule in policy["rules"]}
    assert {"deletion", "non_fast_forward", "pull_request"} <= rules.keys()
    assert rules["pull_request"]["required_review_thread_resolution"]
    checks = rules["required_status_checks"]
    assert checks["strict_required_status_checks_policy"]
    assert {(check["context"], check["integration_id"]) for check in checks["required_status_checks"]} == {
        ("Tests and wheel", 15368), ("containers", 15368),
        ("CodeQL (python)", 15368), ("CodeQL (javascript-typescript)", 15368), ("Dependency review", 15368)
    }

    assert rules["code_scanning"]["code_scanning_tools"] == [{
        "tool": "CodeQL", "alerts_threshold": "errors", "security_alerts_threshold": "high_or_higher"
    }]


def test_public_workflows_are_pinned_and_do_not_execute_privileged_prs():
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        # PyYAML's YAML 1.1 loader treats the workflow key 'on' as True.
        events = workflow.get("on", workflow.get(True, {}))
        assert "pull_request_target" not in events
        assert workflow["permissions"] == {"contents": "read"}
        for job in workflow["jobs"].values():
            if "pull_request" in events and "environment" not in job:
                assert job["runs-on"] == "ubuntu-latest"
                assert "secrets." not in json.dumps(job)
            for step in job.get("steps", []):
                if "uses" in step:
                    assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"])


def test_images_publish_only_from_main_after_scan_then_sign():
    workflow = yaml.safe_load((ROOT / ".github/workflows/images.yml").read_text())
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"push", "workflow_dispatch"}
    assert events["push"] == {"branches": ["main"]}
    image, release = workflow["jobs"]["image"], workflow["jobs"]["release"]
    assert image["if"] == "github.ref == 'refs/heads/main'"
    assert "refs/heads/main" in release["if"]
    assert image["permissions"] == {"contents": "read", "id-token": "write"}
    assert release["permissions"] == {"contents": "write"}  # only the deploy-state commit writes
    assert all("uses" in step and "checkout" in step["uses"] or "run" in step for step in release["steps"])
    names = [step.get("name", step.get("uses", "")) for step in image["steps"]]
    order = [names.index(n) for n in (
        "Smoke test", "Fail on fixable critical vulnerabilities", "Push with SBOM and provenance",
        "Sign and verify (cosign keyless, identity = this workflow on main)")]
    assert order == sorted(order)
    push = next(step for step in image["steps"] if step.get("name") == "Push with SBOM and provenance")
    assert push["with"]["sbom"] is True and push["with"]["provenance"] == "mode=max"


def test_pull_requests_scan_both_images():
    workflow = yaml.safe_load((ROOT / ".github/workflows/containers.yml").read_text())
    steps = [step.get("with", {}).get("image-ref") for step in workflow["jobs"]["containers"]["steps"]]
    assert {"openings-worker:test", "openings-api:test"} <= set(steps)


def test_base_images_and_downloads_are_pinned():
    for path in (ROOT / "docker").glob("Dockerfile.*"):
        text = path.read_text()
        for ref in re.findall(r"^(?:FROM|ARG SPARK_IMAGE=)\s*(\S+)", text, re.MULTILINE):
            if ref.startswith("${"):
                continue
            assert re.search(r"@sha256:[0-9a-f]{64}$", ref), f"{path.name}: {ref} is not digest-pinned"
        for add in re.findall(r"^ADD .*$", text, re.MULTILINE):
            assert re.match(r"ADD --checksum=sha256:[0-9a-f]{64} ", add), f"{path.name}: unchecked download"
