"""玩家视角。此模块只接收最后一条微信正文，不访问玩法、数据库或测试断言。"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Copy:
    start: int
    end: int

    def read(self, receipt: str) -> str:
        return receipt.encode()[self.start : self.end].decode()


def choices(receipt: str, prefix="二狗") -> list[Copy]:
    # 以 UTF-8 原文偏移截取整行。换行是行边界，行内全角字符及空格不做归一化。
    pattern = (
        rb"(?m)^(?:[ \t]|\xe3\x80\x80)*" + re.escape(prefix.encode()) + rb"[^\r\n]*"
    )
    raw = receipt.encode()
    found = [Copy(*m.span()) for m in re.finditer(pattern, raw)]
    # 明确括起的完整命令也可复制。保留括号内换行，不给简称补前缀。
    for left, right in (("「", "」"), ("【", "】"), ("“", "”")):
        quoted = (
            re.escape(left.encode())
            + b"("
            + re.escape(prefix.encode())
            + rb".*?)"
            + re.escape(right.encode())
        )
        for m in re.finditer(quoted, raw, re.DOTALL):
            start, end = m.span(1)
            if not any(item.start <= start and end <= item.end for item in found):
                found.append(Copy(start, end))
    return sorted(found, key=lambda item: item.start)


@dataclass(frozen=True)
class ReceiptDriver:
    open_letter: bool
    join: bool = False
    prefix: str = "二狗"

    @staticmethod
    def start():
        return "二狗闯江湖"

    def next(self, receipt: str) -> str:
        options = choices(receipt, self.prefix)
        if len(options) == 1:
            return options[0].read(receipt)
        if not options:
            raise ValueError("Lint-A 正文没有可整行复制的下一步")
        if len(options) == 2:
            # 只依据玩家眼前的剧情与个人选择，两个身份统一选择平民。
            if "平民出身" in receipt:
                return options[0].read(receipt)
            if "拆开查看" in receipt and "原封退还" in receipt:
                return options[0 if self.open_letter else 1].read(receipt)
            if "加入镖局" in receipt and "婉拒" in receipt:
                return options[0 if self.join else 1].read(receipt)
        raise ValueError("Lint-A 当前多个选项无法从回执辨认用途")
