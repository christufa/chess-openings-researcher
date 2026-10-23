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
