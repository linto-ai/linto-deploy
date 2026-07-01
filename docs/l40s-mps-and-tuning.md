# L40S (linto-gpu-2) — MPS GPU sharing + voxtral batching tuning

Operational trace for enabling **NVIDIA MPS** on the L40S node of the
kube-linto-ai cluster, and record of the **voxtral batching** change. Written to
be portable into the linto-deploy Ansible `gpu` role once validated.

Cluster: kube-linto-ai. Node: `linto-gpu-2` (L40S 48 GB, vRack 10.1.0.87 / WG
10.10.0.5, taint `linto.ai/dedicated=vllm-l40s:NoSchedule`, label
`linto.ai/gpu-role=vllm-l40s`). Only `linto-vllm-hc-voxtral` and
`linto-vllm-hc-translategemma` schedule there. Driver 595.71.05, CUDA 13.2.

Date: 2026-07-01. Status: **DONE + validated live**, and now **reconciled into
linto-deploy git** (profile + `linto-vllm-hc` chart + `gpu` Ansible role) so a full
`linto deploy` reproduces it instead of reverting to time-slicing — see §7.

---

## TL;DR result

Two independent problems starved voxtral on the L40S; both are fixed:

| Fix | Before | After |
|---|---|---|
| **batch** `--max-num-batched-tokens` 256 → **4096** | 0.45x real-time at 4+ streams (audio prefills serialized) | 7 streams real-time (voxtral alone) |
| **MPS** (voxtral+translategemma concurrent, not time-sliced) | with translation active: **0.49x** (drift) | **~0.95-1.0x** (holds) with 7 streams + 5 translations |

Measured on session with 7 SRT audio streams (5 with translation).

---

## 1. Why (the problem)

The L40S runs TWO vLLM processes sharing the GPU: `voxtral` (realtime ASR) and
`translategemma` (translation). Under default **time-slicing**, the two have
separate CUDA contexts and the GPU **alternates** between them (only one runs at a
time + context-switch overhead). Result: when translategemma was actively
translating (5 of 7 channels), voxtral dropped to ~**0.49x real-time** and
accumulated an unbounded backlog.

**MPS (Multi-Process Service)** merges the CUDA contexts into one server so
kernels from both processes run **concurrently** on different SMs — no
serialization, no per-context switch cost.

---

## 2. Voxtral batching change (separate root cause, applied first)

The L40S voxtral was deployed with `--max-num-batched-tokens 256` (copied from the
BM voxtral). 256 caps tokens per engine step, so concurrent realtime streams'
audio prefills **serialize** (each waits its turn) -> ~0.45x real-time at 4+
streams, GPU 95% util but only ~245 W (many small kernels, not dense compute).

