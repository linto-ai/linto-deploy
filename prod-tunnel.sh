sudo systemctl stop k3s
ssh -L 6443:127.0.0.1:6443 ubuntu@kube.linto.ai -N -f
uv sync
