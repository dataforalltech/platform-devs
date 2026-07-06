<#
.SYNOPSIS
  Abre tuneis SSM Port Forwarding para os bancos do ambiente enxuto (1 EC2).
  Nenhuma porta e aberta na internet: o trafego vai pelo agente SSM (outbound).
  No IDE (DBeaver/psql/mysql) voce conecta em host=localhost, porta encaminhada,
  usuario e senha do proprio banco.

.DESCRIPTION
  Usa o documento AWS-StartPortForwardingSession (encaminha localhost:<local>
  ate localhost:<remote> DENTRO da EC2, onde os containers publicam as portas).

.PREREQ
  - AWS CLI v2 e o "Session Manager plugin" instalados.
  - Credenciais AWS ativas (aws sts get-caller-identity) com permissao ssm:StartSession
    no alvo (ver docs/runbooks/local-db-access-ssm.md).

.EXAMPLE
  # Abre TODOS os bancos (cada um em sua janela):
  ./db-tunnel.ps1

.EXAMPLE
  # So o tenant-postgres, na janela atual (bloqueia ate Ctrl-C):
  ./db-tunnel.ps1 -Service tenant-postgres -Foreground

.EXAMPLE
  # Instancia/regiao explicitos (senao descobre via terraform output):
  ./db-tunnel.ps1 -InstanceId i-0123 -Region us-east-1
#>
[CmdletBinding()]
param(
  [ValidateSet('all','admin-mysql','tenant-mysql','tenant-postgres','redis','vault','grafana','prometheus')]
  [string]$Service = 'all',
  [string]$InstanceId,
  [string]$Region,
  [switch]$Foreground
)

$ErrorActionPreference = 'Stop'
$leanDir = Split-Path $PSScriptRoot -Parent   # .../terraform-lean

# porta local = porta remota (host da EC2), pra ficar previsivel no IDE.
$map = [ordered]@{
  'admin-mysql'     = 53306
  'tenant-mysql'    = 3306
  'tenant-postgres' = 5432
  'redis'           = 6379
  'vault'           = 8200
  'grafana'         = 3000
  'prometheus'      = 9090
}

if (-not $InstanceId) {
  Write-Host "Descobrindo instance_id via terraform output..." -ForegroundColor DarkGray
  $InstanceId = (& terraform -chdir="$leanDir" output -raw instance_id).Trim()
}
if (-not $Region) {
  try { $Region = (& terraform -chdir="$leanDir" output -raw region 2>$null).Trim() } catch {}
  if (-not $Region) { $Region = 'us-east-1' }
}
Write-Host "Alvo: $InstanceId  Regiao: $Region" -ForegroundColor Cyan

function Start-Tunnel([string]$name, [int]$port, [bool]$fg) {
  $params = "{`"portNumber`":[`"$port`"],`"localPortNumber`":[`"$port`"]}"
  $argList = @(
    'ssm','start-session',
    '--target', $InstanceId,
    '--region', $Region,
    '--document-name','AWS-StartPortForwardingSession',
    '--parameters', $params
  )
  if ($fg) {
    Write-Host "[$name] localhost:$port  (Ctrl-C para encerrar)" -ForegroundColor Green
    & aws @argList
  } else {
    # cada tunel em sua propria janela PowerShell (fecha com Ctrl-C ou fechando a janela)
    $inner = "Write-Host '[$name] localhost:$port -> EC2:$port  (Ctrl-C encerra)' -ForegroundColor Green; " +
             "aws $($argList -join ' ')"
    Start-Process powershell -ArgumentList '-NoExit','-Command', $inner | Out-Null
    Write-Host ("  {0,-16} localhost:{1}" -f $name, $port) -ForegroundColor Green
  }
}

if ($Service -eq 'all') {
  Write-Host "Abrindo tuneis (uma janela por banco):" -ForegroundColor Cyan
  foreach ($k in $map.Keys) { Start-Tunnel $k $map[$k] $false }
  Write-Host "`nConecte no IDE em host=localhost com as portas acima. Feche as janelas para encerrar." -ForegroundColor Yellow
} else {
  Start-Tunnel $Service $map[$Service] $Foreground.IsPresent
}
