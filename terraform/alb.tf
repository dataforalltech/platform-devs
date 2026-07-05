# alb.tf — ACM (wildcard, validação DNS na Cloudflare) + ALB + listeners/regras.

# ── ACM — certificado wildcard *.dominio (+ ápice) ──────────────────────────
resource "aws_acm_certificate" "wildcard" {
  domain_name               = "*.${var.domain}"
  subject_alternative_names = [var.domain]
  validation_method         = "DNS"
  lifecycle { create_before_destroy = true }
  tags = { Name = "${local.name}-cert" }
}

# Registros de validação DNS na Cloudflare.
resource "cloudflare_record" "acm_validation" {
  for_each = {
    for dvo in aws_acm_certificate.wildcard.domain_validation_options : dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }
  zone_id = var.cloudflare_zone_id
  name    = each.value.name
  type    = each.value.type
  value   = trimsuffix(each.value.value, ".")
  ttl     = 60
  proxied = false
}

resource "aws_acm_certificate_validation" "wildcard" {
  certificate_arn         = aws_acm_certificate.wildcard.arn
  validation_record_fqdns = [for r in cloudflare_record.acm_validation : r.hostname]
}

# ── ALB — internet-facing, subnets públicas, só IPs Cloudflare (SG) ─────────
resource "aws_lb" "main" {
  name                       = "${local.name}-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = [for s in aws_subnet.public : s.id]
  drop_invalid_header_fields = true
  tags                       = { Name = "${local.name}-alb" }
}

# Target group → porta de borda (routing mesh do Swarm) em qualquer nó do app.
resource "aws_lb_target_group" "gateway" {
  name        = "${local.name}-gateway"
  port        = var.edge_published_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  health_check {
    path                = "/api/health/ready"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# Anexa todos os nós do app (managers + workers) — o mesh roteia de qualquer um.
resource "aws_lb_target_group_attachment" "managers" {
  count            = var.app_manager_count
  target_group_arn = aws_lb_target_group.gateway.arn
  target_id        = aws_instance.app_manager[count.index].id
  port             = var.edge_published_port
}
resource "aws_lb_target_group_attachment" "workers" {
  count            = var.app_node_count
  target_group_arn = aws_lb_target_group.gateway.arn
  target_id        = aws_instance.app_worker[count.index].id
  port             = var.edge_published_port
}

# Listener 80 → redireciona para 443.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Listener 443 — TLS ACM, forward padrão para o gateway.
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.wildcard.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.gateway.arn
  }
}

# Bloqueio das rotas internas na borda (D7): 403 fixo, nunca expostas.
resource "aws_lb_listener_rule" "block_internal" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\":\"FORBIDDEN\"}"
      status_code  = "403"
    }
  }
  condition {
    path_pattern { values = ["/internal/*", "/platform-admin/*", "/lab/*"] }
  }
}
