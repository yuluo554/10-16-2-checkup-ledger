"""判定内核契约：四态语义、单一定义点、纯函数。

本文件锁住"口径只有一处实现"——`judge()` 曾自己重复了"无区间 → 拒判"的分支，
与 `compare()` 构成两份实现（改一处漏一处会让语义悄悄分叉）。变异验证抓出后
改为单点，并由本文件守门。

**区间夹具一律从知识库取**（`helpers.bounds_pair` 等）：测试里手写区间数值
会让测试成为"区间数值的第二处定义"——改 YAML 改不动它，断言退化成对陈年
数字的自我确认。零字面量门禁扫 `tests/` 正是为了拦这个。
"""

import inspect

import pytest

from helpers import bounds_pair, step_of, yaml_bounds

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

# 夹具：ALT 的区间与单位（全部来自 YAML）
ALT_LOW, ALT_HIGH = bounds_pair("ALT")
ALT_UNIT = yaml_bounds("ALT")["unit"]
ALT_STEP = step_of(ALT_HIGH)


def _m(value, printed=None, name="ALT", unit=None):
    return Measurement(canonical_name=name, raw_name=name, value=value,
                       unit=unit or ALT_UNIT, ref_range_printed=printed)


def _r(low, high, bounds=BOUNDS_CLOSED):
    return RefRange(low=low, high=high, bounds=bounds)


def _alt_range(bounds=BOUNDS_CLOSED):
    return _r(ALT_LOW, ALT_HIGH, bounds)


# ---------------------------------------------------------------- 四态


def test_compare_four_states():
    above = ALT_HIGH + ALT_STEP
    below = ALT_LOW - ALT_STEP
    inside = ALT_LOW
    assert engine.compare(above, _alt_range()) == FLAG_HIGH
    assert engine.compare(below, _alt_range()) == FLAG_LOW
    assert engine.compare(inside, _alt_range()) == FLAG_NORMAL


def test_compare_no_range_is_not_assessed_not_normal():
    """无区间 = 拒判，**绝不是** normal——这是本题最容易失守的语义。"""
    result = engine.compare(ALT_LOW, RefRange(low=None, high=None, bounds=BOUNDS_CLOSED,
                                              source=RANGE_SOURCE_NONE))
    assert result == FLAG_NOT_ASSESSED
    assert result != FLAG_NORMAL


def test_compare_only_returns_declared_flags():
    for value in (ALT_LOW, ALT_HIGH, ALT_LOW - ALT_STEP, ALT_HIGH + ALT_STEP):
        assert engine.compare(value, _alt_range()) in ALL_FLAGS


# ---------------------------------------------------------------- 边界


def test_closed_bounds_include_endpoints():
    assert engine.compare(ALT_HIGH, _alt_range(BOUNDS_CLOSED)) == FLAG_NORMAL
    assert engine.compare(ALT_LOW, _alt_range(BOUNDS_CLOSED)) == FLAG_NORMAL


def test_open_bounds_exclude_endpoints():
    assert engine.compare(ALT_HIGH, _alt_range(BOUNDS_OPEN)) == FLAG_HIGH
    assert engine.compare(ALT_LOW, _alt_range(BOUNDS_OPEN)) == FLAG_LOW


def test_one_sided_range_does_not_limit_missing_side():
    """单侧上限（如 TC）：只给上限时下限不设限。"""
    tc_high = yaml_bounds("TC")["high"]
    far_above = tc_high * 2
    far_below = tc_high / 2
    assert engine.compare(far_above, _r(None, tc_high)) == FLAG_HIGH
    assert engine.compare(far_below, _r(None, tc_high)) == FLAG_NORMAL


# ---------------------------------------------------------------- 区间校验


@pytest.mark.parametrize(
    "ref",
    [
        RefRange(low=ALT_LOW, high=ALT_HIGH, bounds="half-open"),          # 未知边界语义
        RefRange(low=ALT_LOW, high=ALT_HIGH, bounds=BOUNDS_CLOSED, source="guessed"),  # 未知来源
        RefRange(low=ALT_HIGH, high=ALT_LOW, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_BUILTIN),  # 颠倒
        RefRange(low=None, high=None, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_BUILTIN),  # 空区间却称有来源
    ],
)
def test_invalid_range_is_rejected_loudly(ref):
    """非法区间必须**抛错**，不得静默回落成"拒判"——那会把配置缺陷读成"一切正常"。"""
    with pytest.raises(engine.RangeError):
        engine.compare(ALT_LOW, ref)


# ---------------------------------------------------------------- 三级优先


def test_printed_range_wins_over_default():
    printed = _r(ALT_LOW, ALT_HIGH)
    looser_default = _r(ALT_LOW, ALT_HIGH + ALT_STEP)  # 默认更宽 → 同值结论不同
    value = ALT_HIGH + ALT_STEP
    judged = engine.judge(_m(value, printed=printed), looser_default)
    assert judged.flag == FLAG_HIGH
    assert judged.range_source == RANGE_SOURCE_REPORT


def test_printed_range_wins_even_when_partial():
    """自印只印上限也优先于默认（报告上印的才是有效区间）。"""
    tc_high = yaml_bounds("TC")["high"]
    value = tc_high + step_of(tc_high)
    judged = engine.judge(_m(value, printed=_r(None, tc_high), name="TC"), _r(None, tc_high / 2))
    assert judged.flag == FLAG_HIGH
    assert judged.range_source == RANGE_SOURCE_REPORT


def test_default_used_when_no_printed():
    judged = engine.judge(_m(ALT_HIGH + ALT_STEP), _alt_range())
    assert judged.flag == FLAG_HIGH
    assert judged.range_source == RANGE_SOURCE_BUILTIN


