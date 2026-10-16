"""低置信复核闭环：待复核队列 → 人工确认留痕 → 放行门。

为什么这层不能省：OCR 认不准时给出的是**错值**（比"漏值"危险得多——错值会被
当成事实入库并参与判定）。故纪律是：

1. `confidence < ocr_threshold` 的行**一律**进 `pending_review`（零漏）；
2. **未经复核确认的行不得进入规范化层**——由 `admit_reviewed()` 这唯一出口保证：
   它只放行"有对应 `ReviewRecord` 且确认值非空"的行；
3. 留痕**原始行 → 人工确认值**的对应关系（`ReviewRecord`），可审计：
   出了错能回答"当时看到的是什么、谁改成什么、依据是什么"；
4. 复核记录里出现待复核队列中**不存在**的行号 → **报错**（不是静默忽略）：
   对不上的留痕等于没留痕，还会掩盖"改错了行"这类真实事故。
"""

from typing import Dict, Iterable, List, Optional, Sequence

from checkup_ledger.ingest.errors import IngestError
from checkup_ledger.model import RawLine, ReviewRecord


def partition_by_confidence(lines: Sequence[RawLine], threshold: float) -> tuple:
    """按阈值切分：返回 `(accepted, pending)`。

    判据用**严格小于**：`confidence == threshold` 视为达标（阈值语义是"低于它才复核"）。
    """
    accepted: List[RawLine] = []
    pending: List[RawLine] = []
    for line in lines:
        if line.confidence < threshold:
            pending.append(line)
        else:
            accepted.append(line)
    return accepted, pending


def _line_key(line: RawLine) -> tuple:
    return (line.source_file, line.page, line.line_no)


def index_reviews(records: Iterable[ReviewRecord]) -> Dict[tuple, ReviewRecord]:
    """复核记录按行索引。**同一行出现两条记录 → 报错**（后写覆盖前写会静默丢事实）。"""
    table: Dict[tuple, ReviewRecord] = {}
    for record in records:
        key = _line_key(record.line_ref)
        if key in table:
            raise IngestError(
                "同一行出现多条复核记录：%s 第 %d 页第 %d 行" % key
            )
        table[key] = record
    return table


def admit_reviewed(
    pending: Sequence[RawLine],
    records: Iterable[ReviewRecord],
) -> List[RawLine]:
    """放行门：只有"已复核且确认值非空"的待复核行才允许进入下一层。

    三条硬规则：
    - 待复核行**没有**对应记录 → 不放行（**默认拒入**，不是默认放行）；
    - 记录有但 `confirmed_text` 为空/空白 → 不放行（"点了个确认但没改内容"不算复核）；
    - 记录指向待复核队列里**不存在**的行 → `IngestError`（留痕对不上就是没留痕）。

    返回放行后的行：文本替换为**人工确认值**，`confidence` 归 1.0
    （复核过的行其可信度由人工背书，不再由 OCR 分值决定）。
    """
    table = index_reviews(records)
    pending_keys = {_line_key(line) for line in pending}
    for key in table:
        if key not in pending_keys:
            raise IngestError(
                "复核记录指向的行不在待复核队列中：%s（留痕对不上 = 未留痕）" % (key,)
            )

    admitted: List[RawLine] = []
    for line in pending:
        record = table.get(_line_key(line))
        if record is None:
            continue
        confirmed = record.confirmed_text.strip()
        if not confirmed:
            continue
        admitted.append(
            RawLine(
                page=line.page,
                line_no=line.line_no,
                text=confirmed,
                confidence=line.confidence,
                source_file=line.source_file,
            )
        )
    return admitted


def unreviewed_keys(pending: Sequence[RawLine], records: Iterable[ReviewRecord]) -> List[tuple]:
    """仍未获确认的待复核行（供 CLI/报告显式列出，**不静默丢**）。"""
    table = index_reviews(records)
    out = []
    for line in pending:
        record = table.get(_line_key(line))
        if record is None or not record.confirmed_text.strip():
            out.append(_line_key(line))
    return out


def find_orphan_reviews(pending: Sequence[RawLine], records: Iterable[ReviewRecord]) -> List[tuple]:
    """指向待复核队列之外的复核记录（对不上的留痕）。"""
    pending_keys = {_line_key(line) for line in pending}
    return [key for key in index_reviews(records) if key not in pending_keys]


def build_review_record(line: RawLine, confirmed_text: str, reviewer_note: str = "") -> ReviewRecord:
    """构造一条复核留痕（`original_text` 由**行本身**填入，不由调用方手抄）。"""
    return ReviewRecord(
        line_ref=line,
        original_text=line.text,
        confirmed_text=confirmed_text,
        reviewer_note=reviewer_note,
    )
