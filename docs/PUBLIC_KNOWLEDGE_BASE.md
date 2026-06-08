# ESPAgent Public Knowledge Base

本文是 ESPAgent 项目的公共知识库，面向后续开发者和 AI 协作者。它汇总项目定位、总体架构、文件分工、当前功能、细节边界、进度和未来规划。

`public_knowledge.md` 继续作为工作协议和进度日志入口；本文作为更完整的项目认知总览。

## 项目定位

ESPAgent 是运行在 ESP32-S3 上的轻量 AI Agent 固件。它不是 Linux 多进程框架，而是基于 ESP-IDF 和 FreeRTOS 的 MCU 程序。

公开 GitHub 仓库：

- HTTPS: `https://github.com/cube1345/ESPAgent.git`
- SSH: `git@github.com:cube1345/ESPAgent.git`

当前固件能力可以概括为：

- 通过 Feishu / WebSocket / Serial CLI 接收人类输入。
- 使用 LLM tool calling 理解任务和选择工具。
- 通过 `tool_registry` 执行真实硬件、文件、天气、搜索、定时任务等工具。
- 使用 SPIFFS 保存记忆、会话、skills 和 cron 配置。
- 使用 MQTT / ESP-NOW / WebSocket 作为后续多节点协作链路。
- 以 ESP32-S3 Edge Agent Node 身份接入规划中的 LingShu Agent Mesh。

当前必须清楚区分两层：

- 当前已实现：单 ESP32-S3 上的轻量 Agent runtime，一个 `agent_loop` 串行处理所有 LLM 回合。
- 规划中：多个 ESP32-S3 节点 + ESP32-P4/Android 终端 + 云端 Coordinator/MCP 的多 Agent 协作系统。

## 核心链路

```text
Feishu / WebSocket / Cron / Proactive / CLI Inject
        |
        v
message_bus inbound queue
        |
        v
agent_loop
        |
        v
context_builder + session history + memory + skills
        |
        v
LLM provider API
        |
        v
tool_use?
        |
        v
tool_registry
        |
        v
GPIO / RGB / Servo / Sensors / Files / Weather / Search / Cron
        |
        v
message_bus outbound queue
        |
        v
Feishu / WebSocket reply
```

关键边界：

- 通道只负责收发消息，不直接碰硬件。
- `agent_loop` 决定是否调用工具。
- 工具是 C 函数，LLM 只能通过注册过的 JSON schema 调用。
- 硬件动作必须经过工具实现和 tool guard。
- cron/proactive 只是注入消息，不是独立 LLM Agent。

## 当前 Agent Mesh 状态

当前固件已经支持 ESP32-S3 作为 LingShu Agent Mesh 的 Edge Agent Node：

- `ESPAGENT_NODE_ID`
- `ESPAGENT_NODE_ROLE`
- `ESPAGENT_NODE_LOCATION`
- `ESPAGENT_NODE_CAPABILITIES`
- `ESPAGENT_NODE_RESPONSIBILITIES`
- `ESPAGENT_MESH_TOPIC_PREFIX`

四块 ESP32-S3 可以使用同一套固件，通过 `espagent_secrets.h` 设置不同 profile：

```text
esp32s3-coordinator-01  coordinator_agent  coordinator,communication,llm,dispatch,timeline,alerts
esp32s3-sensor-01       sensor_agent       sensor,telemetry,environment,air_quality,light,presence
esp32s3-control-01      control_agent      control,gpio,rgb,servo,relay,actuator
esp32s3-display-01      display_agent      display,timeline,alerts,state,watchdog
```

MQTT Mesh topic：

```text
espagent/nodes/<node_id>/state
espagent/nodes/<node_id>/telemetry
espagent/nodes/<node_id>/events
espagent/nodes/<node_id>/command
espagent/roles/<role>/command
espagent/agent/dispatch
espagent/agent/timeline
espagent/alerts
```

当前 MQTT command / dispatch 仍然只记录日志，不直接执行硬件动作。真正执行前必须补 command schema、鉴权、审计、message_bus 转发和 tool_guard。

