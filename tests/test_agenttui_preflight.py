"""Delivery preflight contract tests for the operational adapter.

Covers agenttui-registry.md §3 rules 5/6 plus the "delivery preflight" contract:
capability-based routing (no hardcoded multiplexer), pane existence preflight
judged by stdout text, the worst case where a transport command cannot testify
against itself (rc=0 + empty stdout), no-operational-route as a value distinct
from queued-unverified, and the path-derivation fail-closed gate.

Every transport is faked at the seam: no real multiplexer, no real repository,
no real session is touched.
"""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import contextlib
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


def load_script_module(relative_path: str, module_name: str):
    script_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None, script_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


AGENTTUI = load_script_module("overlay/scripts/agenttui.py", "agenttui_under_test")

# No test may append to the developer's real observation log. Repointed once for
# the whole module so that a future test invoking `send` cannot leak into $HOME.
_OBSERVATION_SANDBOX = TemporaryDirectory()
AGENTTUI.OBSERVATION_LOG_DEFAULT = (
    Path(_OBSERVATION_SANDBOX.name) / "focus-intrusion.jsonl"
)
CAPACITY = load_script_module(
    "overlay/scripts/arborist_brand_capacity.py", "capacity_under_test"
)


# Placeholders only — never observed values.
SENDER = "sender-one"
TARGET = "target-two"
FAKE_MUX = "fake-mux"
PANE_SESSION = "placeholder-session"
PANE_ID = "placeholder-pane"
NONCE = "test-nonce-0002"
MESSAGE = "decision: proceed with option A"


class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    """Fake command runner: records argv and replays scripted outcomes."""

    def __init__(self, outcomes: list[FakeCompleted] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._outcomes = list(outcomes or [])

    def __call__(self, argv, *, cwd=None, timeout=None):
        self.calls.append(list(argv))
        if self._outcomes:
            return self._outcomes.pop(0)
        return FakeCompleted()

    def actions(self) -> list[str]:
        # zellij shape: [... "action", <verb>, ...]; verb is what we assert on.
        verbs = []
        for call in self.calls:
            verbs.append(call[call.index("action") + 1] if "action" in call else call[0])
        return verbs


class FakeTransport(AGENTTUI.PaneTransport):
    """A pane transport for an invented multiplexer, registered only in tests."""

    name = FAKE_MUX

    def __init__(
        self,
        *,
        available: bool = True,
        exists: bool = True,
        write_outcome: AGENTTUI.CommandOutcome | None = None,
        submit_outcome: AGENTTUI.CommandOutcome | None = None,
    ) -> None:
        self._available = available
        self._exists = exists
        self._write_outcome = write_outcome
        self._submit_outcome = submit_outcome
        self.exists_calls = 0
        self.writes: list[str] = []
        self.framed: list[bool] = []
        self.keys: list[str] = []
        # Raise instead of answering, to exercise the command-did-not-report paths.
        self.write_timeout = False
        self.submit_timeouts = 0

    def available(self) -> AGENTTUI.Capability:
        return AGENTTUI.Capability(self._available, "fake transport availability")

    def exists(self, pane_ref) -> AGENTTUI.Capability:
        self.exists_calls += 1
        return AGENTTUI.Capability(self._exists, "fake transport existence probe")

    def write_chars_argv(self, pane_ref, text, *, paste_framed=False):
        payload = self.frame_paste(text) if paste_framed else text
        return ["fake-mux-cli", "write", pane_ref["pane_id"], payload]

    def send_key_argv(self, pane_ref, key_byte):
        return ["fake-mux-cli", "key", pane_ref["pane_id"], key_byte]

    def write_chars(self, pane_ref, text, *, paste_framed=False, cwd=None, timeout=None):
        self.writes.append(text)
        self.framed.append(paste_framed)
        argv = self.write_chars_argv(pane_ref, text, paste_framed=paste_framed)
        if self.write_timeout:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout or 0)
        return self._write_outcome or AGENTTUI.CommandOutcome(
            argv=argv, returncode=0, stdout="", stderr="", rejected=False, detail=""
        )

    def send_key(self, pane_ref, key_byte, *, cwd=None, timeout=None):
        self.keys.append(key_byte)
        argv = self.send_key_argv(pane_ref, key_byte)
        if self.submit_timeouts > 0:
            self.submit_timeouts -= 1
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout or 0)
        return self._submit_outcome or AGENTTUI.CommandOutcome(
            argv=argv, returncode=0, stdout="", stderr="", rejected=False, detail=""
        )


def make_record(
    *,
    name: str = TARGET,
    brand: str = "codex",
    state: str = "active",
    pane_ref: dict[str, str] | None = None,
    project_path: Path | None = None,
    session_file: Path | None = None,
) -> "AGENTTUI.AgentRecord":
    base = project_path or Path("/nonexistent-placeholder-repo")
    return AGENTTUI.AgentRecord(
        name=name,
        brand=brand,
        role="impler",
        project_path=base,
        project_id="placeholder-project",
        session_id="placeholder-session-id",
        session_file=session_file or (base / "placeholder-session-file"),
        state=state,
        last_seen=datetime.now().astimezone().isoformat(timespec="seconds"),
        pane_ref=pane_ref,
        spec_path=base / "spec.json",
        runtime_path=base / "runtime.json",
    )


def append_codex_boundary(session_file: Path, activity: str, *, terminated: bool = True) -> None:
    """Append the turn-boundary record that means `activity`, fixture-only.

    Shape only: the event names are contract constants, and no observed transcript
    content, session id, or path appears here.
    """
    event = (
        AGENTTUI.CODEX_TURN_STARTED_EVENT
        if activity == "active"
        else AGENTTUI.CODEX_TURN_COMPLETE_EVENT
    )
    line = json.dumps({"type": "event_msg", "payload": {"type": event}})
    with session_file.open("a", encoding="utf-8") as stream:
        stream.write(line + ("\n" if terminated else ""))


def pane_ref(multiplexer: str = FAKE_MUX) -> dict[str, str]:
    return {
        "multiplexer": multiplexer,
        "session": PANE_SESSION,
        "pane_id": PANE_ID,
    }


class TransportDecouplingTests(unittest.TestCase):
    """The routing layer must speak capabilities, never multiplexer commands."""

    def test_unregistered_multiplexer_is_no_operational_route_not_a_bare_raise(
        self,
    ) -> None:
        target = make_record(pane_ref=pane_ref("some-unregistered-mux"))

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            AGENTTUI.build_route(target, "envelope", transports={FAKE_MUX: FakeTransport})

        self.assertEqual("unknown-pane-transport", caught.exception.reason)
        self.assertEqual(
            AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE,
            caught.exception.payload()["delivery"],
        )

    def test_a_freshly_registered_fake_transport_gets_a_pane_route(self) -> None:
        transport = FakeTransport()
        target = make_record(pane_ref=pane_ref())

        route = AGENTTUI.build_route(
            target,
            "envelope",
            transports={FAKE_MUX: lambda: transport},
            codex_submit_activity="idle",
        )

        self.assertEqual(AGENTTUI.ROUTE_PANE, route.mode)
        self.assertIs(transport, route.transport)
        self.assertEqual(1, transport.exists_calls)
        # The command line comes from the transport, not from the router. Codex
        # targets are paste-framed, which is also a transport-side decision.
        self.assertEqual(
            [
                "fake-mux-cli",
                "write",
                PANE_ID,
                transport.frame_paste("envelope"),
            ],
            route.pane_argv(),
        )

    def test_routing_functions_name_no_concrete_multiplexer(self) -> None:
        routing_source = "".join(
            inspect.getsource(function)
            for function in (
                AGENTTUI.build_route,
                AGENTTUI.build_pane_route,
                AGENTTUI.build_resume_route,
            )
        ).lower()

        for transport_name in AGENTTUI.TRANSPORTS:
            self.assertNotIn(transport_name.lower(), routing_source)
        for command in ("write-chars", "focus-pane-id", "--pane-id", "dump-screen"):
            self.assertNotIn(command, routing_source)

    def test_registry_is_the_single_multiplexer_to_transport_mapping(self) -> None:
        self.assertIn("zellij", AGENTTUI.TRANSPORTS)
        self.assertIs(AGENTTUI.ZellijTransport, AGENTTUI.TRANSPORTS["zellij"])
        self.assertIsInstance(AGENTTUI.resolve_transport("zellij"), AGENTTUI.PaneTransport)
        self.assertIsNone(AGENTTUI.resolve_transport("no-such-multiplexer"))

    def test_two_transports_coexist_so_migration_can_be_per_pane(self) -> None:
        # The registry is also the value domain of pane_ref.multiplexer. Both
        # entries stay registered on purpose: an existing pane_ref keeps working
        # while panes move one at a time, instead of a flag day.
        self.assertEqual({"zellij", "tmux"}, set(AGENTTUI.TRANSPORTS))
        self.assertIs(AGENTTUI.TmuxTransport, AGENTTUI.TRANSPORTS["tmux"])
        self.assertIsInstance(AGENTTUI.resolve_transport("tmux"), AGENTTUI.PaneTransport)


class ExistencePreflightTests(unittest.TestCase):
    """Rule 5: probe must report errors, and be judged by stdout text."""

    def test_missing_pane_is_refused_with_zero_injection_commands(self) -> None:
        runner = RecordingRunner(
            [FakeCompleted(returncode=0, stdout=f"Pane with id Terminal({PANE_ID}) not found\n")]
        )
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _name: "/placeholder/zellij")
        target = make_record(pane_ref=pane_ref("zellij"))

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            AGENTTUI.build_route(
                target,
                "envelope",
                transports={"zellij": lambda: transport},
                codex_submit_activity="idle",
            )

        self.assertEqual("pane-not-reachable", caught.exception.reason)
        # Exactly one command ran, and it was the probe — nothing was injected.
        self.assertEqual(["focus-pane-id"], runner.actions())

    def test_probe_exit_status_zero_with_not_found_text_is_not_success(self) -> None:
        runner = RecordingRunner(
            [FakeCompleted(returncode=0, stdout="Pane with id Terminal(0) not found")]
        )
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _name: "/placeholder/zellij")

        capability = transport.exists(pane_ref("zellij"))

        self.assertFalse(capability.ok)
        self.assertIn("not found", capability.detail)

    def test_missing_session_text_is_detected_although_exit_status_is_zero(self) -> None:
        runner = RecordingRunner(
            [FakeCompleted(returncode=0, stdout=f"Session '{PANE_SESSION}' not found\n")]
        )
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _name: "/placeholder/zellij")

        self.assertFalse(transport.exists(pane_ref("zellij")).ok)

    def test_exit_status_alone_never_decides_reachability(self) -> None:
        # Non-zero status with no addressing text must not be read as "missing":
        # the contract says text decides, not the exit code.
        runner = RecordingRunner([FakeCompleted(returncode=7, stdout="", stderr="")])
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _name: "/placeholder/zellij")

        self.assertTrue(transport.exists(pane_ref("zellij")).ok)

    def test_missing_session_text_survives_a_trailing_session_listing(self) -> None:
        # Real shape of the refusal: the "not found" sentence is followed by a
        # listing of the sessions that do exist, so the pattern must still match
        # mid-stream (format only — no observed session names here).
        runner = RecordingRunner(
            [
                FakeCompleted(
                    returncode=0,
                    stdout=(
                        f"Session '{PANE_SESSION}' not found. "
                        "The following sessions are active:\n"
                        "\x1b[32;1mplaceholder-other\x1b[m [Created 1h ago]\n"
                    ),
                )
            ]
        )
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _name: "/placeholder/zellij")

        self.assertFalse(transport.exists(pane_ref("zellij")).ok)

    def test_unrelated_output_is_not_mistaken_for_an_addressing_failure(self) -> None:
        runner = RecordingRunner(
            [FakeCompleted(returncode=0, stdout="config file not found, using defaults")]
        )
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _name: "/placeholder/zellij")

        self.assertTrue(transport.exists(pane_ref("zellij")).ok)

    def test_probe_is_the_focus_command_and_never_a_screen_dump(self) -> None:
        transport = AGENTTUI.ZellijTransport(
            runner=RecordingRunner(), which=lambda _name: "/placeholder/zellij"
        )

        probe_argv = transport.probe_argv(pane_ref("zellij"))

        self.assertIn("focus-pane-id", probe_argv)
        self.assertNotIn("dump-screen", probe_argv)
        # The focus side effect must be documented, not hidden.
        self.assertIn("focus", AGENTTUI.ZellijTransport.exists.__doc__.lower())

    def test_unavailable_transport_is_refused_before_any_probe(self) -> None:
        runner = RecordingRunner()
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _name: None)
        target = make_record(pane_ref=pane_ref("zellij"))

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            AGENTTUI.build_route(
                target, "envelope", transports={"zellij": lambda: transport}
            )

        self.assertEqual("pane-transport-unavailable", caught.exception.reason)
        self.assertEqual([], runner.calls)


