from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_adapter_module():
    """Load the opt-in reference adapter as a module without a package import."""
    adapter_path = ROOT / "overlay/scripts/agenttui_deliver_zellij.py"
    module_name = "agenttui_deliver_zellij"
    spec = importlib.util.spec_from_file_location(module_name, adapter_path)
    assert spec is not None and spec.loader is not None, adapter_path
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve the module's namespace
    # (from __future__ import annotations makes field annotations strings).
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = load_adapter_module()


class RecordingInjector:
    """Fake PaneInjector: records envelope writes and submit-key sends.

    No real zellij involved; the transport seam is fully mocked.
    """

    def __init__(self) -> None:
        self.envelope_writes: list[tuple[str, str]] = []
        self.submit_sends: list[tuple[str, int]] = []

    def write_envelope(self, pane_ref: str, payload: str) -> None:
        self.envelope_writes.append((pane_ref, payload))

    def send_submit_key(self, pane_ref: str, key_byte: int) -> None:
        self.submit_sends.append((pane_ref, key_byte))


class ScriptedReader:
    """Fake TranscriptReader: fixed boundary size + scripted post-boundary text.

    `read_since` ignores the file entirely and returns the scripted growth,
    so tests need neither a real session file nor a real transcript.
    """

    def __init__(self, boundary: int, growth_after_boundary: str) -> None:
        self._boundary = boundary
        self._growth = growth_after_boundary
        self.read_since_calls = 0

    def size(self, session_file: str) -> int:
        return self._boundary

    def read_since(self, session_file: str, boundary: int) -> str:
        self.read_since_calls += 1
        return self._growth


def make_adapter(growth: str, boundary: int = 4096):
    injector = RecordingInjector()
    reader = ScriptedReader(boundary=boundary, growth_after_boundary=growth)
    adapter = ADAPTER.ZellijDeliveryAdapter(injector=injector, reader=reader)
    return adapter, injector, reader


# A fixed placeholder nonce for tests only — not an instance/runtime value; the
# adapter itself never hardcodes a nonce (it comes from the per-send argument).
TEST_NONCE = "test-nonce-0001"
TEST_SESSION = "/placeholder/target-session-file"
TEST_PANE = "placeholder-pane-ref"
TEST_ENVELOPE = "decision: proceed with option A"


class SubmitKeyRoutingTests(unittest.TestCase):
    """Issue #12 acceptance: brand- and activity-aware submit-key routing."""

    def test_active_codex_queues_with_tab_byte_9(self) -> None:
        # Transcript grows AND carries this nonce marker -> genuinely delivered.
        growth = "peer transcript line\n" + ADAPTER.render_marker(TEST_NONCE) + "\n"
        adapter, injector, _reader = make_adapter(growth)

        result = adapter.deliver(
            session_file=TEST_SESSION,
            pane_ref=TEST_PANE,
            brand="codex",
            activity="active",
            envelope=TEST_ENVELOPE,
            nonce=TEST_NONCE,
        )

        self.assertEqual(ADAPTER.SUBMIT_TAB, 9)
        self.assertEqual([(TEST_PANE, 9)], injector.submit_sends)
        self.assertEqual(ADAPTER.STATUS_DELIVERED, result.status)
        self.assertTrue(result.delivered)

    def test_idle_codex_submits_with_enter_byte_13(self) -> None:
        growth = ADAPTER.render_marker(TEST_NONCE)
        adapter, injector, _reader = make_adapter(growth)

        result = adapter.deliver(
            session_file=TEST_SESSION,
            pane_ref=TEST_PANE,
            brand="codex",
            activity="idle",
            envelope=TEST_ENVELOPE,
            nonce=TEST_NONCE,
        )

        self.assertEqual(ADAPTER.SUBMIT_ENTER, 13)
        self.assertEqual([(TEST_PANE, 13)], injector.submit_sends)
        self.assertEqual(ADAPTER.STATUS_DELIVERED, result.status)

    def test_active_claude_code_submits_with_enter(self) -> None:
        growth = ADAPTER.render_marker(TEST_NONCE)
        adapter, injector, _reader = make_adapter(growth)

        result = adapter.deliver(
            session_file=TEST_SESSION,
            pane_ref=TEST_PANE,
            brand="claude-code",
            activity="active",
            envelope=TEST_ENVELOPE,
            nonce=TEST_NONCE,
        )

        self.assertEqual([(TEST_PANE, 13)], injector.submit_sends)
        self.assertEqual(ADAPTER.STATUS_DELIVERED, result.status)


