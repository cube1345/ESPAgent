# ESPAgent Roadmap

> ESPAgent is tracked as its own ESP32-S3 firmware project. This roadmap lists native ESPAgent capabilities, gaps, and implementation priorities without tying the project identity to any external codebase.
> Priority: P0 = core missing, P1 = important enhancement, P2 = nice to have.

---

## P0 — Core Agent Capabilities

### [x] ~~Tool Use Loop (multi-turn agent iteration)~~
- Implemented: `agent_loop.c` ReAct loop with `llm_chat_tools()`, max 10 iterations, non-streaming JSON parsing.

### [ ] Memory Write via Tool Use (agent-driven memory persistence)
- **Target**: The agent can persist important information into `MEMORY.md` and daily memory files through explicit tool calls.
- **Current**: `memory_write_long_term` and `memory_append_today` exist but are only called from CLI.
- **Scope**: Expose memory write/append tools through `tool_registry.c`; add prompt guidance on when to persist memory; optionally trigger memory flush when session history approaches `ESPAGENT_SESSION_MAX_MSGS`.
- **Depends on**: Tool Use Loop.

### [x] ~~Tool Registry + web_search Tool~~
- Implemented: `tools/tool_registry.c` — tool registration, JSON schema builder, dispatch by name.
- Implemented: `tools/tool_web_search.c` — Tavily/Brave Search API via HTTPS with direct and proxy modes.

### [ ] More Built-in Tools
- **Target**: Add a practical SPIFFS-oriented tool set for embedded use: `read_file`, `write_file`, `list_dir`, `message`, and `memory_write`.
- **Current**: Core registry exists; file tools are present but should be reviewed for prompt guidance and safety boundaries.
- **Recommendation**: Keep each tool narrow, bounded, and explicit about writable paths.

### [ ] Background Work / Long-running Tasks
- **Target**: Support background jobs that can run outside the immediate chat turn and inject results back into the message bus.
- **Current**: Dedicated cron, heartbeat, proactive, sensor monitor, and environment monitor tasks exist. `cron_add` supports recurring, one-shot, and daily jobs; `proactive_service` can periodically inject an internal self-check. There is still no fully generic arbitrary background job runner.
- **Recommendation**: Use one bounded FreeRTOS worker pattern before adding broader scheduling abstractions.

---

## P1 — Important Features

### [ ] Feishu User Allowlist
- **Target**: Restrict which Feishu users/chats may consume the agent and API credits.
- **Current**: No allowlist check in the Feishu inbound path.
- **Recommendation**: Store the allowlist in `espagent_secrets.h` or NVS, then filter before pushing messages into the inbound queue.

### [ ] Feishu Markdown to HTML Conversion
- **Target**: Send richer formatted Feishu replies without parse failures.
- **Current**: Reply formatting is intentionally simple; special characters can still require plain-text fallback.
- **Recommendation**: Implement a small Markdown-to-Feishu converter for code blocks, inline code, bold, lists, and links.

### [ ] Feishu /start Command
- **Target**: Handle `/start` locally with a short ESPAgent welcome/status message.
- **Current**: `/start` is treated as normal user text.
- **Recommendation**: Intercept it in `channels/feishu/feishu_bot.c` before enqueueing to the agent loop.

### [ ] Feishu Media Handling (photos/voice/files)
- **Target**: Handle image, voice, audio, and document messages.
- **Current**: Text messages are supported; media payloads are ignored.
- **Recommendation**: Start with image download and base64 forwarding to a vision-capable LLM; add voice transcription only after the HTTPS memory impact is measured.

### [ ] Skills System Expansion
- **Target**: SPIFFS skills can be always-loaded or loaded on demand, with concise metadata.
- **Current**: `skill_loader.c` builds a prompt summary from Markdown skill files.
- **Recommendation**: Add frontmatter parsing only if the current summary becomes too noisy.

### [ ] Bootstrap File Completion
- **Target**: Keep behavior guidelines, user preferences, tool notes, and identity data as explicit SPIFFS bootstrap files.
- **Current**: `SOUL.md` and `USER.md` are loaded; skills and memory are summarized separately.
- **Recommendation**: Add only the files that materially improve prompt quality, then cache their summaries.

### [ ] Longer Memory Lookback
- **Target**: Make daily memory lookback configurable.
- **Current**: `context_builder.c` uses a short lookback to control token and RAM pressure.
- **Recommendation**: Add a compile-time default and optional runtime setting, with a hard maximum.

### [x] ~~System Prompt Tool Guidance~~
- Implemented: `context_builder.c` includes tool usage guidance in the system prompt.

### [ ] Message Metadata
- **Target**: Carry media references, reply targets, and channel metadata through `espagent_msg_t`.
- **Current**: `espagent_msg_t` contains `channel`, `chat_id`, and `content`.
- **Recommendation**: Extend the struct carefully and audit every producer/consumer before changing ownership rules.

### [ ] Outbound Channel Registration
- **Target**: Let channels register outbound handlers instead of hardcoding every route in `espagent.c`.
- **Current**: Outbound dispatch uses a small if/else chain for Feishu, WebSocket, and system messages.
- **Recommendation**: Current code is simple and acceptable; defer until more channels exist.

---

## P2 — Advanced Features

### [x] ~~Cron Scheduled Task Service~~
- Implemented: `cron_service.c` persists jobs in `/spiffs/cron.json` and injects scheduled messages into the agent loop.
- Implemented: `cron_add` supports `schedule_type="every"`, `schedule_type="at"`, and `schedule_type="daily"` with local hour/minute.
- Remaining enhancement: full cron syntax is intentionally deferred; current simple schedule types are easier to validate on an MCU.

