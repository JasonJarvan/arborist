"""Tests for the shared AgentTUI launcher (`overlay/scripts/atui_launch.sh`).

The launcher is the *one* piece of launch logic both a human and an agent-derived
path use, because two launch paths make `pane_ref` value domain, self-identity and
reachability fork into two — and errors at the fork are silent.

Nothing here starts a multiplexer, touches a real terminal, reads a real registry
or runs a real CLI: every case goes through `--dry-run`, and the one case that
needs the multiplexer binary to *exist* gets a fake one on PATH. The launcher is
deliberately **not wired into any shell startup file**, so these tests are also
what stands in for the not-yet-taken install step.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "overlay/scripts/atui_launch.sh"

CLI = "placeholder-cli"
BYPASS = "--placeholder-bypass"


def code_lines(script: Path) -> list[str]:
    """Executable lines only: comments and the help heredoc are prose.

    Needed because several assertions are about what the launcher *does*, while the
    same words legitimately appear in comments that record why it does not do them.
    """
    lines: list[str] = []
    in_heredoc = False
    for raw in script.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if in_heredoc:
            in_heredoc = stripped != "EOF"
            continue
        if stripped.startswith("cat <<"):
            in_heredoc = True
            continue
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


class LauncherTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        # A throwaway project repo: the launcher's path-derivation gate requires
        # one of the repo markers, exactly like the delivery adapter's gate.
        self.repo = self.base / "placeholder-repo"
        (self.repo / ".trellis").mkdir(parents=True)
        # A fake multiplexer binary, so no case depends on the host having one.
        self.fake_bin = self.base / "bin"
        self.fake_bin.mkdir()
        fake_tmux = self.fake_bin / "tmux"
        fake_tmux.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_tmux.chmod(0o755)
        # A PATH that deliberately has *no* multiplexer on it, for the fail-closed
        # case. Built by symlinking only the utilities the launcher itself needs, so
        # the case does not depend on the host lacking a real multiplexer.
        self.bare_bin = self.base / "bare-bin"
        self.bare_bin.mkdir()
        for utility in ("bash", "env", "basename", "tr"):
            located = shutil.which(utility)
            assert located is not None, utility
            (self.bare_bin / utility).symlink_to(located)

    def run_launcher(
        self,
        *args: str,
        env_extra: dict[str, str] | None = None,
        with_multiplexer: bool = True,
    ) -> subprocess.CompletedProcess:
        env = {
            "PATH": (
                f"{self.fake_bin}:{os.defpath}"
                if with_multiplexer
                else str(self.bare_bin)
            ),
            "HOME": str(self.base),
        }
        env.update(env_extra or {})
        return subprocess.run(
            ["bash", str(LAUNCHER), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.base),
            check=False,
        )

    def plan(self, *args: str, **kwargs) -> list[str]:
        """The single `+ …` line of a dry run, parsed back into an argv list."""
        result = self.run_launcher("--dry-run", *args, **kwargs)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        lines = [
            line for line in result.stdout.splitlines() if line.startswith("+ ")
        ]
        self.assertEqual(1, len(lines), result.stdout)
        return shlex.split(lines[0][2:])


class DryRunTests(LauncherTestCase):
    def test_a_dry_run_executes_nothing(self) -> None:
        # Mechanical: the fake CLI would leave a marker file if it ran.
        marker = self.base / "marker"
        cli = self.fake_bin / CLI
        cli.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        cli.chmod(0o755)

        result = self.run_launcher(
            "--project", str(self.repo), "--dry-run", "--", CLI
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(marker.exists())
        self.assertIn("什么都不会执行", result.stdout)

    def test_the_dry_run_prints_the_command_it_would_run(self) -> None:
        plan = self.plan("--project", str(self.repo), "--", CLI)

        self.assertEqual("tmux", plan[0])
        self.assertIn("new-session", plan)
        self.assertIn(CLI, plan)


class PathDerivationGateTests(LauncherTestCase):
    def test_a_directory_that_is_not_a_repo_is_refused(self) -> None:
        plain = self.base / "not-a-repo"
        plain.mkdir()

        result = self.run_launcher("--project", str(plain), "--dry-run", "--", CLI)

        self.assertEqual(2, result.returncode)
        self.assertIn("不是项目仓", result.stderr)

    def test_a_refusal_creates_nothing(self) -> None:
        plain = self.base / "not-a-repo"
        plain.mkdir()

        self.run_launcher("--project", str(plain), "--dry-run", "--", CLI)

        # `mkdir -p` would make a wrong location look like it had always been there.
        self.assertEqual([], list(plain.iterdir()))

    def test_a_worktree_whose_git_is_a_file_is_accepted(self) -> None:
        # In a git worktree `.git` is a *file*; judging by "is a directory" would
        # reject every worktree, which is where much of the work happens.
        worktree = self.base / "placeholder-worktree"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

        plan = self.plan("--project", str(worktree), "--", CLI)

        self.assertIn("new-session", plan)

    def test_the_project_is_required_rather_than_guessed_from_cwd(self) -> None:
        result = self.run_launcher("--dry-run", "--", CLI)

        self.assertEqual(2, result.returncode)
        self.assertIn("--project", result.stderr)

    def test_a_missing_command_is_refused_rather_than_guessed(self) -> None:
        result = self.run_launcher("--project", str(self.repo), "--dry-run")

        self.assertEqual(2, result.returncode)
        self.assertIn("不猜", result.stderr)


class ArgumentFidelityTests(LauncherTestCase):
    def test_an_argument_containing_spaces_stays_one_argument(self) -> None:
        # `"$@"` rather than `"$*"`: the latter would split this into two.
        plan = self.plan(
            "--project", str(self.repo), "--", CLI, "--flag", "two words"
        )

        self.assertIn("two words", plan)
        self.assertNotIn("two", plan)

    def test_bypass_flags_reach_the_command_line(self) -> None:
        # The spelling is adopter-local, so it is a parameter and never hardcoded.
        plan = self.plan(
            "--project", str(self.repo), "--bypass-flag", BYPASS, "--", CLI
        )

        self.assertIn(BYPASS, plan)

    def test_the_inherited_session_identity_is_always_cleared(self) -> None:
        # Not clearing it makes the child inherit the parent's session identity,
        # and from there it delivers to the wrong pane or writes someone else's
        # brand (launch contract invariant 2).
        for extra in ([], ["--multiplexer", "none"]):
            plan = self.plan("--project", str(self.repo), *extra, "--", CLI)

            self.assertIn("env", plan)
            self.assertIn("-u", plan)
            self.assertIn("TRELLIS_CONTEXT_ID", plan)


class EscapeHatchTests(LauncherTestCase):
    def unwrapped(self) -> list[str]:
        return ["env", "-u", "TRELLIS_CONTEXT_ID", CLI, "--flag", "two words"]

    def test_the_switch_off_plan_is_byte_identical_to_the_pre_change_form(self) -> None:
        # The mechanical proof required of any change to a human's launch
        # environment: with the switch off, the behaviour is *exactly* what it was
        # before the launcher existed.
        plan = self.plan(
            "--project",
            str(self.repo),
            "--",
            CLI,
            "--flag",
            "two words",
            env_extra={"ARBORIST_ATUI_LAUNCH_WRAP": "0"},
        )

        self.assertEqual(self.unwrapped(), plan)

    def test_switching_off_needs_no_multiplexer_at_all(self) -> None:
        plan = self.plan(
            "--project",
            str(self.repo),
            "--",
            CLI,
            "--flag",
            "two words",
            env_extra={"ARBORIST_ATUI_LAUNCH_WRAP": "0"},
            with_multiplexer=False,
        )

        self.assertEqual(self.unwrapped(), plan)

    def test_multiplexer_none_gives_the_same_unwrapped_plan(self) -> None:
        plan = self.plan(
            "--project",
            str(self.repo),
            "--multiplexer",
            "none",
            "--",
            CLI,
            "--flag",
            "two words",
        )

        self.assertEqual(self.unwrapped(), plan)

    def test_the_reason_for_not_wrapping_is_always_stated(self) -> None:
        result = self.run_launcher(
            "--project",
            str(self.repo),
            "--dry-run",
            "--",
            CLI,
            env_extra={"ARBORIST_ATUI_LAUNCH_WRAP": "0"},
        )

        self.assertIn("wrap         = no", result.stdout)
        self.assertIn("ARBORIST_ATUI_LAUNCH_WRAP=0", result.stdout)


class IdempotenceTests(LauncherTestCase):
    def test_already_inside_the_multiplexer_is_a_pass_through(self) -> None:
        # Repeated nesting makes the pane-handle level unpredictable, and the
        # self-identification gate has already measured two real cases of a
        # session mistaking an outer pane for its own.
        plan = self.plan(
            "--project",
            str(self.repo),
            "--",
            CLI,
            env_extra={"TMUX": "/placeholder/socket,1,0"},
        )

        self.assertEqual(["env", "-u", "TRELLIS_CONTEXT_ID", CLI], plan)
        self.assertNotIn("tmux", plan)

    def test_the_pass_through_states_idempotence_as_the_reason(self) -> None:
        result = self.run_launcher(
            "--project",
            str(self.repo),
            "--dry-run",
            "--",
            CLI,
            env_extra={"TMUX": "/placeholder/socket,1,0"},
        )

        self.assertIn("幂等", result.stdout)


class MissingMultiplexerTests(LauncherTestCase):
    def test_a_missing_multiplexer_fails_closed_instead_of_not_wrapping(self) -> None:
        # Silently not wrapping would leave the launched session without a
        # directed handle, and that difference is invisible afterwards: delivery
        # still returns success, it just cannot reach anybody.
        result = self.run_launcher(
            "--project",
            str(self.repo),
            "--dry-run",
            "--",
            CLI,
            with_multiplexer=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("不静默降级", result.stderr)
        self.assertIn("ARBORIST_ATUI_LAUNCH_WRAP=0", result.stderr)


class NamingTests(LauncherTestCase):
    def session_name(self, plan: list[str]) -> str:
        return plan[plan.index("-s") + 1]

    def test_the_first_stage_name_is_project_plus_pid(self) -> None:
        plan = self.plan("--project", str(self.repo), "--", CLI)
        name = self.session_name(plan)

        self.assertTrue(name.startswith("placeholder-repo-"), name)
        self.assertTrue(name.rsplit("-", 1)[1].isdigit(), name)

    def test_the_session_name_avoids_the_characters_the_namespace_forbids(self) -> None:
        # A multiplexer session name may not contain "." or ":", so the project
        # segment is restricted at the source rather than escaped at each consumer.
        awkward = self.base / "Placeholder.Repo:X"
        (awkward / ".trellis").mkdir(parents=True)

        plan = self.plan("--project", str(awkward), "--", CLI)
        name = self.session_name(plan)

        self.assertNotIn(".", name)
        self.assertNotIn(":", name)
        self.assertEqual(name.lower(), name)

    def test_an_explicit_session_name_wins(self) -> None:
        plan = self.plan(
            "--project", str(self.repo), "--session", "placeholder-name", "--", CLI
        )

        self.assertEqual("placeholder-name", self.session_name(plan))

    def test_the_launcher_never_renames_by_itself(self) -> None:
        # Two-stage naming is only safe where the addressing handle carries no
        # session name. This transport's pane_ref *does* carry one and the probe
        # cross-checks it, so a rename invalidates existing handles — loudly, but
        # it still has to be paired with rebuilding the whole pane_ref.
        result = self.run_launcher(
            "--project", str(self.repo), "--dry-run", "--", CLI
        )

        self.assertNotIn("rename-session", result.stdout)
        self.assertIn("整条重建", result.stdout)

    def test_the_launcher_does_not_write_the_brand_or_the_registry(self) -> None:
        # The launcher only picks which binary to start; the actual runtime brand
        # is self-registered by the session (ADR-0006).
        plan = self.plan(
            "--project",
            str(self.repo),
            "--role",
            "impler",
            "--brand",
            "placeholder-brand",
            "--",
            CLI,
        )

        self.assertNotIn("placeholder-brand", plan)
        self.assertNotIn("impler", plan)
        self.assertEqual([], list((self.repo).glob(".arborist/**/*")))


class SocketTests(LauncherTestCase):
    def socket_argv(self, plan: list[str]) -> list[str]:
        return plan[1:3]

    def test_the_default_socket_is_private_to_the_project(self) -> None:
        # The machine's default server already hosts other tools' sessions, so a
        # shared default server is exactly the same-pane-number ambiguity the
        # pane_ref socket dimension exists to remove.
        plan = self.plan("--project", str(self.repo), "--", CLI)

        self.assertEqual(["-L", "arborist-placeholder-repo"], self.socket_argv(plan))

    def test_a_socket_path_is_addressed_as_a_path(self) -> None:
        plan = self.plan(
            "--project",
            str(self.repo),
            "--socket",
            "/placeholder/dir/placeholder.sock",
            "--",
            CLI,
        )

        self.assertEqual(
            ["-S", "/placeholder/dir/placeholder.sock"], self.socket_argv(plan)
        )

    def test_a_socket_name_is_addressed_as_a_name(self) -> None:
        plan = self.plan(
            "--project", str(self.repo), "--socket", "placeholder-socket", "--", CLI
        )

        self.assertEqual(["-L", "placeholder-socket"], self.socket_argv(plan))


class SessionLifecycleTests(LauncherTestCase):
    """Cleanup must not depend on a signal, and must not kill a detached session."""

    def test_cleanup_is_armed_by_attachment_not_by_a_signal(self) -> None:
        # Measured, and it overturned the earlier design: a `trap` on SIGHUP works
        # in a script shell and *not* in the real usage (a human pasting the command
        # into an interactive shell), which left an invisible live agent behind. The
        # multiplexer's own option depends on neither signals nor shell type.
        plan = self.plan("--project", str(self.repo), "--", CLI)
        joined = " ".join(plan)

        self.assertIn("set-hook", joined)
        self.assertIn("client-attached", joined)
        self.assertIn("destroy-unattached on", joined)

    def test_the_option_is_never_set_before_a_client_exists(self) -> None:
        # Measured on a private detached server: setting it while no client is
        # attached destroys the session *immediately* (the server went away), which
        # would kill an ATUI started detached before anyone could look at it.
        plan = self.plan("--project", str(self.repo), "--", CLI)

        self.assertNotIn("destroy-unattached", plan[: plan.index("set-hook")])

    def test_no_signal_trap_appears_anywhere_in_the_launcher(self) -> None:
        # Code, not prose: the incident is *documented* in a comment on purpose,
        # so the assertion is about executable lines only.
        for line in code_lines(LAUNCHER):
            self.assertFalse(line.startswith("trap"), line)

    def test_the_detached_branch_states_that_cleanup_is_not_armed(self) -> None:
        # Without a tty (the agent-derived path) the session is created detached,
        # so the attach hook never fires and the session will not disappear on its
        # own. An unstated caveat here accumulates unreachable pane_refs.
        result = self.run_launcher(
            "--project", str(self.repo), "--dry-run", "--", CLI
        )

        self.assertIn("-d", self.plan("--project", str(self.repo), "--", CLI))
        self.assertIn("首次附着", result.stdout)


class NoInstanceValuesTests(unittest.TestCase):
    def test_the_launcher_hardcodes_no_absolute_home_path(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")

        self.assertNotIn("/home/", source)
        self.assertNotIn("/Users/", source)

    def test_the_launcher_writes_nothing_and_starts_no_registry(self) -> None:
        # It is a launcher, not a registrar: no leaf writing, no directory making
        # (`mkdir -p` is what makes a wrong location look like it always existed).
        for line in code_lines(LAUNCHER):
            for forbidden in ("mkdir", "touch", ">>"):
                self.assertNotIn(forbidden, line)


class GuideAgreementTests(unittest.TestCase):
    """The launcher and its specification must not drift apart."""

    @staticmethod
    def guide() -> str:
        return (
            ROOT / "overlay/spec/guides/agenttui-launch-and-brand-capacity.md"
        ).read_text(encoding="utf-8")

    def test_the_human_machine_isomorphism_invariant_is_written_down(self) -> None:
        guide = self.guide()

        self.assertIn("启动路径必须**人机同构**", guide)
        self.assertIn("atui_launch.sh", guide)

    def test_the_escape_hatch_name_matches_the_script(self) -> None:
        # One name in two places is how a documented escape hatch stops working.
        self.assertIn("ARBORIST_ATUI_LAUNCH_WRAP=0", self.guide())
        self.assertIn(
            "ARBORIST_ATUI_LAUNCH_WRAP", LAUNCHER.read_text(encoding="utf-8")
        )

    def test_the_wiring_status_in_the_guide_matches_reality(self) -> None:
        # A biconditional rather than a snapshot: whoever wires the launcher into
        # the adoption scaffold has to update the guide in the same change, and
        # whoever updates the guide first will see this fail.
        deployed = "atui_launch.sh" in (ROOT / "adopt.sh").read_text(encoding="utf-8")
        claims_unwired = "尚未接线" in self.guide()

        self.assertNotEqual(
            deployed,
            claims_unwired,
            "adopt.sh deployment and the guide's wiring claim disagree",
        )


if __name__ == "__main__":
    unittest.main()
