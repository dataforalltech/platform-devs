/**
 * # Módulo Azure cpu-small — Phase 2d
 *
 * Provisiona Standard_B2s com Ubuntu 20.04 LTS em subnet pré-existente.
 * Ambiente alvo: PROD.
 *
 * Variáveis obrigatórias (via TF_VAR_xxx no ambiente do processo allocator):
 *   TF_VAR_resource_group        — resource group pré-existente
 *   TF_VAR_subnet_id             — resource ID da subnet pré-aprovada
 *                                  (ex: /subscriptions/.../subnets/snet-agents)
 *   TF_VAR_admin_ssh_public_key  — conteúdo da chave pública SSH (ssh-rsa AAAA...)
 *
 * Autenticação Azure: via env vars padrão do Azure CLI / Service Principal:
 *   ARM_CLIENT_ID, ARM_CLIENT_SECRET, ARM_TENANT_ID, ARM_SUBSCRIPTION_ID
 *   ou via az login com AZURE_CONFIG_DIR definido.
 *
 * Output obrigatório lido pelo TerraformProvisioner: vm_ssh_endpoint (host:port).
 *
 * Hard stops do módulo:
 *   - Nunca cria VNet, subnet ou NSG compartilhado.
 *   - NIC conectada à subnet pré-aprovada (VNet/NSG existentes).
 *   - Autenticação apenas por SSH key (password_authentication = false).
 *   - Disco OS Premium_LRS, criptografado por padrão pelo Azure.
 */

terraform {
  required_version = ">= 1.5"

  # Backend local por VM (state isolado em states/<vm_id>.tfstate).
  # Phase 2e: migrar para Azure Storage backend.
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

# IP público estático para endpoint SSH
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

# NIC conectada à subnet pré-aprovada
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

# VM Linux: Standard_B2s, Ubuntu 20.04 LTS
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
    disk_size_gb         = 30
  }

  # Ubuntu 20.04 LTS — OS canônico dataforalltech
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
