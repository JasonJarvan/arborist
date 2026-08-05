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
        self.keys: list[str] = []

    def available(self) -> AGENTTUI.Capability:
        return AGENTTUI.Capability(self._available, "fake transport availability")

    def exists(self, pane_ref) -> AGENTTUI.Capability:
        self.exists_calls += 1
        return AGENTTUI.Capability(self._exists, "fake transport existence probe")

    def write_chars_argv(self, pane_ref, text):
        return ["fake-mux-cli", "write", pane_ref["pane_id"], text]

    def send_key_argv(self, pane_ref, key_byte):
        return ["fake-mux-cli", "key", pane_ref["pane_id"], key_byte]

    def write_chars(self, pane_ref, text, *, cwd=None, timeout=None):
        self.writes.append(text)
        argv = self.write_chars_argv(pane_ref, text)
        return self._write_outcome or AGENTTUI.CommandOutcome(
            argv=argv, returncode=0, stdout="", stderr="", rejected=False, detail=""
        )

    def send_key(self, pane_ref, key_byte, *, cwd=None, timeout=None):
        self.keys.append(key_byte)
        argv = self.send_key_argv(pane_ref, key_byte)
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
            target, "envelope", transports={FAKE_MUX: lambda: transport}
        )

        self.assertEqual(AGENTTUI.ROUTE_PANE, route.mode)
        self.assertIs(transport, route.transport)
        self.assertEqual(1, transport.exists_calls)
        # The command line comes from the transport, not from the router.
        self.assertEqual(
            ["fake-mux-cli", "write", PANE_ID, "envelope"], route.pane_argv()
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
                target, "envelope", transports={"zellij": lambda: transport}
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

        self.assertEqual(AGENTTUI.DELIVERY_QUEUED_UNVERIFIED, result["delivery"])
        self.assertEqual("none", result["evidence"])
        self.assertFalse(result["transport_exit_status_trusted"])
        self.assertIn("not delivery evidence", warnings)

    def test_rejected_submit_after_injection_is_queued_unverified_not_unsent(self) -> None:
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

        _status, result, warnings = self.run_pane_send(transport)

        self.assertEqual(AGENTTUI.DELIVERY_QUEUED_UNVERIFIED, result["delivery"])
        self.assertTrue(result["sent"])
        self.assertFalse(result["retry_safe"])
        self.assertIsNotNone(result["submit_rejected"])
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

    def test_no_operational_route_and_queued_unverified_are_distinct_values(self) -> None:
        self.assertNotEqual(
            AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE, AGENTTUI.DELIVERY_QUEUED_UNVERIFIED
        )
        self.assertEqual("no-operational-route", AGENTTUI.DELIVERY_NO_OPERATIONAL_ROUTE)
        self.assertEqual("queued-unverified", AGENTTUI.DELIVERY_QUEUED_UNVERIFIED)

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


def write_registry(base: Path, *, target_pane_ref: dict[str, str] | None) -> Path:
    """Create a minimal project repository with two registered agents."""
    repo = base / "placeholder-repo"
    (repo / ".trellis").mkdir(parents=True)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for name, brand, pane in ((SENDER, "codex", None), (TARGET, "claude-code", target_pane_ref)):
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

        transport, result = self.send(brand="codex", state="active")

        self.assertEqual(AGENTTUI.DELIVERY_QUEUED_UNVERIFIED, result["delivery"])
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


if __name__ == "__main__":
    unittest.main()
