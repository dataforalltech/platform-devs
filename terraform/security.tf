# security.tf — Security Groups (menor privilégio).
# D6/D7: a ALB só aceita tráfego da Cloudflare; o app tier só recebe da ALB;
# o data tier só recebe do app tier; nada de portas de dados públicas.

data "cloudflare_ip_ranges" "cf" {}

# ── ALB — só IPs da Cloudflare (edge não-contornável) ───────────────────────
resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  description = "ALB — ingress 443/80 apenas da Cloudflare"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS da Cloudflare"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = data.cloudflare_ip_ranges.cf.ipv4_cidr_blocks
  }
  ingress {
    description = "HTTP (redirect) da Cloudflare"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = data.cloudflare_ip_ranges.cf.ipv4_cidr_blocks
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-alb" }
  lifecycle { create_before_destroy = true }
}

# ── App tier (Swarm) — recebe da ALB + tráfego intra-Swarm ──────────────────
resource "aws_security_group" "app" {
  name_prefix = "${local.name}-app-"
  description = "App tier (Docker Swarm) — da ALB + cluster interno"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Porta de borda (routing mesh) vinda da ALB"
    from_port       = var.edge_published_port
    to_port         = var.edge_published_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-app" }
  lifecycle { create_before_destroy = true }
}

# Portas internas do Swarm (cluster/overlay) — só entre nós do app tier.
resource "aws_security_group_rule" "swarm_tcp_2377" {
  type                     = "ingress"
  from_port                = 2377
  to_port                  = 2377
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.app.id
  description              = "Swarm management"
}
resource "aws_security_group_rule" "swarm_gossip_tcp" {
  type                     = "ingress"
  from_port                = 7946
  to_port                  = 7946
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.app.id
  description              = "Swarm node discovery (tcp)"
}
resource "aws_security_group_rule" "swarm_gossip_udp" {
  type                     = "ingress"
  from_port                = 7946
  to_port                  = 7946
  protocol                 = "udp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.app.id
  description              = "Swarm node discovery (udp)"
}
resource "aws_security_group_rule" "swarm_overlay_vxlan" {
  type                     = "ingress"
  from_port                = 4789
  to_port                  = 4789
  protocol                 = "udp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.app.id
  description              = "Swarm overlay (VXLAN)"
}

# ── Data tier — só recebe do app tier (portas dos stores) ───────────────────
resource "aws_security_group" "data" {
  name_prefix = "${local.name}-data-"
  description = "Data tier — MySQL/Postgres/Redis/Kafka apenas do app tier"
  vpc_id      = aws_vpc.main.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-data" }
  lifecycle { create_before_destroy = true }
}

locals {
  data_ports = { mysql = 3306, postgres = 5432, redis = 6379, kafka = 9092 }
}

resource "aws_security_group_rule" "data_from_app" {
  for_each                 = local.data_ports
  type                     = "ingress"
  from_port                = each.value
  to_port                  = each.value
  protocol                 = "tcp"
  security_group_id        = aws_security_group.data.id
  source_security_group_id = aws_security_group.app.id
  description              = "${each.key} do app tier"
}

# ── Vault — 8200 do app tier e do data tier ─────────────────────────────────
resource "aws_security_group" "vault" {
  name_prefix = "${local.name}-vault-"
  description = "Vault — 8200 do app/data tier"
  vpc_id      = aws_vpc.main.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"] # precisa alcançar STS/IAM (aws auth)
  }
  tags = { Name = "${local.name}-vault" }
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group_rule" "vault_from_app" {
  type                     = "ingress"
  from_port                = 8200
  to_port                  = 8200
  protocol                 = "tcp"
  security_group_id        = aws_security_group.vault.id
  source_security_group_id = aws_security_group.app.id
  description              = "Vault API do app tier"
}
