from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_validator_module():
    """Load the overlay validator by path, without a package import."""
    module_path = ROOT / "overlay/scripts/validate_claim_provenance.py"
    module_name = "validate_claim_provenance"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator_module()


def run_main(*argv: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = VALIDATOR.main(list(argv))
    return result, stdout.getvalue(), stderr.getvalue()


class DocumentFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    def write(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return path


class RowContractTests(DocumentFixture):
    def test_observed_and_inferred_claims_with_sources_pass(self) -> None:
        path = self.write(
            "done.md",
            """
## Claim provenance

| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 单测通过 | 实测 | `python3 -m unittest -v` → 24/24 PASS | 无 |
| 该分支可安全合并 | 推断 | 单测结果 + `git diff --check` | 尚未运行目标分支 CI |
""",
        )

        self.assertEqual(VALIDATOR.validate_document(path), [])

        result, stdout, stderr = run_main(str(path))

        self.assertEqual(result, 0, stderr)
        self.assertIn("claim provenance valid", stdout)

    def test_bare_kind_header_without_annotation_also_matches_v1(self) -> None:
        # The annotation `（实测/推断）` is a reading aid, not part of the name.
        path = self.write(
            "done.md",
            """
| 结论 | 类别 | 出处 | 未验证缺口 |
|---|---|---|---|
| 单测通过 | 实测 | `python3 -m unittest` → PASS | 无 |
""",
        )

        self.assertEqual(VALIDATOR.validate_document(path), [])

    def test_document_without_canonical_table_fails(self) -> None:
        path = self.write("done.md", "## Evidence\n\nTests passed.\n")

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(
            any("missing canonical claim provenance table" in error for error in errors),
            errors,
        )

    def test_english_alias_header_is_not_a_v1_table(self) -> None:
        # No fuzzy alias guessing: an English header is *missing*, never
        # half-validated. An alias would be a versioned schema change.
        path = self.write(
            "done.md",
            """
| Claim | Kind | Source | Unverified gap |
|---|---|---|---|
| tests pass | 实测 | `python3 -m unittest` | 无 |
""",
        )

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(
            any("missing canonical claim provenance table" in error for error in errors),
            errors,
        )

    def test_empty_source_fails(self) -> None:
        path = self.write(
            "done.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 单测通过 | 实测 |  | 无 |
""",
        )

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(any("出处 must not be empty" in error for error in errors), errors)

    def test_inference_must_name_the_unverified_step(self) -> None:
        path = self.write(
            "done.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 线上也安全 | 推断 | 本地 smoke PASS | 无 |
""",
        )

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(
            any("推断 must name an unverified gap" in error for error in errors), errors
        )

    def test_invalid_kind_and_placeholder_cells_fail(self) -> None:
        path = self.write(
            "done.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 已可交付 | 混合 | <FILL> | TBD |
""",
        )

        result, _, stderr = run_main(str(path))

        self.assertEqual(result, 1)
        self.assertIn("类别 must be 实测 or 推断", stderr)
        self.assertIn("出处 must not be empty", stderr)
        self.assertIn("未验证缺口 must not be empty", stderr)

    def test_wrong_column_count_fails(self) -> None:
        path = self.write(
            "done.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 单测通过 | 实测 | `python3 -m unittest` |
""",
        )

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(any("must have 4 columns" in error for error in errors), errors)

    def test_unfilled_template_table_fails(self) -> None:
        # The shipped templates must not pass as their own evidence.
        path = self.write(
            "done.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| <可被验收的单一结论> | 实测 | <命令 + 结果 / artifact / path:line> | 无 |
""",
        )

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(any("结论 must not be empty" in error for error in errors), errors)
        self.assertTrue(any("出处 must not be empty" in error for error in errors), errors)


class GapSpecificityTests(DocumentFixture):
    """The four-row repeated-gap regression: a copied constant is not evidence."""

    def test_repeated_non_empty_gap_across_four_rows_fails(self) -> None:
        repeated_gap = "未覆盖真机链路；下游域名尚未解析。"
        path = self.write(
            "validation.md",
            f"""
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 聚焦测试通过 | 实测 | `go test ./pkg/client` | {repeated_gap} |
| 全量测试通过 | 实测 | `go test ./...` | {repeated_gap} |
| diff 无空白错误 | 实测 | `git diff --check` | {repeated_gap} |
| lint 为零 | 实测 | `golangci-lint run` | {repeated_gap} |
""",
        )

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(
            any(
                "the same non-无 未验证缺口 repeats across all 4 rows" in error
                for error in errors
            ),
            errors,
        )

        result, _, _ = run_main(str(path))
        self.assertEqual(result, 1)

    def test_four_observed_rows_may_all_have_no_gap(self) -> None:
        path = self.write(
            "validation.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 检查一通过 | 实测 | `check-one` | 无 |
| 检查二通过 | 实测 | `check-two` | 无 |
| 检查三通过 | 实测 | `check-three` | 无 |
| 检查四通过 | 实测 | `check-four` | 无 |
""",
        )

        self.assertEqual(VALIDATOR.validate_document(path), [])

    def test_three_rows_may_share_one_real_gap(self) -> None:
        path = self.write(
            "validation.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| fixture 一通过 | 实测 | `fixture-one` | 尚未接入真机 |
| fixture 二通过 | 实测 | `fixture-two` | 尚未接入真机 |
| fixture 三通过 | 实测 | `fixture-three` | 尚未接入真机 |
""",
        )

        self.assertEqual(VALIDATOR.validate_document(path), [])

    def test_large_table_shared_limit_must_be_claim_specific(self) -> None:
        path = self.write(
            "validation.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 聚焦测试通过 | 实测 | `go test ./pkg/client` | 未在真机确认聚焦测试覆盖的远端行为 |
| 全量测试通过 | 实测 | `go test ./...` | 未在真机确认全量测试覆盖的远端行为 |
| diff 无空白错误 | 实测 | `git diff --check` | 无 |
| lint 为零 | 实测 | `golangci-lint run` | 无 |
""",
        )

        self.assertEqual(VALIDATOR.validate_document(path), [])


class MultiTableAndCliTests(DocumentFixture):
    def test_second_table_in_the_same_document_is_also_checked(self) -> None:
        path = self.write(
            "done.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 单测通过 | 实测 | `python3 -m unittest` | 无 |

## 附加验收

| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 线上也安全 | 推断 | 本地 smoke PASS | 无 |
""",
        )

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(
            any("推断 must name an unverified gap" in error for error in errors), errors
        )

    def test_header_without_separator_row_fails(self) -> None:
        path = self.write(
            "done.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
| 单测通过 | 实测 | `python3 -m unittest` | 无 |
""",
        )

        errors = VALIDATOR.validate_document(path)

        self.assertTrue(
            any("valid Markdown separator row" in error for error in errors), errors
        )

    def test_every_input_is_reported_not_just_the_first(self) -> None:
        good = self.write(
            "good.md",
            """
| 结论 | 类别（实测/推断） | 出处 | 未验证缺口 |
|---|---|---|---|
| 单测通过 | 实测 | `python3 -m unittest` | 无 |
""",
        )
        bad = self.write("bad.md", "## Evidence\n\nTests passed.\n")

        result, stdout, stderr = run_main(str(good), str(bad))

        self.assertEqual(result, 1)
        self.assertIn("bad.md", stderr)
        self.assertNotIn("claim provenance valid", stdout)

    def test_missing_input_file_fails_closed_with_exit_2(self) -> None:
        absent = self.root / "no-such-done.md"

        result, stdout, stderr = run_main(str(absent))

        self.assertEqual(result, 2)
        self.assertIn("is not a file", stderr)
        self.assertEqual(stdout, "")

    def test_parser_requires_at_least_one_path(self) -> None:
        with self.assertRaises(SystemExit) as raised, redirect_stderr(io.StringIO()):
            VALIDATOR.main([])

        self.assertEqual(raised.exception.code, 2)


class ShippedTemplateTests(unittest.TestCase):
    """The shipped templates must carry the canonical header, verbatim."""

    TEMPLATES = (
        ROOT / "overlay/work_context-templates/sendbox/_TEMPLATE-done.md",
        ROOT / "overlay/spec/guides/_TEMPLATE-acceptance-evidence.md",
    )

    def test_templates_use_the_canonical_v1_header(self) -> None:
        for template in self.TEMPLATES:
            with self.subTest(template=template.name):
                body = template.read_text(encoding="utf-8")
                self.assertIn(VALIDATOR.CANONICAL_HEADER_ROW, body)

    def test_templates_are_rejected_until_placeholders_are_replaced(self) -> None:
        # A template that validated as-is would let a copy-paste stand in for
        # evidence; each shipped table must fail while still a placeholder.
        for template in self.TEMPLATES:
            with self.subTest(template=template.name):
                errors = VALIDATOR.validate_document(template)
                self.assertTrue(errors, f"{template} passed while unfilled")


if __name__ == "__main__":
    unittest.main()
