"""判定内核契约：四态语义、单一定义点、纯函数。

本文件锁住"口径只有一处实现"——`judge()` 曾自己重复了"无区间 → 拒判"的分支，
与 `compare()` 构成两份实现（改一处漏一处会让语义悄悄分叉）。变异验证抓出后
改为单点，并由本文件守门。
"""

import inspect

import pytest

from checkup_ledger.engine import compare as engine

from checkup_ledger.model import (
    ALL_FLAGS,
    BOUNDS_CLOSED,
    BOUNDS_OPEN,
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_NOT_ASSESSED,
    Measurement,
    RANGE_SOURCE_BUILTIN,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
    RefRange,
)


def _m(value, printed=None, name="ALT"):
    return Measurement(canonical_name=name, raw_name=name, value=value, unit="U/L",
                       ref_range_printed=printed)


def _r(low, high, bounds=BOUNDS_CLOSED):
    return RefRange(low=low, high=high, bounds=bounds)


# ---------------------------------------------------------------- 四态


@pytest.mark.parametrize(
    "value,expected",
    [(47.0, FLAG_HIGH), (5.0, FLAG_LOW), (25.0, FLAG_NORMAL)],
)
def test_compare_four_states(value, expected):
    assert engine.compare(value, _r(9, 40)) == expected


def test_compare_no_range_is_not_assessed_not_normal():
    """无区间 = 拒判，**绝不是** normal——这是本题最容易失守的语义。"""
    result = engine.compare(25.0, RefRange(low=None, high=None, bounds=BOUNDS_CLOSED,
                                           source=RANGE_SOURCE_NONE))
    assert result == FLAG_NOT_ASSESSED
    assert result != FLAG_NORMAL


def test_compare_only_returns_declared_flags():
    for value in (0.0, 9.0, 25.0, 40.0, 100.0):
        assert engine.compare(value, _r(9, 40)) in ALL_FLAGS


# ---------------------------------------------------------------- 边界


def test_closed_bounds_include_endpoints():
    assert engine.compare(40.0, _r(9, 40, BOUNDS_CLOSED)) == FLAG_NORMAL
    assert engine.compare(9.0, _r(9, 40, BOUNDS_CLOSED)) == FLAG_NORMAL


def test_open_bounds_exclude_endpoints():
    assert engine.compare(40.0, _r(9, 40, BOUNDS_OPEN)) == FLAG_HIGH
    assert engine.compare(9.0, _r(9, 40, BOUNDS_OPEN)) == FLAG_LOW


def test_one_sided_range_does_not_limit_missing_side():
    assert engine.compare(1000.0, _r(None, 5.2)) == FLAG_HIGH
    assert engine.compare(0.1, _r(None, 5.2)) == FLAG_NORMAL


# ---------------------------------------------------------------- 区间校验


@pytest.mark.parametrize(
    "ref",
    [
        RefRange(low=9, high=40, bounds="half-open"),          # 未知边界语义
        RefRange(low=9, high=40, bounds=BOUNDS_CLOSED, source="guessed"),  # 未知来源
        RefRange(low=40, high=9, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_BUILTIN),  # 上下限颠倒
        RefRange(low=None, high=None, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_BUILTIN),  # 空区间却称有来源
    ],
)
def test_invalid_range_is_rejected_loudly(ref):
    """非法区间必须**抛错**，不得静默回落成"拒判"——那会把配置缺陷读成"一切正常"。"""
    with pytest.raises(engine.RangeError):
        engine.compare(25.0, ref)


# ---------------------------------------------------------------- 三级优先


def test_printed_range_wins_over_default():
    judged = engine.judge(_m(42.0, printed=_r(9, 40)), _r(9, 50))
    assert judged.flag == FLAG_HIGH
    assert judged.range_source == RANGE_SOURCE_REPORT


def test_printed_range_wins_even_when_partial():
    judged = engine.judge(_m(6.0, printed=_r(None, 5.2), name="TC"), _r(None, 4.0))
    assert judged.flag == FLAG_HIGH
    assert judged.range_source == RANGE_SOURCE_REPORT


def test_default_used_when_no_printed():
    judged = engine.judge(_m(47.0), _r(9, 40))
    assert judged.flag == FLAG_HIGH
    assert judged.range_source == RANGE_SOURCE_BUILTIN


def test_no_range_yields_not_assessed_source_none():
    judged = engine.judge(_m(47.0), None)
    assert judged.flag == FLAG_NOT_ASSESSED
    assert judged.range_source == RANGE_SOURCE_NONE


def test_select_range_source_labels_are_rewritten():
    """选出的区间必须被标成对应来源——来源标注是产物可追溯性的载体。"""
    printed = _r(9, 40)
    assert engine.select_range(_m(20.0, printed=printed), None).source == RANGE_SOURCE_REPORT
    assert engine.select_range(_m(20.0), _r(9, 40)).source == RANGE_SOURCE_BUILTIN
    assert engine.select_range(_m(20.0), None).source == RANGE_SOURCE_NONE


# ---------------------------------------------------------------- 单一定义点


def test_not_assessed_decision_has_single_definition_site():
    """`judge()` 不得自带"无区间 → 拒判"的分支。

    变异验证抓出的真实缺陷：judge() 曾用条件表达式重复了这个判断，与 compare()
    构成两份实现。判据 = judge 的源码里不出现 FLAG_NOT_ASSESSED 字面量。
    """
    source = inspect.getsource(engine.judge)
    assert "FLAG_NOT_ASSESSED" not in source, (
        "judge() 出现 FLAG_NOT_ASSESSED——拒判语义被重复实现在两处，"
        "应只由 compare() 决定"
    )


def test_judge_delegates_to_compare():
    """judge 的结果必须与 compare 在同一区间上一致（防止绕开单点另算）。"""
    for value in (0.0, 9.0, 25.0, 40.0, 100.0):
        judged = engine.judge(_m(value), _r(9, 40))
        assert judged.flag == engine.compare(value, judged.range_used)


def test_judge_all_maps_defaults_by_name():
    ms = [_m(47.0, name="ALT"), _m(5.0, name="AST"), _m(25.0, name="XXX")]
    judged = engine.judge_all(ms, {"ALT": _r(9, 40), "AST": _r(9, 40)})
    assert [j.flag for j in judged] == [FLAG_HIGH, FLAG_LOW, FLAG_NOT_ASSESSED]


def test_judge_is_pure_deterministic():
    a = engine.judge(_m(47.0), _r(9, 40))
    b = engine.judge(_m(47.0), _r(9, 40))
    assert (a.flag, a.range_source, a.range_used) == (b.flag, b.range_source, b.range_used)
