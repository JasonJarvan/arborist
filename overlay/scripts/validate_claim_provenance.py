#!/usr/bin/env python3
"""Require a canonical claim-provenance table in done letters / acceptance evidence.

The gate this script mechanizes: **a conclusion that a downstream reader will
act on must carry its own provenance**. Prose around the table may explain
context, but it is not acceptance evidence; only rows of the canonical table
are. Every row must say what was concluded, whether that conclusion was
*observed* or *inferred*, where a second reader can re-check it, and which step
is still unverified.

Canonical table, schema **v1** (four columns, in this order)::

    | 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |

The header spelling is a *schema choice of this framework*, not a business
coupling: the checker matches these four names exactly (an optional
parenthesised annotation on a column, such as the `（实测/推断）` above, is
stripped before comparison). There are deliberately **no English aliases and no
fuzzy header guessing** — a table whose header this script does not recognise is
reported as missing, never half-validated. Adding an alias is a *versioned
schema change*: declare a v2 header set here and in the templates, do not teach
the matcher to guess.

Two checks run over every document:

1. **per-row contract** — 结论 / 出处 / 未验证缺口 must be non-empty and not a
   placeholder; 类别 must be exactly `实测` or `推断`; an `推断` row must name
   the step that is still unverified, so `推断 + 未验证缺口=无` fails. An
   `实测` row with genuinely no gap writes `无`, never a blank.
2. **gap specificity** — from **4 rows** up, a table whose every gap cell is the
   same non-`无` string fails. One copied constant satisfies the required column
   without carrying information: it makes readers skip the whole column and
   drowns the rows that really do have that gap. A shared limitation is allowed,
   but each row must say how it constrains *that* row's conclusion. Below four
   rows the same real gap may legitimately repeat.

**Execution model (read this before claiming CI enforces it).** The gate has
exactly two consumption points, both *inside* the flow that consumes the
evidence:

* before a new done letter is sent, and
* before new or substantially rewritten acceptance evidence is accepted.

It is **not** a generic task hook, and no CI job can enforce it for an
arbitrary adopter: done letters live in a sendbox that is typically excluded
from the product git (see the sendbox guide's form A / form B), so a CI runner
usually cannot even see the file. What CI can check is this script's own
behaviour; what enforces the gate on real letters is the person or agent at
those two moments running it on the exact paths.

Exit codes: 0 valid; 1 validation failure; 2 usage / environment problem
(unreadable input — fail closed, nothing validated).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence


# Canonical v1 column names, in order. Compared exactly after normalisation; a
# spelling that is not in this tuple is not a v1 table.
CANONICAL_HEADERS_V1 = ("结论", "类别", "出处", "未验证缺口")

# The canonical header as written in the templates (annotation included).
CANONICAL_HEADER_ROW = "| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |"

ALLOWED_KINDS = ("实测", "推断")

# Cells that look filled but carry no claim. Compared case-folded.
EMPTY_MARKERS = frozenset(
    {"", "-", "—", "–", "n/a", "na", "none", "null", "tbd", "todo", "待补", "待确认", "?", "？"}
)

# "There is no gap here." Legal for 实测, a failure for 推断.
NO_GAP_MARKERS = frozenset({"无", "none", "n/a", "na", "-", "—", "–"})

SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")

# One trailing parenthesised annotation, fullwidth or ASCII parens. Stripped
# only when what remains is exactly a canonical name (see normalize_header).
HEADER_ANNOTATION = re.compile(r"(（[^（）]*）|\([^()]*\))\s*$")

# A placeholder cell in a template: `<...>`.
PLACEHOLDER_CELL = re.compile(r"^<.*>$")

REPEATED_GAP_MIN_ROWS = 4


def parse_table_row(line: str) -> list[str] | None:
    """Split a Markdown table row into cells, or return None if it is not one."""

    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def normalize_cell(cell: str) -> str:
    """Strip Markdown emphasis / code ticks / spacing, then case-fold."""

    return cell.strip().strip("*_`").strip().casefold()


def normalize_header(cell: str) -> str:
    """Normalise a header cell to its canonical column name, if it is one.

    An annotation in parentheses is dropped, but *only* when the remainder is
    exactly a canonical name — so `类别（实测/推断）` matches `类别`, while an
    unrelated name is left untouched and simply fails to match.
    """

    normalized = cell.strip().strip("*_`").strip()
    if normalized in CANONICAL_HEADERS_V1:
        return normalized
    without_annotation = HEADER_ANNOTATION.sub("", normalized).strip()
    if without_annotation in CANONICAL_HEADERS_V1:
        return without_annotation
    return normalized


def is_canonical_header(cells: list[str] | None) -> bool:
    if cells is None or len(cells) != len(CANONICAL_HEADERS_V1):
        return False
    return tuple(normalize_header(cell) for cell in cells) == CANONICAL_HEADERS_V1


def is_empty_or_placeholder(cell: str) -> bool:
    normalized = normalize_cell(cell)
    return normalized in EMPTY_MARKERS or PLACEHOLDER_CELL.fullmatch(normalized) is not None


def is_no_gap(cell: str) -> bool:
    return normalize_cell(cell) in NO_GAP_MARKERS


def validate_claim_row(path: Path, line_number: int, cells: list[str]) -> list[str]:
    """Check one data row against the per-row contract."""

    prefix = f"{path}:{line_number}"
    if len(cells) != len(CANONICAL_HEADERS_V1):
        return [
            f"{prefix}: claim row must have {len(CANONICAL_HEADERS_V1)} columns, "
            f"got {len(cells)}"
        ]

    claim, kind, source, gap = cells
    errors: list[str] = []
    if is_empty_or_placeholder(claim):
        errors.append(f"{prefix}: 结论 must not be empty")
    if kind.strip().strip("*_`").strip() not in ALLOWED_KINDS:
        errors.append(
            f"{prefix}: 类别 must be {ALLOWED_KINDS[0]} or {ALLOWED_KINDS[1]} "
            "(split a row that mixes both)"
        )
    if is_empty_or_placeholder(source):
        errors.append(f"{prefix}: 出处 must not be empty")
    if is_empty_or_placeholder(gap):
        errors.append(f"{prefix}: 未验证缺口 must not be empty (write 无 if there is none)")
    elif kind.strip().strip("*_`").strip() == "推断" and is_no_gap(gap):
        errors.append(f"{prefix}: 推断 must name an unverified gap")
    return errors


def validate_table_gap_specificity(
    path: Path,
    header_line: int,
    rows: list[tuple[int, list[str]]],
) -> list[str]:
    """Reject a table whose whole gap column is one repeated non-`无` constant."""

    if len(rows) < REPEATED_GAP_MIN_ROWS:
        return []

    normalized_gaps: list[str] = []
    for _, cells in rows:
        if len(cells) != len(CANONICAL_HEADERS_V1):
            return []
        gap = cells[3]
        if is_empty_or_placeholder(gap) or is_no_gap(gap):
            return []
        normalized_gaps.append(normalize_cell(gap))

    if len(set(normalized_gaps)) != 1:
        return []

    return [
        f"{path}:{header_line}: the same non-无 未验证缺口 repeats across all "
        f"{len(rows)} rows; write 无 where no gap applies, and where a shared "
        "limitation really does apply say how it constrains that row's 结论"
    ]


def validate_document(path: Path) -> list[str]:
    """Return every contract violation found in one document (never raises)."""

    lines = path.read_text(encoding="utf-8").splitlines()

    errors: list[str] = []
    tables_found = 0
    index = 0
    while index < len(lines):
        if not is_canonical_header(parse_table_row(lines[index])):
            index += 1
            continue

        tables_found += 1
        header_line = index + 1
        separator = (
            parse_table_row(lines[index + 1]) if index + 1 < len(lines) else None
        )
        if (
            separator is None
            or len(separator) != len(CANONICAL_HEADERS_V1)
            or not all(SEPARATOR_CELL.fullmatch(cell) for cell in separator)
        ):
            errors.append(
                f"{path}:{header_line}: canonical header is not followed by a "
                "valid Markdown separator row"
            )
            index += 1
            continue

        index += 2
        table_rows: list[tuple[int, list[str]]] = []
        while index < len(lines):
            cells = parse_table_row(lines[index])
            if cells is None:
                break
            table_rows.append((index + 1, cells))
            errors.extend(validate_claim_row(path, index + 1, cells))
            index += 1

        if not table_rows:
            errors.append(f"{path}:{header_line}: claim provenance table has no rows")
        else:
            errors.extend(validate_table_gap_specificity(path, header_line, table_rows))

    if tables_found == 0:
        errors.append(
            f"{path}: missing canonical claim provenance table "
            f"({CANONICAL_HEADER_ROW})"
        )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Require the canonical claim provenance table in done letters and "
            "acceptance evidence documents: every conclusion a downstream "
            "reader acts on carries 类别 (实测/推断), a re-checkable 出处, and "
            "an explicit 未验证缺口."
        ),
        epilog=(
            "canonical table (schema v1, exact column names, no English aliases):\n"
            f"  {CANONICAL_HEADER_ROW}\n"
            "  |---|---|---|---|\n"
            "\n"
            "when to run it (two consumption points; this is not a generic task\n"
            "hook, and no CI job can see an arbitrary adopter's sendbox):\n"
            "  1. before a new done letter is sent\n"
            "  2. before new / substantially rewritten acceptance evidence is\n"
            "     accepted\n"
            "\n"
            "exit codes:\n"
            "  0  every document carries a canonical table and every row holds\n"
            "  1  validation failure (missing table, empty cell, bad 类别,\n"
            "     undeclared 推断 gap, or one gap constant copied down >=4 rows)\n"
            "  2  usage / environment problem (unreadable input; fail closed,\n"
            "     nothing validated)\n"
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="done letters and/or acceptance evidence documents to validate",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    documents: list[Path] = []
    for path in args.paths:
        resolved = path.resolve()
        if not resolved.is_file():
            print(f"claim provenance input is not a file: {resolved}", file=sys.stderr)
            return 2
        documents.append(resolved)

    errors: list[str] = []
    for document in documents:
        try:
            errors.extend(validate_document(document))
        except OSError as exc:
            print(f"cannot read claim provenance input: {exc}", file=sys.stderr)
            return 2
        except UnicodeDecodeError as exc:
            print(
                f"claim provenance input is not UTF-8 text: {document}: {exc}",
                file=sys.stderr,
            )
            return 2

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"claim provenance valid: {len(documents)} document(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