## 四节点资源压榨与代码设计

四块 ESP32-S3 不建议拆成四个互不相干的工程。推荐保持同一仓库、同一公共 runtime，再按 role 编译/配置出不同节点：

```text
common runtime + mesh protocol + role-specific service
```

代码层应逐步演进为：

```text
main/
├── mesh/
│   ├── mesh_protocol.c/.h     MQTT/ESP-NOW payload schema、topic builder、JSON encode/decode
│   ├── mesh_mqtt.c/.h         通用 MQTT transport、订阅、发布、重连
│   └── mesh_types.h           node_state、telemetry、command、result、timeline 类型
├── roles/
│   ├── role_config.h          基于 node_profile 的 role/capability 判断
│   ├── coordinator_node.c/.h  LLM、Feishu/WebSocket、dispatch、timeline
│   ├── sensor_node.c/.h       多传感器采样、滤波、缓存、告警、遥测
│   ├── control_node.c/.h      执行器队列、安全互锁、状态机、结果事件
│   └── display_node.c/.h      timeline/state/alerts 订阅与本地展示
├── sensors/
│   ├── sensor_sampler.c/.h    周期采样和驱动调度
│   ├── sensor_cache.c/.h      短期快照、统计、阈值判断
│   └── sensor_analyzer.c/.h   环境状态分析和异常事件
├── control/
│   ├── actuator_registry.c/.h 执行器能力表
│   ├── command_queue.c/.h     远程命令排队、去重、TTL
│   ├── safety_interlock.c/.h  危险动作确认、限流、互锁
│   └── actuator_state.c/.h    执行器当前状态和审计
└── display/
    ├── display_state.c/.h     节点状态聚合
    ├── timeline_store.c/.h    调度时间线缓存
    └── display_service.c/.h   屏幕/串口/状态灯展示
```

启动结构建议保持公共初始化和角色启动分离：

```c
common_init();

if (role_is_coordinator()) coordinator_node_init();
if (role_is_sensor()) sensor_node_init();
if (role_is_control()) control_node_init();
if (role_is_display()) display_node_init();

common_start();

if (role_is_coordinator()) coordinator_node_start();
if (role_is_sensor()) sensor_node_start();
if (role_is_control()) control_node_start();
if (role_is_display()) display_node_start();
```

每个节点的资源使用方向：

| 节点 | 主要吃满的资源 | 设计重点 |
|------|----------------|----------|
| Coordinator | Wi-Fi/HTTPS、TLS buffer、LLM JSON、PSRAM、会话上下文 | 保留 Feishu/WebSocket/LLM/search/weather/cron/proactive，负责理解、拆解、调度、通知。 |
| Sensor | I2C/UART/GPIO 输入、采样任务、滤波缓存、MQTT/ESP-NOW 上报 | 持续采集环境数据，做本地阈值判断和短期统计，不跑 LLM。 |
| Control | GPIO/PWM/I2S/继电器/舵机、命令队列、安全互锁、状态机 | 只执行白名单动作，所有远程命令先入队、校验、限流、审计，不直接从 MQTT 调 GPIO。 |
| Display | PSRAM/屏幕 buffer、timeline 缓存、状态订阅、watchdog | 订阅 state/telemetry/timeline/alerts，展示调度过程和异常状态，不承担主 LLM。 |

远程控制的安全路径必须是：

```text
MQTT command
        |
        v
mesh_protocol validate
        |
        v
command_queue
        |
        v
safety_interlock
        |
        v
actuator_state
        |
        v
driver/tool
        |
        v
result event + timeline event
```

禁止让 MQTT command 直接调用 `gpio_write`、`servo_write`、`ws2812_set` 等硬件工具。这样做虽然快，但会绕过权限、审计、互锁和用户确认边界。

建议的 command 类型：

```c
typedef struct {
    char command_id[40];
    char target_node[32];
    char target_role[32];
    char action[32];
    char args_json[256];
    int ttl_ms;
    int safety_level;
    bool require_ack;
} espagent_mesh_command_t;
```