class SilentInjectionTests(unittest.TestCase):
    """The worst case: a transport command that cannot testify against itself."""

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.session_file = Path(self.temporary.name) / "target-session.jsonl"
        self.session_file.write_text("existing transcript line\n", encoding="utf-8")
        # Keep the suite fast: these cases are about outcome classification, not
        # about how long verification is willing to wait.
        self._window = AGENTTUI.PANE_VERIFY_WINDOW_SECONDS
        self._queued_window = AGENTTUI.PANE_VERIFY_QUEUED_WINDOW_SECONDS
        self._poll = AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS
        AGENTTUI.PANE_VERIFY_WINDOW_SECONDS = 0.0
        AGENTTUI.PANE_VERIFY_QUEUED_WINDOW_SECONDS = 0.0
        AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = 0.0

    def tearDown(self) -> None:
        AGENTTUI.PANE_VERIFY_WINDOW_SECONDS = self._window
        AGENTTUI.PANE_VERIFY_QUEUED_WINDOW_SECONDS = self._queued_window
        AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = self._poll

    def run_pane_send(self, transport: FakeTransport, *, marker: str = "marker-absent"):
        route = AGENTTUI.DeliveryRoute(
            mode=AGENTTUI.ROUTE_PANE,
            cwd=Path(self.temporary.name),
            transport=transport,
            pane_ref=pane_ref(),
            pane_text="envelope body",
            submit_byte=AGENTTUI.PANE_ENTER_BYTE,
        )
        payload = {
            "target": TARGET,
            "target_brand": "claude-code",
            "target_effective_state": "active",
            "target_session_file": str(self.session_file),
            "delivery_marker": marker,
            "nonce": NONCE,
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = AGENTTUI.send_via_pane(
                route, payload, timeout=None, submit_delay=0.0
            )
        return status, json.loads(stdout.getvalue().strip().splitlines()[-1]), stderr.getvalue()

    def test_zero_status_and_empty_output_is_never_delivery_evidence(self) -> None:
        silent = AGENTTUI.CommandOutcome(
            argv=["fake"], returncode=0, stdout="", stderr="", rejected=False, detail=""
        )
        transport = FakeTransport(write_outcome=silent, submit_outcome=silent)

        _status, result, warnings = self.run_pane_send(transport)

        self.assertEqual(AGENTTUI.DELIVERY_SUBMIT_UNVERIFIED, result["delivery"])
        self.assertEqual("none", result["evidence"])
        self.assertFalse(result["transport_exit_status_trusted"])
        self.assertIn("not delivery evidence", warnings)

    def test_rejected_submit_after_injection_is_unverified_not_unsent(self) -> None:
        # Bytes already left this process, so "nothing was sent" would be a lie;
        # a blind resend could duplicate the envelope (rule 2).
        rejected = AGENTTUI.CommandOutcome(
            argv=["fake"],
            returncode=0,
            stdout="Pane with id Terminal(0) not found",
            stderr="",
            rejected=True,
            detail="transport reported 'not found'",
        )
        transport = FakeTransport(submit_outcome=rejected)

        status, result, warnings = self.run_pane_send(transport)

        self.assertEqual(
            AGENTTUI.DELIVERY_SUBMIT_COMMAND_UNVERIFIED, result["delivery"]
        )
        self.assertTrue(result["sent"])
        self.assertFalse(result["retry_safe"])
        self.assertIsNotNone(result["submit_rejected"])
        self.assertEqual(AGENTTUI.EXIT_UNCERTAIN_DELIVERY, status)
        self.assertIn("blind resend can duplicate", warnings)

    def test_nonce_in_transcript_is_the_only_delivery_evidence(self) -> None:
        marker = f"from={SENDER} nonce={NONCE}"
        transport = FakeTransport()

        def append_marker(*_args, **_kwargs):
            with self.session_file.open("a", encoding="utf-8") as stream:
                stream.write(marker + "\n")
            return AGENTTUI.CommandOutcome(
                argv=["fake"], returncode=0, stdout="", stderr="", rejected=False, detail=""
            )

        transport.send_key = append_marker  # type: ignore[assignment]
        _status, result, _warnings = self.run_pane_send(transport, marker=marker)

        self.assertEqual(AGENTTUI.DELIVERY_DELIVERED, result["delivery"])
        self.assertEqual("envelope-nonce-found", result["evidence"])

    def test_rejected_injection_reports_nothing_was_sent(self) -> None:
        rejected = AGENTTUI.CommandOutcome(
            argv=["fake"],
            returncode=0,
            stdout=f"Session '{PANE_SESSION}' not found",
            stderr="",
            rejected=True,
            detail="transport reported 'not found'",
        )
        transport = FakeTransport(write_outcome=rejected)

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            self.run_pane_send(transport)

        self.assertEqual("pane-injection-rejected", caught.exception.reason)
        self.assertFalse(caught.exception.payload()["sent"])
        self.assertEqual([], transport.keys)


class SendSideCapabilityTests(unittest.TestCase):
    """Rule 6: check only the capability this route actually uses."""

    def test_pane_route_does_not_check_the_resume_cli(self) -> None:
        transport = FakeTransport()
        target = make_record(pane_ref=pane_ref())

        route = AGENTTUI.build_route(
            target,
            "envelope",
            transports={FAKE_MUX: lambda: transport},
            codex_submit_activity="idle",
            which=lambda _name: None,  # no resume CLI anywhere
        )

        self.assertEqual(AGENTTUI.ROUTE_PANE, route.mode)

    def test_resume_route_without_its_cli_is_no_operational_route(self) -> None:
        target = make_record(brand="claude-code", state="idle", pane_ref=None)

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            AGENTTUI.build_route(
                target, "envelope", allow_resume=True, which=lambda _name: None
            )

        self.assertEqual("resume-cli-missing", caught.exception.reason)

    def test_resume_route_with_its_cli_is_allowed_when_requested(self) -> None:
        target = make_record(brand="claude-code", state="idle", pane_ref=None)

        route = AGENTTUI.build_route(
            target,
            "envelope",
            allow_resume=True,
            which=lambda name: f"/placeholder/{name}",
        )

        self.assertEqual(AGENTTUI.ROUTE_RESUME, route.mode)

    def test_claude_code_without_pane_no_longer_falls_back_silently(self) -> None:
        target = make_record(brand="claude-code", state="active", pane_ref=None)

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            AGENTTUI.build_route(
                target, "envelope", which=lambda name: f"/placeholder/{name}"
            )

        self.assertEqual("resume-not-authorized", caught.exception.reason)

    def test_both_brands_refuse_in_the_same_shape(self) -> None:
        refusals = {}
        for brand in ("claude-code", "codex"):
            target = make_record(brand=brand, state="active", pane_ref=None)
            with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
                AGENTTUI.build_route(
                    target, "envelope", which=lambda name: f"/placeholder/{name}"
                )
            refusals[brand] = caught.exception.payload()

        self.assertEqual(
            refusals["claude-code"].keys(), refusals["codex"].keys()
        )
        self.assertEqual(refusals["claude-code"], refusals["codex"])

    def test_active_codex_still_refuses_resume_even_when_authorized(self) -> None:
        target = make_record(brand="codex", state="active", pane_ref=None)

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            AGENTTUI.build_route(
                target,
                "envelope",
                allow_resume=True,
                which=lambda name: f"/placeholder/{name}",
            )

        self.assertEqual("active-codex-requires-pane", caught.exception.reason)

    def test_authorized_resume_after_a_pane_failure_is_loudly_warned(self) -> None:
        target = make_record(brand="claude-code", state="idle", pane_ref=pane_ref())

        route = AGENTTUI.build_route(
            target,
            "envelope",
            transports={FAKE_MUX: lambda: FakeTransport(exists=False)},
            allow_resume=True,
            which=lambda name: f"/placeholder/{name}",
        )

        self.assertEqual(AGENTTUI.ROUTE_RESUME, route.mode)
        self.assertTrue(route.warnings)
        self.assertIn("pane route unusable", route.warnings[0])


class DeliveryVocabularyTests(unittest.TestCase):
    """"Nothing was sent" and "sent but unproven" must stay distinguishable."""

    SENT_BUT_UNPROVEN = (
        "DELIVERY_QUEUED_FOR_NEXT_TURN",
        "DELIVERY_SUBMIT_UNVERIFIED",
        "DELIVERY_COMPOSER_UNSUBMITTED",
        "DELIVERY_WRITE_UNVERIFIED",
        "DELIVERY_SUBMIT_COMMAND_UNVERIFIED",
        "DELIVERY_RESUME_STARTED_UNVERIFIED",
        "DELIVERY_RESUME_EXITED_UNVERIFIED",
    )

    def test_no_operational_route_is_distinct_from_every_sent_outcome(self) -> None:
        self.assertEqual("no-operational-route", AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE)
        for name in self.SENT_BUT_UNPROVEN:
            self.assertNotEqual(
                AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE, getattr(AGENTTUI, name), name
            )

    def test_the_single_unverified_bucket_is_gone(self) -> None:
        # The former one-value bucket covered outcomes whose correct caller
        # behaviour is opposite, so a caller could not tell them apart.
        self.assertFalse(hasattr(AGENTTUI, "DELIVERY_QUEUED_UNVERIFIED"))

    def test_every_outcome_names_a_caller_action(self) -> None:
        outcomes = {
            value
            for name, value in vars(AGENTTUI).items()
            if name.startswith("DELIVERY_") and isinstance(value, str)
        }
        # no-operational-route carries its action as `remedy` on the exception.
        outcomes.discard(AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE)

        self.assertEqual(outcomes, set(AGENTTUI.OUTCOME_GUIDANCE))
        for delivery, (action, guidance) in AGENTTUI.OUTCOME_GUIDANCE.items():
            self.assertTrue(action, delivery)
            self.assertTrue(guidance, delivery)

    def test_only_provably_zero_command_outcomes_are_retry_safe(self) -> None:
        # The hard rule: retry_safe claims "resending cannot duplicate anything",
        # which is only mechanically true where no pane command ran at all.
        self.assertEqual(
            {
                AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE,
                AGENTTUI.DELIVERY_PRE_INJECTION_REJECTED,
            },
            set(AGENTTUI.RETRY_SAFE_OUTCOMES),
        )
        for name in self.SENT_BUT_UNPROVEN:
            self.assertNotIn(getattr(AGENTTUI, name), AGENTTUI.RETRY_SAFE_OUTCOMES, name)

    def test_the_queued_outcome_forbids_resending_on_an_early_miss(self) -> None:
        action, guidance = AGENTTUI.OUTCOME_GUIDANCE[
            AGENTTUI.DELIVERY_QUEUED_FOR_NEXT_TURN
        ]

        self.assertIn("do-not-resend", action)
        self.assertEqual(
            "early-transcript-miss-is-not-nondelivery-evidence", guidance
        )

    def test_structured_payloads_disagree_on_sent_and_retry_safe(self) -> None:
        refusal = AGENTTUI.NoOperationalRoute(
            "resume-not-authorized", "detail", remedy="remedy"
        ).payload()

        self.assertFalse(refusal["sent"])
        self.assertTrue(refusal["retry_safe"])
        self.assertEqual("none", refusal["evidence"])

    def test_no_operational_route_exits_non_zero_and_prints_the_payload(self) -> None:
        with TemporaryDirectory() as temporary:
            repo = write_registry(Path(temporary), target_pane_ref=None)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                status = AGENTTUI.main(
                    [
                        "--repo",
                        str(repo),
                        "send",
                        "--from",
                        SENDER,
                        "--to",
                        TARGET,
                        "--message",
                        MESSAGE,
                    ]
                )

        payload = json.loads(stdout.getvalue().strip())
        self.assertNotEqual(0, status)
        self.assertEqual(AGENTTUI.EXIT_NO_OPERATIONAL_ROUTE, status)
        self.assertEqual(AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE, payload["delivery"])
        self.assertEqual("resume-not-authorized", payload["reason"])


def write_registry(
    base: Path,
    *,
    target_pane_ref: dict[str, str] | None,
    target_brand: str = "claude-code",
) -> Path:
    """Create a minimal project repository with two registered agents."""
    repo = base / "placeholder-repo"
    (repo / ".trellis").mkdir(parents=True)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for name, brand, pane in ((SENDER, "codex", None), (TARGET, target_brand, target_pane_ref)):
        leaf = repo / ".arborist" / "agents" / name
        leaf.mkdir(parents=True)
        session_file = repo / f"{name}-session.jsonl"
        session_file.write_text("transcript line\n", encoding="utf-8")
        (leaf / "spec.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "brand": brand,
                    "role": "impler",
                    "project": {"path": str(repo), "project_id": "placeholder-project"},
                }
            ),
            encoding="utf-8",
        )
        (leaf / "runtime.json").write_text(
            json.dumps(
                {
                    "session_id": f"{name}-session-id",
                    "session_file": str(session_file),
                    "state": "active",
                    "last_seen": now,
                    "pane_ref": pane,
                }
            ),
            encoding="utf-8",
        )
    return repo


