# Acesso local aos bancos (ambiente enxuto) via SSM Port Forwarding

> Ambiente enxuto = **1 EC2** rodando app + data + Vault, **sem porta aberta na internet**
> (o Security Group nao tem ingress; a saida e so via Cloudflare Tunnel + SSM).
>
> Para conectar do seu IDE (DBeaver, DataGrip, psql, mysql, redis-cli) usamos
> **SSM Port Forwarding**: um tunel criptografado pelo agente SSM (trafego *outbound*
> da EC2), sem VPN nova e sem abrir nenhuma porta. No IDE voce conecta em
> **host = `localhost`**, a **porta encaminhada**, e **usuario/senha do banco**.

## Por que SSM (e nao abrir porta / VPN)

- **Zero exposicao:** nada publicado na internet; o SG continua 100% fechado.
- **Zero custo e zero infra nova:** o agente SSM ja esta na EC2 (instance profile
  com `AmazonSSMManagedInstanceCore`).
- **Auditavel:** toda sessao SSM fica registrada no CloudTrail / Session Manager.
- **Sem chave SSH:** acesso por identidade IAM.

## Pre-requisitos (uma vez por maquina)

1. **AWS CLI v2** — https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
2. **Session Manager plugin** — https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
   - Verifique: `session-manager-plugin` deve responder no PATH.
3. **Credenciais AWS ativas** apontando para a conta `011756140303`:
   - `aws sts get-caller-identity` tem que responder.
4. **Permissao IAM** para abrir a sessao (ver secao IAM abaixo).

## Portas dos bancos (host da EC2)

| Servico           | Porta (local = remota) | Engine        |
|-------------------|------------------------|---------------|
| `admin-mysql`     | **53306**              | MySQL 8.4 (registry ADMIN_DATAFORALL) |
| `tenant-mysql`    | **3306**               | MySQL 8.4 (dados de tenant) |
| `tenant-postgres` | **5432**               | Postgres 16 (dados de tenant) |
| `redis`           | **6379**               | Redis 7.4 |
| `vault`           | **8200**               | HashiCorp Vault (UI/API) |
| `grafana`         | **3000**               | Observabilidade |
| `prometheus`      | **9090**               | Observabilidade |

> O IDE sempre aponta para `localhost:<porta>`. A porta local e igual a remota
> para ficar previsivel.

## Uso rapido (script)

Do diretorio `terraform-lean/` (o script descobre a instancia via `terraform output`):

```powershell
# Abre TODOS os tuneis, cada um em sua janela:
./scripts/db-tunnel.ps1

# So um banco, na janela atual (bloqueia ate Ctrl-C):
./scripts/db-tunnel.ps1 -Service tenant-postgres -Foreground

# Alvo explicito (sem terraform):
./scripts/db-tunnel.ps1 -InstanceId i-002379444ffb89c10 -Region us-east-1
```

## Uso manual (sem script)

```bash
# tenant-postgres -> localhost:5432
aws ssm start-session \
  --target <INSTANCE_ID> --region us-east-1 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["5432"],"localPortNumber":["5432"]}'
```

Enquanto a sessao estiver aberta, no IDE:

| Campo   | Valor                          |
|---------|--------------------------------|
| Host    | `localhost` (ou `127.0.0.1`)   |
| Port    | `5432` (a que voce encaminhou) |
| User    | usuario do banco               |
| Password| senha do banco (no Vault)      |
| Database| o schema/banco alvo            |

Para encerrar: `Ctrl-C` na sessao (ou feche a janela).

## Permissao IAM para os devs

O **instance profile** da EC2 ja permite ser alvo de SSM. Falta **a identidade do dev**
poder abrir a sessao. Anexe esta policy ao usuario/role/grupo dos devs
(restrinja o `Resource` a instancia do enxuto):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StartPortForwardToLeanHost",
      "Effect": "Allow",
      "Action": ["ssm:StartSession"],
      "Resource": [
        "arn:aws:ec2:us-east-1:011756140303:instance/<INSTANCE_ID>",
        "arn:aws:ssm:*::document/AWS-StartPortForwardingSession"
      ]
    },
    {
      "Sid": "ManageOwnSession",
      "Effect": "Allow",
      "Action": ["ssm:TerminateSession", "ssm:ResumeSession"],
      "Resource": "arn:aws:ssm:*:*:session/${aws:username}-*"
    }
  ]
}
```

> Opcional: posso gerenciar essa policy + um grupo `dataforall-db-access` no Terraform
> (`terraform-lean`) para versionar quem tem acesso. Peça se quiser.

## Hardening aplicado

As portas dos bancos sao publicadas em **`127.0.0.1`** no host da EC2 (nao `0.0.0.0`).
Os apps continuam falando com os bancos pelo **nome do container** na rede docker
(`tenant-mysql:3306`, etc.), entao o bind em loopback nao quebra nada e some com
qualquer superficie mesmo dentro da VPC. O SSM encaminha para `localhost` da EC2,
entao o Port Forwarding funciona normalmente.

## Troubleshooting

- **`TargetNotConnected`**: o agente SSM ainda nao registrou (aguarde 1-2 min pos-boot)
  ou o instance profile nao tem `AmazonSSMManagedInstanceCore`. Cheque:
  `aws ssm describe-instance-information --region us-east-1`.
- **Conecta mas o banco recusa**: o container do banco ainda nao subiu, ou nao esta
  publicado em `127.0.0.1:<porta>`. Confira `docker ps` na EC2 (via
  `aws ssm start-session --target <id>`).
- **Porta local ocupada**: rode com outra `localPortNumber` (ex.: `15432`) e aponte
  o IDE para ela.
