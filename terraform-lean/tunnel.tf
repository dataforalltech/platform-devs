# tunnel.tf — Cloudflare Tunnel (origem sem entrada pública) + DNS wildcard.

resource "random_id" "tunnel_secret" {
  byte_length = 32
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "main" {
  account_id = var.cloudflare_account_id
  name       = local.name
  secret     = random_id.tunnel_secret.b64_std
  config_src = "cloudflare"
}

# Ingress: *.dominio e ápice -> gateway local (edge_port). TLS termina na Cloudflare.
resource "cloudflare_zero_trust_tunnel_cloudflared_config" "main" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.main.id
  config {
    ingress_rule {
      hostname = "*.${var.domain}"
      service  = "http://localhost:${var.edge_port}"
    }
    ingress_rule {
      hostname = var.domain
      service  = "http://localhost:${var.edge_port}"
    }
    # Frontends de produto em zonas .com.br (separadas do var.domain) — bring-up
    # 2026-07-07. Adicionados via API; declarados aqui p/ um apply futuro NÃO
    # reverter o ingress. Ver docs/runbooks/frontends-data4all-bringup.md.
    ingress_rule {
      hostname = "admin.data4all.com.br"
      service  = "http://localhost:${var.edge_port}"
    }
    ingress_rule {
      hostname = "partner.data4all.com.br"
      service  = "http://localhost:${var.edge_port}"
    }
    ingress_rule {
      hostname = "sales.data4all.com.br"
      service  = "http://localhost:${var.edge_port}"
    }
    ingress_rule {
      hostname = "platform.d4all.com.br"
      service  = "http://localhost:${var.edge_port}"
    }
    ingress_rule {
      service = "http_status:404" # catch-all obrigatório
    }
  }
}

# DNS: wildcard multi-tenant (D7) + ápice -> o tunnel (proxied = WAF/DDoS no edge).
resource "cloudflare_record" "wildcard" {
  zone_id = var.cloudflare_zone_id
  name    = "*"
  type    = "CNAME"
  value   = "${cloudflare_zero_trust_tunnel_cloudflared.main.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
  comment = "Wildcard multi-tenant -> Cloudflare Tunnel (terraform-lean)"
}
# NOTA: a raiz (apex) dataforall.tech NAO e gerenciada aqui — ja existe na Cloudflare
# e nao e um tenant (tenants sao subdominios, cobertos pelo wildcard acima).

# Token do tunnel guardado no SSM (SecureString) — o cloudflared lê no boot.
resource "aws_ssm_parameter" "tunnel_token" {
  name  = "/${local.name}/cloudflare-tunnel-token"
  type  = "SecureString"
  value = cloudflare_zero_trust_tunnel_cloudflared.main.tunnel_token
}
