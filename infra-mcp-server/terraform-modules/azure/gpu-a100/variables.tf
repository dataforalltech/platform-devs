# Variáveis do módulo Azure gpu-a100 (Phase 2g)

variable "vm_id" {
  type        = string
  description = "Identificador único da VM gerado pelo allocator (UUID)."
}

variable "spec" {
  type        = string
  description = "Spec da VM. Sempre 'gpu-a100' para este módulo (informativo)."
  default     = "gpu-a100"
}

variable "location" {
  type        = string
  description = "Região Azure para provisionamento."
  default     = "brazilsouth"
}

variable "vm_size" {
  type        = string
  description = "Tamanho da VM Azure com GPU."
  default     = "Standard_NC6s_v3" # 6 vCPU, 112 GiB RAM, 1x NVIDIA Tesla V100 16 GB
}

variable "admin_username" {
  type        = string
  description = "Nome do usuário administrador da VM."
  default     = "azureuser"
}

variable "resource_group" {
  type        = string
  description = "Nome do resource group pré-existente. Obrigatório via TF_VAR_resource_group."
}

variable "subnet_id" {
  type        = string
  description = "Resource ID da subnet pré-aprovada. Obrigatório via TF_VAR_subnet_id."
}

variable "ssh_public_key" {
  type        = string
  sensitive   = true
  description = "Chave pública Ed25519 OpenSSH injetada pelo allocator (Phase 2f). Gerada por VM."
}
