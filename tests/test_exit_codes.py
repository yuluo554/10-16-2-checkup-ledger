"""退出码契约：0/1/2/3 每级至少一条断言。

非零 ≠ 跑挂：`1` 是"工具查出了不合规"这一**成功执行 + 负面结论**。

**`4`（`NOT_READY` 阶段未就绪）已在 M4 整项退役**：首期五模块（输入 / 规范化 /
判定 / 台账 / 导出+报告）全部落地，没有"尚未落地"的模块需要显式拦截。退役的
四处同步在本文件体现为**防复活断言**：常量若还在、或某个子命令还留着
`not_ready` 分派，本文件就会红。
"""

import os
import sys

import pytest

from helpers import requires_pdf, repo_path, run_cli

from checkup_ledger.exit_codes import (
    ALL_EXIT_CODES,
    EXIT_FINDINGS,
    EXIT_MISSING_DEP,
    EXIT_OK,
    EXIT_USAGE,
)


def test_exit_code_set_is_complete():
    """M4 退役后契约是四级：0/1/2/3。"""
    assert set(ALL_EXIT_CODES) == {0, 1, 2, 3}


def test_exit_codes_are_distinct():
    assert len(set(ALL_EXIT_CODES)) == len(ALL_EXIT_CODES)


def test_exit_ok_from_version():
    code, out, _err = run_cli(["version"])
    assert code == EXIT_OK
    assert "checkup-ledger" in out


def test_exit_ok_from_help():
    code, _out, _err = run_cli(["--help"])
    assert code == EXIT_OK


def test_exit_ok_from_selftest():
    code, out, _err = run_cli(["selftest"])
    assert code == EXIT_OK
    assert "自检结论" in out


def test_exit_ok_from_bench():
    code, out, _err = run_cli(["bench"])
    assert code == EXIT_OK
    assert "达标" in out


def test_exit_findings_from_probe_fault():
    """探活：注入缺陷后基准必须报未达标（exit 1）。"""
    code, out, _err = run_cli(["bench", "--probe-fault"])
    assert code == EXIT_FINDINGS
    assert "未达标" in out


def test_exit_usage_from_unknown_command():
    code, _out, err = run_cli(["no-such-command"])
    assert code == EXIT_USAGE
    assert "未知命令" in err


def test_exit_usage_from_unknown_flag():
    code, _out, err = run_cli(["version", "--bogus-flag"])
    assert code == EXIT_USAGE
    assert "用法错误" in err


def test_exit_usage_from_missing_command():
    code, _out, _err = run_cli([])
    assert code == EXIT_USAGE


def test_exit_usage_from_unknown_bench_suite():
    code, _out, err = run_cli(["bench", "--only", "NOPE"])
    assert code == EXIT_USAGE
    assert "未知名套件" in err


@requires_pdf
def test_ingest_is_no_longer_intercepted_by_not_ready():
    """M2：模块① 输入层已落地，**不得**再走 exit 4 拦截。

    这条是"退役四处同步"的第三处（测试面）：分派改了但测试仍断言 exit 4，
    退役就没真发生。断言用"给定真实输入得到真实结果"而非"不再报未就绪"——
    后者可以被"改成报别的错"满足，前者才证明它真的接了实现。
    """
    sample = repo_path("data", "samples", "ingest", "pdf", "ingest-pdf-plain.pdf")
    code, out, err = run_cli(["ingest", sample])
    assert code != 4, "ingest 仍在走未就绪拦截（退役未生效）：%s" % err
    assert "尚未落地" not in err, "ingest 仍报未就绪文案"
    assert "抽取引擎" in out, "ingest 未走真实实现：\n%s" % out


@requires_pdf
def test_normalize_is_no_longer_intercepted_by_not_ready():
    """M3：模块② 规范化层已落地，**不得**再走 exit 4 拦截。

    与 `ingest` 同形态：断言落在"给定真实输入得到真实结果"上——只断言
    "不再报未就绪"是弱断言（改成报别的错也能满足它）。
    """
    sample = repo_path("data", "samples", "ingest", "pdf", "ingest-pdf-plain.pdf")
    code, out, err = run_cli(["normalize", sample])
    assert code != 4, "normalize 仍在走未就绪拦截（退役未生效）：%s" % err
    assert "尚未落地" not in err, "normalize 仍报未就绪文案"
    assert "已映射" in out, "normalize 未走真实实现：\n%s" % out
    # 端到端贯通：报告行 → 规范化 → 判定，判定来源必须显式可见
    assert "report_printed" in out, "判定来源未在产物里显式可见：\n%s" % out


