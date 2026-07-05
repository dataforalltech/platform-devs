# variables.tf — ambiente enxuto.

variable "project" {
  type    = string
  default = "dataforall"
}

variable "environment" {
  description = "hml | prod (mesmo shape enxuto)."
  type        = string
  default     = "hml"
}

variable "owner" {
  description = "Time/pessoa responsável (tag Owner — governança)."
  type        = string
  default     = "platform-team"
}

variable "cost_center" {
  description = "Centro de custo (tag CostCenter — cost allocation no Billing)."
  type        = string
  default     = "platform"
}

variable "region" {
  type    = string
  default = "sa-east-1"
}

variable "az" {
  description = "AZ única (ambiente enxuto, sem HA)."
  type        = string
  default     = "sa-east-1a"
}

variable "vpc_cidr" {
  type    = string
  default = "10.10.0.0/16"
}

# ── DNS / Tunnel (D6/D7) ─────────────────────────────────────────────────────
variable "domain" {
  description = "Domínio multi-tenant (wildcard) — ex.: dataforall.tech."
  type        = string
}

variable "cloudflare_account_id" {
  description = "Account ID da Cloudflare (o Tunnel é escopo de conta)."
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Zone ID da Cloudflare para o domínio."
  type        = string
}

# ── Compute — 1 EC2 rodando tudo (app + data + vault via docker compose) ────
variable "instance_type" {
  description = "Tipo da EC2 única. t3.xlarge (16GB) comporta os ~29 serviços + stores idle; reduza p/ subconjunto."
  type        = string
  default     = "t3.xlarge"
}

variable "root_gib" {
  type    = number
  default = 40
}

variable "data_gib" {
  description = "Volume EBS gp3 dedicado para os dados (todos os stores)."
  type        = number
  default     = 100
}

variable "snapshot_retention_count" {
  description = "Snapshots EBS (DLM) a reter."
  type        = number
  default     = 7
}

variable "edge_port" {
  description = "Porta local do gateway para onde o Tunnel roteia."
  type        = number
  default     = 8080
}

# ECR opcional (por ora o CD usa ACR — D3). Vazio = não cria repositórios.
variable "ecr_services" {
  type    = list(string)
  default = []
}
