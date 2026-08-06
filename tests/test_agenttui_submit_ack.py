"""Tests for the receiver-side submit-ack handshake.

Nothing here may touch the host's real `~/.arborist/`: every ack table lives in a
TemporaryDirectory, and the two subprocess tests run with `HOME` pointed at one,
because the module's default table path is derived from the home directory at
import time. Results must not depend on the machine, and instance values must not
enter the repo.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "overlay/scripts/agenttui_submit_ack.py"
SNIPPETS = {
    "claude-code": ROOT / "overlay/hook-templates/submit-ack/claude-code.snippet.py",
    "codex": ROOT / "overlay/hook-templates/submit-ack/codex.snippet.py",
}


def load_module_from(path: Path, name: str = "agenttui_submit_ack"):
    """Load the module by path, without a package import."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ACK = load_module_from(MODULE_PATH)


def envelope(nonce: str, *, body: str = "short pointer", sender: str = "sender-a",
             target: str = "target-b") -> str:
    """An envelope shaped like the one the sender builds (same field order)."""
    return "\n".join(
        [
            "[ARBORIST-DIRECT:v1]",
            f"from={sender}",
            "from_brand=example-brand",
            f"to={target}",
            f"nonce={nonce}",
            "provenance=declared-not-authenticated",
            "reply_command=python3 agenttui.py send --from x --to y --message <reply>",
            "",
            "message:",
            body,
        ]
    )


