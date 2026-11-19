#!/usr/bin/env python3
"""Set a Trellis project's Codex dispatch mode without rewriting its YAML.

Trellis currently reads this setting only from the project-local
``.trellis/config.yaml``.  Arborist calls this helper during ``adopt.sh`` so a
newly adopted project gets the machine owner's preferred sub-agent behavior
without patching the globally installed Trellis npm package.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


CODEX_HEADER = re.compile(r"^codex:\s*(?:#.*)?$")
TOP_LEVEL_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*:\s*(?:.*)?$")
DISPATCH_KEY = re.compile(r"^(\s+)dispatch_mode\s*:")


def set_subagent_mode(config: Path) -> bool:
    """Set ``codex.dispatch_mode`` to ``sub-agent`` and return whether changed."""

    try:
        text = config.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    lines = text.splitlines(keepends=True)
    codex_headers = [
        index
        for index, line in enumerate(lines)
        if CODEX_HEADER.fullmatch(line.rstrip("\r\n"))
    ]
    if len(codex_headers) > 1:
        raise ValueError(f"multiple top-level codex blocks in {config}")

    if not codex_headers:
        separator = "" if not text or text.endswith("\n\n") else "\n"
        updated = f"{text}{separator}codex:\n  dispatch_mode: sub-agent\n"
    else:
        start = codex_headers[0]
        end = len(lines)
        for index in range(start + 1, len(lines)):
            candidate = lines[index].rstrip("\r\n")
            if candidate and not candidate.startswith((" ", "\t", "#")):
                if TOP_LEVEL_KEY.fullmatch(candidate):
                    end = index
                    break

        dispatch_index = None
        dispatch_indent = "  "
        for index in range(start + 1, end):
            match = DISPATCH_KEY.match(lines[index].rstrip("\r\n"))
            if match:
                if dispatch_index is not None:
                    raise ValueError(f"multiple codex.dispatch_mode keys in {config}")
                dispatch_index = index
                dispatch_indent = match.group(1)

        if dispatch_index is None:
            lines.insert(start + 1, "  dispatch_mode: sub-agent\n")
        else:
            newline = "\r\n" if lines[dispatch_index].endswith("\r\n") else "\n"
            lines[dispatch_index] = (
                f"{dispatch_indent}dispatch_mode: sub-agent{newline}"
            )
        updated = "".join(lines)

    if updated == text:
        return False
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set codex.dispatch_mode to sub-agent in a Trellis config"
    )
    parser.add_argument("config", type=Path, help="path to .trellis/config.yaml")
    args = parser.parse_args()

    try:
        changed = set_subagent_mode(args.config)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"{'updated' if changed else 'already configured'}: {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
