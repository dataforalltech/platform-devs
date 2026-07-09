# storage.tf — ECR (D3) e buckets S3 (logs + backups).

# ── ECR — um repositório por serviço, scan on push, cifrado por KMS ──────────
resource "aws_ecr_repository" "svc" {
  for_each             = toset(var.ecr_services)
  name                 = "dataforall/3.0/${each.value}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
}

# Mantém as N tags mais recentes; expira imagens antigas.
resource "aws_ecr_lifecycle_policy" "svc" {
  for_each   = aws_ecr_repository.svc
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Reter as 20 imagens mais recentes"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}

# ── S3 — logs de aplicação (LOG_UPLOAD_*) ───────────────────────────────────
resource "aws_s3_bucket" "logs" {
  bucket = "${local.name}-logs-${data.aws_caller_identity.current.account_id}"
}
resource "aws_s3_bucket" "backups" {
  bucket = "${local.name}-backups-${data.aws_caller_identity.current.account_id}"
}

# Configuração comum (versionamento, cifra, bloqueio público).
resource "aws_s3_bucket_versioning" "buckets" {
  for_each = { logs = aws_s3_bucket.logs.id, backups = aws_s3_bucket.backups.id }
  bucket   = each.value
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "buckets" {
  for_each = { logs = aws_s3_bucket.logs.id, backups = aws_s3_bucket.backups.id }
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "buckets" {
  for_each                = { logs = aws_s3_bucket.logs.id, backups = aws_s3_bucket.backups.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Ciclo de vida dos backups (retenção — hardening §5).
resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "expire-old-backups"
    status = "Enabled"
    filter {} # aplica a todos os objetos
    noncurrent_version_expiration { noncurrent_days = 30 }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}