def run_main(*argv: str) -> tuple[int, str, str]:
    """Run the module's main, capturing stdout and stderr separately.

    Separate, not merged: this suite asserts on which stream text lands in, and a
    merged capture makes stream membership structurally invisible.
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ACK.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def run_record_cli(payload_text: str, log_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--log",
            str(log_path),
            "record",
            "--brand",
            "example-brand",
            *extra,
        ],
        input=payload_text,
        capture_output=True,
        text=True,
        check=False,
    )


def read_records(log_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class EnvelopeParsingTests(unittest.TestCase):
    def test_matching_prompt_yields_nonce_and_provable_header_fields(self):
        headers = ACK.parse_envelope_headers(envelope("nonce-001"))
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0]["nonce"], "nonce-001")
        self.assertEqual(headers[0]["from"], "sender-a")
        self.assertEqual(headers[0]["to"], "target-b")
        self.assertEqual(headers[0]["from_brand"], "example-brand")

    def test_header_scan_stops_before_the_body(self):
        text = envelope("nonce-002", body="secret=leaked body value")
        headers = ACK.parse_envelope_headers(text)
        self.assertNotIn("secret", headers[0])
        self.assertEqual(set(headers[0]) - {"nonce"}, set(ACK.PROVABLE_HEADER_FIELDS))

    def test_two_envelopes_in_one_prompt_are_both_acked(self):
        text = envelope("nonce-a") + "\n\n" + envelope("nonce-b")
        nonces = [h["nonce"] for h in ACK.parse_envelope_headers(text)]
        self.assertEqual(nonces, ["nonce-a", "nonce-b"])

    def test_non_matching_prompt_yields_nothing(self):
        for text in (
            "",
            "just an ordinary prompt",
            "nonce=looks-like-one but no protocol token",
            "[ARBORIST-DIRECT:v1] mentioned inline in prose, no fields follow",
            "[ARBORIST-DIRECT:v1]\nfrom=sender-a\nto=target-b\n",  # no nonce
        ):
            with self.subTest(text=text[:40]):
                self.assertEqual(ACK.parse_envelope_headers(text), [])

    def test_malformed_nonce_is_not_acked(self):
        text = envelope("bad nonce with spaces")
        self.assertEqual(ACK.parse_envelope_headers(text), [])

    def test_non_string_prompt_is_tolerated(self):
        for value in (None, 17, {"a": 1}, ["x"]):
            with self.subTest(value=value):
                self.assertEqual(ACK.parse_envelope_headers(value), [])


class AppendTests(unittest.TestCase):
    def test_one_line_per_record_and_no_body_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "submit-acks.jsonl"
            payload = {
                "prompt": envelope("nonce-003", body="CONFIDENTIAL-BODY-TOKEN"),
                "cwd": tmp,
                "session_id": "session-placeholder-1",
                "hook_event_name": "UserPromptSubmit",
            }
            records, warnings = ACK.record_submit_ack(
                payload, receiver_brand="example-brand", log_path=log
            )
            self.assertEqual(warnings, [])
            self.assertEqual(len(records), 1)
            raw = log.read_text(encoding="utf-8")
            self.assertEqual(len(raw.splitlines()), 1)
            self.assertNotIn("CONFIDENTIAL-BODY-TOKEN", raw)

    def test_record_carries_the_documented_field_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            ACK.record_submit_ack(
                {
                    "prompt": envelope("nonce-004"),
                    "cwd": tmp,
                    "session_id": "session-placeholder-2",
                    "hook_event_name": "UserPromptSubmit",
                },
                receiver_brand="example-brand",
                log_path=log,
            )
            record = read_records(log)[0]
            self.assertEqual(
                set(record),
                {
                    "ack_version",
                    "nonce",
                    "acked_at",
                    "protocol",
                    "receiver_brand",
                    "receiver_agent",
                    "receiver_project_path",
                    "receiver_project_id",
                    "receiver_session_id",
                    "hook_event",
                    "envelope_header",
                },
            )
            self.assertEqual(record["nonce"], "nonce-004")
            self.assertEqual(record["protocol"], ACK.PROTOCOL)
            self.assertEqual(record["receiver_brand"], "example-brand")
            self.assertEqual(record["receiver_session_id"], "session-placeholder-2")
            self.assertEqual(record["ack_version"], ACK.ACK_RECORD_VERSION)
            # ISO8601 with an offset, so records from two machines can be ordered.
            self.assertRegex(record["acked_at"], r"^\d{4}-\d{2}-\d{2}T.*[+-]\d{2}:\d{2}$")

    def test_unknown_receiver_fields_are_null_not_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            # cwd is a bare directory: no `.trellis/` or `.git/`, so no repo root
            # can be derived and nothing may be guessed.
            plain = Path(tmp) / "not-a-repo"
            plain.mkdir()
            ACK.record_submit_ack(
                {"prompt": envelope("nonce-005"), "cwd": str(plain)},
                receiver_brand=None,
                log_path=log,
            )
            record = read_records(log)[0]
            self.assertIsNone(record["receiver_project_path"])
            self.assertIsNone(record["receiver_project_id"])
            self.assertIsNone(record["receiver_agent"])
            self.assertIsNone(record["receiver_brand"])

    def test_receiver_agent_is_resolved_from_the_registry_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            leaf = repo / ".arborist" / "agents" / "example-agent"
            leaf.mkdir(parents=True)
            (repo / ".trellis").mkdir()
            (leaf / "runtime.json").write_text(
                json.dumps({"session_id": "session-placeholder-3", "state": "active"}),
                encoding="utf-8",
            )
            log = Path(tmp) / "acks.jsonl"
            ACK.record_submit_ack(
                {
                    "prompt": envelope("nonce-006"),
                    "cwd": str(repo),
                    "session_id": "session-placeholder-3",
                },
                receiver_brand="example-brand",
                log_path=log,
            )
            record = read_records(log)[0]
            self.assertEqual(record["receiver_agent"], "example-agent")
            self.assertEqual(record["receiver_project_path"], str(repo.resolve()))

    def test_project_id_comes_from_the_registry_validator_when_it_is_adopted(self):
        """One implementation of the derived id, not two (agenttui-registry §2.3).

        Runs in a copied `.trellis/scripts/` layout because that is where adopt
        puts both files, and the reuse only happens when they are siblings.
        """
        validator = ROOT / "overlay/scripts/validate_agenttui_registry.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            repo = tmpdir / "repo"
            scripts = repo / ".trellis" / "scripts"
            scripts.mkdir(parents=True)
            for source in (MODULE_PATH, validator):
                (scripts / source.name).write_text(
                    source.read_text(encoding="utf-8"), encoding="utf-8"
                )
            log = tmpdir / "acks.jsonl"
            copied = load_module_from(
                scripts / MODULE_PATH.name, name="agenttui_submit_ack_copy"
            )
            copied.record_submit_ack(
                {"prompt": envelope("nonce-pid"), "cwd": str(repo)},
                receiver_brand="example-brand",
                log_path=log,
            )
            record = read_records(log)[0]
            expected = subprocess.run(
                [
                    sys.executable,
                    str(scripts / validator.name),
                    "--print-project-id",
                    str(repo),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(record["receiver_project_id"], expected)

    def test_new_table_is_created_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            ACK.append_ack_records([{"nonce": "n"}], log)
            self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)

    def test_existing_mode_is_preserved_not_tightened(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            log.write_text("", encoding="utf-8")
            os.chmod(log, 0o644)
            ACK.append_ack_records([{"nonce": "n"}], log)
            self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o644)

    def test_write_failure_is_reported_and_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            # A directory where the file should be: opening it for append fails.
            log = Path(tmp) / "acks.jsonl"
            log.mkdir()
            written, warning = ACK.append_ack_records([{"nonce": "n"}], log)
            self.assertEqual(written, 0)
            self.assertIsNotNone(warning)
            self.assertIn("unconfirmed", warning)

    def test_record_submit_ack_never_raises_on_hostile_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            for payload in (
                None,
                [],
                "a string",
                {},
                {"prompt": None},
                {"prompt": envelope("nonce-007"), "cwd": 17},
                {"prompt": envelope("nonce-008"), "cwd": "/nonexistent/" + "x" * 40},
            ):
                with self.subTest(payload=repr(payload)[:40]):
                    records, warnings = ACK.record_submit_ack(
                        payload, receiver_brand="example-brand", log_path=log
                    )
                    self.assertIsInstance(records, list)
                    self.assertIsInstance(warnings, list)


class ConcurrentAppendTests(unittest.TestCase):
    def test_twelve_concurrent_writers_lose_no_records(self):
        """Append-only, one write per record: concurrent ATUIs cannot clobber.

        Separate processes rather than threads, because the failure this guards
        against (read-modify-write) is only visible across processes.
        """
        count = 12
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            # Payloads on disk rather than through pipes, so all writers really do
            # overlap instead of being fed one at a time.
            handles, procs, err_paths = [], [], []
            for index in range(count):
                payload_path = Path(tmp) / f"payload-{index:02d}.json"
                payload_path.write_text(
                    json.dumps(
                        {"prompt": envelope(f"nonce-concurrent-{index:02d}"), "cwd": tmp}
                    ),
                    encoding="utf-8",
                )
                err_path = Path(tmp) / f"stderr-{index:02d}.txt"
                err_paths.append(err_path)
                stdin_handle = payload_path.open("rb")
                err_handle = err_path.open("wb")
                handles.extend([stdin_handle, err_handle])
                procs.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            str(MODULE_PATH),
                            "--log",
                            str(log),
                            "record",
                            "--brand",
                            "example-brand",
                        ],
                        stdin=stdin_handle,
                        stdout=subprocess.DEVNULL,
                        stderr=err_handle,
                    )
                )
            codes = [proc.wait() for proc in procs]
            for handle in handles:
                handle.close()
            self.assertEqual(codes, [0] * count)
            self.assertEqual(
                [p.read_text(encoding="utf-8") for p in err_paths], [""] * count
            )
            records = read_records(log)
            self.assertEqual(len(records), count)
            self.assertEqual(
                sorted(r["nonce"] for r in records),
                sorted(f"nonce-concurrent-{i:02d}" for i in range(count)),
            )


class RecordCliTests(unittest.TestCase):
    """`record` must be inert from the host's point of view: exit 0, empty stdout."""

    def test_stdout_is_always_empty_and_exit_is_always_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            payloads = [
                json.dumps({"prompt": envelope("nonce-cli-1"), "cwd": tmp}),
                json.dumps({"prompt": "an ordinary prompt", "cwd": tmp}),
                json.dumps({"no_prompt_key": True}),
                "",
                "not json at all {{{",
                "[1, 2, 3]",
            ]
            for payload in payloads:
                with self.subTest(payload=payload[:30]):
                    result = run_record_cli(payload, log)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")

    def test_unwritable_table_still_exits_zero_with_a_stderr_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            log.mkdir()
            result = run_record_cli(
                json.dumps({"prompt": envelope("nonce-cli-2"), "cwd": tmp}), log
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("warning", result.stderr)

    def test_quiet_suppresses_the_warning_but_not_the_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            log.mkdir()
            result = run_record_cli(
                json.dumps({"prompt": envelope("nonce-cli-3"), "cwd": tmp}),
                log,
                "--quiet",
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")

    def test_print_path_reports_the_table_without_writing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            code, out, _err = run_main("--log", str(log), "print-path")
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), str(log))
            self.assertFalse(log.exists())