class RepoDerivationGateTests(unittest.TestCase):
    """The path-derivation half of the delivery preflight contract."""

    def test_non_repository_is_refused_with_no_side_effects(self) -> None:
        with TemporaryDirectory() as temporary:
            outside = Path(temporary) / "not-a-repository"
            outside.mkdir()
            before = sorted(path.name for path in outside.iterdir())

            with self.assertRaises(AGENTTUI.RegistryError) as caught:
                AGENTTUI.resolve_repo_root(outside, explicit=True)

            self.assertIn("not a project repository", str(caught.exception))
            self.assertEqual(before, sorted(path.name for path in outside.iterdir()))

    def test_missing_directory_is_refused(self) -> None:
        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "absent"

            with self.assertRaises(AGENTTUI.RegistryError):
                AGENTTUI.resolve_repo_root(missing, explicit=False)

            self.assertFalse(missing.exists())

    def test_git_or_trellis_marker_is_accepted(self) -> None:
        with TemporaryDirectory() as temporary:
            for marker in AGENTTUI.REPO_MARKERS:
                candidate = Path(temporary) / f"repo-with-{marker.strip('.')}"
                (candidate / marker).mkdir(parents=True)
                self.assertEqual(
                    candidate.resolve(),
                    AGENTTUI.resolve_repo_root(candidate, explicit=True),
                )

    def test_cli_refuses_a_non_repository_and_creates_nothing(self) -> None:
        with TemporaryDirectory() as temporary:
            outside = Path(temporary) / "not-a-repository"
            outside.mkdir()

            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as caught:
                    AGENTTUI.main(["--repo", str(outside), "status", "--name", TARGET])

            self.assertNotEqual(0, caught.exception.code)
            self.assertIn("not a project repository", stderr.getvalue())
            self.assertEqual([], list(outside.iterdir()))

    def test_explicit_valid_repository_is_used(self) -> None:
        with TemporaryDirectory() as temporary:
            repo = write_registry(Path(temporary), target_pane_ref=None)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = AGENTTUI.main(
                    ["--repo", str(repo), "status", "--name", TARGET]
                )

            self.assertEqual(0, status)
            self.assertEqual(TARGET, json.loads(stdout.getvalue())["name"])

    def test_dry_run_shows_the_pane_route_without_probing_or_sending(self) -> None:
        transport = FakeTransport()
        original = AGENTTUI.TRANSPORTS.copy()
        AGENTTUI.TRANSPORTS.clear()
        AGENTTUI.TRANSPORTS[FAKE_MUX] = lambda: transport
        self.addCleanup(lambda: (AGENTTUI.TRANSPORTS.clear(), AGENTTUI.TRANSPORTS.update(original)))

        with TemporaryDirectory() as temporary:
            repo = write_registry(Path(temporary), target_pane_ref=pane_ref())
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = AGENTTUI.main(
                    [
                        "--repo",
                        str(repo),
                        "send",
                        "--from",
                        SENDER,
                        "--to",
                        TARGET,
                        "--message",
                        MESSAGE,
                        "--dry-run",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, status)
        self.assertEqual(AGENTTUI.ROUTE_PANE, payload["route_mode"])
        self.assertEqual(FAKE_MUX, payload["pane_transport"])
        self.assertEqual(0, transport.exists_calls)
        self.assertIn("steals terminal focus", payload["pane_preflight"])
        self.assertEqual([], transport.writes)


class CapacityRepoDerivationGateTests(unittest.TestCase):
    """The same gate on the second script that infers its root from __file__."""

    def test_non_repository_is_refused_with_no_side_effects(self) -> None:
        with TemporaryDirectory() as temporary:
            outside = Path(temporary) / "not-a-repository"
            outside.mkdir()

            with self.assertRaises(CAPACITY.CapacityError) as caught:
                CAPACITY.resolve_repo_root(outside)

            self.assertIn("not a project repository", str(caught.exception))
            self.assertEqual([], list(outside.iterdir()))

    def test_cli_refuses_and_creates_no_runtime_directory(self) -> None:
        with TemporaryDirectory() as temporary:
            outside = Path(temporary) / "not-a-repository"
            outside.mkdir()

            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                status = CAPACITY.main(["--repo", str(outside), "refresh"])

            self.assertEqual(1, status)
            self.assertIn("not a project repository", stderr.getvalue())
            self.assertEqual([], list(outside.iterdir()))
            self.assertFalse((outside / ".arborist").exists())

    def test_defaults_derive_from_the_validated_root(self) -> None:
        with TemporaryDirectory() as temporary:
            repo = Path(temporary) / "placeholder-repo"
            (repo / ".git").mkdir(parents=True)
            args = CAPACITY.build_parser().parse_args(
                ["--repo", str(repo), "status"]
            )

            CAPACITY.resolve_paths(args)

            self.assertEqual(repo.resolve(), args.repo)
            self.assertEqual(repo.resolve() / CAPACITY.STATE_RELATIVE_PATH, args.state)
            self.assertEqual(repo.resolve() / CAPACITY.LOCK_RELATIVE_PATH, args.lock)
            # Validation alone must not have created the runtime tree.
            self.assertFalse((repo / ".arborist").exists())



class VerificationWindowTests(unittest.TestCase):
    """Shape 4: a verify window shorter than the target's flush.

    The window used to be one second (10 attempts x 0.1s). Measured three times:
    a delivered envelope's transcript record lands later than that, so the reading
    came back `queued-unverified` for messages that had in fact arrived -- and the
    false negative then drove a *second* submit key. These tests pin both halves:
    a late flush must still read as delivered, and it must not press submit twice.
    """

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.session_file = Path(self.temporary.name) / "target-session.jsonl"
        self.session_file.write_text("existing transcript line\n", encoding="utf-8")
        self._real_contains = AGENTTUI.transcript_contains_marker
        self.addCleanup(
            setattr, AGENTTUI, "transcript_contains_marker", self._real_contains
        )
        self._poll = AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS
        self._window = AGENTTUI.PANE_VERIFY_WINDOW_SECONDS
        AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = 0.0
        AGENTTUI.PANE_VERIFY_WINDOW_SECONDS = 5.0

        def restore() -> None:
            AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = self._poll
            AGENTTUI.PANE_VERIFY_WINDOW_SECONDS = self._window

        self.addCleanup(restore)

    def appears_on_call(self, nth: int) -> list[int]:
        """Make the marker surface only on the nth transcript check."""
        calls: list[int] = []

        def fake(path, marker, start_offset):
            calls.append(1)
            return len(calls) >= nth

        AGENTTUI.transcript_contains_marker = fake
        return calls

    def send(
        self,
        *,
        brand: str = "claude-code",
        state: str = "idle",
        activity: str | None = None,
    ):
        if activity is not None:
            append_codex_boundary(self.session_file, activity)
        transport = FakeTransport()
        route = AGENTTUI.DeliveryRoute(
            mode=AGENTTUI.ROUTE_PANE,
            cwd=Path(self.temporary.name),
            transport=transport,
            pane_ref=pane_ref(),
            pane_text="envelope body",
            submit_byte=AGENTTUI.PANE_ENTER_BYTE,
        )
        payload = {
            "target": TARGET,
            "target_brand": brand,
            "target_effective_state": state,
            "target_submit_activity": activity,
            "target_session_file": str(self.session_file),
            "delivery_marker": f"from={SENDER} nonce={NONCE}",
            "nonce": NONCE,
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            AGENTTUI.send_via_pane(route, payload, timeout=None, submit_delay=0.0)
        result = json.loads(stdout.getvalue().strip().splitlines()[-1])
        return transport, result

    def test_late_flush_reads_as_delivered(self) -> None:
        calls = self.appears_on_call(3)

        _transport, result = self.send()

        self.assertEqual(AGENTTUI.DELIVERY_DELIVERED, result["delivery"])
        self.assertEqual("envelope-nonce-found", result["evidence"])
        self.assertGreaterEqual(len(calls), 3)

    def test_late_flush_never_presses_submit_twice(self) -> None:
        # The regression that mattered: the 1s window's false negative made the
        # retry branch fire, so a delivered envelope got a second submit key.
        self.appears_on_call(3)

        transport, result = self.send()

        self.assertEqual(AGENTTUI.DELIVERY_DELIVERED, result["delivery"])
        self.assertEqual(1, len(transport.keys))

    def test_active_codex_is_not_resent_and_stays_queued(self) -> None:
        # Tab already enqueued the envelope; the nonce cannot appear before the
        # turn ends, so this must neither wait it out nor press a second key.
        AGENTTUI.transcript_contains_marker = lambda *args, **kwargs: False
        AGENTTUI.PANE_VERIFY_QUEUED_WINDOW_SECONDS = 0.0
        self.addCleanup(
            setattr, AGENTTUI, "PANE_VERIFY_QUEUED_WINDOW_SECONDS", 1.0
        )

        transport, result = self.send(brand="codex", state="active", activity="active")

        self.assertEqual(AGENTTUI.DELIVERY_QUEUED_FOR_NEXT_TURN, result["delivery"])
        self.assertEqual(1, len(transport.keys))

    def test_window_is_expressed_in_seconds_and_stays_wide(self) -> None:
        # Direction, not just the number: early exit means widening is free,
        # while narrowing turns delivered into unverified and provokes a
        # duplicate submit. Widening is fail-safe; narrowing is fail-dangerous.
        self.assertFalse(hasattr(AGENTTUI, "PANE_VERIFY_ATTEMPTS"))
        self.assertGreaterEqual(self._window, 15.0)
        self.assertLess(
            AGENTTUI.PANE_VERIFY_QUEUED_WINDOW_SECONDS, self._window
        )

    def test_zero_window_still_checks_once(self) -> None:
        calls = self.appears_on_call(1)

        found = AGENTTUI.wait_for_transcript_marker(
            self.session_file, "marker", 0, 0.0
        )

        self.assertTrue(found)
        self.assertEqual(1, len(calls))

    def test_window_bounds_the_wait_with_an_injected_clock(self) -> None:
        AGENTTUI.transcript_contains_marker = lambda *args, **kwargs: False
        # A fake clock only advances through the injected sleep, so this case
        # needs a real poll interval; setUp zeroes it for the fast cases.
        AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = 0.1
        now = [0.0]
        slept: list[float] = []

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            now[0] += seconds

        found = AGENTTUI.wait_for_transcript_marker(
            self.session_file,
            "marker",
            0,
            2.0,
            monotonic=lambda: now[0],
            sleep=sleep,
        )

        self.assertFalse(found)
        self.assertAlmostEqual(2.0, sum(slept), places=6)
        # Backoff, not a busy loop.
        self.assertLess(len(slept), 20)



class CodexSubmitActivityTests(unittest.TestCase):
    """Reachability and current turn activity are two different questions.

    Transcript freshness answers "is this pane worth addressing"; it does not
    answer "is a turn running right now". A target whose turn just finished is
    still inside the freshness window, so routing on freshness hands Tab to an
    idle composer, where it enqueues nothing and the envelope sits unsubmitted.
    """

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.session_file = Path(self.temporary.name) / "target-session.jsonl"
        self.session_file.write_text("", encoding="utf-8")

    def write(self, *lines: str, terminated: bool = True) -> None:
        text = "\n".join(lines)
        self.session_file.write_text(
            text + ("\n" if terminated and text else ""), encoding="utf-8"
        )

    @staticmethod
    def event(event_type: str) -> str:
        return json.dumps({"type": "event_msg", "payload": {"type": event_type}})

    def test_latest_task_started_reads_as_active(self) -> None:
        self.write(
            self.event(AGENTTUI.CODEX_TURN_COMPLETE_EVENT),
            self.event(AGENTTUI.CODEX_TURN_STARTED_EVENT),
        )

        self.assertEqual(
            AGENTTUI.SUBMIT_ACTIVITY_ACTIVE,
            AGENTTUI.derive_codex_submit_activity(self.session_file),
        )

    def test_latest_task_complete_reads_as_idle(self) -> None:
        self.write(
            self.event(AGENTTUI.CODEX_TURN_STARTED_EVENT),
            self.event(AGENTTUI.CODEX_TURN_COMPLETE_EVENT),
        )

        self.assertEqual(
            AGENTTUI.SUBMIT_ACTIVITY_IDLE,
            AGENTTUI.derive_codex_submit_activity(self.session_file),
        )

    def test_an_unterminated_tail_is_unknown_not_the_previous_boundary(self) -> None:
        # A record still being written means the state is in flux. Skipping it
        # would confidently report the state the target was in *before* it.
        self.write(
            self.event(AGENTTUI.CODEX_TURN_COMPLETE_EVENT),
            self.event(AGENTTUI.CODEX_TURN_STARTED_EVENT),
            terminated=False,
        )

        self.assertIsNone(AGENTTUI.derive_codex_submit_activity(self.session_file))

    def test_unrelated_and_malformed_records_are_skipped(self) -> None:
        self.write(
            self.event(AGENTTUI.CODEX_TURN_COMPLETE_EVENT),
            "not json at all",
            json.dumps({"type": "response_item", "payload": {"type": "message"}}),
            json.dumps({"type": "event_msg", "payload": "not-an-object"}),
            json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}),
        )

        self.assertEqual(
            AGENTTUI.SUBMIT_ACTIVITY_IDLE,
            AGENTTUI.derive_codex_submit_activity(self.session_file),
        )

    def test_no_boundary_at_all_is_unknown(self) -> None:
        self.write(json.dumps({"type": "response_item", "payload": {}}))

        self.assertIsNone(AGENTTUI.derive_codex_submit_activity(self.session_file))

    def test_empty_and_missing_transcripts_are_unknown(self) -> None:
        self.write()
        self.assertIsNone(AGENTTUI.derive_codex_submit_activity(self.session_file))
        self.assertIsNone(
            AGENTTUI.derive_codex_submit_activity(
                Path(self.temporary.name) / "absent.jsonl"
            )
        )

    def test_reverse_scan_crosses_chunk_boundaries_in_order(self) -> None:
        self.write(*[f"line-{index}" for index in range(20)])

        lines = list(AGENTTUI.iter_reverse_lines(self.session_file, chunk_size=8))

        self.assertEqual(b"line-19", lines[0])
        self.assertEqual(b"line-0", lines[-1])
        self.assertEqual(20, len(lines))

    def test_requiring_the_activity_refuses_instead_of_guessing(self) -> None:
        self.write()

        with self.assertRaises(AGENTTUI.CodexTurnStateUnknown) as caught:
            AGENTTUI.require_codex_submit_activity(self.session_file)

        self.assertIn("refusing to guess", str(caught.exception))

    def test_freshness_active_but_idle_turn_routes_enter_not_tab(self) -> None:
        # The exact downstream failure: a reachable-active Codex whose turn had
        # completed was handed Tab, and the envelope stayed in the composer.
        target = make_record(brand="codex", state="active", pane_ref=pane_ref())

        route = AGENTTUI.build_route(
            target,
            "envelope",
            transports={FAKE_MUX: lambda: FakeTransport()},
            codex_submit_activity=AGENTTUI.SUBMIT_ACTIVITY_IDLE,
        )

        self.assertEqual(AGENTTUI.PANE_ENTER_BYTE, route.submit_byte)
        self.assertEqual(AGENTTUI.SUBMIT_ACTIVITY_IDLE, route.submit_activity)

    def test_a_running_turn_still_routes_tab(self) -> None:
        target = make_record(brand="codex", state="active", pane_ref=pane_ref())

        route = AGENTTUI.build_route(
            target,
            "envelope",
            transports={FAKE_MUX: lambda: FakeTransport()},
            codex_submit_activity=AGENTTUI.SUBMIT_ACTIVITY_ACTIVE,
        )

        self.assertEqual(AGENTTUI.CODEX_PANE_QUEUE_BYTE, route.submit_byte)

    def test_claude_code_routing_never_consults_a_turn_boundary(self) -> None:
        # Enter unconditionally, handled by its own receiver-side queue: Tab there
        # is autocomplete, so the Codex adaptation must not be copied over.
        target = make_record(brand="claude-code", state="active", pane_ref=pane_ref())

        route = AGENTTUI.build_route(
            target, "envelope", transports={FAKE_MUX: lambda: FakeTransport()}
        )

        self.assertEqual(AGENTTUI.PANE_ENTER_BYTE, route.submit_byte)
        self.assertIsNone(route.submit_activity)


