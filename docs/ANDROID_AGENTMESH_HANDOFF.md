# Android AgentMesh Display Handoff

本文用于交接给后续 AI/开发者：用 Java 编写一个 Android 端，作为 ESPAgent Agent Mesh 的移动 Display Agent。它的定位类似 ESP32-P4+C6 LVGL 屏，但 Android 端可以承担更复杂的 UI、交互、历史追踪和调试能力。

## 一句话目标

开发一个 Java Android App，通过 MQTT 订阅 ESPAgent Mesh 的 timeline/state/telemetry/alerts 数据，把四个 ESP32-S3 Agent 的推理过程、任务传递、工具调用、硬件执行和最终用户结果可视化，并提供基础调试交互。

## 项目背景

当前 ESPAgent 是 ESP32-S3 上的轻量 Agent runtime。四块 ESP32-S3 使用同一固件，通过 build-time profile 区分角色：

```text
/dev/ttyUSB0  esp32s3-coordinator-01  coordinator_agent
/dev/ttyUSB1  esp32s3-sensor-01       sensor_agent
/dev/ttyUSB2  esp32s3-control-01      control_agent
/dev/ttyUSB3  esp32s3-display-01      display_agent
```

当前核心链路：

```text
Feishu / WebSocket / Cron / Proactive
        |
        v
message_bus inbound queue
        |
        v
agent_loop
        |
        v
LLM tool calling / ReAct / spawn_subagent
        |
        v
tool_registry
        |
        v
传感器 / GPIO / RGB / 舵机 / 文件 / 天气 / 搜索 / Mesh command
        |
        v
message_bus outbound queue
        |
        v
Feishu / WebSocket / MQTT timeline
```

当前边界必须写清楚：

- ESP32-S3 端仍是一个 `agent_loop` 串行处理 LLM 回合，不是多个 Linux 进程式 Agent。
- `spawn_subagent` 已实现，是同一 Coordinator MCU 上临时创建的 FreeRTOS 子任务，工具权限受限。
- MQTT Mesh 已能表达跨节点命令、状态、遥测和 timeline。
- Android 端第一阶段只做 Display Agent 和调试终端，不直接替代 Coordinator。

## 可参考项目

需要先阅读：

- ESPAgent 主项目：`/home/cube/WorkSpace/ESP/ESPAgent`
- 公共知识库：`docs/PUBLIC_KNOWLEDGE_BASE.md`
- Agent 分析：`docs/AGENT_ANALYSIS.md`
- 四角色说明：`docs/ESP32_ROLE_PROFILES.md`
- P4 显示端工程：`/home/cube/WorkSpace/ESP/lvgl_traffic_control`
- 多 Agent 协作参考：`/home/cube/WorkSpace/DLML/Stage`

Stage 项目的迁移重点：

- `Director` 对应 ESPAgent 的 Coordinator/Feishu/LLM 入口。
- `Agent` 对应 ESP32-S3 的 Sensor/Control/Display 等角色节点。
- `StateBoard` 思想应迁移到 Android：所有 MQTT 事件先进入本地状态板，再由 UI 渲染。
- `Event`/`Trace` 思想应迁移到 Android：用户指令、工具调用、Mesh 下发、节点执行、最终回复必须能串成一条 timeline。

## MQTT 接入参数

当前开发联调用：

```text
Broker: broker.emqx.io
Port: 1883
Topic prefix: espagent/cube1345
```

Android 第一版订阅：

```text
espagent/cube1345/agent/timeline
espagent/cube1345/agent/dispatch
espagent/cube1345/nodes/+/state
espagent/cube1345/nodes/+/telemetry
espagent/cube1345/nodes/+/events
espagent/cube1345/alerts
```

可选发布调试命令：

```text
espagent/cube1345/roles/sensor_agent/command
espagent/cube1345/roles/control_agent/command
espagent/cube1345/nodes/<node_id>/command
```

生产注意：

- 当前公共 broker 只用于开发验证。
- App 中 broker、port、topic prefix 必须可配置。
- 后续需要支持用户名/密码、TLS、私有 broker。
- 第一版不要默认开放高风险控制按钮；控制命令必须放在调试页并带确认。

## 需要识别的事件类型

Android 端必须按 `event_type` 或等价字段分类展示：

```text
feishu_inbound          用户从飞书进入的消息
feishu_outbound         AI 回复飞书的消息
tool_use                LLM 选择调用工具
tool_result             工具执行结果
mesh_command_queued     Coordinator 已将 Mesh 命令入队/发布
mesh_command_result     下游节点执行结果
dispatch                Coordinator 调度事件
state                   节点在线/离线/角色状态
telemetry               传感器遥测
alert                   告警
error                   错误路径
final_reply             面向用户的最终结果
```

如果 payload 字段不稳定，Android 端应采用宽松 JSON 解析：

