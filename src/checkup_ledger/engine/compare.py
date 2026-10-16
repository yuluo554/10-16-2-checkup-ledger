"""确定性判定内核。

口径唯一源：data/README.md 第五节「数值口径纪律」。本模块**不重写口径**，
只是它的唯一代码实现处（三级优先 + 四态边界比较）。

分层纪律（静态门禁守）：
- 纯函数：**无文件 I/O、无配置读取、无网络、无随机、不读时钟**。
- **不做任何解读**：不产出"建议/注意/可能/风险"类文字。
- 区间数值**只能来自知识库**：本模块不得出现任何区间数值字面量（零字面量门禁守）。
"""

from typing import Optional

from checkup_ledger.model import (
    ALL_BOUNDS,
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_NOT_ASSESSED,
    BOUNDS_CLOSED,
    Judged,
    Measurement,
    RANGE_SOURCE_BUILTIN,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
    RefRange,
)


class RangeError(ValueError):
    """区间字段非法：来源标注缺失、边界语义未知、上下限颠倒等。

    此类错误**必须显式抛出**，绝不回落成"没有区间"——那会把配置缺陷
    静默读成"拒判"，让本该报警的条目看起来一切正常。
    """


def validate_range(ref: RefRange) -> None:
    """区间结构校验。判定路径的入口门：不合法的区间拒绝参与判定。"""
    if ref.bounds not in ALL_BOUNDS:
        raise RangeError("未知的边界语义 bounds=%r（合法值：%s）" % (ref.bounds, ", ".join(ALL_BOUNDS)))
    if ref.source not in (RANGE_SOURCE_REPORT, RANGE_SOURCE_BUILTIN, RANGE_SOURCE_NONE):
        raise RangeError("未知的区间来源 source=%r" % (ref.source,))
    if ref.low is None and ref.high is None:
        if ref.source != RANGE_SOURCE_NONE:
            raise RangeError("区间上下限同时缺失，却声称来源为 %r" % (ref.source,))
        return
    if ref.low is not None and ref.high is not None and ref.low > ref.high:
        raise RangeError("区间下限定为 %r 高于上限 %r" % (ref.low, ref.high))


def compare(value: float, ref: RefRange) -> str:
    """四态边界比较。**分级优先的"比较"部分**，不管区间从哪来。

    边界归属由 `ref.bounds` 决定，不在代码里硬编码某个标准的习惯：
    - `closed`（闭区间 [low, high]）：恰等于边界 → 区间内；
    - `open`（开区间 (low, high)）：恰等于边界 → 越界。
    单侧区间（只给 low 或只给 high）对缺失的那一侧不设限。
    """
    validate_range(ref)

    if ref.low is None and ref.high is None:
        return FLAG_NOT_ASSESSED

    if ref.high is not None:
        if value > ref.high:
            return FLAG_HIGH
        if ref.bounds == "open" and value == ref.high:
            return FLAG_HIGH

    if ref.low is not None:
        if value < ref.low:
            return FLAG_LOW
        if ref.bounds == "open" and value == ref.low:
            return FLAG_LOW

    return FLAG_NORMAL


def select_range(measurement: Measurement, default: Optional[RefRange] = None) -> RefRange:
    """三级优先选区间的**唯一实现处**。

    ① 报告自印区间（最优先）
    ② 内置来源标注默认值（调用方负责只传 status=verified 的条目，pending 不得进此路径）
    ③ 无区间 → 拒判
    """
    printed = measurement.ref_range_printed
    if printed is not None:
        # 自印区间即便字段不全（如只印了上限）也优先于内置默认——报告上印的才是有效区间。
        validate_range(_as_source(printed, RANGE_SOURCE_REPORT))
        return _as_source(printed, RANGE_SOURCE_REPORT)

    if default is not None:
        validate_range(_as_source(default, RANGE_SOURCE_BUILTIN))
        return _as_source(default, RANGE_SOURCE_BUILTIN)

    return RefRange(low=None, high=None, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_NONE)


def _as_source(ref: RefRange, source: str) -> RefRange:
    """把区间标记成指定来源（保持不可变语义，返回新对象）。"""
    return RefRange(low=ref.low, high=ref.high, bounds=ref.bounds, source=source)


def judge(measurement: Measurement, default: Optional[RefRange] = None) -> Judged:
    """判定单条记录：纯函数，无 I/O。

    "无区间 → 拒判"的判定**只由 `compare()` 一处决定**——本函数不重复这个判断，
    否则同一口径会有两份实现（改一处漏一处 = 判定语义悄悄分叉）。
    """
    ref = select_range(measurement, default)
    return Judged(
        measurement=measurement,
        flag=compare(measurement.value, ref),
        range_used=ref,
        range_source=ref.source,
    )


def judge_all(measurements, defaults=None) -> list:
    """批量判定。`defaults` 为 canonical_name → RefRange 映射（只含 verified 条目）。"""
    table = defaults or {}
    return [judge(m, table.get(m.canonical_name)) for m in measurements]
