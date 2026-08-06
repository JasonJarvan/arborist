#!/usr/bin/env python3
"""Registry-aware AgentTUI lifecycle and direct-message helper."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import tempfile
import uuid
from collections.abc import Iterator, Mapping
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
# Brands whose TUI classifies a fast character stream as a paste burst and then
# treats the submit key as a newline *inside* that burst instead of submitting.
# Measured on one Codex version by a downstream adopter: the target was
# mechanically idle, both submit-key commands returned 0, and the envelope still
# sat in the composer; framing the same text as an explicit paste made the nonce
# appear about a second later. Deliberately a narrow allow-list, not "always
# frame": the same framing has no evidence behind it for other brands, and their
# composers may treat a paste differently (Claude Code, for instance, has its own
# paste handling). Adding a brand here needs its own measurement.
PASTE_FRAMED_BRANDS = frozenset({"codex"})
# Delivery-verification window, expressed in SECONDS on purpose. The previous
# form (attempts x interval = 10 x 0.1) hid the total behind a multiplication,
# which is exactly why nobody noticed the window was one second. Measured three
# independent times: a claude-code target's `type=user` record lands in well
# under five seconds, so a one-second window reported *delivered* messages as
# unverified -- and that false negative then drove the retry branch in
# send_via_pane to press submit a second time.
#
# The direction matters more than the number. Verification exits early on the
# first hit, so the success path pays nothing extra and widening is nearly free;
# narrowing turns a delivered message into "unverified" and provokes a duplicate
# submit. Widening is fail-safe, narrowing is fail-dangerous. Do not shrink
# these to make `send` return sooner. See agenttui-registry.md section 3, shape
# 4 ("verification window shorter than the target's flush").
PANE_VERIFY_WINDOW_SECONDS = 20.0
# An active Codex pane was handed Tab, so the envelope is queued and its nonce
# cannot appear before the current turn ends. Waiting out the full window buys
# nothing there, and `queued-for-next-turn` is the contractually expected
# reading -- so that tier stays deliberately short.
PANE_VERIFY_QUEUED_WINDOW_SECONDS = 1.0
# How long a *detached* resume runner is watched for the nonce. Same early-exit
# reasoning as the pane window, plus one difference that matters: this window
# bounds observation only. It never bounds the runner, which carries the target's
# whole turn and is deliberately left alive when the window ends.
RESUME_VERIFY_WINDOW_SECONDS = 20.0
PANE_VERIFY_POLL_INITIAL_SECONDS = 0.1
PANE_VERIFY_POLL_MAX_SECONDS = 1.0
# Terminal-standard bracketed-paste markers (see PaneTransport.frame_paste).
BRACKETED_PASTE_START = "\x1b[200~"
BRACKETED_PASTE_END = "\x1b[201~"
NONCE_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")

# ``pane_ref.socket`` — WHICH multiplexer *server* the pane id belongs to.
# Optional: absent means that transport's default server, so every pane_ref
# written before this field existed keeps addressing exactly what it addressed.
#
# It is load-bearing wherever pane ids are only server-unique (tmux documents
# ``%N`` as unique within one tmux server). Without it, the
# (multiplexer, session, pane_id) triple can name two *different* real panes on a
# machine running several servers: mostly the default server simply has no pane
# with that number and the send is refused loudly, but if it happens to have one
# *and* that pane's session name matches, every check passes and the envelope
# lands in an uninvolved session's composer — the silent mis-delivery the guide
# rates as its worst outcome (agenttui-registry.md §2.2.1).
#
# NEVER carry a socket in ``session`` instead. A field whose name and content
# disagree costs nothing today and misleads every later reader, including the
# session cross-check that exists to catch a rotted handle.
PANE_REF_DEFAULT_SOCKET = "default"


def normalize_pane_ref_socket(socket: str | None) -> str:
    """Lexical identity of the addressed server; absent == the default name.

    tmux's default socket really is *named* ``default``, so an absent field and an
    explicit ``"default"`` address the same server and must compare equal —
    otherwise two leaves sitting on one pane would not be seen as colliding, and
    uniqueness would be enforced on spelling rather than on the pane.

    Deliberately lexical only: a socket *path* is not resolved against a socket
    *name*, because that mapping depends on the environment of whoever wrote the
    leaf (socket directory, uid) and is not derivable from the leaf. The residual
    gap that leaves — the same server written once as a name and once as a path
    compares unequal — is recorded in agenttui-registry.md §3 rather than papered
    over with a guess. Mirrored in validate_agenttui_registry.py, and a test pins
    the two implementations to the same answers.
    """
    if socket is None:
        return PANE_REF_DEFAULT_SOCKET
    trimmed = socket.strip()
    return trimmed or PANE_REF_DEFAULT_SOCKET

# A derived repository root is only usable if it really is a project repository.
# See agenttui-registry.md §3 "delivery preflight" (path-derivation half).
REPO_MARKERS = (".trellis", ".git")

# Delivery outcome vocabulary, classified BY THE ACTION THAT WAS ACTUALLY
# EXECUTED rather than by a guess about the future. The single former
# "queued-unverified" bucket covered outcomes whose correct caller behaviour is
# opposite (wait out a turn boundary / recover an unsubmitted composer / inspect a
# command that never reported back), so a caller could not tell which one it had.
# See agenttui-registry.md §3 rule 4.
DELIVERY_DELIVERED = "delivered"
DELIVERY_PRE_INJECTION_REJECTED = "pre-injection-rejected"
DELIVERY_QUEUED_FOR_NEXT_TURN = "queued-for-next-turn"
DELIVERY_SUBMIT_UNVERIFIED = "submit-unverified"
DELIVERY_COMPOSER_UNSUBMITTED = "composer-unsubmitted"
DELIVERY_WRITE_UNVERIFIED = "write-unverified"
DELIVERY_SUBMIT_COMMAND_UNVERIFIED = "submit-command-unverified"
DELIVERY_RESUME_STARTED_UNVERIFIED = "resume-started-unverified"
DELIVERY_RESUME_EXITED_UNVERIFIED = "resume-exited-unverified"
DELIVERY_NO_OPERATIONAL_ROUTE = "no-operational-route"

# (recommended_action, verification_guidance) per outcome. A table rather than
# inline strings so that "which caller action does this outcome imply" is one
# greppable place, and so that adding an outcome without an action is impossible.
OUTCOME_GUIDANCE: dict[str, tuple[str, str]] = {
    DELIVERY_DELIVERED: (
        "await-peer-ack",
        "nonce-proves-transport-entry-not-semantic-acceptance",
    ),
    DELIVERY_PRE_INJECTION_REJECTED: (
        "retry-after-turn-state-readable",
        "no-pane-command-executed",
    ),
    DELIVERY_QUEUED_FOR_NEXT_TURN: (
        "wait-for-turn-boundary-do-not-resend",
        "early-transcript-miss-is-not-nondelivery-evidence",
    ),
    DELIVERY_SUBMIT_UNVERIFIED: (
        "inspect-target-or-await-ack-do-not-blind-resend",
        "do-not-infer-retry-safety-from-a-transcript-miss",
    ),
    DELIVERY_COMPOSER_UNSUBMITTED: (
        "recover-existing-composer-do-not-rewrite",
        "envelope-text-is-in-the-composer-unsubmitted",
    ),
    DELIVERY_WRITE_UNVERIFIED: (
        "inspect-target-do-not-resend",
        "command-failure-does-not-prove-zero-side-effects",
    ),
    DELIVERY_SUBMIT_COMMAND_UNVERIFIED: (
        "inspect-target-or-await-ack-do-not-blind-resend",
        "command-failure-does-not-prove-zero-side-effects",
    ),
    DELIVERY_RESUME_STARTED_UNVERIFIED: (
        "await-transcript-or-peer-ack-do-not-resend",
        "detached-runner-continues-after-sender-exit-do-not-resend",
    ),
    DELIVERY_RESUME_EXITED_UNVERIFIED: (
        "inspect-target-and-runner-exit-do-not-blind-resend",
        "runner-exit-does-not-prove-zero-side-effects-do-not-blind-resend",
    ),
}

# ``retry_safe`` is a claim that resending cannot duplicate anything, so it may
# only be set where zero pane commands are *mechanically* provable. Exactly two
# outcomes qualify: the send-side precondition failed before any command
# (no-operational-route), and the Codex turn state was unreadable before the
# first pane command (pre-injection-rejected). Everything else — including a
# command that merely failed to report back — is false, because a failed command
# does not prove the absence of side effects.
RETRY_SAFE_OUTCOMES = frozenset(
    {DELIVERY_NO_OPERATIONAL_ROUTE, DELIVERY_PRE_INJECTION_REJECTED}
)

EXIT_NO_OPERATIONAL_ROUTE = 3
# One pane command was issued and the result is indeterminate: the envelope may
# be sitting in the composer, or a command may have had a side effect without
# reporting it. Non-zero so that a shell caller cannot mistake it for delivery.
EXIT_UNCERTAIN_DELIVERY = 2
# Nothing was sent and retrying is safe, but unlike no-operational-route the
# route itself was fine — only the Codex turn state was unreadable. A distinct
# code so a caller can tell "repair the route" from "read the state again".
EXIT_PRE_INJECTION_REJECTED = 4
# The caller's repository root could not be established without guessing, so
# nothing was read and nothing was written. A distinct code because the previous
# behaviour — silently inferring a root from this script's own location — is what
# produced runs that succeeded against the WRONG repository; "which repo?" and
# "the registry says no" must not share an exit code.
EXIT_REPO_ROOT_UNSPECIFIED = 5

# Whether addressing the target disturbed it. Measured, not predicted: the focus
# probe answers rc=0 when it actually moved the focus (someone's view was pulled
# away) and rc=2 "already focused" when the target was already there (nobody was
# disturbed). Recording this per delivery yields the denominator for "how often
# does delivery actually steal focus" without running any new experiment.
INTRUSION_FOCUS_MOVED = "focus-moved"
INTRUSION_NONE = "already-focused"
INTRUSION_UNKNOWN = "unknown"
# A transport whose existence probe is *not* a focus command cannot have disturbed
# anyone, and that is a different fact from "the target happened to be focused
# already". Recording both as INTRUSION_NONE would merge a structural property
# with a lucky reading, and the analysis question ("would migrating remove the
# focus cost") is exactly the difference between them. Measured on a detached
# server, so it is a claim about the multiplexer's own state layer; whether an
# *attached* client stays put is still unverified (see TmuxTransport.exists).
INTRUSION_NO_FOCUS_COMMAND = "no-focus-command-issued"

# Focus-intrusion observations are appended here, one JSON object per pane
# delivery. Global rather than per-project on purpose: panes belong to the
# multiplexer, so folding bursts across projects requires one file.
#
# EVENTS ONLY -- this log deliberately stores no ratios and no counters, and
# nothing in this script computes an intrusion *rate*. Two measured reasons:
#
#   1. The measurement changes the measured quantity. The probe *is* the focus
#      command, so once one delivery pulls a pane into focus, every immediately
#      following delivery to that same pane reads "already focused" -- even
#      though the first one really did interrupt someone. A ratio therefore looks
#      *cleanest* exactly in the burst traffic that disturbs a human most. Only
#      absolute event counts, folded by an analyzer that can see the gaps between
#      them, mean anything.
#   2. Aggregation hides the stratification that carries the whole question. The
#      harm depends on where the human actually is: a delivery inside the session
#      and tab they are watching is a different event from one to a pane nobody is
#      looking at, and averaging the two answers neither "how common" nor "how
#      bad". Each record therefore carries its own stratification fields and the
#      folding is left to analysis time.
OBSERVATION_LOG_DEFAULT = Path.home() / ".arborist" / "focus-intrusion.jsonl"

# Capturing the active tab around the probe costs one extra read-only command, so
# it runs only when an observation is actually going to be recorded (see
# PaneTransport.observe_addressing). That is not just frugality: an unconditional
# extra command would change the command sequence every caller sees, which is
# itself the "measurement perturbs the measured system" failure this facility
# exists to keep honest. It is per-transport state rather than a module global for
# the same reason -- a global would leak the perturbation across callers.

# Receiver-side submit acknowledgement (rule 8). Two evidence sources answer two
# *different* questions, and neither subsumes the other:
#
#   transcript nonce -> "the envelope reached the session record"  (observer-side)
#   submit ack       -> "the receiver's submit hook actually fired" (causal)
#
# The ack matters most in the one combination the transcript alone cannot read:
# ack present + nonce absent = submitted, not yet flushed => a resend here would
# duplicate. That is precisely the case the retry branch below used to walk into.
#
# Absence of an ack is NEVER "not submitted": the hook may be uninstalled, may
# have been skipped by a tracked settings file (see ADOPT.md), or its write may
# have failed. The fail-safe direction is therefore one-sided -- unconfirmed.
ACK_STATUS_ACKED = "acked"
ACK_STATUS_UNCONFIRMED = "unconfirmed"
ACK_STATUS_UNAVAILABLE = "table-unreadable"
ACK_MODULE_NAME = "agenttui_submit_ack.py"

ROUTE_PANE = "pane"
ROUTE_RESUME = "resume"


SUBMIT_ACTIVITY_ACTIVE = "active"
SUBMIT_ACTIVITY_IDLE = "idle"
# Codex turn-boundary event types in the target's own transcript. These are the
# only mechanical evidence of "is a turn running right now"; transcript freshness
# is NOT that evidence (see agenttui-registry.md §3 rule 1).
CODEX_TURN_STARTED_EVENT = "task_started"
CODEX_TURN_COMPLETE_EVENT = "task_complete"


class RegistryError(RuntimeError):
    """The registry is incomplete, inconsistent, or unsafe to use."""


class RepoRootUnspecified(RegistryError):
    """The caller's repository root is not knowable without guessing.

    A subclass of RegistryError so that every existing caller keeps refusing, but
    a distinct type so the entry point can report it with its own exit code
    instead of burying it in the generic registry-error channel.
    """


class CodexTurnStateUnknown(RegistryError):
    """No safe Codex submit key can be chosen, and nothing has been sent yet.

    Raised only while zero pane commands have run, which is what lets the
    resulting outcome claim ``retry_safe=true`` (see RETRY_SAFE_OUTCOMES).
    """


class NoOperationalRoute(RegistryError):
    """No delivery route is operational, so nothing was sent.

    Strictly distinct from every ``*-unverified`` outcome: those mean the envelope
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


