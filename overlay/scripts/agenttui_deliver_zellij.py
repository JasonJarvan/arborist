#!/usr/bin/env python3
"""AgentTUI 活 pane 投递 — zellij 参考 adapter（可插拔 · opt-in）。

  ⚠️ 这是一个【可插拔参考 adapter · opt-in】,不是 core。
     adopt 默认【不】安装它。规范是 ADR-0007 的【投递契约】,
     具体传输(此处 zellij pane + 字节注入)可整体替换成任意满足
     同一契约的实现。

权威契约见 ADR-0007
(overlay/spec/guides/decisions/0007-agenttui-delivery-contract-pluggable-adapter.md)
与 agenttui-registry §3「投递契约」。本脚本按 Option A 交付:
契约进 core(规范),此 zellij 传输作参考 adapter 随发但 opt-in。

契约(本 adapter 实现的四条,规范性):
  1. brand + 活性感知的 submit 路由:
       有效活跃 + brand=codex  -> 写信封后【发一次 Tab(byte 9)入队】,不 steer 当前 turn;
       空闲 codex              -> Enter(byte 13) 提交;
       claude-code             -> 沿用 Enter 提交。
  2. 不盲目重发入队键:送达未观测到时【不得】重发 Tab(会入队重复信封)。
  3. 送达证据必须 message-specific(fail-closed,绝不假阳性):
       注入前记录目标 transcript 字节边界;每次发送带唯一 nonce;
       仅当该信封的 nonce marker 出现在边界【之后】才 delivered,否则 queued-unverified。
  4. fail-closed:未验证即 queued-unverified,绝不当 delivered。
     pane 命令成功 / pane 存在 / 转录 size 增长 / mtime 变化【都不是】送达证据。

可测性 seam:
  「往 pane 注入/发键」(PaneInjector)与「读 transcript」(TranscriptReader)
  是可注入的类边界。测试注入 fake,无需真 zellij / 真 session 即可跑。
  真实 zellij 命令隔离在 ZellijPaneInjector 之后(默认实现)。

无实例值:目标会话路径 / brand / 活性 / 信封 / nonce / pane 引用全部由参数传入。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

# ── 契约常量 ────────────────────────────────────────────────────────────
SUBMIT_TAB = 9          # active codex: 入队到下一 turn,不 steer
SUBMIT_ENTER = 13       # idle codex / claude-code: 提交

STATUS_DELIVERED = "delivered"
STATUS_QUEUED_UNVERIFIED = "queued-unverified"

# nonce marker 前缀是常量标签(非实例值);具体 nonce 由调用方逐次生成并传入。
_MARKER_PREFIX = "arborist-delivery"


def render_marker(nonce: str) -> str:
    """把 per-send nonce 渲染成可在 transcript 中搜索的 marker token。"""
    return f"[{_MARKER_PREFIX}:{nonce}]"


def build_payload(envelope: str, nonce: str) -> str:
    """信封 + 送达 marker。marker 令 nonce 在被送进 transcript 后可被越界验证命中。"""
    return f"{envelope}\n{render_marker(nonce)}"


def resolve_submit_key(brand: str, activity: str) -> int:
    """契约①:brand + 活性感知的 submit 路由(brand-keyed,与 ADR-0006 一致)。

    activity 由调用方按 ADR-0002 读时派生态给('active'/'idle',contradiction 已按 active 归一)。
    """
    normalized_brand = brand.strip().lower()
    normalized_activity = activity.strip().lower()
    if normalized_brand == "codex":
        if normalized_activity == "active":
            return SUBMIT_TAB
        if normalized_activity == "idle":
            return SUBMIT_ENTER
        raise ValueError(f"unknown activity for codex: {activity!r} (expected active/idle)")
    if normalized_brand == "claude-code":
        return SUBMIT_ENTER
    raise ValueError(f"unknown brand: {brand!r} (expected codex/claude-code)")


# ── seam:注入 / 读取(可注入、可 mock)──────────────────────────────────
class PaneInjector(Protocol):
    """往目标 pane 注入信封文本、发送单个 submit 键字节。传输细节隔离于此。"""

    def write_envelope(self, pane_ref: str, payload: str) -> None: ...

    def send_submit_key(self, pane_ref: str, key_byte: int) -> None: ...


class TranscriptReader(Protocol):
    """读目标 transcript:边界字节 size + 边界之后的新内容。mtime/size 本身非证据。"""

    def size(self, session_file: str) -> int: ...

    def read_since(self, session_file: str, boundary: int) -> str: ...


@dataclass
class DeliveryResult:
    status: str
    nonce: str
    boundary: int
    submit_key: int
    reason: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "nonce": self.nonce,
                "boundary": self.boundary,
                "submit_key": self.submit_key,
                "reason": self.reason,
            },
            ensure_ascii=False,
        )

    @property
    def delivered(self) -> bool:
        return self.status == STATUS_DELIVERED


# ── 默认(真实 zellij / 真实文件)实现,隔离在 seam 之后 ────────────────
class ZellijPaneInjector:
    """真实 zellij 传输。仅在默认 CLI 路径使用;测试注入 fake 绕开它。

    zellij 语义:`zellij action write-chars <text>` 写字符;
    `zellij action write <byte>` 发单字节(9=Tab,13=Enter)。

    ⚠️ pane 定向【尚未实现】(本参考 adapter 的已知缺口):
       write_envelope/send_submit_key 收 pane_ref,但底层 `zellij action
       write-chars`/`write` 【未用它定向】,实际发到【当前聚焦的 pane】。
       故本实现只在「目标恰为当前聚焦 pane」的单/受控环境下正确。
       【真多 pane 环境启用前,必须先补 pane 寻址】(如先 `zellij action
       focus`/按 tab-name 切到目标 pane,或换用支持 pane target 的传输)。
       fail-closed 仍成立:即便投错 pane,目标 transcript 里不会出现本次
       nonce marker -> 返回 queued-unverified,不会假阳性报 delivered。
    """

    def __init__(self, session_name: Optional[str] = None, timeout: float = 10.0) -> None:
        self._session_name = session_name
        self._timeout = timeout

    def _base(self) -> list[str]:
        base = ["zellij"]
        if self._session_name:
            base += ["--session", self._session_name]
        return base

    def _run(self, args: list[str]) -> None:
        subprocess.run(
            [*self._base(), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )

    def write_envelope(self, pane_ref: str, payload: str) -> None:
        # ⚠️ pane_ref 收下但【未用于定向】:下面的 write-chars 发到【当前聚焦 pane】。
        #    多 pane 环境启用前须先补 pane 寻址(见类 docstring 的 TODO)。
        self._run(["action", "write-chars", payload])

    def send_submit_key(self, pane_ref: str, key_byte: int) -> None:
        # ⚠️ 同上:pane_ref 未用于定向,write 发到【当前聚焦 pane】。
        self._run(["action", "write", str(key_byte)])


class FileTranscriptReader:
    """真实 transcript 文件读取:size 取边界,read_since 读边界之后的字节。"""

    def size(self, session_file: str) -> int:
        path = Path(session_file)
        return path.stat().st_size if path.exists() else 0

    def read_since(self, session_file: str, boundary: int) -> str:
        path = Path(session_file)
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            handle.seek(max(0, boundary))
            return handle.read().decode("utf-8", errors="replace")


# ── adapter 主体 ────────────────────────────────────────────────────────
class ZellijDeliveryAdapter:
    """按 ADR-0007 契约投递。传输/读取经 seam 注入,便于无真环境测试。"""

    def __init__(self, injector: PaneInjector, reader: TranscriptReader) -> None:
        self._injector = injector
        self._reader = reader

    def deliver(
        self,
        session_file: str,
        pane_ref: str,
        brand: str,
        activity: str,
        envelope: str,
        nonce: str,
        verify_attempts: int = 1,
        verify_delay: float = 0.0,
    ) -> DeliveryResult:
        """执行契约流程。绝不假阳性:仅本 nonce marker 越界命中才 delivered。

        verify_attempts/verify_delay 仅控制【只读】的送达轮询;
        轮询【绝不】重发 submit 键(契约②),故不会入队重复信封。
        """
        if not nonce:
            raise ValueError("per-send nonce is required (delivery evidence must be message-specific)")

        submit_key = resolve_submit_key(brand, activity)

        # ① 注入前记录字节边界(契约③)。
        boundary = self._reader.size(session_file)

        # ② 把信封(内含 nonce marker)写进 pane。
        payload = build_payload(envelope, nonce)
        self._injector.write_envelope(pane_ref, payload)

        # ③ submit-key 路由:发【一次】键;active codex 是 Tab 入队、不 steer(契约①)。
        self._injector.send_submit_key(pane_ref, submit_key)

        # ④ 送达验证:读边界【之后】的新内容,找本 nonce marker。
        #    轮询只读、绝不重发键(契约②:不盲目重发入队键)。
        marker = render_marker(nonce)
        attempts = max(1, verify_attempts)
        for attempt in range(attempts):
            new_content = self._reader.read_since(session_file, boundary)
            if marker in new_content:
                return DeliveryResult(
                    status=STATUS_DELIVERED,
                    nonce=nonce,
                    boundary=boundary,
                    submit_key=submit_key,
                    reason="nonce marker observed past boundary",
                )
            if attempt + 1 < attempts and verify_delay > 0:
                time.sleep(verify_delay)

        # ⑤ 未验证:fail-closed -> queued-unverified(契约④)。不重发、不盲目重试 Tab。
        return DeliveryResult(
            status=STATUS_QUEUED_UNVERIFIED,
            nonce=nonce,
            boundary=boundary,
            submit_key=submit_key,
            reason="no message-specific nonce marker past boundary; growth/mtime are not evidence",
        )


# ── CLI(默认接真实 zellij / 文件;无实例值,全参数化)──────────────────
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AgentTUI zellij 参考投递 adapter (opt-in, ADR-0007 契约)。",
    )
    parser.add_argument("--session-file", required=True,
                        help="目标会话 transcript 的绝对路径(送达证据锚点)。")
    parser.add_argument("--brand", required=True, choices=["codex", "claude-code"],
                        help="目标实际运行 brand(ADR-0006 路由权威)。")
    parser.add_argument("--activity", required=True, choices=["active", "idle"],
                        help="调用方按 ADR-0002 派生态给出的活性。")
    parser.add_argument("--envelope", required=True, help="要投递的信封文本。")
    parser.add_argument("--nonce", required=True, help="本次发送的唯一 nonce(送达证据)。")
    parser.add_argument("--pane-ref", default="",
                        help="可选:zellij pane/tab 引用,供 adapter 寻址目标 pane。")
    parser.add_argument("--zellij-session", default=None,
                        help="可选:zellij session 名。")
    parser.add_argument("--verify-attempts", type=int, default=1,
                        help="只读送达验证的轮询次数(绝不重发键)。")
    parser.add_argument("--verify-delay", type=float, default=0.0,
                        help="验证轮询间隔秒(仅在 attempts>1 时生效)。")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    adapter = ZellijDeliveryAdapter(
        injector=ZellijPaneInjector(session_name=args.zellij_session),
        reader=FileTranscriptReader(),
    )
    result = adapter.deliver(
        session_file=args.session_file,
        pane_ref=args.pane_ref,
        brand=args.brand,
        activity=args.activity,
        envelope=args.envelope,
        nonce=args.nonce,
        verify_attempts=args.verify_attempts,
        verify_delay=args.verify_delay,
    )
    print(result.to_json())
    # 退出码语义:delivered=0;queued-unverified=3(未失败,但未验证 -> 调用方须另行处理)。
    return 0 if result.delivered else 3


if __name__ == "__main__":
    sys.exit(main())
