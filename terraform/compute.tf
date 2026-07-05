# compute.tf — app tier (Swarm), data tier (EC2 dedicada + EBS) e Vault.

locals {
  private_subnet_ids = [for s in aws_subnet.private : s.id]

  # cloud-init base: instala Docker + exige IMDSv2 já vem do metadata_options.
  docker_userdata = <<-EOT
    #!/bin/bash
    set -euo pipefail
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin awscli
    systemctl enable --now docker
  EOT
}

# ── APP TIER — nós do Swarm (escala estática — D4) ──────────────────────────
# Bootstrap do Swarm (init/join) fica como passo operacional documentado no
# README (troca de token). Estes nós já vêm com Docker instalado.

resource "aws_instance" "app_manager" {
  count                  = var.app_manager_count
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.app_instance_type
  subnet_id              = local.private_subnet_ids[count.index % length(local.private_subnet_ids)]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name
  key_name               = var.key_name
  user_data              = local.docker_userdata

  metadata_options {
    http_tokens   = "required" # IMDSv2
    http_endpoint = "enabled"
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = 40
    encrypted   = true
    kms_key_id  = aws_kms_key.main.arn
  }
  tags = { Name = "${local.name}-swarm-manager-${count.index}", Role = "swarm-manager", Tier = "app" }
}

resource "aws_instance" "app_worker" {
  count                  = var.app_node_count
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.app_instance_type
  subnet_id              = local.private_subnet_ids[count.index % length(local.private_subnet_ids)]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name
  key_name               = var.key_name
  user_data              = local.docker_userdata

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = 40
    encrypted   = true
    kms_key_id  = aws_kms_key.main.arn
  }
  tags = { Name = "${local.name}-swarm-worker-${count.index}", Role = "swarm-worker", Tier = "app" }
}

# ── DATA TIER — EC2 dedicada por store + volume EBS gp3 (D1 / hardening §5) ──
resource "aws_instance" "data" {
  for_each               = var.data_nodes
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = each.value.instance_type
  subnet_id              = local.private_subnet_ids[0] # fixe a AZ do store; réplica na outra AZ
  vpc_security_group_ids = [aws_security_group.data.id]
  iam_instance_profile   = aws_iam_instance_profile.data.name
  key_name               = var.key_name
  user_data              = local.docker_userdata

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
    kms_key_id  = aws_kms_key.main.arn
  }
  tags = { Name = "${local.name}-data-${each.key}", Role = each.key, Tier = "data" }
}

# Volume EBS dedicado de dados (separado do root) — recebe snapshots do DLM.
resource "aws_ebs_volume" "data" {
  for_each          = var.data_nodes
  availability_zone = aws_instance.data[each.key].availability_zone
  size              = each.value.data_gib
  type              = "gp3"
  encrypted         = true
  kms_key_id        = aws_kms_key.main.arn
  tags              = { Name = "${local.name}-data-${each.key}-vol", Backup = "true", Tier = "data" }
}

resource "aws_volume_attachment" "data" {
  for_each    = var.data_nodes
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data[each.key].id
  instance_id = aws_instance.data[each.key].id
}

# ── VAULT — instância dedicada ──────────────────────────────────────────────
resource "aws_instance" "vault" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.vault_instance_type
  subnet_id              = local.private_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.vault.id]
  iam_instance_profile   = aws_iam_instance_profile.vault.name
  key_name               = var.key_name
  user_data              = local.docker_userdata

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
    kms_key_id  = aws_kms_key.main.arn
  }
  tags = { Name = "${local.name}-vault", Role = "vault", Tier = "data" }
}

# ── DLM — snapshots automáticos dos volumes de dados (Backup=true) ──────────
data "aws_iam_policy_document" "dlm_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "dlm" {
  name               = "${local.name}-dlm"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json
}
resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "data" {
  description        = "${local.name} — snapshots do data tier"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    target_tags    = { Backup = "true" }

    schedule {
      name = "diario"
      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]
      }
      retain_rule { count = var.snapshot_retention_count }
      copy_tags = true
    }
  }
}
