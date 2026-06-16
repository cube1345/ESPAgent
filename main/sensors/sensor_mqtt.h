#pragma once

#include "esp_err.h"

esp_err_t sensor_mqtt_start(void);
esp_err_t sensor_mqtt_publish_text(const char *topic, const char *payload);
esp_err_t sensor_mqtt_publish_node_event(const char *event_type, const char *detail);
esp_err_t sensor_mqtt_publish_timeline_event(const char *phase,
                                             const char *event_type,
                                             const char *status,
                                             const char *summary,
                                             const char *command_id,
                                             const char *target_role,
                                             const char *target_node,
                                             const char *action);
