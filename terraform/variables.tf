# variables.tf — entradas da landing zone.

variable "project" {
  description = "Prefixo de nomeação dos recursos."
  type        = string
  default     = "dataforall"
}

variable "environment" {
  description = "Ambiente (prod | hml | dev)."
  type        = string
  default     = "prod"
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
  description = "Região AWS."
  type        = string
  default     = "sa-east-1"
}

variable "azs" {
  description = "Zonas de disponibilidade (>= 2 para HA — D4)."
  type        = list(string)
  default     = ["sa-east-1a", "sa-east-1c"]
}

variable "vpc_cidr" {
  description = "CIDR da VPC."
  type        = string
  default     = "10.0.0.0/16"
}

# ── DNS / TLS (D6/D7) ────────────────────────────────────────────────────────
variable "domain" {
  description = "Domínio raiz da plataforma (multi-tenant por subdomínio — D7)."
  type        = string
  default     = "dataforalltech.com"
}

variable "cloudflare_zone_id" {
  description = "Zone ID da Cloudflare (para DNS wildcard e validação do ACM)."
  type        = string
}

variable "cloudflare_proxied" {
  description = "Proxy da Cloudflare (laranja) nos registros — WAF/DDoS no edge."
  type        = bool
  default     = true
}

# ── Compute ──────────────────────────────────────────────────────────────────
variable "key_name" {
  description = "Nome do key pair EC2 para acesso SSH de bootstrap."
  type        = string
  default     = null
}

variable "app_instance_type" {
  description = "Tipo de instância dos nós do app tier (Swarm)."
  type        = string
  default     = "t3.large"
}

variable "app_node_count" {
  description = "Nº fixo de nós worker do Swarm (escala estática — D4)."
  type        = number
  default     = 2
}

variable "app_manager_count" {
  description = "Nº de managers do Swarm (quórum — 3 recomendado)."
  type        = number
  default     = 3
}

# Data tier — EC2 dedicada por store (D1). type + tamanho do volume EBS (GiB).
variable "data_nodes" {
  description = "Mapa dos data stores: instância + volume EBS gp3 dedicado."
  type = map(object({
    instance_type = string
    data_gib      = number
  }))
  default = {
    mysql-admin     = { instance_type = "t3.large", data_gib = 100 }
    mysql-tenant    = { instance_type = "t3.xlarge", data_gib = 200 }
    postgres-tenant = { instance_type = "t3.xlarge", data_gib = 200 }
    redis           = { instance_type = "t3.medium", data_gib = 30 }
    kafka           = { instance_type = "t3.large", data_gib = 100 }
  }
}

variable "vault_instance_type" {
  description = "Tipo da instância do Vault."
  type        = string
  default     = "t3.small"
}

variable "snapshot_retention_count" {
  description = "Quantos snapshots EBS reter (DLM) por volume do data tier."
  type        = number
  default     = 14
}

# ── Registry (D3) ────────────────────────────────────────────────────────────
variable "ecr_services" {
  description = "Serviços que ganham repositório ECR."
  type        = list(string)
  default = [
    "platform-api-gateway", "platform-mcp", "platform-auth", "platform-admin",
    "platform-notification", "platform-cdc", "platform-ml", "platform-crm-agent",
    "platform-governance", "platform-monitor", "platform-datalake", "platform-connectors",
    "platform-analytics", "platform-communication", "platform-docextract", "platform-dai",
    "platform-flow", "platform-iceberg", "platform-pipeline", "platform-db-vector",
    "platform-security", "platform-agents-factory", "platform-scheduler", "platform-crm",
    "platform-marketing", "platform-marketing-agent", "platform-finance",
    "platform-finance-agent", "platform-sales",
  ]
}

# Porta publicada pelo serviço de borda (gateway) nos nós do Swarm (routing mesh).
variable "edge_published_port" {
  description = "Porta do gateway exposta nos nós para o target group da ALB."
  type        = number
  default     = 8080
}
