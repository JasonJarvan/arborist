from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "set_trellis_codex_dispatch.py"
SPEC = importlib.util.spec_from_file_location("set_trellis_codex_dispatch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SetTrellisCodexDispatchTest(unittest.TestCase):
    def apply(self, original: str) -> tuple[str, bool]:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(original, encoding="utf-8")
            changed = MODULE.set_subagent_mode(config)
            return config.read_text(encoding="utf-8"), changed

    def test_replaces_inline_without_touching_other_yaml(self) -> None:
        original = "hooks:\n  after_start:\n    - keep-me\n\ncodex:\n  dispatch_mode: inline\n"
        updated, changed = self.apply(original)
        self.assertTrue(changed)
        self.assertEqual(
            "hooks:\n  after_start:\n    - keep-me\n\ncodex:\n  dispatch_mode: sub-agent\n",
            updated,
        )

    def test_adds_missing_codex_block(self) -> None:
        updated, changed = self.apply("channel:\n  worker_guard:\n    max_live_workers: 6\n")
        self.assertTrue(changed)
        self.assertEqual(
            "channel:\n  worker_guard:\n    max_live_workers: 6\n\ncodex:\n  dispatch_mode: sub-agent\n",
            updated,
        )

    def test_creates_missing_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".trellis" / "config.yaml"
            changed = MODULE.set_subagent_mode(config)
            self.assertTrue(changed)
            self.assertEqual(
                "codex:\n  dispatch_mode: sub-agent\n",
                config.read_text(encoding="utf-8"),
            )

    def test_adds_missing_key_to_existing_codex_block(self) -> None:
        updated, changed = self.apply("codex:\n  another_setting: true\nhooks:\n  keep: true\n")
        self.assertTrue(changed)
        self.assertEqual(
            "codex:\n  dispatch_mode: sub-agent\n  another_setting: true\nhooks:\n  keep: true\n",
            updated,
        )

    def test_is_idempotent(self) -> None:
        original = "codex:\n  dispatch_mode: sub-agent\n"
        updated, changed = self.apply(original)
        self.assertFalse(changed)
        self.assertEqual(original, updated)

    def test_rejects_duplicate_codex_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("codex:\n  one: true\ncodex:\n  two: true\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "multiple top-level codex blocks"):
                MODULE.set_subagent_mode(config)


if __name__ == "__main__":
    unittest.main()