def test_no_range_yields_not_assessed_source_none():
    judged = engine.judge(_m(ALT_HIGH + ALT_STEP), None)
    assert judged.flag == FLAG_NOT_ASSESSED
    assert judged.range_source == RANGE_SOURCE_NONE


def test_select_range_source_labels_are_rewritten():
    """选出的区间必须被标成对应来源——来源标注是产物可追溯性的载体。"""
    printed = _r(ALT_LOW, ALT_HIGH)
    assert engine.select_range(_m(ALT_LOW, printed=printed), None).source == RANGE_SOURCE_REPORT
    assert engine.select_range(_m(ALT_LOW), _alt_range()).source == RANGE_SOURCE_BUILTIN
    assert engine.select_range(_m(ALT_LOW), None).source == RANGE_SOURCE_NONE


# ---------------------------------------------------------------- 适用域（applies_to.sex）


def test_sex_constraint_blocks_inapplicable_default():
    """区间主体不适用 → 等同没有区间 → 拒判（**不是**拿不适用的区间下结论）。

    这是"这条规则不该命中"的机制：女性样本配男性区间，值落在区间内也不得判 normal。
    """
    hgb_low, hgb_high = bounds_pair("HGB")
    inside = hgb_low
    judged = engine.judge(
        _m(inside, name="HGB"), _r(hgb_low, hgb_high),
        subject_sex="female", default_constraint="male",
    )
    assert judged.flag == FLAG_NOT_ASSESSED
    assert judged.range_source == RANGE_SOURCE_NONE


def test_sex_constraint_allows_matching_subject():
    """主体匹配 → 区间适用，照常判定（反向对照：门不是"一律拒判"）。"""
    hgb_low, hgb_high = bounds_pair("HGB")
    judged = engine.judge(
        _m(hgb_low - step_of(hgb_low), name="HGB"), _r(hgb_low, hgb_high),
        subject_sex="male", default_constraint="male",
    )
    assert judged.flag == FLAG_LOW
    assert judged.range_source == RANGE_SOURCE_BUILTIN


def test_sex_any_applies_regardless_of_subject():
    judged = engine.judge(_m(ALT_HIGH + ALT_STEP), _alt_range(),
                          subject_sex="female", default_constraint="any")
    assert judged.flag == FLAG_HIGH
    assert judged.range_source == RANGE_SOURCE_BUILTIN


def test_unknown_subject_sex_does_not_get_constrained_range():
    """主体未知时不得套用带主体限制的区间——宁拒判，不拿不适用的区间下结论。"""
    hgb_low, hgb_high = bounds_pair("HGB")
    judged = engine.judge(_m(hgb_low, name="HGB"), _r(hgb_low, hgb_high),
                          subject_sex=None, default_constraint="male")
    assert judged.flag == FLAG_NOT_ASSESSED


def test_invalid_sex_constraint_is_rejected_loudly():
    """未知的 applies_to.sex 必须抛错，不得静默降级成"不适用"。"""
    with pytest.raises(engine.RangeError):
        engine.range_applies_to("unknown", "male")


def test_printed_range_is_not_blocked_by_sex_constraint():
    """自印区间是该受检者报告上的区间，主体天然适用——不受 default_constraint 影响。"""
    hgb_low, hgb_high = bounds_pair("HGB")
    judged = engine.judge(
        _m(hgb_low, printed=_r(hgb_low, hgb_high), name="HGB"), None,
        subject_sex="female", default_constraint="male",
    )
    assert judged.range_source == RANGE_SOURCE_REPORT
    assert judged.flag == FLAG_NORMAL


# ---------------------------------------------------------------- 趋势


def test_trend_direction_three_states():
    low, high = bounds_pair("ALT")
    assert engine.trend_direction(engine.trend_delta(low, high)) == "up"
    assert engine.trend_direction(engine.trend_delta(high, low)) == "down"
    assert engine.trend_direction(engine.trend_delta(high, high)) == "flat"


def test_trend_delta_is_signed_fact_only():
    low, high = bounds_pair("ALT")
    assert engine.trend_delta(low, high) == high - low
    assert engine.trend_delta(high, low) == low - high


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
    for value in (ALT_LOW - ALT_STEP, ALT_LOW, ALT_HIGH, ALT_HIGH + ALT_STEP):
        judged = engine.judge(_m(value), _alt_range())
        assert judged.flag == engine.compare(value, judged.range_used)


def test_judge_all_maps_defaults_by_name():
    ms = [_m(ALT_HIGH + ALT_STEP, name="ALT"), _m(ALT_LOW - ALT_STEP, name="AST"),
          _m(ALT_LOW, name="XXX")]
    judged = engine.judge_all(ms, {"ALT": _alt_range(), "AST": _alt_range()})
    assert [j.flag for j in judged] == [FLAG_HIGH, FLAG_LOW, FLAG_NOT_ASSESSED]


def test_judge_all_applies_sex_constraints():
    hgb_low, hgb_high = bounds_pair("HGB")
    ms = [_m(hgb_low, name="HGB")]
    judged = engine.judge_all(
        ms, {"HGB": _r(hgb_low, hgb_high)},
        subject_sex="female", constraints={"HGB": "male"},
    )
    assert judged[0].flag == FLAG_NOT_ASSESSED


def test_judge_is_pure_deterministic():
    a = engine.judge(_m(ALT_HIGH + ALT_STEP), _alt_range())
    b = engine.judge(_m(ALT_HIGH + ALT_STEP), _alt_range())
    assert (a.flag, a.range_source, a.range_used) == (b.flag, b.range_source, b.range_used)
