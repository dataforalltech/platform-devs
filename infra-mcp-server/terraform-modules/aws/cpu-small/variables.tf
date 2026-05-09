# Variáveis do módulo AWS cpu-small (Phase 2d)
# Obrigatórias: definir via TF_VAR_xxx no ambiente do processo allocator.

variable "vm_id" {
  type        = string
  description = "Identificador único da VM gerado pelo allocator (UUID)."
}

variable "spec" {
  type        = string
  description = "Spec da VM. Sempre 'cpu-small' para este módulo (informativo)."
  default     = "cpu-small"
}

variable "region" {
  type        = string
  description = "Região AWS para provisionamento."
  default     = "us-east-1"
}

variable "instance_type" {
  type        = string
  description = "Tipo de instância EC2."
  default     = "t3.medium" # 2 vCPU, 4 GiB RAM
}

# --- Variáveis obrigatórias (sem default) ---

variable "subnet_id" {
  type        = string
  description = "ID da subnet pré-aprovada (ex: subnet-0abc1234). Obrigatório via TF_VAR_subnet_id."
}

variable "vpc_id" {
  type        = string
  description = "ID da VPC para criação do Security Group (ex: vpc-0abc1234). Obrigatório via TF_VAR_vpc_id."
}

variable "ssh_public_key" {
  type        = string
  description = "Chave pública Ed25519 OpenSSH injetada pelo allocator (Phase 2f). Gerada por VM."
}

# --- Variáveis opcionais com defaults seguros ---

variable "ssh_source_cidr" {
  type        = string
  description = "CIDR autorizado a acessar SSH (porta 22). Restringir ao range do allocator em produção."
  default     = "10.0.0.0/8"
}

variable "associate_public_ip_address" {
  type        = bool
  description = "Associar IP público. Desabilitar se a subnet for privada com bastion/VPN."
  default     = true
}
