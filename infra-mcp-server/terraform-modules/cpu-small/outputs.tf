# Outputs do módulo cpu-small
# O allocator lê `vm_ssh_endpoint` após terraform apply.

output "vm_ssh_endpoint" {
  description = "Endpoint SSH da VM no formato host:port. Phase 2c: stub simulado. Phase 2d: IP real da VM Azure."
  value       = "stub-${var.vm_id}.local:22"
}

output "vm_id" {
  description = "Identificador da VM (passthrough do input, para rastreabilidade)."
  value       = var.vm_id
}

output "spec" {
  description = "Spec provisionada."
  value       = var.spec
}
