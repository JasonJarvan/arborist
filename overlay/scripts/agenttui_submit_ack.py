#!/usr/bin/env python3
"""Receiver-side submit-ack: causal evidence that a direct-injected envelope
was actually submitted by the target session.

WHY THIS EXISTS (the whole design follows from it)
--------------------------------------------------
The delivery contract's only delivery evidence so far is the sender walking the
target's transcript looking for the per-send nonce (agenttui-registry.md §3
rule 3). That is *bystander* evidence, and it has two measured limits:

  * It lags the target CLI's own flush to disk. A too-small verification window
    reads an already-delivered envelope as unverified, and that false negative
    has already caused a duplicate submit (registry guide, failure mode 4).
  * It cannot tell "the text is piled up in the composer and was never
    submitted" apart from "it was submitted but has not been flushed yet".
    Those two need opposite handling, and the first one is the pain a human
    actually reports.

The receiving CLI's "the user submitted a prompt" hook is *causal*: it fires
only when a prompt is really submitted. Text sitting in a composer never fires
it. So an ack record is positive proof of submission, and its absence is a
readable-but-weak negative -- see the fail-safe direction below.

FAIL-SAFE DIRECTION (hard rule, encoded in this module's exit codes)
--------------------------------------------------------------------
A missing ack means UNCONFIRMED, never "not submitted". The hook may not be
installed at all; a brand's init step silently skips hook installation when the
host settings file is tracked by the product repo (see ADOPT.md); an ack write
may have failed. Asserting "not submitted" from an absent record would trigger a
capability-ladder downgrade and re-deliver a message the target already has --
exactly the duplicate delivery rule 2 exists to prevent. Hence this module never
emits a "not submitted" verdict: the only values are `acked` and `unconfirmed`.

TABLE SHAPE
-----------
Append-only JSONL, one record per line, global (not per project): panes and
agents cross project boundaries, so "was this nonce submitted" is a machine-wide
fact. Append-only rather than read-modify-write because several ATUIs write
concurrently and a read-modify-write loses records. Same shape and same
permission handling as the focus-intrusion event log in `agenttui.py`.

The record carries only what the hook can itself prove. Never the message body:
that is the receiver's conversation content (privacy) and would make the table
grow without bound (size).

WRITING MUST NEVER FAIL THE HOOK
--------------------------------
This runs inside a submit hook. A non-zero exit there blocks a real person's
prompt. Every failure path in `record` is therefore caught and degraded to a
stderr warning with exit 0, and nothing is ever written to stdout (stdout of a
submit hook is injected into the target's context on some brands).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


PROTOCOL = "ARBORIST-DIRECT:v1"

# Schema version of one ack record. Bumped only for incompatible field changes;
# readers must tolerate unknown versions by skipping, never by guessing.
ACK_RECORD_VERSION = 1

ARBORIST_HOME_ENV = "ARBORIST_HOME"


def arborist_home() -> Path:
    """The machine-level Arborist root: `$ARBORIST_HOME`, else `~/.arborist`.

    Unset **and** empty both resolve to `~/.arborist` (an empty string is how a
    shell spells "not configured"; treating it as a root would resolve against the
    process cwd). Read once, at import, so a caller cannot end up with a half-moved
    set of derived paths. Mirrors the resolver in `agenttui.py`; a test pins both to
    the same answers.
    """

    override = os.environ.get(ARBORIST_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".arborist"


# Global on purpose -- see the module docstring ("TABLE SHAPE"). Sits next to the
# focus-intrusion log so the runtime surface stays in one place.
ACK_LOG_DEFAULT = arborist_home() / "submit-acks.jsonl"

# Same nonce alphabet as the sender's envelope builder. Kept strict so a stray
# word in the submitted text cannot be read as a nonce.
NONCE_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")

_PROTOCOL_TOKEN = re.compile(re.escape(f"[{PROTOCOL}]"))
_MARKER_FIELD = re.compile(r"^\s*([a-z_]+)\s*=\s*(\S.*?)\s*$")
# Same fields when something along the way flattened the envelope onto one line.
# Not hypothetical: an envelope is written into a composer and then handed to a
# hook, and neither the composer's newline handling nor a brand's hook payload
# normalisation is under our control. If only the multi-line form parsed, a
# flattened envelope would produce **no ack at all** -- and the failure would be
# silent, i.e. indistinguishable from "the target never submitted", which is the
# exact confusion this whole facility exists to remove. So the flat form is
# parsed too, and both forms are pinned by tests.
_INLINE_FIELD = re.compile(r"\b([a-z_]+)=(\S+)")

# Envelope header fields worth keeping: they are what the hook can prove it saw,
# and they let a reader tell "the right envelope" from "some other envelope that
# happened to carry a nonce". Deliberately excludes anything from the body.
PROVABLE_HEADER_FIELDS = ("from", "from_brand", "to", "provenance")

# The envelope puts a blank line and a `message:` line between the header and the
# body. Scanning stops there so no body text is ever parsed as a header field.
_HEADER_TERMINATORS = ("message:",)

# Payload keys that different hosts use for the submitted prompt text. Missing
# key => no ack (unconfirmed), never a guess.
PROMPT_KEYS = ("prompt", "user_prompt", "userPrompt", "message", "text", "input")
SESSION_KEYS = ("session_id", "sessionId", "sessionID")
CWD_KEYS = ("cwd", "workspace_root", "workspaceRoot", "project_dir")

ACK_STATUS_ACKED = "acked"
ACK_STATUS_UNCONFIRMED = "unconfirmed"

# Exit codes for `lookup`. `record` is excluded from all of these on purpose: it
# always exits 0 (see the module docstring). Bad CLI usage keeps argparse's own
# exit 2, which is why no EXIT_USAGE is defined here.
EXIT_ACKED = 0
EXIT_UNCONFIRMED = 1
EXIT_TABLE_UNREADABLE = 3


# --- envelope parsing ---------------------------------------------------------


def _lookup_string(payload: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def parse_envelope_headers(text: str) -> list[dict[str, str]]:
    """Every direct-injection envelope header found in a submitted prompt.

    Returns one dict per envelope carrying `nonce` plus whichever
    PROVABLE_HEADER_FIELDS were present. Envelopes without a well-formed nonce
    are dropped: the nonce is the join key with the sender's delivery result, so
    a header without one cannot be acked.

    A prompt can legitimately hold more than one envelope (two deliveries landing
    in the same composer before the human hits submit), so all of them are
    returned rather than the first.
    """
    if not isinstance(text, str) or not text:
        return []
    headers: list[dict[str, str]] = []
    for match in _PROTOCOL_TOKEN.finditer(text):
        fields: dict[str, str] = {}
        for line in text[match.end():].splitlines():
            stripped = line.strip()
            if not stripped:
                # The rest of the protocol-token line, plus the blank line the
                # envelope puts before its body. Blank lines only terminate the
                # header once at least one field has been seen.
                if fields:
                    break
                continue
            if stripped in _HEADER_TERMINATORS:
                break
            # A flattened envelope carries every field on one line, so a
            # single-field match whose value still contains `key=` is really
            # several fields glued together -- take the inline reading there.
            # Body text is cut off first, so a message can never contribute a
            # field.
            head = stripped.split("message:", 1)[0]
            inline = dict(_INLINE_FIELD.findall(head))
            if len(inline) > 1:
                for key, value in inline.items():
                    fields.setdefault(key, value)
                break
            field = _MARKER_FIELD.match(line)
            if field is None:
                break
            fields[field.group(1)] = field.group(2)
        nonce = fields.get("nonce")
        if nonce is None or not NONCE_PATTERN.fullmatch(nonce):
            continue
        header = {"nonce": nonce}
        for name in PROVABLE_HEADER_FIELDS:
            if name in fields:
                header[name] = fields[name]
        headers.append(header)
    return headers


# --- receiver identity (best effort; unknown is recorded as null) -------------


def _project_id_for(path: Path) -> str | None:
    """The registry's project_id, computed by the registry's own implementation.

    Deliberately not reimplemented here. Two implementations of a derived id is
    how the same repo ends up with two ids (agenttui-registry.md §2.3). If the
    validator is not next to this script, the field is recorded as null -- an
    unknown value, never a guessed one.
    """
    module_path = Path(__file__).resolve().parent / "validate_agenttui_registry.py"
    if not module_path.is_file():
        return None
    name = "_arborist_registry_validator"
    try:
        spec = importlib.util.spec_from_file_location(name, module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        # Registered before exec on purpose: a module executed while absent from
        # sys.modules cannot resolve its own name, and the dataclasses in the
        # validator fail with an unrelated-looking AttributeError when it does.
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return str(module.project_id_for(path))
    except Exception:
        sys.modules.pop(name, None)
        return None


def find_repo_root(start: Path) -> Path | None:
    """Nearest ancestor that really looks like a project repo.

    Same judgement as the delivery preflight's path-derivation half: a derived
    root is only usable if it contains `.trellis/` or `.git/`. Nothing is ever
    created here -- this module only reads.
    """
    try:
        current = start.expanduser().resolve()
    except OSError:
        return None
    for candidate in (current, *current.parents):
        if (candidate / ".trellis").is_dir() or (candidate / ".git").exists():
            return candidate
    return None


def resolve_receiver_agent(repo_root: Path | None, session_id: str | None) -> str | None:
    """Registry leaf name of the session that submitted, matched by session_id.

    Read-only scan of `<repo>/.arborist/agents/*/runtime.json`. Returns None when
    the session is not registered -- an unregistered receiver still produces a
    usable ack, because the nonce alone is the join key.
    """
    if repo_root is None or not session_id:
        return None
    agents_dir = repo_root / ".arborist" / "agents"
    if not agents_dir.is_dir():
        return None
    try:
        entries = sorted(agents_dir.iterdir())
    except OSError:
        return None
    for entry in entries:
        runtime = entry / "runtime.json"
        if not runtime.is_file():
            continue
        try:
            data = json.loads(runtime.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("session_id") == session_id:
            return entry.name
    return None


# --- record construction and appending ----------------------------------------


def build_ack_records(
    headers: Sequence[dict[str, str]],
    *,
    receiver_brand: str | None,
    receiver_agent: str | None,
    receiver_project_path: str | None,
    receiver_project_id: str | None,
    receiver_session_id: str | None,
    hook_event: str | None,
    acked_at: str | None = None,
) -> list[dict[str, Any]]:
    """One record per envelope header. Body content is structurally absent.

    Field-by-field rationale is in the spec section (agenttui-registry.md §3,
    "receiver-side submit-ack"). Unknown values are recorded as null rather than
    omitted, so a reader can tell "the hook could not prove this" from "an older
    writer did not have the field".
    """
    timestamp = acked_at or datetime.now(timezone.utc).astimezone().isoformat()
    records: list[dict[str, Any]] = []
    for header in headers:
        record: dict[str, Any] = {
            "ack_version": ACK_RECORD_VERSION,
            "nonce": header["nonce"],
            "acked_at": timestamp,
            "protocol": PROTOCOL,
            "receiver_brand": receiver_brand,
            "receiver_agent": receiver_agent,
            "receiver_project_path": receiver_project_path,
            "receiver_project_id": receiver_project_id,
            "receiver_session_id": receiver_session_id,
            "hook_event": hook_event,
            "envelope_header": {
                name: header[name] for name in PROVABLE_HEADER_FIELDS if name in header
            },
        }
        records.append(record)
    return records


def append_ack_records(
    records: Sequence[dict[str, Any]],
    log_path: Path | None = None,
) -> tuple[int, str | None]:
    """Append records, one JSON object per line. Returns (written, warning).

    Never raises: the caller is a submit hook, and losing an ack must never cost
    a real person their prompt. One `write` per record on a file opened in append
    mode, so concurrent writers cannot interleave or lose each other's lines.

    Permissions: 0600 is applied only when this call creates the file. An
    existing mode is left exactly as found -- tightening someone else's runtime
    file is a separate decision, not a side effect of writing to it.
    """
    if not records:
        return 0, None
    path = ACK_LOG_DEFAULT if log_path is None else Path(log_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if not existed:
            os.chmod(path, 0o600)
        return len(records), None
    except Exception as exc:  # noqa: BLE001 -- see docstring: never raise here
        return 0, (
            f"warning: could not record the submit ack ({exc}); the prompt "
            f"itself is unaffected, but senders will read this delivery as "
            f"unconfirmed"
        )


def record_submit_ack(
    payload: dict[str, Any],
    *,
    receiver_brand: str | None = None,
    log_path: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Hook entry point: ack every envelope in this submitted prompt.

    Returns (records written, warnings). Never raises, never writes to stdout.
    Callers embedded in an existing hook must ignore the return value and keep
    going -- see the paste-in snippets under `overlay/hook-templates/submit-ack/`.
    """
    warnings: list[str] = []
    try:
        if not isinstance(payload, dict):
            return [], warnings
        prompt = _lookup_string(payload, PROMPT_KEYS)
        if prompt is None:
            return [], warnings
        headers = parse_envelope_headers(prompt)
        if not headers:
            return [], warnings
        session_id = _lookup_string(payload, SESSION_KEYS)
        cwd = _lookup_string(payload, CWD_KEYS) or os.getcwd()
        repo_root = find_repo_root(Path(cwd))
        records = build_ack_records(
            headers,
            receiver_brand=receiver_brand,
            receiver_agent=resolve_receiver_agent(repo_root, session_id),
            receiver_project_path=str(repo_root) if repo_root else None,
            receiver_project_id=_project_id_for(repo_root) if repo_root else None,
            receiver_session_id=session_id,
            hook_event=_lookup_string(payload, ("hook_event_name", "hookEventName")),
        )
        written, warning = append_ack_records(records, log_path)
        if warning:
            warnings.append(warning)
        return (records if written else []), warnings
    except Exception as exc:  # noqa: BLE001 -- a submit hook must not fail
        warnings.append(
            f"warning: submit-ack recording raised unexpectedly ({exc}); "
            f"the prompt itself is unaffected"
        )
        return [], warnings