# --- Entry form: which copy of this script is running ------------------------
# Two entry forms exist and they need OPPOSITE defaults for "no --repo given":
#
#   project-copy      <repo>/.trellis/scripts/agenttui.py -- adopted into the
#                     caller's own repository. parents[2] really IS the caller's
#                     repo root, so inferring it is correct and must keep working.
#   global-authority  one machine-wide copy, invoked through a shim from any
#                     repository. parents[2] is the repository that HOSTS the
#                     authority copy, which has nothing to do with the caller.
#
# resolve_repo_root() cannot separate these: it only proves the derived path
# *looks like* a project repository — and the authority's host does. The observed
# result is a run that succeeds against the WRONG repository. Per §2.2.1 of
# agenttui-registry ("mis-delivery is more severe than unreachability"), a
# visible failure is always better than an invisible success, so the global form
# must refuse rather than infer.
ENTRY_FORM_ENV = "ARBORIST_ENTRY_FORM"
ENTRY_FORM_GLOBAL = "global-authority"
ENTRY_FORM_PROJECT = "project-copy"
ENTRY_FORM_UNKNOWN = "unknown"
ENTRY_FORMS = (ENTRY_FORM_GLOBAL, ENTRY_FORM_PROJECT)
# The layout that infer_repo_root()'s parents[2] arithmetic is built on, read
# from the script outward: <repo>/.trellis/scripts/<script>. Checking it is not
# path guessing — it is verifying the inference's own stated precondition before
# trusting the inference. It is the *backstop*; the declared signal above wins.
ADOPTED_SCRIPT_ANCESTRY = ("scripts", ".trellis")


