# Outputs do módulo GCP high-mem (Phase 2g)

output "vm_ssh_endpoint" {
  description = "Endpoint SSH no formato host:port (IP externo NAT da instância)."
  value       = "${google_compute_instance.vm.network_interface[0].access_config[0].nat_ip}:22"
}

output "vm_id" {
  description = "Identificador do allocator (passthrough)."
  value       = var.vm_id
}

output "spec" {
  description = "Spec provisionada (passthrough)."
  value       = var.spec
}

output "gcp_instance_id" {
  description = "ID da instância GCP (para auditoria e runbook)."
  value       = google_compute_instance.vm.id
}

output "internal_ip" {
  description = "IP interno da instância."
  value       = google_compute_instance.vm.network_interface[0].network_ip
}
