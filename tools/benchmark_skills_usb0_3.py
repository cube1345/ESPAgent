#!/usr/bin/env python3
"""ESPAgent runtime skill benchmark for ESP32-S3 boards.

The benchmark uses only /dev/ttyUSB0-3 by default. It can run simple serial CLI
checks and agent-loop injection cases, then scores each case from serial logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import sys
import termios
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PORTS = [f"/dev/ttyUSB{i}" for i in range(4)]
EXPECTED_ROLES = {
    "/dev/ttyUSB0": "coordinator_agent",
    "/dev/ttyUSB1": "sensor_agent",
    "/dev/ttyUSB2": "control_agent",
    "/dev/ttyUSB3": "guardian_agent",
}
CRASH_PATTERNS = (
    "Guru Meditation",
    "panic",
    "abort()",
    "assert failed",
    "Backtrace:",
    "stack canary",
    "StoreProhibited",
    "LoadProhibited",
)


@dataclass
class PortState:
    port: str
    fd: int
    buffer: str = ""
    text: str = ""
    role: str | None = None
    node_id: str | None = None
    lines: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case_id: str
    name: str
    skill: str
    passed: bool
    mode: str
    duration_s: float
    matched_expect: list[str] = field(default_factory=list)
    matched_expect_all: list[str] = field(default_factory=list)
    missing_expect_all: list[str] = field(default_factory=list)
    matched_forbidden: list[str] = field(default_factory=list)
    crashes: int = 0
    details: str = ""


def configure_serial(fd: int) -> None:
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = termios.B115200
    attrs[5] = termios.B115200
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def open_ports(required_ports: list[str]) -> dict[int, PortState]:
    missing = [port for port in required_ports if not os.path.exists(port)]
    if missing:
        print("ERROR: missing required ESP32-S3 ttyUSB ports:", ", ".join(missing), file=sys.stderr)
        print("ERROR: this benchmark does not use /dev/ttyACM*.", file=sys.stderr)
        sys.exit(2)

    states: dict[int, PortState] = {}
    for port in required_ports:
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        configure_serial(fd)
        states[fd] = PortState(port=port, fd=fd)
        try:
            os.read(fd, 65535)
        except BlockingIOError:
            pass
    return states


def close_ports(states: dict[int, PortState]) -> None:
    for fd in list(states):
        try:
            os.close(fd)
        except OSError:
            pass


def state_for_port(states: dict[int, PortState], port: str) -> PortState:
    for state in states.values():
        if state.port == port:
            return state
    raise KeyError(port)


def write_line(state: PortState, line: str) -> None:
    if not line.endswith("\n"):
        line += "\n"
    os.write(state.fd, line.encode("utf-8"))


def drain(states: dict[int, PortState], seconds: float, echo: bool) -> str:
    start_snapshot = {fd: len(st.text) for fd, st in states.items()}
    end = time.time() + seconds
    while time.time() < end:
        readable, _, _ = select.select(list(states), [], [], 0.2)
        for fd in readable:
            state = states[fd]
            try:
                data = os.read(fd, 8192)
            except BlockingIOError:
                data = b""
            if not data:
                continue
            chunk = data.decode("utf-8", "replace")
            state.text += chunk
            state.buffer += chunk
            lines = state.buffer.splitlines(keepends=True)
            if lines and not lines[-1].endswith(("\n", "\r")):
                state.buffer = lines.pop()
            else:
                state.buffer = ""
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                state.lines.append(line)
                if echo and interesting(line):
                    print(f"{state.port}: {line}")

    chunks = []
    for fd, state in states.items():
        chunks.append(state.text[start_snapshot[fd]:])
    return "\n".join(chunks)


def interesting(line: str) -> bool:
    keys = (
        "BENCH-",
        "=== CONV ===",
        "Tool use iteration",
        "Executing tool:",
        "sandbox denied",
        "mesh_send_command",
        "automation_create_workflow",
        "automation_create_rule",
        "policy_check",
        "policy_decision",
        "Mesh role command received",
        "Mesh sensor command executed",
        "Mesh control command executed",
        "OutputMessage",
        "Queue final response",
        "Error:",
        "W (",
        "E (",
    )
    return any(key in line for key in keys) or any(key in line for key in CRASH_PATTERNS)


def find_config_field(text: str, label: str) -> str | None:
    value = None
    for line in text.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
        if not line.startswith(label) or ":" not in line:
            continue
        value = line.split(":", 1)[1].strip()
        value = re.sub(r"\s+\[[^\]]+\]$", "", value).strip()
    return value


def request_config(states: dict[int, PortState], strict_roles: bool) -> bool:
    for state in states.values():
        write_line(state, "config_show")
    drain(states, 7, echo=False)

    ok = True
    print("===== role check =====")
    for port in sorted(st.port for st in states.values()):
        state = state_for_port(states, port)
        state.role = find_config_field(state.text, "Node Role")
        state.node_id = find_config_field(state.text, "Node ID")
        expected = EXPECTED_ROLES.get(port)
        status = "OK"
        if strict_roles and expected and state.role != expected:
            status = "MISMATCH"
            ok = False
        print(f"{port}: node={state.node_id or 'unknown'} role={state.role or 'unknown'} expected={expected or 'n/a'} {status}")
    return ok


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return cases


def first_markdown_heading(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    return line
    except OSError:
        pass
    return f"# {path.stem}"


def append_auto_skill_cases(cases: list[dict[str, Any]], skills_dir: Path) -> list[dict[str, Any]]:
    """Add one serial readability case for every local SPIFFS skill file."""
    existing = {str(case.get("id", "")) for case in cases}
    out = list(cases)
    for path in sorted(skills_dir.glob("*.md")):
        name = path.stem
        case_id = f"skill_read_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}"
        if case_id in existing:
            continue
        heading = first_markdown_heading(path)
        out.append({
            "id": case_id,
            "name": f"skill file readable: {name}",
            "mode": "serial",
            "port": "/dev/ttyUSB0",
            "command": f"skill_show {name}",
            "skill": name,
            "auto_generated": True,
            "expect_all": [re.escape(heading)],
            "expect_any": [re.escape(heading), "When to use", "Core rule", "How to use"],
            "must_not": ["Skill not found", "Failed to read"],
            "timeout_s": 6,
        })
    return out


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    case_ids: set[str] = set()
    for index, case in enumerate(cases, 1):
        prefix = f"case #{index}"
        case_id = str(case.get("id", ""))
        if not case_id:
            errors.append(f"{prefix}: missing id")
        elif case_id in case_ids:
            errors.append(f"{prefix}: duplicate id {case_id}")
        else:
            case_ids.add(case_id)

        mode = str(case.get("mode", ""))
        if mode not in ("serial", "inject"):
            errors.append(f"{case_id or prefix}: unsupported mode {mode!r}")
        if mode == "serial" and not case.get("command"):
            errors.append(f"{case_id or prefix}: serial case missing command")
        if mode == "inject" and not case.get("prompt"):
            errors.append(f"{case_id or prefix}: inject case missing prompt")

        port = str(case.get("port", ""))
        if port and not port.startswith("/dev/ttyUSB"):
            errors.append(f"{case_id or prefix}: port must be /dev/ttyUSB*, got {port}")
        if not case.get("expect_any") and not case.get("expect_all"):
            errors.append(f"{case_id or prefix}: missing expect_any or expect_all")
        try:
            float(case.get("timeout_s", 30))
        except (TypeError, ValueError):
            errors.append(f"{case_id or prefix}: invalid timeout_s")
    return errors


def print_case_list(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        print(
            f"{case.get('id', '')}\t"
            f"{case.get('mode', '')}\t"
            f"{case.get('port', '')}\t"
            f"{case.get('skill', '')}\t"
            f"{case.get('name', '')}"
        )


def pattern_matches(text: str, pattern: str) -> bool:
    try:
        return re.search(pattern, text, re.IGNORECASE | re.MULTILINE) is not None
    except re.error:
        return pattern.lower() in text.lower()


def score_text_without_input(case: dict[str, Any], text: str) -> str:
    """Remove command echo and injected user text before matching expectations.

    ESP-IDF console usually echoes the command line. Scoring that echo caused
    false positives for privacy cases and false negatives for prompt-injection
    cases because forbidden phrases were present in the user's prompt itself.
    The raw case log is still preserved; only scoring uses this sanitized view.
    """
    redacted = text
    for field in ("command", "prompt"):
        value = str(case.get(field, ""))
        if value:
            redacted = redacted.replace(value, "")
    chat_id = str(case.get("chat_id", ""))
    if chat_id:
        redacted = "\n".join(
            line for line in redacted.splitlines()
            if not (line.startswith("inject_msg ") and chat_id in line)
        )
    return redacted


def score_case(case: dict[str, Any], text: str, duration_s: float) -> CaseResult:
    score_text = score_text_without_input(case, text)
    expect = [str(x) for x in case.get("expect_any", [])]
    expect_all = [str(x) for x in case.get("expect_all", [])]
    forbidden = [str(x) for x in case.get("must_not", [])]
    matched_expect = [p for p in expect if pattern_matches(score_text, p)]
    matched_expect_all = [p for p in expect_all if pattern_matches(score_text, p)]
    missing_expect_all = [p for p in expect_all if p not in matched_expect_all]
    matched_forbidden = [p for p in forbidden if pattern_matches(score_text, p)]
    crashes = sum(score_text.count(pattern) for pattern in CRASH_PATTERNS)
    has_any = bool(matched_expect) if expect else True
    has_all = not missing_expect_all
    passed = has_any and has_all and not matched_forbidden and crashes == 0
    details = ""
    if not has_any:
        details = "no expected signal matched"
    if missing_expect_all:
        details = f"required signal missing: {missing_expect_all[0]}"
    if matched_forbidden:
        details = f"forbidden signal matched: {matched_forbidden[0]}"
    if crashes:
        details = f"crash pattern matched: {crashes}"
    return CaseResult(
        case_id=str(case.get("id", "")),
        name=str(case.get("name", "")),
        skill=str(case.get("skill", "")),
        passed=passed,
        mode=str(case.get("mode", "")),
        duration_s=duration_s,
        matched_expect=matched_expect,
        matched_expect_all=matched_expect_all,
        missing_expect_all=missing_expect_all,
        matched_forbidden=matched_forbidden,
        crashes=crashes,
        details=details,
    )


def run_case(states: dict[int, PortState], case: dict[str, Any], echo: bool) -> tuple[CaseResult, str]:
    port = str(case.get("port", "/dev/ttyUSB0"))
    timeout_s = float(case.get("timeout_s", 30))
    state = state_for_port(states, port)
    mode = str(case.get("mode", "serial"))

    start = time.time()
    if mode == "serial":
        command = str(case["command"])
        write_line(state, command)
    elif mode == "inject":
        channel = str(case.get("channel", "system"))
        chat_id = str(case.get("chat_id", case.get("id", "bench")))
        prompt = str(case["prompt"])
        write_line(state, f"inject_msg {channel} {chat_id} {prompt}")
    else:
        raise ValueError(f"unsupported case mode: {mode}")

    text = drain(states, timeout_s, echo=echo)
    duration_s = time.time() - start
    result = score_case(case, text, duration_s)
    return result, text


def write_artifacts(out_dir: Path,
                    run_id: str,
                    states: dict[int, PortState],
                    results: list[CaseResult],
                    case_logs: dict[str, str],
                    cases_path: Path,
                    resource_snapshots: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for state in states.values():
        name = state.port.rsplit("/", 1)[-1]
        (out_dir / f"skills_benchmark_{run_id}_{name}.log").write_text(
            state.text, encoding="utf-8", errors="replace")

    for case_id, text in case_logs.items():
        (out_dir / f"skills_benchmark_{run_id}_{case_id}.case.log").write_text(
            text, encoding="utf-8", errors="replace")

    summary = build_summary(run_id, results, cases_path, resource_snapshots)
    (out_dir / f"skills_benchmark_{run_id}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8")


def build_summary(run_id: str,
                  results: list[CaseResult],
                  cases_path: Path,
                  resource_snapshots: dict[str, Any] | None = None) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    by_skill: dict[str, dict[str, int]] = {}
    for result in results:
        item = by_skill.setdefault(result.skill or "unknown", {"passed": 0, "total": 0})
        item["total"] += 1
        if result.passed:
            item["passed"] += 1
    return {
        "run_id": run_id,
        "cases": str(cases_path),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0.0,
        "by_skill": by_skill,
        "resources": resource_snapshots or {},
        "results": [result.__dict__ for result in results],
    }


def parse_resource_snapshot(text: str) -> dict[str, int]:
    fields = {
        "internal_free": r"Internal free:\s+(\d+)\s+bytes",
        "psram_free": r"PSRAM free:\s+(\d+)\s+bytes",
        "total_free": r"Total free:\s+(\d+)\s+bytes",
        "cache_entries": r"Cache entries:\s+(\d+)/",
        "cache_bytes": r"Cache bytes:\s+(\d+)/",
        "cache_hits": r"Cache hits:\s+(\d+)",
        "cache_misses": r"Cache misses:\s+(\d+)",
        "cache_evictions": r"Cache evictions:\s+(\d+)",
    }
    out: dict[str, int] = {}
    for key, pattern in fields.items():
        match = re.search(pattern, text)
        if match:
            out[key] = int(match.group(1))
    return out


def collect_resources(states: dict[int, PortState], label: str, echo: bool) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    for state in states.values():
        before = len(state.text)
        write_line(state, "heap_info")
        write_line(state, "cache_stats")
        drain({state.fd: state}, 3.0, echo=echo)
        text = state.text[before:]
        snapshots[state.port] = parse_resource_snapshot(text)
    print(f"===== resources: {label} =====")
    for port in sorted(snapshots):
        snap = snapshots[port]
        if not snap:
            print(f"{port}: unavailable")
            continue
        print(
            f"{port}: internal={snap.get('internal_free', -1)} "
            f"psram={snap.get('psram_free', -1)} "
            f"total={snap.get('total_free', -1)} "
            f"cache={snap.get('cache_entries', -1)} entries/{snap.get('cache_bytes', -1)} bytes"
        )
    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ESPAgent skill benchmark over /dev/ttyUSB0-3")
    parser.add_argument("--cases", default="benchmarks/skills/espagent_skill_benchmark.jsonl")
    parser.add_argument("--out-dir", default="artifacts/skills_benchmark")
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--ports", nargs="*", default=PORTS)
    parser.add_argument("--no-role-check", action="store_true")
    parser.add_argument("--echo", action="store_true")
    parser.add_argument("--case-filter", default="", help="Run only cases whose id/name/skill contains this text")
    parser.add_argument("--skills-dir", default="spiffs_data/skills")
    parser.add_argument("--no-auto-skill-cases", action="store_true", help="Do not append one readability case for every SPIFFS skill file")
    parser.add_argument("--no-resource-snapshot", action="store_true", help="Do not collect heap/cache snapshots before and after the run")
    parser.add_argument("--list-cases", action="store_true", help="List selected benchmark cases without opening serial ports")
    parser.add_argument("--validate-only", action="store_true", help="Validate benchmark case schema without opening serial ports")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    cases = load_cases(cases_path)
    if not args.no_auto_skill_cases:
        cases = append_auto_skill_cases(cases, Path(args.skills_dir))
    if args.case_filter:
        needle = args.case_filter.lower()
        cases = [
            case for case in cases
            if needle in str(case.get("id", "")).lower()
            or needle in str(case.get("name", "")).lower()
            or needle in str(case.get("skill", "")).lower()
        ]
    if not cases:
        print("ERROR: no benchmark cases selected", file=sys.stderr)
        return 2
    case_errors = validate_cases(cases)
    if case_errors:
        for error in case_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.list_cases:
        print_case_list(cases)
        return 0
    if args.validate_only:
        print(f"OK: {len(cases)} benchmark cases validated from {cases_path}")
        return 0

    states = open_ports(args.ports)
    results: list[CaseResult] = []
    case_logs: dict[str, str] = {}
    resource_snapshots: dict[str, Any] = {}
    try:
        if not request_config(states, strict_roles=not args.no_role_check):
            print("ERROR: role check failed. Use --no-role-check only for single-board local checks.", file=sys.stderr)
            return 2

        if not args.no_resource_snapshot:
            resource_snapshots["before"] = collect_resources(states, "before", echo=args.echo)

        print("===== skill benchmark =====")
        for index, case in enumerate(cases, 1):
            case_id = str(case.get("id", f"case_{index}"))
            print(f"[{index}/{len(cases)}] {case_id}: {case.get('name', '')}")
            result, text = run_case(states, case, echo=args.echo)
            results.append(result)
            case_logs[case_id] = text
            status = "PASS" if result.passed else "FAIL"
            print(f"  {status}: matched={result.matched_expect} forbidden={result.matched_forbidden} {result.details}")
            drain(states, 1.0, echo=False)

        if not args.no_resource_snapshot:
            resource_snapshots["after"] = collect_resources(states, "after", echo=args.echo)
    finally:
        out_dir = Path(args.out_dir)
        write_artifacts(out_dir, args.run_id, states, results, case_logs, cases_path, resource_snapshots)
        close_ports(states)

    summary = build_summary(args.run_id, results, cases_path, resource_snapshots)
    print("===== summary =====")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