实现顺序建议：

1. 先补 `mesh_types` 和 `mesh_protocol`，稳定 topic 与 JSON schema。
2. 再把现有 `sensor_mqtt.c` 拆成通用 `mesh_mqtt` 和传感器 telemetry service。
3. 再加 `roles/*_node` 骨架，让不同 profile 启动不同服务。
4. 最后才开放 command 执行，并强制经过 command queue、safety interlock、tool guard 和 timeline event。

## 主要目录

```text
ESPAgent/
├── main/                       ESP-IDF application component
├── spiffs_data/                SPIFFS 初始文件
├── docs/                       架构、方案、集成、路线图
├── scripts/                    构建和环境脚本
├── skills/deploy/              部署辅助 skill
├── partitions.csv              Flash 分区表
├── sdkconfig.defaults          公共 ESP-IDF 默认配置
├── sdkconfig.defaults.esp32s3  ESP32-S3 默认配置
├── public_knowledge.md         AI 工作协议和进度日志
└── README.md                   项目入口说明
```

## main/ 文件分工

### 启动与全局配置

| 文件 | 意义 |
|------|------|
| `main/espagent.c` | ESP-IDF `app_main()` 入口，打印启动横幅并调用 app 启动阶段。 |
| `main/app/espagent_app.c/.h` | 真正的启动编排：NVS、SPIFFS、message bus、memory、cache、skills、Wi-Fi、LLM、tools、cron、proactive、CLI、网络服务。 |
| `main/espagent_config.h` | 全局编译期配置、默认值、分区路径、任务栈、GPIO、天气、MQTT、Mesh node profile、NVS namespace/key。 |
| `main/espagent_secrets.h.example` | build-time secrets 模板。真实 `espagent_secrets.h` 被 gitignore，不能提交。 |
| `main/CMakeLists.txt` | main 组件源文件和 ESP-IDF 依赖列表。 |

### 消息与 Agent

| 文件 | 意义 |
|------|------|
| `main/bus/message_bus.c/.h` | inbound/outbound FreeRTOS queue，统一传递 `espagent_msg_t`。 |
| `main/agent/agent_loop.c/.h` | 核心 ReAct loop：读取消息、构造 LLM 请求、执行 tool_use、保存会话、推送回复。 |
| `main/agent/context_builder.c/.h` | 构建 system prompt，包含工具说明、硬件边界、node profile、memory、recent notes、skills summary。 |
| `main/llm/llm_proxy.c/.h` | LLM provider HTTP 调用，支持 Anthropic 和 OpenAI-compatible tool-use 解析。 |
| `main/node/node_profile.c/.h` | 当前节点身份、角色、能力、职责和 capability 检查。用于四 ESP32 分工。 |

### 通道与网关

| 文件 | 意义 |
|------|------|
| `main/channels/feishu/feishu_bot.c/.h` | Feishu/Lark WebSocket 接入、事件解析、消息入队、回复发送。 |
| `main/gateway/ws_server.c/.h` | 本地 WebSocket chat gateway，默认端口 `18789`。 |
| `main/cli/serial_cli.c/.h` | USB serial CLI，提供配置、诊断、工具直调、注入消息、搜索测试、proactive 测试等命令。 |
| `main/onboard/wifi_onboard.c/.h` | Wi-Fi onboarding/admin AP。 |
| `main/onboard/onboard_html.h` | 内嵌 onboarding HTML 页面。 |

### 存储、记忆、缓存、技能

| 文件 | 意义 |
|------|------|
| `main/memory/memory_store.c/.h` | 长期记忆 `MEMORY.md` 和 daily notes 读写。 |
| `main/memory/session_mgr.c/.h` | 每个 chat 的 JSONL 会话历史，文件名使用 hash，避免长 chat_id 破坏 SPIFFS 路径。 |
| `main/cache/cache_store.c/.h` | RAM KV cache，目前主要缓存 skills summary，后续可缓存 MCP tools list、搜索摘要、传感器快照。 |
| `main/skills/skill_loader.c/.h` | 从 SPIFFS skills markdown 中构建 prompt summary。 |