class PreInjectionRejectionTests(unittest.TestCase):
    """Unknown turn state before the first pane command: refuse, zero commands.

    This is the only pane outcome allowed to claim retry_safe=true, and the claim
    is only true if nothing — including the existence probe, which is itself a
    focus command — has touched the pane yet.
    """

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def repo_with_unreadable_turn_state(self, *, brand: str = "codex") -> Path:
        repo = write_registry(
            Path(self.temporary.name), target_pane_ref=pane_ref(), target_brand=brand
        )
        # Fresh transcript (so the target reads as reachable) that carries no
        # turn-boundary event at all.
        session_file = repo / f"{TARGET}-session.jsonl"
        session_file.write_text("transcript line\n", encoding="utf-8")
        return repo

    def test_zero_pane_commands_run_when_the_turn_state_is_unreadable(self) -> None:
        transport = FakeTransport()
        repo = self.repo_with_unreadable_turn_state()

        with self.assertRaises(AGENTTUI.CodexTurnStateUnknown):
            AGENTTUI.plan_delivery(
                repo,
                sender_name=SENDER,
                target_name=TARGET,
                message=MESSAGE,
                nonce=NONCE,
                script_path=Path("/placeholder/agenttui.py"),
                transports={FAKE_MUX: lambda: transport},
            )

        self.assertEqual(0, transport.exists_calls)
        self.assertEqual([], transport.writes)
        self.assertEqual([], transport.keys)

    def test_cli_reports_pre_injection_rejected_and_exits_non_zero(self) -> None:
        transport = FakeTransport()
        original = AGENTTUI.TRANSPORTS.copy()
        AGENTTUI.TRANSPORTS.clear()
        AGENTTUI.TRANSPORTS[FAKE_MUX] = lambda: transport
        self.addCleanup(
            lambda: (AGENTTUI.TRANSPORTS.clear(), AGENTTUI.TRANSPORTS.update(original))
        )
        repo = self.repo_with_unreadable_turn_state()

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            status = AGENTTUI.main(
                [
                    "--repo",
                    str(repo),
                    "send",
                    "--from",
                    SENDER,
                    "--to",
                    TARGET,
                    "--message",
                    MESSAGE,
                    "--no-observation-log",
                ]
            )

        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(AGENTTUI.EXIT_PRE_INJECTION_REJECTED, status)
        self.assertEqual(AGENTTUI.DELIVERY_PRE_INJECTION_REJECTED, payload["delivery"])
        self.assertEqual("none-pre-injection", payload["submit_action"])
        self.assertFalse(payload["sent"])
        self.assertTrue(payload["retry_safe"])
        self.assertEqual("no-pane-command-executed", payload["verification_guidance"])
        self.assertEqual([], transport.writes)

    def test_the_refusal_is_not_conflated_with_no_operational_route(self) -> None:
        # Both mean "nothing was sent", but the remedies differ: repair the route
        # versus read the state again.
        self.assertNotEqual(
            AGENTTUI.EXIT_PRE_INJECTION_REJECTED, AGENTTUI.EXIT_NO_OPERATIONAL_ROUTE
        )
        self.assertNotEqual(
            AGENTTUI.DELIVERY_PRE_INJECTION_REJECTED,
            AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE,
        )

    def test_a_claude_code_target_is_unaffected_by_the_same_transcript(self) -> None:
        transport = FakeTransport()
        repo = self.repo_with_unreadable_turn_state(brand="claude-code")

        plan = AGENTTUI.plan_delivery(
            repo,
            sender_name=SENDER,
            target_name=TARGET,
            message=MESSAGE,
            nonce=NONCE,
            script_path=Path("/placeholder/agenttui.py"),
            transports={FAKE_MUX: lambda: transport},
        )

        self.assertEqual(AGENTTUI.ROUTE_PANE, plan.route.mode)
        self.assertIsNone(plan.payload["target_submit_activity"])

    def test_dry_run_refuses_too_instead_of_showing_a_guessed_key(self) -> None:
        transport = FakeTransport()
        original = AGENTTUI.TRANSPORTS.copy()
        AGENTTUI.TRANSPORTS.clear()
        AGENTTUI.TRANSPORTS[FAKE_MUX] = lambda: transport
        self.addCleanup(
            lambda: (AGENTTUI.TRANSPORTS.clear(), AGENTTUI.TRANSPORTS.update(original))
        )
        repo = self.repo_with_unreadable_turn_state()

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            status = AGENTTUI.main(
                [
                    "--repo",
                    str(repo),
                    "send",
                    "--from",
                    SENDER,
                    "--to",
                    TARGET,
                    "--message",
                    MESSAGE,
                    "--dry-run",
                ]
            )

        self.assertEqual(AGENTTUI.EXIT_PRE_INJECTION_REJECTED, status)
        self.assertEqual(
            AGENTTUI.DELIVERY_PRE_INJECTION_REJECTED,
            json.loads(stdout.getvalue().strip())["delivery"],
        )


