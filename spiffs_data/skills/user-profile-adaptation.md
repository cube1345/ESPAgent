# User Profile Adaptation

Maintain a slowly evolving user profile for preferences, habits, tolerance
thresholds, routines, and environment comfort rules.

## When to use

Use this when the user repeatedly expresses a preference, corrects the agent's
assumption, reacts to an environment condition, asks for personalized proactive
behavior, or changes a previously learned habit.

Typical examples:

- "30% humidity is too dry, turn on the humidifier."
- "I now feel dry even around 40% humidity."
- "Do not remind me about weather at night."
- "If the room is bright after work hours, remind me."
- "I prefer the light blue when reading."

## Storage

Use `/spiffs/memory/MEMORY.md` for stable profile facts and
`/spiffs/memory/daily/<YYYY-MM-DD>.md` for raw daily evidence.

Recommended MEMORY.md section:

```markdown
## User Profile

### Comfort thresholds
- Humidity: user currently tends to treat `<threshold>%RH` as dry.
  Evidence: <short dated evidence list>.
  Confidence: low|medium|high.
  Last reviewed: YYYY-MM-DD.

### Automation preferences
- <condition> -> <preferred action>, with safety notes.

### Corrections and conflicts
- <old belief> was corrected by <new evidence>.
```

## Update policy

1. Prefer slow updates. Review profile updates at most once per day unless the
   user explicitly says "remember this", "update my preference", or "from now on".
2. Always call `get_current_time` before writing dated evidence.
3. Before changing MEMORY.md, use `read_file /spiffs/memory/MEMORY.md`.
4. Record raw evidence in today's daily note first when the signal is weak.
5. Promote a preference into MEMORY.md only when one of these is true:
   - The user explicitly states a stable preference.
   - The same pattern appears at least 2-3 times across separate interactions.
   - The user corrects an existing profile item.
6. Do not overwrite an old profile item silently. Add a correction note with
   date, old value, new value, reason, and confidence.
7. If new behavior strictly conflicts with the existing profile, treat it as
   possible drift rather than an error. Lower the old confidence, add evidence,
   and update the threshold only after repeated confirmation or explicit user
   instruction.
8. Keep profile entries compact. Store the preference, threshold, confidence,
   and evidence summary, not the full conversation.

## Humidity example

If the user says:

> "30% humidity is unacceptable; turn on the humidifier."

Record that the user dislikes 30%RH humidity. If this happens repeatedly, update
the profile to say the user treats around 30%RH as too dry.

If later the user repeatedly says 40%RH is also too dry, update the same profile
entry:

```markdown
- Humidity: user currently tends to treat humidity at or below 40%RH as dry.
  Evidence: 2026-xx-xx user asked for humidifier at 30%RH; 2026-xx-xx user
  complained at 40%RH twice.
  Confidence: medium.
  Last reviewed: 2026-xx-xx.
```

Do not claim "the room is dry" as an objective fact when acting from this
profile. Say the action is based on the user's learned comfort preference, for
example: "Humidity is near your dry threshold, so I am turning on the
humidifier."

## Acting on profile facts

For one-off actions, use the proper hardware or Mesh tool.

For persistent background behavior, create an automation rule instead of
keeping an LLM turn open. For example, a learned humidity threshold can become:

```json
{
  "name": "user_humidity_comfort_rule",
  "sensor": "humidity_percent",
  "operator": "<",
  "threshold": 40,
  "action": {
    "target_role": "control_agent",
    "action": "humidifier_on",
    "args": {}
  }
}
```

Hardware actions must still go through the normal ESPAgent safety path:
`automation_create_rule` or `mesh_send_command`, Guardian policy, Control
whitelist, and final OutputMessage. The user profile does not bypass safety.

## Privacy and safety

- Store only useful preferences and environment habits.
- Avoid sensitive personal details unless the user explicitly asks the agent to
  remember them.
- Do not infer medical, psychological, financial, or identity attributes from
  weak signals.
- If a profile-driven action is potentially risky, costly, noisy, or privacy
  sensitive, ask for confirmation before creating or changing automation.