### 后台行为

| 文件 | 意义 |
|------|------|
| `main/cron/cron_service.c/.h` | 定时任务服务，支持 every、at、daily，任务触发后注入 agent turn。 |
| `main/proactive/proactive_service.c/.h` | 周期性主动检查，必要时向最近联系人发起消息；`PROACTIVE_NO_MESSAGE` 表示无需打扰。 |
| `main/heartbeat/heartbeat.c/.h` | 周期性读取 `HEARTBEAT.md` 并按需注入任务。 |

### 硬件、传感器和通信

| 文件 | 意义 |
|------|------|
| `main/drivers/*.c/.h` | 底层驱动：SGP30、AHT10/AHT20、BH1750、MAX98357 等。 |
| `main/tools/*.c/.h` | AI-callable 工具实现。每个工具做参数解析、边界检查和具体硬件/服务调用。 |
| `main/tools/tool_registry.c/.h` | 工具注册表、JSON schema 构建、按名字分发执行。 |
| `main/tools/gpio_policy.c/.h` | GPIO allowlist 和安全策略。 |
| `main/sensors/sensor_mqtt.c/.h` | MQTT state/event/telemetry 发布，订阅 node/role command、dispatch、alerts。 |
| `main/espnow/espnow_sender.c/.h` | ESP-NOW 广播文本遥测。 |
| `main/wifi/wifi_manager.c/.h` | Wi-Fi STA 生命周期、事件处理、重连退避。 |
| `main/proxy/http_proxy.c/.h` | HTTP CONNECT 代理，用于 Feishu/LLM/search 等 HTTPS 出口。 |
| `main/ota/ota_manager.c/.h` | HTTPS OTA 更新封装。 |

## SPIFFS 初始文件

| 路径 | 意义 |
|------|------|
| `spiffs_data/config/SOUL.md` | AI 个性和基本行为设定。 |
| `spiffs_data/config/USER.md` | 用户信息 bootstrap。 |
| `spiffs_data/memory/MEMORY.md` | 长期记忆初始文件。 |
| `spiffs_data/skills/*.md` | skills，运行时由 `skill_loader` 汇总进 prompt。 |

运行期还会使用：

- `/spiffs/memory/<YYYY-MM-DD>.md`: daily notes。
- `/spiffs/sessions/session_<hash>.jsonl`: 每个 chat 的短期会话历史。
- `/spiffs/cron.json`: cron 任务配置。
- `/spiffs/HEARTBEAT.md`: heartbeat 待办。

## 当前功能总览

### 通信入口

- Feishu/Lark WebSocket：主要用户聊天入口。
- 本地 WebSocket gateway：端口 `18789`，可用于上位机或调试网页。
- Serial CLI：无 Wi-Fi 时也可进行配置、诊断和工具测试。
- Cron / proactive / heartbeat：内部主动注入 agent turn。

### LLM 与工具调用

- `agent_loop` 使用非流式 LLM 请求。
- 支持 Anthropic Messages API 和 OpenAI-compatible provider。
- 支持多轮 tool_use，最大迭代由 `ESPAGENT_AGENT_MAX_TOOL_ITER` 控制，当前为 10。
- 工具 schema 由 `tool_registry` 统一生成。
- 工具结果回填给 LLM，再生成最终自然语言回复。

### 已注册工具