@requires_pdf
def test_ledger_export_report_are_no_longer_intercepted_by_not_ready():
    """M4：模块④ 台账与模块⑤ 导出/报告已落地，**不得**再走 exit 4 拦截。

    三条命令都断言"给定真实输入得到真实结果"（而不是"不再报未就绪"）：
    - `ledger`：入库后台账里有行（`入库 N 条`）；
    - `export`：导出物真的落盘且内容含表头；
    - `report`：HTML 真的落盘且含折线图元。

    这里用**显式临时库/临时产物路径**，不碰用户主目录与 CWD。
    """
    import tempfile

    sample = repo_path("data", "samples", "ingest", "pdf", "ingest-pdf-plain.pdf")

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "ledger.db")
        code, out, err = run_cli(
            ["ledger", sample, "--db", db, "--date", "2024-03-11", "--subject", "张三"]
        )
        assert code != 4, "ledger 仍在走未就绪拦截（退役未生效）：%s" % err
        assert "尚未落地" not in err, "ledger 仍报未就绪文案"
        assert "入库 4 条" in out, "ledger 未走真实实现：\n%s" % out

        out_csv = os.path.join(tmp, "s.csv")
        code, out, err = run_cli(
            ["export", sample, "--db", db, "--date", "2024-03-11", "--subject", "张三",
             "--out", out_csv, "--fmt", "csv"]
        )
        assert code != 4, "export 仍在走未就绪拦截（退役未生效）：%s" % err
        assert "尚未落地" not in err, "export 仍报未就绪文案"
        assert os.path.isfile(out_csv), "export 未落盘产物"
        assert "指标,日期,数值" in open(out_csv, encoding="utf-8").read(), "导出物缺表头"

        out_html = os.path.join(tmp, "r.html")
        code, out, err = run_cli(
            ["report", sample, "--db", db, "--date", "2024-03-11", "--subject", "张三",
             "--out", out_html]
        )
        assert code != 4, "report 仍在走未就绪拦截（退役未生效）：%s" % err
        assert "尚未落地" not in err, "report 仍报未就绪文案"
        assert os.path.isfile(out_html), "report 未落盘产物"
        assert "<svg" in open(out_html, encoding="utf-8").read(), "报告缺折线图元"


def test_not_ready_module_list_is_gone():
    """防幽灵语义复活（M4 整项退役）：拦截名单与常量必须一并消失。

    判据落在"模块属性还在不在"上，而不是"名单是不是空的"——把名单改成空
    dict 也能让"名单为空"成立，而 `cmd_not_ready` 与常量仍留在源码里
    （语义复活）。故这里**直接断言属性不存在**。
    """
    import checkup_ledger.cli as cli_mod
    import checkup_ledger.exit_codes as exit_mod

    assert not hasattr(cli_mod, "_NOT_READY_MODULES"), (
        "首期五模块全部落地，_NOT_READY_MODULES 应随退役删除（幽灵语义复活）"
    )
    assert not hasattr(cli_mod, "cmd_not_ready"), (
        "cmd_not_ready 应随退役删除（幽灵语义复活）"
    )
    assert not hasattr(exit_mod, "EXIT_NOT_READY"), (
        "EXIT_NOT_READY 常量应随退役删除（幽灵语义复活）"
    )


def test_missing_dep_constant_exists():
    """缺依赖出口常量的取值锁定（模块①②落地后由真实路径覆盖）。"""
    assert EXIT_MISSING_DEP == 3
    assert EXIT_MISSING_DEP not in (EXIT_OK, EXIT_FINDINGS, EXIT_USAGE)


@pytest.mark.skipif(sys.version_info < (3, 8), reason="require 3.8+")
def test_exit_codes_module_has_no_resurrected_stage_codes():
    """防幽灵语义复活：退役时必须连常量一起删。"""
    import checkup_ledger.exit_codes as mod

    for name in dir(mod):
        if name.startswith("EXIT_") and name not in (
            "EXIT_OK",
            "EXIT_FINDINGS",
            "EXIT_USAGE",
            "EXIT_MISSING_DEP",
        ):
            assert name in ("EXIT_CODES",), "出现未登记的新退出码常量：%s" % name