# --- reading (sender side) ----------------------------------------------------


class AckTableUnreadable(RuntimeError):
    """The table could not be read at all -- which is UNCONFIRMED, not absent."""


def read_acks(nonce: str, log_path: Path | None = None) -> list[dict[str, Any]]:
    """Every ack recorded for one nonce, oldest line first.

    An empty list means UNCONFIRMED, never "not submitted" (module docstring).
    Malformed lines are skipped rather than fatal: a partially corrupt table must
    still surrender the records it does hold. A table that cannot be opened at
    all raises AckTableUnreadable, so the caller cannot mistake "I could not
    look" for "I looked and it was not there". A missing file is not an error --
    it is the ordinary state before the first ack.
    """
    path = ACK_LOG_DEFAULT if log_path is None else Path(log_path)
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AckTableUnreadable(str(exc)) from exc
    matches: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("nonce") == nonce:
            matches.append(record)
    return matches


def lookup_ack(nonce: str, log_path: Path | None = None) -> dict[str, Any]:
    """Structured ack reading for one nonce.

    `ack_status` is only ever `acked` or `unconfirmed`. There is deliberately no
    "not submitted" value for the sender to act on: see the module docstring.
    """
    try:
        matches = read_acks(nonce, log_path)
    except AckTableUnreadable as exc:
        return {
            "nonce": nonce,
            "ack_status": ACK_STATUS_UNCONFIRMED,
            "ack_count": 0,
            "acks": [],
            "table_readable": False,
            "detail": str(exc),
            "reading_guidance": (
                "the ack table could not be read, so this says nothing about "
                "whether the target submitted; treat as unconfirmed and do not "
                "downgrade the delivery ladder on it"
            ),
        }
    if matches:
        return {
            "nonce": nonce,
            "ack_status": ACK_STATUS_ACKED,
            "ack_count": len(matches),
            "acks": matches,
            "table_readable": True,
            "reading_guidance": (
                "the receiving CLI's submit hook fired for this nonce, which is "
                "causal proof that the envelope was submitted; a transcript that "
                "does not yet show the nonce means not-yet-flushed, NOT "
                "not-delivered -- do not resend"
            ),
        }
    return {
        "nonce": nonce,
        "ack_status": ACK_STATUS_UNCONFIRMED,
        "ack_count": 0,
        "acks": [],
        "table_readable": True,
        "reading_guidance": (
            "no ack for this nonce, which means unconfirmed and NOT "
            "not-submitted: the receiver's hook may be uninstalled, skipped at "
            "init time, or its write may have failed; an absent ack must not be "
            "read as evidence of non-delivery"
        ),
    }


