#!/usr/bin/env python3
"""Registry-aware AgentTUI lifecycle and direct-message helper."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple


PROTOCOL = "ARBORIST-DIRECT:v1"
SUPPORTED_BRANDS = frozenset({"claude-code", "codex"})
LARGE_TRANSCRIPT_BYTES = 2_000_000
CODEX_PANE_SUBMIT_DELAY_SECONDS = 1.0
# Codex's busy-TUI queue shortcut is Tab; Enter steers the current turn.
CODEX_PANE_QUEUE_BYTE = "9"
PANE_ENTER_BYTE = "13"
PANE_VERIFY_ATTEMPTS = 10
PANE_VERIFY_INTERVAL_SECONDS = 0.1
NONCE_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")


class RegistryError(RuntimeError):
    """The registry is incomplete, inconsistent, or unsafe to use."""


class AgentRecord(NamedTuple):
    name: str
    brand: str
    role: str | None
    project_path: Path
    project_id: str
    session_id: str
    session_file: Path
    state: str
    last_seen: str
    pane_ref: dict[str, str] | None
    spec_path: Path
    runtime_path: Path


class DeliveryRoute(NamedTuple):
    argv: list[str]
    cwd: Path
    submit_argv: list[str] | None = None
    mode: str = "resume"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"missing registry file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"invalid JSON in registry file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistryError(f"registry file must contain an object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{label} must be a non-empty string")
    return value


def load_agent(repo: Path, name: str) -> AgentRecord:
    leaf = repo / ".arborist" / "agents" / name
    spec_path = leaf / "spec.json"
    runtime_path = leaf / "runtime.json"
    spec = read_json(spec_path)
    runtime = read_json(runtime_path)

    spec_name = require_text(spec.get("name"), f"{spec_path}: name")
    if spec_name != name:
        raise RegistryError(
            f"registry name mismatch: directory={name!r}, spec.name={spec_name!r}"
        )

    project = spec.get("project")
    if not isinstance(project, dict):
        raise RegistryError(f"{spec_path}: project must be an object")

    project_path = Path(
        require_text(project.get("path"), f"{spec_path}: project.path")
    ).resolve()
    if not project_path.is_dir():
        raise RegistryError(f"registered project path is not a directory: {project_path}")

    state = require_text(runtime.get("state"), f"{runtime_path}: state")
    if state not in {"active", "stopped", "idle"}:
        raise RegistryError(f"{runtime_path}: unsupported state {state!r}")
    pane_ref_value = runtime.get("pane_ref")
    pane_ref: dict[str, str] | None = None
    if pane_ref_value is not None:
        if not isinstance(pane_ref_value, dict):
            raise RegistryError(f"{runtime_path}: pane_ref must be an object or null")
        pane_ref = {
            "multiplexer": require_text(
                pane_ref_value.get("multiplexer"),
                f"{runtime_path}: pane_ref.multiplexer",
            ),
            "session": require_text(
                pane_ref_value.get("session"), f"{runtime_path}: pane_ref.session"
            ),
            "pane_id": require_text(
                pane_ref_value.get("pane_id"), f"{runtime_path}: pane_ref.pane_id"
            ),
        }

    return AgentRecord(
        name=name,
        brand=require_text(spec.get("brand"), f"{spec_path}: brand"),
        role=spec.get("role") if isinstance(spec.get("role"), str) else None,
        project_path=project_path,
        project_id=require_text(project.get("project_id"), f"{spec_path}: project_id"),
        session_id=require_text(
            runtime.get("session_id"), f"{runtime_path}: session_id"
        ),
        session_file=Path(
            require_text(runtime.get("session_file"), f"{runtime_path}: session_file")
        ),
        state=state,
        last_seen=require_text(
            runtime.get("last_seen"), f"{runtime_path}: last_seen"
        ),
        pane_ref=pane_ref,
        spec_path=spec_path,
        runtime_path=runtime_path,
    )


def delivery_marker_fields(
    sender: AgentRecord,
    target: AgentRecord,
    nonce: str,
) -> list[str]:
    if not NONCE_PATTERN.fullmatch(nonce):
        raise RegistryError(
            "nonce must be a non-empty token containing only "
            "ASCII letters, digits, dot, underscore, colon, or hyphen"
        )
    return [
        f"from={sender.name}",
        f"from_brand={sender.brand}",
        f"to={target.name}",
        f"nonce={nonce}",
        "provenance=declared-not-authenticated",
    ]


def build_delivery_marker(
    sender: AgentRecord,
    target: AgentRecord,
    nonce: str,
) -> str:
    return " ".join(delivery_marker_fields(sender, target, nonce))


def build_envelope(
    sender: AgentRecord,
    target: AgentRecord,
    message: str,
    *,
    nonce: str,
    script_path: Path,
) -> str:
    if not message.strip():
        raise RegistryError("message must not be empty")
    marker_fields = delivery_marker_fields(sender, target, nonce)
    reply_command = shlex.join(
        [
            "python3",
            str(script_path),
            "send",
            "--from",
            target.name,
            "--to",
            sender.name,
            "--message",
            "<reply>",
        ]
    )
    return "\n".join(
        [
            f"[{PROTOCOL}]",
            *marker_fields,
            f"reply_command={reply_command}",
            "",
            "message:",
            message,
        ]
    )


def build_route(target: AgentRecord, envelope: str) -> DeliveryRoute:
    if target.pane_ref is not None and target.state in {"active", "idle"}:
        if target.pane_ref["multiplexer"] != "zellij":
            raise RegistryError(
                "unsupported pane multiplexer: "
                f"{target.pane_ref['multiplexer']!r}"
            )
        prefix = [
            "zellij",
            "--session",
            target.pane_ref["session"],
            "action",
        ]
        pane_message = " ".join(envelope.splitlines())
        submit_byte = (
            CODEX_PANE_QUEUE_BYTE
            if target.brand == "codex" and target.state == "active"
            else PANE_ENTER_BYTE
        )
        return DeliveryRoute(
            argv=[
                *prefix,
                "write-chars",
                "--pane-id",
                target.pane_ref["pane_id"],
                pane_message,
            ],
            cwd=target.project_path,
            submit_argv=[
                *prefix,
                "write",
                "--pane-id",
                target.pane_ref["pane_id"],
                submit_byte,
            ],
            mode="pane",
        )

    if target.brand == "claude-code":
        argv = [
            "claude",
            "-p",
            "--resume",
            target.session_id,
            "--output-format",
            "json",
            envelope,
        ]
    elif target.brand == "codex":
        if target.state == "active":
            raise RegistryError(
                "refusing bare codex exec resume for an active Codex TUI without "
                "pane_ref; register a reachable pane or use an app-server turn/steer "
                "adapter"
            )
        argv = ["codex", "exec", "resume", target.session_id, envelope]
    else:
        raise RegistryError(f"unsupported target brand: {target.brand!r}")
    return DeliveryRoute(argv=argv, cwd=target.project_path)


def parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegistryError(f"{label} is not a valid ISO8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise RegistryError(f"{label} must include a timezone: {value!r}")
    return parsed


def derive_effective_state(
    agent: AgentRecord,
    *,
    now: datetime | None = None,
    idle_after: timedelta = timedelta(minutes=15),
    stale_after: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    observed_at = now or datetime.now().astimezone()
    if observed_at.tzinfo is None:
        raise RegistryError("effective-state observation time must include a timezone")
    last_seen = parse_timestamp(agent.last_seen, f"{agent.runtime_path}: last_seen")

    if not agent.session_file.is_file():
        return {
            "declared_state": agent.state,
            "effective_state": "stopped",
            "diagnostic": "session-file-missing",
            "session_file_mtime": None,
        }

    mtime = datetime.fromtimestamp(
        agent.session_file.stat().st_mtime,
        tz=observed_at.tzinfo,
    )
    if agent.state == "stopped":
        if mtime > last_seen + timedelta(seconds=1):
            return {
                "declared_state": agent.state,
                "effective_state": "active",
                "diagnostic": "declared-stopped-but-transcript-newer",
                "session_file_mtime": mtime.isoformat(timespec="seconds"),
            }
        return {
            "declared_state": agent.state,
            "effective_state": "stopped",
            "diagnostic": None,
            "session_file_mtime": mtime.isoformat(timespec="seconds"),
        }

    age = observed_at - mtime
    if age < idle_after:
        effective = "active"
    elif age < stale_after:
        effective = "idle"
    else:
        effective = "stopped"
    return {
        "declared_state": agent.state,
        "effective_state": effective,
        "diagnostic": None if effective != "stopped" else "transcript-stale",
        "session_file_mtime": mtime.isoformat(timespec="seconds"),
    }


def plan_delivery(
    repo: Path,
    *,
    sender_name: str,
    target_name: str,
    message: str,
    nonce: str,
    script_path: Path,
) -> dict[str, Any]:
    sender = load_agent(repo, sender_name)
    target = load_agent(repo, target_name)
    if sender.brand not in SUPPORTED_BRANDS:
        raise RegistryError(f"unsupported sender brand: {sender.brand!r}")
    target_state = derive_effective_state(target)
    routed_target = target._replace(state=target_state["effective_state"])
    envelope = build_envelope(
        sender, target, message, nonce=nonce, script_path=script_path
    )
    route = build_route(routed_target, envelope)
    return {
        "protocol": PROTOCOL,
        "sender": sender.name,
        "sender_brand": sender.brand,
        "target": target.name,
        "target_brand": target.brand,
        "target_session_id": target.session_id,
        "target_declared_state": target.state,
        "target_effective_state": target_state["effective_state"],
        "target_state_diagnostic": target_state["diagnostic"],
        "target_session_file": str(target.session_file),
        "nonce": nonce,
        "delivery_marker": build_delivery_marker(sender, target, nonce),
        "cwd": str(route.cwd),
        "argv": route.argv,
        "submit_argv": route.submit_argv,
        "route_mode": route.mode,
    }


def update_global_summary(
    index_path: Path,
    agent: AgentRecord,
    *,
    state: str,
) -> None:
    index = read_json(index_path)
    projects = index.get("projects")
    if not isinstance(projects, list):
        raise RegistryError(f"{index_path}: projects must be an array")

    project_entry: dict[str, Any] | None = None
    for candidate in projects:
        if isinstance(candidate, dict) and candidate.get("project_id") == agent.project_id:
            project_entry = candidate
            break
    if project_entry is None:
        raise RegistryError(
            f"{index_path}: project {agent.project_id!r} is not registered"
        )

    agents = project_entry.get("agents")
    if not isinstance(agents, list):
        raise RegistryError(f"{index_path}: project agents must be an array")
    for summary in agents:
        if isinstance(summary, dict) and summary.get("name") == agent.name:
            summary["brand"] = agent.brand
            summary["state"] = state
            summary["session_id"] = agent.session_id
            atomic_write_json(index_path, index)
            return
    raise RegistryError(f"{index_path}: agent {agent.name!r} is not registered")


def write_runtime_state(
    repo: Path,
    name: str,
    *,
    state: str,
    now: str,
    global_index: Path | None,
    confirm_session_exit: bool = False,
) -> None:
    if state not in {"active", "stopped"}:
        raise RegistryError(f"state must be active or stopped, got {state!r}")
    if state == "stopped" and not confirm_session_exit:
        raise RegistryError(
            "refusing to mark stopped without explicit session termination "
            "confirmation; task/turn completion is not session termination"
        )

    agent = load_agent(repo, name)
    runtime = read_json(agent.runtime_path)
    runtime["state"] = state
    runtime["last_seen"] = now
    atomic_write_json(agent.runtime_path, runtime)
    if global_index is not None:
        update_global_summary(global_index, agent, state=state)


def current_session_id() -> str | None:
    codex_id = os.environ.get("CODEX_THREAD_ID")
    if codex_id:
        return codex_id
    context_id = os.environ.get("TRELLIS_CONTEXT_ID")
    if context_id:
        for prefix in ("codex_", "claude_"):
            if context_id.startswith(prefix):
                return context_id.removeprefix(prefix)
        return context_id
    return None


def require_current_session(agent: AgentRecord, supplied: str | None) -> None:
    actual = supplied or current_session_id()
    if not actual:
        raise RegistryError(
            "cannot identify the current session; pass --session-id explicitly"
        )
    if actual != agent.session_id:
        raise RegistryError(
            f"session mismatch for {agent.name!r}: "
            f"current={actual!r}, registered={agent.session_id!r}"
        )


def default_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def transcript_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def transcript_contains_marker(path: Path, marker: str, start_offset: int) -> bool:
    marker_parts = [part.encode() for part in marker.split(" ")]
    separator = rb"(?:[ \t\r\n]|\\[nr])+"
    encoded_marker = separator.join(re.escape(part) for part in marker_parts)
    try:
        with path.open("rb") as transcript:
            size = os.fstat(transcript.fileno()).st_size
            if size < start_offset:
                return False
            transcript.seek(start_offset)
            return re.search(encoded_marker, transcript.read()) is not None
    except FileNotFoundError:
        return False


def wait_for_transcript_marker(
    path: Path,
    marker: str,
    start_offset: int,
) -> bool:
    for _ in range(PANE_VERIFY_ATTEMPTS):
        if transcript_contains_marker(path, marker, start_offset):
            return True
        time.sleep(PANE_VERIFY_INTERVAL_SECONDS)
    return False


def create_parser() -> argparse.ArgumentParser:
    canonical_repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="AgentTUI registry lifecycle and cross-brand direct messaging"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=canonical_repo,
        help=(
            "repository containing .arborist/ "
            "(default: canonical root inferred from this script)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    send = subparsers.add_parser("send", help="direct-message a registered peer")
    send.add_argument("--from", dest="sender", required=True)
    send.add_argument("--to", dest="target", required=True)
    send.add_argument("--message", required=True)
    send.add_argument("--timeout", type=float, default=120.0)
    send.add_argument(
        "--pane-submit-delay",
        type=float,
        default=None,
        help=(
            "seconds between pane text injection and the submit key "
            f"(default: {CODEX_PANE_SUBMIT_DELAY_SECONDS} for Codex, 0 otherwise)"
        ),
    )
    send.add_argument("--dry-run", action="store_true")

    heartbeat = subparsers.add_parser(
        "heartbeat", help="declare the current registered session active"
    )
    heartbeat.add_argument("--name", required=True)
    heartbeat.add_argument("--session-id")
    heartbeat.add_argument(
        "--global-index",
        type=Path,
        default=Path.home() / ".arborist" / "index.json",
    )

    stop = subparsers.add_parser(
        "stop", help="declare a session stopped only during actual teardown"
    )
    stop.add_argument("--name", required=True)
    stop.add_argument("--session-id")
    stop.add_argument("--confirm-session-exit", action="store_true")
    stop.add_argument(
        "--global-index",
        type=Path,
        default=Path.home() / ".arborist" / "index.json",
    )

    status = subparsers.add_parser(
        "status", help="derive effective state and diagnose declaration conflicts"
    )
    status.add_argument("--name", required=True)
    return parser


def command_send(args: argparse.Namespace, repo: Path) -> int:
    script_path = Path(__file__).resolve()
    payload = plan_delivery(
        repo,
        sender_name=args.sender,
        target_name=args.target,
        message=args.message,
        nonce=str(uuid.uuid4()),
        script_path=script_path,
    )
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.pane_submit_delay is not None and (
        not math.isfinite(args.pane_submit_delay) or args.pane_submit_delay < 0
    ):
        raise RegistryError("--pane-submit-delay must be finite and non-negative")

    executable = payload["argv"][0]
    if shutil.which(executable) is None:
        raise RegistryError(f"required executable is not installed: {executable}")

    session_file = Path(payload["target_session_file"])
    transcript_start_offset = (
        transcript_size(session_file)
        if payload["route_mode"] == "pane"
        else 0
    )
    pane_delivered = False
    if (
        payload["route_mode"] == "resume"
        and session_file.is_file()
        and session_file.stat().st_size >= LARGE_TRANSCRIPT_BYTES
    ):
        print(
            f"warning: target transcript is {session_file.stat().st_size:,} bytes; "
            "resume may be expensive because it loads the target context",
            file=sys.stderr,
        )

    try:
        result = subprocess.run(
            payload["argv"],
            cwd=payload["cwd"],
            text=True,
            capture_output=True,
            timeout=args.timeout,
            check=False,
        )
        if result.returncode == 0 and payload["submit_argv"] is not None:
            submit_delay = args.pane_submit_delay
            if submit_delay is None:
                submit_delay = (
                    CODEX_PANE_SUBMIT_DELAY_SECONDS
                    if payload["target_brand"] == "codex"
                    else 0.0
                )
            if submit_delay:
                time.sleep(submit_delay)
            result = subprocess.run(
                payload["submit_argv"],
                cwd=payload["cwd"],
                text=True,
                capture_output=True,
                timeout=args.timeout,
                check=False,
            )
            if result.returncode == 0:
                pane_delivered = wait_for_transcript_marker(
                    session_file,
                    payload["delivery_marker"],
                    transcript_start_offset,
                )
            queue_for_next_turn = (
                payload["target_brand"] == "codex"
                and payload["target_effective_state"] == "active"
            )
            if result.returncode == 0 and not pane_delivered and not queue_for_next_turn:
                time.sleep(max(submit_delay, PANE_VERIFY_INTERVAL_SECONDS))
                result = subprocess.run(
                    payload["submit_argv"],
                    cwd=payload["cwd"],
                    text=True,
                    capture_output=True,
                    timeout=args.timeout,
                    check=False,
                )
                if result.returncode == 0:
                    pane_delivered = wait_for_transcript_marker(
                        session_file,
                        payload["delivery_marker"],
                        transcript_start_offset,
                    )
    except subprocess.TimeoutExpired as exc:
        raise RegistryError(
            "delivery attempt timed out; the target may still have queued the message"
        ) from exc

    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode != 0:
        print(
            "warning: the delivery command returned non-zero; delivery is uncertain, "
            "not proven failed (busy sessions may queue the message)",
            file=sys.stderr,
        )
    elif payload["route_mode"] == "pane":
        if not pane_delivered:
            print(
                "warning: pane commands succeeded but this envelope nonce was not found "
                "in the target transcript after the pane submit attempt; the message may "
                "still be queued or remain in the input box, so retry when the target "
                "is idle or seek an explicit peer reply",
                file=sys.stderr,
            )
        print(
            json.dumps(
                {
                    "delivery": "delivered" if pane_delivered else "queued-unverified",
                    "route_mode": "pane",
                    "target": payload["target"],
                    "target_brand": payload["target_brand"],
                    "nonce": payload["nonce"],
                    "evidence": (
                        "envelope-nonce-found" if pane_delivered else "none"
                    ),
                    "acknowledged": False,
                },
                ensure_ascii=False,
            )
        )
    return result.returncode


def command_state(args: argparse.Namespace, repo: Path, state: str) -> int:
    agent = load_agent(repo, args.name)
    require_current_session(agent, args.session_id)
    write_runtime_state(
        repo,
        args.name,
        state=state,
        now=default_now(),
        global_index=args.global_index,
        confirm_session_exit=getattr(args, "confirm_session_exit", False),
    )
    print(
        json.dumps(
            {"name": args.name, "state": state, "session_id": agent.session_id},
            ensure_ascii=False,
        )
    )
    return 0


def command_status(args: argparse.Namespace, repo: Path) -> int:
    agent = load_agent(repo, args.name)
    result = derive_effective_state(agent)
    print(
        json.dumps(
            {
                "name": agent.name,
                "brand": agent.brand,
                "session_id": agent.session_id,
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if result["diagnostic"] == "declared-stopped-but-transcript-newer" else 0


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        if args.command == "send":
            return command_send(args, repo)
        if args.command == "heartbeat":
            return command_state(args, repo, "active")
        if args.command == "stop":
            return command_state(args, repo, "stopped")
        if args.command == "status":
            return command_status(args, repo)
    except RegistryError as exc:
        parser.error(str(exc))
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
