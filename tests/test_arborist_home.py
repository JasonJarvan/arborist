"""Tests for the `ARBORIST_HOME` override of the machine-level Arborist root.

The override exists so the global tier can be rehearsed against a scratch
directory: without it, every dry run of a migration that moves something *into*
the global root has to be performed on the one real copy of that root, which is
not a dry run.

The override is only safe to add if it is inert when unset, so the assertions
here are deliberately two-sided:

1. **Unset, and set-but-empty, resolve to `~/.arborist` -- spelled out as the
   literal expression the code used before the override existed.** That literal is
   the mechanical proof that adding a knob did not move anybody's paths: if the
   resolver ever stops agreeing with it, this fails, whatever the resolver's own
   comments claim.
2. Set to a value, every derived default moves under it and *nothing else does*.

Every module is (re)loaded inside a patched environment, because the derived
defaults are module constants read once at import -- which is itself a pinned
property (a caller that flipped the variable mid-process would otherwise end up
with a half-moved set of paths).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]

ENV = "ARBORIST_HOME"

# The scripts that resolve the global root, and the module-level defaults each one
# derives from it. Kept as one table so a newly added default cannot quietly skip
# these assertions.
RESOLVERS: dict[str, tuple[str, ...]] = {
    "agenttui.py": ("OBSERVATION_LOG_DEFAULT", "GLOBAL_INDEX_DEFAULT"),
    "agenttui_submit_ack.py": ("ACK_LOG_DEFAULT",),
    "validate_agenttui_registry.py": ("DEFAULT_GLOBAL_INDEX",),
}

# The expression the code used before the override existed, restated here rather
# than imported: an expectation copied out of the implementation proves nothing.
LEGACY_ROOT = Path.home() / ".arborist"


@contextmanager
def patched_env(value: str | None) -> Iterator[None]:
    """Run with `ARBORIST_HOME` set to `value`, or removed when `value is None`."""

    previous = os.environ.get(ENV)
    try:
        if value is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = value
        yield
    finally:
        if previous is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = previous


def load(script: str) -> Any:
    """Load one overlay script by path, freshly, so import-time constants re-run."""

    module_path = ROOT / "overlay/scripts" / script
    module_name = f"_arborist_home_probe_{script.replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


class ArboristHomeUnsetTest(unittest.TestCase):
    """Absence of the variable must be indistinguishable from its absence before."""

    def test_unset_resolves_to_the_legacy_root(self) -> None:
        for script in RESOLVERS:
            with self.subTest(script=script), patched_env(None):
                module = load(script)
                self.assertEqual(module.arborist_home(), LEGACY_ROOT)

    def test_empty_string_resolves_to_the_legacy_root(self) -> None:
        # A set-but-blank variable is how a shell spells "I did not mean to
        # configure this". Honouring it as a root would resolve every derived path
        # against the process cwd -- a silent relocation, and the worst of the
        # three possible behaviours.
        for script in RESOLVERS:
            with self.subTest(script=script), patched_env(""):
                module = load(script)
                self.assertEqual(module.arborist_home(), LEGACY_ROOT)

    def test_derived_defaults_are_unchanged_when_unset(self) -> None:
        for script, names in RESOLVERS.items():
            with patched_env(None):
                module = load(script)
            for name in names:
                with self.subTest(script=script, default=name):
                    value = getattr(module, name)
                    self.assertEqual(
                        value.parent,
                        LEGACY_ROOT,
                        f"{script}:{name} no longer sits directly in {LEGACY_ROOT}",
                    )

    def test_the_known_default_filenames_did_not_move(self) -> None:
        # Named literally, not derived: these three paths are already written into
        # deployed hook configs and tool entries, so a rename is a breaking change
        # that must not be able to ride along with a refactor of the root.
        with patched_env(None):
            agenttui = load("agenttui.py")
            ack = load("agenttui_submit_ack.py")
            registry = load("validate_agenttui_registry.py")
        self.assertEqual(
            agenttui.OBSERVATION_LOG_DEFAULT, LEGACY_ROOT / "focus-intrusion.jsonl"
        )
        self.assertEqual(agenttui.GLOBAL_INDEX_DEFAULT, LEGACY_ROOT / "index.json")
        self.assertEqual(ack.ACK_LOG_DEFAULT, LEGACY_ROOT / "submit-acks.jsonl")
        self.assertEqual(registry.DEFAULT_GLOBAL_INDEX, LEGACY_ROOT / "index.json")


class ArboristHomeSetTest(unittest.TestCase):
    def test_override_moves_every_derived_default(self) -> None:
        scratch = Path("/nonexistent-scratch-root/arborist-home")
        for script, names in RESOLVERS.items():
            with patched_env(str(scratch)):
                module = load(script)
                self.assertEqual(module.arborist_home(), scratch)
            for name in names:
                with self.subTest(script=script, default=name):
                    self.assertEqual(getattr(module, name).parent, scratch)

    def test_override_expands_a_leading_tilde(self) -> None:
        # A path handed over by a human or a shell that did not expand it is the
        # common case; leaving it literal would create a directory named `~`.
        with patched_env("~/scratch-arborist"):
            module = load("validate_agenttui_registry.py")
            self.assertEqual(module.arborist_home(), Path.home() / "scratch-arborist")

    def test_the_two_resolvers_agree(self) -> None:
        # Three copies of the resolver exist because each script must stay
        # deployable on its own. Pinning them to the same answers here is what
        # keeps "three copies" from becoming "three behaviours".
        for value in (None, "", "/tmp/one-root", "~/another-root"):
            with self.subTest(value=value), patched_env(value):
                answers = {
                    script: load(script).arborist_home() for script in RESOLVERS
                }
                self.assertEqual(len(set(answers.values())), 1, answers)


if __name__ == "__main__":
    unittest.main()
