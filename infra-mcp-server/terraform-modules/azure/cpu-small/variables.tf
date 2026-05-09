# Variáveis do módulo Azure cpu-small (Phase 2d)
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

variable "location" {
  type        = string
  description = "Região Azure para provisionamento."
  default     = "brazilsouth"
}

variable "vm_size" {
  type        = string
  description = "Tamanho da VM Azure."
  default     = "Standard_B2s" # 2 vCPU, 4 GiB RAM
}

variable "admin_username" {
  type        = string
  description = "Nome do usuário administrador da VM."
  default     = "azureuser"
}

# --- Variáveis obrigatórias (sem default) ---

variable "resource_group" {
  type        = string
  description = "Nome do resource group pré-existente. Obrigatório via TF_VAR_resource_group."
}

variable "subnet_id" {
  type        = string
  description = "Resource ID da subnet pré-aprovada (ex: /subscriptions/.../subnets/snet-agents). Obrigatório via TF_VAR_subnet_id."
}

variable "admin_ssh_public_key" {
  type        = string
  sensitive   = true
  description = "Conteúdo da chave SSH pública (ssh-rsa AAAA...). Obrigatório via TF_VAR_admin_ssh_public_key."
}
