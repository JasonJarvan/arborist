from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_capacity_module():
    """Load the overlay observer script by path, without a package import."""
    module_path = ROOT / "overlay/scripts/arborist_brand_capacity.py"
    module_name = "arborist_brand_capacity"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


capacity = load_capacity_module()


# Placeholder identifiers for tests only — neutral, not instance/runtime values.
PLACEHOLDER_PROJECT_ID = "test-project"
PLACEHOLDER_AGENT = "example-impler"


class BrandCapacityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name)
        self.config = self.repo / ".work_context/sendbox/_handoff-config.yaml"
        self.config.parent.mkdir(parents=True)
        # Mirror the host route-config shape: supported_brands nested under
        # brand_routing. The parser matches by indentation, not the parent key.
        self.config.write_text(
            "brand_routing:\n"
            "  supported_brands:\n"
            "    - codex\n"
            "    - claude-code\n"
            "  same_brand_policy: strict\n",
            encoding="utf-8",
        )
        self.sessions = self.repo / "codex-sessions"
        self.sessions.mkdir()
        self.state = self.repo / ".arborist/runtime/brand-capacity.json"
        self.reports = self.repo / ".arborist/runtime/brand-capacity-reports"
        self.lock = self.repo / ".arborist/runtime/brand-capacity.lock"
        self.now = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)

    # --- fixtures ---------------------------------------------------------

    def write_codex_rollout(
        self,
        *,
        name: str,
        observed_at: str,
        used_percent: float,
        window_minutes: int = 10080,
    ) -> None:
        payload = {
            "timestamp": observed_at,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "rate_limits": {
                        "limit_id": "codex",
                        "primary": {
                            "used_percent": used_percent,
                            "window_minutes": window_minutes,
                            "resets_at": 1785611988,
                        },
                        "secondary": None,
                    }
                },
            },
        }
        (self.sessions / name).write_text(
            json.dumps(payload) + "\n", encoding="utf-8"
        )

    def write_agent(self, name: str, brand: str) -> None:
        leaf = self.repo / ".arborist/agents" / name
        leaf.mkdir(parents=True)
        (leaf / "spec.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "role": "impler",
                    "brand": brand,
                    "project": {
                        "path": str(self.repo),
                        "project_id": PLACEHOLDER_PROJECT_ID,
                    },
                }
            ),
            encoding="utf-8",
        )

    def claude_usage_output(self, result_text: str, **overrides) -> str:
        payload = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 0,
            "total_cost_usd": 0,
            "result": result_text,
        }
        payload.update(overrides)
        return json.dumps(payload)

    # --- closed-set loading ----------------------------------------------

    def test_supported_brands_come_only_from_host_contract(self) -> None:
        self.assertEqual(
            capacity.load_supported_brands(self.config),
            ["codex", "claude-code"],
        )

    def test_installed_but_unsupported_cli_never_becomes_a_row(self) -> None:
        self.write_codex_rollout(
            name="rollout-current.jsonl",
            observed_at="2026-07-29T03:58:00Z",
            used_percent=25,
        )
        snapshot = capacity.refresh_snapshot(
            repo_root=self.repo,
            config_path=self.config,
            codex_sessions=self.sessions,
            state_path=self.state,
            reports_dir=self.reports,
            now=self.now,
        )
        # gemini is installed-in-the-world but absent from the closed set.
        self.assertNotIn("gemini", snapshot["brands"])
        self.assertEqual(set(snapshot["brands"]), {"codex", "claude-code"})

    # --- newest observation wins -----------------------------------------

    def test_latest_codex_rate_limit_record_wins(self) -> None:
        self.write_codex_rollout(
            name="rollout-old.jsonl",
            observed_at="2026-07-29T03:20:00Z",
            used_percent=80,
        )
        self.write_codex_rollout(
            name="rollout-new.jsonl",
            observed_at="2026-07-29T03:58:00Z",
            used_percent=25,
        )

        record = capacity.find_latest_codex_capacity(self.sessions)

        self.assertEqual(record["source"], "polled")
        self.assertEqual(record["observed_at"], "2026-07-29T03:58:00Z")
        self.assertEqual(record["windows"][0]["used_percent"], 25.0)
        self.assertEqual(record["windows"][0]["window_minutes"], 10080)

    # --- unknown rows stay explicit --------------------------------------

    def test_refresh_keeps_unknown_brand_explicit(self) -> None:
        self.write_codex_rollout(
            name="rollout-current.jsonl",
            observed_at="2026-07-29T03:58:00Z",
            used_percent=25,
        )

        snapshot = capacity.refresh_snapshot(
            repo_root=self.repo,
            config_path=self.config,
            codex_sessions=self.sessions,
            state_path=self.state,
            reports_dir=self.reports,
            now=self.now,
        )

        self.assertEqual(snapshot["supported_brands"], ["codex", "claude-code"])
        self.assertEqual(snapshot["brands"]["codex"]["status"], "observed")
        claude = snapshot["brands"]["claude-code"]
        self.assertEqual(claude["status"], "unknown")
        self.assertEqual(claude["source"], "unavailable")
        self.assertIsNone(claude["observed_at"])
        self.assertEqual(claude["windows"], [])
        # The persisted snapshot equals the returned value (atomic write).
        self.assertEqual(json.loads(self.state.read_text()), snapshot)

    # --- self-report brand mismatch --------------------------------------

    def test_self_report_requires_agent_brand_to_match(self) -> None:
        self.write_agent(PLACEHOLDER_AGENT, "claude-code")
        report = {
            "observed_at": "2026-07-29T03:55:00Z",
            "source": "self-reported",
            "windows": [
                {
                    "name": "five-hour",
                    "used_percent": 40,
                    "window_minutes": 300,
                    "resets_at": 1785611988,
                }
            ],
        }

        written = capacity.write_self_report(
            repo_root=self.repo,
            reports_dir=self.reports,
            agent_name=PLACEHOLDER_AGENT,
            payload=report,
        )
        self.assertEqual(written["brand"], "claude-code")
        self.assertEqual(written["agent"], PLACEHOLDER_AGENT)
        stored = json.loads(
            (self.reports / f"{PLACEHOLDER_AGENT}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored, written)

        # A report claiming a brand that disagrees with the registered spec is
        # refused; a mislabeled self-report never lands as headroom.
        report["brand"] = "codex"
        with self.assertRaisesRegex(capacity.CapacityError, "brand mismatch"):
            capacity.write_self_report(
                repo_root=self.repo,
                reports_dir=self.reports,
                agent_name=PLACEHOLDER_AGENT,
                payload=report,
            )

    # --- fresh capacity beats role affinity ------------------------------

    def test_recommend_uses_fresh_headroom_before_role_preference(self) -> None:
        snapshot = {
            "schema_version": 1,
            "generated_at": "2026-07-29T04:00:00Z",
            "supported_brands": ["codex", "claude-code"],
            "brands": {
                "codex": {
                    "status": "observed",
                    "source": "polled",
                    "observed_at": "2026-07-29T03:58:00Z",
                    "windows": [{"name": "weekly", "used_percent": 95.0}],
                },
                "claude-code": {
                    "status": "observed",
                    "source": "self-reported",
                    "observed_at": "2026-07-29T03:59:00Z",
                    "windows": [{"name": "weekly", "used_percent": 20.0}],
                },
            },
        }

        recommendation = capacity.recommend_brand(
            snapshot, role="impler", now=self.now, max_age_seconds=900
        )

        # impler affinity prefers codex, but claude-code has far more headroom.
        self.assertEqual(recommendation["recommended_brand"], "claude-code")
        self.assertEqual(recommendation["decision_quality"], "fresh-capacity")
        self.assertEqual(
            recommendation["selection_scope"], "impler-creation-only"
        )

    # --- fallback to role affinity when everything is unknown ------------

    def test_recommend_falls_back_to_role_affinity_when_unknown(self) -> None:
        snapshot = {
            "schema_version": 1,
            "generated_at": "2026-07-29T04:00:00Z",
            "supported_brands": ["codex", "claude-code"],
            "brands": {
                "codex": {
                    "status": "unknown",
                    "source": "unavailable",
                    "observed_at": None,
                    "windows": [],
                },
                "claude-code": {
                    "status": "unknown",
                    "source": "unavailable",
                    "observed_at": None,
                    "windows": [],
                },
            },
        }

        impler = capacity.recommend_brand(
            snapshot, role="impler", now=self.now, max_age_seconds=900
        )
        orchestrator = capacity.recommend_brand(
            snapshot, role="orchestrator", now=self.now, max_age_seconds=900
        )

        self.assertEqual(impler["recommended_brand"], "codex")
        self.assertEqual(orchestrator["recommended_brand"], "claude-code")
        self.assertEqual(impler["decision_quality"], "role-affinity-fallback")
        self.assertEqual(impler["selection_scope"], "impler-creation-only")

    def test_stale_observation_is_not_fresh_headroom(self) -> None:
        snapshot = {
            "schema_version": 1,
            "generated_at": "2026-07-29T04:00:00Z",
            "supported_brands": ["codex", "claude-code"],
            "brands": {
                "codex": {
                    "status": "observed",
                    "source": "polled",
                    # Two hours old — well beyond max_age.
                    "observed_at": "2026-07-29T02:00:00Z",
                    "windows": [{"name": "weekly", "used_percent": 5.0}],
                },
                "claude-code": {
                    "status": "unknown",
                    "source": "unavailable",
                    "observed_at": None,
                    "windows": [],
                },
            },
        }

        recommendation = capacity.recommend_brand(
            snapshot, role="impler", now=self.now, max_age_seconds=900
        )
        self.assertEqual(recommendation["decision_quality"], "role-affinity-fallback")
        codex_candidate = next(
            c for c in recommendation["candidates"] if c["brand"] == "codex"
        )
        self.assertFalse(codex_candidate["fresh"])

    def test_recommend_rejects_unknown_role(self) -> None:
        snapshot = {
            "schema_version": 1,
            "generated_at": "2026-07-29T04:00:00Z",
            "supported_brands": ["codex"],
            "brands": {
                "codex": {
                    "status": "unknown",
                    "source": "unavailable",
                    "observed_at": None,
                    "windows": [],
                }
            },
        }
        with self.assertRaisesRegex(capacity.CapacityError, "role must be"):
            capacity.recommend_brand(snapshot, role="reviewer", now=self.now)


class ClaudeCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)

    def usage_output(self, result_text: str, **overrides) -> str:
        payload = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 0,
            "total_cost_usd": 0,
            "result": result_text,
        }
        payload.update(overrides)
        return json.dumps(payload)

    def test_mechanical_usage_is_parsed_into_windows(self) -> None:
        # Synthetic usage text: format strings only, not real usage numbers.
        result_text = (
            "You are currently on a subscription plan.\n\n"
            "Current session: 2% used\n"
            "Current week (all models): 18% used\n"
            "Current week (Opus): 0% used\n"
            "Approximate, based on local sessions on this machine.\n"
        )
        record = capacity.parse_claude_usage_response(
            self.usage_output(result_text), observed_at=self.now
        )
        self.assertEqual(record["source"], "polled")
        self.assertEqual(record["observed_at"], "2026-07-29T04:00:00Z")
        self.assertEqual(
            record["windows"],
            [
                {"name": "current-session", "used_percent": 2.0},
                {"name": "current-week-all-models", "used_percent": 18.0},
                {"name": "current-week-opus", "used_percent": 0.0},
            ],
        )

    def test_collector_fails_closed_on_model_turn(self) -> None:
        output = self.usage_output(
            "Current session: 2% used", num_turns=1, total_cost_usd=0.01
        )
        with self.assertRaisesRegex(
            capacity.CapacityError, "refusing non-mechanical output"
        ):
            capacity.parse_claude_usage_response(output, observed_at=self.now)

    def test_collector_fails_closed_on_error_result(self) -> None:
        output = self.usage_output(
            "Current session: 2% used", is_error=True, subtype="error_during_execution"
        )
        with self.assertRaisesRegex(capacity.CapacityError, "error result"):
            capacity.parse_claude_usage_response(output, observed_at=self.now)

    def test_collector_fails_closed_on_format_drift(self) -> None:
        # Valid mechanical envelope but no recognizable usage line.
        output = self.usage_output("Usage information is temporarily unavailable.")
        with self.assertRaisesRegex(
            capacity.CapacityError, "no recognized capacity windows"
        ):
            capacity.parse_claude_usage_response(output, observed_at=self.now)

    def test_poll_detaches_stdin_and_clears_parent_identity(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=self.usage_output("Current session: 2% used"),
            stderr="",
        )
        with (
            mock.patch.object(
                capacity.shutil, "which", return_value="/usr/bin/claude"
            ),
            mock.patch.object(
                capacity.subprocess, "run", return_value=completed
            ) as run,
            mock.patch.dict(
                capacity.os.environ, {"TRELLIS_CONTEXT_ID": "parent-session"}
            ),
        ):
            record = capacity.find_claude_capacity("claude", observed_at=self.now)

        self.assertEqual(record["source"], "polled")
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertNotIn("TRELLIS_CONTEXT_ID", kwargs["env"])

    def test_poll_fails_closed_on_nonzero_exit(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="boom"
        )
        with (
            mock.patch.object(
                capacity.shutil, "which", return_value="/usr/bin/claude"
            ),
            mock.patch.object(capacity.subprocess, "run", return_value=completed),
        ):
            with self.assertRaisesRegex(capacity.CapacityError, "exited with status"):
                capacity.find_claude_capacity("claude", observed_at=self.now)


class WriterLockAndAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name)
        self.lock = self.repo / ".arborist/runtime/brand-capacity.lock"

    def test_second_writer_fails_closed_while_lock_is_held(self) -> None:
        with capacity.exclusive_lock(self.lock):
            with self.assertRaisesRegex(capacity.CapacityError, "already running"):
                with capacity.exclusive_lock(self.lock):
                    pass

    def test_atomic_write_leaves_no_temp_file(self) -> None:
        target = self.repo / ".arborist/runtime/brand-capacity.json"
        capacity.atomic_write_json(target, {"schema_version": 1})
        self.assertEqual(json.loads(target.read_text()), {"schema_version": 1})
        leftovers = list(target.parent.glob(".brand-capacity.json.tmp-*"))
        self.assertEqual(leftovers, [])
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