| 工具 | 作用 |
|------|------|
| `web_search` | Tavily 优先、Brave fallback 的联网搜索。 |
| `get_weather` | 高德 Amap WebService 天气，默认南京市栖霞区。 |
| `get_current_time` | 获取当前时间并设置系统时钟。 |
| `read_temperature_humidity` | AHT10/AHT20 温湿度读取。 |
| `read_environment` | AHT10/AHT20 + SGP30 + BH1750/GY-30 综合环境读取。 |
| `read_presence` | 人体存在或 HC-SR05 超声波存在判断。 |
| `hc_sr05_read_distance` | HC-SR05 低层距离读取。 |
| `read_file` / `write_file` / `edit_file` / `list_dir` | SPIFFS 文件工具。 |
| `gpio_write` / `gpio_read` / `gpio_read_all` | GPIO 控制和读取。 |
| `ws2812_set` / `set_status_light` | WS2812 RGB 状态灯控制。 |
| `servo_write` | GPIO5 舵机控制，角度或脉宽。 |
| `max98357_play_tone` | MAX98357 I2S 扬声器测试音。 |
| `sgp30_read_air_quality` / `read_air_quality` | SGP30 空气质量 eCO2/TVOC。 |
| `read_light_level` | BH1750/GY-30 光照 lux。 |
| `cron_add` / `cron_list` / `cron_remove` | 定时任务管理。 |

### 硬件能力

- WS2812 RGB：默认 GPIO48。
- 舵机：GPIO5，LEDC PWM，50Hz，500-2500us。
- AHT10/AHT20：温湿度。
- SGP30：空气质量 eCO2/TVOC。
- BH1750/GY-30：光照 lux。
- HC-SR05：超声波距离/存在检测，Echo 必须做电平保护。
- 3-wire presence/PIR：数字人体存在输入。
- MAX98357：I2S 音频测试。
- GPIO：仅允许安全 allowlist，避免破坏 USB/boot。

### 主动性

- `cron_add` 支持 recurring、one-shot、daily。
- `proactive_service` 可周期性触发自检，必要时主动发消息。
- 天气主动提醒应优先使用 `get_weather`。
- 如果 LLM 返回 `PROACTIVE_NO_MESSAGE`，proactive turn 不打扰用户。

## 配置方式

核心配置位于 `main/espagent_config.h`，真实部署值放在 `main/espagent_secrets.h`。

重要规则：

- `main/espagent_secrets.h` 是私有文件，不能提交。
- `main/espagent_secrets.h.example` 是公开模板。
- 部分配置可通过 Serial CLI 存入 NVS，但 node profile 当前主要依赖 build-time macros。
- Wi-Fi、LLM、搜索、高德、Feishu、代理、传感器引脚、Mesh 节点身份都通过宏或 NVS 管理。

常用 node profile 宏：

```c
#define ESPAGENT_SECRET_NODE_ID "esp32s3-sensor-01"
#define ESPAGENT_SECRET_NODE_ROLE "sensor_agent"
#define ESPAGENT_SECRET_NODE_LOCATION "南京市栖霞区"
#define ESPAGENT_SECRET_NODE_CAPABILITIES "sensor,telemetry,environment,air_quality,light,presence"
#define ESPAGENT_SECRET_NODE_RESPONSIBILITIES "read environment sensors and publish telemetry"
```

## 存储与分区

Flash 配置为 16MB，自定义分区表：

| 分区 | 大小 | 作用 |
|------|------|------|
| `nvs` | 24KB | Wi-Fi、LLM、Feishu、搜索、proactive、Amap 等 NVS 配置。 |
| `ota_0` | 2MB | OTA app slot A。 |
| `ota_1` | 2MB | OTA app slot B。 |
| `spiffs` | 约 11.8MB | memory、sessions、skills、cron、config 文件。 |
| `coredump` | 64KB | 预留 coredump，当前 sdkconfig 禁用 flash coredump。 |

最近构建结果：

- `build/ESPAgent.bin` size `0x147e40`。
- 最小 app 分区剩余 `0xb81c0`，约 36%。

## 运行时任务

核心 FreeRTOS 任务：

- `agent_loop`: Core 1，处理 LLM 和工具调用。
- `feishu_ws`: Core 0，Feishu WebSocket。
- `outbound`: Core 0，统一发送 Feishu/WebSocket 回复。
- `serial_cli`: Core 0，串口 REPL。
- `cron`: 定时任务轮询。
- `proactive`: 主动检查。
- `sensor_mqtt`: MQTT state/event/telemetry。
- ESP-IDF 内部 Wi-Fi/httpd/TLS 任务。

设计原则：

