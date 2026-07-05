# main.tf — locals, AMI e chave KMS compartilhada.

locals {
  name = "${var.project}-${var.environment}"

  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Stack       = "dataforall-platform"
  }
}

# AMI Ubuntu 22.04 LTS (Docker/Swarm). Trocar o owner/filtro se preferir AL2023.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# KMS para cifrar volumes EBS e buckets S3 (at-rest — hardening §5).
resource "aws_kms_key" "main" {
  description             = "${local.name} — EBS/S3 encryption"
  deletion_window_in_days = 14
  enable_key_rotation     = true
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.main.key_id
}
