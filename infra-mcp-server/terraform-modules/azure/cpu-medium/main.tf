/**
 * # Módulo Azure cpu-medium — Phase 2d
 *
 * Provisiona Standard_D4s_v3 com Ubuntu 20.04 LTS em subnet pré-existente.
 * Ambiente alvo: PROD (cargas mais pesadas que cpu-small).
 *
 * Variáveis obrigatórias (via TF_VAR_xxx):
 *   TF_VAR_resource_group, TF_VAR_subnet_id, TF_VAR_admin_ssh_public_key
 *
 * Idêntico ao módulo cpu-small; apenas vm_size padrão difere.
 * Ver cpu-small/main.tf para comentários detalhados.
 */

terraform {
  required_version = ">= 1.5"
  backend "local" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_public_ip" "vm" {
  name                = "pip-alloc-${substr(var.vm_id, 0, 8)}"
  location            = var.location
  resource_group_name = var.resource_group
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = {
    ManagedBy   = "infra-mcp-allocator"
    Spec        = var.spec
    AllocatorVM = var.vm_id
  }
}

resource "azurerm_network_interface" "vm" {
  name                = "nic-alloc-${substr(var.vm_id, 0, 8)}"
  location            = var.location
  resource_group_name = var.resource_group

  ip_configuration {
    name                          = "primary"
    subnet_id                     = var.subnet_id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.vm.id
  }

  tags = {
    ManagedBy   = "infra-mcp-allocator"
    Spec        = var.spec
    AllocatorVM = var.vm_id
  }
}

resource "azurerm_linux_virtual_machine" "vm" {
  name                            = "vm-alloc-${substr(var.vm_id, 0, 8)}"
  location                        = var.location
  resource_group_name             = var.resource_group
  size                            = var.vm_size
  admin_username                  = var.admin_username
  disable_password_authentication = true

  network_interface_ids = [azurerm_network_interface.vm.id]

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  os_disk {
    name                 = "osdisk-alloc-${substr(var.vm_id, 0, 8)}"
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 50
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-focal"
    sku       = "20_04-lts-gen2"
    version   = "latest"
  }

  tags = {
    ManagedBy   = "infra-mcp-allocator"
    Spec        = var.spec
    AllocatorVM = var.vm_id
  }
}
