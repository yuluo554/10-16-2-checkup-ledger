"""PDF 文本层直读（依赖可选 extras `[pdf]` = pdfplumber）。

为什么不用 `page.extract_text()` 了事：实测（见 plan/00 的 M2 实测证据节）显示
逐字定位导出的 PDF 上，pdfplumber 原生文本抽取会把 `U/L` 拆成 `U/ L`——它按
字符间距猜空格，而逐字定位的字距没有真实空白字符可依。故本模块**不用它的文本**，
改用**字符坐标**自行装配（`lines.assemble_lines`），陷阱处理集中在那一处。

缺依赖走 `exit 3` 契约：`run_guarded` 包住**从 import 到调用完成**的整条路径——
pdfplumber 在 `open()` 内部才 import pdfminer，只包 import 行是假门。
"""

import os
from typing import List

from checkup_ledger.ingest.deps import run_guarded
from checkup_ledger.ingest.errors import IngestError
from checkup_ledger.ingest.lines import SPACE_POLICY_ADVANCE, assemble_lines, chars_to_fragments
from checkup_ledger.model import Note, RawLine

ENGINE_PDF_TEXT = "pdf_text"
PDF_EXTENSIONS = (".pdf",)

NOTE_PAGE_NO_TEXT = "page_no_text_layer"
NOTE_CHARS_SKIPPED = "chars_skipped"
NOTE_MULTI_LINE_CLUSTER = "cluster_merged"

# 中文路径与 CRLF 都是实测坑：路径统一经 os.fspath + abspath（不手拼字符串），
# 文本层内容一律按 LF 归一后再进入装配（PDF 抽取常带回车）。
_MESSAGE_PAGE_NO_TEXT = "第 %d 页没有可抽取的文本层（可能是扫描件，需走 OCR 兜底）"
_MESSAGE_CHARS_SKIPPED = "第 %d 页有 %d 个字符缺少坐标被跳过（不影响其余行）"
_MESSAGE_CLUSTER_MERGED = "第 %d 页有 %d 处相邻碎片被合并成同一行（跨行挤断）"


def ingest_pdf_text_layer(path) -> List[RawLine]:
    """读 PDF 文本层 → `RawLine[]`。文件不可读/格式错 → `IngestError`。

    **不抛 ImportError**：缺 `[pdf]` 时抛 `MissingDependencyError`（CLI 转 exit 3）。
    """
    target = os.path.abspath(os.fspath(path))
    if not os.path.isfile(target):
        raise IngestError("输入文件不存在：%s" % target)
    if os.path.splitext(target)[1].lower() not in PDF_EXTENSIONS:
        raise IngestError("不是 PDF 文件（本函数只读文本层）：%s" % target)

    result = _ingest_pdf_guarded(target)
    return result.lines


def ingest_pdf_document(path) -> "object":
    """读 PDF 并返回 `IngestResult`（含页面注记）。CLI 用这个，好把"没看到"说出来。"""
    target = os.path.abspath(os.fspath(path))
    if not os.path.isfile(target):
        raise IngestError("输入文件不存在：%s" % target)
    return _ingest_pdf_guarded(target)


def _ingest_pdf_guarded(target: str):
    """整条读取路径包在缺依赖守卫里（import + open + 逐页抽取，一处不漏）。"""
    from checkup_ledger.model import IngestResult

    def _read():
        import pdfplumber  # 真实 import 在守卫内

        lines: List[RawLine] = []
        notes: List[Note] = []
        display = os.path.basename(target)

        with pdfplumber.open(target) as document:
            for page_index, page in enumerate(document.pages):
                chars = _extract_chars(page)
                if not chars:
                    notes.append(Note(NOTE_PAGE_NO_TEXT, _MESSAGE_PAGE_NO_TEXT % (page_index + 1)))
                    continue
                fragments = chars_to_fragments(chars)
                page_lines = assemble_lines(
                    fragments,
                    page=page_index + 1,
                    source_file=display,
                    space_policy=SPACE_POLICY_ADVANCE,
                )
                lines.extend(page_lines)
                if len(fragments) != len(chars):
                    notes.append(
                        Note(
                            NOTE_CHARS_SKIPPED,
                            _MESSAGE_CHARS_SKIPPED % (page_index + 1, len(chars) - len(fragments)),
                        )
                    )

        return IngestResult(lines=lines, engine=ENGINE_PDF_TEXT, notes=notes)

    return run_guarded("pdfplumber", "pdf", "PDF 文本层直读", _read)


def _extract_chars(page) -> List[dict]:
    """取该页字符（带坐标）。缺坐标的字符记入注记（不静默丢）。"""
    return list(page.chars)
