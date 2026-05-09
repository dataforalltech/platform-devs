# Variáveis do módulo GCP gpu-a100 (Phase 2g)

variable "vm_id" {
  type        = string
  description = "Identificador único da VM gerado pelo allocator (UUID)."
}

variable "spec" {
  type        = string
  description = "Spec da VM. Sempre 'gpu-a100' para este módulo (informativo)."
  default     = "gpu-a100"
}

variable "region" {
  type        = string
  description = "Região GCP para provisionamento."
  default     = "us-central1"
}

variable "zone" {
  type        = string
  description = "Zona GCP com quota de GPU A100 disponível."
  default     = "us-central1-c" # A100 disponível em us-central1-c
}

variable "machine_type" {
  type        = string
  description = "Tipo de máquina GCP com GPU A100."
  default     = "a2-highgpu-1g" # 12 vCPU, 85 GiB RAM, 1x NVIDIA A100 40 GB
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
  description = "Chave pública Ed25519 OpenSSH injetada pelo allocator (Phase 2f). Gerada por VM."
}

variable "ssh_source_cidr" {
  type        = string
  description = "CIDR autorizado a acessar SSH."
  default     = "10.0.0.0/8"
}
