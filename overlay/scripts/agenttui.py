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
from typing import Any, Callable, NamedTuple


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

# A derived repository root is only usable if it really is a project repository.
# See agenttui-registry.md §3 "delivery preflight" (path-derivation half).
REPO_MARKERS = (".trellis", ".git")

# Delivery outcome vocabulary. "no-operational-route" (nothing was sent, retry is
# safe and necessary) and "queued-unverified" (bytes went out, delivery is
# unproven, blind retry may enqueue a duplicate) are deliberately distinct
# values — see agenttui-registry.md §3 rules 2/3/6.
DELIVERY_DELIVERED = "delivered"
DELIVERY_QUEUED_UNVERIFIED = "queued-unverified"
DELIVERY_NO_OPERATIONAL_ROUTE = "no-operational-route"
EXIT_NO_OPERATIONAL_ROUTE = 3

ROUTE_PANE = "pane"
ROUTE_RESUME = "resume"


class RegistryError(RuntimeError):
    """The registry is incomplete, inconsistent, or unsafe to use."""


class NoOperationalRoute(RegistryError):
    """No delivery route is operational, so nothing was sent.

    Strictly distinct from ``queued-unverified``: that one means the envelope
    left this process and delivery could not be proven, so a blind retry risks a
    duplicate (rule 2). This one means the send-side precondition failed and the
    envelope never went out, so retrying is both safe and necessary.
    """

    def __init__(self, reason: str, detail: str, *, remedy: str) -> None:
        super().__init__(f"{DELIVERY_NO_OPERATIONAL_ROUTE} ({reason}): {detail}")
        self.reason = reason
        self.detail = detail
        self.remedy = remedy

    def payload(self, **extra: Any) -> dict[str, Any]:
        return {
            "delivery": DELIVERY_NO_OPERATIONAL_ROUTE,
            "reason": self.reason,
            "detail": self.detail,
            "remedy": self.remedy,
            "sent": False,
            "retry_safe": True,
            "evidence": "none",
            "acknowledged": False,
            **extra,
        }


def looks_like_project_repo(path: Path) -> bool:
    return any((path / marker).exists() for marker in REPO_MARKERS)


def infer_repo_root(script_path: Path) -> Path:
    """Unvalidated inference: this script is adopted at <repo>/.trellis/scripts/."""
    return script_path.resolve().parents[2]


def resolve_repo_root(candidate: Path, *, explicit: bool) -> Path:
    """Fail closed unless the derived path really is a project repository.

    Never creates anything: ``mkdir -p`` on a mis-derived root would make the
    wrong location look like it had always been there, which is exactly the
    silent failure mode this gate exists to prevent (a leaf whose fields were all
    correct but whose registry landed in the repository's *parent* directory went
    unnoticed for days).
    """
    resolved = candidate.expanduser()
    resolved = resolved.resolve() if resolved.exists() else resolved.absolute()
    source = "--repo" if explicit else "path inferred from this script's location"
    if not resolved.is_dir():
        raise RegistryError(
            f"derived repository root is not a directory ({source}): {resolved}; "
            "run this from inside the project repository or pass --repo explicitly"
        )
    if not looks_like_project_repo(resolved):
        raise RegistryError(
            f"derived repository root is not a project repository ({source}): "
            f"{resolved} contains none of "
            f"{', '.join(marker + '/' for marker in REPO_MARKERS)}; refusing to "
            "read or write a registry there (and refusing to create one) — run "
            "this from inside the project repository or pass --repo explicitly"
        )
    return resolved


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


class Capability(NamedTuple):
    """Answer to one capability question, with the text that justified it."""

    ok: bool
    detail: str


class CommandOutcome(NamedTuple):
    """Result of one transport command.

    ``rejected`` is decided by *stdout text*, never by ``returncode``: multiplexers
    are observed to exit 0 while only saying "not found" on stdout. And note the
    worst case that no post-hoc parsing can rescue — a live session with a dead
    pane answers rc=0 with *empty* stdout — so a clean outcome here is **not**
    delivery evidence (rule 3's nonce is).
    """

    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    rejected: bool
    detail: str


