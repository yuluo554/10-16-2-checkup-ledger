"""退出码契约：0/1/2/3/4 每级至少一条断言。

非零 ≠ 跑挂：`1` 是"工具查出了不合规"这一**成功执行 + 负面结论**。
`4` 是"阶段未就绪"，语义是**显式拦截、不伪造空结果**。
"""

import sys

import pytest

from helpers import run_cli

from checkup_ledger.exit_codes import (
    ALL_EXIT_CODES,
    EXIT_FINDINGS,
    EXIT_MISSING_DEP,
    EXIT_NOT_READY,
    EXIT_OK,
    EXIT_USAGE,
)


def test_exit_code_set_is_complete():
    assert set(ALL_EXIT_CODES) == {0, 1, 2, 3, 4}


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


def test_exit_not_ready_from_unimplemented_module():
    """未实现模块必须显式拦截，而不是返回伪造的空结果。"""
    code, _out, err = run_cli(["ledger"])
    assert code == EXIT_NOT_READY
    assert "尚未落地" in err


def test_ingest_is_no_longer_intercepted_by_not_ready():
    """M2：模块① 输入层已落地，**不得**再走 exit 4 拦截。

    这条是"退役四处同步"的第三处（测试面）：分派改了但测试仍断言 exit 4，
    退役就没真发生。断言用"给定真实输入得到真实结果"而非"不再报未就绪"——
    后者可以被"改成报别的错"满足，前者才证明它真的接了实现。
    """
    from helpers import repo_path

    sample = repo_path("data", "samples", "ingest", "pdf", "ingest-pdf-plain.pdf")
    code, out, err = run_cli(["ingest", sample])
    assert code != EXIT_NOT_READY, "ingest 仍在走未就绪拦截（退役未生效）：%s" % err
    assert "尚未落地" not in err, "ingest 仍报未就绪文案"
    assert "抽取引擎" in out, "ingest 未走真实实现：\n%s" % out


def test_not_ready_module_list_excludes_landed_module():
    """防幽灵语义复活：已落地模块不得留在拦截名单里。"""
    from checkup_ledger.cli import _NOT_READY_MODULES

    assert "ingest" not in _NOT_READY_MODULES, (
        "已落地模块仍在未就绪名单：%s" % sorted(_NOT_READY_MODULES)
    )
    # 其余模块尚未落地，仍应在名单内（防"一刀切清空"把拦截也删掉）
    for name in ("normalize", "ledger", "export", "report"):
        assert name in _NOT_READY_MODULES, "尚未落地的模块 %s 被移出拦截名单" % name


def test_not_ready_constant_is_retained_until_last_module_lands():
    """**部分退役**是 M2 的有意决策，不是"忘了删常量"。

    待办原文写的是"本模块的拦截点整项退役"。实现时按"触发点逐个退役"处置：
    常量保留（其余四个模块仍在使用它），只把已落地模块移出拦截名单。
    理由：若提前删常量，其余未落地模块只能借用 `EXIT_USAGE`，那会把"阶段未就绪"
    读成"用法错误"——一个语义明确的码被换成一个语义错误的码，是**退步**。

    这条断言的作用：让后来者知道"常量还在"是**设计内行为**，
    并钉住"只有全部模块落地后才可删"的判据（那时本测试也要一并改）。
    """
    import checkup_ledger.exit_codes as mod
    from checkup_ledger.cli import _NOT_READY_MODULES

    if _NOT_READY_MODULES:
        assert hasattr(mod, "EXIT_NOT_READY"), (
            "仍有模块未落地，却已删除 EXIT_NOT_READY——它们只能借用用法错误码（语义退步）"
        )
    else:  # pragma: no cover - 首期全部落地后才走到这里（M4）
        assert not hasattr(mod, "EXIT_NOT_READY"), (
            "首期模块全部落地，EXIT_NOT_READY 应整项退役（连带本测试一并改）"
        )


def test_not_ready_does_not_fake_empty_result():
    """未就绪路径不得打印任何看起来像正常结果的表格/计数。"""
    _code, out, _err = run_cli(["ledger"])
    assert "0 条记录" not in out
    assert "成功" not in out


def test_missing_dep_constant_exists():
    """缺依赖出口常量的取值锁定（模块①②落地后由真实路径覆盖）。"""
    assert EXIT_MISSING_DEP == 3
    assert EXIT_MISSING_DEP not in (EXIT_OK, EXIT_FINDINGS, EXIT_USAGE, EXIT_NOT_READY)


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
            "EXIT_NOT_READY",
        ):
            assert name in ("EXIT_CODES",), "出现未登记的新退出码常量：%s" % name
