#!/usr/bin/env bash
# build-service.sh <image> <repo> <branch> [context-subdir]
# Clona github.com/<org>/<repo> no <branch>, builda com o secret github_token
# (libs privadas) e faz push pro ACR como :latest + :<sha>. Roda na EC2 (BuildKit).
#
#   ./build-service.sh platform-auth      platform-auth release/1.4.0        # API (contexto raiz)
#   ./build-service.sh platform-auth-mcp  platform-auth release/1.4.0 mcp    # MCP (contexto mcp/)
set -uo pipefail
IMAGE="${1:?uso: build-service.sh <image> <repo> <branch> [dockerfile] [context]}"
REPO="${2:?repo}"
BRANCH="${3:?branch}"
DF="${4:-Dockerfile}"  # dockerfile relativo a raiz do repo (ex.: gateway_mcp/Dockerfile)
CTX="${5:-.}"          # contexto de build relativo a raiz (alguns MCP COPY da raiz, outros do subdir)
REGION=us-east-1; NAME=dataforall-hml; ACR=d4all.azurecr.io
ORG=$(aws ssm get-parameter --region $REGION --name /$NAME/github/org --query Parameter.Value --output text)
BUILDROOT=/data/build; mkdir -p "$BUILDROOT"

# token do GitHub (secret do build) em arquivo temporario
TF=$(mktemp); trap 'rm -f "$TF"' EXIT
aws ssm get-parameter --region $REGION --name /$NAME/github/token --with-decryption --query Parameter.Value --output text > "$TF"
GHTOK=$(cat "$TF")

# clona (token na URL — Basic auth p/ PAT classico; dir e transitorio na box privada)
D="$BUILDROOT/$REPO"
rm -rf "$D"
GIT_TERMINAL_PROMPT=0 git clone --depth 1 -b "$BRANCH" \
  "https://x-access-token:${GHTOK}@github.com/${ORG}/${REPO}.git" "$D" -q || { echo "FALHA clone $REPO@$BRANCH"; exit 1; }
git -C "$D" remote set-url origin "https://github.com/${ORG}/${REPO}.git" # tira o token do .git/config
SHA=$(git -C "$D" rev-parse --short HEAD)
echo "clonado $REPO@$BRANCH ($SHA); build contexto=$CTX"

# login ACR
ACR_USER=$(aws ssm get-parameter --region $REGION --name /$NAME/acr/username --query Parameter.Value --output text)
aws ssm get-parameter --region $REGION --name /$NAME/acr/password --with-decryption --query Parameter.Value --output text | docker login $ACR -u "$ACR_USER" --password-stdin >/dev/null

# build com BuildKit + secret, tags :latest e :<sha>
DOCKER_BUILDKIT=1 docker build --secret id=github_token,src="$TF" -f "$D/$DF" \
  -t "$ACR/dataforall/3.0/$IMAGE:latest" -t "$ACR/dataforall/3.0/$IMAGE:$SHA" \
  "$D/$CTX" || { echo "FALHA build $IMAGE"; exit 1; }

docker push "$ACR/dataforall/3.0/$IMAGE:latest" -q
docker push "$ACR/dataforall/3.0/$IMAGE:$SHA" -q
echo "PUSHED $IMAGE:latest (+$SHA)"
