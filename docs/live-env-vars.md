# Live session environment variables (`linto-live` chart)

Complete reference of the environment variables for the studio-plugins services
deployed by the `linto-live` chart: **Session API**, **Scheduler**, **Transcriber**,
**BotService**, **Translator** (and the one-shot **migration** job).

Canonical source of truth: `linto-studio-plugins/.envdefault` (+ `.envdefault.docker`).
Defaults below are the **image defaults**; the chart overrides the host/port/wiring
values at deploy time (see [How the chart wires env](#how-the-chart-wires-env)).
Variables added in the current `next` cycle are tagged **(next)**.

## How the chart wires env

| Mechanism | Where | Notes |
|---|---|---|
| Non-secret env | Per-service `ConfigMap` (`templates/configmap.yaml`), via `envFrom` | Literals in the template; hosts come from `_helpers.tpl` (`brokerHost`, `postgresHost`, `transcriberHost`) |
| Secrets | One `{release}-linto-live-secrets` Secret (`templates/secrets.yaml`), via `secretKeyRef` | `postgres-password` → `DB_PASSWORD`, `crypt-key` → `SECURITY_CRYPT_KEY` |
| Overrides | `values.yaml` (`botService.env`, `translator.env`, `sessionApi.env`, …) and CLI profile fields | A variable **absent from the ConfigMap keeps its image default** |

A variable can therefore be: set by the chart ConfigMap, injected from the Secret, or
left at its `.envdefault` value. The "Wired" column in the per-service section tells
which.

## Global / shared

Used by every Node service (loaded through `lib/config.js`).

| Variable | Default | Secret | Role |
|---|---|---|---|
| `NODE_ENV` | `production` | no | Selects the migration config |
| `TZ` | `UTC` | no | Process timezone |
| `LOG_FORMAT` | `text` | no | `text` or `json` |
| `LOG_LEVEL` | `debug` | no | `error` / `warn` / `info` / `debug` |

## Security (Session API + Transcriber)

| Variable | Default | Secret | Role |
|---|---|---|---|
| `SECURITY_CRYPT_KEY` | _(empty)_ | **yes** | Key encrypting sensitive data (ASR profile keys) at rest. **Must be identical** on Session API and Transcriber |
| `SECURITY_SALT_FILEPATH` | _(empty)_ | no | Optional salt file path; if set, must be readable by both services |

## Component registration (per service — "don't touch")

Comma-separated list of components loaded, in order.

| Variable | Default | Service |
|---|---|---|
| `TRANSCRIBER_COMPONENTS` | `BrokerClient,StreamingServer,Healthcheck` | Transcriber |
| `SCHEDULER_COMPONENTS` | `BrokerClient` | Scheduler |
| `SESSION_API_COMPONENTS` | `WebServer,BrokerClient` | Session API |
| `DELIVERY_COMPONENTS` | `BrokerClient,WebServer,IoHandler` | Delivery (not deployed by this chart) |
| `BOTSERVICE_COMPONENTS` **(next)** | `BrokerClient,Healthcheck` | BotService |

## BotService **(next)** — meeting bot

Headless Chromium joins Visio/Teams/Jitsi/BBB and streams PCM to the Transcriber.
The chart wires only the broker + healthcheck; the rest keeps its image default unless
overridden via `botService.env`. Sizing: [botservice-sizing.md](./botservice-sizing.md).

| Variable | Default | Secret | Role |
|---|---|---|---|
| `MAX_CONCURRENT_BOTS` | `10` | no | Max browser contexts (bots) per replica |
| `BOTSERVICE_HEALTHCHECK_HTTP` | `8080` | no | Liveness HTTP port (JSON status) |
| `EMPTY_MEETING_TIMEOUT_SECONDS` | `60` | no | Auto-leave after the last participant leaves |
| `BOT_DISPLAY_NAME` | `LinTO Bot` | no | Name shown when joining |
| `BOT_CAPABILITIES` | all (`jitsi,bigbluebutton,teams,visio`) | no | Providers advertised for Scheduler routing |
| `STREAMING_WS_BOT_HOST` | `transcriber` | no | Transcriber host the bot dials (also read by the Scheduler) |
| `JOIN_TIMEOUT_SECONDS` | `120` | no | Leave if no participant after join (watchdog) |
| `AUDIO_SILENCE_TIMEOUT_SECONDS` | `30` | no | Tear down if no PCM after admission (`0` disables) |
| `EARLY_AUDIO_MAX_AGE_SECONDS` | `30` | no | Max age of buffered early (SFU) audio before the reaper drops it |
| `TRANSCRIBER_ACK_TIMEOUT_SECONDS` | `10` | no | Wait for the Transcriber init `{type:ack}` |
| `BOTSERVICE_MAX_RSS_MB` | `2048` | no | RSS ceiling → advertise `capabilities=[]`, refuse bots (`0` disables) |
| `BOTSERVICE_WS_RECONNECT_RETRIES` | `3` | no | Max Transcriber WS reconnection attempts |
| `BOTSERVICE_WS_RECONNECT_BASE_MS` | `1000` | no | Base delay (ms) for the WS reconnection backoff |

The BotService docker entrypoint also honours `USER_ID` / `GROUP_ID` (runtime uid/gid,
default `33`) and `DEVELOPMENT` (skip chown on dev volume mounts).

## Audio streaming buffers (Transcriber)

| Variable | Default | Role |
|---|---|---|
| `MAX_AUDIO_BUFFER` | `10` | Seconds of audio kept to fast-forward on ASR reconnect |
| `MIN_AUDIO_BUFFER` | `200` | Send to ASR once the buffer is ≥ this many ms |
| `BYTES_PER_SAMPLE` | `2` | 1=8-bit, 2=16-bit, 4=32-bit |
| `SAMPLE_RATE` | `16000` | 8000 / 16000 / 32000 / 44100 / 48000 |
| `AUDIO_STORAGE_PATH` | `/audio-storage` | Channel audio files path (chart mounts `/session_audio`) |

## Inbound streaming (Transcriber listeners + URL building)

The Transcriber listens; the Session API and Scheduler build endpoint/proxy URLs.

| Variable | Default | Used by | Role |
|---|---|---|---|
| `STREAMING_HOST` | `0.0.0.0` | Transcriber | Listen address |
| `STREAMING_PROTOCOLS` | `SRT,RTMP,WS` | Transcriber | Enabled inbound protocols |
| `STREAMING_PASSPHRASE` | `A0123456789` | Transcriber / API | SRT passphrase (empty/`false`/≥10 chars) |
| `STREAMING_SRT_MODE` | `listener` | Transcriber | `listener` / `caller` / `rendezvous` |
| `STREAMING_SRT_UDP_PORT` | `8889` | Transcriber | SRT UDP port |
| `STREAMING_RTMP_TCP_PORT` | `1935` | Transcriber | RTMP TCP port |
| `STREAMING_WS_TCP_PORT` | `8080` | Transcriber / Scheduler **(next)** | WS port (also the bot ingest port the Scheduler mints) |
| `STREAMING_WS_ENDPOINT` | `transcriber-ws` | Transcriber / Scheduler **(next)** | WS path (also the bot ingest path) |
| `STREAMING_WS_SECURE` | `false` | Transcriber / API / Scheduler **(next)** | `wss` unless `false`; the Scheduler uses it for the bot URL scheme |
| `STREAMING_RTMP_SECURE` | `false` | Transcriber | `rtmps` unless `false` |
| `STREAMING_HEALTHCHECK_TCP` | `9999` | Transcriber | Healthcheck TCP port |
| `STREAMING_PROXY_SRT_HOST` | `false` | API | Public SRT host for built URLs (`false` disables) |
| `STREAMING_PROXY_RTMP_HOST` | `localhost` | API | Public RTMP host for built URLs |
| `STREAMING_PROXY_WS_HOST` | `localhost` | API | Public WS host for built URLs |
| `STREAMING_PROXY_SRT_UDP_PORT` | `8889` | API | Public SRT port |
| `STREAMING_PROXY_RTMP_TCP_PORT` | `1935` | API | Public RTMP port |
| `STREAMING_PROXY_WS_TCP_PORT` | `8080` | API | Public WS port |

> The chart points the Scheduler's `STREAMING_WS_BOT_HOST` / `_TCP_PORT` / `_ENDPOINT`
> / `_SECURE` at the in-cluster transcriber Service over plain `ws`
> (`{release}-linto-live-session-transcriber:8080/transcriber-ws`).

## Database (Session API, Scheduler, migration)

| Variable | Default | Secret | Role |
|---|---|---|---|
| `DB_HOST` | `localhost` | no | PostgreSQL host (chart: `{release}-postgres`) |
| `DB_PORT` | `5432` | no | PostgreSQL port |
| `DB_USER` | `postgres` | no | DB user (chart: `session_user`) |
| `DB_PASSWORD` | `secret` | **yes** | DB password (chart: from Secret `postgres-password`) |
| `DB_NAME` | `postgres` | no | DB name (chart: `session_DB`) |

## ASR (Transcriber) + stop draining

| Variable | Default | Role |
|---|---|---|
| `TRANSCRIBER_BOT_NAME` | `bot` | Speaker label for the bot's audio |
| `TRANSCRIBER_RESET_MESSAGE` | `"Channel reset."` | Message on channel reset |
| `ASR_STOP_FLUSH_TIMEOUT_MS` **(next)** | `3000` | Max wait for the ASR provider to flush pending finals at stop |
| `ASR_STOP_SETTLE_MS` **(next)** | `300` | Grace after flush for straggler SDK callbacks |
| `ASR_AVAILABLE_TRANSLATIONS_MICROSOFT` | `ar,eu,…,cy` | Discrete translation targets for Microsoft |
| `ASR_HAS_DIARIZATION_MICROSOFT` | `true` | Microsoft diarization capability |
| `ASR_AVAILABLE_TRANSLATIONS_AMAZON` | _(empty)_ | Amazon translation targets |
| `ASR_HAS_DIARIZATION_AMAZON` | `true` | Amazon diarization capability |
| `ASR_AVAILABLE_TRANSLATIONS_OPENAI_STREAMING` | _(empty)_ | OpenAI Streaming translation targets |
| `ASR_HAS_DIARIZATION_OPENAI_STREAMING` | `false` | OpenAI Streaming diarization capability |
| `ASR_AVAILABLE_TRANSLATIONS_VOXSTRAL` | _(empty)_ | Voxstral translation targets |
| `ASR_HAS_DIARIZATION_VOXSTRAL` | `false` | Voxstral diarization capability |
| `ASR_AVAILABLE_TRANSLATIONS_GOOGLE` **(next)** | _(unset)_ | Dynamic `ASR_AVAILABLE_TRANSLATIONS_<TYPE>` for the new Google ASR provider |
| `ASR_HAS_DIARIZATION_GOOGLE` **(next)** | _(unset)_ | Dynamic `ASR_HAS_DIARIZATION_<TYPE>` for the Google ASR provider |

> `ASR_AVAILABLE_TRANSLATIONS_<TYPE>` / `ASR_HAS_DIARIZATION_<TYPE>` are read
> dynamically per provider type. The Google provider reads its credentials from the
> transcriber-profile DB config (decrypted with `SECURITY_CRYPT_KEY`), **not** from an
> env var — no new `GOOGLE_*` secret.

`SESSION_STOP_FLUSH_TIMEOUT_MS` **(next)** (`10000`) belongs to the **Session API**:
max wait in `PUT /sessions/:id/stop?waitFinal=true` for every channel to deactivate
before reading captions as-is.

## MQTT broker (all services)

| Variable | Default | Secret | Role |
|---|---|---|---|
| `BROKER_HOST` | `localhost` | no | Broker host (chart: `{release}-broker`) |
| `BROKER_PORT` | `1883` | no | Broker port |
| `BROKER_USERNAME` | _(empty)_ | yes¹ | Auth username (empty = anonymous) |
| `BROKER_PASSWORD` | _(empty)_ | **yes**¹ | Auth password |
| `BROKER_KEEPALIVE` | `60` | no | MQTT keepalive (s) |
| `BROKER_PROTOCOL` | `mqtt` | no | `mqtt` or `mqtts` |
| `BROKER_USE_TLS` | `false` | no | Enable TLS (switches to `mqtts`) |
| `BROKER_CA_FILEPATH` | _(empty)_ | no | CA cert path (custom/self-signed) |
| `BROKER_CERT_FILEPATH` | _(empty)_ | no | Client cert path (mutual TLS) |
| `BROKER_KEY_FILEPATH` | _(empty)_ | yes¹ | Client private key path (mutual TLS) |
| `BROKER_REJECT_UNAUTHORIZED` | `true` | no | Reject untrusted broker certs (`false` for self-signed) |

¹ Empty by default — the chart's Mosquitto runs with no auth. No Secret key exists for
these today; if broker auth/mTLS is enabled later, follow the existing file-mount /
secret pattern (none is introduced for BotService).

## Session API

| Variable | Default | Role |
|---|---|---|
| `SESSION_API_HOST` | `http://localhost:8000` | Host used by the Swagger doc to call the API |
| `SESSION_API_WEBSERVER_HTTP_PORT` | `8000` | API HTTP port (chart: `80`) |

## Translator (chart values, not `.envdefault`)

The Python translator is configured from `values.translator.env`.

| Variable | Default (chart) | Role |
|---|---|---|
| `TRANSLATOR_NAME` | `gemma` | Translator registration name |
| `TRANSLATION_PROVIDER` | `translategemma` | Backend provider |
| `TRANSLATEGEMMA_ENDPOINT` | _(empty)_ | TranslateGemma endpoint |
| `TRANSLATEGEMMA_MODEL` | `Infomaniak-AI/vllm-translategemma-4b-it` | Model id |
| `PARTIAL_DEBOUNCE_MS` | `300` | Debounce for partial re-translation |

## Secrets

| Secret key | Injected as | Services | Default |
|---|---|---|---|
| `postgres-password` | `DB_PASSWORD` | session-api, scheduler, postgres (+ migration init) | `randAlphaNum 16` (or `postgres.password`) |
| `crypt-key` | `SECURITY_CRYPT_KEY` | session-api, transcriber | `randAlphaNum 32` (or `sessionApi.env.SECURITY_CRYPT_KEY`) |
