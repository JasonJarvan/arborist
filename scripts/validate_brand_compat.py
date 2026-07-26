#!/usr/bin/env python3
"""Validate Arborist brand-contract sources and an optional adopted repository."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


CONTRACT_ID = "ARBORIST-BRAND-COMPAT:v1"
BLOCK_START = "<!-- ARBORIST-BRAND-COMPAT:START -->"
BLOCK_END = "<!-- ARBORIST-BRAND-COMPAT:END -->"
HANDOFF_CONFIG_RELATIVE = Path(
    ".work_context/sendbox/_handoff-config.yaml"
)
SUPPORTED_BRANDS = ("codex", "claude-code")
ROUTE_LANES = ("fast", "full")
ROUTE_TASK_KINDS = ("implement", "explore", "check", "challenge", "research")
TASK_EXECUTING_ROLES = ("Impler", "SubOrche", "Reviewer")
REQUIRED_BRANCH_TOKENS = (
    "same-brand",
    "effective_subagent_brand = impler.spec.brand",
    "brand=codex",
    "brand=claude-code",
    "brand mismatch",
)

SOURCE_PATHS = {
    "registry": Path("overlay/spec/guides/agenttui-registry.md"),
    "roles": Path("overlay/spec/guides/roles-and-tiering.md"),
    "execution": Path("overlay/spec/guides/execution-policy.md"),
    "sendbox": Path("overlay/spec/guides/sendbox.md"),
    "agents_block": Path("overlay/project-instructions/brand-compat.md"),
    "workflow_block": Path("overlay/workflow-phase-index-brand-compat.md"),
    "handoff": Path(
        "overlay/work_context-templates/sendbox/_TEMPLATE-handoff.md"
    ),
    "config": Path("overlay/work_context-templates/sendbox/_handoff-config.yaml"),
    "full_agent": Path(
        "overlay/platform-templates/claude/agents/trellis-implement-full.md"
    ),
    "explore_agent": Path(
        "overlay/platform-templates/claude/agents/trellis-explore.md"
    ),
    "installer": Path("scripts/install-brand-compat.py"),
}

PRIVACY_PATTERNS = {
    "machine-specific home path": re.compile(r"/(?:home|Users)/[^<\s/]+/"),
    "email address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "UUID": re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    ),
}

UNSCOPED_CLAUDE_ROUTE_PATTERNS = (
    re.compile(
        r"(?i)\b(?:implement(?:ation)?|check|challenge|explore|research)\b"
        r".{0,48}\b(?:must|always|only)\b.{0,24}\bclaude(?: code)?\b"
    ),
    re.compile(
        r"(?i)\b(?:must|always|only)\b.{0,24}\bclaude(?: code)?\b"
        r".{0,48}\b(?:implement(?:ation)?|check|challenge|explore|research)\b"
    ),
    re.compile(r"实现.{0,12}(?:一律|必须|只能).{0,12}Claude", re.IGNORECASE),
)


def read_sources(root: Path, errors: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, relative in SOURCE_PATHS.items():
        path = root / relative
        try:
            result[key] = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            errors.append(f"missing source: {relative}")
    return result


def require_tokens(
    label: str, text: str, tokens: tuple[str, ...] | list[str], errors: list[str]
) -> None:
    for token in tokens:
        if token not in text:
            errors.append(f"{label}: missing {token!r}")


def validate_neutral_contract(
    root: Path, sources: dict[str, str], errors: list[str]
) -> None:
    if "registry" in sources:
        require_tokens(
            "registry",
            sources["registry"],
            [
                "actual runtime brand",
                "human-direct harness",
                "must not be reported as unregistered",
                "fail closed",
            ],
            errors,
        )
    for label in ("roles", "execution", "sendbox"):
        if label in sources:
            require_tokens(
                label,
                sources[label],
                [
                    "effective_subagent_brand = impler.spec.brand",
                    "brand mismatch",
                    "fail closed",
                ],
                errors,
            )

    try:
        spec = json.loads(
            (root / "overlay/arborist-templates/agents/example/spec.json").read_text(
                encoding="utf-8"
            )
        )
        runtime = json.loads(
            (
                root / "overlay/arborist-templates/agents/example/runtime.json"
            ).read_text(encoding="utf-8")
        )
        index = json.loads(
            (root / "overlay/arborist-templates/index.json").read_text(
                encoding="utf-8"
            )
        )
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        errors.append(f"registry examples are not valid JSON: {exc}")
    else:
        if spec.get("brand") != "<actual-brand>":
            errors.append("registry spec example must use <actual-brand>")
        if runtime.get("session_file") != "<absolute-session-file-for-actual-brand>":
            errors.append(
                "registry runtime example must use "
                "<absolute-session-file-for-actual-brand>"
            )
        agents = index.get("projects", [{}])[0].get("agents", [])
        if not agents or agents[0].get("brand") != "<actual-brand>":
            errors.append("registry index example must use <actual-brand>")


def validate_visible_blocks(sources: dict[str, str], errors: list[str]) -> None:
    blocks: list[tuple[str, str]] = []
    for label in ("agents_block", "workflow_block"):
        if label not in sources:
            continue
        text = sources[label]
        require_tokens(
            label,
            text,
            [
                CONTRACT_ID,
                *SUPPORTED_BRANDS,
                *REQUIRED_BRANCH_TOKENS,
                "<REPO_ROOT>/.work_context/sendbox/_handoff-config.yaml",
                "Handoff and inherit MUST receive this absolute path explicitly",
            ],
            errors,
        )
        blocks.append((label, text))
    if len(blocks) == 2:
        for token in REQUIRED_BRANCH_TOKENS:
            if (token in blocks[0][1]) != (token in blocks[1][1]):
                errors.append(f"visible blocks disagree about {token!r}")


def frontmatter_model(text: str) -> str | None:
    match = re.search(r"^model:\s*(\S+)\s*$", text, flags=re.MULTILINE)
    return match.group(1) if match else None


def frontmatter_tools(text: str) -> tuple[str, ...]:
    match = re.search(r"^tools:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    if match is None:
        return ()
    return tuple(part.strip() for part in match.group(1).split(","))


def _indented_list(
    lines: list[str], key: str, errors: list[str]
) -> list[str]:
    header = f"  {key}:"
    try:
        start = next(
            index for index, line in enumerate(lines) if line.rstrip() == header
        )
    except StopIteration:
        errors.append(f"handoff config: missing brand_routing.{key}")
        return []

    values: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 2:
            break
        match = re.fullmatch(r" {4}-\s+(\S+)\s*", line)
        if match is None:
            errors.append(f"handoff config: malformed list item under {key}")
            continue
        values.append(match.group(1))
    return values


def parse_route_policies(
    text: str, errors: list[str]
) -> dict[tuple[str, str, str], dict[str, str | None]]:
    lines = text.splitlines()
    try:
        brand_start = next(
            index
            for index, line in enumerate(lines)
            if line.rstrip() == "brand_routing:"
        )
    except StopIteration:
        errors.append("handoff config: missing brand_routing")
        return {}

    brand_end = len(lines)
    for index in range(brand_start + 1, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:", line):
                errors.append(
                    f"handoff config: malformed top-level YAML key: {line}"
                )
            brand_end = index
            break
    brand_lines = lines[brand_start + 1 : brand_end]
    top_keys = {
        match.group(1)
        for line in brand_lines
        if (match := re.fullmatch(r"  ([a-z_]+):(?:\s+.*)?", line))
    }
    expected_top_keys = {
        "task_executing_roles",
        "supported_brands",
        "same_brand_policy",
        "route_policies",
    }
    if top_keys != expected_top_keys:
        errors.append(
            "handoff config: brand_routing keys must be exactly "
            f"{sorted(expected_top_keys)}"
        )

    roles = _indented_list(brand_lines, "task_executing_roles", errors)
    for role in TASK_EXECUTING_ROLES:
        if role not in roles:
            errors.append(f"handoff config: task_executing_roles missing {role}")

    supported = _indented_list(brand_lines, "supported_brands", errors)
    if set(supported) != set(SUPPORTED_BRANDS):
        errors.append(
            "handoff config: supported_brands must be exactly codex and claude-code"
        )
    if not re.search(
        r"(?m)^  same_brand_policy:\s+strict\s*$", "\n".join(brand_lines)
    ):
        errors.append("handoff config: same_brand_policy must be strict")

    try:
        route_start = next(
            index
            for index, line in enumerate(brand_lines)
            if line.rstrip() == "  route_policies:"
        )
    except StopIteration:
        errors.append("handoff config: missing brand_routing.route_policies")
        return {}

    policies: dict[tuple[str, str, str], dict[str, str | None]] = {}
    current_brand: str | None = None
    current_lane: str | None = None
    current_kind: str | None = None
    fragment_lines: list[str] | None = None

    for line in brand_lines[route_start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if fragment_lines is not None and indent >= 12:
            fragment_lines.append(stripped)
            continue
        fragment_lines = None

        key_match = re.fullmatch(r"([a-z][a-z0-9-]*):", stripped)
        if indent == 4 and key_match:
            current_brand = key_match.group(1)
            current_lane = None
            current_kind = None
            continue
        if indent == 6 and key_match:
            current_lane = key_match.group(1)
            current_kind = None
            continue
        if indent == 8 and key_match:
            current_kind = key_match.group(1)
            if current_brand is None or current_lane is None:
                errors.append("handoff config: route policy has an incomplete key path")
                continue
            route_key = (current_brand, current_lane, current_kind)
            if route_key in policies:
                errors.append(f"handoff config: duplicate route tuple {route_key}")
            policies[route_key] = {}
            continue
        if indent == 10:
            if current_brand is None or current_lane is None or current_kind is None:
                errors.append("handoff config: leaf field has no route tuple")
                continue
            route_key = (current_brand, current_lane, current_kind)
            field_match = re.fullmatch(
                r"(policy_id|route_fragment|agent|model):(?:\s*(.*))?", stripped
            )
            if field_match is None:
                errors.append(
                    f"handoff config: unknown leaf field in {route_key}: {stripped}"
                )
                continue
            field, raw_value = field_match.groups()
            if field in policies[route_key]:
                errors.append(
                    f"handoff config: duplicate {field} in route tuple {route_key}"
                )
                continue
            if field == "route_fragment":
                if raw_value != "|":
                    errors.append(
                        f"handoff config: route_fragment must use | in {route_key}"
                    )
                fragment_lines = []
                policies[route_key][field] = ""
                continue
            value = (raw_value or "").strip()
            policies[route_key][field] = None if value == "null" else value
            continue
        errors.append(f"handoff config: invalid route policy indentation: {line}")

    # Fill block scalars in a second focused pass so their exact text is available
    # for cross-brand checks without requiring a third-party YAML parser.
    route_header = re.compile(r"^ {8}([a-z][a-z0-9-]*):\s*$")
    active_key: tuple[str, str, str] | None = None
    active_brand: str | None = None
    active_lane: str | None = None
    for index, line in enumerate(brand_lines[route_start + 1 :]):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        key_match = re.fullmatch(r"([a-z][a-z0-9-]*):", stripped)
        if indent == 4 and key_match:
            active_brand = key_match.group(1)
        elif indent == 6 and key_match:
            active_lane = key_match.group(1)
        elif route_header.fullmatch(line):
            kind = route_header.fullmatch(line).group(1)
            if active_brand is not None and active_lane is not None:
                active_key = (active_brand, active_lane, kind)
        elif indent == 10 and stripped == "route_fragment: |" and active_key:
            content: list[str] = []
            following = brand_lines[route_start + 2 + index :]
            for fragment_line in following:
                fragment_indent = len(fragment_line) - len(fragment_line.lstrip())
                if fragment_line.strip() and fragment_indent < 12:
                    break
                if fragment_line.strip():
                    content.append(fragment_line.strip())
            policies[active_key]["route_fragment"] = "\n".join(content)
    return policies


def validate_route_config(text: str, errors: list[str]) -> None:
    policies = parse_route_policies(text, errors)
    expected_tuples = {
        (brand, lane, kind)
        for brand in SUPPORTED_BRANDS
        for lane in ROUTE_LANES
        for kind in ROUTE_TASK_KINDS
    }
    if set(policies) != expected_tuples:
        missing = sorted(expected_tuples - set(policies))
        extra = sorted(set(policies) - expected_tuples)
        errors.append(
            f"handoff config: route tuple matrix mismatch; missing={missing}, extra={extra}"
        )

    policy_ids: list[str] = []
    claude_expectations = {
        "implement": {
            "fast": ("trellis-implement", "sonnet"),
            "full": ("trellis-implement-full", "opus"),
        },
        "explore": {
            "fast": ("trellis-explore", "sonnet"),
            "full": ("trellis-explore", "sonnet"),
        },
        "check": {
            "fast": ("trellis-check", "opus"),
            "full": ("trellis-check", "opus"),
        },
        "challenge": {
            "fast": ("trellis-check", "opus"),
            "full": ("trellis-check", "opus"),
        },
        "research": {
            "fast": ("trellis-research", "sonnet"),
            "full": ("trellis-research", "sonnet"),
        },
    }
    for route_key, leaf in policies.items():
        if set(leaf) != {"policy_id", "route_fragment", "agent", "model"}:
            errors.append(
                f"handoff config: {route_key} must have exactly "
                "policy_id, route_fragment, agent, and model"
            )
            continue
        policy_id = leaf["policy_id"]
        fragment = leaf["route_fragment"]
        if not isinstance(policy_id, str) or not policy_id:
            errors.append(f"handoff config: {route_key} has no policy_id")
        else:
            policy_ids.append(policy_id)
        if not isinstance(fragment, str) or not fragment:
            errors.append(f"handoff config: {route_key} has no route_fragment")

        brand, lane, kind = route_key
        if brand == "codex":
            if leaf["agent"] is not None or leaf["model"] is not None:
                errors.append(f"handoff config: {route_key} must use null agent/model")
            lowered = fragment.lower() if isinstance(fragment, str) else ""
            if "codex" not in lowered or "project configuration" not in lowered:
                errors.append(
                    f"handoff config: {route_key} must name Codex and project configuration"
                )
            for forbidden in ("claude", "sonnet", "opus", "trellis-"):
                if forbidden in lowered:
                    errors.append(
                        f"handoff config: {route_key} contains {forbidden!r}"
                    )
        elif brand == "claude-code":
            expected_agent, expected_model = claude_expectations[kind][lane]
            if leaf["agent"] != expected_agent or leaf["model"] != expected_model:
                errors.append(
                    f"handoff config: {route_key} must use "
                    f"{expected_agent}/{expected_model}"
                )
    if len(policy_ids) != len(set(policy_ids)):
        errors.append("handoff config: policy_id values must be globally unique")


def validate_routes(sources: dict[str, str], errors: list[str]) -> None:
    if "full_agent" in sources:
        if frontmatter_model(sources["full_agent"]) != "opus":
            errors.append("trellis-implement-full must pin model: opus")
        require_tokens(
            "trellis-implement-full",
            sources["full_agent"],
            [CONTRACT_ID, "Claude Code"],
            errors,
        )
        if frontmatter_tools(sources["full_agent"]) != (
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
        ):
            errors.append(
                "trellis-implement-full tools must be Read, Write, Edit, "
                "Bash, Glob, Grep"
            )
    if "explore_agent" in sources:
        if frontmatter_model(sources["explore_agent"]) != "sonnet":
            errors.append("trellis-explore must pin model: sonnet")
        require_tokens(
            "trellis-explore",
            sources["explore_agent"],
            [CONTRACT_ID, "Claude Code"],
            errors,
        )
        if frontmatter_tools(sources["explore_agent"]) != (
            "Read",
            "Bash",
            "Glob",
            "Grep",
        ):
            errors.append(
                "trellis-explore tools must be read-only: Read, Bash, Glob, Grep"
            )
    if "handoff" in sources:
        require_tokens(
            "handoff template",
            sources["handoff"],
            [
                "recipient_brand: <claude-code|codex>",
                "route_policy:",
                "policy_id:",
                "lane:",
                "task_kind:",
                "agent:",
                "model:",
            ],
            errors,
        )
    if "config" in sources:
        validate_route_config(sources["config"], errors)
        if re.search(
            r"(?m)^\s*(?:export\s+)?CLAUDE_CODE_SUBAGENT_MODEL\s*[:=]",
            sources["config"],
        ):
            errors.append(
                "handoff config must not set CLAUDE_CODE_SUBAGENT_MODEL"
            )


def validate_unscoped_route_text(
    label: str, text: str, errors: list[str]
) -> None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        clauses = re.split(r"[;；]|\.\s+|。\s*", line)
        for clause in clauses:
            if "brand=claude-code" in clause or "brand: claude-code" in clause:
                continue
            if any(
                pattern.search(clause)
                for pattern in UNSCOPED_CLAUDE_ROUTE_PATTERNS
            ):
                errors.append(
                    f"{label}:{line_number}: unscoped Claude routing clause"
                )
                break


def validate_unscoped_routes(
    sources: dict[str, str], errors: list[str]
) -> None:
    for label in (
        "roles",
        "execution",
        "sendbox",
        "agents_block",
        "workflow_block",
        "handoff",
    ):
        validate_unscoped_route_text(label, sources.get(label, ""), errors)


def split_managed_block(
    label: str, text: str, errors: list[str]
) -> tuple[str, str]:
    if text.count(BLOCK_START) != 1 or text.count(BLOCK_END) != 1:
        errors.append(f"{label}: expected exactly one managed brand block")
        return "", text
    pattern = re.compile(
        rf"{re.escape(BLOCK_START)}.*?{re.escape(BLOCK_END)}",
        flags=re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        errors.append(f"{label}: managed brand block markers are out of order")
        return "", text
    managed = match.group(0)
    outside = text[: match.start()] + text[match.end() :]
    return managed, outside


def validate_privacy(root: Path, sources: dict[str, str], errors: list[str]) -> None:
    extra_paths = (
        Path("overlay/arborist-templates/agents/example/spec.json"),
        Path("overlay/arborist-templates/agents/example/runtime.json"),
        Path("overlay/arborist-templates/index.json"),
    )
    texts = [(SOURCE_PATHS[key], text) for key, text in sources.items()]
    for relative in extra_paths:
        try:
            texts.append((relative, (root / relative).read_text(encoding="utf-8")))
        except FileNotFoundError:
            continue
    for relative, text in texts:
        for label, pattern in PRIVACY_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{relative}: contains {label}")


def validate_target(source_tree: Path, target_repo: Path, errors: list[str]) -> None:
    installer = source_tree / "scripts/install-brand-compat.py"
    result = subprocess.run(
        [
            sys.executable,
            str(installer),
            "--source-tree",
            str(source_tree),
            "--target-repo",
            str(target_repo),
            "--check",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        errors.append(f"adopted target validation failed: {detail}")
    target_config = target_repo / HANDOFF_CONFIG_RELATIVE
    try:
        config_text = target_config.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"adopted target is missing {target_config}")
    else:
        target_errors: list[str] = []
        validate_route_config(config_text, target_errors)
        errors.extend(f"adopted target: {error}" for error in target_errors)

    expected_config_path = str((target_repo / HANDOFF_CONFIG_RELATIVE).resolve())
    for relative in (Path("AGENTS.md"), Path(".trellis/workflow.md")):
        path = target_repo / relative
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            errors.append(f"adopted target is missing {path}")
            continue
        label = f"adopted target {relative}"
        managed, outside = split_managed_block(label, text, errors)
        if expected_config_path not in managed:
            errors.append(
                f"{label}: managed block must name {expected_config_path}"
            )
        if "<REPO_ROOT>" in managed:
            errors.append(f"{label}: managed block contains unresolved <REPO_ROOT>")
        validate_unscoped_route_text(label, outside, errors)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-tree",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Arborist source tree to validate",
    )
    parser.add_argument(
        "--target-repo",
        type=Path,
        help="also verify an adopted repository with installer --check",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.source_tree.resolve()
    errors: list[str] = []
    sources = read_sources(root, errors)
    validate_neutral_contract(root, sources, errors)
    validate_visible_blocks(sources, errors)
    validate_routes(sources, errors)
    validate_unscoped_routes(sources, errors)
    validate_privacy(root, sources, errors)
    if args.target_repo is not None:
        validate_target(root, args.target_repo.resolve(), errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"OK: {CONTRACT_ID} source contract is valid for "
        f"{', '.join(SUPPORTED_BRANDS)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
