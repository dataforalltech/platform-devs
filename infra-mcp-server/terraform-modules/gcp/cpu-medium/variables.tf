# Variáveis do módulo GCP cpu-medium (Phase 2d)
# Idêntico ao cpu-small, com machine_type diferente.

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
  description = "Região GCP para provisionamento."
  default     = "us-central1"
}

variable "zone" {
  type        = string
  description = "Zona GCP para provisionamento."
  default     = "us-central1-a"
}

variable "machine_type" {
  type        = string
  description = "Tipo de máquina GCP."
  default     = "e2-standard-4" # 4 vCPU, 16 GiB RAM
}

variable "project" {
  type        = string
  description = "GCP project ID. Obrigatório via TF_VAR_project."
}

variable "network" {
  type        = string
  description = "Nome da rede VPC pré-existente. Obrigatório via TF_VAR_network."
}

variable "subnetwork" {
  type        = string
  description = "Nome ou self_link da subnet pré-existente. Obrigatório via TF_VAR_subnetwork."
}

variable "ssh_user" {
  type        = string
  description = "Usuário SSH para acesso à instância."
  default     = "ubuntu"
}

variable "ssh_public_key" {
  type        = string
  sensitive   = true
  description = "Conteúdo da chave SSH pública. Obrigatório via TF_VAR_ssh_public_key."
}

variable "ssh_source_cidr" {
  type        = string
  description = "CIDR autorizado a acessar SSH. Restringir ao range do allocator em produção."
  default     = "10.0.0.0/8"
}
