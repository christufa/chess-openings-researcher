# Security policy

Report suspected vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/christufa/chess-openings-researcher/security/advisories/new).
Do not publish exploit details, tokens, personal information or confidential data
in public issues, pull requests or workflow logs.

Include the affected commit/version, reproduction steps, expected and observed
behavior, and potential impact. Use synthetic data and redact credentials. Do not
probe production systems, access other users' data or perform denial-of-service
testing without explicit authorization.

This project is pre-production. Security fixes target the current main branch;
there is no supported historical release line or guaranteed response SLA. The
maintainer will coordinate investigation, remediation and disclosure through the
private report. Public visibility does not imply that deployment is hardened or
that every scanner finding has been resolved.

If a credential is exposed, revoke/rotate it immediately. Removing a file or
rewriting Git history does not revoke credentials. Do not paste replacement keys
into the report.
