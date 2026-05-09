/**
 * # Módulo GCP cpu-small — Phase 2d
 *
 * Provisiona e2-medium com Ubuntu 20.04 LTS em subnet pré-existente.
 * Ambiente alvo: testes pontuais na GCP.
 *
 * Variáveis obrigatórias (via TF_VAR_xxx no ambiente do processo allocator):
 *   TF_VAR_project           — GCP project ID
 *   TF_VAR_network           — nome da VPC pré-existente (ex: default)
 *   TF_VAR_subnetwork        — nome ou self_link da subnet pré-existente
 *   TF_VAR_ssh_user          — usuário SSH (ex: ubuntu)
 *   TF_VAR_ssh_public_key    — conteúdo da chave pública (ssh-rsa AAAA...)
 *
 * Autenticação GCP: via GOOGLE_APPLICATION_CREDENTIALS ou gcloud auth
 *   application-default login (para uso interativo/DEV).
 *
 * Output obrigatório lido pelo TerraformProvisioner: vm_ssh_endpoint (host:port).
 *
 * Hard stops do módulo:
 *   - Nunca cria VPC, subnet ou regra de firewall compartilhada.
 *   - Firewall rule tag-based: aplica apenas à instância provisionada.
 *   - SSH key restrita à instância (block-project-ssh-keys = true).
 *   - Disco SSD de 20 GiB, deletado junto com a instância.
 */

terraform {
  required_version = ">= 1.5"

  # Backend local por VM (state isolado em states/<vm_id>.tfstate).
  # Phase 2e: migrar para GCS backend.
  backend "local" {}

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
  zone    = var.zone
}

# Ubuntu 20.04 LTS (ubuntu-os-cloud) — OS canônico dataforalltech
data "google_compute_image" "ubuntu_20_04" {
  family  = "ubuntu-2004-lts"
  project = "ubuntu-os-cloud"
}

# Regra de firewall tag-based: SSH restrito ao CIDR configurado.
# Um firewall rule por VM — escopo limitado via network tag.
resource "google_compute_firewall" "vm_ssh" {
  name    = "alloc-ssh-${substr(var.vm_id, 0, 8)}"
  network = var.network

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = [var.ssh_source_cidr]
  target_tags   = ["alloc-${substr(var.vm_id, 0, 8)}"]

  description = "SSH for allocator VM ${var.vm_id} (spec: ${var.spec}). Managed by infra-mcp-server."
}

# Compute Instance: e2-medium, Ubuntu 20.04 LTS
resource "google_compute_instance" "vm" {
  name         = "alloc-${substr(var.vm_id, 0, 8)}"
  machine_type = var.machine_type
  zone         = var.zone

  # Tag associa a regra de firewall ssh acima
  tags = ["alloc-${substr(var.vm_id, 0, 8)}"]

  boot_disk {
    initialize_params {
      image = data.google_compute_image.ubuntu_20_04.self_link
      size  = 20
      type  = "pd-ssd"
    }
    auto_delete = true
  }

  network_interface {
    network    = var.network
    subnetwork = var.subnetwork

    # IP externo (NAT) para endpoint SSH
    access_config {}
  }

  metadata = {
    # Formato GCP: "user:ssh-rsa AAAA..."
    ssh-keys               = "${var.ssh_user}:${var.ssh_public_key}"
    block-project-ssh-keys = "true"
    enable-oslogin         = "false"
  }

  labels = {
    managed_by   = "infra-mcp-allocator"
    spec         = var.spec
    # Labels GCP: apenas lowercase, números, hífens e underscores
    allocator_vm = substr(replace(var.vm_id, "-", "_"), 0, 32)
  }

  lifecycle {
    # SSH key pode mudar entre re-provisions sem forçar recreate
    ignore_changes = [metadata["ssh-keys"]]
  }
}
