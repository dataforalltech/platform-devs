/**
 * # Módulo AWS cpu-small — Phase 2d
 *
 * Provisiona EC2 t3.medium com Ubuntu 20.04 LTS em subnet pré-existente.
 * Ambiente alvo: DEV / HML.
 *
 * Variáveis obrigatórias (via TF_VAR_xxx no ambiente do processo allocator):
 *   TF_VAR_subnet_id      — ID da subnet pré-aprovada (ex: subnet-0abc1234)
 *   TF_VAR_vpc_id         — ID da VPC para o Security Group (ex: vpc-0abc1234)
 *   TF_VAR_ssh_public_key — chave pública Ed25519 gerada pelo allocator (Phase 2f)
 *
 * Autenticação AWS: via variáveis padrão da AWS CLI
 *   AWS_PROFILE, AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, etc.
 *
 * Output obrigatório lido pelo TerraformProvisioner: vm_ssh_endpoint (host:port).
 *
 * Hard stops do módulo:
 *   - Nunca cria VPC, subnet ou Internet Gateway.
 *   - Security Group restringe SSH ao CIDR configurado em TF_VAR_ssh_source_cidr.
 *   - EBS sempre criptografado (gp3, 20 GiB).
 *   - delete_on_termination = true — sem volumes órfãos.
 */

terraform {
  required_version = ">= 1.5"

  # Backend local por VM (state isolado em states/<vm_id>.tfstate).
  # Phase 2e: migrar para S3 backend com DynamoDB lock.
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

# Ubuntu 20.04 LTS (Canonical) — OS canônico dataforalltech
data "aws_ami" "ubuntu_20_04" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

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

# Security Group dedicado: SSH restrito ao CIDR configurado.
# Um SG por VM — destruído junto com a VM no terraform destroy (Phase 2e).
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

# Key Pair por VM: gerado pelo allocator (Phase 2f), destruído junto com a VM.
resource "aws_key_pair" "vm" {
  key_name   = "infra-alloc-${var.vm_id}"
  public_key = var.ssh_public_key

  tags = {
    ManagedBy   = "infra-mcp-allocator"
    AllocatorVM = var.vm_id
  }
}

# EC2 Instance: t3.medium, Ubuntu 20.04 LTS
resource "aws_instance" "vm" {
  ami                         = data.aws_ami.ubuntu_20_04.id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  key_name                    = aws_key_pair.vm.key_name
  vpc_security_group_ids      = [aws_security_group.vm_ssh.id]
  associate_public_ip_address = var.associate_public_ip_address

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 20
    delete_on_termination = true
    encrypted             = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 obrigatório (hardening)
  }

  tags = {
    Name        = "infra-alloc-${var.vm_id}"
    ManagedBy   = "infra-mcp-allocator"
    Spec        = var.spec
    AllocatorVM = var.vm_id
  }
}
