"""扫描件 OCR 兜底（依赖可选 extras `[ocr]` = rapidocr-onnxruntime）。

ONNX Runtime CPU 本地推理，**零联网**（模型权重随 wheel 分发，不下载）。
缺依赖走 `exit 3` 契约，且 `run_guarded` 包住**从 import 到引擎构造完成**的整条路径
——RapidOCR 在**构造**时才 import onnxruntime，只包 import 行是假门。

引擎可注入（`engine_factory`）：回归测试用**确定性桩引擎**，这样
"低置信 → 待复核 → 复核放行"的闭环在本机没有 OCR 权重时也能真跑。
"""

import os
from typing import Callable, List, Optional, Sequence

from checkup_ledger.ingest.deps import run_guarded
from checkup_ledger.ingest.errors import IngestError
from checkup_ledger.ingest.lines import SPACE_POLICY_ALWAYS, assemble_lines, boxes_to_fragments
from checkup_ledger.model import Note, RawLine

ENGINE_OCR = "ocr"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")

NOTE_IMAGE_NO_TEXT = "image_no_text"
_MESSAGE_IMAGE_NO_TEXT = "%s 未识别出任何文本（空白图/极端模糊，或引擎未就绪）"


def ingest_images(paths, *, engine_factory: Optional[Callable] = None) -> List[RawLine]:
    """扫描件 → `RawLine[]`。缺 `[ocr]` 时抛 `MissingDependencyError`（CLI 转 exit 3）。"""
    return ingest_images_result(paths, engine_factory=engine_factory).lines


def ingest_images_result(paths, *, engine_factory: Optional[Callable] = None):
    """同 `ingest_images`，但返回 `IngestResult`（带逐图注记）。"""
    from checkup_ledger.model import IngestResult

    targets = _normalize_paths(paths)

    def _run():
        engine = _build_engine(engine_factory)
        lines: List[RawLine] = []
        notes: List[Note] = []

        for image_index, target in enumerate(targets):
            display = os.path.basename(target)
            boxes = _run_engine(engine, target)
            if not boxes:
                notes.append(Note(NOTE_IMAGE_NO_TEXT, _MESSAGE_IMAGE_NO_TEXT % display))
                continue
            fragments = boxes_to_fragments(boxes)
            page_lines = assemble_lines(
                fragments,
                page=image_index + 1,
                source_file=display,
                space_policy=SPACE_POLICY_ALWAYS,
            )
            lines.extend(page_lines)

        return IngestResult(lines=lines, engine=ENGINE_OCR, notes=notes)

    return run_guarded("rapidocr_onnxruntime", "ocr", "扫描件 OCR 兜底", _run)


def _normalize_paths(paths) -> List[str]:
    if isinstance(paths, (str, bytes)) or hasattr(paths, "__fspath__"):
        candidates = [paths]
    else:
        candidates = list(paths)
    if not candidates:
        raise IngestError("未提供任何扫描件路径")

    targets = []
    for item in candidates:
        target = os.path.abspath(os.fspath(item))
        if not os.path.isfile(target):
            raise IngestError("输入图片不存在：%s" % target)
        if os.path.splitext(target)[1].lower() not in IMAGE_EXTENSIONS:
            raise IngestError("不是支持的图片格式（%s）：%s" % (", ".join(IMAGE_EXTENSIONS), target))
        targets.append(target)
    return targets


def _build_engine(engine_factory: Optional[Callable]):
    if engine_factory is not None:
        return engine_factory()

    def _make():
        from rapidocr_onnxruntime import RapidOCR  # 构造在守卫内

        return RapidOCR()

    return run_guarded("rapidocr_onnxruntime", "ocr", "RapidOCR 引擎构造", _make)


def _run_engine(engine, target: str) -> List[tuple]:
    """调用引擎并归一化输出。

    RapidOCR 的输出形态随版本有 `(result, elapse)` 与直接 `result` 两种，
    故按"元组且首元素为列表"判形态，**不假设**某一版。
    """
    raw = engine(target)
    if isinstance(raw, tuple) and raw and isinstance(raw[0], (list, type(None))):
        raw = raw[0]
    if not raw:
        return []
    out = []
    for item in raw:
        box, text, score = item[0], item[1], item[2]
        if not str(text).strip():
            continue
        out.append((box, str(text), float(score)))
    return out


def make_scripted_engine(scripted: Sequence[tuple]) -> Callable:
    """构造**确定性桩引擎**：给定图片路径 → 预置的 (box, text, score) 列表。

    用途：没有 OCR 权重时也能真跑复核闭环；也让"低置信行"可精确构造
    （不用靠把图故意糊掉来碰运气——那种做法在 CI 上会随机红）。
    """
    table = {os.path.abspath(os.fspath(key)): list(value) for key, value in scripted}

    def _engine(path):
        target = os.path.abspath(os.fspath(path))
        if target not in table:
            raise IngestError("桩引擎未登记该图片：%s" % target)
        return table[target], None

    return _engine