- 优先读取 `event_type`、`type`、`name`。
- 优先读取 `node_id`、`role`、`source`、`target_role`、`target_node`。
- 优先读取 `command_id`、`trace_id`、`task_id`，没有则本地生成。
- 原始 JSON 必须保留，供调试面板查看。

## 本地数据模型

建议 Java model：

```text
AgentNode
  nodeId
  role
  capabilities
  location
  online
  lastSeenMs
  lastStateRawJson

MeshEvent
  id
  timestampMs
  topic
  eventType
  severity
  nodeId
  role
  source
  targetNode
  targetRole
  commandId
  traceId
  title
  summary
  rawJson

AgentTrace
  traceId
  userMessage
  events
  finalReply
  startedAtMs
  updatedAtMs
  status

TelemetrySnapshot
  nodeId
  role
  temperature
  humidity
  eco2
  tvoc
  lux
  presence
  rawJson
  updatedAtMs
```

StateBoard：

```text
AgentMeshStateBoard
  Map<String, AgentNode> nodes
  List<MeshEvent> timeline
  Map<String, AgentTrace> traces
  Map<String, TelemetrySnapshot> telemetry
  List<MeshEvent> alerts
```

规则：

- MQTT callback 只负责解析和入队，不直接操作复杂 UI。
- StateBoard 是 App 内唯一事实源。
- ViewModel 从 StateBoard 派生 UI state。
- 保留最近 500-2000 条事件，避免手机长时间运行导致内存无限增长。
- 关键 trace 可保存到本地 SQLite/Room，第一版可先用内存 + 导出 JSON。

## Android 技术栈要求

语言与框架：

- Java
- AndroidX AppCompat 或 Material Components
- MVVM：Activity/Fragment + ViewModel + LiveData
- RecyclerView 展示 timeline
- Eclipse Paho MQTT Android Client 或 HiveMQ MQTT Client Android 可选其一
- Gson 或 Moshi 解析 JSON
- Room 可作为第二阶段持久化

建议目录：

```text
app/src/main/java/<package>/
├── MainActivity.java
├── mqtt/
│   ├── MqttManager.java
│   ├── MqttConfig.java
│   └── MqttMessageRouter.java
├── model/
│   ├── AgentNode.java
│   ├── MeshEvent.java
│   ├── AgentTrace.java
│   └── TelemetrySnapshot.java
├── state/
│   └── AgentMeshStateBoard.java
├── ui/
│   ├── dashboard/
│   ├── timeline/
│   ├── trace/
│   ├── nodes/
│   ├── telemetry/
│   └── debug/
└── util/
    ├── JsonFieldReader.java
    └── TimeFormat.java
```

## UI 信息架构

第一屏是 Agent Mesh Dashboard，不做营销页。

底部导航或侧边导航：

```text
Dashboard   总览
Timeline    推理/通信时间线
Trace       单次任务链路
Nodes       四个 ESP32 节点
Telemetry   传感器数据
Debug       MQTT 原始包与调试命令
Settings    broker/topic 配置
```

Dashboard：

- 显示 Coordinator/Sensor/Control/Display 四张节点状态卡。
- 显示最近一条用户请求、当前任务状态、最终回复。
- 显示在线节点数量、最近告警、最近传感器摘要。

Timeline：

- 纵向时间线，按事件类型使用不同 icon 和颜色。
- 必须展示：用户输入、工具调用、Mesh 下发、节点执行、最终回复。
- 点击事件可展开 raw JSON。
- 支持按 node/role/event_type 过滤。

Trace：

- 以一次用户请求为中心展示完整链路。
- 如果没有 `trace_id`，用时间窗口 + `command_id` + topic 进行弱关联。
- 展示类似：

```text
用户: 读取温湿度
Coordinator: tool_use mesh_send_command
MQTT: mesh_command_queued -> sensor_agent
Sensor: mesh_command_result
Coordinator: final_reply
```

Nodes：

- 四个角色固定展示，即使某个节点暂时未上线也要有占位。
- 每个节点显示 role、node_id、capabilities、last_seen、online/offline、最近事件。

Telemetry：

- 温湿度、空气质量、光照、人体存在等数据卡片。
- 当前传感器可能未接好，读数失败时要显示“节点在线但传感器未返回”，不能显示成 App 崩溃或空白。

Debug：

- MQTT 连接状态、订阅 topic、最近原始消息。
- 提供只读 raw JSON 查看。
- 可选提供“发送测试命令”，必须二次确认。

Settings：

- broker、port、topic prefix、client id、是否自动重连。
- 保存到 SharedPreferences。

## 交互效果要求

- 新事件进入时，Timeline 顶部或对应事件行有轻量动画。
- 节点在线/离线状态有明显但克制的变化。
- Trace 页用连线或步骤条表达任务传播过程。
- 错误事件和告警应突出，但不要遮挡主流程。
- UI 应适合现场演示：不用解释文字堆砌，而是让观众一眼看到“AI 正在调度哪个 Agent”。

