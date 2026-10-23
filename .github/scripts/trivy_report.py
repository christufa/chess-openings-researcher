"""Turn a Trivy JSON report into a job summary table and one annotation per finding.

Exits 1 if there are findings (Trivy has already filtered to fixable criticals and
applied .trivyignore).
"""

import json
import os
import sys

report = json.load(open(sys.argv[1], encoding="utf-8"))
image = sys.argv[2]
rows = []
for result in report.get("Results", []):
    for vuln in result.get("Vulnerabilities") or []:
        rows.append((vuln["VulnerabilityID"], vuln.get("PkgName", ""), vuln.get("InstalledVersion", ""),
                     vuln.get("FixedVersion", ""), result.get("Target", ""), (vuln.get("Title") or "")[:100]))

with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as out:
    out.write(f"### Trivy: {image}\n\n")
    if not rows:
        out.write("No fixable critical vulnerabilities.\n")
    else:
        out.write("| ID | package | installed | fixed in | where | title |\n|---|---|---|---|---|---|\n")
        for row in rows:
            out.write("| " + " | ".join(value.replace("|", "/") for value in row) + " |\n")
print(f"::notice title=Trivy {image}::{len(rows)} fixable critical vulnerabilities (full table in the job summary)")
for vid, pkg, installed, fixed, target, title in rows[:9]:  # GitHub shows 10 annotations per step
    print(f"::error title={vid} in {pkg}::{pkg} {installed} -> {fixed} ({target}) {title}")
sys.exit(1 if rows else 0)