class DeliveryEvidenceTests(unittest.TestCase):
    """Issue #12 acceptance: fail-closed, nonce-specific delivery evidence."""

    def test_false_positive_protection_growth_without_nonce_is_unverified(self) -> None:
        # Busy target grows its OWN transcript but the growth does NOT contain
        # this send's nonce marker -> must be queued-unverified, never delivered.
        busy_growth = (
            "assistant: still working on the previous turn...\n"
            "tool_call: read some unrelated file\n"
            + ADAPTER.render_marker("some-other-unrelated-nonce")
            + "\n"
        )
        adapter, injector, reader = make_adapter(busy_growth)

        result = adapter.deliver(
            session_file=TEST_SESSION,
            pane_ref=TEST_PANE,
            brand="codex",
            activity="active",
            envelope=TEST_ENVELOPE,
            nonce=TEST_NONCE,
        )

        self.assertEqual(ADAPTER.STATUS_QUEUED_UNVERIFIED, result.status)
        self.assertFalse(result.delivered)
        # Growth was observed (reader ran) yet still not accepted as evidence.
        self.assertGreaterEqual(reader.read_since_calls, 1)
        # Envelope was written and one submit key sent — success of those is not evidence.
        self.assertEqual(1, len(injector.envelope_writes))

    def test_no_duplicate_tab_when_delivery_unverified(self) -> None:
        # Unverified active-Codex send must NOT resend the enqueue key (Tab),
        # otherwise it would enqueue a duplicate envelope.
        busy_growth = "assistant: busy, no marker here at all\n"
        adapter, injector, _reader = make_adapter(busy_growth)

        result = adapter.deliver(
            session_file=TEST_SESSION,
            pane_ref=TEST_PANE,
            brand="codex",
            activity="active",
            envelope=TEST_ENVELOPE,
            nonce=TEST_NONCE,
            # Even multiple verify attempts must not resend the submit key.
            verify_attempts=5,
            verify_delay=0.0,
        )

        self.assertEqual(ADAPTER.STATUS_QUEUED_UNVERIFIED, result.status)
        tab_sends = [send for send in injector.submit_sends if send[1] == ADAPTER.SUBMIT_TAB]
        self.assertEqual(1, len(tab_sends), "Tab must be sent exactly once, never resent")
        self.assertEqual(1, len(injector.submit_sends))

    def test_boundary_recorded_before_injection(self) -> None:
        # The byte boundary must be the pre-injection size (evidence is past it).
        growth = ADAPTER.render_marker(TEST_NONCE)
        adapter, _injector, _reader = make_adapter(growth, boundary=12345)

        result = adapter.deliver(
            session_file=TEST_SESSION,
            pane_ref=TEST_PANE,
            brand="codex",
            activity="idle",
            envelope=TEST_ENVELOPE,
            nonce=TEST_NONCE,
        )

        self.assertEqual(12345, result.boundary)

    def test_empty_nonce_is_rejected(self) -> None:
        adapter, _injector, _reader = make_adapter(growth="")
        with self.assertRaises(ValueError):
            adapter.deliver(
                session_file=TEST_SESSION,
                pane_ref=TEST_PANE,
                brand="codex",
                activity="active",
                envelope=TEST_ENVELOPE,
                nonce="",
            )


class SubmitKeyResolverTests(unittest.TestCase):
    def test_resolver_matrix(self) -> None:
        self.assertEqual(9, ADAPTER.resolve_submit_key("codex", "active"))
        self.assertEqual(13, ADAPTER.resolve_submit_key("codex", "idle"))
        self.assertEqual(13, ADAPTER.resolve_submit_key("claude-code", "active"))
        self.assertEqual(13, ADAPTER.resolve_submit_key("claude-code", "idle"))

    def test_resolver_rejects_unknown_brand(self) -> None:
        with self.assertRaises(ValueError):
            ADAPTER.resolve_submit_key("gemini", "active")


if __name__ == "__main__":
    unittest.main()