### [ ] Heartbeat Service
- **Target**: Periodically inspect heartbeat instructions and trigger the agent when work is pending.
- **Current**: Heartbeat service exists.
- **Recommendation**: Add better observability and storage guards before increasing frequency.

### [ ] Multi-LLM Provider Support
- **Target**: Support OpenAI-compatible APIs and a small provider selection layer.
- **Current**: `llm_proxy.c` supports Anthropic-style and OpenAI-compatible tool-use parsing, but provider selection/configuration remains intentionally small.
- **Recommendation**: Keep the current normalization layer until more provider-specific behavior is needed.

### [ ] Voice Transcription
- **Target**: Convert Feishu voice messages into text before entering the agent loop.
- **Current**: Not implemented.
- **Recommendation**: Measure heap/TLS impact for download plus transcription API before adding it to default builds.

### [x] ~~Build-time Config File + Runtime NVS Override~~
- Implemented: `espagent_secrets.h` as build-time defaults, NVS as runtime override via CLI.
- Two-layer config: build-time secrets -> NVS fallback, CLI commands to set/show/reset.

### [ ] WebSocket Gateway Protocol Enhancement
- **Target**: Add richer client protocol events such as streaming tokens and structured tool status.
- **Current**: Basic JSON request/reply protocol on port `18789`.
- **Recommendation**: Add versioned message types before introducing streaming.

### [ ] LingShu Agent Mesh Coordinator
- **Target**: Expand the current ESP32-S3 Edge Agent Node into a multi-node system with Coordinator Agent, Sensor Agent, Control Agent, Memory Agent, Communication Agent, and Display Agent.
- **Current**: Phase 1 is implemented in firmware: node identity and role profile exist, MQTT publishes state/telemetry/events under `espagent/nodes/<node_id>/...`, node/role command topics are subscribed for observability only, and four ESP32-S3 profiles are documented.
- **Recommendation**: Keep remote command execution disabled until command schema, authorization, audit events, and message_bus/tool_guard routing are implemented.

### [ ] Multi-Channel Manager
- **Target**: Centralize channel lifecycle if Feishu, WebSocket, serial, and future channels need common management.
- **Current**: Startup is orchestrated directly in `app_main()`.
- **Recommendation**: Defer until lifecycle duplication becomes real.

### [ ] Additional IM Channels
- **Target**: Add more user-facing channels only when there is a clear deployment need.
- **Current**: Feishu and WebSocket are the supported chat paths.
- **Recommendation**: Keep channel implementations isolated under `main/channels/`.

### [x] ~~Feishu Proxy Support (HTTP CONNECT)~~
- Implemented: HTTP CONNECT tunnel via `proxy/http_proxy.c`, configurable via `espagent_secrets.h` (`ESPAGENT_SECRET_PROXY_HOST`/`ESPAGENT_SECRET_PROXY_PORT`).

### [ ] Session Metadata Persistence
- **Target**: Store session metadata such as created/updated timestamps.
- **Current**: JSONL session files store role/content/ts records only. File names now use a stable FNV-1a hash of `chat_id`, with read/clear compatibility for safe legacy names.
- **Recommendation**: Low priority; add only if UI or maintenance tooling needs it.

---

## Completed ESPAgent Capabilities

- [x] Feishu WebSocket channel
- [x] Message Bus (inbound/outbound queues)
- [x] Agent Loop with ReAct tool use (multi-turn, max 10 iterations)
- [x] LLM API integration (Anthropic Messages API plus OpenAI-compatible tool-call parsing)
- [x] Tool Registry + web_search tool (Tavily/Brave Search API)
- [x] Structured Weather Tool (`get_weather` via Amap WebService, default Nanjing Qixia District)
- [x] Context Builder (system prompt + bootstrap files + memory + tool guidance)
- [x] Context Builder bounded append safety (prevents prompt offset overflow after truncation)
- [x] Memory Store (MEMORY.md + daily notes)
- [x] Session Manager (hashed JSONL file names, ring buffer history, legacy-safe read/clear)
- [x] Pending clarification carry-over (previous assistant question is injected as likely pending context)
- [x] Proactive Service (periodic internal checks, NVS target, `PROACTIVE_NO_MESSAGE` suppression)
- [x] Daily Cron Scheduling (hour/minute local-time jobs for reminders, weather, and check-ins)
- [x] LingShu Agent Mesh Phase 1 identity and MQTT observability topics
- [x] Four-ESP32 role profile configuration (`coordinator_agent`, `sensor_agent`, `control_agent`, `display_agent`)
- [x] WebSocket Gateway (port 18789, JSON protocol)
- [x] Serial CLI (esp_console, debug/maintenance commands)
- [x] HTTP CONNECT Proxy (Feishu + LLM API + search APIs via proxy tunnel)
- [x] OTA Update
- [x] WiFi Manager (build-time credentials, exponential backoff)
- [x] SPIFFS storage
- [x] Build-time config (`espagent_secrets.h`) + runtime NVS override via CLI

---

## Suggested Implementation Order

```text
1. [done] Tool Use Loop + Tool Registry + web_search
2. Memory Write via Tool Use
3. Built-in Tools (read_file, write_file, message)
4. Feishu Allowlist
5. Bootstrap File Completion
6. [partial] Background Work / Long-running Tasks
7. Feishu Markdown -> HTML
8. Media Handling
9. Heartbeat/proactive observability
10. Other enhancements
```
