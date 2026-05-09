/**
 * # Módulo cpu-small — stub Phase 2c
 *
 * Phase 2c: null_resource + output simulado para validar o fluxo
 * terraform init/apply/output sem provisionar infra Azure real.
 *
 * Phase 2d: substituir null_resource por azurerm_linux_virtual_machine
 * em subnet pré-aprovada (VNet/subnet existente, NSG com regra SSH
 * restrita a range do allocator).
 *
 * OS canônico: Ubuntu 20.04 LTS (conforme padrão dataforalltech).
 */

terraform {
  required_version = ">= 1.5"

  # Phase 2c: estado local (arquivo terraform.tfstate no diretório do módulo).
  # Phase 2d: migrar para backend remoto (Azure Storage ou Terraform Cloud).
  backend "local" {}

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

# Stub: simula tempo de provisionamento e gera endpoint fake.
# Phase 2d: substituir por azurerm_linux_virtual_machine.
resource "null_resource" "vm_stub" {
  triggers = {
    vm_id = var.vm_id
    spec  = var.spec
  }

  provisioner "local-exec" {
    # Simula ~1s de "provisionamento" — suficiente para testar o fluxo async.
    command = "echo Provisioning ${var.spec} vm_id=${var.vm_id} && exit 0"
  }
}
