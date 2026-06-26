# BotService sizing

How to size the meeting-bot service (`botService` in the `linto-live` chart) and
why it does **not** scale 1:1 with the Transcriber. Companion of the streaming
topology doc in `linto-studio-plugins/doc/production-topology.md`.

## The chain: one bot is one stream is one STT session

When a bot is started for a live meeting:

```
1 meeting = 1 channel = 1 bot = 1 outbound WebSocket = 1 Transcriber stream = 1 ASR/STT session
```

It is a 1:1 chain per concurrent meeting. A bot joins the meeting in a headless
Chromium, captures the audio, and streams PCM 16 kHz to a Transcriber over a single
WebSocket. The Scheduler mints that URL (`STREAMING_WS_BOT_HOST` / `_TCP_PORT` /
`_ENDPOINT` / `_SECURE`) and routes the bot to a replica by advertised capability and
load; the Transcriber instance is then chosen by the load balancer.

## Why botService replicas ≠ transcriber replicas

The two services are bounded on different axes, so matching their replica counts
wastes resources.

| Service | What bounds it | Sized for |
|---|---|---|
| **Transcriber** (4–6 replicas) | A relay/multiplexer: one instance serves many streams. For the **bot path (WS)** it is *light* — the bot already sends PCM, so there is **no GStreamer worker** (unlike SRT/RTMP). | Redundancy, transient overshoot, the SRT/RTMP protocol mix. |
| **BotService** (1+ replicas) | **Memory (Chromium)**. A replica hosts up to `MAX_CONCURRENT_BOTS` browser contexts, but `BOTSERVICE_MAX_RSS_MB` backpressure caps it sooner (it advertises `capabilities=[]` and refuses bots near the ceiling). | Peak concurrent bot meetings. |
| **STT** (GPU) | GPU throughput — one streaming ASR session per stream. | The real concurrency cap of the whole chain. |

A single Transcriber replica relays many bot streams, so there is no reason to run
one BotService per Transcriber. The true throughput ceiling is the **STT (GPU)**, not
the Transcriber or BotService.

## Capacity model

```
botService replicas = ceil( peak_concurrent_bot_meetings / effective_bots_per_replica )
```

`effective_bots_per_replica` is **memory-bound**, not the nominal `MAX_CONCURRENT_BOTS`:
with the default `BOTSERVICE_MAX_RSS_MB=2048` (2 Gi) and ~250–500 MB per Chromium
context, expect ~4–8 bots per replica before backpressure, well below the nominal 10.

Size Transcriber and STT so they can absorb the same peak number of concurrent
streams.

## Resource coherence (chart defaults)

The `botService` defaults in `charts/linto-live/values.yaml`:

| Knob | Default | Note |
|---|---|---|
| `replicas` | 1 | profile-driven via `bot_service_replicas` |
| `shmSize` | 1Gi | Chromium `/dev/shm` (in-memory `emptyDir`, **counts against the memory limit**; the default 64Mi crashes tabs) |
| `resources.limits.memory` | 4Gi | must exceed `shmSize` + `BOTSERVICE_MAX_RSS_MB` headroom |
| `resources.requests.cpu` | 500m | Chromium is CPU-spiky (WebRTC + audio mixing); no CPU limit (burstable, like the other services) |
| `resources.requests.memory` | 1Gi | |

These interlock: app RSS is capped at `BOTSERVICE_MAX_RSS_MB` (2 Gi) + `shmSize`
(1 Gi) ≈ 3 Gi, under the 4 Gi limit — so the in-app backpressure fires **before** the
OOM killer, with ~1 Gi of headroom.

## How to scale

- **More concurrent meetings → more replicas.** Set `bot_service_replicas` in the
  deploy profile (mirrors `session_transcriber_replicas`), then `linto deploy <profile>`.
  Defaults to 1; raise it for production resilience and load.
- **Higher density per replica → raise three knobs together.** `MAX_CONCURRENT_BOTS`
  (via `botService.env`), `resources.limits.memory`, and `shmSize` must grow in step,
  keeping `memory limit > BOTSERVICE_MAX_RSS_MB + shmSize`.
- **Enablement.** Part of the live stack: `botService.enabled` follows
  `live_session_enabled`, like the other live services. Ensure the profile's resolved
  `studio-plugins-botservice` tag points to a published image (the `next`→`main` merge
  and release build it with the same tag as the other studio-plugins).

Tunables (`MAX_CONCURRENT_BOTS`, `BOTSERVICE_MAX_RSS_MB`, join/silence/ack timeouts,
WS reconnect) keep their image defaults unless overridden through `botService.env`;
they are documented in `linto-studio-plugins/.envdefault`.