## 第一阶段验收标准

必须完成：

- App 可配置 MQTT broker/topic prefix 并成功连接。
- 能订阅并显示 `agent/timeline` 原始事件。
- 能显示四个节点的在线状态。
- 能解析并分类展示 `tool_use`、`tool_result`、`mesh_command_queued`、`mesh_command_result`、`final_reply`、`error`。
- Feishu 发 `读取温湿度` 后，Android Timeline 能看到 Coordinator 下发到 Sensor 的链路。
- Feishu 发 `点亮WS2812为蓝色` 后，Android Timeline 能看到 Coordinator 下发到 Control 的链路。
- 断网/重连后 UI 不崩溃，连接状态明确。

暂不要求：

- Android 端直接调用 LLM。
- Android 端替代 Feishu 入口。
- Android 端直接控制高风险硬件。
- 完整历史数据库和云同步。

## 第二阶段建议

- 加 Room 持久化 trace/event。
- 加任务回放：按时间轴重播一次 Agent 协作过程。
- 加节点拓扑图：Coordinator -> Sensor/Control/Display。
- 加告警规则：传感器异常、节点长时间离线、命令超时。
- 加 Android 端主动控制入口，但必须经过确认和权限分级。
- 加语音入口：Android STT -> 发送给 Coordinator/WebSocket/Feishu-like channel。
- 加 TTS 播报最终结果和重要告警。

## 给实现 AI 的任务 Prompt

可以把下面这段直接交给写 Android 代码的 AI：

```text
你要用 Java 写一个 Android App，项目名建议为 ESPAgentMeshDisplay。它是 ESPAgent 多 Agent 项目的 Android Display Agent，定位类似 ESP32-P4+C6 LVGL 屏，但需要更复杂的 UI 和交互。

请先阅读这些背景文件：
1. /home/cube/WorkSpace/ESP/ESPAgent/docs/PUBLIC_KNOWLEDGE_BASE.md
2. /home/cube/WorkSpace/ESP/ESPAgent/docs/AGENT_ANALYSIS.md
3. /home/cube/WorkSpace/ESP/ESPAgent/docs/ESP32_ROLE_PROFILES.md
4. /home/cube/WorkSpace/ESP/ESPAgent/docs/ANDROID_AGENTMESH_HANDOFF.md
5. /home/cube/WorkSpace/DLML/Stage/README.md
6. /home/cube/WorkSpace/DLML/Stage/CLAUDE.md

实现目标：
- Android App 使用 Java。
- 通过 MQTT 连接 broker.emqx.io:1883，默认 topic prefix 为 espagent/cube1345，但必须可在 Settings 中修改。
- 订阅：
  espagent/cube1345/agent/timeline
  espagent/cube1345/agent/dispatch
  espagent/cube1345/nodes/+/state
  espagent/cube1345/nodes/+/telemetry
  espagent/cube1345/nodes/+/events
  espagent/cube1345/alerts
- 在 App 内实现 AgentMeshStateBoard，把 MQTT 事件统一归档为 nodes、timeline、traces、telemetry、alerts。
- UI 至少包含 Dashboard、Timeline、Trace、Nodes、Telemetry、Debug、Settings。
- Timeline 必须能展示用户输入、LLM tool_use、tool_result、mesh_command_queued、mesh_command_result、final_reply、error。
- Nodes 页固定展示 coordinator_agent、sensor_agent、control_agent、display_agent 四个角色。
- Debug 页能查看原始 MQTT topic/payload。
- 代码采用 MVVM：MqttManager -> MqttMessageRouter -> AgentMeshStateBoard -> ViewModel -> RecyclerView/UI。
- MQTT callback 不直接操作 UI。
- JSON 解析要宽松，未知字段保留 rawJson，不允许因为字段缺失崩溃。
- 第一版只做展示与调试，不直接替代 Coordinator，也不要默认开放高风险控制。

验收：
1. App 启动后可以连接 MQTT，并显示连接状态。
2. 发送测试 MQTT JSON 到 agent/timeline，Timeline 页面能实时出现事件。
3. 四个 ESP32 上电后，Nodes 页面能看到 state online。
4. 从飞书发送“读取温湿度”，Timeline/Trace 能看到 Coordinator -> Sensor 的链路。
5. 从飞书发送“点亮WS2812为蓝色”，Timeline/Trace 能看到 Coordinator -> Control 的链路。
6. 断开网络再恢复，App 不崩溃，并能自动重连或显示明确错误。

不要做：
- 不要把 Android 端写成普通聊天机器人。
- 不要让 Android 第一版直接调用 LLM。
- 不要绕过 MQTT Mesh 直接控制硬件。
- 不要把未验证的 P4/Android 展示能力描述成已经完全跑通。
```
