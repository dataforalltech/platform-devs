#!/bin/bash
while true; do
  DEVTEAM_NAME=$(basename $0 .sh)
  DEVTEAM_CMD="${DEVTEAM_NAME}-mcp-server"
  $DEVTEAM_CMD || true
  sleep 1
done
