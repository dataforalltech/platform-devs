# Variáveis do módulo cpu-small
# Phase 2c: stub — null_resource + output simulado.
# Phase 2d: trocar por azurerm_linux_virtual_machine real.

variable "vm_id" {
  type        = string
  description = "Identificador único da VM gerado pelo allocator (Phase 2c: usado no output simulado)."
}

variable "spec" {
  type        = string
  description = "Spec da VM solicitada (ex: cpu-small). Informativo nesse stub."
  default     = "cpu-small"
}

variable "location" {
  type        = string
  description = "Região Azure (Phase 2d). Ignorada no stub Phase 2c."
  default     = "brazilsouth"
}

variable "resource_group" {
  type        = string
  description = "Resource group Azure (Phase 2d). Ignorado no stub Phase 2c."
  default     = "rg-agents-sandbox"
}
