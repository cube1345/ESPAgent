# ESPAgent

ESPAgent is an ESP32-S3 firmware project that runs a lightweight AI agent directly on ESP-IDF and FreeRTOS. It connects messaging channels, local WebSocket access, persistent SPIFFS memory, LLM tool use, and hardware-control tools into one embedded agent runtime.

The project is maintained as ESPAgent. Public documentation, runtime logs, generated binaries, and directory structure should use the ESPAgent name consistently.

## Capabilities

- ESP32-S3 firmware built with ESP-IDF 6.1
- Feishu/Lark WebSocket channel for chat input and replies
- Local WebSocket gateway on port `18789`
- Serial CLI for diagnostics and local maintenance
- ReAct-style agent loop with LLM tool use
- SPIFFS-backed memory, sessions, skills, and config files
- Hardware tools for GPIO, WS2812, servo, MAX98357, AHT10/AHT20, SGP30, BH1750/GY-30, HC-SR05, and environment readings
- ESP-NOW environment telemetry sender
- Wi-Fi onboarding/admin AP under the `ESPAgent-XXXX` network name

## Repository Layout

```text
ESPAgent/
├── main/                       ESP-IDF application component
│   ├── espagent.c              app_main() banner and startup phase calls
│   ├── espagent_config.h       compile-time project constants
│   ├── espagent_secrets.h.example
│   │                           build-time credentials template
│   ├── app/                    application startup and service orchestration
│   ├── agent/                  agent loop and system prompt construction
│   ├── bus/                    FreeRTOS inbound/outbound message queues
│   ├── cache/                  local runtime cache for prompt fragments
│   ├── channels/feishu/        Feishu/Lark WebSocket channel
│   ├── cli/                    USB serial CLI
│   ├── cron/                   scheduled agent trigger service
│   ├── drivers/                sensor and peripheral drivers
│   ├── espnow/                 ESP-NOW telemetry sender
│   ├── gateway/                local WebSocket chat gateway
│   ├── heartbeat/              heartbeat-driven background checks
│   ├── llm/                    HTTPS LLM provider client and tool-use parser
│   ├── memory/                 long-term memory and per-chat JSONL sessions
│   ├── onboard/                Wi-Fi onboarding/admin portal
│   ├── ota/                    HTTPS OTA update support
│   ├── proxy/                  HTTP CONNECT proxy support
│   ├── sensors/                periodic sensor publishing integrations
│   ├── skills/                 SPIFFS skill summary loader
│   └── tools/                  AI-callable tool registry and tool handlers
├── spiffs_data/                files bundled into the SPIFFS partition
│   ├── config/                 SOUL.md and USER.md bootstrap files
│   ├── memory/                 MEMORY.md and daily notes
│   └── skills/                 markdown skills loaded at runtime
├── docs/                       architecture, setup, and integration notes
├── skills/deploy/              local deployment helper skill and scripts
├── scripts/                    host setup/build helper scripts
├── partitions.csv              flash partition table
├── sdkconfig.defaults          shared ESP-IDF defaults
└── sdkconfig.defaults.esp32s3  ESP32-S3-specific defaults
```

## Build

Load the ESP-IDF environment, then build:

```bash
idf.py build
```

The default firmware artifact is:

```text
build/ESPAgent.bin
```

Flash with:

```bash
idf.py -p /dev/ttyUSB0 flash monitor
```

## Configuration

Copy the secrets template when build-time credentials are needed:

```bash
cp main/espagent_secrets.h.example main/espagent_secrets.h
```

Credentials can also be set through the serial CLI and stored in NVS. The local setup portal appears as an `ESPAgent-XXXX` Wi-Fi network when onboarding/admin AP mode is active.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Feishu setup](docs/im-integration/FEISHU_SETUP.md)
- [Wi-Fi onboarding AP](docs/WIFI_ONBOARDING_AP.md)
- [Tavily setup](docs/tool-setup/TAVILY_SETUP.md)
- [Roadmap](docs/TODO.md)
