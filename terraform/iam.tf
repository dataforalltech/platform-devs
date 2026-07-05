# iam.tf — instance profiles (least-privilege) para app, data e Vault.

data "aws_caller_identity" "current" {}

# ── Trust policy comum (EC2) ────────────────────────────────────────────────
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# ── App tier — ECR pull + SSM + logs no S3 ──────────────────────────────────
resource "aws_iam_role" "app" {
  name               = "${local.name}-app-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_role_policy_attachment" "app_ecr" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

data "aws_iam_policy_document" "app_logs" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.logs.arn}/*"]
  }
}
resource "aws_iam_role_policy" "app_logs" {
  name   = "${local.name}-app-logs"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app_logs.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name}-app-ec2"
  role = aws_iam_role.app.name
}

# ── Data tier — SSM + backups no S3 ─────────────────────────────────────────
resource "aws_iam_role" "data" {
  name               = "${local.name}-data-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}
resource "aws_iam_role_policy_attachment" "data_ssm" {
  role       = aws_iam_role.data.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
data "aws_iam_policy_document" "data_backups" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
  }
}
resource "aws_iam_role_policy" "data_backups" {
  name   = "${local.name}-data-backups"
  role   = aws_iam_role.data.id
  policy = data.aws_iam_policy_document.data_backups.json
}
resource "aws_iam_instance_profile" "data" {
  name = "${local.name}-data-ec2"
  role = aws_iam_role.data.name
}

# ── Vault — aws auth (valida identidade) + KMS auto-unseal + SSM ────────────
resource "aws_iam_role" "vault" {
  name               = "${local.name}-vault-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}
resource "aws_iam_role_policy_attachment" "vault_ssm" {
  role       = aws_iam_role.vault.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
data "aws_iam_policy_document" "vault" {
  statement {
    sid       = "AwsAuthValidation"
    actions   = ["ec2:DescribeInstances", "iam:GetInstanceProfile", "iam:GetUser", "iam:GetRole", "sts:GetCallerIdentity"]
    resources = ["*"]
  }
  statement {
    sid       = "KmsAutoUnseal"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:DescribeKey"]
    resources = [aws_kms_key.main.arn]
  }
}
resource "aws_iam_role_policy" "vault" {
  name   = "${local.name}-vault"
  role   = aws_iam_role.vault.id
  policy = data.aws_iam_policy_document.vault.json
}
resource "aws_iam_instance_profile" "vault" {
  name = "${local.name}-vault-ec2"
  role = aws_iam_role.vault.name
}
