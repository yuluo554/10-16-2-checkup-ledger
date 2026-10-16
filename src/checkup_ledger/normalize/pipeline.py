"""模块② 编排：把行级草稿变成可判定的 `Measurement[]`（**唯一读文件处**）。

两个入口，形态与模块① 同源：

- `normalize(lines, *, dictionary)`——**纯函数**：别名/单位表经参数接收，不读文件。
  这样"别名表只在 YAML 一处定义"这条纪律才守得住：测试与基准可以注入**夹具字典**，
  而不必去改真实知识库。
- `normalize_document(lines, *, knowledge_path=None)`——编排入口：加载知识库后调用
  `normalize`。**本模块是模块② 里唯一碰文件的地方**（与 `ingest` 的编排地位相同）。

本层**不做判定**：不 import `engine`、不产出 `FLAG_*`。它只回答"这条记录是什么"，
"这条记录是否越界"是模块③ 的事（分层由静态门禁守）。
"""

from typing import Iterable, Optional, Sequence

from checkup_ledger.model import (
    Measurement,
    Note,
    NormalizeResult,
    PendingMap,
    RANGE_SOURCE_REPORT,
    RawLine,
    RefRange,
)
from checkup_ledger.normalize.errors import NormalizeError
from checkup_ledger.normalize.mapping import (
    ALL_REASONS,
    MeasurementDictionary,
    REASON_NAME_UNMAPPED,
    REASON_RANGE_UNPARSED,
    REASON_UNIT_ABSENT,
    REASON_UNIT_UNMAPPED,
    REASON_VALUE_UNLOCATED,
    build_dictionary,
)
from checkup_ledger.normalize.parse import parse_lines

NOTE_PENDING_MAPPING = "pending_mapping"
NOTE_MAPPED = "mapped"
NOTE_HELD_BACK = "held_back"

_MESSAGE_PENDING = "有 %d 行无法映射，已进入待人工映射队列（不猜、不静默丢弃）"
_MESSAGE_MAPPED = "已映射 %d 行（指标名与单位均命中知识库登记写法）"
_MESSAGE_HELD_BACK = "有 %d 行仍未获复核确认，**未进入本层**（待复核 ≠ 通过）"

_REASON_LABEL = {
    REASON_NAME_UNMAPPED: "指标名未登记",
    REASON_UNIT_UNMAPPED: "单位认不出（或与该指标量纲不符）",
    REASON_UNIT_ABSENT: "报告未写单位",
    REASON_VALUE_UNLOCATED: "数值未定位",
    REASON_RANGE_UNPARSED: "印了区间但读不出",
}


def _line_key(line: RawLine) -> tuple:
    return (line.source_file, line.page, line.line_no)


def _printed_range(parsed, dictionary: MeasurementDictionary) -> Optional[RefRange]:
    """报告自印区间 → `RefRange`（**开闭语义取自知识库条目**，见 `bounds_for` 的注记）。

    `printed` 为 None 表示报告声明没印——此时返回 None，交由判定层回落默认值或拒判。
    """
    if parsed.printed is None:
        return None
    low, high = parsed.printed
    return RefRange(
        low=low,
        high=high,
        bounds=dictionary.bounds_for(parsed.name),
        source=RANGE_SOURCE_REPORT,
    )


