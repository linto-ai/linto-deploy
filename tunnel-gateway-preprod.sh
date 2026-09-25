#!/usr/bin/env bash
# Tunnel for the preprod profile + port-forward to the STT API gateway
# Forwards local 6443 to the k3s API on preprod.linto.ai,
# then forwards local 9191 to the gateway pod (port 80)
sudo systemctl stop k3s
pkill -f 'ssh -L 6443:127.0.0.1:6443' 2>/dev/null
ssh -L 6443:127.0.0.1:6443 ubuntu@preprod.linto.ai -N -f
uv run linto port-forward preprod deployment/linto-stt-api-gateway 9191:80
