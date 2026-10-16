"""模块① 输入层：PDF / 扫描件 → 行级草稿 + 低置信复核闭环。

职责边界（plan/03 模块①）：**只做抽取，不做任何数值语义判断**。本层输出
`RawLine[]` 与 `pending_review` 队列，规范化层（模块②）只接收**已复核放行**的行。

对外三个入口：
- `ingest_pdf_text_layer(path)` / `ingest_images(paths)`：单通道抽取；
- `ingest(path, ...)`：按扩展名分派 + 低置信切分 + 复核放行，返回 `IngestResult`。

`ocr_threshold` **没有代码默认值**：必须显式传入或由配置提供（`config.load_config`）。
缺配置即报错——静默取 0.8 之类的字面值会让"阈值单点定义"失效。
"""

import os
from typing import Callable, Iterable, Optional, Sequence

from checkup_ledger.ingest import deps, lines as lines_module, ocr, pdf, review
from checkup_ledger.ingest.deps import MissingDependencyError
from checkup_ledger.ingest.errors import IngestError
from checkup_ledger.ingest.ocr import ingest_images, ingest_images_result, make_scripted_engine
from checkup_ledger.ingest.pdf import ingest_pdf_document, ingest_pdf_text_layer
from checkup_ledger.ingest.review import (
    admit_reviewed,
    build_review_record,
    find_orphan_reviews,
    partition_by_confidence,
    unreviewed_keys,
)
from checkup_ledger.model import IngestResult, Note, RawLine, ReviewRecord

ENGINE_PDF_TEXT = pdf.ENGINE_PDF_TEXT
ENGINE_OCR = ocr.ENGINE_OCR

NOTE_PENDING_REVIEW = "pending_review"
NOTE_REVIEW_ORPHAN = "review_orphan"
NOTE_REVIEW_ADMITTED = "review_admitted"
NOTE_REVIEW_STILL_PENDING = "review_still_pending"

_MESSAGE_PENDING = "有 %d 行置信度低于阈值 %g，已进入待复核队列（未复核不向下传递）"
_MESSAGE_ADMITTED = "已放行 %d 行（人工复核确认，其可信度由人工背书）"
_MESSAGE_STILL_PENDING = "仍有 %d 行未获复核确认，**不向下传递**（待复核≠通过）"
_MESSAGE_ORPHAN = "有 %d 条复核记录指向不存在的待复核行（留痕对不上）"


def is_pdf(path) -> bool:
    return os.path.splitext(os.fspath(path))[1].lower() in pdf.PDF_EXTENSIONS


def is_image(path) -> bool:
    return os.path.splitext(os.fspath(path))[1].lower() in ocr.IMAGE_EXTENSIONS


def ingest(
    path,
    *,
    ocr_threshold: float,
    reviews: Optional[Iterable[ReviewRecord]] = None,
    engine_factory: Optional[Callable] = None,
) -> IngestResult:
    """抽取 + 低置信切分 + 复核放行（**唯一编排入口**）。

    返回的 `lines` **只含可向下传递的行**（达标行 + 已复核放行行）；
    `pending_review` 是仍未获确认的行，**显式列出、不静默丢**。

    `reviews` 提供人工复核留痕；未提供的待复核行一律不放行（默认拒入）。
    """
    target = os.fspath(path)
    if is_pdf(target):
        raw = pdf.ingest_pdf_document(target)
    elif is_image(target):
        raw = ocr.ingest_images_result(target, engine_factory=engine_factory)
    else:
        raise IngestError(
            "无法识别的输入类型（%s）：支持 PDF 文本层与常见图片格式"
            % os.path.splitext(target)[1]
        )

    return apply_review_gate(raw, ocr_threshold=ocr_threshold, reviews=reviews)


def apply_review_gate(
    raw: IngestResult,
    *,
    ocr_threshold: float,
    reviews: Optional[Iterable[ReviewRecord]] = None,
) -> IngestResult:
    """对已抽取结果施加低置信复核门（**闭环的唯一实现处**）。

    分离出来是为了让 `ingest_images` 的桩引擎路径与真实 OCR 路径共用同一套门
    ——两套门 = 同一口径两份实现，改一处漏一处。
    """
    accepted, pending = review.partition_by_confidence(raw.lines, ocr_threshold)
    records = list(reviews or [])

    orphans = review.find_orphan_reviews(pending, records)
    if orphans:
        raise IngestError(
            "复核记录指向不存在的待复核行：%s" % ", ".join(_format_key(key) for key in orphans)
        )

    admitted = review.admit_reviewed(pending, records)
    still_pending = [line for line in pending if _key(line) not in {_key(item) for item in admitted}]

    notes = list(raw.notes)
    if pending:
        notes.append(Note(NOTE_PENDING_REVIEW, _MESSAGE_PENDING % (len(pending), ocr_threshold)))
    if admitted:
        notes.append(Note(NOTE_REVIEW_ADMITTED, _MESSAGE_ADMITTED % len(admitted)))
    if still_pending:
        notes.append(Note(NOTE_REVIEW_STILL_PENDING, _MESSAGE_STILL_PENDING % len(still_pending)))

    return IngestResult(
        lines=accepted + admitted,
        engine=raw.engine,
        pending_review=still_pending,
        notes=notes,
    )


def _key(line: RawLine) -> tuple:
    return (line.source_file, line.page, line.line_no)


def _format_key(key) -> str:
    return "%s 第 %d 页第 %d 行" % key