def normalize(
    lines: Sequence[RawLine],
    *,
    dictionary: MeasurementDictionary,
) -> NormalizeResult:
    """**纯函数**：行级草稿 → `NormalizeResult`。不读文件、不读时钟、不联网。

    三条纪律（口径见 `plan/03` 模块② / `data/README.md` 第五节）：

    1. **映射不上就进 `pending_mapping`**（原文 + 原因码），不猜、不静默丢弃；
    2. **单位最长优先**（在 `mapping.match_unit` 一处实现），认不出是第三态
       （`unit_unmapped`），**不落 `not_found`**；
    3. `Measurement.line_ref` **保留原始行**——溯源链（页/行/来源文件）在规范化这层
       不能断；断了之后"这个数是哪一行读出来的"就再也答不上来。
    """
    if dictionary is None:
        raise NormalizeError("规范化需要指标名字典（别名表经参数接收，模块不读文件）")

    measurements = []
    pending = []
    for line, parsed, reason in parse_lines(lines, dictionary):
        if reason is not None:
            if reason not in ALL_REASONS:
                raise NormalizeError("未知的待映射原因码：%r" % (reason,))
            pending.append(
                PendingMap(
                    line_ref=line,
                    raw_text=line.text,
                    reason=reason,
                    raw_name=parsed.raw_name,
                    raw_unit=parsed.raw_unit,
                )
            )
            continue

        unit = dictionary.canonical_unit(parsed.name)
        if unit is None:  # pragma: no cover - parse 已保证命中字典的条目才有 name
            raise NormalizeError("条目 %s 不在字典里（内部不一致）" % parsed.name)

        measurements.append(
            Measurement(
                canonical_name=parsed.name,
                raw_name=parsed.raw_name,
                value=parsed.value,
                unit=unit,
                raw_unit=parsed.raw_unit,
                ref_range_printed=_printed_range(parsed, dictionary),
                line_ref=line,
                reviewed=True,
            )
        )

    notes = []
    if measurements:
        notes.append(Note(NOTE_MAPPED, _MESSAGE_MAPPED % len(measurements)))
    if pending:
        notes.append(Note(NOTE_PENDING_MAPPING, _MESSAGE_PENDING % len(pending)))
    return NormalizeResult(measurements=measurements, pending_mapping=pending, notes=notes)


def normalize_ingest(
    result,
    *,
    dictionary: MeasurementDictionary,
) -> NormalizeResult:
    """从模块① 的产出接续（**唯一合法接续点**）。

    只取 `result.lines`（达标行 + 已复核放行行）；`result.pending_review` **一律不进**。
    这里额外做一道**防绕过**检查：若某行的键同时出现在 `lines` 与 `pending_review` 里，
    说明上游的复核门被绕过了（同一行既"可传递"又"待复核"），必须**报错**而不是照常处理
    ——否则"未复核行不得进入规范化层"这条纪律就有了第二条绕过路径。

    待复核行数**显式记入注记**（不静默丢）：用户看得到"有几行被拦在门外"。
    """
    pending_keys = {_line_key(line) for line in result.pending_review}
    leaked = [line for line in result.lines if _line_key(line) in pending_keys]
    if leaked:
        raise NormalizeError(
            "待复核行出现在可传递行里（复核门被绕过）：%s"
            % ", ".join("%s 第 %d 页第 %d 行" % _line_key(line) for line in leaked)
        )

    out = normalize(result.lines, dictionary=dictionary)
    if result.pending_review:
        out.notes.append(
            Note(NOTE_HELD_BACK, _MESSAGE_HELD_BACK % len(result.pending_review))
        )
    return out


def normalize_document(
    lines: Sequence[RawLine],
    *,
    knowledge_path=None,
    dictionary: Optional[MeasurementDictionary] = None,
) -> NormalizeResult:
    """编排入口：加载知识库（过来源门禁）后调用 `normalize`。

    `dictionary` 显式传入时**不读文件**（测试/基准注入夹具字典的路径）——
    两条路径并存，正是"纯函数与编排分离"的用处：夹具不必去改真实知识库。
    """
    if dictionary is None:
        dictionary = load_dictionary(knowledge_path)
    return normalize(lines, dictionary=dictionary)


def load_dictionary(knowledge_path=None) -> MeasurementDictionary:
    """从知识库文件加载字典（**本模块唯一的读文件路径**）。"""
    from checkup_ledger.loader import load_indicators
    from checkup_ledger.paths import indicators_path

    path = knowledge_path if knowledge_path is not None else indicators_path()
    table = load_indicators(path)
    return build_dictionary(table.entries, disabled=table.disabled)


def pending_summary(pending: Iterable[PendingMap]) -> dict:
    """待映射队列的逐原因计数（CLI 与报告用它把"哪一类没看懂"讲清楚）。"""
    counts = {}
    for item in pending:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    return counts


def reason_label(reason: str) -> str:
    """原因码的中文说明（CLI 展示用）。未知码原样返回——不静默吞掉。"""
    return _REASON_LABEL.get(reason, reason)
