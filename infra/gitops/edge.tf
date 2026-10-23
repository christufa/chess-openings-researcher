# Entry from the internet: Cloudflare Tunnel + Access, as in lichess-delta-kube. No public
# IP, load balancer or open port on the cluster: cloudflared (deploy/cloudflared) dials out
# to Cloudflare, which routes the hostnames below to it.
#
# Private hostnames (<prefix>-cd, <prefix>-flows): Cloudflare Access asks for a Microsoft
# (Entra ID) sign-in through the identity provider lichess-delta-kube already created in
# this Cloudflare account, and lets in only var.access_allowed_emails; cloudflared re-checks
# the Access token (aud) on every request, so traffic can't reach them without Access.
#
# Public hostname (<prefix>): the research explorer and its read-only API, rate-limited per
# client IP by the API itself (CF-Connecting-IP).
#
# chess-engines.<domain>: the shared engine API (christufa/chess-engines) for projects
# outside this cluster, and its playground UI at /. Cloudflare Access admits its service
# tokens (programs) and the owner after a Microsoft sign-in (the playground); a program
# without a token gets a 401, not a sign-in page. cloudflared re-checks the Access token.
# https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
locals {
  private_hosts = {
    cd = {
      hostname      = "${var.hostname_prefix}-cd.${var.domain}"
      title         = "Argo CD"
      service       = "https://argocd-server.argocd.svc.cluster.local:443"
      no_tls_verify = true # Argo CD's self-signed certificate on an in-cluster hop
    }
    flows = {
      hostname      = "${var.hostname_prefix}-flows.${var.domain}"
      title         = "Argo Workflows"
      service       = "http://argo-workflows-server.argo.svc.cluster.local:2746"
      no_tls_verify = false
    }
  }
  public_hostname = "${var.hostname_prefix}.${var.domain}"
  public_service  = "http://openings-api.openings-research.svc.cluster.local:80"

  engines_hostname = "${var.chess_engines_hostname}.${var.domain}"
  engines_service  = "http://chess-engines.chess-engines.svc.cluster.local:80"
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "aks" {
  account_id = var.cloudflare_account_id
  name       = "aks-openings"
  config_src = "cloudflare" # ingress rules managed here, not in a cloudflared config file
}

data "cloudflare_zero_trust_tunnel_cloudflared_token" "aks" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.aks.id
}

resource "cloudflare_zero_trust_access_policy" "owner" {
  account_id = var.cloudflare_account_id
  name       = "${var.hostname_prefix}: owner only"
  decision   = "allow"
  include    = [for e in var.access_allowed_emails : { email = { email = e } }]
}

resource "cloudflare_zero_trust_access_application" "private" {
  for_each = local.private_hosts

  account_id                 = var.cloudflare_account_id
  name                       = "${var.hostname_prefix}: ${each.value.title}"
  type                       = "self_hosted"
  domain                     = each.value.hostname
  destinations               = [{ type = "public", uri = each.value.hostname }]
  session_duration           = "24h"
  allowed_idps               = [var.access_identity_provider_id]
  auto_redirect_to_identity  = true # straight to the Microsoft sign-in
  app_launcher_visible       = true
  http_only_cookie_attribute = true
  same_site_cookie_attribute = "lax"
  policies                   = [{ id = cloudflare_zero_trust_access_policy.owner.id, precedence = 1 }]
}

# ---- chess-engines: service tokens only ----

# One token per calling project, so each can be rotated or revoked on its own.
resource "cloudflare_zero_trust_access_service_token" "chess_engines" {
  for_each = var.chess_engines_service_tokens

  account_id = var.cloudflare_account_id
  name       = "chess-engines: ${each.key}"
  duration   = "8760h" # a year; Cloudflare emails before expiry, then re-apply to rotate
}

resource "cloudflare_zero_trust_access_policy" "chess_engines" {
  account_id = var.cloudflare_account_id
  name       = "chess-engines: service tokens"
  decision   = "non_identity"
  include = [for t in cloudflare_zero_trust_access_service_token.chess_engines :
  { service_token = { token_id = t.id } }]
}