# --- CLI ---------------------------------------------------------------------


def _load_hook_payload(stream: Any) -> dict[str, Any]:
    """Read a hook payload from stdin, degrading to {} on anything unexpected."""
    try:
        raw = stream.read()
    except Exception:  # noqa: BLE001 -- a submit hook must not fail
        return {}
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttui_submit_ack.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Receiver-side submit-ack handshake for cross-ATUI direct injection.\n"
            "`record` runs inside a submit hook and always exits 0.\n"
            "`lookup` is for the sending side."
        ),
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help=f"ack table path (default: {ACK_LOG_DEFAULT})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser(
        "record",
        help="read a submit-hook payload on stdin and append an ack per envelope",
        description=(
            "Appends one ack per direct-injection envelope found in the submitted "
            "prompt. ALWAYS exits 0 and ALWAYS writes an empty stdout: a non-zero "
            "exit here would block a real person's prompt, and stdout is injected "
            "into the session's context on some brands."
        ),
    )
    record.add_argument(
        "--brand",
        default=None,
        help="actual runtime brand of THIS session (e.g. the receiving CLI)",
    )
    record.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the stderr warning when an ack could not be written",
    )

    lookup = sub.add_parser(
        "lookup",
        help="report whether a nonce was acked by its receiver",
        description=(
            "Exit 0 = acked (causal proof of submission); 1 = unconfirmed (NOT "
            "proof of non-submission); 3 = the table could not be read (also "
            "unconfirmed). Never reports 'not submitted'."
        ),
    )
    lookup.add_argument("--nonce", required=True, help="the per-send nonce")

    sub.add_parser(
        "print-path",
        help="print the ack table path this invocation would use",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "print-path":
        print(ACK_LOG_DEFAULT if args.log is None else args.log)
        return EXIT_ACKED

    if args.command == "record":
        payload = _load_hook_payload(sys.stdin)
        _records, warnings = record_submit_ack(
            payload, receiver_brand=args.brand, log_path=args.log
        )
        if not args.quiet:
            for warning in warnings:
                print(warning, file=sys.stderr)
        # Unconditional 0, and nothing on stdout. See the module docstring.
        return EXIT_ACKED

    reading = lookup_ack(args.nonce, args.log)
    print(json.dumps(reading, ensure_ascii=False, indent=2))
    if reading["ack_status"] == ACK_STATUS_ACKED:
        return EXIT_ACKED
    if not reading["table_readable"]:
        return EXIT_TABLE_UNREADABLE
    return EXIT_UNCONFIRMED


if __name__ == "__main__":
    sys.exit(main())