class PaneOutcomeClassificationTests(unittest.TestCase):
    """Rule 4: name the outcome after the action that was actually executed.

    One shared "unverified" value covered outcomes whose correct caller behaviour
    is opposite — wait out a turn boundary, recover an unsubmitted composer,
    inspect a command that never reported back — so the reading could not tell a
    caller which one had happened. Each case below pins one action's outcome.
    """

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.session_file = Path(self.temporary.name) / "target-session.jsonl"
        self.session_file.write_text("existing transcript line\n", encoding="utf-8")
        self._window = AGENTTUI.PANE_VERIFY_WINDOW_SECONDS
        self._queued = AGENTTUI.PANE_VERIFY_QUEUED_WINDOW_SECONDS
        self._poll = AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS
        AGENTTUI.PANE_VERIFY_WINDOW_SECONDS = 0.0
        AGENTTUI.PANE_VERIFY_QUEUED_WINDOW_SECONDS = 0.0
        AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = 0.0

        def restore() -> None:
            AGENTTUI.PANE_VERIFY_WINDOW_SECONDS = self._window
            AGENTTUI.PANE_VERIFY_QUEUED_WINDOW_SECONDS = self._queued
            AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = self._poll

        self.addCleanup(restore)

    def send(
        self,
        transport: FakeTransport,
        *,
        brand: str = "codex",
        activity: str | None = None,
        marker: str = "marker-absent",
        submit_byte: str | None = None,
    ):
        route = AGENTTUI.DeliveryRoute(
            mode=AGENTTUI.ROUTE_PANE,
            cwd=Path(self.temporary.name),
            transport=transport,
            pane_ref=pane_ref(),
            pane_text="envelope body",
            submit_byte=submit_byte
            or (
                AGENTTUI.CODEX_PANE_QUEUE_BYTE
                if activity == "active"
                else AGENTTUI.PANE_ENTER_BYTE
            ),
            paste_framed=brand in AGENTTUI.PASTE_FRAMED_BRANDS,
            submit_activity=activity,
        )
        payload = {
            "target": TARGET,
            "target_brand": brand,
            "target_effective_state": "active",
            "target_submit_activity": activity,
            "target_session_file": str(self.session_file),
            "delivery_marker": marker,
            "nonce": NONCE,
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = AGENTTUI.send_via_pane(
                route, payload, timeout=None, submit_delay=0.0
            )
        return (
            status,
            json.loads(stdout.getvalue().strip().splitlines()[-1]),
            stderr.getvalue(),
        )

    def scripted_activity(self, *answers: str | None) -> list[int]:
        """Replace the turn-state reading with a scripted sequence (a file seam)."""
        calls: list[int] = []
        queue = list(answers)

        def fake(_session_file):
            calls.append(1)
            return queue.pop(0) if queue else answers[-1]

        original = AGENTTUI.derive_codex_submit_activity
        AGENTTUI.derive_codex_submit_activity = fake
        self.addCleanup(setattr, AGENTTUI, "derive_codex_submit_activity", original)
        return calls

    def test_a_write_command_that_never_reports_back_is_write_unverified(self) -> None:
        transport = FakeTransport()
        transport.write_timeout = True

        status, result, warnings = self.send(transport, activity="idle")

        self.assertEqual(AGENTTUI.DELIVERY_WRITE_UNVERIFIED, result["delivery"])
        self.assertEqual("none-write-command-unverified", result["submit_action"])
        # A command that failed to report does not prove zero side effects.
        self.assertFalse(result["retry_safe"])
        self.assertEqual(AGENTTUI.EXIT_UNCERTAIN_DELIVERY, status)
        self.assertEqual([], transport.keys)
        self.assertIn("do not resend", warnings)

    def test_a_submit_command_that_never_reports_back_is_distinguishable(self) -> None:
        transport = FakeTransport()
        transport.submit_timeouts = 1
        self.scripted_activity("idle")

        status, result, _warnings = self.send(transport, activity="idle")

        self.assertEqual(
            AGENTTUI.DELIVERY_SUBMIT_COMMAND_UNVERIFIED, result["delivery"]
        )
        self.assertNotEqual(
            AGENTTUI.DELIVERY_WRITE_UNVERIFIED, result["delivery"]
        )
        self.assertEqual(AGENTTUI.EXIT_UNCERTAIN_DELIVERY, status)
        self.assertEqual(1, len(transport.writes))

    def test_unknown_turn_state_after_the_write_sends_no_key_at_all(self) -> None:
        # The text is already in the composer, so guessing a key is the one thing
        # that cannot be undone. Recovering that text is the caller's job.
        transport = FakeTransport()
        self.scripted_activity(None)

        status, result, warnings = self.send(transport, activity="idle")

        self.assertEqual(AGENTTUI.DELIVERY_COMPOSER_UNSUBMITTED, result["delivery"])
        self.assertEqual("none-post-write-unknown", result["submit_action"])
        self.assertEqual([], transport.keys)
        self.assertEqual(1, len(transport.writes))
        self.assertEqual(AGENTTUI.EXIT_UNCERTAIN_DELIVERY, status)
        self.assertEqual(
            "recover-existing-composer-do-not-rewrite", result["recommended_action"]
        )
        self.assertIn("unsubmitted in the composer", warnings)

    def test_a_turn_that_ends_during_the_settle_delay_switches_to_enter(self) -> None:
        # Planned as Tab while the turn was running; by key time the turn was over,
        # and Tab into an idle composer enqueues nothing.
        transport = FakeTransport()
        self.scripted_activity("idle")

        _status, result, _warnings = self.send(transport, activity="active")

        self.assertEqual([AGENTTUI.PANE_ENTER_BYTE], transport.keys[:1])
        self.assertEqual("enter-submit", result["submit_action"])
        self.assertEqual("idle", result["target_submit_activity"])

    def test_a_running_turn_is_enqueued_once_and_reported_as_queued(self) -> None:
        transport = FakeTransport()
        self.scripted_activity("active")

        status, result, warnings = self.send(transport, activity="active")

        self.assertEqual(AGENTTUI.DELIVERY_QUEUED_FOR_NEXT_TURN, result["delivery"])
        self.assertEqual("tab-queue", result["submit_action"])
        self.assertEqual([AGENTTUI.CODEX_PANE_QUEUE_BYTE], transport.keys)
        self.assertEqual(
            "early-transcript-miss-is-not-nondelivery-evidence",
            result["verification_guidance"],
        )
        self.assertIn("wait for the turn boundary", warnings)
        self.assertEqual(0, status)

    def test_an_unverified_enter_is_retried_only_while_still_idle(self) -> None:
        transport = FakeTransport()
        # idle before the key, still idle before the retry.
        self.scripted_activity("idle", "idle")

        _status, result, _warnings = self.send(transport, activity="idle")

        self.assertEqual(2, len(transport.keys))
        self.assertEqual(AGENTTUI.DELIVERY_SUBMIT_UNVERIFIED, result["delivery"])

    def test_no_second_enter_once_the_target_started_a_turn(self) -> None:
        # A second Enter would steer the turn that just started.
        transport = FakeTransport()
        self.scripted_activity("idle", "active")

        _status, result, _warnings = self.send(transport, activity="idle")

        self.assertEqual(1, len(transport.keys))
        self.assertEqual(AGENTTUI.DELIVERY_SUBMIT_UNVERIFIED, result["delivery"])

    def test_no_second_enter_when_the_state_became_unreadable(self) -> None:
        transport = FakeTransport()
        self.scripted_activity("idle", None)

        _status, result, _warnings = self.send(transport, activity="idle")

        self.assertEqual(1, len(transport.keys))
        self.assertEqual(AGENTTUI.DELIVERY_SUBMIT_UNVERIFIED, result["delivery"])
        self.assertIsNone(result["target_submit_activity"])

    def test_delivery_reports_the_nonce_as_the_only_evidence(self) -> None:
        marker = f"from={SENDER} nonce={NONCE}"
        transport = FakeTransport()
        self.scripted_activity("idle")

        def append_marker(*_args, **_kwargs):
            with self.session_file.open("a", encoding="utf-8") as stream:
                stream.write(marker + "\n")
            return AGENTTUI.CommandOutcome(
                argv=["fake"], returncode=0, stdout="", stderr="", rejected=False, detail=""
            )

        transport.send_key = append_marker  # type: ignore[assignment]
        status, result, _warnings = self.send(
            transport, activity="idle", marker=marker
        )

        self.assertEqual(AGENTTUI.DELIVERY_DELIVERED, result["delivery"])
        self.assertEqual("envelope-nonce-found", result["evidence"])
        self.assertEqual("await-peer-ack", result["recommended_action"])
        # Delivery is transport entry; only a peer reply is a semantic ACK.
        self.assertFalse(result["acknowledged"])
        self.assertEqual(0, status)

    def test_every_pane_outcome_carries_the_full_action_field_set(self) -> None:
        required = {
            "delivery",
            "submit_action",
            "recommended_action",
            "verification_guidance",
            "retry_safe",
            "nonce",
            "evidence",
            "acknowledged",
            "target_submit_activity",
            "target_effective_state",
        }
        transport = FakeTransport()
        self.scripted_activity("active")

        _status, result, _warnings = self.send(transport, activity="active")

        self.assertTrue(required.issubset(result.keys()), required - result.keys())

    def test_deriving_the_turn_state_issues_no_pane_command(self) -> None:
        # Observation discipline: the reading that decides the submit key must not
        # add to the command sequence the target sees. Exactly one write and one
        # key, the same sequence as before this facility existed.
        transport = FakeTransport()
        self.scripted_activity("active")

        self.send(transport, activity="active")

        self.assertEqual(1, len(transport.writes))
        self.assertEqual(1, len(transport.keys))
        self.assertEqual(0, transport.exists_calls)


class BracketedPasteFramingTests(unittest.TestCase):
    """Shape 3's causal fix: framing, not a different multiplexer.

    Measured downstream on one Codex version: an unframed fast character stream is
    classified as a paste burst, and the submit key is then consumed as a newline
    inside that burst — mechanically idle target, both key commands returning 0,
    envelope still in the composer. Framing addresses the write *method* only; it
    must not change routing, the transport choice, or the command sequence.
    """

    def route(self, brand: str) -> "AGENTTUI.DeliveryRoute":
        return AGENTTUI.build_route(
            make_record(brand=brand, state="idle", pane_ref=pane_ref()),
            "line one\nline two",
            transports={FAKE_MUX: lambda: FakeTransport()},
            codex_submit_activity="idle" if brand == "codex" else None,
        )

    def test_a_codex_envelope_is_framed_as_one_paste(self) -> None:
        route = self.route("codex")

        self.assertTrue(route.paste_framed)
        self.assertEqual(
            f"{AGENTTUI.BRACKETED_PASTE_START}line one line two"
            f"{AGENTTUI.BRACKETED_PASTE_END}",
            route.pane_argv()[-1],
        )

    def test_claude_code_is_deliberately_left_unframed(self) -> None:
        # No measurement supports framing there, and its composer has its own
        # paste handling — so the allow-list stays narrow rather than "always".
        route = self.route("claude-code")

        self.assertFalse(route.paste_framed)
        self.assertEqual("line one line two", route.pane_argv()[-1])
        self.assertEqual({"codex"}, set(AGENTTUI.PASTE_FRAMED_BRANDS))

    def test_framing_changes_the_text_only_never_the_key_or_the_route(self) -> None:
        codex = self.route("codex")
        claude = self.route("claude-code")

        self.assertEqual(AGENTTUI.PANE_ENTER_BYTE, codex.submit_byte)
        self.assertEqual(codex.submit_byte, claude.submit_byte)
        self.assertEqual(codex.mode, claude.mode)
        self.assertEqual(claude.submit_argv(), codex.submit_argv())

    def test_the_escape_bytes_live_in_the_transport_not_in_routing(self) -> None:
        # Routing asks a capability question (paste_framed); the mechanism is the
        # transport's business, exactly like the multiplexer's command lines.
        routing_source = "".join(
            inspect.getsource(function)
            for function in (
                AGENTTUI.build_route,
                AGENTTUI.build_pane_route,
                AGENTTUI.build_resume_route,
            )
        )

        for mechanism in ("200~", "201~", "\x1b["):
            self.assertNotIn(mechanism, routing_source)

    def test_the_concrete_transport_frames_at_its_command_line(self) -> None:
        transport = AGENTTUI.ZellijTransport(
            runner=RecordingRunner(), which=lambda _name: "/placeholder/zellij"
        )

        framed = transport.write_chars_argv(pane_ref("zellij"), "body", paste_framed=True)
        plain = transport.write_chars_argv(pane_ref("zellij"), "body")

        self.assertTrue(framed[-1].startswith(AGENTTUI.BRACKETED_PASTE_START))
        self.assertTrue(framed[-1].endswith(AGENTTUI.BRACKETED_PASTE_END))
        self.assertEqual("body", plain[-1])
        # Same verb, same addressing, same command count: only the payload differs.
        self.assertEqual(framed[:-1], plain[:-1])

    def test_a_transport_may_override_the_framing_mechanism(self) -> None:
        # The abstraction owns the intent, not the escape bytes: a transport with a
        # native paste primitive must be able to use it instead.
        class NativePasteTransport(FakeTransport):
            def frame_paste(self, text: str) -> str:
                return f"<native-paste>{text}</native-paste>"

        transport = NativePasteTransport()
        route = AGENTTUI.build_route(
            make_record(brand="codex", state="idle", pane_ref=pane_ref()),
            "body",
            transports={FAKE_MUX: lambda: transport},
            codex_submit_activity="idle",
        )

        self.assertEqual("<native-paste>body</native-paste>", route.pane_argv()[-1])

    def test_framing_does_not_change_the_command_sequence(self) -> None:
        runner = RecordingRunner()
        transport = AGENTTUI.ZellijTransport(
            runner=runner, which=lambda _name: "/placeholder/zellij"
        )

        transport.write_chars(pane_ref("zellij"), "body", paste_framed=True)

        self.assertEqual(["write-chars"], runner.actions())


class FakePopen:
    """Fake detached process: scripted poll answers, records any kill attempt."""

    def __init__(self, poll_answers: list[int | None], **kwargs) -> None:
        self.kwargs = kwargs
        self.pid = 424242
        self._answers = list(poll_answers)
        self.signals: list[str] = []

    def poll(self) -> int | None:
        if not self._answers:
            return None
        answer = self._answers[0]
        if len(self._answers) > 1:
            self._answers.pop(0)
        return answer

    def kill(self) -> None:  # pragma: no cover - must never be called
        self.signals.append("kill")

    def terminate(self) -> None:  # pragma: no cover - must never be called
        self.signals.append("terminate")

    def wait(self, timeout=None) -> int:  # pragma: no cover
        self.signals.append("wait")
        return 0


class DetachedResumeTests(unittest.TestCase):
    """The resume runner carries the target's whole turn, so we must not own it.

    Running it under this process's timeout made the sender's patience the
    target's deadline: a sender-side timeout SIGKILLed a runner that was working
    correctly, aborting a turn that may already have written files or called out
    to other systems. The window here bounds observation only.
    """

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.session_file = Path(self.temporary.name) / "target-session.jsonl"
        self.session_file.write_text("existing transcript line\n", encoding="utf-8")
        self.marker = f"from={SENDER} nonce={NONCE}"
        self._poll = AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS
        AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = 0.0
        self.addCleanup(
            setattr, AGENTTUI, "PANE_VERIFY_POLL_INITIAL_SECONDS", self._poll
        )

    def append_marker(self) -> None:
        with self.session_file.open("a", encoding="utf-8") as stream:
            stream.write(self.marker + "\n")

    def send(
        self,
        poll_answers: list[int | None],
        *,
        timeout: float = 0.0,
        on_start=None,
    ):
        processes: list[FakePopen] = []

        def fake_popen(argv, **kwargs):
            process = FakePopen(poll_answers, **kwargs)
            processes.append(process)
            if on_start is not None:
                # Runs after the pre-send boundary was recorded, so anything it
                # appends counts as post-boundary evidence.
                on_start()
            return process

        route = AGENTTUI.DeliveryRoute(
            mode=AGENTTUI.ROUTE_RESUME,
            cwd=Path(self.temporary.name),
            argv=["placeholder-resume-cli", "--resume", "placeholder-id", "envelope"],
        )
        payload = {
            "target": TARGET,
            "target_brand": "claude-code",
            "target_effective_state": "idle",
            "target_session_file": str(self.session_file),
            "delivery_marker": self.marker,
            "nonce": NONCE,
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        original = AGENTTUI.subprocess.Popen
        AGENTTUI.subprocess.Popen = fake_popen
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = AGENTTUI.send_via_resume(route, payload, timeout=timeout)
        finally:
            AGENTTUI.subprocess.Popen = original
        result = json.loads(stdout.getvalue().strip().splitlines()[-1])
        return status, result, stderr.getvalue(), processes[0]

    def test_the_runner_is_started_in_its_own_process_session(self) -> None:
        _status, result, _warnings, process = self.send([None])

        self.assertTrue(process.kwargs["start_new_session"])
        self.assertEqual(AGENTTUI.subprocess.DEVNULL, process.kwargs["stdin"])
        self.assertEqual("detached-from-sender", result["execution_lifecycle"])
        self.assertEqual(process.pid, result["runner_pid"])

    def test_an_expired_observation_window_never_kills_the_runner(self) -> None:
        status, result, warnings, process = self.send([None])

        self.assertEqual(
            AGENTTUI.DELIVERY_RESUME_STARTED_UNVERIFIED, result["delivery"]
        )
        self.assertEqual([], process.signals)
        self.assertEqual("running", result["runner_state"])
        self.assertEqual(0, status)
        self.assertIn("was NOT terminated", warnings)

    def test_an_abandoned_runner_keeps_a_readable_output_path(self) -> None:
        # Not DEVNULL: for the claude-code shape the runner's stdout is the only
        # place the target's reply ever appears. Not a pipe either -- an abandoned
        # runner whose pipe buffer filled would block inside the target's turn.
        _status, result, _warnings, _process = self.send([None])

        output_path = Path(result["runner_output_path"])
        self.addCleanup(output_path.unlink, True)
        self.assertTrue(output_path.exists())
        self.assertEqual(0o600, output_path.stat().st_mode & 0o777)

    def test_the_nonce_is_the_delivery_evidence_here_too(self) -> None:
        status, result, _warnings, process = self.send([None], on_start=self.append_marker)

        self.assertEqual(AGENTTUI.DELIVERY_DELIVERED, result["delivery"])
        self.assertEqual("envelope-nonce-found", result["evidence"])
        self.assertEqual([], process.signals)
        self.assertEqual(0, status)

    def test_delivery_does_not_claim_the_target_turn_finished(self) -> None:
        _status, result, _warnings, _process = self.send([None], on_start=self.append_marker)

        self.assertEqual("unverified", result["task_completion"])
        self.assertEqual("not-observed", result["target_turn_outcome"])
        self.assertFalse(result["acknowledged"])

    def test_a_runner_exit_before_the_nonce_is_its_own_outcome(self) -> None:
        status, result, warnings, _process = self.send([0])

        self.assertEqual(
            AGENTTUI.DELIVERY_RESUME_EXITED_UNVERIFIED, result["delivery"]
        )
        self.assertEqual("exited", result["runner_state"])
        self.assertEqual(0, result["runner_returncode"])
        self.assertEqual(AGENTTUI.EXIT_UNCERTAIN_DELIVERY, status)
        self.assertFalse(result["retry_safe"])
        self.assertIn("does not prove the target had no side", warnings)

    def test_a_runner_exit_cleans_up_its_capture_file(self) -> None:
        _status, result, _warnings, _process = self.send([0])

        self.assertIsNone(result["runner_output_path"])

    def test_a_transcript_append_racing_the_exit_is_still_counted(self) -> None:
        # The runner can exit between the last poll and the transcript flush, so
        # one final message-specific reading happens after the exit is seen.
        checks: list[int] = []
        original = AGENTTUI.transcript_contains_marker

        def fake(path, marker, start_offset):
            checks.append(1)
            return len(checks) >= 2

        AGENTTUI.transcript_contains_marker = fake
        self.addCleanup(setattr, AGENTTUI, "transcript_contains_marker", original)

        _status, result, _warnings, _process = self.send([0])

        self.assertEqual(AGENTTUI.DELIVERY_DELIVERED, result["delivery"])
        self.assertEqual(2, len(checks))

    def test_the_observation_window_is_bounded_by_the_callers_timeout(self) -> None:
        # A fake clock only advances through the injected sleep, so this case needs
        # a real poll interval; setUp zeroes it for the fast cases.
        AGENTTUI.PANE_VERIFY_POLL_INITIAL_SECONDS = 0.1
        slept: list[float] = []
        now = [0.0]

        class NeverExits:
            def poll(self):
                return None

        found, returncode = AGENTTUI.observe_detached_resume(
            NeverExits(),
            self.session_file,
            "marker-absent",
            0,
            2.0,
            monotonic=lambda: now[0],
            sleep=lambda seconds: (slept.append(seconds), now.__setitem__(0, now[0] + seconds)),
        )

        self.assertFalse(found)
        self.assertIsNone(returncode)
        self.assertAlmostEqual(2.0, sum(slept), places=6)

    def test_no_code_path_here_can_signal_the_runner(self) -> None:
        # Mechanical: the whole point is that this process never ends the target's
        # turn, so the resume path must contain no termination call at all.
        source = "".join(
            inspect.getsource(function)
            for function in (AGENTTUI.send_via_resume, AGENTTUI.observe_detached_resume)
        )

        for forbidden in (".kill(", ".terminate(", ".send_signal(", "os.killpg"):
            self.assertNotIn(forbidden, source)


class ProbeReturnCodeTests(unittest.TestCase):
    """rc=2 means "the requested focus change did not happen" -- two opposite causes.

    Measured on one multiplexer version: the probe answers rc=2 both for a pane
    that does not exist and for a pane that is *already focused*. The second is
    positive existence evidence and is the state a verified-successful delivery
    was in, so rejecting on a non-zero code would refuse the healthiest case.
    Only not-found text may reject.
    """

    def outcome(self, returncode: int, stderr: str, stdout: str = ""):
        runner = RecordingRunner([FakeCompleted(returncode, stdout, stderr)])
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _n: "/x/zellij")
        return transport.exists(pane_ref("zellij"))

    def test_already_focused_is_not_a_rejection(self) -> None:
        capability = self.outcome(2, "Pane Terminal(6) is already focused")

        self.assertTrue(capability.ok)

    def test_missing_pane_is_a_rejection_despite_the_same_return_code(self) -> None:
        capability = self.outcome(2, "Pane with id Terminal(9999) not found")

        self.assertFalse(capability.ok)

    def test_successful_focus_is_silent_and_passes(self) -> None:
        capability = self.outcome(0, "")

        self.assertTrue(capability.ok)

    def test_missing_session_diagnostic_on_stderr_is_still_caught(self) -> None:
        # stdout carries ordinary content (a session list) while the diagnostic is
        # on stderr, so a stdout-only judgement would pass this.
        capability = self.outcome(
            0, "Session 'absent' not found. The following sessions are active:",
            stdout="some-session [Created 1h ago]\n",
        )

        self.assertFalse(capability.ok)

    def test_already_focused_is_absent_from_the_rejection_patterns(self) -> None:
        joined = " ".join(p.pattern for p in AGENTTUI.ZELLIJ_NOT_FOUND_PATTERNS)

        self.assertNotIn("focused", joined)



class FocusIntrusionCounterTests(unittest.TestCase):
    """The probe's own answer says whether this delivery stole someone's focus.

    rc=0 means the focus actually moved (a human watching another pane lost their
    view); rc=2 with "already focused" means the target was already there and
    nobody was disturbed. Recording it per delivery turns an architectural cost
    into a measurable rate -- the denominator for whether that cost justifies
    changing transports -- with no new experiment and no interruption.
    """

    def transport(self, returncode: int, stderr: str, stdout: str = ""):
        runner = RecordingRunner([FakeCompleted(returncode, stdout, stderr)])
        return AGENTTUI.ZellijTransport(runner=runner, which=lambda _n: "/x/zellij")

    def test_moved_focus_is_recorded_as_intrusive(self) -> None:
        transport = self.transport(0, "")

        capability = transport.exists(pane_ref("zellij"))

        self.assertTrue(capability.ok)
        self.assertEqual(
            AGENTTUI.INTRUSION_FOCUS_MOVED, transport.addressing_intrusion()
        )
        self.assertIn("lost their view", capability.detail)

    def test_already_focused_is_recorded_as_non_intrusive(self) -> None:
        transport = self.transport(2, "Pane Terminal(6) is already focused")

        capability = transport.exists(pane_ref("zellij"))

        self.assertTrue(capability.ok)
        self.assertEqual(AGENTTUI.INTRUSION_NONE, transport.addressing_intrusion())

    def test_unreachable_pane_reports_no_intrusion_value_at_all(self) -> None:
        # Not "none": nothing was delivered, so counting it as an undisturbed
        # delivery would pad the denominator and understate the real rate.
        transport = self.transport(2, "Pane with id Terminal(9999) not found")

        capability = transport.exists(pane_ref("zellij"))

        self.assertFalse(capability.ok)
        self.assertIsNone(transport.addressing_intrusion())

    def test_unexpected_nonzero_answer_is_unknown_not_assumed_harmless(self) -> None:
        transport = self.transport(3, "some unfamiliar diagnostic")

        transport.exists(pane_ref("zellij"))

        self.assertEqual(AGENTTUI.INTRUSION_UNKNOWN, transport.addressing_intrusion())

    def test_before_any_probe_the_answer_is_unknown_by_absence(self) -> None:
        transport = self.transport(0, "")

        self.assertIsNone(transport.addressing_intrusion())

    def test_the_abstract_transport_refuses_to_guess(self) -> None:
        # A transport that cannot tell must return None, never "none".
        self.assertIsNone(AGENTTUI.PaneTransport().addressing_intrusion())



class ObservationRecordingTests(unittest.TestCase):
    """Events, never rates -- and the measurement must not perturb non-measurers.

    Two measured hazards drive this shape. A ratio looks *cleanest* in the burst
    traffic that disturbs a human most, because the probe itself pulls the pane
    into focus and every following send to it then reads "already focused". And an
    aggregate hides the stratification that carries the whole question. So each
    delivery emits one event with its own context and folding is left to analysis.
    """

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.log = Path(self.temporary.name) / "nested" / "focus.jsonl"

    def transport(self, layout_before: str, layout_after: str, *, probe_rc: int = 0,
                  probe_stderr: str = "", observe: bool = True):
        outcomes = [
            FakeCompleted(0, layout_before, ""),
            FakeCompleted(probe_rc, "", probe_stderr),
            FakeCompleted(0, layout_after, ""),
        ]
        if not observe:
            outcomes = [FakeCompleted(probe_rc, "", probe_stderr)]
        runner = RecordingRunner(outcomes)
        transport = AGENTTUI.ZellijTransport(runner=runner, which=lambda _n: "/x/z")
        transport.observe_addressing = observe
        return transport, runner

    @staticmethod
    def layout(focused_tab: str) -> str:
        return (
            'layout {\n    tab name="Other" hide_floating_panes=true {\n'
            '        pane\n    }\n'
            f'    tab name="{focused_tab}" focus=true hide_floating_panes=true {{\n'
            '        pane focus=true\n    }\n'
            "    swap_tiled_layout name=\"vertical\" {\n        tab max_panes=5 {\n"
            "            pane\n        }\n    }\n}\n"
        )

    def test_a_tab_switch_is_recorded_as_the_strongest_disturbance(self) -> None:
        transport, _runner = self.transport(self.layout("Mine"), self.layout("Theirs"))

        transport.exists(pane_ref("zellij"))
        observation = transport.addressing_observation()

        self.assertEqual("Mine", observation["active_tab_before"])
        self.assertEqual("Theirs", observation["active_tab_after"])
        self.assertTrue(observation["tab_switched"])

    def test_same_tab_is_recorded_as_no_switch(self) -> None:
        transport, _runner = self.transport(self.layout("Mine"), self.layout("Mine"))

        transport.exists(pane_ref("zellij"))

        self.assertFalse(transport.addressing_observation()["tab_switched"])

    def test_an_unreadable_layout_is_unknown_not_no_switch(self) -> None:
        # None, never False: a missing reading must not be reported as "nothing
        # happened", which is the direction that understates the real rate.
        transport, _runner = self.transport("no tabs here", self.layout("Mine"))

        transport.exists(pane_ref("zellij"))
        observation = transport.addressing_observation()

        self.assertIsNone(observation["active_tab_before"])
        self.assertIsNone(observation["tab_switched"])

    def test_swap_layout_templates_are_not_mistaken_for_tabs(self) -> None:
        transport, _runner = self.transport(self.layout("Real"), self.layout("Real"))

        transport.exists(pane_ref("zellij"))

        self.assertEqual("Real", transport.addressing_observation()["active_tab_before"])

    def test_not_observing_issues_no_extra_commands(self) -> None:
        # The regression that matters for everyone else: a caller who is not
        # recording observations must see exactly the old command sequence.
        transport, runner = self.transport("", "", observe=False)

        transport.exists(pane_ref("zellij"))

        self.assertEqual(1, len(runner.calls))
        observation = transport.addressing_observation()
        # Still reported, still as unknown -- absence would read as "no switch".
        self.assertIsNone(observation["active_tab_before"])
        self.assertIsNone(observation["tab_switched"])

    def test_observation_is_appended_and_private(self) -> None:
        AGENTTUI.append_observation({"intrusion": "focus-moved"}, self.log)
        AGENTTUI.append_observation({"intrusion": "already-focused"}, self.log)

        lines = self.log.read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(2, len(lines))
        self.assertEqual("focus-moved", json.loads(lines[0])["intrusion"])
        self.assertEqual(0o600, self.log.stat().st_mode & 0o777)

    def test_no_log_path_records_nothing(self) -> None:
        AGENTTUI.append_observation({"intrusion": "focus-moved"}, None)

        self.assertFalse(self.log.exists())

    def test_a_failed_write_never_costs_the_delivery(self) -> None:
        unwritable = Path(self.temporary.name) / "as-a-file" / "focus.jsonl"
        unwritable.parent.write_text("not a directory", encoding="utf-8")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            AGENTTUI.append_observation({"intrusion": "focus-moved"}, unwritable)

        self.assertIn("delivery itself is unaffected", stderr.getvalue())

    def test_the_script_computes_no_intrusion_rate_anywhere(self) -> None:
        # Pins the "events only" decision mechanically: a ratio computed in this
        # script would be systematically wrong in both directions described above.
        source = Path(ROOT / "overlay/scripts/agenttui.py").read_text(encoding="utf-8")

        for forbidden in ("intrusion_rate", "focus_moved_ratio", "intrusion_percent"):
            self.assertNotIn(forbidden, source)


class TmuxTransportTests(unittest.TestCase):
    """The second pane transport: directed writes, and a read-only probe.

    Every reading behind these cases was measured on a private detached tmux
    server, never on anyone's terminal. No real multiplexer is involved here
    either: the runner is faked at the same seam as the other transport's tests.
    """

    def transport(self, outcomes: list[FakeCompleted] | None = None):
        runner = RecordingRunner(outcomes)
        transport = AGENTTUI.TmuxTransport(
            runner=runner, which=lambda _name: "/placeholder/tmux"
        )
        return transport, runner

    @staticmethod
    def listing(session: str = PANE_SESSION, pane: str = PANE_ID) -> str:
        # Shape of `list-panes -F '#{session_name}\t#{pane_id}'`: one line per pane
        # in the addressed window (placeholders only, never observed values).
        return f"{session}\tplaceholder-other-pane\n{session}\t{pane}\n"

    def test_the_probe_is_read_only_and_never_a_property_read(self) -> None:
        transport, _runner = self.transport()

        probe = transport.probe_argv(pane_ref("tmux"))

        self.assertIn("list-panes", probe)
        # Measured rc=0 for a missing target while silently falling back to the
        # *current* pane -- the same shape of trap as the other transport's screen
        # dump, so it may never be the existence criterion.
        self.assertNotIn("display-message", probe)

    def test_no_command_this_transport_can_issue_moves_the_focus(self) -> None:
        # The substantive advantage over a focus-addressed transport: the probe
        # does not have to be the focus command, so preflight disturbs nobody.
        transport, _runner = self.transport()
        reference = pane_ref("tmux")

        commands = [
            transport.probe_argv(reference),
            transport.write_chars_argv(reference, "body"),
            transport.send_key_argv(reference, AGENTTUI.PANE_ENTER_BYTE),
        ]

        for argv in commands:
            for forbidden in ("select-pane", "select-window", "focus"):
                self.assertNotIn(forbidden, " ".join(argv))

    def test_the_only_property_read_is_a_self_query_without_a_target(self) -> None:
        # Mechanical: the banned command appears exactly once in the transport, in
        # the self-query, and that call site passes no target.
        source = inspect.getsource(AGENTTUI.TmuxTransport._own_session)
        whole = inspect.getsource(AGENTTUI.TmuxTransport)

        self.assertIn("display-message", source)
        self.assertNotIn('"-t"', source)
        self.assertEqual(1, whole.count('"display-message"'))

    def test_a_missing_pane_is_refused_with_zero_injection_commands(self) -> None:
        transport, runner = self.transport(
            [FakeCompleted(returncode=1, stderr="can't find pane: %placeholder\n")]
        )
        target = make_record(pane_ref=pane_ref("tmux"))

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            AGENTTUI.build_route(
                target,
                "envelope",
                transports={"tmux": lambda: transport},
                codex_submit_activity="idle",
            )

        self.assertEqual("pane-not-reachable", caught.exception.reason)
        self.assertEqual(1, len(runner.calls))
        self.assertIn("list-panes", runner.calls[0])

    def test_the_text_decides_even_though_this_transport_exits_non_zero(self) -> None:
        # rc is more trustworthy here than on the other transport, but it is still
        # not the criterion: one tmux command answers rc=0 for a missing target.
        transport, _runner = self.transport(
            [FakeCompleted(returncode=0, stderr="can't find pane: %placeholder\n")]
        )

        capability = transport.exists(pane_ref("tmux"))

        self.assertFalse(capability.ok)
        self.assertIn("can't find pane", capability.detail)

    def test_a_missing_server_is_an_addressing_failure_too(self) -> None:
        transport, _runner = self.transport(
            [
                FakeCompleted(
                    returncode=1,
                    stderr="no server running on /placeholder/socket\n",
                )
            ]
        )

        self.assertFalse(transport.exists(pane_ref("tmux")).ok)

    def test_a_non_zero_code_alone_never_decides_reachability(self) -> None:
        transport, _runner = self.transport(
            [FakeCompleted(returncode=1, stdout="", stderr="some unfamiliar text")]
        )

        capability = transport.exists(pane_ref("tmux"))

        # Refused -- but for the listing, not for the exit code: the probe simply
        # never said anything about the addressed pane.
        self.assertFalse(capability.ok)
        self.assertIn("not among the panes", capability.detail)

    def test_a_listed_pane_in_the_registered_session_is_reachable(self) -> None:
        transport, runner = self.transport([FakeCompleted(stdout=self.listing())])

        capability = transport.exists(pane_ref("tmux"))

        self.assertTrue(capability.ok)
        self.assertEqual(1, len(runner.calls))
        self.assertEqual(
            AGENTTUI.INTRUSION_NO_FOCUS_COMMAND, transport.addressing_intrusion()
        )

    def test_a_session_name_disagreement_is_refused_as_a_rotted_handle(self) -> None:
        # Addressing by pane id would have worked; a pane_ref whose fields
        # disagree with reality has rotted, and delivering anyway is how an
        # envelope lands in a stranger's composer.
        transport, _runner = self.transport(
            [FakeCompleted(stdout=self.listing(session="placeholder-renamed"))]
        )

        capability = transport.exists(pane_ref("tmux"))

        self.assertFalse(capability.ok)
        self.assertIn("rebuilt in full", capability.detail)
        self.assertIn("not patched field by field", capability.detail)

    def test_an_answer_that_omits_the_target_is_not_evidence_of_it(self) -> None:
        transport, _runner = self.transport(
            [FakeCompleted(stdout=f"{PANE_SESSION}\tplaceholder-other-pane\n")]
        )

        self.assertFalse(transport.exists(pane_ref("tmux")).ok)

    def test_an_unreachable_pane_records_no_intrusion_value(self) -> None:
        transport, _runner = self.transport(
            [FakeCompleted(returncode=1, stderr="can't find pane: %placeholder\n")]
        )

        transport.exists(pane_ref("tmux"))

        self.assertIsNone(transport.addressing_intrusion())

    def test_a_read_only_probe_is_not_recorded_as_already_focused(self) -> None:
        # "Nobody was disturbed because no focus command exists" and "the target
        # happened to be focused already" are different facts; merging them would
        # let a structural property hide inside the same denominator as a lucky
        # reading, which is exactly the question a migration decision asks.
        transport, _runner = self.transport([FakeCompleted(stdout=self.listing())])

        transport.exists(pane_ref("tmux"))

        self.assertNotEqual(AGENTTUI.INTRUSION_NONE, transport.addressing_intrusion())
        self.assertEqual(
            "no-focus-command-issued", AGENTTUI.INTRUSION_NO_FOCUS_COMMAND
        )

    def test_the_window_switch_reading_stays_unknown_rather_than_false(self) -> None:
        # Measured on a server with no client attached, so "an attached human is
        # undisturbed" is NOT verified. None means unknown; False would claim it.
        transport, _runner = self.transport([FakeCompleted(stdout=self.listing())])

        transport.exists(pane_ref("tmux"))
        observation = transport.addressing_observation()

        self.assertIsNone(observation["tab_switched"])
        self.assertFalse(observation["probe_is_focus_command"])
        self.assertEqual(PANE_SESSION, observation["observed_pane_session"])

    def test_not_observing_issues_no_extra_commands(self) -> None:
        transport, runner = self.transport([FakeCompleted(stdout=self.listing())])

        transport.exists(pane_ref("tmux"))

        self.assertEqual(1, len(runner.calls))
        self.assertIsNone(
            transport.addressing_observation()["same_multiplexer_session"]
        )

    def test_observing_adds_the_self_query_and_stratifies_the_event(self) -> None:
        transport, runner = self.transport(
            [
                FakeCompleted(stdout=self.listing()),
                FakeCompleted(stdout=f"{PANE_SESSION}\n"),
            ]
        )
        transport.observe_addressing = True
        original = AGENTTUI.os.environ.get("TMUX_PANE")
        AGENTTUI.os.environ["TMUX_PANE"] = "%placeholder-own-pane"
        self.addCleanup(
            lambda: (
                AGENTTUI.os.environ.__setitem__("TMUX_PANE", original)
                if original is not None
                else AGENTTUI.os.environ.pop("TMUX_PANE", None)
            )
        )

        transport.exists(pane_ref("tmux"))

        self.assertEqual(2, len(runner.calls))
        self.assertIn("display-message", runner.calls[1])
        self.assertTrue(
            transport.addressing_observation()["same_multiplexer_session"]
        )

    def test_outside_the_multiplexer_the_self_query_is_skipped(self) -> None:
        # No self-identification handle means the answer is unknown, and asking
        # anyway would add a command for a caller who cannot use the reading.
        transport, runner = self.transport([FakeCompleted(stdout=self.listing())])
        transport.observe_addressing = True
        original = AGENTTUI.os.environ.pop("TMUX_PANE", None)
        if original is not None:
            self.addCleanup(AGENTTUI.os.environ.__setitem__, "TMUX_PANE", original)

        transport.exists(pane_ref("tmux"))

        self.assertEqual(1, len(runner.calls))
        self.assertIsNone(
            transport.addressing_observation()["same_multiplexer_session"]
        )

    def test_text_is_written_literally_and_framing_only_wraps_the_payload(self) -> None:
        transport, _runner = self.transport()
        reference = pane_ref("tmux")

        plain = transport.write_chars_argv(reference, "body")
        framed = transport.write_chars_argv(reference, "body", paste_framed=True)

        self.assertEqual(
            ["tmux", "send-keys", "-t", PANE_ID, "-l", "body"], plain
        )
        self.assertTrue(framed[-1].startswith(AGENTTUI.BRACKETED_PASTE_START))
        self.assertTrue(framed[-1].endswith(AGENTTUI.BRACKETED_PASTE_END))
        # Same verb, same addressing, same command count: only the payload differs.
        self.assertEqual(plain[:-1], framed[:-1])

    def test_the_submit_key_is_sent_as_the_contract_byte_not_a_key_name(self) -> None:
        # A key *name* would go through this multiplexer's key encoding, and an
        # extended-keys configuration can change what Enter looks like on the wire.
        transport, _runner = self.transport()
        reference = pane_ref("tmux")

        enter = transport.send_key_argv(reference, AGENTTUI.PANE_ENTER_BYTE)
        queue = transport.send_key_argv(reference, AGENTTUI.CODEX_PANE_QUEUE_BYTE)

        self.assertEqual(["tmux", "send-keys", "-t", PANE_ID, "-H", "0d"], enter)
        self.assertEqual("09", queue[-1])
        self.assertNotIn("Enter", enter)

    def test_a_key_that_is_not_a_byte_is_refused_rather_than_guessed(self) -> None:
        transport, _runner = self.transport()

        with self.assertRaises(AGENTTUI.RegistryError):
            transport.send_key_argv(pane_ref("tmux"), "Enter")
        with self.assertRaises(AGENTTUI.RegistryError):
            transport.send_key_argv(pane_ref("tmux"), "999")

    def test_an_unavailable_cli_is_refused_before_any_probe(self) -> None:
        runner = RecordingRunner()
        transport = AGENTTUI.TmuxTransport(runner=runner, which=lambda _name: None)
        target = make_record(pane_ref=pane_ref("tmux"))

        with self.assertRaises(AGENTTUI.NoOperationalRoute) as caught:
            AGENTTUI.build_route(
                target, "envelope", transports={"tmux": lambda: transport}
            )

        self.assertEqual("pane-transport-unavailable", caught.exception.reason)
        self.assertEqual([], runner.calls)

    def test_the_route_takes_its_command_lines_from_this_transport(self) -> None:
        transport, _runner = self.transport([FakeCompleted(stdout=self.listing())])

        route = AGENTTUI.build_route(
            make_record(brand="codex", pane_ref=pane_ref("tmux")),
            "envelope",
            transports={"tmux": lambda: transport},
            codex_submit_activity="idle",
        )

        self.assertEqual(AGENTTUI.ROUTE_PANE, route.mode)
        self.assertEqual("tmux", route.transport.name)
        self.assertEqual("send-keys", route.pane_argv()[1])
        self.assertEqual("0d", route.submit_argv()[-1])


class PaneRefSocketDimensionTests(unittest.TestCase):
    """`pane_ref.socket` — which multiplexer *server* the pane id belongs to.

    A pane id can be unique only within one server, so without this dimension a
    pane_ref names a pane *number*, not a pane: on a machine running several
    servers, a same-numbered pane on the default server whose session name also
    matched would pass every check and the envelope would land in an uninvolved
    session's composer, silently.
    """

    SOCKET_NAME = "placeholder-socket"
    SOCKET_PATH = "/placeholder/dir/placeholder.sock"

    def transport(self, outcomes: list[FakeCompleted] | None = None):
        runner = RecordingRunner(outcomes)
        transport = AGENTTUI.TmuxTransport(
            runner=runner, which=lambda _name: "/placeholder/tmux"
        )
        return transport, runner

    def test_a_socket_name_and_a_socket_path_pick_different_options(self) -> None:
        # The value's own shape decides, which is the distinction the multiplexer's
        # own two options draw -- so no second schema field is needed and no single
        # value can mean both.
        transport, _runner = self.transport()

        by_name = transport.socket_argv({"socket": self.SOCKET_NAME})
        by_path = transport.socket_argv({"socket": self.SOCKET_PATH})

        self.assertEqual(["-L", self.SOCKET_NAME], by_name)
        self.assertEqual(["-S", self.SOCKET_PATH], by_path)

    def test_an_absent_socket_leaves_the_command_line_byte_identical(self) -> None:
        # Backward compatibility, mechanically: a pane_ref written before this
        # field existed must produce exactly the commands it produced before.
        transport, _runner = self.transport()
        without = pane_ref("tmux")

        self.assertEqual([], transport.socket_argv(without))
        self.assertEqual([], transport.socket_argv({"socket": "   "}))
        self.assertEqual(
            ["tmux", "send-keys", "-t", PANE_ID, "-l", "body"],
            transport.write_chars_argv(without, "body"),
        )
        self.assertEqual(
            ["tmux", "list-panes", "-t", PANE_ID, "-F", AGENTTUI.TMUX_PANE_LISTING_FORMAT],
            transport.probe_argv(without),
        )

    def test_every_command_addresses_the_socket_the_pane_ref_names(self) -> None:
        # Including the *probe*: a preflight on another server would be a question
        # about a different pane that happens to carry the same number.
        transport, _runner = self.transport()
        reference = dict(pane_ref("tmux"), socket=self.SOCKET_NAME)

        for argv in (
            transport.probe_argv(reference),
            transport.write_chars_argv(reference, "body"),
            transport.send_key_argv(reference, AGENTTUI.PANE_ENTER_BYTE),
        ):
            self.assertEqual(["tmux", "-L", self.SOCKET_NAME], argv[:3])

    def test_the_probe_runs_against_the_named_socket(self) -> None:
        transport, runner = self.transport(
            [FakeCompleted(stdout=f"{PANE_SESSION}\t{PANE_ID}\n")]
        )
        reference = dict(pane_ref("tmux"), socket=self.SOCKET_NAME)

        self.assertTrue(transport.exists(reference).ok)
        self.assertEqual(["tmux", "-L", self.SOCKET_NAME], runner.calls[0][:3])

    def test_the_schema_accepts_an_optional_socket_and_refuses_a_blank_one(self) -> None:
        # Optional, but *validated* when present: a blank socket would quietly
        # fall back to the default server, which is the silent mis-delivery this
        # field exists to prevent.
        with TemporaryDirectory() as raw:
            repo = Path(raw)
            leaf = repo / ".arborist" / "agents" / TARGET
            leaf.mkdir(parents=True)
            (repo / ".trellis").mkdir()
            (leaf / "spec.json").write_text(
                json.dumps(
                    {
                        "name": TARGET,
                        "brand": "codex",
                        "role": "impler",
                        "project": {
                            "path": str(repo),
                            "project_id": "placeholder-project",
                        },
                    }
                ),
                encoding="utf-8",
            )

            def write_runtime(socket_value: object, *, omit: bool = False) -> None:
                reference: dict[str, object] = {
                    "multiplexer": "tmux",
                    "session": PANE_SESSION,
                    "pane_id": PANE_ID,
                }
                if not omit:
                    reference["socket"] = socket_value
                (leaf / "runtime.json").write_text(
                    json.dumps(
                        {
                            "session_id": "placeholder-session-id",
                            "session_file": str(repo / "placeholder.jsonl"),
                            "state": "active",
                            "last_seen": "2000-01-01T00:00:00+00:00",
                            "pane_ref": reference,
                        }
                    ),
                    encoding="utf-8",
                )

            write_runtime(self.SOCKET_NAME)
            record = AGENTTUI.load_agent(repo, TARGET)
            assert record.pane_ref is not None
            self.assertEqual(self.SOCKET_NAME, record.pane_ref["socket"])

            write_runtime(None, omit=True)
            record = AGENTTUI.load_agent(repo, TARGET)
            assert record.pane_ref is not None
            self.assertNotIn("socket", record.pane_ref)

            write_runtime("")
            with self.assertRaises(AGENTTUI.RegistryError):
                AGENTTUI.load_agent(repo, TARGET)

    def test_the_socket_never_hides_in_the_session_field(self) -> None:
        # Stuffing a socket into `session` costs nothing today and misleads every
        # later reader, including the session cross-check that catches a rotted
        # handle. Mechanically: the session field is read as a session name only.
        transport, _runner = self.transport(
            [FakeCompleted(stdout=f"{self.SOCKET_NAME}\t{PANE_ID}\n")]
        )
        reference = dict(pane_ref("tmux"), socket=self.SOCKET_NAME)

        capability = transport.exists(reference)

        self.assertFalse(capability.ok)
        self.assertIn("rebuilt in full", capability.detail)

    def test_normalisation_agrees_with_the_validator_implementation(self) -> None:
        # Two copies, one answer: the socket normalisation decides both what the
        # transport addresses and what the validator calls a collision, and two
        # different rules there would let a real conflict pass unreported.
        validator = load_script_module(
            "overlay/scripts/validate_agenttui_registry.py",
            "validate_agenttui_registry_socket_agreement",
        )
        self.assertEqual(
            AGENTTUI.PANE_REF_DEFAULT_SOCKET, validator.PANE_REF_DEFAULT_SOCKET
        )
        for value in (None, "", "   ", "default", " socket-one ", self.SOCKET_PATH):
            self.assertEqual(
                AGENTTUI.normalize_pane_ref_socket(value),
                validator.normalize_pane_ref_socket(value),
                value,
            )

    def test_a_different_server_settles_same_session_without_comparing_names(
        self,
    ) -> None:
        # Two servers can each hold a session of the same name, so comparing names
        # across servers would answer "same session" about two panes that cannot
        # see each other. Unknown stays None; only a definite difference is False.
        transport, _runner = self.transport(
            [FakeCompleted(stdout=f"{PANE_SESSION}\t{PANE_ID}\n")]
        )
        transport.observe_addressing = True
        original = AGENTTUI.os.environ.get("TMUX")
        AGENTTUI.os.environ["TMUX"] = "/placeholder/other.sock,1,0"
        self.addCleanup(
            lambda: (
                AGENTTUI.os.environ.__setitem__("TMUX", original)
                if original is not None
                else AGENTTUI.os.environ.pop("TMUX", None)
            )
        )

        transport.exists(dict(pane_ref("tmux"), socket=self.SOCKET_PATH))
        observation = transport.addressing_observation()

        self.assertFalse(observation["same_multiplexer_server"])
        self.assertFalse(observation["same_multiplexer_session"])
        self.assertEqual(self.SOCKET_PATH, observation["addressed_socket"])

    def test_a_socket_name_against_a_socket_path_stays_unknown(self) -> None:
        # Turning a name into a path needs the socket directory and uid of whoever
        # wrote the leaf. Unknown is reported as None rather than resolved by a
        # guess -- a wrong same-server assumption is the silent mis-delivery.
        transport, _runner = self.transport(
            [FakeCompleted(stdout=f"{PANE_SESSION}\t{PANE_ID}\n")]
        )
        transport.observe_addressing = True
        original = AGENTTUI.os.environ.get("TMUX")
        AGENTTUI.os.environ["TMUX"] = "/placeholder/other.sock,1,0"
        self.addCleanup(
            lambda: (
                AGENTTUI.os.environ.__setitem__("TMUX", original)
                if original is not None
                else AGENTTUI.os.environ.pop("TMUX", None)
            )
        )

        transport.exists(dict(pane_ref("tmux"), socket=self.SOCKET_NAME))

        self.assertIsNone(
            transport.addressing_observation()["same_multiplexer_server"]
        )

    def test_the_server_reading_costs_no_command(self) -> None:
        # It comes from an environment variable this process already holds, so
        # recording it adds no observation of the target.
        transport, runner = self.transport(
            [FakeCompleted(stdout=f"{PANE_SESSION}\t{PANE_ID}\n")]
        )

        transport.exists(dict(pane_ref("tmux"), socket=self.SOCKET_PATH))

        self.assertEqual(1, len(runner.calls))
        self.assertIsNone(
            transport.addressing_observation()["same_multiplexer_server"]
        )


class TmuxContractWordingTests(unittest.TestCase):
    """The measured tmux trap and the rule-5 downgrade must be written down.

    A transport whose readings live only in code is a transport the next person
    re-derives by experiment -- on someone's real terminal.
    """

    @staticmethod
    def guide() -> str:
        return (ROOT / "overlay/spec/guides/agenttui-registry.md").read_text(
            encoding="utf-8"
        )

    def test_the_forbidden_property_read_is_named_in_the_guide(self) -> None:
        guide = self.guide()

        self.assertIn("display-message -p -t", guide)
        self.assertIn("list-panes -t", guide)

    def test_the_two_traps_are_stated_as_one_general_lesson(self) -> None:
        # Each multiplexer has a "most natural property read" command, and that is
        # exactly the one that falls back silently with rc=0. The point is the
        # generalisation, not two isolated anecdotes.
        guide = self.guide()

        self.assertIn("同名命令同语义", guide)
        self.assertIn("静默回落", guide)

    def test_rule_five_downgrade_is_scoped_to_this_transport_only(self) -> None:
        guide = self.guide()

        self.assertIn("从**必需**降为**优化**", guide)
        # And the code must not act on the downgrade: the contract is transport
        # neutral, and the downgrade holds for one transport only.
        preflight_source = inspect.getsource(AGENTTUI.build_pane_route)
        self.assertIn("if preflight:", preflight_source)
        for transport_name in AGENTTUI.TRANSPORTS:
            self.assertNotIn(transport_name, preflight_source)

    def test_the_multiplexer_value_domain_in_the_guide_matches_the_registry(self) -> None:
        guide = self.guide()
        row = next(
            line
            for line in guide.splitlines()
            if line.startswith("| `pane_ref`")
        )

        for transport_name in AGENTTUI.TRANSPORTS:
            self.assertIn(f"`{transport_name}`", row)
        self.assertIn("整条", row)

    def test_the_tmux_specific_gaps_stay_visible(self) -> None:
        guide = self.guide()

        # Pane ids are unique within one server, so the socket dimension and the
        # attached-client boundary both have to be written down.
        self.assertIn("socket", guide)
        self.assertIn("attach", guide)

    def test_the_socket_dimension_is_specified_and_its_misuse_forbidden(self) -> None:
        guide = self.guide()

        self.assertIn("`pane_ref.socket`", guide)
        self.assertIn("(multiplexer, socket, session, pane_id)", guide)
        # Stuffing the socket into `session` must stay explicitly forbidden: a
        # field whose name and content disagree misleads every later reader.
        self.assertIn("严禁把 socket 塞进 `session` 字段", guide)

    def test_the_residual_socket_gaps_are_listed_not_glossed(self) -> None:
        # Closing one gap must not quietly create two unlisted ones: the lexical
        # normalisation and the transports that ignore the field are both real.
        guide = self.guide()

        self.assertIn("socket 归一化是纯字面的", guide)
        self.assertIn("静默忽略", guide)

    def test_the_long_text_and_active_target_gap_stays_unverified(self) -> None:
        # This implementation touches none of that variable combination, so the
        # gap may not be upgraded by it -- and the guide must say what a valid
        # re-test needs, or "unverified" is a dead end rather than a next step.
        guide = self.guide()

        self.assertIn("**未**证任何关于长文本/活跃目标的事", guide)
        self.assertIn("长信封", guide)
        self.assertIn("逐字节比对", guide)


class SessionLifecycleWordingTests(unittest.TestCase):
    """The cleanup mechanism the guide recommends must not depend on a signal.

    The previous recommendation (`trap` a hangup signal) passed an end-to-end test
    in a script shell and failed in the real usage -- a human pasting the command
    into an interactive shell -- leaving an invisible live agent behind.
    """

    @staticmethod
    def guide() -> str:
        return (ROOT / "overlay/spec/guides/agenttui-registry.md").read_text(
            encoding="utf-8"
        )

    def test_the_recommended_mechanism_is_the_builtin_not_a_signal(self) -> None:
        guide = self.guide()

        self.assertIn("推荐手段 = 复用器内建的「最后一个客户端断开即销毁 session」", guide)
        self.assertIn("不依赖信号", guide)

    def test_the_known_cost_is_stated_next_to_the_mechanism(self) -> None:
        # A recommendation without its cost is how the previous wrong prescription
        # survived: inner detach is collateral damage, outer detach is not.
        guide = self.guide()

        self.assertIn("内层 detach 会被误伤", guide)
        self.assertIn("用外层 detach 的人不受影响", guide)

    def test_arming_the_option_without_a_client_is_forbidden(self) -> None:
        # Measured: switching it on while nothing is attached destroys the session
        # immediately, which would kill an ATUI started detached.
        guide = self.guide()

        self.assertIn("不得在建 session 时直接开", guide)
        self.assertIn("当场被销毁", guide)



class SubmitAckConsumptionTests(unittest.TestCase):
    """Rule 8 on the sender side: the ack decides whether a retry is safe.

    The transcript alone cannot separate "never submitted" from "submitted, not
    yet flushed". The old code pressed submit again in both cases, so it
    duplicated accepted messages. An ack resolves exactly that pair.
    """

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.session_file = Path(self.temporary.name) / "target.jsonl"
        self.session_file.write_text("existing line\n", encoding="utf-8")
        self._real = AGENTTUI.read_submit_ack
        self.addCleanup(setattr, AGENTTUI, "read_submit_ack", self._real)
        self._window = AGENTTUI.PANE_VERIFY_WINDOW_SECONDS
        AGENTTUI.PANE_VERIFY_WINDOW_SECONDS = 0.0
        self.addCleanup(
            setattr, AGENTTUI, "PANE_VERIFY_WINDOW_SECONDS", self._window
        )

    def fake_ack(self, status: str):
        AGENTTUI.read_submit_ack = lambda nonce, **kw: {
            "ack_status": status,
            "ack_count": 1 if status == AGENTTUI.ACK_STATUS_ACKED else 0,
            "ack_detail": "fake",
        }

    def send(self, *, brand: str = "claude-code", state: str = "idle"):
        transport = FakeTransport()
        route = AGENTTUI.DeliveryRoute(
            mode=AGENTTUI.ROUTE_PANE,
            cwd=Path(self.temporary.name),
            transport=transport,
            pane_ref=pane_ref(),
            pane_text="envelope body",
            submit_byte=AGENTTUI.PANE_ENTER_BYTE,
        )
        payload = {
            "target": TARGET,
            "target_brand": brand,
            "target_effective_state": state,
            "target_submit_activity": None,
            "target_session_file": str(self.session_file),
            "delivery_marker": "marker-never-present",
            "nonce": NONCE,
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            AGENTTUI.send_via_pane(route, payload, timeout=None, submit_delay=0.0)
        return transport, json.loads(stdout.getvalue().strip().splitlines()[-1])

    def test_an_ack_suppresses_the_second_submit(self) -> None:
        # The regression that matters: an accepted-but-unflushed envelope must
        # not be submitted twice.
        self.fake_ack(AGENTTUI.ACK_STATUS_ACKED)

        transport, result = self.send()

        self.assertEqual(1, len(transport.keys))
        self.assertEqual(AGENTTUI.DELIVERY_SUBMIT_UNVERIFIED, result["delivery"])
        self.assertEqual(AGENTTUI.ACK_STATUS_ACKED, result["ack_status"])

    def test_no_ack_still_allows_the_documented_retry(self) -> None:
        # Absence must not *block* the retry either -- it is unconfirmed, and the
        # existing single retry stays available.
        self.fake_ack(AGENTTUI.ACK_STATUS_UNCONFIRMED)

        transport, result = self.send()

        self.assertEqual(2, len(transport.keys))
        self.assertEqual(AGENTTUI.ACK_STATUS_UNCONFIRMED, result["ack_status"])

    def test_an_unreadable_table_is_not_treated_as_absence(self) -> None:
        # "I could not look" must stay distinct from "I looked and found nothing".
        self.fake_ack(AGENTTUI.ACK_STATUS_UNAVAILABLE)

        _transport, result = self.send()

        self.assertEqual(AGENTTUI.ACK_STATUS_UNAVAILABLE, result["ack_status"])
        self.assertNotEqual(AGENTTUI.ACK_STATUS_UNCONFIRMED, result["ack_status"])

    def test_the_reading_is_reported_on_success_too(self) -> None:
        # The pair's value is in the combination, so success reports it as well.
        self.fake_ack(AGENTTUI.ACK_STATUS_ACKED)
        marker = "marker-present"

        class FlushingTransport(FakeTransport):
            """Appends the marker when the submit key lands, like a real target.

            The marker has to appear *after* the pre-send byte boundary: only a
            nonce past that boundary counts as delivery evidence, so seeding the
            file up front would prove nothing.
            """

            def __init__(self, path: Path) -> None:
                super().__init__()
                self._path = path

            def send_key(self, pane_ref, key_byte, *, cwd=None, timeout=None):
                outcome = super().send_key(pane_ref, key_byte, cwd=cwd, timeout=timeout)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(f"line with {marker}\n")
                return outcome

        transport = FlushingTransport(self.session_file)
        route = AGENTTUI.DeliveryRoute(
            mode=AGENTTUI.ROUTE_PANE,
            cwd=Path(self.temporary.name),
            transport=transport,
            pane_ref=pane_ref(),
            pane_text="body",
            submit_byte=AGENTTUI.PANE_ENTER_BYTE,
        )
        payload = {
            "target": TARGET,
            "target_brand": "claude-code",
            "target_effective_state": "idle",
            "target_submit_activity": None,
            "target_session_file": str(self.session_file),
            "delivery_marker": marker,
            "nonce": NONCE,
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            AGENTTUI.send_via_pane(route, payload, timeout=None, submit_delay=0.0)
        result = json.loads(stdout.getvalue().strip().splitlines()[-1])

        self.assertEqual(AGENTTUI.DELIVERY_DELIVERED, result["delivery"])
        self.assertEqual(AGENTTUI.ACK_STATUS_ACKED, result["ack_status"])

    def test_a_missing_ack_module_reads_as_unavailable_not_absence(self) -> None:
        # The facility may simply not be adopted here; that says nothing about
        # whether the target submitted.
        original = AGENTTUI.ACK_MODULE_NAME
        AGENTTUI.ACK_MODULE_NAME = "no-such-ack-module.py"
        self.addCleanup(setattr, AGENTTUI, "ACK_MODULE_NAME", original)

        reading = self._real(NONCE)

        self.assertEqual(AGENTTUI.ACK_STATUS_UNAVAILABLE, reading["ack_status"])


class SelfRegistrationRollupTests(unittest.TestCase):
    """A1: a session that just self-registered must be able to complete a heartbeat.

    Before this, the roll-up refused when the summary (or the project entry) was
    absent -- which is exactly the state right after a correct self-registration.
    So the documented "self-register, then heartbeat" sequence could not complete:
    the first heartbeat always failed, and it failed *after* the leaf was already
    on disk, i.e. it reported `error` for a half-success.
    """

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "demo-repo"
        (self.repo / ".trellis").mkdir(parents=True)
        self.leaf = self.repo / ".arborist" / "agents" / "an-agent"
        self.leaf.mkdir(parents=True)
        self.project_id = "0123456789ab"
        (self.leaf / "spec.json").write_text(
            json.dumps(
                {
                    "name": "an-agent",
                    "role": "impler",
                    "brand": "claude-code",
                    "lineage": 3,
                    "project": {"path": str(self.repo), "project_id": self.project_id},
                }
            ),
            encoding="utf-8",
        )
        session_file = self.root / "session.jsonl"
        session_file.write_text("line\n", encoding="utf-8")
        (self.leaf / "runtime.json").write_text(
            json.dumps(
                {
                    "session_id": "a-session-id",
                    "session_file": str(session_file),
                    "state": "active",
                    "last_seen": "2026-01-01T00:00:00+00:00",
                    "pane_ref": None,
                }
            ),
            encoding="utf-8",
        )
        self.index = self.root / "index.json"

    def write_index(self, payload) -> None:
        self.index.write_text(json.dumps(payload), encoding="utf-8")

    def read_index(self):
        return json.loads(self.index.read_text(encoding="utf-8"))

    def run_state(self):
        return AGENTTUI.write_runtime_state(
            self.repo,
            "an-agent",
            state="active",
            now="2026-02-02T00:00:00+00:00",
            global_index=self.index,
        )

    def test_first_heartbeat_after_self_registration_succeeds(self) -> None:
        # The project exists but the agent summary does not -- the exact state a
        # correct self-registration leaves behind.
        self.write_index(
            {"projects": [{"project_id": self.project_id, "path": str(self.repo), "name": "demo-repo", "agents": []}]}
        )

        result = self.run_state()

        self.assertEqual("written", result["leaf"])
        self.assertEqual("created-summary", result["summary"])
        summaries = self.read_index()["projects"][0]["agents"]
        self.assertEqual(1, len(summaries))
        self.assertEqual("an-agent", summaries[0]["name"])

    def test_an_absent_project_entry_is_created_too(self) -> None:
        self.write_index({"projects": []})

        result = self.run_state()

        self.assertEqual("created-project", result["summary"])
        project = self.read_index()["projects"][0]
        self.assertEqual(self.project_id, project["project_id"])
        self.assertEqual(str(self.repo), project["path"])

    def test_created_entries_are_marked_so_an_auditor_can_tell(self) -> None:
        # Silent creation would make a mis-derived project id look like it had
        # always been there.
        self.write_index({"projects": []})

        self.run_state()

        project = self.read_index()["projects"][0]
        self.assertEqual("agenttui-rollup", project["created_by"])
        self.assertEqual("agenttui-rollup", project["agents"][0]["created_by"])

    def test_lineage_is_rolled_up_not_defaulted_away(self) -> None:
        self.write_index({"projects": []})

        self.run_state()

        self.assertEqual(3, self.read_index()["projects"][0]["agents"][0]["lineage"])

    def test_an_existing_summary_is_updated_not_duplicated(self) -> None:
        self.write_index(
            {
                "projects": [
                    {
                        "project_id": self.project_id,
                        "path": str(self.repo),
                        "name": "demo-repo",
                        "agents": [{"name": "an-agent", "brand": "stale", "state": "stopped"}],
                    }
                ]
            }
        )

        result = self.run_state()

        self.assertEqual("updated", result["summary"])
        summaries = self.read_index()["projects"][0]["agents"]
        self.assertEqual(1, len(summaries))
        self.assertEqual("claude-code", summaries[0]["brand"])

    def test_a_damaged_index_reports_both_halves_and_refuses_to_advise_a_retry(self) -> None:
        # The regression guard that matters most: replacing a loud error with a
        # quiet half-success would be worse, and telling the caller to retry a
        # failure that cannot improve would send it into a hopeless loop.
        self.write_index({"projects": "not-an-array"})

        result = self.run_state()

        self.assertEqual("written", result["leaf"])
        self.assertEqual("failed", result["summary"])
        self.assertEqual("no", result["summary_self_repairing"])
        self.assertIn("do NOT just retry", result["recommended_action"])
        self.assertIn("half-registered", result["recommended_action"])

    def test_the_leaf_is_still_written_when_the_rollup_fails(self) -> None:
        # The original bug: the leaf was already on disk and the caller was told
        # `error`, with no way to tell "nothing happened" from "half happened".
        self.write_index({"projects": "not-an-array"})

        self.run_state()

        runtime = json.loads((self.leaf / "runtime.json").read_text(encoding="utf-8"))
        self.assertEqual("2026-02-02T00:00:00+00:00", runtime["last_seen"])

    def test_no_global_index_requested_is_not_a_failure(self) -> None:
        result = AGENTTUI.write_runtime_state(
            self.repo, "an-agent", state="active", now="2026-02-02T00:00:00+00:00",
            global_index=None,
        )

        self.assertEqual("not-requested", result["summary"])


if __name__ == "__main__":
    unittest.main()
