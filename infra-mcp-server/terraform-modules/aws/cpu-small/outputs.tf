# Outputs do módulo AWS cpu-small (Phase 2d)
# TerraformProvisioner lê `vm_ssh_endpoint` após terraform apply.

output "vm_ssh_endpoint" {
  description = "Endpoint SSH no formato host:port. IP público se disponível, senão privado."
  value = format(
    "%s:22",
    coalesce(aws_instance.vm.public_ip, aws_instance.vm.private_ip)
  )
}

output "vm_id" {
  description = "Identificador do allocator (passthrough para rastreabilidade)."
  value       = var.vm_id
}

output "spec" {
  description = "Spec provisionada (passthrough)."
  value       = var.spec
}

output "instance_id" {
  description = "ID da instância EC2 (para auditoria e runbook de destroy manual)."
  value       = aws_instance.vm.id
}

output "private_ip" {
  description = "IP privado da instância (sempre disponível, independente de IP público)."
  value       = aws_instance.vm.private_ip
}

output "ami_id" {
  description = "AMI usada no provisionamento (Ubuntu 20.04 LTS, para rastreabilidade)."
  value       = data.aws_ami.ubuntu_20_04.id
}
