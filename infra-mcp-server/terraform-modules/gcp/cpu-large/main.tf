/**
 * # Módulo GCP cpu-large — Phase 2e
 *
 * Provisiona e2-standard-8 com Ubuntu 20.04 LTS em subnet pré-existente.
 * Ambiente alvo: testes pontuais na GCP (cargas intensas).
 *
 * Variáveis obrigatórias (via TF_VAR_xxx):
 *   TF_VAR_project, TF_VAR_network, TF_VAR_subnetwork,
 *   TF_VAR_ssh_user, TF_VAR_ssh_public_key
 *
 * Idêntico ao gcp/cpu-small; apenas machine_type e disk_size diferem.
 */

terraform {
  required_version = ">= 1.5"
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

data "google_compute_image" "ubuntu_20_04" {
  family  = "ubuntu-2004-lts"
  project = "ubuntu-os-cloud"
}

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

resource "google_compute_instance" "vm" {
  name         = "alloc-${substr(var.vm_id, 0, 8)}"
  machine_type = var.machine_type
  zone         = var.zone

  tags = ["alloc-${substr(var.vm_id, 0, 8)}"]

  boot_disk {
    initialize_params {
      image = data.google_compute_image.ubuntu_20_04.self_link
      size  = 50
      type  = "pd-ssd"
    }
    auto_delete = true
  }

  network_interface {
    network    = var.network
    subnetwork = var.subnetwork

    access_config {}
  }

  metadata = {
    ssh-keys               = "${var.ssh_user}:${var.ssh_public_key}"
    block-project-ssh-keys = "true"
    enable-oslogin         = "false"
  }

  labels = {
    managed_by   = "infra-mcp-allocator"
    spec         = var.spec
    allocator_vm = substr(replace(var.vm_id, "-", "_"), 0, 32)
  }

  lifecycle {
    ignore_changes = [metadata["ssh-keys"]]
  }
}
