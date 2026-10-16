"""模块⑤a 就诊摘要导出：CSV / Markdown，**只陈述事实数值与变化幅度**。

职责边界（plan/03 模块⑤）：把已判定记录导出成人可读的就诊摘要。
本层**不做判定**（标记来自既有 `Judged`/台账行，不重算 H/L），
也**不做解读**——不写"建议""可能""风险提示"这类话。

三条纪律（都是"改了会打挂测试"的口径）：

1. **建议性词根逐字校验是出口的常驻行为**，不是"测试里验一次"：
   `export_summary` 每次写盘前跑 `assert_no_advisory_wording(artifact)`——
   负向词表命中即抛错（不是打印警告）。把承诺变成出口行为，测试只做旁证。
2. **变化幅度由引擎一处实算**（`engine.trend_delta` / `trend_direction`）：
   导出层不重写"涨跌"口径。首点无可比前值 → 变化列留空（**不填 0**：
   "没有可比前值"与"变化为零"是两件事，填 0 会让人以为"平稳"）。
3. **写盘单点**：产物经 `serialize.write_atomic` 写出（不各自 `open()`）。

**免责声明是产物的一部分**：就诊摘要若不带免责就外流，比不导出更糟。故产物末尾
常驻免责段——其措辞**刻意不含负向词表里的六个词根**，这样"整份产物过词根门"
与"免责必须在位"两条可以同时成立（免责若写成"不做治疗建议"就会命中 `建议`，
那是自相矛盾的写法；本文件的免责措辞因此避开词根，见 `DISCLAIMER`）。
"""

import os
from typing import Dict, List, Optional, Sequence

from checkup_ledger.engine.compare import trend_delta, trend_direction
from checkup_ledger.model import ALL_TRENDS, Judged
from checkup_ledger.serialize import write_atomic

# 负向词表：**建议性/解读性**措辞的词根。命中即判为"工具在给意见"。
# 逐字校验（不是"语义近似"）：宁可漏掉某些同义改写，也不放过这几个明确的词。
ADVISORY_ROOTS = ("建议", "可能", "风险提示", "注意", "应", "考虑")

# 百分比换算常数（**结构常数**，与参考区间端点无关）：比例 × 它 = 百分数。
# 命名为常量而不是裸字面量，让"这个 100 是什么"在代码里自明。
PERCENT_SCALE = 100.0

DISCLAIMER = (
    "本摘要只陈述数值与变化幅度的事实，不含解读。表中标记为数值与区间的机械比较结果。"
    "各机构以本机构 LIS 打印区间为最终准绳；以报告单和医嘱为准。"
    "本工具不做诊断、不做分诊、不提供医疗意见。"
)

# 产物里的标记与来源一律用**canonical token**（不换成人话标签）：
# CSV 与 Markdown 两处若各自维护一套标签，早晚一处改了一处没改
# （"同一个库导出的两份产物说法不同"）。人话标签只在渲染层（report/html.py）出现。
CSV_COLUMNS = (
    "指标",
    "日期",
    "数值",
    "单位",
    "标记",
    "所用区间下限",
    "所用区间上限",
    "区间来源",
    "上次数值",
    "上次日期",
    "变化幅度",
    "变化比例",
    "趋势",
)

_CSV_HEADER_KEYS = (
    "canonical_name",
    "date",
    "value",
    "unit",
    "flag",
    "range_low",
    "range_high",
    "range_source",
    "previous_value",
    "previous_date",
    "delta",
    "delta_pct",
    "direction",
)


class AdvisoryWordingError(AssertionError):
    """产物出现建议性词根——违反"不做解读"承诺。"""


class ExportError(RuntimeError):
    """导出参数或数据形态非法。"""


def find_advisory_wording(text: str) -> List[str]:
    """产物里出现的建议性词根（去重保序）。空列表 = 合规。"""
    hits: List[str] = []
    for root in ADVISORY_ROOTS:
        if root in text and root not in hits:
            hits.append(root)
    return hits


def assert_no_advisory_wording(text: str) -> None:
    """导出出口的常驻断言：命中词根即抛错。"""
    hits = find_advisory_wording(text)
    if hits:
        raise AdvisoryWordingError(
            "导出物出现建议性词根（违反「只陈述事实、不做解读」）：%s" % "、".join(hits)
        )


def _number(value) -> str:
    """数值的展示写法：整数不带小数点，其余保留原精度（不四舍五入到"看起来整齐"）。"""
    if value is None:
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return repr(number)


def _percent(value: Optional[float]) -> str:
    """变化比例的展示写法（带正负号）。`None` 表示无法表达（前值为零或无可比前值）。"""
    if value is None:
        return ""
    sign = "+" if value > 0 else ""
    return "%s%s%%" % (sign, _number(value * PERCENT_SCALE))


