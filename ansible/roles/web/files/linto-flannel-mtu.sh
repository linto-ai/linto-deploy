#!/bin/bash
# Pin the flannel VXLAN MTU to the WireGuard overlay path so large inter-node
# UDP (notably SRT) is not silently dropped.
#
# k3s derives flannel.1 MTU from the flannel-iface (iface_mtu - 50). On spoke
# nodes the flannel-iface is wg0 (1420 -> flannel.1 1370), which is correct. On
# the master the flannel-iface is ens7 (1500 -> flannel.1 1450) for VTEP/FDB
# reasons, while the real VXLAN egress to the spokes is over wg0. The resulting
# 1450-vs-1370 divergence drops large inter-node UDP packets (~10 min SRT flap)
# and is re-created on every k3s restart / reboot.
#
# Target = wg0 MTU - 50 (VXLAN overhead), derived live so it tracks any wg0
# retune. Idempotent: flannel.1 is only touched when its MTU differs.
# Managed by Ansible (web role, flannel_mtu_enforce).
set -eu
OVERHEAD=50
FALLBACK="${1:-1370}"

if ip link show wg0 >/dev/null 2>&1; then
    target=$(( $(cat /sys/class/net/wg0/mtu) - OVERHEAD ))
else
    target="$FALLBACK"
fi

# flannel.1 may not exist yet right after a k3s (re)start; wait for it.
for _ in $(seq 1 60); do
    if ip link show flannel.1 >/dev/null 2>&1; then
        cur=$(cat /sys/class/net/flannel.1/mtu)
        if [ "$cur" != "$target" ]; then
            ip link set flannel.1 mtu "$target"
            logger -t linto-flannel-mtu "flannel.1 MTU ${cur} -> ${target} (wg0-derived)"
        fi
        exit 0
    fi
    sleep 2
done
logger -t linto-flannel-mtu "flannel.1 not present after 120s; nothing to do"
exit 0
