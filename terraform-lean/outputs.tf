output "instance_id" {
  value = aws_instance.host.id
}
output "region" {
  description = "Regiao AWS do ambiente enxuto."
  value       = var.region
}
output "public_ip" {
  description = "IP público (só egress; sem ingress no SG)."
  value       = aws_instance.host.public_ip
}
output "tunnel_id" {
  value = cloudflare_zero_trust_tunnel_cloudflared.main.id
}
output "tunnel_cname" {
  value = "${cloudflare_zero_trust_tunnel_cloudflared.main.id}.cfargotunnel.com"
}
output "s3_backups_bucket" {
  value = aws_s3_bucket.backups.bucket
}
output "ssm_access_hint" {
  description = "Acesse o host sem SSH via SSM Session Manager."
  value       = "aws ssm start-session --target ${aws_instance.host.id} --region ${var.region}"
}
