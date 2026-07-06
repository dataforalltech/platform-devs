# compute.tf — 1 EC2 rodando tudo (app + data + vault via docker compose) + EBS.

resource "aws_instance" "host" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.host.id]
  iam_instance_profile   = aws_iam_instance_profile.host.name

  metadata_options {
    http_tokens   = "required" # IMDSv2
    http_endpoint = "enabled"
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_gib
    encrypted   = true
    kms_key_id  = aws_kms_key.main.arn
  }

  # Instala Docker + cloudflared (conecta o tunnel com o token do SSM) e monta
  # o volume de dados. O deploy dos serviços (docker compose) é passo de bootstrap.
  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates curl gnupg awscli
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker

    # Swap (folga contra OOM: 29 serviços + stores + observabilidade em 16GB)
    if [ ! -f /swapfile ]; then
      fallocate -l 4G /swapfile
      chmod 600 /swapfile
      mkswap /swapfile
      swapon /swapfile
      echo '/swapfile none swap sw 0 0' >> /etc/fstab
      sysctl -w vm.swappiness=10
    fi

    # Volume de dados (Nitro: 2º volume aparece como /dev/nvme1n1)
    DEV=/dev/nvme1n1
    if ! blkid $DEV; then mkfs -t ext4 $DEV; fi
    mkdir -p /data
    echo "$DEV /data ext4 defaults,nofail 0 2" >> /etc/fstab
    mount -a || true

    # cloudflared conectado ao tunnel (token no SSM)
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
    dpkg -i /tmp/cloudflared.deb
    TOKEN=$(aws ssm get-parameter --name "${aws_ssm_parameter.tunnel_token.name}" --with-decryption --query Parameter.Value --output text --region ${var.region})
    cloudflared service install "$TOKEN"
  EOT

  tags = {
    Name      = "${local.name}-host"
    Component = "compute"
    Role      = "all-in-one"
    Tier      = "app+data"
  }
  depends_on = [aws_ssm_parameter.tunnel_token]
}

# ── Volume EBS dedicado de dados (bancos/volumes dos stores) ────────────────
resource "aws_ebs_volume" "data" {
  availability_zone = var.az
  size              = var.data_gib
  type              = "gp3"
  encrypted         = true
  kms_key_id        = aws_kms_key.main.arn
  tags = {
    Name      = "${local.name}-data-vol"
    Component = "data"
    Tier      = "data"
    Backup    = "true"
  }
}
resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.host.id
}

# ── DLM — snapshots automáticos do volume de dados ──────────────────────────
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
  description        = "${local.name} snapshots do volume de dados"
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