resource "cloudflare_zero_trust_access_application" "chess_engines" {
  account_id                = var.cloudflare_account_id
  name                      = "chess-engines API"
  type                      = "self_hosted"
  domain                    = local.engines_hostname
  destinations              = [{ type = "public", uri = local.engines_hostname }]
  session_duration          = "24h"
  allowed_idps              = [var.access_identity_provider_id]
  auto_redirect_to_identity = true # browsers go straight to the Microsoft sign-in
  app_launcher_visible      = true
  service_auth_401_redirect = true # programs: 401 for a missing or bad token, not a login redirect
  policies = [
    { id = cloudflare_zero_trust_access_policy.chess_engines.id, precedence = 1 }, # service tokens
    { id = cloudflare_zero_trust_access_policy.owner.id, precedence = 2 },         # the playground
  ]
}

# Copies for callers in other clusters (External Secrets, CI secrets). Writing needs your
# IP in the vault's firewall, like any other secret you set by hand.
resource "azurerm_key_vault_secret" "chess_engines_client_id" {
  for_each = cloudflare_zero_trust_access_service_token.chess_engines

  name         = "chess-engines-${each.key}-client-id"
  value        = each.value.client_id
  key_vault_id = local.compute.key_vault_id
  content_type = "Cloudflare Access service token ID for https://${local.engines_hostname}"
}

resource "azurerm_key_vault_secret" "chess_engines_client_secret" {
  for_each = cloudflare_zero_trust_access_service_token.chess_engines

  name         = "chess-engines-${each.key}-client-secret"
  value        = each.value.client_secret
  key_vault_id = local.compute.key_vault_id
  content_type = "Cloudflare Access service token secret for https://${local.engines_hostname}"
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "aks" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.aks.id
  config = {
    ingress = concat(
      [for k, h in local.private_hosts : {
        hostname = h.hostname
        service  = h.service
        origin_request = {
          no_tls_verify = h.no_tls_verify
          access = {
            required  = true
            team_name = var.cloudflare_team_name
            aud_tag   = [cloudflare_zero_trust_access_application.private[k].aud]
          }
        }
      }],
      [{ hostname = local.public_hostname, service = local.public_service }],
      [{
        hostname = local.engines_hostname
        service  = local.engines_service
        origin_request = {
          access = {
            required  = true
            team_name = var.cloudflare_team_name
            aud_tag   = [cloudflare_zero_trust_access_application.chess_engines.aud]
          }
        }
      }],
      [{ service = "http_status:404" }], # anything else
    )
  }
}

resource "cloudflare_dns_record" "private" {
  for_each = local.private_hosts

  zone_id = var.cloudflare_zone_id
  name    = each.value.hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.aks.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1 # automatic (proxied)
  comment = "openings-researcher: ${each.value.title} via Cloudflare Tunnel + Access (infra/gitops/edge.tf)"
}

resource "cloudflare_dns_record" "public" {
  zone_id = var.cloudflare_zone_id
  name    = local.public_hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.aks.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
  comment = "openings-researcher: research explorer via Cloudflare Tunnel (infra/gitops/edge.tf)"
}

resource "cloudflare_dns_record" "chess_engines" {
  zone_id = var.cloudflare_zone_id
  name    = local.engines_hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.aks.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
  comment = "chess-engines API via Cloudflare Tunnel + Access service tokens (infra/gitops/edge.tf)"
}

# The tunnel token for cloudflared, straight into the cluster (never in a file or git).
resource "kubernetes_namespace_v1" "cloudflared" {
  metadata {
    name = "cloudflared"
    labels = {
      "pod-security.kubernetes.io/enforce" = "restricted"
      "pod-security.kubernetes.io/warn"    = "restricted"
      "pod-security.kubernetes.io/audit"   = "restricted"
    }
  }
}

resource "kubernetes_secret_v1" "cloudflared_token" {
  metadata {
    name      = "cloudflared-token"
    namespace = kubernetes_namespace_v1.cloudflared.metadata[0].name
  }
  data = {
    token = data.cloudflare_zero_trust_tunnel_cloudflared_token.aks.token
  }
}
