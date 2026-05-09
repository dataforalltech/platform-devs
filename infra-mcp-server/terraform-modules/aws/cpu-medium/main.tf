/**
 * # Módulo AWS cpu-medium — Phase 2d
 *
 * Provisiona EC2 t3.xlarge com Ubuntu 20.04 LTS em subnet pré-existente.
 * Ambiente alvo: DEV / HML (cargas mais pesadas que cpu-small).
 *
 * Variáveis obrigatórias (via TF_VAR_xxx):
 *   TF_VAR_subnet_id, TF_VAR_vpc_id, TF_VAR_ssh_public_key
 *
 * Idêntico ao módulo cpu-small; apenas instance_type padrão difere.
 * Ver cpu-small/main.tf para comentários detalhados.
 */

terraform {
  required_version = ">= 1.5"
  backend "local" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_ami" "ubuntu_20_04" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_security_group" "vm_ssh" {
  name        = "infra-alloc-${var.vm_id}"
  description = "SSH for allocator VM ${var.vm_id} (spec: ${var.spec}). Managed by infra-mcp-server."
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_source_cidr]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "infra-alloc-${var.vm_id}"
    ManagedBy   = "infra-mcp-allocator"
    Spec        = var.spec
    AllocatorVM = var.vm_id
  }
}

resource "aws_key_pair" "vm" {
  key_name   = "infra-alloc-${var.vm_id}"
  public_key = var.ssh_public_key

  tags = {
    ManagedBy   = "infra-mcp-allocator"
    AllocatorVM = var.vm_id
  }
}

resource "aws_instance" "vm" {
  ami                         = data.aws_ami.ubuntu_20_04.id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  key_name                    = aws_key_pair.vm.key_name
  vpc_security_group_ids      = [aws_security_group.vm_ssh.id]
  associate_public_ip_address = var.associate_public_ip_address

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    delete_on_termination = true
    encrypted             = true
  }

  metadata_options {
    http_tokens = "required"
  }

  tags = {
    Name        = "infra-alloc-${var.vm_id}"
    ManagedBy   = "infra-mcp-allocator"
    Spec        = var.spec
    AllocatorVM = var.vm_id
  }
}
