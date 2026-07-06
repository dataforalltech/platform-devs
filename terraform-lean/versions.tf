# versions.tf — ambiente ENXUTO (HML / prod inicial): 1 EC2 + Cloudflare Tunnel.
terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 5.40" }
    cloudflare = { source = "cloudflare/cloudflare", version = "~> 4.30" }
    random     = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = local.common_tags }
}

# Cloudflare — token via env CLOUDFLARE_API_TOKEN (Tunnel + DNS + Zero Trust).
provider "cloudflare" {}
