#!/bin/bash
while true; do
  ZILLA_NAME=$(basename $0 .sh)
  ZILLA_CMD="${ZILLA_NAME}-mcp-server"
  $ZILLA_CMD || true
  sleep 1
done
