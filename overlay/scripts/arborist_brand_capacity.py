#!/usr/bin/env python3
"""Single-writer observer for supported-brand capacity and Impler-creation hints.

This tool only observes local capacity signals and produces a read-only brand
recommendation. It never starts or stops sessions, never edits the agent
registry, never writes a session's actual brand on its behalf, never switches
an existing Impler (or its L1 chain) across brands, and never reads, stores, or
prints any credential. Standard library only; no network access.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


# Two levels deep: adopted at <repo>/.trellis/scripts/, so parents[2] is the
# *candidate* repository root (same convention as agenttui.py). The inference is
# only a candidate: nothing derived from it may be read or created before
# resolve_repo_root() has confirmed it really is a project repository.
REPO_MARKERS = (".trellis", ".git")
CONFIG_RELATIVE_PATH = ".work_context/sendbox/_handoff-config.yaml"
STATE_RELATIVE_PATH = ".arborist/runtime/brand-capacity.json"
REPORTS_RELATIVE_PATH = ".arborist/runtime/brand-capacity-reports"
LOCK_RELATIVE_PATH = ".arborist/runtime/brand-capacity.lock"
DEFAULT_CODEX_SESSIONS = Path.home() / ".codex/sessions"
DEFAULT_MAX_AGE_SECONDS = 15 * 60
DEFAULT_SERVICE_INTERVAL_SECONDS = 60.0
DEFAULT_CLAUDE_COMMAND = "claude"
DEFAULT_CLAUDE_TIMEOUT_SECONDS = 20.0
SCHEMA_VERSION = 1

AGENT_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*")

# Claude Code's built-in `/usage` renders capacity as human-readable text inside
# the `result` field. These are format patterns, not observed values; the real
# percentages come only from a live poll and are never hardcoded here.
CLAUDE_SESSION_PATTERN = re.compile(
    r"^Current session:\s*(?P<used>\d+(?:\.\d+)?)%\s+used\b",
    re.MULTILINE,
)
CLAUDE_WEEK_PATTERN = re.compile(
    r"^Current week \((?P<label>[^)]+)\):\s*(?P<used>\d+(?:\.\d+)?)%\s+used\b",
    re.MULTILINE,
)

# Role affinity is a non-binding tie-breaker / fallback only, never a headroom
# fact. It is derived, not authoritative.
ROLE_AFFINITY = {
    "impler": ["codex", "claude-code"],
    "orchestrator": ["claude-code", "codex"],
}


class CapacityError(RuntimeError):
    """The capacity input or local Arborist state is unsafe to consume."""


def looks_like_project_repo(path: Path) -> bool:
    return any((path / marker).exists() for marker in REPO_MARKERS)


def infer_repo_root(script_path: Path) -> Path:
    """Unvalidated inference: this script is adopted at <repo>/.trellis/scripts/."""
    return script_path.resolve().parents[2]


def resolve_repo_root(candidate: Path | None) -> Path:
    """Fail closed unless the derived path really is a project repository.

    This gate creates nothing. State, reports and the lock all live under the
    derived root, and every one of those writers would happily `mkdir -p` its
    parents — which is precisely how a mis-derived root becomes invisible: the
    wrong location ends up looking like it had always been there.
    """
    explicit = candidate is not None
    resolved = (candidate if explicit else infer_repo_root(Path(__file__))).expanduser()
    resolved = resolved.resolve() if resolved.exists() else resolved.absolute()
    source = "--repo" if explicit else "path inferred from this script's location"
    if not resolved.is_dir():
        raise CapacityError(
            f"derived repository root is not a directory ({source}): {resolved}; "
            "run this from inside the project repository or pass --repo explicitly"
        )
    if not looks_like_project_repo(resolved):
        raise CapacityError(
            f"derived repository root is not a project repository ({source}): "
            f"{resolved} contains none of "
            f"{', '.join(marker + '/' for marker in REPO_MARKERS)}; refusing to "
            "read or create capacity state there — run this from inside the "
            "project repository or pass --repo explicitly"
        )
    return resolved


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapacityError(f"{label} must be an object")
    return value


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapacityError(f"{label} must be a non-empty string")
    return value.strip()


def parse_timestamp(value: Any, label: str) -> datetime:
    text = require_text(value, label)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CapacityError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise CapacityError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "unnamed"


def load_supported_brands(config_path: Path) -> list[str]:
    """Read the closed supported_brands list without adding a YAML dependency.

    The host route config is the sole source of the closed set. Any installed
    CLI whose brand is absent here never becomes a candidate.
    """

    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CapacityError(f"cannot read host route config: {config_path}") from exc

    list_indent: int | None = None
    brands: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if list_indent is None:
            if stripped == "supported_brands:":
                list_indent = indent
            continue
        if indent <= list_indent:
            break
        if stripped.startswith("- "):
            brand = stripped[2:].strip().strip("\"'")
            if brand:
                brands.append(brand)

    if not brands:
        raise CapacityError(
            f"host route config has no supported_brands list: {config_path}"
        )
    if len(set(brands)) != len(brands):
        raise CapacityError("supported_brands contains duplicate values")
    return brands


def normalize_window(value: Any, name: str) -> dict[str, Any]:
    window = require_object(value, f"window {name}")
    raw_used = window.get("used_percent")
    if not isinstance(raw_used, (int, float)) or isinstance(raw_used, bool):
        raise CapacityError(f"window {name}.used_percent must be numeric")
    used_percent = float(raw_used)
    if not math.isfinite(used_percent) or not 0 <= used_percent <= 100:
        raise CapacityError(f"window {name}.used_percent must be between 0 and 100")

    normalized: dict[str, Any] = {"name": name, "used_percent": used_percent}
    raw_minutes = window.get("window_minutes")
    if raw_minutes is not None:
        if (
            not isinstance(raw_minutes, (int, float))
            or isinstance(raw_minutes, bool)
            or raw_minutes <= 0
        ):
            raise CapacityError(f"window {name}.window_minutes must be positive")
        normalized["window_minutes"] = int(raw_minutes)
    raw_reset = window.get("resets_at")
    if raw_reset is not None:
        if isinstance(raw_reset, bool) or not isinstance(raw_reset, (int, float, str)):
            raise CapacityError(f"window {name}.resets_at must be numeric or a string")
        normalized["resets_at"] = raw_reset
    return normalized


# --- Codex: passive, server-provided rate limits from local rollout logs ------


def find_nested_rate_limits(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        candidate = value.get("rate_limits")
        if isinstance(candidate, dict):
            return candidate
        for child in value.values():
            found = find_nested_rate_limits(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_nested_rate_limits(child)
            if found is not None:
                return found
    return None


def normalize_rate_limits(rate_limits: dict[str, Any]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for name in ("primary", "secondary"):
        value = rate_limits.get(name)
        if value is not None:
            windows.append(normalize_window(value, name))
    if not windows:
        raise CapacityError("rate_limits contains no observable windows")
    return windows


def find_latest_codex_capacity(sessions_root: Path) -> dict[str, Any] | None:
    """Return the newest server-provided Codex rate-limit observation.

    Read-only recursive scan of rollout logs. The values are authoritative
    server responses but land passively, so freshness is judged by observed_at.
    No network access and no credentials are read.
    """

    if not sessions_root.is_dir():
        return None

    latest: tuple[datetime, dict[str, Any]] | None = None
    for path in sessions_root.rglob("rollout-*.jsonl"):
        try:
            stream = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with stream:
            for line in stream:
                if "rate_limits" not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                rate_limits = find_nested_rate_limits(event)
                if rate_limits is None:
                    continue
                try:
                    observed_at = parse_timestamp(
                        event.get("timestamp"), f"{path}: timestamp"
                    )
                    windows = normalize_rate_limits(rate_limits)
                except CapacityError:
                    continue
                record = {
                    "status": "observed",
                    "source": "polled",
                    "observed_at": require_text(
                        event.get("timestamp"), f"{path}: timestamp"
                    ),
                    "windows": windows,
                }
                if latest is None or observed_at > latest[0]:
                    latest = observed_at, record
    return latest[1] if latest is not None else None


# --- Claude Code: mechanical `/usage` collector (no model turn) ---------------


def parse_claude_usage_response(
    output: str,
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    """Parse Claude Code's built-in `/usage` result from print mode.

    Credence gate (all must hold, otherwise fail closed and observe nothing):
      1. is_error is False and subtype == "success";
      2. num_turns == 0 and total_cost_usd == 0 (proves zero side effects);
      3. at least one explicit usage line maps into windows[].

    observed_at is the observer's poll time (query freshness), not a claim about
    when the server generated the underlying numbers.
    """

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise CapacityError("Claude /usage did not return JSON") from exc
    response = require_object(payload, "Claude /usage response")

    if response.get("is_error") is not False:
        raise CapacityError("Claude /usage reported an error result")
    if response.get("subtype") != "success":
        raise CapacityError("Claude /usage subtype is not 'success'")
    if response.get("num_turns") != 0:
        raise CapacityError(
            "Claude /usage used a model turn; refusing non-mechanical output"
        )
    raw_cost = response.get("total_cost_usd")
    if (
        not isinstance(raw_cost, (int, float))
        or isinstance(raw_cost, bool)
        or float(raw_cost) != 0.0
    ):
        raise CapacityError("Claude /usage reported non-zero or invalid model cost")

    result = require_text(response.get("result"), "Claude /usage result")
    windows: list[dict[str, Any]] = []
    session_match = CLAUDE_SESSION_PATTERN.search(result)
    if session_match is not None:
        windows.append(
            normalize_window(
                {"used_percent": float(session_match.group("used"))},
                "current-session",
            )
        )
    for week_match in CLAUDE_WEEK_PATTERN.finditer(result):
        name = "current-week-" + _slugify(week_match.group("label"))
        windows.append(
            normalize_window(
                {"used_percent": float(week_match.group("used"))},
                name,
            )
        )
    if not windows:
        raise CapacityError("Claude /usage contained no recognized capacity windows")
    return {
        "status": "observed",
        "source": "polled",
        "observed_at": format_timestamp(observed_at),
        "windows": windows,
    }


def find_claude_capacity(
    command: str,
    *,
    observed_at: datetime,
    timeout_seconds: float = DEFAULT_CLAUDE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Poll Claude Code's built-in `/usage` mechanically, without an LLM turn.

    Borrows the local Claude CLI login state only to run the built-in command;
    it never reads, copies, or passes any token. stdin is detached (avoids the
    print-mode stdin wait) and the inherited session-context identity variable
    is cleared so no parent identity leaks into the poll.
    """

    executable = shutil.which(command)
    if executable is None:
        raise CapacityError(f"Claude command is unavailable: {command}")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise CapacityError("Claude usage timeout must be finite and positive")
    environment = os.environ.copy()
    environment.pop("TRELLIS_CONTEXT_ID", None)
    try:
        completed = subprocess.run(
            [executable, "-p", "/usage", "--output-format", "json"],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=timeout_seconds,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise CapacityError("Claude /usage timed out") from exc
    except OSError as exc:
        raise CapacityError("cannot execute Claude /usage") from exc
    if completed.returncode != 0:
        raise CapacityError(f"Claude /usage exited with status {completed.returncode}")
    return parse_claude_usage_response(completed.stdout, observed_at=observed_at)


# --- Self-report fallback (registered session reports its own /usage) ---------


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CapacityError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CapacityError(f"invalid JSON in {path}: {exc}") from exc
    return require_object(value, str(path))


def normalize_self_report(
    payload: dict[str, Any],
    *,
    agent_name: str,
    agent_brand: str,
) -> dict[str, Any]:
    declared_brand = payload.get("brand")
    if declared_brand is not None and declared_brand != agent_brand:
        raise CapacityError(
            f"self-report brand mismatch: agent={agent_brand!r}, "
            f"report={declared_brand!r}"
        )
    if payload.get("source") != "self-reported":
        raise CapacityError("self-report source must be 'self-reported'")
    observed_at = require_text(payload.get("observed_at"), "observed_at")
    parse_timestamp(observed_at, "observed_at")
    raw_windows = payload.get("windows")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise CapacityError("self-report windows must be a non-empty list")
    windows: list[dict[str, Any]] = []
    for index, raw_window in enumerate(raw_windows):
        window = require_object(raw_window, f"windows[{index}]")
        name = require_text(window.get("name"), f"windows[{index}].name")
        windows.append(normalize_window(window, name))
    return {
        "schema_version": SCHEMA_VERSION,
        "agent": agent_name,
        "brand": agent_brand,
        "status": "observed",
        "source": "self-reported",
        "observed_at": observed_at,
        "windows": windows,
    }


def write_self_report(
    *,
    repo_root: Path,
    reports_dir: Path,
    agent_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if AGENT_NAME_PATTERN.fullmatch(agent_name) is None:
        raise CapacityError("agent name has unsupported characters")
    spec_path = repo_root / ".arborist/agents" / agent_name / "spec.json"
    spec = read_json(spec_path)
    if spec.get("name") != agent_name:
        raise CapacityError(
            f"agent name mismatch: directory={agent_name!r}, spec={spec.get('name')!r}"
        )
    agent_brand = require_text(spec.get("brand"), f"{spec_path}: brand")
    normalized = normalize_self_report(
        payload,
        agent_name=agent_name,
        agent_brand=agent_brand,
    )
    atomic_write_json(reports_dir / f"{agent_name}.json", normalized)
    return normalized


def latest_self_reports(
    reports_dir: Path,
    supported_brands: Sequence[str],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    latest: dict[str, tuple[datetime, dict[str, Any]]] = {}
    diagnostics: list[str] = []
    if not reports_dir.is_dir():
        return {}, diagnostics
    for path in reports_dir.glob("*.json"):
        try:
            report = read_json(path)
            brand = require_text(report.get("brand"), f"{path}: brand")
            if brand not in supported_brands:
                diagnostics.append(f"{path.name}: unsupported brand {brand!r}")
                continue
            if report.get("source") != "self-reported":
                raise CapacityError("source must be self-reported")
            observed_at = parse_timestamp(
                report.get("observed_at"), f"{path}: observed_at"
            )
            raw_windows = report.get("windows")
            if not isinstance(raw_windows, list) or not raw_windows:
                raise CapacityError("windows must be a non-empty list")
            windows = [
                normalize_window(
                    require_object(item, f"{path}: windows[{index}]"),
                    require_text(
                        require_object(item, f"{path}: windows[{index}]").get("name"),
                        f"{path}: windows[{index}].name",
                    ),
                )
                for index, item in enumerate(raw_windows)
            ]
            normalized = {
                "status": "observed",
                "source": "self-reported",
                "observed_at": require_text(
                    report.get("observed_at"), f"{path}: observed_at"
                ),
                "windows": windows,
                "agent": require_text(report.get("agent"), f"{path}: agent"),
            }
        except CapacityError as exc:
            diagnostics.append(f"{path.name}: {exc}")
            continue
        previous = latest.get(brand)
        if previous is None or observed_at > previous[0]:
            latest[brand] = observed_at, normalized
    return {brand: item[1] for brand, item in latest.items()}, diagnostics


# --- Snapshot assembly --------------------------------------------------------


def refresh_snapshot(
    *,
    repo_root: Path,
    config_path: Path,
    codex_sessions: Path,
    state_path: Path,
    reports_dir: Path,
    claude_command: str | None = None,
    claude_timeout_seconds: float = DEFAULT_CLAUDE_TIMEOUT_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    supported_brands = load_supported_brands(config_path)
    self_reports, diagnostics = latest_self_reports(reports_dir, supported_brands)
    codex = (
        find_latest_codex_capacity(codex_sessions)
        if "codex" in supported_brands
        else None
    )
    generated_at = now or datetime.now(timezone.utc)
    claude: dict[str, Any] | None = None
    if "claude-code" in supported_brands and claude_command is not None:
        try:
            claude = find_claude_capacity(
                claude_command,
                observed_at=generated_at,
                timeout_seconds=claude_timeout_seconds,
            )
        except CapacityError as exc:
            # Fail closed: the mechanical poll did not clear the credence gate,
            # so Claude Code stays unknown unless a self-report backs it.
            diagnostics.append(f"claude-code: {exc}")
    brands: dict[str, dict[str, Any]] = {}
    for brand in supported_brands:
        if brand == "codex" and codex is not None:
            brands[brand] = codex
        elif brand == "claude-code" and claude is not None:
            brands[brand] = claude
        elif brand in self_reports:
            brands[brand] = self_reports[brand]
        else:
            brands[brand] = {
                "status": "unknown",
                "source": "unavailable",
                "observed_at": None,
                "windows": [],
            }
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": format_timestamp(generated_at),
        "supported_brands": supported_brands,
        "brands": brands,
        "diagnostics": diagnostics,
    }
    atomic_write_json(state_path, snapshot)
    return snapshot


# --- Recommendation (Impler-creation only) ------------------------------------


def candidate_capacity(
    brand: str,
    observation: dict[str, Any],
    *,
    now: datetime,
    max_age_seconds: float,
) -> dict[str, Any]:
    observed_at_value = observation.get("observed_at")
    age_seconds: float | None = None
    if observed_at_value is not None:
        age_seconds = max(
            0.0,
            (now - parse_timestamp(observed_at_value, f"{brand}.observed_at"))
            .total_seconds(),
        )
    raw_windows = observation.get("windows")
    headrooms: list[float] = []
    if isinstance(raw_windows, list):
        for raw_window in raw_windows:
            if not isinstance(raw_window, dict):
                continue
            used = raw_window.get("used_percent")
            if isinstance(used, (int, float)) and not isinstance(used, bool):
                used_float = float(used)
                if math.isfinite(used_float) and 0 <= used_float <= 100:
                    headrooms.append(100.0 - used_float)
    fresh = (
        observation.get("status") == "observed"
        and age_seconds is not None
        and age_seconds <= max_age_seconds
        and bool(headrooms)
    )
    return {
        "brand": brand,
        "status": observation.get("status", "unknown"),
        "source": observation.get("source", "unavailable"),
        "observed_at": observed_at_value,
        "age_seconds": age_seconds,
        "fresh": fresh,
        "minimum_headroom_percent": min(headrooms) if headrooms else None,
    }


def recommend_brand(
    snapshot: dict[str, Any],
    *,
    role: str,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    if role not in ROLE_AFFINITY:
        raise CapacityError("role must be 'impler' or 'orchestrator'")
    if not math.isfinite(max_age_seconds) or max_age_seconds < 0:
        raise CapacityError("max_age_seconds must be finite and non-negative")
    supported = snapshot.get("supported_brands")
    brands = snapshot.get("brands")
    if not isinstance(supported, list) or not supported:
        raise CapacityError("snapshot supported_brands must be a non-empty list")
    if not isinstance(brands, dict):
        raise CapacityError("snapshot brands must be an object")

    observed_now = now or datetime.now(timezone.utc)
    candidates = [
        candidate_capacity(
            require_text(brand, "supported brand"),
            require_object(brands.get(brand, {}), f"brands.{brand}"),
            now=observed_now,
            max_age_seconds=max_age_seconds,
        )
        for brand in supported
    ]
    preference = ROLE_AFFINITY[role]
    affinity = {
        brand: len(preference) - index for index, brand in enumerate(preference)
    }
    fresh = [candidate for candidate in candidates if candidate["fresh"]]
    if fresh:
        selected = max(
            fresh,
            key=lambda candidate: (
                candidate["minimum_headroom_percent"],
                affinity.get(candidate["brand"], 0),
            ),
        )
        quality = "fresh-capacity"
        reason = (
            "selected the fresh supported brand with the greatest minimum "
            "observed headroom; role affinity only breaks ties"
        )
    else:
        selected = next(
            (
                candidate
                for brand in preference
                for candidate in candidates
                if candidate["brand"] == brand
            ),
            candidates[0],
        )
        quality = "role-affinity-fallback"
        reason = (
            "no fresh comparable headroom was available; used the non-binding "
            "role affinity fallback"
        )
    return {
        "recommended_brand": selected["brand"],
        "decision_quality": quality,
        "selection_scope": "impler-creation-only",
        "role": role,
        "max_age_seconds": max_age_seconds,
        "reason": reason,
        "candidates": candidates,
        "constraints": [
            "the launched session must self-register its actual brand",
            "never switch an existing Impler or its L1 chain across brands",
        ],
    }


# --- Single-writer lock + CLI -------------------------------------------------


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        path.chmod(0o600)
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CapacityError(
                f"brand capacity writer is already running: {path}"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Observe supported Arborist brand capacity and recommend a brand "
            "only when creating a new Impler."
        )
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help=(
            "project repository root (default: inferred from this script's "
            "location, then validated — the inferred path must itself contain "
            f"{' or '.join(marker + '/' for marker in REPO_MARKERS)}, otherwise "
            "the run is refused instead of creating capacity state somewhere else)"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"default: <repo>/{CONFIG_RELATIVE_PATH}",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help=f"default: <repo>/{STATE_RELATIVE_PATH}",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=None,
        help=f"default: <repo>/{REPORTS_RELATIVE_PATH}",
    )
    parser.add_argument("--codex-sessions", type=Path, default=DEFAULT_CODEX_SESSIONS)
    parser.add_argument(
        "--claude-command",
        default=DEFAULT_CLAUDE_COMMAND,
        help="Claude Code executable used for built-in /usage polling",
    )
    parser.add_argument(
        "--claude-timeout-seconds",
        type=float,
        default=DEFAULT_CLAUDE_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=None,
        help=f"default: <repo>/{LOCK_RELATIVE_PATH}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("refresh", help="refresh the local capacity snapshot")
    subparsers.add_parser("status", help="print the current capacity snapshot")

    report = subparsers.add_parser(
        "report",
        help="write one registered AgentTUI's self-reported capacity observation",
    )
    report.add_argument("--agent", required=True)
    report.add_argument("--input", type=Path, required=True)

    recommend = subparsers.add_parser(
        "recommend",
        help="recommend a supported brand without launching or registering it",
    )
    recommend.add_argument("--role", choices=("impler", "orchestrator"), required=True)
    recommend.add_argument(
        "--max-age-seconds",
        type=float,
        default=DEFAULT_MAX_AGE_SECONDS,
    )

    serve = subparsers.add_parser(
        "serve",
        help="run a single-writer foreground snapshot refresh loop (not a daemon)",
    )
    serve.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_SERVICE_INTERVAL_SECONDS,
    )
    serve.add_argument(
        "--once",
        action="store_true",
        help="refresh once under the service lock, then exit",
    )
    return parser


def print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run_refresh(args: argparse.Namespace) -> dict[str, Any]:
    return refresh_snapshot(
        repo_root=args.repo,
        config_path=args.config,
        codex_sessions=args.codex_sessions.resolve(),
        state_path=args.state,
        reports_dir=args.reports_dir,
        claude_command=args.claude_command,
        claude_timeout_seconds=args.claude_timeout_seconds,
    )


def resolve_paths(args: argparse.Namespace) -> None:
    """Validate the repository root first, then derive every path from it.

    Order matters: nothing may be resolved (let alone created) under an
    unvalidated root.
    """
    args.repo = resolve_repo_root(args.repo)
    defaults = {
        "config": CONFIG_RELATIVE_PATH,
        "state": STATE_RELATIVE_PATH,
        "reports_dir": REPORTS_RELATIVE_PATH,
        "lock": LOCK_RELATIVE_PATH,
    }
    for attribute, relative in defaults.items():
        supplied = getattr(args, attribute)
        setattr(
            args,
            attribute,
            (args.repo / relative) if supplied is None else supplied.resolve(),
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        resolve_paths(args)
        if args.command == "status":
            print_json(read_json(args.state))
            return 0
        if args.command == "recommend":
            snapshot = read_json(args.state)
            print_json(
                recommend_brand(
                    snapshot,
                    role=args.role,
                    max_age_seconds=args.max_age_seconds,
                )
            )
            return 0
        if args.command == "refresh":
            with exclusive_lock(args.lock):
                print_json(run_refresh(args))
            return 0
        if args.command == "report":
            payload = read_json(args.input.resolve())
            with exclusive_lock(args.lock):
                print_json(
                    write_self_report(
                        repo_root=args.repo,
                        reports_dir=args.reports_dir,
                        agent_name=args.agent,
                        payload=payload,
                    )
                )
            return 0
        if args.command == "serve":
            if not math.isfinite(args.interval) or args.interval <= 0:
                raise CapacityError("--interval must be finite and positive")
            with exclusive_lock(args.lock):
                while True:
                    print_json(run_refresh(args))
                    if args.once:
                        return 0
                    time.sleep(args.interval)
    except CapacityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
