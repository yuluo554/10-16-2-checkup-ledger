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
    code, _out, err = run_cli(["ingest"])
    assert code == EXIT_NOT_READY
    assert "尚未落地" in err


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
