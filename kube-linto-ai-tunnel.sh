#!/usr/bin/env bash
# Tunnel for the kube-linto-ai profile (.linto/profiles/kube-linto-ai.json)
# Forwards local 6443 to the k3s API on kube.linto.ai
sudo systemctl stop k3s
pkill -f 'ssh -L 6443:127.0.0.1:6443' 2>/dev/null
ssh -L 6443:127.0.0.1:6443 ubuntu@kube.linto.ai -N -f
uv sync
