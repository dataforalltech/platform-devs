# Variáveis do módulo Azure cpu-large (Phase 2e)

variable "vm_id" {
  type        = string
  description = "Identificador único da VM gerado pelo allocator (UUID)."
}

variable "spec" {
  type        = string
  description = "Spec da VM. Sempre 'cpu-large' para este módulo (informativo)."
  default     = "cpu-large"
}

variable "location" {
  type        = string
  description = "Região Azure para provisionamento."
  default     = "brazilsouth"
}

variable "vm_size" {
  type        = string
  description = "Tamanho da VM Azure."
  default     = "Standard_D8s_v3" # 8 vCPU, 32 GiB RAM
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

variable "admin_ssh_public_key" {
  type        = string
  sensitive   = true
  description = "Conteúdo da chave SSH pública. Obrigatório via TF_VAR_admin_ssh_public_key."
}
