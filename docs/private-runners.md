# Private runner GitHub App setup

This repository belongs to the personal account `christufa`. Register runners at
repository scope, limited to `christufa/chess-openings-researcher`.

1. Open [GitHub App settings](https://github.com/settings/apps) and select New
   GitHub App. Use a unique name such as `chess-openings-private-runners`.
2. Set the homepage to the repository URL. User authorization callbacks and
   OAuth user tokens are not needed. Disable the webhook Active checkbox;
   runner scale sets do not require an inbound webhook for this configuration.
3. Under Repository permissions, select **Administration: Read and write**.
   Metadata remains **Read-only**. Leave other permissions at No access.
   Do not request Contents/Workflows write, account permissions, or organization
   runner permissions for this repository-scoped installation.
4. Restrict installation to this account, create the App, and record the **App
   ID** (not Client ID). Generate a private key and retain its downloaded `.pem`
   file outside the repository.
5. Install the App on your account using **Only select repositories**, selecting
   `chess-openings-researcher`. Record the installation ID from the installation
   settings URL. Do not install on unrelated repositories.
6. Provide the App ID, installation ID and local private-key path to the deployment
   operator. Never paste the key or place it in a PR, artifact, Terraform variable
   file or state. The deployment will reference a privately created Kubernetes
   Secret with `github_app_id`, `github_app_installation_id` and
   `github_app_private_key`; Helm receives only the Secret name.

[GitHub's ARC authentication documentation](https://docs.github.com/en/actions/how-tos/manage-runners/use-actions-runner-controller/authenticate-to-the-api)
describes the repository Administration permission. This permission is broader
than runner registration alone, so the App key must remain outside job containers.
Do not add this App as a ruleset bypass actor. GitHub App authentication does not
grant Azure access; publication uses the separate protected-environment OIDC identity.

## Activation prerequisites

Runner installation is still pending the App and private network infrastructure.
Only protected-main publication jobs may use the private runners. PR jobs stay
GitHub-hosted, and external-contributor approval is required. Labels alone are
not a security boundary. Keep production approval enabled, use one-job ephemeral
runners and destroy job storage afterward. Never expose the controller key,
Kubernetes service-account token or host Docker socket to a build container.

The current 28-vCPU cluster envelope reserves all spare family quota for upgrades.
Do not add a dedicated runner node pool to it without revising capacity. A runner
architecture and isolation validation are required before registering any runners;
creating the App by itself does not establish a safe execution environment.

Rotate by generating a new App key, updating the private Secret, proving new
runner registration works, then revoking the previous key. Revoking the App key
or uninstalling the App stops future registrations; terminate existing runners
separately if investigating compromise.