class LookupTests(unittest.TestCase):
    def test_acked_nonce_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            ACK.record_submit_ack(
                {"prompt": envelope("nonce-look-1"), "cwd": tmp},
                receiver_brand="example-brand",
                log_path=log,
            )
            code, out, _err = run_main("--log", str(log), "lookup", "--nonce", "nonce-look-1")
            self.assertEqual(code, ACK.EXIT_ACKED)
            reading = json.loads(out)
            self.assertEqual(reading["ack_status"], ACK.ACK_STATUS_ACKED)
            self.assertEqual(reading["ack_count"], 1)
            self.assertIn("do not resend", reading["reading_guidance"])

    def test_absent_ack_is_unconfirmed_never_not_submitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            code, out, _err = run_main("--log", str(log), "lookup", "--nonce", "nonce-absent")
            self.assertEqual(code, ACK.EXIT_UNCONFIRMED)
            reading = json.loads(out)
            self.assertEqual(reading["ack_status"], ACK.ACK_STATUS_UNCONFIRMED)
            self.assertTrue(reading["table_readable"])
            self.assertIn("NOT", reading["reading_guidance"])

    def test_unreadable_table_is_unconfirmed_with_its_own_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            log.mkdir()  # exists, cannot be read as a file
            code, out, _err = run_main("--log", str(log), "lookup", "--nonce", "nonce-x")
            self.assertEqual(code, ACK.EXIT_TABLE_UNREADABLE)
            reading = json.loads(out)
            self.assertEqual(reading["ack_status"], ACK.ACK_STATUS_UNCONFIRMED)
            self.assertFalse(reading["table_readable"])

    def test_malformed_lines_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "acks.jsonl"
            log.write_text(
                "not json\n"
                + json.dumps({"nonce": "nonce-look-2", "acked_at": "2000-01-01T00:00:00+00:00"})
                + "\n[1,2]\n\n",
                encoding="utf-8",
            )
            reading = ACK.lookup_ack("nonce-look-2", log)
            self.assertEqual(reading["ack_status"], ACK.ACK_STATUS_ACKED)
            self.assertEqual(reading["ack_count"], 1)

    def test_status_vocabulary_has_no_not_submitted_value(self):
        """The fail-safe direction is encoded in the value domain, not in prose."""
        statuses = {
            value
            for name, value in vars(ACK).items()
            if name.startswith("ACK_STATUS_") and isinstance(value, str)
        }
        self.assertEqual(statuses, {"acked", "unconfirmed"})


