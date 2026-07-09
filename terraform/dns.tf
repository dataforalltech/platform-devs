# dns.tf — DNS na Cloudflare (D6/D7): wildcard + ápice → ALB, com proxy (WAF).

# Wildcard: cada tenant é um subdomínio (D7). Nenhum registro novo por tenant —
# basta cadastrar o domínio em ADMIN_DATAFORALL.PLATFORMS.
resource "cloudflare_record" "wildcard" {
  zone_id = var.cloudflare_zone_id
  name    = "*"
  type    = "CNAME"
  value   = aws_lb.main.dns_name
  proxied = var.cloudflare_proxied
  ttl     = 1 # automático quando proxied
  comment = "Wildcard multi-tenant -> ALB (terraform)"
}

# Ápice do domínio (CNAME flattening da Cloudflare).
resource "cloudflare_record" "apex" {
  zone_id = var.cloudflare_zone_id
  name    = "@"
  type    = "CNAME"
  value   = aws_lb.main.dns_name
  proxied = var.cloudflare_proxied
  ttl     = 1
  comment = "Apex -> ALB (terraform)"
}
