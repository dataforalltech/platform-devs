# Variáveis do módulo Azure cpu-medium (Phase 2d)
# Idêntico ao cpu-small, com vm_size diferente.

variable "vm_id" {
  type        = string
  description = "Identificador único da VM gerado pelo allocator (UUID)."
}

variable "spec" {
  type        = string
  description = "Spec da VM. Sempre 'cpu-medium' para este módulo (informativo)."
  default     = "cpu-medium"
}

variable "location" {
  type        = string
  description = "Região Azure para provisionamento."
  default     = "brazilsouth"
}

variable "vm_size" {
  type        = string
  description = "Tamanho da VM Azure."
  default     = "Standard_D4s_v3" # 4 vCPU, 16 GiB RAM
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