class DefaultTablePathTests(unittest.TestCase):
    def test_default_is_global_and_is_never_written_by_this_suite(self):
        self.assertEqual(ACK.ACK_LOG_DEFAULT, Path.home() / ".arborist" / "submit-acks.jsonl")


class SnippetNonPerturbationTests(unittest.TestCase):
    """Form B must not change the host hook's existing behaviour or output.

    The proof is a differential run: an existing-hook fixture is executed with and
    without the snippet pasted in, and both stdout and the exit code must be
    byte-identical. The same fixture also proves the snippet is not merely inert
    -- the ack really lands in the table.
    """

    FIXTURE = (
        "import json, sys\n"
        "data = json.loads(sys.stdin.read() or '{}')\n"
        "# __SNIPPET__\n"
        "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',"
        " 'additionalContext': 'breadcrumb'}}))\n"
        "sys.exit(0)\n"
    )

    def _run(self, script: Path, payload: str, home: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["HOME"] = str(home)
        env.pop("USERPROFILE", None)
        return subprocess.run(
            [sys.executable, str(script)],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_snippet_leaves_stdout_and_exit_code_identical(self):
        for brand, snippet_path in SNIPPETS.items():
            with self.subTest(brand=brand), tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                repo = tmpdir / "repo"
                scripts = repo / ".trellis" / "scripts"
                scripts.mkdir(parents=True)
                (scripts / "agenttui_submit_ack.py").write_text(
                    MODULE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
                )
                home = tmpdir / "home"
                home.mkdir()

                plain = tmpdir / "hook_plain.py"
                plain.write_text(self.FIXTURE, encoding="utf-8")
                patched = tmpdir / "hook_patched.py"
                patched.write_text(
                    self.FIXTURE.replace(
                        "# __SNIPPET__", snippet_path.read_text(encoding="utf-8")
                    ),
                    encoding="utf-8",
                )

                payload = json.dumps(
                    {
                        "prompt": envelope(f"nonce-snippet-{brand}"),
                        "cwd": str(repo),
                        "session_id": "session-placeholder-4",
                        "hook_event_name": "UserPromptSubmit",
                    }
                )
                before = self._run(plain, payload, home)
                after = self._run(patched, payload, home)

                self.assertEqual(before.stdout, after.stdout)
                self.assertEqual(before.returncode, after.returncode)
                self.assertEqual(after.returncode, 0)

                # ... and it did record, so the identical output is not because
                # the snippet did nothing.
                table = home / ".arborist" / "submit-acks.jsonl"
                self.assertTrue(table.exists(), after.stderr)
                nonces = [r["nonce"] for r in read_records(table)]
                self.assertEqual(nonces, [f"nonce-snippet-{brand}"])

    def test_snippet_keeps_hook_succeeding_when_the_ack_write_fails(self):
        for brand, snippet_path in SNIPPETS.items():
            with self.subTest(brand=brand), tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                repo = tmpdir / "repo"
                scripts = repo / ".trellis" / "scripts"
                scripts.mkdir(parents=True)
                (scripts / "agenttui_submit_ack.py").write_text(
                    MODULE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
                )
                home = tmpdir / "home"
                # A directory where the ack table belongs: every write fails.
                (home / ".arborist" / "submit-acks.jsonl").mkdir(parents=True)

                plain = tmpdir / "hook_plain.py"
                plain.write_text(self.FIXTURE, encoding="utf-8")
                patched = tmpdir / "hook_patched.py"
                patched.write_text(
                    self.FIXTURE.replace(
                        "# __SNIPPET__", snippet_path.read_text(encoding="utf-8")
                    ),
                    encoding="utf-8",
                )
                payload = json.dumps(
                    {"prompt": envelope(f"nonce-fail-{brand}"), "cwd": str(repo)}
                )
                before = self._run(plain, payload, home)
                after = self._run(patched, payload, home)

                self.assertEqual(after.returncode, 0)
                self.assertEqual(before.stdout, after.stdout)
                self.assertIn("warning", after.stderr)

    def test_snippet_is_inert_when_the_module_is_not_adopted(self):
        for brand, snippet_path in SNIPPETS.items():
            with self.subTest(brand=brand), tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                repo = tmpdir / "repo"
                repo.mkdir()
                home = tmpdir / "home"
                home.mkdir()
                patched = tmpdir / "hook_patched.py"
                patched.write_text(
                    self.FIXTURE.replace(
                        "# __SNIPPET__", snippet_path.read_text(encoding="utf-8")
                    ),
                    encoding="utf-8",
                )
                result = self._run(
                    patched,
                    json.dumps({"prompt": envelope("nonce-none"), "cwd": str(repo)}),
                    home,
                )
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
                self.assertFalse((home / ".arborist").exists())



class FlattenedEnvelopeTests(unittest.TestCase):
    """A flattened envelope must still be acked, or the failure is silent.

    An envelope is written into a composer and then handed to a hook; neither the
    composer's newline handling nor a brand's hook payload normalisation is under
    this repo's control. If only the multi-line form parsed, a flattened envelope
    would yield **no ack at all** -- and that reads exactly like "the target never
    submitted", which is the confusion this facility exists to remove.
    """

    NONCE = "deadbeef-0000-4000-8000-abcdefabcdef"

    def parse(self, text):
        return ACK.parse_envelope_headers(text)

    def test_all_fields_on_one_line_is_parsed(self) -> None:
        headers = self.parse(
            f"[ARBORIST-DIRECT:v1] from=sender-a from_brand=claude-code "
            f"to=target-b nonce={self.NONCE} provenance=declared-not-authenticated  "
            "message: body text"
        )

        self.assertEqual(1, len(headers))
        self.assertEqual(self.NONCE, headers[0]["nonce"])
        self.assertEqual("sender-a", headers[0]["from"])

    def test_multi_line_form_still_parsed(self) -> None:
        headers = self.parse(
            "\n".join(
                [
                    "[ARBORIST-DIRECT:v1]",
                    "from=sender-a",
                    "to=target-b",
                    f"nonce={self.NONCE}",
                    "",
                    "message:",
                    "body text",
                ]
            )
        )

        self.assertEqual(1, len(headers))
        self.assertEqual(self.NONCE, headers[0]["nonce"])

    def test_flattened_body_never_contributes_a_field(self) -> None:
        # The body is cut at the marker, so `key=value` inside prose cannot be
        # mistaken for a header field.
        headers = self.parse(
            f"[ARBORIST-DIRECT:v1] to=target-b nonce={self.NONCE}  "
            "message: set from=somebody-else and to=wrong-target"
        )

        self.assertEqual(1, len(headers))
        self.assertNotIn("from", headers[0])
        self.assertEqual("target-b", headers[0]["to"])

    def test_flattened_without_a_nonce_is_dropped(self) -> None:
        self.assertEqual([], self.parse("[ARBORIST-DIRECT:v1] from=a to=b  message: x"))

    def test_bare_mention_in_prose_is_not_an_envelope(self) -> None:
        self.assertEqual([], self.parse("[ARBORIST-DIRECT:v1] mentioned in prose only"))


if __name__ == "__main__":
    unittest.main()
