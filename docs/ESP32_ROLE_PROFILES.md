# ESP32 Role Profiles

本文说明如何用同一套 ESPAgent 固件，让四块 ESP32-S3 在 LingShu Agent Mesh 中各司其职。

核心原则：

- 四块板可以使用同一套代码。
- 每块板通过 `main/espagent_secrets.h` 设置不同的 `NODE_ID`、`NODE_ROLE`、`NODE_CAPABILITIES` 和 `NODE_RESPONSIBILITIES`。
- MQTT state/telemetry/event payload 会带上这些字段。
- 每块板会订阅自己的节点命令 topic 和角色命令 topic。
- 远程 command 当前仍只记录日志，不直接执行硬件动作；真正执行前必须接入 message_bus、schema 校验和 tool_guard。

## 通用配置项

```c
#define ESPAGENT_SECRET_NODE_ID "esp32s3-edge-01"
#define ESPAGENT_SECRET_NODE_ROLE "edge_agent"
#define ESPAGENT_SECRET_NODE_LOCATION "南京市栖霞区"
#define ESPAGENT_SECRET_MESH_TOPIC_PREFIX "espagent"
#define ESPAGENT_SECRET_NODE_CAPABILITIES "coordinator,communication,sensor,control,display,telemetry,timeline,alerts"
#define ESPAGENT_SECRET_NODE_RESPONSIBILITIES "single-node development profile; can chat, sense, control, publish telemetry, and display mesh state"
```

## ESP32-1: Coordinator / Communication Node

职责：

- 接收 Feishu / WebSocket 用户消息。
- 调用 LLM 做任务理解。
- 后续负责生成 dispatch 和 timeline。
- 作为用户入口，不直接承担所有硬件控制。

建议配置：

```c
#define ESPAGENT_SECRET_NODE_ID "esp32s3-coordinator-01"
#define ESPAGENT_SECRET_NODE_ROLE "coordinator_agent"
#define ESPAGENT_SECRET_NODE_CAPABILITIES "coordinator,communication,llm,dispatch,timeline,alerts"
#define ESPAGENT_SECRET_NODE_RESPONSIBILITIES "receive user messages, call LLM, plan dispatch, publish timeline, and notify users"
```

## ESP32-2: Sensor Node

职责：

- 采集温湿度、空气质量、光照、人体存在等数据。
- 周期发布 telemetry。
- 不直接控制高风险执行器。

建议配置：

```c
#define ESPAGENT_SECRET_NODE_ID "esp32s3-sensor-01"
#define ESPAGENT_SECRET_NODE_ROLE "sensor_agent"
#define ESPAGENT_SECRET_NODE_CAPABILITIES "sensor,telemetry,environment,air_quality,light,presence"
#define ESPAGENT_SECRET_NODE_RESPONSIBILITIES "read environment sensors and publish telemetry for coordinator and display nodes"
```

## ESP32-3: Control Node

职责：

- 控制 RGB、GPIO、舵机、继电器、风扇、水泵、加湿器等。
- 后续接收安全 command 后执行硬件动作。
- 保持工具权限窄、动作可审计。

建议配置：

```c
#define ESPAGENT_SECRET_NODE_ID "esp32s3-control-01"
#define ESPAGENT_SECRET_NODE_ROLE "control_agent"
#define ESPAGENT_SECRET_NODE_CAPABILITIES "control,gpio,rgb,servo,relay,actuator"
#define ESPAGENT_SECRET_NODE_RESPONSIBILITIES "execute whitelisted hardware actions after schema validation and tool guard checks"
```

## ESP32-4: Display / Watchdog Node

职责：

- 订阅状态、告警和 timeline。
- 展示节点在线状态、环境数据、任务过程。
- 可做状态灯、蜂鸣提示或本地 watchdog。

建议配置：

```c
#define ESPAGENT_SECRET_NODE_ID "esp32s3-display-01"
#define ESPAGENT_SECRET_NODE_ROLE "display_agent"
#define ESPAGENT_SECRET_NODE_CAPABILITIES "display,timeline,alerts,state,watchdog"
#define ESPAGENT_SECRET_NODE_RESPONSIBILITIES "display mesh state, timeline, telemetry, alerts, and watchdog status"
```

## MQTT Topics

每个节点都会使用：

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

示例：

```text
espagent/nodes/esp32s3-control-01/command
espagent/roles/control_agent/command
```

## 当前实现边界

已经实现：

- 节点身份、能力和职责配置。
- `config_show` 展示节点 profile。
- MQTT state/event/telemetry 带节点 profile。
- 按节点和按角色订阅 command topic。
- 非 sensor profile 不会因为缺少 DHT22/MH-Z19 而反复重连。

尚未实现：

- MQTT command schema。
- MQTT command 到 message_bus 的安全转发。
- 根据 role 自动裁剪工具列表。
- Coordinator 真实跨节点调度。
- timeline tool_result 事件流。
