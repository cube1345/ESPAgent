#pragma once

#include "esp_err.h"

#include <stddef.h>

typedef enum {
    ESPAGENT_TOOL_RISK_READ_ONLY = 0,
    ESPAGENT_TOOL_RISK_LOW_CONTROL = 1,
    ESPAGENT_TOOL_RISK_MEDIUM_CONTROL = 2,
    ESPAGENT_TOOL_RISK_HIGH_CONTROL = 3,
    ESPAGENT_TOOL_RISK_PRIVACY = 4,
    ESPAGENT_TOOL_RISK_SYSTEM = 5,
} espagent_tool_risk_t;

const char *tool_sandbox_risk_name(espagent_tool_risk_t risk);

esp_err_t tool_sandbox_check(const char *name,
                             const char *input_json,
                             char *reason,
                             size_t reason_size);
