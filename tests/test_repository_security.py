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
