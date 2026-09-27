"""ensure_gpu_workers_recreate: GPU Deployments left in RollingUpdate are switched before helm."""

import json
from types import SimpleNamespace

import linto.backends.k3s as k3s


def deployment(name, strategy, gpu):
    limits = {"nvidia.com/gpu": 1} if gpu else {}
    return {
        "metadata": {"name": name},
        "spec": {
            "strategy": strategy,
            "template": {"spec": {"containers": [{"name": "c", "resources": {"limits": limits}}]}},
        },
    }


def test_only_gpu_deployments_in_rolling_update_are_patched(monkeypatch):
    items = [
        deployment("stt-whisper-workers-gpu-0", {"type": "RollingUpdate", "rollingUpdate": {"maxSurge": "25%"}}, True),
        deployment("stt-diarization-gpu-0", {"type": "Recreate"}, True),
        deployment("studio-api", {"type": "RollingUpdate"}, False),
        deployment("vllm", {}, True),  # no strategy field: RollingUpdate by default
    ]
    calls = []

    def run_cmd(cmd, check=True, **kw):
        calls.append(cmd)
        if cmd[:3] == ["kubectl", "get", "deploy"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"items": items}))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(k3s, "run_cmd", run_cmd)
    assert k3s.ensure_gpu_workers_recreate("linto") == ["stt-whisper-workers-gpu-0", "vllm"]
    patches = [c for c in calls if c[:2] == ["kubectl", "patch"]]
    assert json.loads(patches[0][-1]) == {"spec": {"strategy": {"type": "Recreate", "rollingUpdate": None}}}


def test_cluster_unreachable_is_not_fatal(monkeypatch):
    monkeypatch.setattr(k3s, "run_cmd", lambda cmd, check=True, **kw: SimpleNamespace(returncode=1, stdout=""))
    assert k3s.ensure_gpu_workers_recreate("linto") == []
