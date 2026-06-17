#include "tools/tool_mesh_command.h"

#include "esp_timer.h"
#include "esp_log.h"
#include "espagent_config.h"
#include "mesh/mesh_protocol.h"
#include "sensors/sensor_mqtt.h"

#include "cJSON.h"

#include <stdio.h>
#include <stdbool.h>
#include <string.h>

static const char *json_string(cJSON *root, const char *key)
{
    cJSON *item = cJSON_GetObjectItem(root, key);
    return cJSON_IsString(item) ? item->valuestring : NULL;
}

static int json_int(cJSON *root, const char *key, int default_value)
{
    cJSON *item = cJSON_GetObjectItem(root, key);
    return cJSON_IsNumber(item) ? item->valueint : default_value;
}

static bool json_bool(cJSON *root, const char *key, bool default_value)
{
    cJSON *item = cJSON_GetObjectItem(root, key);
    if (!item) {
        return default_value;
    }
    return cJSON_IsTrue(item);
}

static bool is_control_action(const char *action)
{
    return action &&
           (strcmp(action, "set_status_light") == 0 ||
            strcmp(action, "ws2812_set") == 0 ||
            strcmp(action, "servo_write") == 0 ||
            strcmp(action, "gpio_write") == 0);
}

static bool is_sensor_action(const char *action)
{
    return action && strcmp(action, "read_temperature_humidity") == 0;
}

static bool is_allowed_mesh_action(const char *action)
{
    return is_sensor_action(action) || is_control_action(action);
}

static esp_err_t request_policy_decision(const char *command_id,
                                         const char *trace_id,
                                         const char *target_role,
                                         const char *target_node,
                                         const char *action,
                                         int safety_level,
                                         int ttl_ms,
                                         char *decision_json,
                                         size_t decision_json_size,
                                         char *reason,
                                         size_t reason_size)
{
    cJSON *policy = cJSON_CreateObject();
    if (!policy) {
        return ESP_ERR_NO_MEM;
    }

    int64_t ts_ms = esp_timer_get_time() / 1000;
    cJSON_AddStringToObject(policy, "schema", "espagent.policy_check.v1");
    cJSON_AddStringToObject(policy, "event", "policy_check");
    cJSON_AddStringToObject(policy, "command_id", command_id);
    cJSON_AddStringToObject(policy, "trace_id", trace_id);
    cJSON_AddStringToObject(policy, "source_role", "coordinator_agent");
    cJSON_AddStringToObject(policy, "target_role", target_role ? target_role : "");
    cJSON_AddStringToObject(policy, "target_node", target_node ? target_node : "");
    cJSON_AddStringToObject(policy, "action", action);
    cJSON_AddNumberToObject(policy, "safety_level", safety_level);
    cJSON_AddNumberToObject(policy, "ttl_ms", ttl_ms);
    cJSON_AddNumberToObject(policy, "ts_ms", (double)ts_ms);

    char *json = cJSON_PrintUnformatted(policy);
    cJSON_Delete(policy);
    if (!json) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI("tool_mesh_command", "Policy check requested: %s", json);
    esp_err_t err = sensor_mqtt_publish_text(ESPAGENT_MESH_TOPIC_POLICY_CHECK, json);
    cJSON_free(json);
    if (err != ESP_OK) {
        snprintf(reason, reason_size, "failed to publish policy_check: %s", esp_err_to_name(err));
        return err;
    }

    uint32_t wait_ms = ttl_ms > 0 ? (uint32_t)ttl_ms : 30000U;
    if (wait_ms > 8000U) {
        wait_ms = 8000U;
    }
    if (wait_ms < 1000U) {
        wait_ms = 1000U;
    }

    err = sensor_mqtt_wait_policy_decision(command_id,
                                           decision_json,
                                           decision_json_size,
                                           wait_ms);
    if (err != ESP_OK) {
        snprintf(reason, reason_size, "policy_decision wait timed out after %ums", (unsigned)wait_ms);
        return err;
    }

    cJSON *decision = cJSON_Parse(decision_json);
    if (!decision || !cJSON_IsObject(decision)) {
        cJSON_Delete(decision);
        snprintf(reason, reason_size, "policy_decision is not valid JSON");
        return ESP_ERR_INVALID_RESPONSE;
    }

    cJSON *decision_item = cJSON_GetObjectItem(decision, "decision");
    cJSON *reason_item = cJSON_GetObjectItem(decision, "reason");
    const char *decision_text = cJSON_IsString(decision_item) ? decision_item->valuestring : "";
    const char *reason_text = cJSON_IsString(reason_item) ? reason_item->valuestring : "";
    snprintf(reason, reason_size, "%s", reason_text);
    bool allowed = strcmp(decision_text, "allow") == 0;
    cJSON_Delete(decision);

    return allowed ? ESP_OK : ESP_ERR_INVALID_STATE;
}

static void copy_text(char *dst, size_t dst_size, const char *src)
{
    if (!dst || dst_size == 0) {
        return;
    }
    snprintf(dst, dst_size, "%s", src ? src : "");
}

