# Visio native bot sizing

How the `visioBotService` resources of the `linto-live` chart were chosen, and how to
recompute them for another load or another node.

## What limits a replica

One replica runs every bot it is given in a single Python process. Each bot decodes the
participants' Opus audio and resamples it to 16 kHz in the LiveKit SDK's native threads.
It then mixes the audio and streams it to the Transcriber in Python. The Python part runs
on one core at a time (GIL). When that core is saturated, the mixer falls behind and the
Transcriber receives less audio than real time. Extra CPU does not help: the useful
CPU of a replica tops out at about 1.5 cores. More load needs more replicas. The Scheduler
sends each bot to the replica with the fewest active bots.

## Formulas

For one replica serving `M` meetings with `P` microphones in all (count muted ones too),
on a node whose core is `k` times slower than the reference core:

| Quantity | Formula |
|---|---|
| Real time holds while | `k × (P + 4 × M) <= 60` (saturation at 75) |
| CPU | `k × (30m × P + 50m × M)`, about 1.5 cores at the limit whatever `k` |
| Memory | `80Mi + 2.5Mi × P`, kept after the peak (Python does not return it) |

The formulas are envelopes of the measurements below, with `BOT_PERSTREAM=false` (the
chart default) and the bot subscribed to the microphones only (VisioBotService fix
"subscribe to the microphones only"). Before that fix every camera added about
2.2 Mbit/s, 45m of CPU and 9Mi. Per-stream mode was not measured.

`k` is measured with the reference loop, using the same Python as the image (3.12):

```bash
python3 -c "
import time
def f():
    s = 0
    for i in range(20_000_000): s += i & 7
t = time.perf_counter(); f(); print(round(time.perf_counter() - t, 2))"
```

`k` = the printed time / 0.43 (reference: a recent 5 GHz desktop core). A 2013 Xeon
at 2.7 GHz prints 1.43, so `k` = 3.3 there.

## Chart values

| Value | Setting | Why |
|---|---|---|
| `requests.cpu` | `1500m` | CPU of a replica at its real-time limit; a busy node cannot shrink it |
| `limits.cpu` | `2` | Above the 1.7 cores measured in overload, so throttling never bites first |
| `requests.memory` | `256Mi` | `P` = 70, more than any replica holds in real time (`P <= 56` for `k >= 1`) |
| `limits.memory` | `512Mi` | `P` = 170, margin for an overloaded replica |
| `replicas` | `1` | Raise it with the peak load, as below |

Replicas = `ceil(k × Σ(P_i + 4) / 60)` over the meetings transcribed at the peak.
For example, 6 meetings of 6 people on a node with `k` = 2 give
`2 × (36 + 24) / 60 = 2` replicas.

## Measurements

Bench:
- LiveKit server v1.13.11 in dev mode;
- participants published by `lk load-test` (Opus audio, simulcast cameras);
- a fake Transcriber that acknowledges and counts the audio;
- the bot image built from plugins `next` with the fix;
- 40 s windows, on the reference core;
- for memory, the RSS of a freshly started replica.

"Real time" is the audio delivered to the Transcriber divided by 32 kB/s per meeting.

| Meetings | Microphones | CPU (cores) | Python thread | RSS (MiB) | Real time |
|---|---|---|---|---|---|
| 0 | 0 | 0.00 | 0% | 65 | — |
| 1 | 1 | 0.04 | 2% | 82 | — |
| 1 | 4 | 0.11 | 5% | 81 | 1.00 |
| 1 | 8 | 0.21 | 10% | 84 | — |
| 1 | 15 | 0.45 | 20–26% | 84 | 0.98 |
| 5 | 20 | 0.83–0.89 | 48% | 89 | 1.00 |
| 5 | 50 | 1.42–1.47 | 77% | 151 | 0.97–1.00 |
| 10 | 40 | 1.41–1.43 | 78% | 128 | 0.94 |
| 12 | 48 | 1.45 | 79% | — | 0.84 |
| 15 | 60 | 1.49 | 77% | — | 0.71 |
| 20 | 80 | 1.57–1.60 (max 1.74) | 77% | 231 | 0.45 |

The real-time ratio follows `75 / (P + 4 × M)` once that load passes 75.

Cameras, before and after the microphone-only fix:

| Meetings × (microphones + cameras) | Before: CPU / RSS / received | After |
|---|---|---|
| 1 × (4 + 4) | 0.33 cores / 127 MiB / 8.9 Mbit/s | 0.09 / 81 / 0.2 |
| 1 × (15 + 15) | 1.22 cores / 223 MiB / 32.6 Mbit/s | 0.39 / 89 / 0.8 |
| 10 × (4 + 4) | 3.75 cores / 544 MiB / 89.5 Mbit/s | 1.42 / 160 / 2.2 |
