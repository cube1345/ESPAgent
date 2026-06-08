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

## 资源使用设计

目标不是让四块板都跑同样的满功能固件，而是让每块 ESP32-S3 吃满自己擅长的硬件资源。

| 节点 | 资源侧重点 | 不建议承担 |
|------|------------|------------|
| `coordinator_agent` | LLM HTTPS、Feishu/WebSocket、JSON 解析、session/context、dispatch/timeline | 长周期传感器采样、高风险执行器直控 |
| `sensor_agent` | I2C/UART/GPIO 采样、滤波、短期缓存、MQTT/ESP-NOW telemetry | LLM、用户聊天入口、继电器/电机控制 |
| `control_agent` | GPIO、PWM、I2S、继电器、舵机、RGB、动作队列、安全互锁 | 任务理解、天气搜索、跨节点规划 |
| `display_agent` | 屏幕/状态灯、PSRAM buffer、timeline cache、alerts/watchdog | 主 LLM、重型采样、危险控制 |

当前 profile 只是声明能力；下一步要把声明能力变成实际启动行为。推荐结构：

```text
common runtime
  Wi-Fi / NVS / SPIFFS / message_bus / node_profile / serial_cli

mesh protocol
  topic builder / JSON schema / MQTT transport / ESP-NOW framing

role service
  coordinator_node / sensor_node / control_node / display_node
```

推荐启动方式：

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

## 远程命令安全路径

后续允许 Coordinator 调用 Control Node 时，命令必须走固定链路：

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

不要让 MQTT callback 直接调用 `gpio_write`、`servo_write` 或 `ws2812_set`。原因是 MQTT 只是传输入口，不应该绕过 schema 校验、TTL、权限、互锁、审计和 timeline。

建议 command 数据结构：

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

## 模块拆分路线

下一轮代码改造建议按这个顺序做：

1. 新增 `main/mesh/mesh_types.h`，集中定义 node_state、telemetry、command、result、timeline 类型。
2. 新增 `main/mesh/mesh_protocol.c/.h`，集中处理 topic 构造和 JSON encode/decode。
3. 将 `main/sensors/sensor_mqtt.c` 拆成通用 `mesh_mqtt.c` 和 sensor telemetry service。
4. 新增 `main/roles/role_config.h`，封装 `node_profile` role/capability 判断。
5. 新增四个 role service 骨架：`coordinator_node`、`sensor_node`、`control_node`、`display_node`。
6. 修改 `main/app/espagent_app.c`，按 role 启动对应服务。
7. command 执行先保持禁用或 dry-run，只做 parse/validate/log/timeline，确认安全链路后再接入真实执行。
