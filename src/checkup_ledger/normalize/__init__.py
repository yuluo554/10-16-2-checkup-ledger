"""模块② 规范化层：报告行 → `Measurement`（指标名映射 + 单位归一 + 数值抽取）。

职责边界（plan/03 模块②）：把**已复核放行的行**变成结构化记录。
- 指标名原文 → `canonical_name`（别名表只在知识库 YAML 一处定义，经参数传入）；
- 单位归一（**最长优先**匹配；认不出 → `pending` + 原因码 `unit_unmapped`）；
- 无法映射 → `pending_mapping`（原文 + 原因码），**不猜、不静默丢弃**。

分层纪律（静态门禁守）：
- `mapping.py` / `parse.py` 是**纯函数**模块：不 import 文件 I/O、不读时钟、不联网；
  别名表与单位表由调用方加载后传入。
- 本层**不做判定**：不 import 判定内核、不产出 `FLAG_*`（那是模块③ 的职责）。

对外三个入口：
- `normalize(lines, *, dictionary)`：纯函数，不读文件（别名/单位表经参数接收）；
- `normalize_ingest(result, *, dictionary)`：从模块① 的产出接续（**只取已复核放行行**）；
- `normalize_document(lines, *, knowledge_path=None)`：编排入口，加载知识库后调用
  `normalize`（**唯一读文件处**，与模块① 的 `ingest` 同形态）。
"""

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
from checkup_ledger.normalize.parse import (
    ParsedLine,
    parse_line,
    parse_lines,
    parse_range_column,
    split_columns,
    strip_annotations,
)
from checkup_ledger.normalize.pipeline import (
    load_dictionary,
    normalize,
    normalize_document,
    normalize_ingest,
    pending_summary,
    reason_label,
)

__all__ = [
    "ALL_REASONS",
    "MeasurementDictionary",
    "NormalizeError",
    "ParsedLine",
    "REASON_NAME_UNMAPPED",
    "REASON_RANGE_UNPARSED",
    "REASON_UNIT_ABSENT",
    "REASON_UNIT_UNMAPPED",
    "REASON_VALUE_UNLOCATED",
    "build_dictionary",
    "load_dictionary",
    "normalize",
    "normalize_document",
    "normalize_ingest",
    "parse_line",
    "parse_lines",
    "parse_range_column",
    "pending_summary",
    "reason_label",
    "split_columns",
    "strip_annotations",
]