- Core 0 偏 I/O。
- Core 1 偏 Agent/JSON/HTTPS。
- 大 buffer 优先 PSRAM。
- FreeRTOS queue 传递消息所有权，pop 后由消费者释放 `content`。

## 当前进度

已经完成：

- 项目重命名和文档体系统一为 ESPAgent。
- ESP-IDF 6.1-dev 构建适配。
- Feishu、WebSocket、Serial CLI 三类入口。
- 单 agent loop + tool calling + tool registry。
- SGP30、AHT10/AHT20、BH1750、HC-SR05、WS2812、舵机、MAX98357 等工具或驱动。
- 高德天气 `get_weather`，默认南京市栖霞区。
- Tavily/Brave 搜索。
- prompt 安全边界和 execution-side tool guard。
- SPIFFS memory、daily notes、sessions、skills。
- Cron daily proactive 和 periodic proactive service。
- 反问承接的启发式上下文提示。
- Agent Mesh Phase 1：node identity、capabilities、responsibilities、MQTT state/telemetry/event、node/role command topic。
- 四 ESP32 role profile 文档：coordinator、sensor、control、display。
- GitHub 远端：
  - HTTPS: `https://github.com/cube1345/ESPAgent.git`
  - SSH: `git@github.com:cube1345/ESPAgent.git`
  - `main` 已推送，最新推送提交包含 `91d7ead`。

## 当前限制

- 当前仍是单 ESP32-S3 的单 `agent_loop`，不是完整多 Agent 运行时。
- MQTT command 和 dispatch 现在只打印日志，不执行硬件动作。
- 还没有 MQTT command schema、鉴权、审计事件和安全执行链路。
- 还没有根据 role 自动裁剪工具列表。
- Coordinator 还没有真实跨节点调度。
- timeline topic 目前是规划保留，还没有完整 tool_result/event 流。
- Memory 写入依赖模型主动调用文件工具，没有固件侧强制 consolidation。
- session 只保存最终对话，不保存完整 tool_use/tool_result 轨迹。
- system prompt 仍集中在 C 字符串中，后续可以拆成 SPIFFS prompt fragments。
- NVS 只有 24KB，后续如果存节点表、证书或更多运行时配置，建议扩容。
- 本地工作区 `.git` 是只读空目录；最近一次推送使用 `/tmp/espagent_push_git_20260609` 作为临时 Git 元数据目录完成。

## 未来规划

### P0

- 实现 MQTT command schema。
- 将 MQTT command 安全转入 `message_bus`，由 `agent_loop` 和 `tool_guard` 处理。
- 发布 timeline events：用户指令、任务拆解、工具调用、工具结果、最终回复。
- 增加节点 heartbeat / discovery。
- 增加 `storage_info` CLI，打印 SPIFFS/NVS/session 状态。

### P1

- Role-based tool exposure，根据 node capabilities 裁剪工具表和 prompt。
- Coordinator Agent 最小实现：只做任务路由和只读查询，不直接绕过安全层。
- Display Agent 支持 ESP32-P4 或 Android 订阅 timeline。
- MQTT TLS/认证或内网/VPN 部署规范。
- 完善 session/tool trace 持久化，便于调试和展示。

### P2

- MCP Gateway：数据库、知识库、Home Assistant、云服务。
- Memory Agent：长期记忆压缩、用户偏好、skills 管理。
- Android App：移动查看、调试、控制、调度时间线展示。
- ESP32-P4 中控屏：现场可视化和触控操作。
- 多节点策略：传感器冗余、控制器仲裁、异常告警。

## 开发注意事项

- 修改文件前先读 `public_knowledge.md`。
- 不要提交 `main/espagent_secrets.h`、`sdkconfig`、`dependencies.lock`、`build/`。
- 硬件工具要窄、可解释、可测试。
- 新硬件能力先做底层工具，再注册 tool schema，再补 prompt guidance，再用 CLI 测试。
- 通道模块不要直接控制硬件。
- 远程控制必须经过 schema、鉴权、message_bus、agent_loop、tool_guard。
- 对 ESP-IDF API 不确定时先查项目用法或官方文档。