CommandRunner = Callable[..., subprocess.CompletedProcess]


class PaneTransport:
    """Capability seam for pane-addressed delivery (one per multiplexer).

    Routing code may only ask the questions declared here; a concrete
    multiplexer's name and command lines live in the subclass and nowhere else.
    Swapping multiplexers must therefore be a new subclass plus one registry
    entry, with the delivery contract untouched (ADR-0007 transport neutrality).
    """

    name = "abstract"

    def available(self) -> Capability:
        """Is this transport's own tooling usable at all in this process?"""
        raise NotImplementedError

    def exists(self, pane_ref: dict[str, str]) -> Capability:
        """Existence preflight for the addressed pane (rule 5).

        Implementations must use a probe that *reports an error* for a missing
        pane and must judge it by stdout text, not by exit code.

        WARNING — known, contract-recorded side effect: for a transport that
        addresses panes through GUI focus, the only reliable probe is the focus
        command itself, so preflight **steals the terminal focus** toward the
        target pane. That is an architectural limitation of such transports, not
        a tuning problem; no implementation of this method may be described as
        side-effect free without saying so.
        """
        raise NotImplementedError

    def write_chars_argv(self, pane_ref: dict[str, str], text: str) -> list[str]:
        raise NotImplementedError

    def send_key_argv(self, pane_ref: dict[str, str], key_byte: str) -> list[str]:
        raise NotImplementedError

    def write_chars(
        self,
        pane_ref: dict[str, str],
        text: str,
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> CommandOutcome:
        raise NotImplementedError

    def send_key(
        self,
        pane_ref: dict[str, str],
        key_byte: str,
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> CommandOutcome:
        raise NotImplementedError


class DeliveryRoute(NamedTuple):
    mode: str
    cwd: Path
    # resume mode
    argv: list[str] | None = None
    # pane mode
    transport: PaneTransport | None = None
    pane_ref: dict[str, str] | None = None
    pane_text: str | None = None
    submit_byte: str | None = None
    preflight: Capability | None = None
    warnings: tuple[str, ...] = ()

    def pane_argv(self) -> list[str] | None:
        if self.mode != ROUTE_PANE or self.transport is None:
            return None
        assert self.pane_ref is not None and self.pane_text is not None
        return self.transport.write_chars_argv(self.pane_ref, self.pane_text)

    def submit_argv(self) -> list[str] | None:
        if self.mode != ROUTE_PANE or self.transport is None:
            return None
        assert self.pane_ref is not None and self.submit_byte is not None
        return self.transport.send_key_argv(self.pane_ref, self.submit_byte)


def run_command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


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


# --- Concrete transport: zellij ----------------------------------------------
# Everything zellij-specific is confined below this line plus the TRANSPORTS
# registry entry. Routing code must never name a multiplexer or its commands.

# Observed failure texts. zellij reports these while still exiting 0, so they are
# the only trustworthy signal — for the probe *and* for the injection and submit
# commands themselves. Kept narrow on purpose: a loose "not found" would let
# unrelated output masquerade as an addressing failure.
ZELLIJ_NOT_FOUND_PATTERNS = (
    re.compile(r"pane with id\b.*\bnot found", re.IGNORECASE),
    re.compile(r"session '[^']*' not found", re.IGNORECASE),
    re.compile(r"no\s+(?:active\s+)?(?:zellij\s+)?sessions?\s+found", re.IGNORECASE),
)


class ZellijTransport(PaneTransport):
    """zellij implementation of the pane transport capabilities."""

    name = "zellij"
    executable = "zellij"

    def __init__(
        self,
        *,
        runner: CommandRunner = run_command,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._runner = runner
        self._which = which

    def _action_argv(self, pane_ref: dict[str, str], *action: str) -> list[str]:
        return [
            self.executable,
            "--session",
            pane_ref["session"],
            "action",
            *action,
        ]

    def available(self) -> Capability:
        located = self._which(self.executable)
        if located is None:
            return Capability(
                False, f"pane transport CLI {self.executable!r} is not installed"
            )
        return Capability(True, f"{self.executable} found at {located}")

    def probe_argv(self, pane_ref: dict[str, str]) -> list[str]:
        return self._action_argv(pane_ref, "focus-pane-id", pane_ref["pane_id"])

    def write_chars_argv(self, pane_ref: dict[str, str], text: str) -> list[str]:
        return self._action_argv(
            pane_ref, "write-chars", "--pane-id", pane_ref["pane_id"], text
        )

    def send_key_argv(self, pane_ref: dict[str, str], key_byte: str) -> list[str]:
        return self._action_argv(
            pane_ref, "write", "--pane-id", pane_ref["pane_id"], key_byte
        )

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path | None,
        timeout: float | None,
    ) -> CommandOutcome:
        try:
            completed = self._runner(argv, cwd=cwd, timeout=timeout)
        except OSError as exc:
            return CommandOutcome(
                argv=argv,
                returncode=127,
                stdout="",
                stderr=str(exc),
                rejected=True,
                detail=f"could not execute {argv[0]!r}: {exc}",
            )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        # Judged by text, not by returncode (rc is 0 even for "not found").
        text = f"{stdout}\n{stderr}"
        for pattern in ZELLIJ_NOT_FOUND_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                return CommandOutcome(
                    argv=argv,
                    returncode=completed.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    rejected=True,
                    detail=(
                        f"{self.name} reported {match.group(0)!r} "
                        f"(exit status {completed.returncode}, which is not a "
                        "reliable signal here)"
                    ),
                )
        return CommandOutcome(
            argv=argv,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            rejected=False,
            detail=(
                f"{self.name} reported no addressing error "
                "(silence is not delivery evidence)"
            ),
        )

    def exists(self, pane_ref: dict[str, str]) -> Capability:
        """Existence preflight via ``focus-pane-id`` — judged by stdout text.

        ``dump-screen -p`` is deliberately NOT used: it returns empty output with
        exit status 0 for a pane that does not exist, i.e. it manufactures false
        positives.

        Side effect, stated plainly: this probe *is* the focus command, so it
        moves the terminal focus to the target pane. That is also what makes
        cross-tab injection work at all, and it is why delivery structurally
        conflicts with a human driving the same multiplexer session.
        """
        outcome = self._run(self.probe_argv(pane_ref), cwd=None, timeout=None)
        if outcome.rejected:
            return Capability(
                False,
                f"pane {pane_ref['pane_id']!r} in session "
                f"{pane_ref['session']!r} is not reachable: {outcome.detail}",
            )
        return Capability(
            True,
            f"pane {pane_ref['pane_id']!r} in session {pane_ref['session']!r} "
            "answered the existence probe (focus moved there as a side effect)",
        )

    def write_chars(
        self,
        pane_ref: dict[str, str],
        text: str,
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> CommandOutcome:
        return self._run(
            self.write_chars_argv(pane_ref, text), cwd=cwd, timeout=timeout
        )

    def send_key(
        self,
        pane_ref: dict[str, str],
        key_byte: str,
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> CommandOutcome:
        return self._run(
            self.send_key_argv(pane_ref, key_byte), cwd=cwd, timeout=timeout
        )


# Single place where a multiplexer name maps to a transport. Adding one is a new
# entry here plus a PaneTransport subclass; no routing code changes.
TRANSPORTS: dict[str, Callable[[], PaneTransport]] = {
    ZellijTransport.name: ZellijTransport,
}


def resolve_transport(
    multiplexer: str,
    *,
    transports: dict[str, Callable[[], PaneTransport]] | None = None,
) -> PaneTransport | None:
    registry = TRANSPORTS if transports is None else transports
    factory = registry.get(multiplexer)
    return None if factory is None else factory()


# --- Capability-based routing (transport-neutral) -----------------------------


def build_pane_route(
    target: AgentRecord,
    envelope: str,
    *,
    transports: dict[str, Callable[[], PaneTransport]] | None = None,
    preflight: bool = True,
) -> DeliveryRoute:
    """Route to a live pane using only capability questions.

    Deliberately free of any multiplexer name or command line: the questions are
    "is a transport registered for this pane_ref", "is that transport usable",
    "does the addressed pane exist" (rule 5). Which multiplexer answers them is
    the registry's business.
    """
    pane_ref = target.pane_ref
    assert pane_ref is not None
    multiplexer = pane_ref["multiplexer"]
    registry = TRANSPORTS if transports is None else transports
    transport = resolve_transport(multiplexer, transports=transports)
    if transport is None:
        raise NoOperationalRoute(
            "unknown-pane-transport",
            f"no transport is registered for pane_ref.multiplexer="
            f"{multiplexer!r} (registered: {', '.join(sorted(registry)) or 'none'})",
            remedy=(
                "register a transport for this multiplexer, or rebuild the whole "
                "pane_ref for a registered one — a pane_ref is a launch-time "
                "snapshot and must be rebuilt entirely, not patched field by field"
            ),
        )
    if target.brand not in SUPPORTED_BRANDS:
        raise NoOperationalRoute(
            "unsupported-target-brand",
            f"submit-key routing is brand-keyed and {target.brand!r} has no "
            "defined submit key",
            remedy="register the target with a supported brand",
        )
    usable = transport.available()
    if not usable.ok:
        raise NoOperationalRoute(
            "pane-transport-unavailable",
            usable.detail,
            remedy=(
                "install the pane transport CLI, or choose the resume transport "
                "explicitly with --allow-resume"
            ),
        )
    probe: Capability | None = None
    if preflight:
        probe = transport.exists(pane_ref)
        if not probe.ok:
            raise NoOperationalRoute(
                "pane-not-reachable",
                probe.detail,
                remedy=(
                    "rebuild the target's pane_ref (session rename or a closed "
                    "pane rots the whole handle); injecting anyway can be "
                    "silently swallowed with exit status 0 and empty output"
                ),
            )
    submit_byte = (
        CODEX_PANE_QUEUE_BYTE
        if target.brand == "codex" and target.state == "active"
        else PANE_ENTER_BYTE
    )
    return DeliveryRoute(
        mode=ROUTE_PANE,
        cwd=target.project_path,
        transport=transport,
        pane_ref=pane_ref,
        pane_text=" ".join(envelope.splitlines()),
        submit_byte=submit_byte,
        preflight=probe,
    )


def build_resume_route(
    target: AgentRecord,
    envelope: str,
    *,
    allow_resume: bool,
    which: Callable[[str], str | None] = shutil.which,
    warnings: tuple[str, ...] = (),
) -> DeliveryRoute:
    """Route via the target's session file — only ever as an explicit choice.

    Resume is not a fallback (rule 6): it changes both cost and semantics (the
    reply lands on *this* process's stdout and never appears in the target's live
    TUI), so it must be asked for, not silently substituted.
    """
    if not allow_resume:
        raise NoOperationalRoute(
            "resume-not-authorized",
            "no operational pane route for this target and the resume transport "
            "was not requested; refusing to silently downgrade to appending to "
            "the target's session file (its reply would return here, invisible "
            "in the target's live TUI)",
            remedy=(
                "register or repair a reachable pane_ref, or choose resume "
                "explicitly with --allow-resume"
            ),
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
            raise NoOperationalRoute(
                "active-codex-requires-pane",
                "refusing bare codex exec resume for an active Codex TUI without "
                "pane_ref",
                remedy=(
                    "register a reachable pane, or use an app-server turn/steer "
                    "adapter"
                ),
            )
        argv = ["codex", "exec", "resume", target.session_id, envelope]
    else:
        raise NoOperationalRoute(
            "unsupported-target-brand",
            f"no resume transport is defined for brand {target.brand!r}",
            remedy="register the target with a supported brand",
        )
    # Rule 6: only the capability this route actually uses gets checked.
    if which(argv[0]) is None:
        raise NoOperationalRoute(
            "resume-cli-missing",
            f"the resume transport for brand {target.brand!r} requires "
            f"{argv[0]!r}, which is not installed",
            remedy=f"install {argv[0]!r}, or deliver to a reachable pane instead",
        )
    return DeliveryRoute(
        mode=ROUTE_RESUME,
        cwd=target.project_path,
        argv=argv,
        warnings=warnings,
    )


def build_route(
    target: AgentRecord,
    envelope: str,
    *,
    transports: dict[str, Callable[[], PaneTransport]] | None = None,
    allow_resume: bool = False,
    preflight: bool = True,
    which: Callable[[str], str | None] = shutil.which,
) -> DeliveryRoute:
    """Pick a route from capabilities alone, or fail closed.

    No branch here knows any multiplexer: a pane route is attempted whenever the
    target advertises a pane handle and reads as reachable, and the resume route
    is available only when the caller asked for it.
    """
    warnings: list[str] = []
    if target.pane_ref is not None and target.state in {"active", "idle"}:
        try:
            return build_pane_route(
                target, envelope, transports=transports, preflight=preflight
            )
        except NoOperationalRoute as pane_failure:
            if not allow_resume:
                raise
            warnings.append(
                f"pane route unusable ({pane_failure.reason}): "
                f"{pane_failure.detail}; falling back to the explicitly "
                "authorized resume transport — the target's live TUI will not "
                "show this envelope, and its pane_ref probably needs rebuilding"
            )
    return build_resume_route(
        target,
        envelope,
        allow_resume=allow_resume,
        which=which,
        warnings=tuple(warnings),
    )


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


class DeliveryPlan(NamedTuple):
    payload: dict[str, Any]
    route: DeliveryRoute


def plan_delivery(
    repo: Path,
    *,
    sender_name: str,
    target_name: str,
    message: str,
    nonce: str,
    script_path: Path,
    transports: dict[str, Callable[[], PaneTransport]] | None = None,
    allow_resume: bool = False,
    preflight: bool = True,
    which: Callable[[str], str | None] = shutil.which,
) -> DeliveryPlan:
    sender = load_agent(repo, sender_name)
    target = load_agent(repo, target_name)
    if sender.brand not in SUPPORTED_BRANDS:
        raise RegistryError(f"unsupported sender brand: {sender.brand!r}")
    target_state = derive_effective_state(target)
    routed_target = target._replace(state=target_state["effective_state"])
    envelope = build_envelope(
        sender, target, message, nonce=nonce, script_path=script_path
    )
    route = build_route(
        routed_target,
        envelope,
        transports=transports,
        allow_resume=allow_resume,
        preflight=preflight,
        which=which,
    )
    payload = {
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
        "argv": route.argv if route.mode == ROUTE_RESUME else route.pane_argv(),
        "submit_argv": route.submit_argv(),
        "route_mode": route.mode,
        "pane_transport": route.transport.name if route.transport else None,
        "pane_preflight": (
            route.preflight.detail
            if route.preflight is not None
            else (
                "not performed (the existence probe steals terminal focus, so it "
                "runs only on a real send)"
                if route.mode == ROUTE_PANE
                else None
            )
        ),
        "resume_authorized": allow_resume,
        "warnings": list(route.warnings),
    }
    return DeliveryPlan(payload=payload, route=route)


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
    parser = argparse.ArgumentParser(
        description="AgentTUI registry lifecycle and cross-brand direct messaging"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help=(
            "repository containing .arborist/ (default: inferred from this "
            "script's location, then validated — the inferred path must itself "
            "contain .trellis/ or .git/, otherwise the run is refused instead of "
            "reading or creating a registry somewhere else; pass this explicitly "
            "when running the script from outside a project repository)"
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
    send.add_argument(
        "--allow-resume",
        action="store_true",
        help=(
            "opt in to the resume transport (append to the target's session file). "
            "Off by default: without it, a target with no reachable pane is "
            "refused with no-operational-route rather than silently downgraded, "
            "because resume changes the semantics — the reply comes back on THIS "
            "process's stdout and never appears in the target's live TUI"
        ),
    )
    send.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "print the routing decision without sending; the pane existence "
            "probe is skipped because it steals terminal focus"
        ),
    )

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


def echo_transport_output(outcome: CommandOutcome) -> None:
    if outcome.stdout:
        print(outcome.stdout, end="" if outcome.stdout.endswith("\n") else "\n")
    if outcome.stderr:
        print(
            outcome.stderr,
            file=sys.stderr,
            end="" if outcome.stderr.endswith("\n") else "\n",
        )


def send_via_pane(
    route: DeliveryRoute,
    payload: dict[str, Any],
    *,
    timeout: float | None,
    submit_delay: float | None,
) -> int:
    """Inject into a live pane, then judge delivery only by the rule 3 nonce.

    Exit status of the transport commands is never consulted as a success signal:
    a live session with a dead pane answers rc=0 with empty output, so a clean
    invocation proves nothing. Rejections are recognised from command *text*; the
    only positive evidence is the per-send nonce appearing in the transcript.
    """
    transport = route.transport
    assert transport is not None and route.pane_ref is not None
    assert route.pane_text is not None and route.submit_byte is not None
    session_file = Path(payload["target_session_file"])
    boundary = transcript_size(session_file)
    submit_rejection: str | None = None
    delivered = False

    try:
        injected = transport.write_chars(
            route.pane_ref, route.pane_text, cwd=route.cwd, timeout=timeout
        )
        echo_transport_output(injected)
        if injected.rejected:
            raise NoOperationalRoute(
                "pane-injection-rejected",
                injected.detail,
                remedy=(
                    "rebuild the target's pane_ref entirely (a renamed session or "
                    "closed pane rots the whole handle) and send again — nothing "
                    "was injected"
                ),
            )

        if submit_delay is None:
            submit_delay = (
                CODEX_PANE_SUBMIT_DELAY_SECONDS
                if payload["target_brand"] == "codex"
                else 0.0
            )
        if submit_delay:
            time.sleep(submit_delay)
        submitted = transport.send_key(
            route.pane_ref, route.submit_byte, cwd=route.cwd, timeout=timeout
        )
        echo_transport_output(submitted)
        if submitted.rejected:
            # The envelope text already went out, so this is not "nothing was
            # sent"; it is a send whose delivery cannot be proven.
            submit_rejection = submitted.detail
        else:
            delivered = wait_for_transcript_marker(
                session_file, payload["delivery_marker"], boundary
            )
            # Rule 2: an enqueue key must never be resent (it would enqueue a
            # duplicate envelope). Only a plain submit may be retried.
            enqueued_for_next_turn = (
                payload["target_brand"] == "codex"
                and payload["target_effective_state"] == "active"
            )
            if not delivered and not enqueued_for_next_turn:
                time.sleep(max(submit_delay, PANE_VERIFY_INTERVAL_SECONDS))
                submitted = transport.send_key(
                    route.pane_ref, route.submit_byte, cwd=route.cwd, timeout=timeout
                )
                echo_transport_output(submitted)
                if submitted.rejected:
                    submit_rejection = submitted.detail
                else:
                    delivered = wait_for_transcript_marker(
                        session_file, payload["delivery_marker"], boundary
                    )
    except subprocess.TimeoutExpired as exc:
        raise RegistryError(
            "delivery attempt timed out; the target may still have queued the message"
        ) from exc

    if submit_rejection is not None:
        print(
            "warning: the envelope text was injected but the submit key was "
            f"rejected ({submit_rejection}); the envelope may be sitting "
            "unsubmitted in the target's input box, so this is not delivery "
            "evidence and a blind resend can duplicate it — rebuild the target's "
            "pane_ref and inspect the target before retrying",
            file=sys.stderr,
        )
    elif not delivered:
        print(
            "warning: the pane transport reported no addressing error, but this "
            "envelope nonce was not found in the target transcript; command "
            "success is not delivery evidence, so the message may still be queued "
            "or sitting in the input box — retry when the target is idle or seek "
            "an explicit peer reply",
            file=sys.stderr,
        )
    print(
        json.dumps(
            {
                "delivery": (
                    DELIVERY_DELIVERED if delivered else DELIVERY_QUEUED_UNVERIFIED
                ),
                "route_mode": ROUTE_PANE,
                "pane_transport": transport.name,
                "target": payload["target"],
                "target_brand": payload["target_brand"],
                "nonce": payload["nonce"],
                "evidence": "envelope-nonce-found" if delivered else "none",
                "sent": True,
                "retry_safe": False,
                "transport_exit_status_trusted": False,
                "submit_rejected": submit_rejection,
                "acknowledged": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


def send_via_resume(
    route: DeliveryRoute,
    payload: dict[str, Any],
    *,
    timeout: float | None,
) -> int:
    assert route.argv is not None
    session_file = Path(payload["target_session_file"])
    if session_file.is_file() and session_file.stat().st_size >= LARGE_TRANSCRIPT_BYTES:
        print(
            f"warning: target transcript is {session_file.stat().st_size:,} bytes; "
            "resume may be expensive because it loads the target context",
            file=sys.stderr,
        )
    try:
        result = run_command(route.argv, cwd=route.cwd, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RegistryError(
            "delivery attempt timed out; the target may still have queued the message"
        ) from exc
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            file=sys.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
        )
    if result.returncode != 0:
        print(
            "warning: the delivery command returned non-zero; delivery is uncertain, "
            "not proven failed (busy sessions may queue the message)",
            file=sys.stderr,
        )
    return result.returncode


def command_send(args: argparse.Namespace, repo: Path) -> int:
    script_path = Path(__file__).resolve()
    if args.pane_submit_delay is not None and (
        not math.isfinite(args.pane_submit_delay) or args.pane_submit_delay < 0
    ):
        raise RegistryError("--pane-submit-delay must be finite and non-negative")

    plan = plan_delivery(
        repo,
        sender_name=args.sender,
        target_name=args.target,
        message=args.message,
        nonce=str(uuid.uuid4()),
        script_path=script_path,
        allow_resume=args.allow_resume,
        # The existence probe moves the terminal focus, so a dry run must not run
        # it; the payload says so instead of pretending the check happened.
        preflight=not args.dry_run,
    )
    payload, route = plan
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    for warning in route.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if route.mode == ROUTE_PANE:
        return send_via_pane(
            route,
            payload,
            timeout=args.timeout,
            submit_delay=args.pane_submit_delay,
        )
    return send_via_resume(route, payload, timeout=args.timeout)


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
    try:
        repo = resolve_repo_root(
            args.repo if args.repo is not None else infer_repo_root(Path(__file__)),
            explicit=args.repo is not None,
        )
        if args.command == "send":
            return command_send(args, repo)
        if args.command == "heartbeat":
            return command_state(args, repo, "active")
        if args.command == "stop":
            return command_state(args, repo, "stopped")
        if args.command == "status":
            return command_status(args, repo)
    except NoOperationalRoute as exc:
        # Structured, non-zero, and never conflated with queued-unverified.
        print(json.dumps(exc.payload(), ensure_ascii=False), file=sys.stdout)
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NO_OPERATIONAL_ROUTE
    except RegistryError as exc:
        parser.error(str(exc))
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
