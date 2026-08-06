#!/usr/bin/env python3
"""Run a diagnostic command so that its own failure cannot be read as its answer.

## Why this exists as a program and not as a paragraph

`verification-and-gates.md` carries the rule "a forensic command is itself
fallible, and its failure arrives dressed as a normal reading", with five measured
instances in one night from two independent parties. Three of those came from one
party who **knew the rule and did not trigger it three times**. That established a
criterion for judging any rule of this kind:

> **A rule's degree of mechanisation equals what omitting it costs you.**
> If omitting it means doing nothing, the rule is zero-mechanised and restating it
> changes nothing. Only when omitting it requires an explicit extra action --
> passing a flag, writing an escape -- is it actually a gate.

Measured against that ruler, two of that rule's three products failed:

- "the exit code must come from the command being diagnosed, not the end of a
  pipe" -- omitting it costs nothing; `cmd | tail; echo $?` is the *easier* thing
  to type.
- "on a first-run negative conclusion, prove the command itself first" -- omitting
  it costs nothing whatsoever. It was pure discipline.

This program is the carrier for both. It keeps the two streams separate (so
silencing stdout can never silence a failure), reports the rc **of the command
itself**, and -- the load-bearing part -- **refuses to hand back a negative
reading on its own**. A negative reading is available only if you also supply a
control known to read positive, or explicitly declare that you are taking an
uncorroborated negative and say why. Both cost an action.

## What counts as "negative", and why the definition is deliberately broad

A reading is negative when the command failed (`rc != 0`), produced no output, or
produced output that is only a zero count. Those are exactly the shapes that
arrive with their own ready-made explanation ("it isn't there", "there are none")
and so get accepted without a second look, while the competing explanation -- "my
command did not test what I think it tested" -- carries no explanatory power at
all and therefore never comes to mind.

## Known disguises (check against this list, do not merely read it)

Every instance so far had the same outer appearance: **the failure looked like a
problem with the subject**. Three distinct mechanisms produce that appearance, and
they are listed rather than described because a list can be gone through
item-by-item while prose can only be read:

| Disguise | The mechanism | What it looked like |
|---|---|---|
| **The command was written wrong** | arguments never split, the wrong path, an incomplete listing | "that commit does not exist" / "the directory is gone" |
| **A stream was swallowed** | `>/dev/null 2>&1` on a diagnostic; `$?` taken after a pipe | "it ran every time" (the subcommand did not exist) / "rc=0, passed" (it refused) |
| **The data was rewritten on its way to the parser** | a shell `echo` interpreting backslash escapes, so `\n` became a real newline | "the program emits invalid JSON" |

The third is the reason this program prints to stdout and expects to be read by a
parser reading the process's stdout directly. Do not route its output through a
shell echo.

## Boundary discipline

Control arguments are read from a **file, one argv token per line**, never split
out of a shell string. This program exists to remove a class of shell accident, so
it must not reintroduce one at its own boundary (same reasoning as the delivery
adapter's `--message-file`).

It runs whatever it is given and is **not** a sandbox: it makes a reading
trustworthy, it does not make a command safe.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


EXIT_OK = 0
# One code per outcome, because "the thing is absent" and "I cannot tell whether
# it is absent" must never share a reading -- that collapse is the whole failure
# this program exists to prevent.
EXIT_NEGATIVE = 1
EXIT_USAGE = 2
EXIT_INCONCLUSIVE = 4
EXIT_PROBE_SUSPECT = 5

ZERO_COUNT = re.compile(r"^\s*0\s*$")


def read_argv_file(path: Path) -> list[str]:
    """One argv token per line. Blank lines and `#` comments are dropped."""

    # NOTE the exit code: `SystemExit("message")` would exit 1, which is this
    # program's code for "negative, corroborated". Colliding those two is exactly
    # the collapse this program exists to prevent -- an operator typo would read as
    # a confirmed finding. Usage errors get EXIT_USAGE and nothing else.
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"probe: cannot read argv file {path}: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE) from exc
    tokens = [
        line.rstrip("\n")
        for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not tokens:
        print(f"probe: argv file {path} yields no tokens", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    return tokens


def run(argv: list[str]) -> dict[str, object]:
    """Run argv, keeping the streams apart and the rc attributable."""

    try:
        completed = subprocess.run(argv, capture_output=True, text=True)
    except OSError as exc:
        # A command that cannot even start is the sharpest instance of the whole
        # problem: the measured case was a subcommand that did not exist, whose
        # failure `2>&1` hid twelve times running.
        return {
            "argv": argv,
            "rc": None,
            "stdout": "",
            "stderr": str(exc),
            "negative_reasons": ["command could not be executed"],
            "verdict": "negative",
        }

    stdout = completed.stdout
    negative_reasons: list[str] = []
    if completed.returncode != 0:
        negative_reasons.append(f"rc={completed.returncode}")
    if not stdout.strip():
        negative_reasons.append("empty stdout")
    elif ZERO_COUNT.match(stdout):
        negative_reasons.append("stdout is a zero count")
    return {
        "argv": argv,
        "rc": completed.returncode,
        "stdout": stdout,
        "stderr": completed.stderr,
        "negative_reasons": negative_reasons,
        "verdict": "negative" if negative_reasons else "positive",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probe",
        description=(
            "run a diagnostic so its own failure cannot be read as its answer; a "
            "negative reading is withheld unless a control proves the probe works"
        ),
    )
    parser.add_argument(
        "--control-file",
        help=(
            "path to an argv file (one token per line) holding a command KNOWN to "
            "read positive. Required to obtain a negative verdict, unless "
            "--accept-unverified-negative is given"
        ),
    )
    parser.add_argument(
        "--accept-unverified-negative",
        metavar="REASON",
        help=(
            "take a negative reading with no control, stating why. The reason is "
            "echoed into the result so a later reader can see the negative was "
            "never corroborated"
        ),
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER, help="the command to run, after `--`"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = [token for token in args.command if token != "--"]
    if not command:
        parser.error("no command given (put it after `--`)")

    result = run(command)

    if result["verdict"] == "positive":
        result["outcome"] = "positive"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return EXIT_OK

    # From here the reading is negative -- exactly the shape that gets accepted
    # without a second look.
    if args.control_file:
        control = run(read_argv_file(Path(args.control_file).expanduser()))
        result["control"] = control
        if control["verdict"] != "positive":
            # The control was supposed to be known-positive and was not, so what is
            # in question is the probe machinery, NOT the subject. Reporting this
            # as a negative finding about the subject IS the bug.
            result["outcome"] = "probe-suspect"
            result["detail"] = (
                "the control was expected to read positive and did not, so this run "
                "says nothing about the subject: the probe itself is in question. "
                "Fix the control (or the command shape) and re-run"
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return EXIT_PROBE_SUSPECT
        result["outcome"] = "negative"
        result["detail"] = "negative, corroborated by a control that read positive"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return EXIT_NEGATIVE

    if args.accept_unverified_negative:
        result["outcome"] = "negative-unverified"
        result["accepted_without_control"] = args.accept_unverified_negative
        result["detail"] = (
            "negative, NOT corroborated: no control was run. Treat as a lead, not a "
            "finding"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return EXIT_NEGATIVE

    result["outcome"] = "inconclusive"
    result["detail"] = (
        "withholding this negative reading: a negative result is also what a broken "
        "probe produces, and nothing here distinguishes the two. Supply "
        "--control-file <argv file with a known-positive command>, or "
        "--accept-unverified-negative '<why>' to record that you are taking it "
        "uncorroborated"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_INCONCLUSIVE


if __name__ == "__main__":
    sys.exit(main())