static esp_err_t copy_args(cJSON *root, cJSON *cmd)
{
    const char *args_json = json_string(root, "args_json");
    if (args_json && args_json[0]) {
        cJSON *args = cJSON_Parse(args_json);
        if (!args) {
            return ESP_ERR_INVALID_ARG;
        }
        cJSON_AddItemToObject(cmd, "args", args);
        return ESP_OK;
    }

    cJSON *args = cJSON_GetObjectItem(root, "args");
    if (args) {
        cJSON_AddItemReferenceToObject(cmd, "args", args);
    } else {
        cJSON_AddItemToObject(cmd, "args", cJSON_CreateObject());
    }
    return ESP_OK;
}

esp_err_t tool_mesh_send_command_execute(const char *input_json,
                                         char *output,
                                         size_t output_size)
{
    cJSON *root = cJSON_Parse(input_json);
    if (!root || !cJSON_IsObject(root)) {
        if (root) {
            cJSON_Delete(root);
        }
        snprintf(output, output_size, "Error: invalid JSON input");
        return ESP_ERR_INVALID_ARG;
    }

    const char *target_node = json_string(root, "target_node");
    const char *target_role = json_string(root, "target_role");
    const char *action = json_string(root, "action");
    if (!action || !action[0]) {
        cJSON_Delete(root);
        snprintf(output, output_size, "Error: action is required");
        return ESP_ERR_INVALID_ARG;
    }
    if (!is_allowed_mesh_action(action)) {
        cJSON_Delete(root);
        snprintf(output, output_size, "Error: unsupported mesh action=%s", action);
        return ESP_ERR_INVALID_ARG;
    }
    if ((!target_node || !target_node[0]) && (!target_role || !target_role[0]) &&
        strcmp(action, "read_temperature_humidity") == 0) {
        target_role = "sensor_agent";
    } else if ((!target_node || !target_node[0]) && (!target_role || !target_role[0]) &&
               is_control_action(action)) {
        target_role = "control_agent";
    }
    if ((!target_node || !target_node[0]) && (!target_role || !target_role[0])) {
        cJSON_Delete(root);
        snprintf(output, output_size,
                 "Error: target_node or target_role is required for action=%s",
                 action);
        return ESP_ERR_INVALID_ARG;
    }
    if (target_role && target_role[0]) {
        if (is_sensor_action(action) && strcmp(target_role, "sensor_agent") != 0) {
            cJSON_Delete(root);
            snprintf(output, output_size,
                     "Error: action=%s must target sensor_agent, got %s",
                     action, target_role);
            return ESP_ERR_INVALID_ARG;
        }
        if (is_control_action(action) && strcmp(target_role, "control_agent") != 0) {
            cJSON_Delete(root);
            snprintf(output, output_size,
                     "Error: action=%s must target control_agent, got %s",
                     action, target_role);
            return ESP_ERR_INVALID_ARG;
        }
    }

    char action_copy[ESPAGENT_MESH_ACTION_MAX] = {0};
    char command_id_copy[ESPAGENT_MESH_ID_MAX] = {0};
    char trace_id_copy[ESPAGENT_MESH_TRACE_MAX] = {0};
    char target_role_copy[ESPAGENT_MESH_ROLE_MAX] = {0};
    char target_node_copy[ESPAGENT_MESH_NODE_MAX] = {0};
    copy_text(action_copy, sizeof(action_copy), action);
    copy_text(target_role_copy, sizeof(target_role_copy), target_role);
    copy_text(target_node_copy, sizeof(target_node_copy), target_node);

    char topic[160] = {0};
    esp_err_t topic_err = ESP_OK;
    if (target_node_copy[0]) {
        topic_err = espagent_mesh_build_node_topic(target_node_copy, "command", topic, sizeof(topic));
    } else {
        topic_err = espagent_mesh_build_role_topic(target_role_copy, "command", topic, sizeof(topic));
    }
    if (topic_err != ESP_OK) {
        cJSON_Delete(root);
        snprintf(output, output_size, "Error: failed to build MQTT command topic");
        return topic_err;
    }

    cJSON *cmd = cJSON_CreateObject();
    if (!cmd) {
        cJSON_Delete(root);
        snprintf(output, output_size, "Error: out of memory");
        return ESP_ERR_NO_MEM;
    }

    const char *command_id = json_string(root, "command_id");
    char generated_id[40] = {0};
    if (!command_id || !command_id[0]) {
        snprintf(generated_id, sizeof(generated_id), "cmd-%lld", (long long)(esp_timer_get_time() / 1000));
        command_id = generated_id;
    }
    copy_text(command_id_copy, sizeof(command_id_copy), command_id);

    const char *trace_id = json_string(root, "trace_id");
    char generated_trace_id[48] = {0};
    if (!trace_id || !trace_id[0]) {
        snprintf(generated_trace_id, sizeof(generated_trace_id), "trace-%s", command_id_copy);
        trace_id = generated_trace_id;
    }
    copy_text(trace_id_copy, sizeof(trace_id_copy), trace_id);

    int ttl_ms = json_int(root, "ttl_ms", 30000);
    if (ttl_ms < 1000) {
        ttl_ms = 1000;
    } else if (ttl_ms > 30000) {
        ttl_ms = 30000;
    }
    int safety_level = json_int(root, "safety_level", 1);
    if (safety_level < ESPAGENT_MESH_SAFETY_LOW ||
        safety_level > ESPAGENT_MESH_SAFETY_HIGH) {
        cJSON_Delete(cmd);
        cJSON_Delete(root);
        snprintf(output, output_size, "Error: safety_level must be 0, 1, or 2");
        return ESP_ERR_INVALID_ARG;
    }
    bool require_ack = json_bool(root, "require_ack", true);

    cJSON_AddStringToObject(cmd, "command_id", command_id_copy);
    cJSON_AddStringToObject(cmd, "trace_id", trace_id_copy);
    if (target_node_copy[0]) {
        cJSON_AddStringToObject(cmd, "target_node", target_node_copy);
    }
    if (target_role_copy[0]) {
        cJSON_AddStringToObject(cmd, "target_role", target_role_copy);
    }
    cJSON_AddStringToObject(cmd, "action", action);
    cJSON_AddNumberToObject(cmd, "ttl_ms", ttl_ms);
    cJSON_AddNumberToObject(cmd, "safety_level", safety_level);
    cJSON_AddBoolToObject(cmd, "require_ack", require_ack);

    esp_err_t args_err = copy_args(root, cmd);
    if (args_err != ESP_OK) {
        cJSON_Delete(cmd);
        cJSON_Delete(root);
        snprintf(output, output_size, "Error: args_json is not valid JSON");
        return args_err;
    }

    char *payload = cJSON_PrintUnformatted(cmd);
    cJSON_Delete(cmd);
    cJSON_Delete(root);
    if (!payload) {
        snprintf(output, output_size, "Error: failed to serialize command");
        return ESP_ERR_NO_MEM;
    }

    char policy_json[512] = {0};
    char policy_reason[160] = {0};
    esp_err_t policy_err = request_policy_decision(command_id_copy,
                                                   trace_id_copy,
                                                   target_role_copy,
                                                   target_node_copy,
                                                   action_copy,
                                                   safety_level,
                                                   ttl_ms,
                                                   policy_json,
                                                   sizeof(policy_json),
                                                   policy_reason,
                                                   sizeof(policy_reason));
    if (policy_err != ESP_OK) {
        snprintf(output, output_size,
                 "Error: Guardian policy blocked mesh command action=%s command_id=%s reason=%s decision=%s",
                 action_copy, command_id_copy, policy_reason, policy_json[0] ? policy_json : "(none)");
        (void)sensor_mqtt_publish_timeline_event("policy",
                                                 "policy_check",
                                                 "blocked",
                                                 output,
                                                 command_id_copy,
                                                 target_role_copy,
                                                 target_node_copy,
                                                 action_copy);
        cJSON_free(payload);
        return policy_err;
    }

    (void)sensor_mqtt_publish_timeline_event("policy",
                                             "policy_check",
                                             "ok",
                                             policy_reason[0] ? policy_reason : "Guardian allowed command",
                                             command_id_copy,
                                             target_role_copy,
                                             target_node_copy,
                                             action_copy);

    esp_err_t err = sensor_mqtt_publish_text(topic, payload);
    if (err == ESP_OK) {
        snprintf(output, output_size,
                 "OK: queued MQTT mesh command action=%s topic=%s command_id=%s",
                 action_copy, topic, command_id_copy);
        (void)sensor_mqtt_publish_timeline_event("dispatch",
                                                 "mesh_command_queued",
                                                 "ok",
                                                 output,
                                                 command_id_copy,
                                                 target_role_copy,
                                                 target_node_copy,
                                                 action_copy);
        if (require_ack) {
            char output_json[768] = {0};
            uint32_t wait_ms = ttl_ms > 0 ? (uint32_t)ttl_ms : 30000U;
            esp_err_t wait_err = sensor_mqtt_wait_output_message(command_id_copy,
                                                                 output_json,
                                                                 sizeof(output_json),
                                                                 wait_ms);
            if (wait_err == ESP_OK) {
                snprintf(output, output_size,
                         "OK: mesh command completed command_id=%s output_message=%s",
                         command_id_copy, output_json);
            } else {
                snprintf(output, output_size,
                         "OK: queued MQTT mesh command action=%s topic=%s command_id=%s; OutputMessage wait timed out after %ums",
                         action_copy, topic, command_id_copy, (unsigned)wait_ms);
            }
        }
    } else {
        snprintf(output, output_size,
                 "Error: failed to queue MQTT mesh command (%s)",
                 esp_err_to_name(err));
        (void)sensor_mqtt_publish_timeline_event("dispatch",
                                                 "mesh_command_queued",
                                                 "error",
                                                 output,
                                                 command_id_copy,
                                                 target_role_copy,
                                                 target_node_copy,
                                                 action_copy);
    }
    cJSON_free(payload);
    return err;
}
