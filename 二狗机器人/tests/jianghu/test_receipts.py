import pytest

from ergou.engine import UNKNOWN_COMMAND

from . import audit
from .driver import ReceiptDriver
from .replay import SCENARIOS, run
from .transport import session


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_cold_to_ending(tmp_path, scenario):
    trace = run(tmp_path / "room.sqlite", scenario)
    print("\n" + trace.markdown())
    assert not trace.failures, "\n".join(trace.failures)


def test_exact_copy():
    driver = ReceiptDriver(True)
    body = "建议整行复制\r\n二狗选　１  \r\n末尾说明"
    assert driver.next(body).encode() == "二狗选　１  ".encode()
    assert driver.next("请发「二狗选　1」继续") == "二狗选　1"
    assert (
        driver.next("请发「二狗加点 臂力20\n身法20」继续") == "二狗加点 臂力20\n身法20"
    )
    for text in ("明天可发【主线】", "🧘 尚未满一小时，进度已保留。"):
        with pytest.raises(ValueError, match="Lint-A"):
            driver.next(text)


def test_leak_and_address_lints(tmp_path):
    path = tmp_path / "lint.sqlite"
    with session(path):
        pattern = audit.leak_pattern(path)
    for hidden in (
        "max_hp",
        "group_id",
        "event_type",
        "jh_invites",
        "BEGIN  IMMEDIATE",
        "first_win_at",
    ):
        assert pattern.search("正文" + hidden + "泄漏")
    assert not pattern.search("气血上限 300，身法 20")
    assert audit.addressable("加点 臂力20 身法20 根骨30 悟性10")
    assert not audit.addressable("加点 ？？")
    assert not audit.addressable("主 线")


@pytest.mark.parametrize("token", ("历练", "主线", "打坐", "确认加点"))
def test_fixed_command_near_misses(tmp_path, token):
    path = tmp_path / "routing.sqlite"
    with session(path) as worker:
        before = audit.snapshot(path)
        pattern = audit.leak_pattern(path)
        for presentation in (token, " " + token + " ", "　" + token + "　"):
            seq, body = worker.send("二狗" + presentation)
            assert audit.tagged(path, seq) and "先到悦来客栈报个名" in body, (
                presentation,
                body,
            )
            assert not pattern.search(body)
        near_alias = {
            "历练": "江湖试炼",
            "主线": "江湖正传",
            "打坐": "盘腿打坐",
            "确认加点": "确认分配属性",
        }[token]
        for unsupported in (
            near_alias,
            token[:1] + " " + token[1:],
            token[:1] + "　" + token[1:],
            token + "A",
            token + "a",
            token + "Ａ",
            token + "ａ",
            token + "?",
            token + "？",
        ):
            seq, body = worker.send("二狗" + unsupported)
            assert body == UNKNOWN_COMMAND.format(prefix="二狗"), (unsupported, body)
            assert not audit.tagged(path, seq) and not pattern.search(body)
        _, body = worker.send(token)
        assert not body and audit.snapshot(path) == before
        _, body = worker.send("@二狗\u2005" + token, mentioned=True)
        assert not body and audit.snapshot(path) == before | {
            "model": before["model"] + 1
        }


def test_declared_aliases(tmp_path):
    path = tmp_path / "aliases.sqlite"
    with session(path) as worker:
        before = audit.snapshot(path)
        pattern = audit.leak_pattern(path)
        _, expected = worker.send("二狗江湖录帮助")
        assert (
            "闯江湖" in expected
            and not pattern.search(expected)
            and not audit.unaddressable(expected)
        )
        for cmd in ("江湖帮助", "江湖菜单", "江湖录菜单"):
            assert audit.addressable(cmd)
            assert worker.send("二狗" + cmd)[1] == expected
        for cmd in ("面板", "江湖面板", "选1", "选 1"):
            seq, body = worker.send("二狗" + cmd)
            assert (
                audit.tagged(path, seq)
                and not pattern.search(body)
                and "先到悦来客栈" in body
            )
        assert audit.snapshot(path) == before


def test_existing_six_endings_receipt_lints():
    """用既有 R1–R6 脚本抵达盲走尚不可达的回执，单列其证据性质。"""
    from tests.test_jianghu import JianghuReplay

    class ScriptedEndings(JianghuReplay):
        def send(self, text, **kwargs):
            body = super().send(text, **kwargs)
            if not hasattr(self, "leaks"):
                self.leaks = audit.leak_pattern(self.path)
            assert not self.leaks.search(body), (text, body)
            assert not audit.unaddressable(body), (text, body)
            return body

    case = ScriptedEndings("test_r1_through_r6")
    try:
        case.setUp()
        case.test_r1_through_r6()
    finally:
        case.doCleanups()
