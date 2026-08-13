"""The cross-project mirror facility must be nameable without reading the source.

`foreign_repo_registration` was implemented (delivery side + validator check 7)
and specified (agenttui-registry.md §2.2.2) while being absent from every surface
a caller actually meets: `--help` at both levels, and the error raised when a
peer's name fails to resolve. The measured consequence was a sender concluding
cross-project delivery was unsupported and routing by hand instead.

These tests pin the three surfaces. Each asserts on the FIELD NAME, because that
is the token a caller can search for -- prose about "mirrors" that never spells
the field leaves the reader where they started.
"""

from __future__ import annotations

import importlib.util
import io
import contextlib
import sys
import unittest
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


AGENTTUI = load_script_module("overlay/scripts/agenttui.py", "agenttui_help_under_test")

FIELD = AGENTTUI.FOREIGN_REGISTRATION_FIELD


def help_text(argv: list[str]) -> str:
    """Render argparse help exactly as a caller sees it, including the epilog."""
    buffer = io.StringIO()
    parser = AGENTTUI.create_parser()
    with contextlib.redirect_stdout(buffer):
        with self_exit_ok():
            parser.parse_args(argv)
    return buffer.getvalue()


@contextlib.contextmanager
def self_exit_ok():
    try:
        yield
    except SystemExit:
        pass


class CrossProjectHelpTests(unittest.TestCase):
    def test_top_level_help_names_the_field(self) -> None:
        text = help_text(["--help"])
        self.assertIn(FIELD, text)
        # The three keys are what makes a declaration complete; a help text that
        # names the field but not its required keys still sends the reader to the
        # source to find out what to write.
        for key in AGENTTUI.FOREIGN_REGISTRATION_REQUIRED:
            self.assertIn(key, text)

    def test_send_help_names_the_field(self) -> None:
        # `send` is where a caller is standing when the question arises, so the
        # subcommand help must answer it without a trip back to the top level.
        text = help_text(["send", "--help"])
        self.assertIn(FIELD, text)

    def test_send_help_documents_both_naming_forms(self) -> None:
        text = help_text(["send", "--help"])
        self.assertIn("<project_id>.<name>", text)


class UnresolvedNameErrorTests(unittest.TestCase):
    """The raise site is the only surface reached by a caller who never ran --help."""

    def test_missing_leaf_names_the_mechanism(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".arborist" / "agents").mkdir(parents=True)
            with self.assertRaises(AGENTTUI.RegistryError) as caught:
                AGENTTUI.load_agent(repo, "peer-in-another-project")
        message = str(caught.exception)
        self.assertIn(FIELD, message)
        self.assertIn("peer-in-another-project", message)

    def test_broken_leaf_is_not_reported_as_unregistered(self) -> None:
        """Directory existence and file contents are two readings, not one.

        A leaf whose directory exists but whose spec.json does not is BROKEN, not
        absent, and the mirror hint would be wrong advice there: the operator must
        repair the leaf, not register a mirror of it somewhere.
        """
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".arborist" / "agents" / "half-written").mkdir(parents=True)
            with self.assertRaises(AGENTTUI.RegistryError) as caught:
                AGENTTUI.load_agent(repo, "half-written")
        message = str(caught.exception)
        self.assertIn("missing registry file", message)
        self.assertNotIn(FIELD, message)


if __name__ == "__main__":
    unittest.main()