def _fact_row(item: Judged, previous: Optional[Dict[str, object]]) -> Dict[str, object]:
    """把一条判定结果摊平成事实字段（不含解读）。"""
    m = item.measurement
    ref = item.range_used
    row: Dict[str, object] = {
        "canonical_name": m.canonical_name,
        "date": "",
        "value": m.value,
        "unit": m.unit,
        "flag": item.flag,
        "range_low": ref.low,
        "range_high": ref.high,
        "range_source": item.range_source,
        "previous_value": None,
        "previous_date": "",
        "delta": None,
        "delta_pct": None,
        "direction": None,
    }
    if previous is not None:
        earlier = float(previous["value"])
        row["previous_value"] = earlier
        row["previous_date"] = previous.get("date", "")
        delta = trend_delta(earlier, float(m.value))
        direction = trend_direction(delta)
        if direction not in ALL_TRENDS:
            raise ExportError("实算出未声明的趋势态：%r" % (direction,))
        row["delta"] = delta
        row["direction"] = direction
        if earlier != 0:
            row["delta_pct"] = delta / earlier
    return row


def _render_csv(rows: Sequence[Dict[str, object]], title: str) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if title:
        writer.writerow([title])
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([_csv_cell(row, key) for key in _CSV_HEADER_KEYS])
    writer.writerow([])
    writer.writerow([DISCLAIMER])
    text = buffer.getvalue()
    return text.replace("\r\n", "\n")


def _csv_cell(row: Dict[str, object], key: str) -> str:
    if key == "delta_pct":
        return _percent(row.get("delta_pct"))
    if key in ("value", "range_low", "range_high", "previous_value", "delta"):
        return _number(row.get(key))
    # 其余列一律走 `_text`：**None 必须渲染成空串**，不能落成字面 "None"
    # （"None" 是 Python 的 repr 泄漏到产物里，用户会以为那是个有效取值）。
    return _text(row.get(key))


def _text(value) -> str:
    """文本列的统一渲染：缺值 → 空串（**不是** `"None"`）。"""
    if value is None:
        return ""
    return str(value)


def _render_markdown(rows: Sequence[Dict[str, object]], title: str) -> str:
    lines: List[str] = []
    if title:
        lines.append("# %s" % title)
        lines.append("")
    lines.append("| %s |" % " | ".join(CSV_COLUMNS))
    lines.append("|%s|" % "|".join(["---"] * len(CSV_COLUMNS)))
    for row in rows:
        lines.append("| %s |" % " | ".join(_csv_cell(row, key) for key in _CSV_HEADER_KEYS))
    lines.append("")
    lines.append("> %s" % DISCLAIMER)
    lines.append("")
    return "\n".join(lines)


def export_summary(
    judged: Sequence[Judged],
    *,
    fmt: str,
    out,
    subject: str = "",
    date: str = "",
    title: str = "",
    history: Optional[Dict[str, Sequence[Dict[str, object]]]] = None,
) -> str:
    """导出就诊摘要。返回写出的绝对路径。

    - `fmt`：`csv` 或 `md`（未知格式 → `ExportError`，不静默选一个默认）；
    - `history`：`canonical_name → 该指标既往记录列表（升序，含 date/value）`。
      给了它才计算变化幅度（**由引擎实算**）；没给则变化列留空——
      "没有可比前值"与"变化为零"是两件事，不留 0。
    - 产物末尾常驻免责段；写盘前跑建议性词根门（**出口常驻**）。
    """
    normalized = (fmt or "").strip().lower()
    if normalized not in ("csv", "md"):
        raise ExportError("未知导出格式 %r（只认 csv / md）" % (fmt,))

    table = history or {}
    rows = []
    for item in judged:
        name = item.measurement.canonical_name
        previous = _latest_before(table.get(name, ()), date)
        row = _fact_row(item, previous)
        row["date"] = date
        rows.append(row)

    rows.sort(key=lambda row: (str(row["date"]), str(row["canonical_name"])))

    if normalized == "csv":
        artifact = _render_csv(rows, title)
    else:
        artifact = _render_markdown(rows, title)

    assert_no_advisory_wording(artifact)
    write_atomic(out, artifact)
    return os.path.abspath(os.fspath(out))


def _latest_before(series: Sequence[Dict[str, object]], date: str) -> Optional[Dict[str, object]]:
    """既往序列里**严格早于** `date` 的最近一条。

    为什么要"严格早于"：同一天重跑导出的两份摘要若互相成为"上次值"，
    变化幅度会变成 0——那会把"这次没变"这个假事实写进产物。
    """
    candidate = None
    for point in series:
        point_date = str(point.get("date", ""))
        if date and point_date >= date:
            break
        candidate = point
    return candidate


def history_from_ledger(ledger, *, subject: str) -> Dict[str, List[Dict[str, object]]]:
    """从台账读回**按指标分组**的既往序列（升序）——CLI 的取数口。"""
    from checkup_ledger.ledger import rows_for

    grouped: Dict[str, List[Dict[str, object]]] = {}
    for row in rows_for(ledger, subject=subject):
        grouped.setdefault(str(row["canonical_name"]), []).append(row)
    return grouped
