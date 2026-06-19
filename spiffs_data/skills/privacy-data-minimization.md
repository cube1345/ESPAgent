# Privacy Data Minimization

Protect smart-home privacy by keeping raw personal signals local, classifying
data sensitivity, and sending only the minimum necessary summary to LLMs,
MQTT, display terminals, or external APIs.

## When to use

Use this when handling home telemetry, presence, camera, microphone, user
profile, routines, personal habits, Feishu messages, memory, sessions, or any
request that may reveal private household behavior.

## Principle

Do privacy filtering before data leaves the local trust boundary.

Correct path:

```text
Sensor raw data
  -> local Guardian / local rules / local gateway sanitization
  -> minimal summary or allow/deny result
  -> Coordinator
  -> remote LLM only when needed
```

Do not send raw sensitive data to a remote LLM just to ask whether it is safe.

## Data classes

- `public`: generic project status, non-user documentation.
- `low`: temperature, humidity, weather, basic non-identifying device state.
- `medium`: light level, air quality, device usage pattern, room-level state.
- `high`: presence, sleep/wake routine, door/window state, location inference,
  household occupancy, user profile preferences.
- `restricted`: camera raw frames, microphone raw audio, voice transcript,
  identity attributes, health/medical inference, secrets, credentials.

## Handling rules

1. Send only the fields needed for the task.
2. Prefer boolean or coarse summaries over raw timelines.
3. Do not send camera frames, microphone audio, voice transcripts, or presence
   timelines to remote LLMs by default.
4. Do not put secrets, API keys, Feishu tokens, Wi-Fi passwords, full chat logs,
   or raw private telemetry into MQTT payloads.
5. Store user profile facts as compact preferences with evidence summaries, not
   complete conversations.
6. For high or restricted data, default to `deny`, `sanitize`, or
   `require_confirm`.
7. If a reply needs natural language, ask the LLM to phrase a sanitized result;
   do not include the original sensitive evidence.

## Examples

Presence event:

Bad:

```json
{"room":"bedroom","presence":true,"time":"23:41","history":["..."]}
```

Better:

```json
{"privacy_level":"high","event":"authorized_rule_matched","allowed_for_llm":false}
```

Humidity comfort:

Low-risk summary can be sent:

```json
{"humidity_percent":38,"user_threshold_percent":40,"reason":"comfort_rule"}
```

User-facing wording should say the action is based on learned preference:

```text
Humidity is near your dry threshold, so I am turning on the humidifier.
```

## MQTT and display terminals

P4 and Android should consume sanitized state, telemetry, timeline, and
OutputMessage streams. They should not receive raw private timelines unless the
user explicitly enables a local debug mode.

For production, MQTT should run on a trusted LAN/VPN or use TLS, authentication,
and ACLs. The current public broker style is development-only.

## Memory policy

Before writing `/spiffs/memory/MEMORY.md` or daily notes:

1. Ask whether the information is useful for future behavior.
2. Avoid sensitive attributes unless explicitly requested by the user.
3. Prefer "user prefers humidity above 40%RH" over raw event history.
4. Use dates and confidence for profile facts.
5. Remove or revise stale preferences when later evidence conflicts.

## Research basis

This skill follows OWASP LLM risks around sensitive information disclosure and
prompt injection, NIST AI RMF privacy/risk governance practices, and agent-tool
security guidance that recommends local filtering, least data, scoped access,
and auditable data flows.