def classify_entry_form(
    script_path: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return ``(entry_form, evidence)``; never guesses in the unsafe direction.

    Precedence: the declared signal (set by whoever installed the entry point)
    beats structure, because only the installer knows what it built. An
    unrecognised declared value is ``unknown`` rather than a fallback to
    structure — a typo in the signal must not silently re-enable inference.
    """
    environ = os.environ if env is None else env
    declared = environ.get(ENTRY_FORM_ENV)
    if declared:
        if declared in ENTRY_FORMS:
            return declared, f"{ENTRY_FORM_ENV}={declared}"
        return (
            ENTRY_FORM_UNKNOWN,
            f"{ENTRY_FORM_ENV}={declared!r} is not one of "
            f"{', '.join(ENTRY_FORMS)}",
        )
    resolved = script_path.resolve()
    ancestry = tuple(parent.name for parent in resolved.parents[:2])
    if ancestry == ADOPTED_SCRIPT_ANCESTRY:
        return (
            ENTRY_FORM_PROJECT,
            f"{ENTRY_FORM_ENV} unset; this script sits at the adopted location "
            f".trellis/scripts/{resolved.name}, so its repo-root inference holds",
        )
    return (
        ENTRY_FORM_UNKNOWN,
        f"{ENTRY_FORM_ENV} unset and this script does not sit at "
        f".trellis/scripts/{resolved.name} (found .../{'/'.join(reversed(ancestry))}"
        f"/{resolved.name}), so its repo-root inference has no basis",
    )


def resolve_caller_repo_root(
    explicit: Path | None,
    *,
    script_path: Path,
    env: Mapping[str, str] | None = None,
) -> Path:
    """The single gate every project-state command passes before reading anything.

    Deliberately no exemptions: every subcommand of this script reads or writes
    project state (send/heartbeat/stop/status all go through the repo's
    ``.arborist/``). ``--help`` is exempt only because argparse handles it during
    parsing, before this runs — an exemption granted by the call order, not by a
    list here that could rot.
    """
    if explicit is not None:
        return resolve_repo_root(explicit, explicit=True)
    form, evidence = classify_entry_form(script_path, env)
    if form != ENTRY_FORM_PROJECT:
        raise RepoRootUnspecified(
            "refusing to infer the caller's repository root: entry form is "
            f"{form!r} ({evidence}). A global entry point must be told "
            "the caller's repo root explicitly — pass --repo <caller repo root>. "
            "Nothing was read and nothing was written: inferring here would "
            "silently target the repository that hosts this script, and a run "
            "that succeeds against the wrong repository is worse than one that "
            "refuses"
        )
    return resolve_repo_root(infer_repo_root(script_path), explicit=False)


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
    # Role-inheritance generation, from spec.json. Absent reads as 1 (the first
    # holder) per section 2.1 -- so a leaf written before this field existed keeps
    # working. Defaulted here too, which keeps every existing construction site
    # valid; the point of rolling it up is that a cross-project reader looking for
    # "the current holder of this role" needs it in the summary, not just the leaf.
    lineage: int = 1
    # Set only for a leaf that declares itself a cross-project mirror. When set,
    # every runtime field above was read from `mirror.runtime_path` (the home leaf,
    # the only place the target's heartbeat writes), and `mirror_stale` lists the
    # addressing fields where the mirror's own copy has already rotted. Both
    # default to "not a mirror", so every existing construction site is unchanged.
    mirror: "MirrorRegistration | None" = None
    mirror_stale: tuple[str, ...] = ()
    # The project half of this agent's cross-project identity: `project_id`
    # **derived from `project_path`**, not the literal in the spec (a hand-copied
    # literal is how one repo splits into two identities, guide §2.3). Empty means
    # "not derived", which every consumer must treat as unqualified rather than
    # local; `load_agent` always fills it.
    project_qualifier: str = ""


class Capability(NamedTuple):
    """Answer to one capability question, with the text that justified it."""

    ok: bool
    detail: str


class CommandOutcome(NamedTuple):
    """Result of one transport command.

    ``rejected`` is decided by *stdout and stderr joined*, never by ``returncode``:
    multiplexers are observed to exit 0 for a missing session and for a missing
    pane, with the "not found" diagnostic on stderr while stdout carries ordinary
    content. And note the worst case that no post-hoc parsing can rescue — a live
    session with a dead pane answers rc=0 with *both streams empty* — so a clean
    outcome here is **not** delivery evidence (rule 3's nonce is).
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

    #: Opt-in: capture the extra stratification readings around the existence
    #: probe. Off by default so that callers who are not recording observations
    #: see exactly the command sequence they would have seen without this
    #: facility -- the measurement must not perturb non-measuring callers.
    observe_addressing = False

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

    def addressing_intrusion(self) -> str | None:
        """Did the last existence probe disturb the target, and how?

        Transports that address panes through focus cannot avoid disturbing a
        human sharing the multiplexer, and cannot know *in advance* whether a
        given send will disturb one -- but the probe's own answer says so
        afterwards. Reporting it turns an architectural cost into a measurable
        rate, which is what decides whether that cost is worth a migration.

        Returns one of ``INTRUSION_*``, or ``None`` when the transport cannot
        tell (never guess: an unknown must not be counted as "did not disturb").
        """
        return None

    def addressing_observation(self) -> dict[str, Any]:
        """Stratification facts about the last probe that this transport can attest.

        Never a summary and never a rate: a rate computed here would be wrong for
        two measured reasons (see OBSERVATION_LOG_DEFAULT). Unknown facts must be
        reported as ``None`` rather than omitted or guessed -- an absent field
        reads as "nothing happened", which is the failure mode being avoided.
        """
        return {}

    def frame_paste(self, text: str) -> str:
        """Mark ``text`` as one paste burst rather than a stream of keystrokes.

        WHY THIS SITS ON THE ABSTRACTION AND NOT IN ``ZellijTransport`` ALONE:
        the *intent* — "deliver this envelope as a single paste, so the receiving
        TUI cannot interleave the submit key into it" — is a transport capability
        question that any pane transport must answer, and the routing layer asks
        it without naming a multiplexer (``DeliveryRoute.paste_framed``). The
        *mechanism* is per transport, which is why this is an overridable method
        and not a module-level string operation: the sequences below are the
        terminal-standard bracketed-paste markers, correct for any transport whose
        write primitive is a raw byte stream into the pane's pty (which is what
        every multiplexer's "type this text" verb is). A transport with a native
        paste primitive — a buffer-load-and-paste verb, say — should override this
        and use it instead of injecting escape bytes.

        Not free of a caveat: the receiving application must have bracketed-paste
        mode enabled for these bytes to be interpreted rather than displayed. That
        is why the caller decides by brand (PASTE_FRAMED_BRANDS) instead of this
        being applied unconditionally.
        """
        return f"{BRACKETED_PASTE_START}{text}{BRACKETED_PASTE_END}"

    def write_chars_argv(
        self,
        pane_ref: dict[str, str],
        text: str,
        *,
        paste_framed: bool = False,
    ) -> list[str]:
        raise NotImplementedError

    def send_key_argv(self, pane_ref: dict[str, str], key_byte: str) -> list[str]:
        raise NotImplementedError

    def write_chars(
        self,
        pane_ref: dict[str, str],
        text: str,
        *,
        paste_framed: bool = False,
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
    # Capability question, asked without naming a transport: must this text reach
    # the pane as one paste burst rather than as a keystroke stream?
    paste_framed: bool = False
    submit_activity: str | None = None
    preflight: Capability | None = None
    warnings: tuple[str, ...] = ()

    def pane_argv(self) -> list[str] | None:
        if self.mode != ROUTE_PANE or self.transport is None:
            return None
        assert self.pane_ref is not None and self.pane_text is not None
        return self.transport.write_chars_argv(
            self.pane_ref, self.pane_text, paste_framed=self.paste_framed
        )

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


# --- project-qualified agent identity ----------------------------------------
#
# An agent name is unique **within one project**, never across the machine, so a
# bare name is not an identity: two repos routinely hold a same-role agent under
# the same name. That makes an unqualified `from=` in an envelope ambiguous in the
# worst possible direction — the receiver reads it as **its own repo's** agent of
# that name, so the envelope is not just mis-addressed, it is **signed with
# somebody else's name**, and everything the receiver sees is self-consistent.
#
# The path is demonstrable rather than anecdotal, and both halves are re-checkable:
# (a) `send --repo <other repo> --from <name>` **passes** registry validation
# whenever that other repo happens to hold a leaf of the same name, and (b) the
# envelope carried no project qualifier at all. No claim is made here that such a
# delivery has actually happened.
#
# Qualifier = the registry's `project_id`, never the repository's directory name:
# a directory can be renamed and one repository can have several worktrees, while
# `project_id` is derived from `realpath` (guide §2.1) and so answers "which
# project instance" mechanically.
QUALIFIED_NAME_SEPARATOR = "."

# A 12-hex prefix followed by the separator. Strict enough that a bare name
# containing a dot cannot be mistaken for a qualified one, which matters because
# the fallback for "unqualified" must never be "assume this repo".
QUALIFIED_NAME_PATTERN = re.compile(r"^([0-9a-f]{12})\.(.+)$")

REGISTRY_VALIDATOR_MODULE_NAME = "validate_agenttui_registry.py"


def registry_project_id(path: Path) -> str:
    """`project_id` for one repo root, computed by the registry's own implementation.

    Deliberately not reimplemented here, for the same reason the ack module refuses
    to: two implementations of a derived id is how one repo ends up with two ids
    (guide §2.3). Unlike the ack module, an unavailable implementation **fails
    closed** rather than recording null — the value signs the envelope, and an
    unsigned envelope is precisely the gap this qualifier closes.
    """

    module_path = Path(__file__).resolve().parent / REGISTRY_VALIDATOR_MODULE_NAME
    if not module_path.is_file():
        raise RegistryError(
            f"{REGISTRY_VALIDATOR_MODULE_NAME} is not installed next to this script, "
            "so the project qualifier that identifies this project cannot be "
            "computed. Refusing to send an envelope whose from/to would be a bare "
            "name: a bare name reads as the receiver's own agent of that name"
        )
    try:
        spec = importlib.util.spec_from_file_location(
            "_agenttui_registry_validator", module_path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Registered before exec: a module executed while absent from sys.modules
        # cannot resolve its own name (the validator's dataclasses then fail with
        # an unrelated-looking AttributeError).
        sys.modules["_agenttui_registry_validator"] = module
        spec.loader.exec_module(module)
        return str(module.project_id_for(path))
    except RegistryError:
        raise
    except Exception as exc:
        sys.modules.pop("_agenttui_registry_validator", None)
        raise RegistryError(
            f"cannot compute the project qualifier for {path} via "
            f"{REGISTRY_VALIDATOR_MODULE_NAME}: {exc}"
        ) from exc


def parse_qualified_name(value: str) -> tuple[str | None, str]:
    """Split `<project_id>.<name>` into its halves; a bare name yields None.

    None means **unqualified**, which is explicitly *not* "belongs to this repo":
    silently reading it as local is the defect this whole facility addresses.
    """

    match = QUALIFIED_NAME_PATTERN.match(value.strip())
    if match is None:
        return None, value.strip()
    return match.group(1), match.group(2)


def qualified_name(agent: AgentRecord) -> str:
    """How this agent is named to anybody outside its own project."""

    return f"{agent.project_qualifier}{QUALIFIED_NAME_SEPARATOR}{agent.name}"


def load_agent_by_reference(repo: Path, reference: str) -> AgentRecord:
    """Load a leaf named either bare or `<project_id>.<name>`, fail closed on mismatch.

    A qualified reference is **verified against the leaf actually loaded**, so
    pasting the `from=` out of a received envelope into a reply cannot resolve to
    this repo's same-named agent: it refuses instead. That is the receiver-side
    half of the qualifier — without it, a qualified name in an envelope would be
    decoration a replier's command line silently discards.
    """

    qualifier, name = parse_qualified_name(reference)
    agent = load_agent(repo, name)
    if qualifier is not None and qualifier != agent.project_qualifier:
        raise RegistryError(
            f"project-qualified name {reference!r} does not name the agent that "
            f"{repo} holds under {name!r}: that leaf's project qualifier is "
            f"{agent.project_qualifier} (project {agent.project_path}). Same name, "
            "different instance — refusing rather than resolving to the local "
            "agent of that name, which would deliver to, or sign as, somebody "
            "else. If the intended agent lives in another project, register an "
            "authorised mirror of it here (spec field "
            f"{FOREIGN_REGISTRATION_FIELD}) instead of borrowing this leaf"
        )
    return agent


class MirrorRegistration(NamedTuple):
    """A leaf that declares itself a cross-project mirror of an authoritative one.

    Cross-project delivery has no repo-crossing parameter: ``plan_delivery`` takes
    one repo root and loads *both* sides from it, so "repo A's sender reaches repo
    B's target" is expressible only by giving repo A a second leaf for that target
    (guide §2.2.1: a human-authorised mirror, not stray data). What the mirror may
    not carry is *authority*: its runtime half is a copy taken at mirroring time,
    while the target's heartbeat only ever writes its **home** leaf.
    """

    home: Path
    spec_path: Path
    runtime_path: Path
    reason: str
    authorized_by: str


# The self-declaration that makes a mirror a mirror. All three are required: a
# mirror without `home_registry` has no authority to defer to, and one without
# `reason` / `authorized_by` is indistinguishable from the mis-registration the
# uniqueness checks exist to catch (guide §2.2.1, "先判性质，再判对错").
FOREIGN_REGISTRATION_FIELD = "foreign_repo_registration"
FOREIGN_REGISTRATION_REQUIRED = ("home_registry", "reason", "authorized_by")

# Runtime fields that *address* the target: a stale value here sends the envelope
# somewhere. `session_id` addresses the resume route, `pane_ref` the pane route,
# and `session_file` is the probe every reachability decision is derived from, so
# a stale one routes off a state that was never observed. Divergence in these is
# reported loudly on the delivery path (and as a validator failure); everything
# else in a mirrored runtime is a snapshot field whose divergence is expected.
MIRROR_ADDRESSING_FIELDS = ("session_id", "session_file", "pane_ref")


def resolve_mirror_registration(
    spec: dict[str, Any],
    *,
    spec_path: Path,
    name: str,
    project_path: Path,
) -> MirrorRegistration | None:
    """Validate a leaf's mirror self-declaration, or return None if it has none.

    Every failure here raises. A mirror whose home cannot be validated must not
    silently degrade to "use the copy": the copy's `pane_ref` is exactly the stale
    handle this whole path exists to stop using, and panes get reused in sequence,
    so the degraded read delivers into whoever holds that pane now — silently, and
    into a third party (guide §2.2.1: 误投 > 不可达, 一个能被看见的失败恒优于一个
    看不见的成功).
    """

    declaration = spec.get(FOREIGN_REGISTRATION_FIELD)
    if declaration is None:
        return None
    if not isinstance(declaration, dict):
        raise RegistryError(
            f"{spec_path}: {FOREIGN_REGISTRATION_FIELD} must be an object"
        )
    values = {
        field: require_text(
            declaration.get(field), f"{spec_path}: {FOREIGN_REGISTRATION_FIELD}.{field}"
        )
        for field in FOREIGN_REGISTRATION_REQUIRED
    }

    home_declared = Path(values["home_registry"])
    if not home_declared.is_absolute():
        raise RegistryError(
            f"{spec_path}: {FOREIGN_REGISTRATION_FIELD}.home_registry must be an "
            f"absolute path to the authoritative leaf directory, got "
            f"{values['home_registry']!r}; a relative path would resolve against "
            "whatever cwd the sender happened to run in"
        )
    home = home_declared.resolve()
    if not home.is_dir():
        raise RegistryError(
            f"{spec_path}: {FOREIGN_REGISTRATION_FIELD}.home_registry is not a "
            f"directory: {home}. Refusing to fall back to this mirror's own runtime "
            "copy: it is a snapshot taken at mirroring time and its pane_ref may "
            "now address a pane a different session owns"
        )
    if home == spec_path.parent.resolve():
        raise RegistryError(
            f"{spec_path}: {FOREIGN_REGISTRATION_FIELD}.home_registry points at "
            "this same leaf, so the mirror claims to be its own authority"
        )

    home_spec_path = home / "spec.json"
    home_runtime_path = home / "runtime.json"
    home_spec = read_json(home_spec_path)
    if FOREIGN_REGISTRATION_FIELD in home_spec:
        raise RegistryError(
            f"{home_spec_path} is itself a mirror ({FOREIGN_REGISTRATION_FIELD} "
            "present): mirror chains are refused, a mirror must name the "
            "authoritative leaf directly"
        )
    home_name = require_text(home_spec.get("name"), f"{home_spec_path}: name")
    if home_name != name:
        raise RegistryError(
            f"mirror points at the wrong agent: {spec_path} mirrors {name!r} but "
            f"{home_spec_path} names {home_name!r}"
        )
    home_project = home_spec.get("project")
    if not isinstance(home_project, dict):
        raise RegistryError(f"{home_spec_path}: project must be an object")
    home_project_path = Path(
        require_text(home_project.get("path"), f"{home_spec_path}: project.path")
    ).expanduser()
    home_project_path = (
        home_project_path.resolve()
        if home_project_path.exists()
        else home_project_path.absolute()
    )
    if home_project_path != project_path:
        raise RegistryError(
            f"mirror points at the wrong project: {spec_path} declares "
            f"project.path {project_path} but its home {home_spec_path} declares "
            f"{home_project_path}. A mirror's project fields must name the agent's "
            "real home project (guide §2.2.1), so a divergence here means the "
            "mirror addresses an agent other than the one it claims"
        )
    return MirrorRegistration(
        home=home,
        spec_path=home_spec_path,
        runtime_path=home_runtime_path,
        reason=values["reason"],
        authorized_by=values["authorized_by"],
    )


def mirror_addressing_drift(
    mirror_runtime: dict[str, Any],
    home_runtime: dict[str, Any],
) -> tuple[str, ...]:
    """Which addressing fields the mirror's stale copy disagrees with home on.

    Reported, never silently repaired: rewriting the mirror to match would hide
    the fact that mirrors rot at all, and that fact is the reason the home leaf
    has to be read on every delivery rather than periodically synced.
    """

    return tuple(
        field
        for field in MIRROR_ADDRESSING_FIELDS
        if mirror_runtime.get(field) != home_runtime.get(field)
    )


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

    # A leaf without the self-declaration takes exactly the path it always took:
    # `mirror` is None, nothing below is reached, and every field still comes from
    # this repo's own runtime.json (pinned by test).
    mirror = resolve_mirror_registration(
        spec, spec_path=spec_path, name=spec_name, project_path=project_path
    )
    mirror_stale: tuple[str, ...] = ()
    if mirror is not None:
        home_runtime = read_json(mirror.runtime_path)
        mirror_stale = mirror_addressing_drift(runtime, home_runtime)
        # The mirror's own runtime copy is kept on disk (deleting it would break
        # readers that only know the mirror) but is demoted to diagnostics: from
        # here on, every addressing value comes from home.
        runtime = home_runtime
        runtime_path = mirror.runtime_path

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
        socket = pane_ref_value.get("socket")
        if socket is not None:
            # Optional (absent = the transport's default server) but *validated*
            # rather than coerced when present: a blank socket would quietly fall
            # back to the default server, which is precisely the silent
            # mis-delivery this field exists to prevent.
            pane_ref["socket"] = require_text(
                socket, f"{runtime_path}: pane_ref.socket"
            )

    raw_lineage = spec.get("lineage", 1)
    lineage = raw_lineage if isinstance(raw_lineage, int) and raw_lineage >= 1 else 1
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
        lineage=lineage,
        mirror=mirror,
        mirror_stale=mirror_stale,
        # One value, two uses — deliberately the *same* `project_path` that the
        # mirror check validated against home above. Addressing reads home and the
        # signature signs home because both derive from this one resolved path; two
        # separate derivations would be two things free to drift apart.
        project_qualifier=registry_project_id(project_path),
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
    # `from` / `to` are **project-qualified**, always. A bare name is unique only
    # inside one project, so an unqualified `from=` is read by the receiver as its
    # own agent of that name: the envelope arrives signed with somebody else's
    # name, and nothing the receiver can see contradicts it.
    #
    # `identity_form` is what makes the older, unqualified form mechanically
    # distinguishable instead of merely absent: a reader that finds this field
    # knows from/to can be compared against its own project_id, and a reader that
    # does NOT find it knows the names in that envelope are unqualified and
    # therefore **cannot** be used to judge instance identity. Absence had to be
    # given a meaning, because the alternative — treating an unqualified name as
    # local — is exactly the defect.
    return [
        f"from={qualified_name(sender)}",
        f"from_brand={sender.brand}",
        f"to={qualified_name(target)}",
        f"nonce={nonce}",
        "identity_form=project-qualified",
        "provenance=declared-not-authenticated",
    ]


def build_delivery_marker(
    sender: AgentRecord,
    target: AgentRecord,
    nonce: str,
) -> str:
    return " ".join(delivery_marker_fields(sender, target, nonce))


def reply_entry_argv(script_path: Path, env: Mapping[str, str] | None = None) -> list[str]:
    """The argv prefix a replier should use, preferring the stable global entry.

    The global shim is preferred because it is a single machine-wide path that
    stays valid even if the authority copy moves, whereas ``script_path`` is only
    valid while this particular copy exists where it is now. Falling back to
    ``python3 <script_path>`` is fine *because* the caller's repo travels in
    --repo either way (see build_envelope): the entry form is an optimisation,
    the --repo is the correctness requirement.
    """
    environ = os.environ if env is None else env
    home = environ.get("ARBORIST_HOME")
    global_root = Path(home) if home else Path.home() / ".arborist"
    shim = global_root / "bin" / "agenttui"
    if shim.is_file() and os.access(shim, os.X_OK):
        return [str(shim)]
    return ["python3", str(script_path)]


def build_envelope(
    sender: AgentRecord,
    target: AgentRecord,
    message: str,
    *,
    nonce: str,
    script_path: Path,
    repo: Path,
    env: Mapping[str, str] | None = None,
) -> str:
    if not message.strip():
        raise RegistryError("message must not be empty")
    marker_fields = delivery_marker_fields(sender, target, nonce)
    # --repo is mandatory here, not a nicety: without it the replier re-derives
    # the repo root from whatever copy of the script it happens to run, which is
    # exactly the wrong-repo failure this envelope's own sender just avoided. The
    # repo was already resolved once, in this process; propagate that answer
    # rather than making the second hop guess again.
    reply_command = shlex.join(
        [
            *reply_entry_argv(script_path, env),
            "--repo",
            str(repo),
            "send",
            # Project-qualified on both sides, for the same reason the marker is:
            # a reply pasted with bare names resolves against whatever repo the
            # replier is standing in. (Only these two values are qualified here;
            # the rest of this command's shape is owned elsewhere.)
            "--from",
            qualified_name(target),
            "--to",
            qualified_name(sender),
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
# Real tabs in a dumped layout carry a name; the swap-layout templates below them
# do not, which is what keeps this from matching a template.
ZELLIJ_FOCUSED_TAB_PATTERN = re.compile(r'tab name="([^"]+)"[^\n]*focus=true')

# Not an error: the probe says this when the target pane was already the focus.
# It shares rc=2 with "not found" but means the opposite, so it lives apart from
# the rejection patterns and is read as "nobody was disturbed".
ZELLIJ_ALREADY_FOCUSED_PATTERN = re.compile(r"\bis already focused\b", re.IGNORECASE)

# Only addressing *failures* belong here. Notably absent, on purpose: the probe's
# "already focused" answer, which shares rc=2 with "not found" but means the
# opposite (the pane exists and is exactly where we want it). Matching it would
# refuse delivery to the most common healthy case.
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
        self._last_intrusion: str | None = None
        self._last_observation: dict[str, Any] = {}

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

    def write_chars_argv(
        self,
        pane_ref: dict[str, str],
        text: str,
        *,
        paste_framed: bool = False,
    ) -> list[str]:
        # This verb types the argument into the pane as a raw byte stream, so the
        # standard bracketed-paste markers from the base class are exactly right
        # here; no zellij-specific paste primitive exists to prefer over them.
        payload = self.frame_paste(text) if paste_framed else text
        return self._action_argv(
            pane_ref, "write-chars", "--pane-id", pane_ref["pane_id"], payload
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
        # Judged by the two streams joined, never by the return code. Measured
        # on one multiplexer version: injection and submit commands return 0 for
        # a missing session *and* for a missing pane, and the diagnostic lands on
        # stderr while stdout may carry ordinary content (a session list). The
        # probe does return non-zero for a missing pane, but a non-zero code is
        # not a rejection signal either, and that is measured rather than merely
        # cautious: the probe answers rc=2 both for a pane that does not exist AND
        # for a pane that is *already focused*. Those two mean opposite things --
        # the second is positive existence evidence, and it is the state a
        # verified-successful delivery was in -- so only not-found *text* may
        # reject. See agenttui-registry.md section 3.
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
        """Existence preflight via ``focus-pane-id`` — judged by joined output.

        The verdict comes from stdout and stderr together: the "not found"
        diagnostic was measured on stderr, so reading stdout alone would miss it.

        ``dump-screen -p`` is deliberately NOT used: it returns empty output with
        exit status 0 for a pane that does not exist, i.e. it manufactures false
        positives.

        Side effect, stated plainly: this probe *is* the focus command, so it
        moves the terminal focus to the target pane. That is also what makes
        cross-tab injection work at all, and it is why delivery structurally
        conflicts with a human driving the same multiplexer session.
        """
        session = pane_ref["session"]
        observing = self.observe_addressing
        tab_before = self._active_tab(session) if observing else None
        outcome = self._run(self.probe_argv(pane_ref), cwd=None, timeout=None)
        self._last_intrusion = self._classify_intrusion(outcome)
        tab_after = self._active_tab(session) if observing else None
        own_session = self._own_session()
        self._last_observation = {
            "active_tab_before": tab_before,
            "active_tab_after": tab_after,
            # The strongest disturbance: the human's whole view changed tabs.
            # None (not False) when either reading is unknown -- a missing
            # reading must not be reported as "no switch happened".
            "tab_switched": (
                None
                if tab_before is None or tab_after is None
                else tab_before != tab_after
            ),
            "same_multiplexer_session": (
                None if own_session is None else own_session == session
            ),
        }
        if outcome.rejected:
            return Capability(
                False,
                f"pane {pane_ref['pane_id']!r} in session "
                f"{pane_ref['session']!r} is not reachable: {outcome.detail}",
            )
        moved = self._last_intrusion == INTRUSION_FOCUS_MOVED
        return Capability(
            True,
            f"pane {pane_ref['pane_id']!r} in session {pane_ref['session']!r} "
            + (
                "answered the existence probe and the focus was moved there "
                "(a human watching another pane just lost their view)"
                if moved
                else "answered the existence probe and was already focused "
                "(nobody's view was disturbed)"
            ),
        )

    def _active_tab(self, session: str) -> str | None:
        """Name of the currently focused tab, or None if it cannot be read.

        Read-only and best-effort: this is measurement, so it must never be able
        to fail a delivery. Any problem yields None, which analysis reads as
        "unknown" rather than "unchanged".
        """
        try:
            outcome = self._run(
                [self.executable, "--session", session, "action", "dump-layout"],
                cwd=None,
                timeout=None,
            )
        except Exception:  # measurement must not break delivery
            return None
        if outcome.returncode != 0:
            return None
        match = ZELLIJ_FOCUSED_TAB_PATTERN.search(outcome.stdout)
        return match.group(1) if match is not None else None

    def _own_session(self) -> str | None:
        return os.environ.get("ZELLIJ_SESSION_NAME") or None

    def _classify_intrusion(self, outcome: CommandOutcome) -> str | None:
        if outcome.rejected:
            # Nothing was delivered and nothing moved; the intrusion question
            # does not apply, and answering "none" would pad the denominator.
            return None
        if ZELLIJ_ALREADY_FOCUSED_PATTERN.search(f"{outcome.stdout}\n{outcome.stderr}"):
            return INTRUSION_NONE
        if outcome.returncode == 0:
            return INTRUSION_FOCUS_MOVED
        return INTRUSION_UNKNOWN

    def addressing_intrusion(self) -> str | None:
        return self._last_intrusion

    def addressing_observation(self) -> dict[str, Any]:
        return dict(self._last_observation)

    def write_chars(
        self,
        pane_ref: dict[str, str],
        text: str,
        *,
        paste_framed: bool = False,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> CommandOutcome:
        return self._run(
            self.write_chars_argv(pane_ref, text, paste_framed=paste_framed),
            cwd=cwd,
            timeout=timeout,
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


# --- Concrete transport: tmux -------------------------------------------------
# The second pane transport, deliberately *coexisting* with the one above rather
# than replacing it: both stay registered, so an existing pane_ref keeps working
# while panes migrate one at a time. Everything tmux-specific is confined below
# this line plus the TRANSPORTS entry; the delivery contract and the routing layer
# are untouched (ADR-0007 transport neutrality).

# Observed failure texts (tmux 3.4, measured on a private detached socket so that
# no human's terminal was touched). This transport does exit non-zero for a
# missing target, but the verdict is still taken from the *joined* streams: the
# same discipline holds for every transport, and one of tmux's own commands
# answers rc=0 for a target that does not exist (see TmuxTransport.exists).
TMUX_NOT_FOUND_PATTERNS = (
    re.compile(r"can't find pane\b", re.IGNORECASE),
    re.compile(r"can't find window\b", re.IGNORECASE),
    re.compile(r"can't find session\b", re.IGNORECASE),
    re.compile(r"no server running on\b", re.IGNORECASE),
    re.compile(r"error connecting to\b", re.IGNORECASE),
)

# Session name plus pane id per listed pane. Not an f-string anywhere: the braces
# are tmux's own format syntax.
TMUX_PANE_LISTING_FORMAT = "#{session_name}\t#{pane_id}"


class TmuxTransport(PaneTransport):
    """tmux implementation of the pane transport capabilities.

    Measured differences from the focus-addressed transport above, each of which
    shows up as a design decision in this class:

    1. ``send-keys -t <pane>`` is genuinely directed: it reaches a pane in a
       *different* window with no selection side effect at all (measured: the
       session's active window and every pane's ``pane_active`` flag were
       identical before and after, and no other pane received a byte). So the
       existence probe here does **not** have to be a focus command, which is
       this transport's substantive advantage over one that addresses panes
       through focus.
    2. The probe is therefore ``list-panes -t`` (``capture-pane -t`` would do as
       well): both answer rc=1 and ``can't find pane:`` for a missing target.
    3. ``display-message -p -t <missing>`` is **forbidden as an existence
       criterion**: measured rc=0 while silently falling back to the *current*
       pane's attributes. It is the same shape of trap as the other transport's
       screen-dump probe — the command that looks like the natural "just read
       this pane's properties" is exactly the one that lies. It is used below in
       one place only, without ``-t``, as a self-query.
    4. Addressing anchors on the pane id (``%N``), which tmux documents as
       unchanged for the life of the pane. A window rename, a pane renumber or
       ``base-index``/``pane-base-index`` offsets therefore cannot rot the
       address — unlike a handle whose addressing depends on a session *name*
       captured at launch time, which rots silently on rename. The session name
       is still carried in the pane_ref and is cross-checked below, so a rename
       surfaces as a loud refusal ("rebuild the pane_ref") rather than as a
       silent write into nowhere. That is a smaller rot surface, not none.
    5. A target's own pane is self-reported through ``TMUX_PANE``, so a pane_ref
       can be registered from authoritative self-knowledge instead of guessed by
       matching cwd and command.
    6. A pane id is unique only *within one server*, so every command below is
       addressed to the server named by ``pane_ref.socket`` (``socket_argv``).
       Omitting that dimension is what previously left a residual silent
       mis-delivery: on a machine running several servers, a same-numbered pane on
       the default server whose session name also matched would pass every check.

    Known limits, stated rather than implied. The measurements above were taken
    on a server with no client attached, so they are readings of the
    multiplexer's state layer; whether a *watching* human is left undisturbed is
    not verified here.
    """

    name = "tmux"
    executable = "tmux"

    def __init__(
        self,
        *,
        runner: CommandRunner = run_command,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._runner = runner
        self._which = which
        self._last_intrusion: str | None = None
        self._last_observation: dict[str, Any] = {}

    def available(self) -> Capability:
        located = self._which(self.executable)
        if located is None:
            return Capability(
                False, f"pane transport CLI {self.executable!r} is not installed"
            )
        return Capability(True, f"{self.executable} found at {located}")

    @staticmethod
    def socket_argv(pane_ref: dict[str, str]) -> list[str]:
        """Address the *server* this pane lives on: ``-L <name>`` or ``-S <path>``.

        A pane id is unique only within one server, so a pane_ref without this
        dimension is ambiguous on a machine running several — see
        PANE_REF_DEFAULT_SOCKET for what that ambiguity costs.

        Which of the two options to use is decided by the value's own shape: a
        value containing a path separator is a socket *path* (``-S``), anything
        else is a socket *name* (``-L``). That is the same distinction tmux's own
        two options draw, so no second schema field has to be invented and no
        single value can mean both.

        An absent socket yields **no arguments at all**, so a pane_ref written
        before this field existed produces a byte-identical command line.
        """
        socket = pane_ref.get("socket")
        if socket is None or not socket.strip():
            return []
        value = socket.strip()
        return ["-S", value] if os.sep in value else ["-L", value]

    def probe_argv(self, pane_ref: dict[str, str]) -> list[str]:
        """Read-only existence probe: errors loudly for a missing pane.

        Deliberately not ``display-message -p -t``, which answers rc=0 and the
        current pane's attributes for a target that does not exist.
        """
        return [
            self.executable,
            *self.socket_argv(pane_ref),
            "list-panes",
            "-t",
            pane_ref["pane_id"],
            "-F",
            TMUX_PANE_LISTING_FORMAT,
        ]

    def write_chars_argv(
        self,
        pane_ref: dict[str, str],
        text: str,
        *,
        paste_framed: bool = False,
    ) -> list[str]:
        # ``-l`` sends the argument literally, as a byte stream into the pane's
        # pty, so the base class's terminal-standard bracketed-paste markers are
        # exactly right and no override is needed. tmux does have a native paste
        # primitive (``load-buffer`` + ``paste-buffer -p``), and it is measured to
        # work, but it costs a second command and a *shared, named buffer* —
        # extra cross-delivery state, plus a different command sequence for
        # everyone. Whether framing happens at all stays the caller's brand-keyed
        # decision (PASTE_FRAMED_BRANDS), identical to the other transport.
        payload = self.frame_paste(text) if paste_framed else text
        return [
            self.executable,
            *self.socket_argv(pane_ref),
            "send-keys",
            "-t",
            pane_ref["pane_id"],
            "-l",
            payload,
        ]

    def send_key_argv(self, pane_ref: dict[str, str], key_byte: str) -> list[str]:
        # ``-H <hex>`` sends that literal byte, which is what the submit-key
        # contract names (Enter = 13, Codex's queue key = 9). A key *name*
        # (``send-keys Enter``) would go through tmux's key encoding instead,
        # and this machine's tmux configuration can enable extended keys, which
        # may change what Enter looks like on the wire.
        return [
            self.executable,
            *self.socket_argv(pane_ref),
            "send-keys",
            "-t",
            pane_ref["pane_id"],
            "-H",
            self._hex_byte(key_byte),
        ]

    @staticmethod
    def _hex_byte(key_byte: str) -> str:
        try:
            value = int(key_byte)
        except ValueError as exc:
            raise RegistryError(
                f"submit key must be a decimal byte value, got {key_byte!r}"
            ) from exc
        if not 0 <= value <= 255:
            raise RegistryError(f"submit key byte out of range: {key_byte!r}")
        return format(value, "02x")

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
        # Same rule as every other transport: judged by the two streams joined.
        # This one's exit status happens to be more trustworthy -- a missing pane
        # is rc=1 with a diagnostic, including for the injection command itself --
        # but the code is still not the criterion, because ``display-message -t``
        # answers rc=0 for a missing target. Trusting rc where it works and text
        # where it does not would give two rules to remember and one of them
        # silently wrong.
        text = f"{stdout}\n{stderr}"
        for pattern in TMUX_NOT_FOUND_PATTERNS:
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
                        f"(exit status {completed.returncode}; the text is the "
                        "criterion, not the code)"
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
        """Existence preflight via ``list-panes -t`` — judged by joined output.

        No focus is taken and no key is sent: unlike a focus-addressed transport,
        this probe is read-only, which is why nothing here has to warn about
        stealing a human's view. The honest boundary: that was measured on a
        server with **no client attached**, so it is a reading of the
        multiplexer's state layer, not proof that a watching human is undisturbed.

        Three refusals, all fail-closed:

        * the probe reported a not-found text (the pane, window, session or the
          server itself is gone);
        * the probe answered but the addressed pane id is not among the panes it
          listed — silence about the target is not evidence of the target;
        * the listed session name differs from ``pane_ref.session``. Addressing
          would still have worked (the pane id is server-unique), but a pane_ref
          whose fields disagree with reality has rotted, and delivering anyway is
          how an envelope lands in a stranger's composer. A whole new pane_ref is
          the remedy; patching one field is not.

        The probe is addressed to the *same server* as the delivery that follows
        it (``socket_argv``), which is what makes it a preflight for that delivery
        rather than a question about a different machine-local server that happens
        to have a pane with the same number.
        """
        observing = self.observe_addressing
        outcome = self._run(self.probe_argv(pane_ref), cwd=None, timeout=None)
        listed_session = self._listed_session(outcome.stdout, pane_ref["pane_id"])
        own_session = self._own_session() if observing else None
        same_server = self._same_server(pane_ref) if observing else None
        # Not INTRUSION_NONE: that value means "the target happened to be focused
        # already", a reading this probe never takes. Recording it here would let
        # a structural property masquerade as a lucky one in the same denominator.
        self._last_intrusion = None if outcome.rejected else INTRUSION_NO_FOCUS_COMMAND
        self._last_observation = {
            # Kept as explicit unknowns rather than omitted: an absent field reads
            # as "nothing happened", and this transport genuinely did not read the
            # attached client's view. It cannot switch a window either -- but that
            # is unverified under an attached client, so it is not claimed here.
            "active_tab_before": None,
            "active_tab_after": None,
            "tab_switched": None,
            "same_multiplexer_session": (
                # A different *server* settles it without comparing names: two
                # servers can each hold a session of the same name, so comparing
                # names across servers would answer "same session" about two panes
                # that cannot see each other.
                False
                if same_server is False
                else None
                if own_session is None or listed_session is None
                else own_session == listed_session
            ),
            "probe_is_focus_command": False,
            "observed_pane_session": listed_session,
            # Which server was addressed, as written in the pane_ref: None means
            # the default one. Recorded because a delivery to another server is a
            # different event from one inside the human's own server, and folding
            # them together is the stratification mistake OBSERVATION_LOG_DEFAULT
            # exists to avoid.
            "addressed_socket": pane_ref.get("socket"),
            "same_multiplexer_server": same_server,
        }
        if outcome.rejected:
            return Capability(
                False,
                f"pane {pane_ref['pane_id']!r} in session "
                f"{pane_ref['session']!r} is not reachable: {outcome.detail}",
            )
        if listed_session is None:
            return Capability(
                False,
                f"pane {pane_ref['pane_id']!r} was not among the panes the "
                "existence probe listed, and an answer that does not mention the "
                "target is not evidence of the target",
            )
        if listed_session != pane_ref["session"]:
            return Capability(
                False,
                f"pane {pane_ref['pane_id']!r} exists but reports session "
                f"{listed_session!r}, not the registered {pane_ref['session']!r}; "
                "this pane_ref has rotted and must be rebuilt in full, not "
                "patched field by field",
            )
        return Capability(
            True,
            f"pane {pane_ref['pane_id']!r} in session {pane_ref['session']!r} "
            "answered the read-only existence probe (no focus was taken, so "
            "nobody's view was disturbed)",
        )

    @staticmethod
    def _listed_session(stdout: str, pane_id: str) -> str | None:
        """Session name reported for ``pane_id``, or None if it was not listed."""
        for line in stdout.splitlines():
            session, separator, listed_pane = line.partition("\t")
            if separator and listed_pane.strip() == pane_id:
                return session
        return None

    def _own_session(self) -> str | None:
        """Which session this process itself sits in, or None if unknown.

        The one legitimate use of ``display-message -p``: with no ``-t`` it is a
        *self*-query, so the "silently falls back to the current pane" behaviour
        that disqualifies it as an existence probe is precisely what is wanted.
        Read-only, best-effort and measurement-only: any problem yields None,
        which analysis reads as "unknown" rather than "not the same session".
        """
        if not os.environ.get("TMUX_PANE"):
            return None
        try:
            outcome = self._run(
                [self.executable, "display-message", "-p", "#{session_name}"],
                cwd=None,
                timeout=None,
            )
        except Exception:  # measurement must not break delivery
            return None
        if outcome.rejected or outcome.returncode != 0:
            return None
        return outcome.stdout.strip() or None

    @staticmethod
    def _same_server(pane_ref: dict[str, str]) -> bool | None:
        """Is the addressed server this process's own server? None = unknown.

        Comparable only when both sides are socket *paths*: ``$TMUX`` reports a
        path, while ``pane_ref.socket`` may hold a name, and turning a name into a
        path means guessing this machine's socket directory and uid. Unknown is
        therefore reported as None instead of resolved by a guess — the reason the
        socket dimension exists at all is that a wrong same-server assumption is
        the silent mis-delivery. Measurement only, and it runs **no command**: the
        reading comes from an environment variable this process already holds.
        """
        own = os.environ.get("TMUX", "").split(",")[0]
        addressed = (pane_ref.get("socket") or "").strip()
        if not own or os.sep not in addressed:
            return None
        try:
            return os.path.realpath(own) == os.path.realpath(addressed)
        except OSError:  # measurement must never break delivery
            return None

    def addressing_intrusion(self) -> str | None:
        return self._last_intrusion

    def addressing_observation(self) -> dict[str, Any]:
        return dict(self._last_observation)

    def write_chars(
        self,
        pane_ref: dict[str, str],
        text: str,
        *,
        paste_framed: bool = False,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> CommandOutcome:
        return self._run(
            self.write_chars_argv(pane_ref, text, paste_framed=paste_framed),
            cwd=cwd,
            timeout=timeout,
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


# Single place where a multiplexer name maps to a transport, and the authoritative
# value domain of ``pane_ref.multiplexer``. Adding one is a new entry here plus a
# PaneTransport subclass; no routing code changes. Two transports coexist on
# purpose: migration is per pane, not a flag day. Moving a pane between them means
# rebuilding its whole pane_ref -- editing only ``multiplexer`` leaves an address
# from the old multiplexer under the new one's name.
TRANSPORTS: dict[str, Callable[[], PaneTransport]] = {
    ZellijTransport.name: ZellijTransport,
    TmuxTransport.name: TmuxTransport,
}


def resolve_transport(
    multiplexer: str,
    *,
    transports: dict[str, Callable[[], PaneTransport]] | None = None,
) -> PaneTransport | None:
    registry = TRANSPORTS if transports is None else transports
    factory = registry.get(multiplexer)
    return None if factory is None else factory()


# --- Codex submit activity (read-only, zero pane commands) --------------------
# Reachability and submit activity are two different questions that used to be
# answered by one value. Transcript freshness says "this pane is probably worth
# addressing"; it does NOT say "a turn is running right now". A target whose turn
# has just finished is still inside the freshness window, so routing on freshness
# hands Tab to an *idle* composer, where it enqueues nothing and the envelope sits
# there unsubmitted. This derivation answers the second question separately, from
# the target's own turn-boundary events.
#
# It reads a file and issues no transport command, which is what keeps the
# resulting refusal honest: an unreadable turn state must be reported as "nothing
# was sent", and that claim is only true if this inspection cannot touch the pane.


def iter_reverse_lines(
    path: Path,
    *,
    chunk_size: int = 64 * 1024,
    end_offset: int | None = None,
) -> Iterator[bytes]:
    """Yield a file's lines newest-first without reading the whole file.

    Transcripts grow without bound and the interesting record is always near the
    end, so a forward scan would make the cost of choosing a submit key scale
    with the target's history.
    """
    with path.open("rb") as stream:
        file_size = stream.seek(0, os.SEEK_END)
        position = file_size if end_offset is None else min(end_offset, file_size)
        remainder = b""
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            stream.seek(position)
            parts = (stream.read(read_size) + remainder).split(b"\n")
            remainder = parts[0]
            for line in reversed(parts[1:]):
                if line:
                    yield line
        if remainder:
            yield remainder


def derive_codex_submit_activity(session_file: Path) -> str | None:
    """Is the target Codex session executing a turn right now? None = unknown.

    The answer is the latest complete turn-boundary event, newest-first. A
    non-empty transcript whose last line has no terminating newline is a
    concurrent write in progress: that is reported as unknown rather than skipped,
    because skipping it would reuse an *older* boundary and confidently return
    the state the target was in before the record currently being written.
    """
    try:
        with session_file.open("rb") as transcript:
            snapshot_size = transcript.seek(0, os.SEEK_END)
            if snapshot_size == 0:
                return None
            transcript.seek(snapshot_size - 1)
            if transcript.read(1) != b"\n":
                return None
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None
    for raw_line in iter_reverse_lines(session_file, end_offset=snapshot_size):
        try:
            record = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or record.get("type") != "event_msg":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        event_type = payload.get("type")
        if event_type == CODEX_TURN_STARTED_EVENT:
            return SUBMIT_ACTIVITY_ACTIVE
        if event_type == CODEX_TURN_COMPLETE_EVENT:
            return SUBMIT_ACTIVITY_IDLE
    return None


def require_codex_submit_activity(session_file: Path) -> str:
    activity = derive_codex_submit_activity(session_file)
    if activity is None:
        raise CodexTurnStateUnknown(
            "cannot choose a safe Codex pane submit key: no trustworthy "
            f"{CODEX_TURN_STARTED_EVENT}/{CODEX_TURN_COMPLETE_EVENT} turn-boundary "
            f"event was found in {session_file}; refusing to guess the key from "
            "transcript freshness"
        )
    return activity


def codex_submit_byte(activity: str) -> str:
    """Tab enqueues to the next turn, Enter submits now — one place, brand-keyed.

    Shared by routing and by the pre-key refresh so that the two cannot drift.
    """
    if activity == SUBMIT_ACTIVITY_ACTIVE:
        return CODEX_PANE_QUEUE_BYTE
    if activity == SUBMIT_ACTIVITY_IDLE:
        return PANE_ENTER_BYTE
    raise RegistryError(f"unknown Codex submit activity: {activity!r}")


# --- Capability-based routing (transport-neutral) -----------------------------


def build_pane_route(
    target: AgentRecord,
    envelope: str,
    *,
    transports: dict[str, Callable[[], PaneTransport]] | None = None,
    preflight: bool = True,
    observe_addressing: bool = False,
    codex_submit_activity: str | None = None,
) -> DeliveryRoute:
    """Route to a live pane using only capability questions.

    Deliberately free of any multiplexer name or command line: the questions are
    "is a transport registered for this pane_ref", "is that transport usable",
    "does the addressed pane exist" (rule 5). Which multiplexer answers them is
    the registry's business.

    ``codex_submit_activity`` must already have been derived by the caller, and
    the refusal below must stay *before* the existence probe: the probe is a pane
    command (it moves the focus), so deriving or re-deriving the turn state here
    would destroy the "zero pane commands" property that
    ``pre-injection-rejected`` claims.
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
    # Last check before the first pane command. Structural route failures above
    # take precedence (their remedy is "repair the route", not "read the state
    # again"), but this one must stay ahead of the probe, which moves the focus.
    if target.brand == "codex" and codex_submit_activity not in {
        SUBMIT_ACTIVITY_ACTIVE,
        SUBMIT_ACTIVITY_IDLE,
    }:
        raise CodexTurnStateUnknown(
            "Codex pane routing requires an independently derived submit "
            f"activity; got {codex_submit_activity!r}"
        )
    transport.observe_addressing = observe_addressing
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
    # Brand-keyed, and for Codex keyed on the *derived turn activity* rather than
    # on the reachability state: the latter is only "recently addressable".
    submit_byte = (
        codex_submit_byte(codex_submit_activity)
        if target.brand == "codex"
        else PANE_ENTER_BYTE
    )
    return DeliveryRoute(
        mode=ROUTE_PANE,
        cwd=target.project_path,
        transport=transport,
        pane_ref=pane_ref,
        pane_text=" ".join(envelope.splitlines()),
        submit_byte=submit_byte,
        paste_framed=target.brand in PASTE_FRAMED_BRANDS,
        submit_activity=codex_submit_activity,
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
    observe_addressing: bool = False,
    codex_submit_activity: str | None = None,
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
                target,
                envelope,
                transports=transports,
                preflight=preflight,
                observe_addressing=observe_addressing,
                codex_submit_activity=codex_submit_activity,
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


def mirror_warnings(*agents: AgentRecord) -> list[str]:
    """One loud line per mirrored leaf whose addressing copy has rotted.

    Said on the delivery path rather than fixed in place, because "the mirror is
    rotting" is the fact worth surfacing: a silent re-sync would leave the next
    reader believing a mirror's runtime can be trusted, which is how a stale
    `pane_ref` gets used to address whoever holds that pane now.
    """

    lines: list[str] = []
    for agent in agents:
        if agent.mirror is None or not agent.mirror_stale:
            continue
        lines.append(
            f"mirror-stale: {agent.name!r} is registered here as a cross-project "
            f"mirror and its own runtime copy disagrees with the authoritative leaf "
            f"on {', '.join(agent.mirror_stale)}. This delivery used the values "
            f"from {agent.mirror.runtime_path} (the home leaf, the only place this "
            f"agent's heartbeat writes); the copy at {agent.spec_path.parent}/"
            f"runtime.json is stale and is NOT used for addressing. Left as-is on "
            "purpose: re-syncing it silently would hide that mirrors rot."
        )
    return lines


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
    observe_addressing: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> DeliveryPlan:
    # By reference, not by bare name: a `--from` / `--to` carrying a project
    # qualifier is checked against the leaf it resolves to, so naming another
    # project's agent refuses instead of quietly using the local same-named one.
    sender = load_agent_by_reference(repo, sender_name)
    target = load_agent_by_reference(repo, target_name)
    if sender.brand not in SUPPORTED_BRANDS:
        raise RegistryError(f"unsupported sender brand: {sender.brand!r}")
    target_state = derive_effective_state(target)
    routed_target = target._replace(state=target_state["effective_state"])
    # Derived here, before build_route runs anything: build_route's pane branch
    # probes the pane (a focus command), so an unreadable turn state has to be
    # refused while the "zero pane commands" claim is still true.
    codex_submit_activity: str | None = None
    if (
        target.brand == "codex"
        and target.pane_ref is not None
        and target_state["effective_state"] in {"active", "idle"}
    ):
        codex_submit_activity = require_codex_submit_activity(target.session_file)
    envelope = build_envelope(
        sender,
        target,
        message,
        nonce=nonce,
        script_path=script_path,
        # The repo this process already resolved -- the second hop must not
        # re-derive it.
        repo=repo,
    )
    route = build_route(
        routed_target,
        envelope,
        transports=transports,
        allow_resume=allow_resume,
        preflight=preflight,
        observe_addressing=observe_addressing,
        codex_submit_activity=codex_submit_activity,
        which=which,
    )
    payload = {
        "protocol": PROTOCOL,
        "sender": sender.name,
        # The names as anybody outside these projects must read them. Kept beside
        # the bare ones rather than replacing them: the bare name is still the key
        # inside its own project, and conflating the two is the confusion here.
        "sender_qualified": qualified_name(sender),
        "sender_brand": sender.brand,
        "target": target.name,
        "target_qualified": qualified_name(target),
        "target_brand": target.brand,
        "target_session_id": target.session_id,
        "target_declared_state": target.state,
        "target_effective_state": target_state["effective_state"],
        # Reachability (above) and current turn activity (here) are separate
        # answers on purpose; None means "not applicable to this target/route".
        "target_submit_activity": codex_submit_activity,
        "target_state_diagnostic": target_state["diagnostic"],
        "target_session_file": str(target.session_file),
        # Where the addressing values above actually came from. None means "this
        # repo's own leaf"; a path means the target is registered here as a
        # cross-project mirror and the authority was read from its home leaf.
        "target_runtime_authority": (
            str(target.mirror.runtime_path) if target.mirror is not None else None
        ),
        "target_mirror_stale_fields": list(target.mirror_stale),
        "nonce": nonce,
        "delivery_marker": build_delivery_marker(sender, target, nonce),
        "cwd": str(route.cwd),
        "argv": route.argv if route.mode == ROUTE_RESUME else route.pane_argv(),
        "submit_argv": route.submit_argv(),
        "route_mode": route.mode,
        "pane_transport": route.transport.name if route.transport else None,
        "pane_paste_framed": route.paste_framed if route.mode == ROUTE_PANE else None,
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
        "warnings": list(route.warnings) + mirror_warnings(sender, target),
    }
    return DeliveryPlan(payload=payload, route=route)


def update_global_summary(
    index_path: Path,
    agent: AgentRecord,
    *,
    state: str,
) -> str:
    """Roll the leaf's summary up into the global index. Creates what is missing.

    Returns what it did: "updated", "created-summary", or "created-project".

    Why it creates rather than refuses: **a summary is derived from the leaf**, and
    the leaf is authoritative (section 2.3), so generating one needs no information
    the leaf does not already carry -- there is nothing to guess. Refusing instead
    meant that a session which had just self-registered correctly could never
    succeed at its first heartbeat: the leaf existed, the summary did not, and this
    function raised on exactly that state. That is not a guard against a mistake;
    it is a guard against the normal first-run path, i.e. it made the documented
    "self-register, then heartbeat" sequence impossible to complete.

    It also *is* the repair for one half of half-registered (direction B: leaf
    present, summary absent) -- the guide asks for the two to exist pairwise, and
    the only mechanism that can restore the pair is the writer of the leaf.

    Creation is recorded, never silent: a created entry carries `created_by` so an
    auditor can tell a rolled-up entry from one a human wrote. Silent creation
    would make a mis-derived project id look like it had always been there, which
    is the failure mode the path-derivation gate exists to prevent.
    """
    index = read_json(index_path)
    projects = index.get("projects")
    if not isinstance(projects, list):
        raise RegistryError(f"{index_path}: projects must be an array")

    project_entry: dict[str, Any] | None = None
    for candidate in projects:
        if isinstance(candidate, dict) and candidate.get("project_id") == agent.project_id:
            project_entry = candidate
            break

    outcome = "updated"
    if project_entry is None:
        # Every field is derived, none is guessed: the id is recomputed from the
        # realpath by the same rule the validator uses, and the path is the one
        # this leaf physically lives under.
        project_entry = {
            "project_id": agent.project_id,
            "path": str(agent.project_path),
            "name": agent.project_path.name,
            "created_by": "agenttui-rollup",
            "agents": [],
        }
        projects.append(project_entry)
        outcome = "created-project"

    agents = project_entry.get("agents")
    if not isinstance(agents, list):
        raise RegistryError(f"{index_path}: project agents must be an array")
    for summary in agents:
        if isinstance(summary, dict) and summary.get("name") == agent.name:
            summary["brand"] = agent.brand
            summary["state"] = state
            summary["session_id"] = agent.session_id
            atomic_write_json(index_path, index)
            return outcome

    agents.append(
        {
            "name": agent.name,
            "role": agent.role,
            "brand": agent.brand,
            "state": state,
            "session_id": agent.session_id,
            "lineage": agent.lineage,
            "created_by": "agenttui-rollup",
        }
    )
    atomic_write_json(index_path, index)
    return outcome if outcome == "created-project" else "created-summary"


def write_runtime_state(
    repo: Path,
    name: str,
    *,
    state: str,
    now: str,
    global_index: Path | None,
    confirm_session_exit: bool = False,
) -> dict[str, str]:
    """Write the leaf, then roll the summary up. Reports both halves separately."""
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
    if global_index is None:
        return {"leaf": "written", "summary": "not-requested"}

    # Two files cannot be written atomically together -- there is no single
    # os.replace that covers both. So this does NOT pretend to be atomic; it makes
    # the outcome *readable*, which is where the actual harm was.
    #
    # The harm was never "not atomic": it was that a leaf had already been written
    # and the caller was told `error`, with no way to tell "nothing happened" from
    # "half of it happened". A caller that reads that as "nothing happened" then
    # believes the heartbeat did not land, when it did.
    #
    # The leaf is written first on purpose: it is the authority (section 2.3), and
    # a leaf without its summary is a *named, detectable* state (half-registered
    # direction B) with a defined repair. The reverse -- a summary with no leaf --
    # is direction A, which points at an agent that may not exist. Given that one
    # of the two must land first, land the one whose failure mode is the diagnosable
    # one.
    #
    # Which failures are left, and who repairs them -- because "report it and
    # suggest a retry" would have been a *regression*: it replaces a loud error
    # with a quiet half-success, and **a loud wrong reading gets chased down while
    # a quiet half-success does not.**
    #
    # Once the roll-up creates what is missing, the "entry absent" class of failure
    # no longer exists -- so a *self-healing* path is not needed for it; it simply
    # cannot occur. What remains raises only on **structural damage** (the index's
    # arrays are not arrays) or on I/O (unreadable, unwritable, invalid JSON). None
    # of those improves by repeating the command. Telling the caller to retry would
    # send it into a loop that can never succeed, which is worse than saying
    # nothing.
    #
    # So the remaining failures are reported as **not self-repairing**, and pointed
    # at the mechanism that actually finds them: the registry consistency validator
    # reports leaf-without-summary as half-registered direction B, and it has an
    # answer-moment (periodic maintenance, and before/after any bulk change). That
    # is a real executor. "Someone will read stderr" is not -- a heartbeat is
    # invoked automatically and nobody is watching its stderr.
    try:
        outcome = update_global_summary(global_index, agent, state=state)
    except (RegistryError, OSError, json.JSONDecodeError) as exc:
        return {
            "leaf": "written",
            "summary": "failed",
            "summary_self_repairing": "no",
            "detail": str(exc),
            "recommended_action": (
                "do NOT just retry -- what remains here is structural or I/O damage "
                "to the global index and repeating the command cannot fix it. Repair "
                "the index, then re-run. Until then this leaf reads as "
                "half-registered direction B, which the registry consistency "
                "validator reports"
            ),
        }
    return {"leaf": "written", "summary": outcome}


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
    window_seconds: float = PANE_VERIFY_WINDOW_SECONDS,
    *,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> bool:
    """Poll the target transcript until the marker appears or the window ends.

    Exits on the first hit, so a wide window costs the success path nothing.
    Always checks at least once, even for a zero window. A zero poll interval
    degenerates to a busy poll bounded by the window; the clock seams exist so
    tests can bound both without real waiting.
    """
    deadline = monotonic() + max(0.0, window_seconds)
    delay = PANE_VERIFY_POLL_INITIAL_SECONDS
    while True:
        if transcript_contains_marker(path, marker, start_offset):
            return True
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleep(min(delay, PANE_VERIFY_POLL_MAX_SECONDS, remaining))
        delay = min(delay * 2, PANE_VERIFY_POLL_MAX_SECONDS)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AgentTUI registry lifecycle and cross-brand direct messaging"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help=(
            "repository containing .arborist/. REQUIRED when running through a "
            "global entry point (shim): a machine-wide copy cannot know which "
            "repository is calling it, and inferring would target the repository "
            "that hosts the script. Only an adopted copy at "
            ".trellis/scripts/ may omit it — there the inference is correct, and "
            "the inferred path is still validated (must contain .trellis/ or "
            ".git/) instead of reading or creating a registry somewhere else"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    send = subparsers.add_parser("send", help="direct-message a registered peer")
    send.add_argument("--from", dest="sender", required=True)
    send.add_argument("--to", dest="target", required=True)
    send.add_argument("--message", required=True)
    send.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help=(
            "seconds a single pane command may take. For the resume transport it "
            "bounds only how long delivery is OBSERVED: that runner carries the "
            "target's whole turn and is never terminated by this process"
        ),
    )
    send.add_argument(
        "--observation-log",
        type=Path,
        default=OBSERVATION_LOG_DEFAULT,
        help=(
            "append one focus-intrusion event per pane delivery here "
            "(events only, never rates; see the module docstring)"
        ),
    )
    send.add_argument(
        "--no-observation-log",
        dest="observation_log",
        action="store_const",
        const=None,
        help="do not record the focus-intrusion event for this delivery",
    )
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


def append_observation(record: dict[str, Any], log_path: Path | None) -> None:
    """Append one focus-intrusion event. Never allowed to fail a delivery.

    One line per event, appended: no read-modify-write, so concurrent senders
    cannot lose each other's records. Failures are reported and swallowed --
    losing a measurement must never cost a message.
    """
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        existed = log_path.exists()
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if not existed:
            os.chmod(log_path, 0o600)
    except OSError as exc:
        print(
            f"warning: could not record the focus-intrusion observation "
            f"({exc}); the delivery itself is unaffected",
            file=sys.stderr,
        )


PANE_OUTCOME_WARNINGS: dict[str, str] = {
    DELIVERY_COMPOSER_UNSUBMITTED: (
        "the envelope text was written to the pane, but the target's turn state "
        "became unreadable before a submit key could be chosen; NO key was sent, "
        "so the envelope is sitting unsubmitted in the composer — recover that "
        "existing text instead of rewriting the envelope"
    ),
    DELIVERY_WRITE_UNVERIFIED: (
        "the pane write command did not report back (timeout); it may still have "
        "typed part or all of the envelope, so this is neither delivery evidence "
        "nor proof of zero side effects — inspect the target, do not resend"
    ),
    DELIVERY_SUBMIT_COMMAND_UNVERIFIED: (
        "the envelope text was written but the submit-key command failed or did "
        "not report back; the envelope may be sitting unsubmitted in the target's "
        "input box, and a blind resend can duplicate it — inspect the target (and "
        "rebuild its pane_ref if the failure was an addressing error) first"
    ),
    DELIVERY_SUBMIT_UNVERIFIED: (
        "the pane transport reported no addressing error, but this envelope nonce "
        "was not found in the target transcript; command success is not delivery "
        "evidence, so the envelope may still be sitting in the input box — inspect "
        "the target or seek an explicit peer reply, and do not blindly resend"
    ),
    DELIVERY_QUEUED_FOR_NEXT_TURN: (
        "the enqueue key was executed while the target was mid-turn, so this "
        "envelope's nonce cannot appear until that turn ends; an early transcript "
        "miss is NOT non-delivery evidence — wait for the turn boundary, never "
        "resend the enqueue key"
    ),
}


def pane_result_payload(
    delivery: str,
    payload: dict[str, Any],
    transport: PaneTransport,
    *,
    submit_action: str,
    submit_activity: str | None,
    delivered: bool,
    sent: bool,
    submit_rejected: str | None = None,
) -> dict[str, Any]:
    """One structured pane outcome, named after the action that was executed."""
    recommended_action, verification_guidance = OUTCOME_GUIDANCE[delivery]
    return {
        "delivery": delivery,
        "route_mode": ROUTE_PANE,
        "pane_transport": transport.name,
        # Measured focus cost of *this* delivery (see INTRUSION_*), reported on
        # success too: the question is a rate, not an incident. Deliberately an
        # event, never a summary -- see OBSERVATION_LOG_DEFAULT for why a ratio
        # computed here would be systematically wrong.
        "addressing_intrusion": transport.addressing_intrusion(),
        "addressing_observation": transport.addressing_observation(),
        "target": payload["target"],
        "target_brand": payload["target_brand"],
        "target_effective_state": payload.get("target_effective_state"),
        "target_submit_activity": submit_activity,
        "submit_action": submit_action,
        "recommended_action": recommended_action,
        "verification_guidance": verification_guidance,
        "nonce": payload["nonce"],
        "evidence": "envelope-nonce-found" if delivered else "none",
        "sent": sent,
        "retry_safe": delivery in RETRY_SAFE_OUTCOMES,
        "transport_exit_status_trusted": False,
        "submit_rejected": submit_rejected,
        "acknowledged": False,
    }


def read_submit_ack(nonce: str, *, log_path: Path | None = None) -> dict[str, Any]:
    """Ask the receiver-side ack table about one nonce. Never raises.

    Three outcomes, deliberately distinct: `acked` (the receiver's hook fired),
    `unconfirmed` (looked, found nothing -- **not** "not submitted"), and
    `table-unreadable` (could not look at all, which must not be reported as
    having looked). The distinction is the whole point: "I could not check" and
    "I checked and it was absent" license different actions.

    A missing ack module is itself `table-unreadable`, not `unconfirmed`: the
    facility may simply not be adopted here, and that is not evidence about the
    target's behaviour.
    """
    module_path = Path(__file__).resolve().parent / ACK_MODULE_NAME
    if not module_path.is_file():
        return {
            "ack_status": ACK_STATUS_UNAVAILABLE,
            "ack_count": 0,
            "ack_detail": (
                f"{ACK_MODULE_NAME} is not installed next to this script, so the "
                "ack table could not be consulted; this says nothing about whether "
                "the target submitted"
            ),
        }
    try:
        spec = importlib.util.spec_from_file_location("_agenttui_ack", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        records = module.read_acks(nonce) if log_path is None else module.read_acks(
            nonce, log_path=log_path
        )
    except Exception as exc:  # a measurement must never fail a delivery
        return {
            "ack_status": ACK_STATUS_UNAVAILABLE,
            "ack_count": 0,
            "ack_detail": f"the ack table could not be read ({exc})",
        }
    if records:
        return {
            "ack_status": ACK_STATUS_ACKED,
            "ack_count": len(records),
            "ack_detail": (
                "the receiver's submit hook fired for this nonce, which is causal "
                "evidence that the envelope was submitted"
            ),
        }
    return {
        "ack_status": ACK_STATUS_UNCONFIRMED,
        "ack_count": 0,
        "ack_detail": (
            "no ack for this nonce. This means UNCONFIRMED, not not-submitted: the "
            "receiver's hook may be uninstalled or skipped, or its write may have "
            "failed"
        ),
    }


def send_via_pane(
    route: DeliveryRoute,
    payload: dict[str, Any],
    *,
    timeout: float | None,
    submit_delay: float | None,
    observation_log: Path | None = None,
) -> int:
    """Inject into a live pane, then judge delivery only by the rule 3 nonce.

    Exit status of the transport commands is never consulted as a success signal:
    a live session with a dead pane answers rc=0 with empty output, so a clean
    invocation proves nothing. Rejections are recognised from command *text*; the
    only positive evidence is the per-send nonce appearing in the transcript.

    Every exit from here is classified by the action that was actually executed
    (rule 4), because the correct caller behaviour differs per action: wait out a
    turn boundary, recover an unsubmitted composer, or inspect a command that
    never reported back. One shared "unverified" value made those indistinguishable.
    """
    transport = route.transport
    assert transport is not None and route.pane_ref is not None
    assert route.pane_text is not None and route.submit_byte is not None
    session_file = Path(payload["target_session_file"])
    boundary = transcript_size(session_file)
    target_is_codex = payload["target_brand"] == "codex"
    submit_activity = payload.get("target_submit_activity")
    ack_reading: dict[str, Any] = {}

    def report(
        delivery: str,
        *,
        submit_action: str,
        delivered: bool = False,
        sent: bool = True,
        submit_rejected: str | None = None,
        activity: str | None = None,
        status: int = 0,
    ) -> int:
        result = pane_result_payload(
            delivery,
            payload,
            transport,
            submit_action=submit_action,
            submit_activity=activity if activity is not None else submit_activity,
            delivered=delivered,
            sent=sent,
            submit_rejected=submit_rejected,
        )
        # Rule 8: report the receiver-side reading alongside the observer-side one.
        # Reported on every outcome, including success, because the value of the
        # pair is in their *combination* -- see the ack/nonce matrix in section 3.
        result.update(ack_reading)
        warning = PANE_OUTCOME_WARNINGS.get(delivery)
        if warning is not None:
            print(f"warning: {warning}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False))
        append_observation(
            {
                "observed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "nonce": payload["nonce"],
                "delivery": result["delivery"],
                "intrusion": transport.addressing_intrusion(),
                "target_pane": dict(route.pane_ref or {}),
                **transport.addressing_observation(),
            },
            observation_log,
        )
        return status

    try:
        injected = transport.write_chars(
            route.pane_ref,
            route.pane_text,
            paste_framed=route.paste_framed,
            cwd=route.cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # The write command never came back, so it is unknown whether any bytes
        # reached the composer. Not "nothing was sent": a command that failed to
        # report does not prove the absence of side effects.
        return report(
            DELIVERY_WRITE_UNVERIFIED,
            submit_action="none-write-command-unverified",
            status=EXIT_UNCERTAIN_DELIVERY,
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
            CODEX_PANE_SUBMIT_DELAY_SECONDS if target_is_codex else 0.0
        )
    if submit_delay:
        time.sleep(submit_delay)

    submit_byte = route.submit_byte
    if target_is_codex:
        # Refresh immediately before the key: the turn may have ended during the
        # settle delay, and then the planned Tab would land in an idle composer
        # and enqueue nothing. Unknown here is NOT a licence to guess — the text
        # is already in the composer, so the honest outcome is to send no key.
        submit_activity = derive_codex_submit_activity(session_file)
        if submit_activity is None:
            return report(
                DELIVERY_COMPOSER_UNSUBMITTED,
                submit_action="none-post-write-unknown",
                status=EXIT_UNCERTAIN_DELIVERY,
            )
        submit_byte = codex_submit_byte(submit_activity)

    # Rule 2: an enqueue key must never be resent (it would enqueue a duplicate
    # envelope). Only a plain submit may be retried. Derived before verification
    # because it also selects the window: a queued envelope cannot surface until
    # the turn ends, so waiting out the full window would be pure idling.
    enqueued_for_next_turn = (
        target_is_codex and submit_activity == SUBMIT_ACTIVITY_ACTIVE
    )
    submit_action = "tab-queue" if enqueued_for_next_turn else "enter-submit"
    verify_window = (
        PANE_VERIFY_QUEUED_WINDOW_SECONDS
        if enqueued_for_next_turn
        else PANE_VERIFY_WINDOW_SECONDS
    )

    try:
        submitted = transport.send_key(
            route.pane_ref, submit_byte, cwd=route.cwd, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return report(
            DELIVERY_SUBMIT_COMMAND_UNVERIFIED,
            submit_action=submit_action,
            status=EXIT_UNCERTAIN_DELIVERY,
        )
    echo_transport_output(submitted)
    if submitted.rejected:
        # The envelope text already went out, so this is not "nothing was sent";
        # it is a send whose delivery cannot be proven.
        return report(
            DELIVERY_SUBMIT_COMMAND_UNVERIFIED,
            submit_action=submit_action,
            submit_rejected=submitted.detail,
            status=EXIT_UNCERTAIN_DELIVERY,
        )

    delivered = wait_for_transcript_marker(
        session_file, payload["delivery_marker"], boundary, verify_window
    )
    ack_reading = read_submit_ack(payload["nonce"])
    if delivered:
        return report(DELIVERY_DELIVERED, submit_action=submit_action, delivered=True)
    if enqueued_for_next_turn:
        return report(DELIVERY_QUEUED_FOR_NEXT_TURN, submit_action=submit_action)

    # The one combination the transcript alone cannot read: the receiver's hook
    # fired (so the envelope *was* submitted) but the record has not surfaced yet.
    # Pressing submit again here would duplicate an accepted message -- which is
    # precisely what the old code did, because it could not tell this apart from
    # "never submitted". This is the whole reason the ack exists.
    if ack_reading["ack_status"] == ACK_STATUS_ACKED:
        return report(DELIVERY_SUBMIT_UNVERIFIED, submit_action=submit_action)

    time.sleep(max(submit_delay, PANE_VERIFY_POLL_INITIAL_SECONDS))
    if target_is_codex:
        # A second Enter is only safe while the target is still idle: if the turn
        # has started, Enter would steer it, and unknown could be either.
        submit_activity = derive_codex_submit_activity(session_file)
        if submit_activity != SUBMIT_ACTIVITY_IDLE:
            return report(DELIVERY_SUBMIT_UNVERIFIED, submit_action=submit_action)
    try:
        submitted = transport.send_key(
            route.pane_ref, submit_byte, cwd=route.cwd, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return report(
            DELIVERY_SUBMIT_COMMAND_UNVERIFIED,
            submit_action=submit_action,
            status=EXIT_UNCERTAIN_DELIVERY,
        )
    echo_transport_output(submitted)
    if submitted.rejected:
        return report(
            DELIVERY_SUBMIT_COMMAND_UNVERIFIED,
            submit_action=submit_action,
            submit_rejected=submitted.detail,
            status=EXIT_UNCERTAIN_DELIVERY,
        )
    delivered = wait_for_transcript_marker(
        session_file, payload["delivery_marker"], boundary, verify_window
    )
    # Re-read: an ack may have landed during the retry, and reporting the stale
    # reading would understate what is known.
    ack_reading = read_submit_ack(payload["nonce"])
    if delivered:
        return report(DELIVERY_DELIVERED, submit_action=submit_action, delivered=True)
    return report(DELIVERY_SUBMIT_UNVERIFIED, submit_action=submit_action)


def observe_detached_resume(
    process: subprocess.Popen,
    path: Path,
    marker: str,
    start_offset: int,
    window_seconds: float,
    *,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> tuple[bool, int | None]:
    """Watch for the nonce without ever owning the resumed turn's lifetime.

    Returns ``(delivered, runner_returncode)`` where a ``None`` return code means
    the runner is still working. Never terminates the runner: the window bounds
    only this process's *observation*.
    """
    deadline = monotonic() + max(0.0, window_seconds)
    delay = PANE_VERIFY_POLL_INITIAL_SECONDS
    while True:
        if transcript_contains_marker(path, marker, start_offset):
            return True, process.poll()
        returncode = process.poll()
        if returncode is not None:
            # The transcript append can race the process exit, so take one final
            # message-specific reading before calling it unverified.
            return (
                transcript_contains_marker(path, marker, start_offset),
                returncode,
            )
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False, None
        sleep(min(delay, PANE_VERIFY_POLL_MAX_SECONDS, remaining))
        delay = min(delay * 2, PANE_VERIFY_POLL_MAX_SECONDS)


def send_via_resume(
    route: DeliveryRoute,
    payload: dict[str, Any],
    *,
    timeout: float | None,
) -> int:
    """Start the resume transport detached, then observe without owning it.

    The resume process is not a bounded "write this message" command: it carries
    the target's entire turn. Running it under this process's timeout therefore
    made the sender's patience the target's deadline — a sender-side timeout
    SIGKILLed the runner and aborted a turn that was working correctly, possibly
    after it had already written files or called out to other systems. So the
    runner is started in its own process session and is never terminated here;
    ``timeout`` bounds only how long this process watches for the nonce.

    Its output is captured to a private file rather than to a pipe. A pipe would
    reintroduce the same class of bug in a quieter form: an abandoned runner whose
    pipe buffer filled would block *inside the target's turn*. Discarding the
    output instead would silently drop the target's reply, which for the
    claude-code shape is the only place that reply ever appears.
    """
    assert route.argv is not None
    session_file = Path(payload["target_session_file"])
    if session_file.is_file() and session_file.stat().st_size >= LARGE_TRANSCRIPT_BYTES:
        print(
            f"warning: target transcript is {session_file.stat().st_size:,} bytes; "
            "resume may be expensive because it loads the target context",
            file=sys.stderr,
        )
    boundary = transcript_size(session_file)
    handle, capture_name = tempfile.mkstemp(prefix="agenttui-resume-", suffix=".log")
    capture_path = Path(capture_name)
    try:
        with os.fdopen(handle, "wb") as capture:
            process = subprocess.Popen(
                route.argv,
                cwd=route.cwd,
                stdin=subprocess.DEVNULL,
                stdout=capture,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        capture_path.unlink(missing_ok=True)
        raise RegistryError(f"failed to start the resume transport: {exc}") from exc

    window = RESUME_VERIFY_WINDOW_SECONDS
    if timeout is not None:
        window = min(window, timeout)
    delivered, runner_returncode = observe_detached_resume(
        process, session_file, payload["delivery_marker"], boundary, window
    )

    still_running = runner_returncode is None
    if delivered:
        delivery = DELIVERY_DELIVERED
    elif still_running:
        delivery = DELIVERY_RESUME_STARTED_UNVERIFIED
    else:
        delivery = DELIVERY_RESUME_EXITED_UNVERIFIED
    recommended_action, verification_guidance = OUTCOME_GUIDANCE[delivery]

    captured = ""
    if not still_running:
        # Safe to read and clean up only once the writer is gone.
        captured = capture_path.read_text(encoding="utf-8", errors="replace")
        capture_path.unlink(missing_ok=True)
        if captured:
            print(captured, end="" if captured.endswith("\n") else "\n")
    if still_running:
        print(
            "warning: the resume runner is still working and this envelope nonce "
            "has not appeared yet; it was NOT terminated, so do not resend — its "
            f"output is being written to {capture_path}",
            file=sys.stderr,
        )
    elif not delivered:
        print(
            "warning: the resume runner exited before this envelope nonce "
            "appeared; a runner exit does not prove the target had no side "
            "effects, so inspect the target instead of blindly resending",
            file=sys.stderr,
        )
    print(
        json.dumps(
            {
                "delivery": delivery,
                "route_mode": ROUTE_RESUME,
                "target": payload["target"],
                "target_brand": payload["target_brand"],
                "target_effective_state": payload.get("target_effective_state"),
                "submit_action": "detached-resume",
                "recommended_action": recommended_action,
                "verification_guidance": verification_guidance,
                "nonce": payload["nonce"],
                "evidence": "envelope-nonce-found" if delivered else "none",
                "sent": True,
                "retry_safe": delivery in RETRY_SAFE_OUTCOMES,
                "execution_lifecycle": "detached-from-sender",
                "runner_pid": process.pid,
                "runner_state": "running" if still_running else "exited",
                "runner_returncode": runner_returncode,
                "runner_output_path": str(capture_path) if still_running else None,
                # Delivery is transport entry. Whether the target's turn ran to
                # completion is a different question, and this process no longer
                # owns the turn, so it must not be implied either way.
                "task_completion": "unverified",
                "target_turn_outcome": "not-observed",
                "acknowledged": False,
            },
            ensure_ascii=False,
        )
    )
    if delivered or still_running:
        return 0
    return EXIT_UNCERTAIN_DELIVERY


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
        # Extra readings only when they will actually be recorded.
        observe_addressing=(
            not args.dry_run and getattr(args, "observation_log", None) is not None
        ),
    )
    payload, route = plan
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # The payload's list, not the route's: it is the route's warnings plus the
    # mirror-staleness lines, which have to be as loud as the route ones (a stale
    # mirror is a mis-delivery that already happened once). Identical output for
    # every non-mirror send, where the two lists are equal.
    for warning in payload["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    if route.mode == ROUTE_PANE:
        return send_via_pane(
            route,
            payload,
            timeout=args.timeout,
            submit_delay=args.pane_submit_delay,
            observation_log=getattr(args, "observation_log", None),
        )
    return send_via_resume(route, payload, timeout=args.timeout)


def command_state(args: argparse.Namespace, repo: Path, state: str) -> int:
    agent = load_agent(repo, args.name)
    require_current_session(agent, args.session_id)
    written = write_runtime_state(
        repo,
        args.name,
        state=state,
        now=default_now(),
        global_index=args.global_index,
        confirm_session_exit=getattr(args, "confirm_session_exit", False),
    )
    print(
        json.dumps(
            {
                "name": args.name,
                "state": state,
                "session_id": agent.session_id,
                # Both halves, always -- including on success, because "the leaf
                # landed" and "the summary landed" are separate facts and a caller
                # that cannot see them separately cannot act on a partial result.
                **written,
            },
            ensure_ascii=False,
        )
    )
    if written.get("summary") == "failed":
        # Non-zero, but a *different* non-zero meaning from "nothing happened":
        # the payload says the leaf is already correct and the retry is safe.
        print(
            "warning: the leaf was written but the global summary roll-up failed. "
            "The leaf is authoritative and already correct, so nothing was lost -- "
            "but this is NOT self-repairing: the remaining failure classes are "
            "structural or I/O damage to the global index, which a retry cannot "
            "fix. Repair the index, then re-run. Meanwhile this leaf reads as "
            "half-registered direction B and the registry consistency validator "
            "will report it -- that validator, not this stderr line, is the "
            "executor here (a heartbeat runs automatically and nobody watches its "
            "stderr)",
            file=sys.stderr,
        )
        return EXIT_UNCERTAIN_DELIVERY
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
        # Before any subcommand runs, i.e. before any repository state is read.
        repo = resolve_caller_repo_root(args.repo, script_path=Path(__file__))
        if args.command == "send":
            return command_send(args, repo)
        if args.command == "heartbeat":
            return command_state(args, repo, "active")
        if args.command == "stop":
            return command_state(args, repo, "stopped")
        if args.command == "status":
            return command_status(args, repo)
    except RepoRootUnspecified as exc:
        # Its own exit code, and stderr only: there is no delivery outcome to
        # report because no repository was ever opened.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REPO_ROOT_UNSPECIFIED
    except CodexTurnStateUnknown as exc:
        # Structured, non-zero, and mechanically zero pane commands: this refusal
        # is raised while planning, before the existence probe (itself a pane
        # command) can run, which is what makes retry_safe=true true here.
        recommended_action, verification_guidance = OUTCOME_GUIDANCE[
            DELIVERY_PRE_INJECTION_REJECTED
        ]
        print(
            json.dumps(
                {
                    "delivery": DELIVERY_PRE_INJECTION_REJECTED,
                    "route_mode": ROUTE_PANE,
                    "detail": str(exc),
                    "submit_action": "none-pre-injection",
                    "recommended_action": recommended_action,
                    "verification_guidance": verification_guidance,
                    "sent": False,
                    "retry_safe": DELIVERY_PRE_INJECTION_REJECTED
                    in RETRY_SAFE_OUTCOMES,
                    "evidence": "none",
                    "acknowledged": False,
                },
                ensure_ascii=False,
            )
        )
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PRE_INJECTION_REJECTED
    except NoOperationalRoute as exc:
        # Structured, non-zero, and never conflated with a *-unverified outcome.
        print(json.dumps(exc.payload(), ensure_ascii=False), file=sys.stdout)
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NO_OPERATIONAL_ROUTE
    except RegistryError as exc:
        parser.error(str(exc))
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
