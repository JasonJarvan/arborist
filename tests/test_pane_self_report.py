#!/usr/bin/env python3
"""自报本 pane:`§5.0` 的根规则第一次拿到一个能让它**通过**的证据来源。

那条根规则是「凡自识别证据不足以唯一确定该 pane ⇒ 拒绝写入」。在此之前它只能拒 ——
没有任何东西产出足够强的证据,于是「正确」的路径不存在,只剩「被拒」和「猜」。

多路复用器把 pane id 注入到每个 pane 的进程环境里,产出的正是那种证据,而且**按构造正确**:
不是推断出来的、不是从显示标题匹配出来的、也不是从一份可能指到别人 pane 的列举里挑出来的。

**关键区别**:自查询答的是「我是哪个 pane」,这一问不会因别处的歧义而失真;读列举答的是
「有哪些 pane」,再按标题挑一个就是根规则禁止的猜 —— 标题是显示名,而真实发生过的那次,
陈旧 ref 指向的是一个活着、且属于别人的 pane,id 看起来完全合理。
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agenttui_under_test", ROOT / "overlay" / "scripts" / "agenttui.py"
)
assert SPEC and SPEC.loader
AGENTTUI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENTTUI)


def only(**environ: str) -> mock._patch_dict:
    """把环境**整个换掉**,而不是叠加 —— 否则真实运行环境里的 ZELLIJ_* 会污染断言。"""
    return mock.patch.dict(os.environ, environ, clear=True)


class ZellijSelfReportTest(unittest.TestCase):
    def transport(self) -> object:
        return AGENTTUI.ZellijTransport()

    def test_it_reports_the_pane_from_the_injected_environment(self) -> None:
        with only(ZELLIJ_SESSION_NAME="workspace", ZELLIJ_PANE_ID="7"):
            self.assertEqual(
                {"multiplexer": "zellij", "session": "workspace", "pane_id": "terminal_7"},
                self.transport().self_pane_ref(),
            )

    def test_a_bare_integer_is_canonicalised_to_the_prefixed_form(self) -> None:
        """写路径两种形态都收,但**核验**拿存的值去比 `list-panes` 的输出。

        存裸形态会让投递可用而核验拒绝 —— 一个 pane 明明好着,却 fail-closed。
        """
        with only(ZELLIJ_SESSION_NAME="w", ZELLIJ_PANE_ID="0"):
            self.assertEqual("terminal_0", self.transport().self_pane_ref()["pane_id"])

    def test_an_id_that_already_carries_a_kind_is_passed_through_untouched(self) -> None:
        """改写它就是本方法在**发明** id,基类契约禁止。"""
        for given in ("terminal_3", "plugin_2"):
            with only(ZELLIJ_SESSION_NAME="w", ZELLIJ_PANE_ID=given):
                self.assertEqual(given, self.transport().self_pane_ref()["pane_id"])

    def test_a_missing_pane_id_yields_unknown_not_a_synthesised_ref(self) -> None:
        with only(ZELLIJ_SESSION_NAME="workspace"):
            self.assertIsNone(self.transport().self_pane_ref())

    def test_a_missing_session_yields_unknown(self) -> None:
        with only(ZELLIJ_PANE_ID="7"):
            self.assertIsNone(self.transport().self_pane_ref())

    def test_an_empty_environment_yields_unknown(self) -> None:
        with only():
            self.assertIsNone(self.transport().self_pane_ref())

    def test_it_runs_no_command(self) -> None:
        """纯读环境。跑命令会让「测量」有失败模式,而测量不得能拖垮调用方。"""
        transport = self.transport()
        with mock.patch.object(
            transport, "_run", side_effect=AssertionError("self-report ran a command")
        ):
            with only(ZELLIJ_SESSION_NAME="w", ZELLIJ_PANE_ID="1"):
                self.assertIsNotNone(transport.self_pane_ref())


class ResolverRefusesAmbiguityTest(unittest.TestCase):
    """开火构造:歧义必须拒,而不是挑一个看起来合理的。"""

    def test_nested_multiplexers_refuse_instead_of_picking_one(self) -> None:
        zellij = AGENTTUI.ZellijTransport()
        tmux = AGENTTUI.TmuxTransport()
        with mock.patch.object(
            zellij, "self_pane_ref",
            return_value={"multiplexer": "zellij", "session": "a", "pane_id": "terminal_1"},
        ), mock.patch.object(
            tmux, "self_pane_ref",
            return_value={"multiplexer": "tmux", "session": "b", "pane_id": "%3"},
        ), mock.patch.dict(
            AGENTTUI.TRANSPORTS, {"zellij": lambda: zellij, "tmux": lambda: tmux}, clear=True
        ):
            ref, reason = AGENTTUI.self_reported_pane_ref()
        self.assertIsNone(ref)
        self.assertIn("nested", reason)
        self.assertIn("someone else", reason)

    def test_no_multiplexer_reporting_yields_a_stated_reason(self) -> None:
        with only():
            ref, reason = AGENTTUI.self_reported_pane_ref()
        self.assertIsNone(ref)
        self.assertTrue(reason.strip())

    def test_a_transport_that_raises_is_treated_as_unknown_not_fatal(self) -> None:
        broken = AGENTTUI.ZellijTransport()
        with mock.patch.object(broken, "self_pane_ref", side_effect=RuntimeError("boom")), \
             mock.patch.dict(AGENTTUI.TRANSPORTS, {"zellij": lambda: broken}, clear=True):
            ref, reason = AGENTTUI.self_reported_pane_ref()
        self.assertIsNone(ref)
        self.assertTrue(reason.strip())

    def test_exactly_one_reporter_is_taken(self) -> None:
        zellij = AGENTTUI.ZellijTransport()
        expected = {"multiplexer": "zellij", "session": "a", "pane_id": "terminal_1"}
        with mock.patch.object(zellij, "self_pane_ref", return_value=expected), \
             mock.patch.dict(AGENTTUI.TRANSPORTS, {"zellij": lambda: zellij}, clear=True):
            ref, reason = AGENTTUI.self_reported_pane_ref()
        self.assertEqual(expected, ref)
        self.assertIn("self-reported", reason)


class BaseContractTest(unittest.TestCase):
    def test_the_abstract_transport_reports_unknown_rather_than_raising(self) -> None:
        """新 transport 忘了实现时,方向必须是「未知」,不是崩,也不是编一个。"""
        self.assertIsNone(AGENTTUI.PaneTransport().self_pane_ref())


if __name__ == "__main__":
    unittest.main()
