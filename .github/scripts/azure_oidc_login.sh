#!/usr/bin/env bash
# Sign in to Azure with this job's GitHub OIDC token (federated credential on
# id-openings-ci, infra/compute/registry.tf). On a mismatch, Azure's error is reported as
# an annotation; the token's subject is printed so it can be compared with the credential.
set -euo pipefail
: "${AZURE_CLIENT_ID:?secret AZURE_CLIENT_ID is not set}"
: "${AZURE_TENANT_ID:?secret AZURE_TENANT_ID is not set}"

token=$(curl -sSf -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=api://AzureADTokenExchange" | jq -r .value)
echo "::add-mask::$token"

# The subject must equal the federated credential's subject exactly.
sub=$(python3 -c 'import sys,json,base64;p=sys.argv[1].split(".")[1];p+="="*(-len(p)%4);print(json.loads(base64.urlsafe_b64decode(p))["sub"])' "$token")
echo "::notice title=GitHub OIDC subject::$sub"

if ! az login --service-principal -u "$AZURE_CLIENT_ID" --tenant "$AZURE_TENANT_ID" \
     --federated-token "$token" --allow-no-subscriptions --output none 2> az-login.err; then
  grep -v '^\s*$' az-login.err | head -6 | while IFS= read -r line; do echo "::error title=az login::$line"; done
  exit 1
fi
echo "signed in to Azure as the CI identity"
