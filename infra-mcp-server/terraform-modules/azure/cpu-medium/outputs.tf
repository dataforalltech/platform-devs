# Outputs do módulo Azure cpu-medium (Phase 2d)

output "vm_ssh_endpoint" {
  description = "Endpoint SSH no formato host:port (IP público estático da VM)."
  value       = "${azurerm_public_ip.vm.ip_address}:22"
}

output "vm_id" {
  description = "Identificador do allocator (passthrough)."
  value       = var.vm_id
}

output "spec" {
  description = "Spec provisionada (passthrough)."
  value       = var.spec
}

output "azure_vm_id" {
  description = "Resource ID da VM Azure (para auditoria e runbook)."
  value       = azurerm_linux_virtual_machine.vm.id
}

output "private_ip" {
  description = "IP privado da VM."
  value       = azurerm_network_interface.vm.private_ip_address
}
