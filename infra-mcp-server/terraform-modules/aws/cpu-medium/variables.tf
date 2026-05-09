# Variáveis do módulo AWS cpu-medium (Phase 2d)
# Idêntico ao cpu-small, com instance_type diferente.

variable "vm_id" {
  type        = string
  description = "Identificador único da VM gerado pelo allocator (UUID)."
}

variable "spec" {
  type        = string
  description = "Spec da VM. Sempre 'cpu-medium' para este módulo (informativo)."
  default     = "cpu-medium"
}

variable "region" {
  type        = string
  description = "Região AWS para provisionamento."
  default     = "us-east-1"
}

variable "instance_type" {
  type        = string
  description = "Tipo de instância EC2."
  default     = "t3.xlarge" # 4 vCPU, 16 GiB RAM
}

variable "subnet_id" {
  type        = string
  description = "ID da subnet pré-aprovada. Obrigatório via TF_VAR_subnet_id."
}

variable "vpc_id" {
  type        = string
  description = "ID da VPC para o Security Group. Obrigatório via TF_VAR_vpc_id."
}

variable "ssh_public_key" {
  type        = string
  description = "Chave pública Ed25519 OpenSSH injetada pelo allocator (Phase 2f). Gerada por VM."
}

variable "ssh_source_cidr" {
  type        = string
  description = "CIDR autorizado a acessar SSH. Restringir ao range do allocator em produção."
  default     = "10.0.0.0/8"
}

variable "associate_public_ip_address" {
  type        = bool
  description = "Associar IP público. Desabilitar em subnets privadas."
  default     = true
}
