project     = "dataforall"
environment = "prod"
region      = "sa-east-1"
azs         = ["sa-east-1a", "sa-east-1c"]
vpc_cidr    = "10.0.0.0/16"

# DNS / TLS (D6/D7) — zona de testes (dataforall.tech)
domain             = "dataforall.tech"
cloudflare_zone_id = "2a74d4c384c07781196ad2f84db55251"
cloudflare_proxied = true

# Compute — sem keypair (usar SSM Session Manager)
key_name            = null
app_instance_type   = "t3.large"
app_manager_count   = 3
app_node_count      = 2
vault_instance_type = "t3.small"

snapshot_retention_count = 14
