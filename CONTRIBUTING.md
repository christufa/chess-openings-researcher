# Contributing

Open a pull request against main. Do not commit provider tokens, private keys,
Terraform state/plan files, local data, or private research material. Use synthetic
fixtures for tests. Report vulnerabilities through SECURITY.md rather than issues.

Run Python tests and Ruff, relevant Helm rendering checks, and Terraform
validation for infrastructure changes. CI additionally exercises real Iceberg
reads and writes and browser behavior. Security checks cover Python/JavaScript with CodeQL
and reject newly introduced high/critical dependency vulnerabilities.

External contributors' workflow runs require maintainer approval. All PR code
runs on GitHub-hosted machines without production secrets; never add a production
runner, pull_request_target execution path, or cloud identity to a PR workflow.
Repository checks and deployment approval are separate gates. New actions need a
reviewed allowlist update and a full commit SHA. CODEOWNERS routes review requests;
it does not grant repository write permission.

