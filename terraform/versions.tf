# versions.tf — versões de Terraform e providers.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.30"
    }
  }

  # Recomendado em produção: backend remoto versionado.
  # backend "s3" {
  #   bucket         = "dataforall-tfstate"
  #   key            = "infra/terraform.tfstate"
  #   region         = "sa-east-1"
  #   dynamodb_table = "dataforall-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = local.common_tags
  }
}

# Cloudflare (DNS/edge — D6). API token via env: CLOUDFLARE_API_TOKEN
provider "cloudflare" {}
