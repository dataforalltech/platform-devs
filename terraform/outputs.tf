# outputs.tf

output "alb_dns_name" {
  description = "DNS do ALB (alvo dos registros Cloudflare)."
  value       = aws_lb.main.dns_name
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "app_manager_private_ips" {
  description = "IPs privados dos managers do Swarm (bootstrap do cluster)."
  value       = aws_instance.app_manager[*].private_ip
}

output "app_worker_private_ips" {
  value = aws_instance.app_worker[*].private_ip
}

output "data_private_ips" {
  description = "IPs privados dos data stores (para DB_HOST/ADMIN_DB_HOST/etc)."
  value       = { for k, i in aws_instance.data : k => i.private_ip }
}

output "vault_private_ip" {
  value = aws_instance.vault.private_ip
}

output "ecr_repository_urls" {
  description = "URLs dos repositórios ECR por serviço."
  value       = { for k, r in aws_ecr_repository.svc : k => r.repository_url }
}

output "s3_logs_bucket" {
  value = aws_s3_bucket.logs.bucket
}

output "s3_backups_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "acm_certificate_arn" {
  value = aws_acm_certificate_validation.wildcard.certificate_arn
}

output "kms_key_arn" {
  value = aws_kms_key.main.arn
}

output "iam_app_role_arn" {
  description = "Role do app tier — ligar no Vault (auth/aws role bound_iam_principal_arn)."
  value       = aws_iam_role.app.arn
}