- Changed to **4096** (16x). 7+ streams run real-time. Fits the 0.42 mem budget
  (activation ~4-6 GB). **8192 and 16384 OOM** the KV cache ("No available memory
  for the cache blocks") in the 0.42 budget — 4096 is the sweet spot.
- Applied live: `kubectl patch deploy/linto-vllm-hc-voxtral` on the args element
  (the standalone "256" after `--max-num-batched-tokens`).
- Persisted in chart: `charts/linto-vllm-hc/values.yaml` voxtral extraArgs
  256 -> 4096 (with comment). NOT yet in the profile.

---

## 3. Current device-plugin / GPU setup (what we found)

- Device plugin: `nvcr.io/nvidia/k8s-device-plugin:v0.17.0`, single DaemonSet
  `nvidia-device-plugin-daemonset` on all 5 GPU nodes, arg
  `--config-file=/etc/nvidia/config.yaml` (single config, no per-node selection,
  no config-manager, **no mps-control-daemon**).
- ConfigMap `kube-system/nvidia-device-plugin-config`: time-slicing, replicas 10,
  applied to ALL nodes.
- L40S node has NO `nvidia.com/device-plugin.config` label -> uses the default.
- L40S node has the MPS binaries (`/usr/bin/nvidia-cuda-mps-control`,
  `nvidia-cuda-mps-server`), driver 595, compute_mode **Default** (MPS OK),
  `sudo` nopasswd.

**Decision — node-level MPS (not device-plugin MPS).** The "official" device-plugin
MPS would require switching the SHARED daemonset to multi-config + config-manager
+ deploying the mps-control-daemon, which rolls across ALL prod GPU nodes. Too
risky. Instead we run MPS at the node level on the L40S only (host MPS daemon +
pod env/mount). Blast radius = the L40S + its 2 pods. Still Ansible-clean (systemd
unit + pod spec).

---

## 4. MPS enablement — the steps applied

### 4a. Host: MPS control daemon (systemd) on linto-gpu-2

`/etc/systemd/system/nvidia-mps.service`:

```ini
[Unit]
Description=NVIDIA CUDA MPS Control Daemon (L40S vllm sharing)
After=nvidia-persistenced.service

[Service]
Type=forking
Environment=CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
Environment=CUDA_MPS_LOG_DIRECTORY=/var/log/nvidia-mps
ExecStartPre=/usr/bin/mkdir -p /tmp/nvidia-mps /var/log/nvidia-mps
ExecStart=/usr/bin/nvidia-cuda-mps-control -d
ExecStop=/bin/sh -c 'echo quit | /usr/bin/nvidia-cuda-mps-control'
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now nvidia-mps.service
# verify: control responds
CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps bash -c 'echo get_default_active_thread_percentage | nvidia-cuda-mps-control'  # -> 100.0
```

Starting the daemon does NOT disturb already-running pods (they only use MPS if
`CUDA_MPS_PIPE_DIRECTORY` is set at process start).

### 4b. Pods: point voxtral + translategemma at the MPS daemon

For BOTH `linto-vllm-hc-voxtral` and `linto-vllm-hc-translategemma`, add to the
`vllm` container: env `CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps` + a hostPath mount
of the pipe dir. Applied live:

```bash
kubectl -n linto patch deployment <dep> --type=strategic -p '{
  "spec":{"template":{"spec":{
    "containers":[{"name":"vllm",
      "env":[{"name":"CUDA_MPS_PIPE_DIRECTORY","value":"/tmp/nvidia-mps"}],
      "volumeMounts":[{"name":"mps-pipe","mountPath":"/tmp/nvidia-mps"}]}],
    "volumes":[{"name":"mps-pipe","hostPath":{"path":"/tmp/nvidia-mps","type":"Directory"}}]
  }}}}'
```

Both pods restart and connect. They run as root in-container (UID 0 == host root),
which matches the MPS daemon user, so no UID/permission tweak needed.

---

## 5. Verification

- Host: a single `nvidia-cuda-mps-server` spawns and both vLLM EngineCore
  processes attach to it (one server, two clients = concurrent):
  ```
  57194  nvidia-cuda-mps-server        30 MiB
  57145  VLLM::EngineCore (voxtral)  ~18800 MiB
  58439  VLLM::EngineCore (transgm.) ~10-18 GB
  ```
  `echo get_server_list | CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps nvidia-cuda-mps-control` -> the server pid.
- Both pods `1/1 Ready`, restarts=0, no MPS/CUDA error in logs.
- Live load (7 SRT streams, 5 translating): voxtral advance rate **~0.94-1.01x
  real-time** (was 0.49x under time-slicing). All 7 channels emit finals steadily.
- L40S ~89% util, ~239 W, 49 C, ~43 GB mem (both models + MPS).

**Residual:** ~0.9x on some channels at peak (L40S near combined capacity). If
strict real-time is required, give voxtral an MPS compute priority:
set `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE` per client (e.g. voxtral 70 / translategemma 30)
via the pod env, or `set_active_thread_percentage <pid> <n>` on the control daemon.

---

## 6. Rollback

```bash
# pods back to time-slicing: remove the MPS env + mount (re-patch without them,
# or edit the deployments), pods restart.
# host: stop MPS
sudo systemctl disable --now nvidia-mps.service
```
No other state to undo. (The batch 4096 change is orthogonal; keep it.)

---

## 7. Reconciliation into linto-deploy git (DONE 2026-07-01)

All of the below is now committed, so `linto deploy` reproduces the live L40S
instead of reverting it. What was added:

- **gpu Ansible role:** `nvidia_mps_enabled` host var (default false; set true on
  `linto-gpu-2` in `inventory/ovh-production.yml`), a `nvidia-mps.service.j2`
  systemd template (content of §4a), and a guarded task that templates the unit +
  `enabled=yes state=started`. Time-sliced nodes are untouched (var is false).
  Also `nvidia_mps_pipe_dir` / `nvidia_mps_log_dir` defaults.
- **Chart (`charts/linto-vllm-hc`):** per-instance `mps: {enabled, pipeDir}` toggle.
  `deployment.yaml` renders `CUDA_MPS_PIPE_DIRECTORY` + a hostPath volume/mount of
  the pipe dir when enabled. Batch=4096 is in `values.yaml` (readable default).
- **Model + render:** `VllmInstance.mps_enabled` / `mps_pipe_dir`
  (`src/linto/model/profile.py`), mapped to chart `instances.<name>.mps` in
  `generate_vllm_hc_values` (`src/linto/backends/k3s.py`).
- **Profile `kube-linto-ai.json` `vllm_hc_instances`:** voxtral image pinned to
  `sha256:05da6a70…` (= live), batch `--max-num-batched-tokens 4096`,
  `mps_enabled: true`; translategemma `mps_enabled: true` (image stays
  `sha256:081b9c3f…`, = live). Verified: profile → `linto render` → `helm template`
  matches the running deployments.
- **Do NOT** convert the shared `nvidia-device-plugin` daemonset to device-plugin
  MPS on this cluster while other nodes must stay time-sliced, unless you move to
  per-node config-manager + mps-control-daemon (bigger change, all GPU nodes).
- **Still host-side only (host, not k8s):** the MPS daemon was set up live via
  ssh/systemd tonight; the Ansible task above will re-assert it idempotently the
  next time the gpu role runs against `linto-gpu-2`. Optional future knob:
  `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE` (voxtral 70 / translategemma 30) if strict
  real-time is needed at peak.
