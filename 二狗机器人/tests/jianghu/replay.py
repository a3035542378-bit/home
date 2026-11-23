"""同一份逐跳断言同时供 pytest 和 Markdown 预览使用。"""

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory

from ergou.db import BJ
from ergou.engine import UNKNOWN_COMMAND

from . import audit
from .driver import ReceiptDriver
from .transport import START, session


@dataclass(frozen=True)
class Scenario:
    name: str
    open_letter: bool
    join: bool = False
    rest: int = 120


SCENARIOS = (
    Scenario("拆信", True),
    Scenario("还信入门", False, True),
    Scenario("还信婉拒·隔夜回来", False, rest=86400),
    Scenario("拆信·打坐未满两分钟", True, rest=119),
)


@dataclass
class Trace:
    name: str
    rows: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    status: str = ""

    def check(self, ok, hop, message):
        if not ok:
            self.failures.append(f"第 {hop} 跳 · {message}")
        return "绿" if ok else "红"

    def markdown(self):
        lines = [
            f"### {self.name}",
            "",
            "| 跳 | 北京时间 | 玩家发送 | 微信回执正文 | 原文提取的下一句 | 非兜底 / 业务态 / 模型增量 | 本群业务态 |",
            "|---:|---|---|---|---|---|---|",
        ]
        for row in self.rows:
            cells = [
                escape(str(c)).replace("|", "&#124;").replace("\n", "<br>") for c in row
            ]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(
            [*lines, "", self.status, "", *["- " + f for f in self.failures]]
        )


def run(path, scenario):
    trace = Trace(scenario.name)
    driver = ReceiptDriver(scenario.open_letter, scenario.join)
    command = driver.start()
    now = START
    restarted = False
    finished = False
    with session(path) as worker:
        pattern = audit.leak_pattern(path)
        for hop in range(1, 26):
            before = audit.snapshot(path)
            seq, receipt = worker.send(command, now)
            after = audit.snapshot(path)
            genuine = trace.check(
                bool(receipt) and receipt != UNKNOWN_COMMAND.format(prefix="二狗"),
                hop,
                "无玩法正文或命中 UNKNOWN_COMMAND",
            )
            model = after["model"] - before["model"]
            trace.check(model == 0, hop, f"模型队列增量 {model}")
            try:
                assert audit.tagged(path, seq), "未进入本群江湖业务回执队列"
                audit.check_hop(
                    command.removeprefix("二狗"), before, after, now, receipt
                )
            except (AssertionError, KeyError, ValueError, TypeError) as error:
                business = trace.check(
                    False, hop, f"业务态断言 {command!r} 失败 {error!r}"
                )
            else:
                business = "绿"
            for word in pattern.findall(receipt):
                trace.check(False, hop, f"Lint-B 正文泄漏 {word!r}")
            for unknown in audit.unaddressable(receipt):
                trace.check(False, hop, f"Lint-C 无玩法或帮助入口 {unknown!r}")
            finished = "第一章·客栈风云 已完成" in receipt
            selected = ""
            if receipt and not finished:
                try:
                    # 杀死监听与结算进程，再用新玩家驱动实例读上一条回执。
                    if not restarted and "加点草稿" in receipt:
                        worker.restart()
                        restarted = True
                        driver = ReceiptDriver(scenario.open_letter, scenario.join)
                    selected = driver.next(receipt)
                except ValueError as error:
                    trace.check(False, hop, str(error))
            trace.rows.append(
                (
                    hop,
                    datetime.fromtimestamp(now, BJ).strftime("%m-%d %H:%M:%S"),
                    command,
                    receipt,
                    selected,
                    f"{genuine} / {business} / {model}",
                    audit.state_label(after),
                )
            )
            if finished or not selected:
                break
            # 只有当前复制的动作需要等待时才拨钟；首胜的续章预告不会延迟当场练功。
            ready = re.search(r"北京时间 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", receipt)
            if ready and selected in ("二狗打坐", "二狗主线"):
                at = datetime.strptime(ready[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)
                now = max(now, at.timestamp())
            elif selected == "二狗打坐" and ("已开始打坐" in receipt or "出关 ·" in receipt):
                now += scenario.rest
            command = selected
        else:
            trace.check(False, hop, "Lint-A 回执循环，超过 25 跳")
    expected = (
        {"自胜", "解围"}
        if scenario.open_letter
        else {"加入" if scenario.join else "婉拒"}
    )
    p, events = after["player"], after["events"]
    count = int(scenario.join)
    trace.check(restarted, hop, "未完成进程替换")
    trace.check(
        finished
        and p.get("ending") in expected
        and p.get("completed_at") is not None
        and p.get("level") == 3
        and p.get("next_state") == "done"
        and events.get("chapter_done", 0) == 1
        and events.get("first_win", 0) == 1
        and events.get("join_broadcast", 0) == count
        and after["notices"] == count,
        hop,
        f"终态未通过，应达{'或'.join(sorted(expected))}、Lv.3、完结一次、恭贺 {count} 条；"
        f"实到 {p.get('ending') or '未结局'}、Lv.{p.get('level', 0)}、"
        f"完结 {events.get('chapter_done', 0)} 次、恭贺 {after['notices']} 条",
    )
    trace.status = (
        f"草稿回执后强制换进程{'已执行' if restarted else '未执行'}。"
        f"首胜 {events.get('first_win', 0)}，章节完结 {events.get('chapter_done', 0)}，"
        f"入门事件 {events.get('join_broadcast', 0)}，含恭贺的实际发件箱记录 {after['notices']}。"
    )
    return trace


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        traces = [
            run(Path(directory) / f"case-{i}.sqlite", s)
            for i, s in enumerate(SCENARIOS)
        ]
    print("# 江湖 P1 逐字盲走回放\n\n" + "\n\n".join(t.markdown() for t in traces))
    sys.exit(int(any(t.failures for t in traces)))
