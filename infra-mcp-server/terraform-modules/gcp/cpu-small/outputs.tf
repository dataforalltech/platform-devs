# Outputs do módulo GCP cpu-small (Phase 2d)
# TerraformProvisioner lê `vm_ssh_endpoint` após terraform apply.

output "vm_ssh_endpoint" {
  description = "Endpoint SSH no formato host:port (IP externo NAT da instância)."
  value       = "${google_compute_instance.vm.network_interface[0].access_config[0].nat_ip}:22"
}

output "vm_id" {
  description = "Identificador do allocator (passthrough para rastreabilidade)."
  value       = var.vm_id
}

output "spec" {
  description = "Spec provisionada (passthrough)."
  value       = var.spec
}

output "gcp_instance_id" {
  description = "ID da instância GCP (para auditoria e runbook de destroy manual)."
  value       = google_compute_instance.vm.id
}

output "internal_ip" {
  description = "IP interno da instância (atribuído pela subnet)."
  value       = google_compute_instance.vm.network_interface[0].network_ip
}
