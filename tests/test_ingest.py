"""模块① 输入层门禁：抽取陷阱、低置信复核闭环、缺依赖契约。

本文件的判据都落在**可指认的实物**上：用 `data/samples/ingest/` 的合成夹具
（PDF / 扫描件，字节冻结）跑真实抽取，再与真值文件比对。

四条门（缺一条就有一种假绿）：
1. **形态无关性**：正常 / 逐字定位 / 补白三种 PDF 形态经装配后得到**逐字相同**的行
   —— 形态差异不该泄漏到行文本里（伪空格与补白归一都在此处被证）；
2. **未复核不向下传递**：低置信行默认不放行；提供复核留痕后才放行（**阴性对照**）；
3. **留痕对不上要报错**：复核记录指向不存在的待复核行 → 抛错，不静默忽略；
4. **缺依赖走契约**：打桩 `builtins.__import__` 令可选依赖不可导入 →
   `MissingDependencyError`（CLI 转 exit 3），**不裸抛 `ModuleNotFoundError`**。
"""

import builtins
import json
import os
import sys

import pytest

from helpers import requires_pdf, repo_path, run_cli

from checkup_ledger.ingest import (
    IngestError,
    MissingDependencyError,
    apply_review_gate,
    build_review_record,
    ingest,
    ingest_images_result,
    ingest_pdf_document,
    ingest_pdf_text_layer,
    make_scripted_engine,
)
from checkup_ledger.ingest.lines import (
    Fragment,
    assemble_lines,
    boxes_to_fragments,
    chars_to_fragments,
)
from checkup_ledger.ingest.review import (
    admit_reviewed,
    find_orphan_reviews,
    partition_by_confidence,
    unreviewed_keys,
)
from checkup_ledger.model import IngestResult, RawLine, ReviewRecord

FIXTURES = "data/samples/ingest"
PDF_CASES = ("ingest-pdf-plain", "ingest-pdf-per-char", "ingest-pdf-padded")
SCAN_CASES = ("ingest-scan-clean", "ingest-scan-degraded")


def _fixture(rel):
    return repo_path(*(FIXTURES.split("/") + rel.split("/")))


def _truth(case_id):
    with open(_fixture("truth/%s.truth.json" % case_id), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _manifest():
    with open(_fixture("manifest.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _threshold():
    from checkup_ledger.config import load_config

    return load_config().ocr_threshold


def _scripted_scan(threshold, boxes):
    """构造一个"桩引擎 + 临时图片"的最小场景（不依赖 OCR 权重即可跑闭环）。"""
    import tempfile

    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.write(b"\x89PNG\r\n\x1a\n")  # 桩引擎不看内容，只按路径查表
    handle.close()
    engine = make_scripted_engine([(handle.name, boxes)])
    return handle.name, engine


# ============================================================ 门 1：抽取形态无关性


@pytest.mark.parametrize("case_id", PDF_CASES)
@requires_pdf
def test_pdf_fixture_matches_truth(case_id):
    """三种 PDF 形态都必须抽出与真值一致的行。"""
    lines = ingest_pdf_text_layer(_fixture("pdf/%s.pdf" % case_id))
    got = [line.text for line in lines]
    assert got == _truth(case_id)["expected_lines"], "抽取结果与真值不符：%s" % got


@requires_pdf
def test_pdf_layouts_yield_identical_lines():
    """**形态无关性**（本层最承重的断言）：三种形态的行文本必须逐字相同。

    这条证明伪空格与补白归一确实生效——若装配层对逐字定位的 PDF 掉回
    `pdfplumber.extract_text()` 的猜空格行为，`U/L` 会被拆成 `U/ L`，此处必红。
    """
    per_layout = {
        case_id: [line.text for line in ingest_pdf_text_layer(_fixture("pdf/%s.pdf" % case_id))]
        for case_id in PDF_CASES
    }
    baseline = per_layout[PDF_CASES[0]]
    for case_id, got in per_layout.items():
        assert got == baseline, "形态 %s 的行文本与基线不同：%s vs %s" % (case_id, got, baseline)


@requires_pdf
def test_pseudo_space_is_normalized():
    """伪空格专项：逐字定位 PDF 抽出的行里**不得出现** `U/ L` 这类被拆开的单位。"""
    lines = ingest_pdf_text_layer(_fixture("pdf/ingest-pdf-per-char.pdf"))
    for line in lines:
        assert "U/ L" not in line.text, "伪空格未被归一：%r" % line.text
        assert "  " not in line.text, "行内出现连续空格（未归一）：%r" % line.text


@requires_pdf
def test_text_layer_confidence_is_full():
    """PDF 文本层没有 OCR 不确定性，行置信度为满分（不是"没测"的哨兵值）。"""
    lines = ingest_pdf_text_layer(_fixture("pdf/ingest-pdf-plain.pdf"))
    assert lines, "抽取为空（探针失效）"
    for line in lines:
        assert line.confidence == 1.0, "文本层行置信度应为 1.0，实得 %r" % line.confidence


def test_pdf_fixtures_are_registered_in_manifest():
    """夹具必须逐份登记在 manifest 里（防"生成了但没登记"）。"""
    manifest = _manifest()
    registered = {case["case_id"] for case in manifest["cases"]}
    assert set(PDF_CASES) | set(SCAN_CASES) <= registered, "manifest 未登记全部夹具"
    for case in manifest["cases"]:
        assert os.path.isfile(repo_path(*(case["file"].split("/")))), "登记的文件不在位：%s" % case["file"]


# ============================================================ 门 2：未复核不向下传递


def _boxes(rows):
    """构造 OCR 框：每个字段一个框，y 按行递增。"""
    out = []
    for row_index, fields in enumerate(rows):
        for col_index, text in enumerate(fields):
            top = 20 + row_index * 30
            left = 20 + col_index * 120
            out.append(([[left, top], [left + 90, top], [left + 90, top + 24], [left, top + 24]], text, 0.99))
    return out


def test_low_confidence_lines_are_held_back_by_default():
    """低置信行默认**不放行**（默认拒入，不是默认放行）。"""
    threshold = _threshold()
    boxes = _boxes([["ALT", "43"]]) + [
        ([[20, 200], [200, 200], [200, 230], [20, 230]], "AST 28", threshold / 2.0),
    ]
    path, engine = _scripted_scan(threshold, boxes)
    try:
        result = ingest(path, ocr_threshold=threshold, engine_factory=lambda: engine)
    finally:
        os.unlink(path)

    assert len(result.lines) == 1, "低置信行被默认放行了：%s" % [line.text for line in result.lines]
    assert len(result.pending_review) == 1, "低置信行未进待复核队列"
    assert result.pending_review[0].confidence < threshold


def test_review_admits_low_confidence_line():
    """**阴性对照**：提供复核留痕后，同一行才被放行。"""
    threshold = _threshold()
    boxes = _boxes([["ALT", "43"]]) + [
        ([[20, 200], [200, 200], [200, 230], [20, 230]], "AST 28", threshold / 2.0),
    ]
    path, engine = _scripted_scan(threshold, boxes)
    try:
        first = ingest(path, ocr_threshold=threshold, engine_factory=lambda: engine)
        record = build_review_record(first.pending_review[0], "AST 28", "人工核对原单")
        second = ingest(path, ocr_threshold=threshold, engine_factory=lambda: engine, reviews=[record])
    finally:
        os.unlink(path)

    assert len(second.lines) == 2, "复核后仍未放行：%s" % [line.text for line in second.lines]
    assert not second.pending_review, "复核后仍有待复核行"


def test_empty_confirmed_text_does_not_admit():
    """"点了确认但没改内容"不算复核——空确认值一律不放行。"""
    line = RawLine(page=1, line_no=1, text="AST 28", confidence=0.2, source_file="x.png")
    record = ReviewRecord(line_ref=line, original_text="AST 28", confirmed_text="   ", reviewer_note="")
    assert admit_reviewed([line], [record]) == [], "空白确认值被放行了"


def test_review_record_carries_traceable_fields():
    """留痕必须能回答"原始行 → 人工确认值"——四个字段齐备。"""
    line = RawLine(page=2, line_no=7, text="HGB 12", confidence=0.3, source_file="scan.png")
    record = build_review_record(line, "HGB 156", "原单为 156")
    assert record.original_text == "HGB 12", "留痕未记原始行文本"
    assert record.confirmed_text == "HGB 156"
    assert record.reviewer_note == "原单为 156"
    assert record.line_ref.line_no == 7, "留痕未指向原始行"


def test_orphan_review_record_raises():
    """复核记录指向**不存在**的待复核行 → 报错（对不上的留痕等于没留痕）。"""
    pending = [RawLine(page=1, line_no=1, text="a", confidence=0.1, source_file="x.png")]
    stray = RawLine(page=8, line_no=8, text="z", confidence=0.1, source_file="x.png")
    record = ReviewRecord(line_ref=stray, original_text="z", confirmed_text="Z", reviewer_note="")
    assert find_orphan_reviews(pending, [record]), "孤儿复核记录未被识别"
    with pytest.raises(IngestError):
        admit_reviewed(pending, [record])


def test_duplicate_review_records_raise():
    """同一行两条复核记录 → 报错（后写覆盖前写会静默丢事实）。"""
    line = RawLine(page=1, line_no=1, text="a", confidence=0.1, source_file="x.png")
    records = [
        ReviewRecord(line_ref=line, original_text="a", confirmed_text="A", reviewer_note=""),
        ReviewRecord(line_ref=line, original_text="a", confirmed_text="B", reviewer_note=""),
    ]
    with pytest.raises(IngestError):
        admit_reviewed([line], records)


def test_partition_uses_strict_less_than():
    """阈值语义：`confidence == threshold` 视为达标（低于才复核）。"""
    threshold = _threshold()
    at = RawLine(page=1, line_no=1, text="a", confidence=threshold, source_file="x.png")
    below = RawLine(page=1, line_no=2, text="b", confidence=threshold - 0.01, source_file="x.png")
    accepted, pending = partition_by_confidence([at, below], threshold)
    assert accepted == [at], "恰好等于阈值的行被误判为待复核"
    assert pending == [below]


def test_unreviewed_keys_lists_everything_not_confirmed():
    """未获确认的行必须**全部**列出来（不静默丢）。"""
    threshold = _threshold()
    lines = [
        RawLine(page=1, line_no=1, text="a", confidence=0.1, source_file="x.png"),
        RawLine(page=1, line_no=2, text="b", confidence=0.1, source_file="x.png"),
    ]
    record = build_review_record(lines[0], "A")
    assert unreviewed_keys(lines, [record]) == [("x.png", 1, 2)]


def test_gate_never_admits_unreviewed_rows():
    """闭包性质：施加门之后，`lines` 里**不存在**未获确认的低置信行。"""
    threshold = _threshold()
    raw = IngestResult(
        lines=[
            RawLine(page=1, line_no=1, text="ok", confidence=1.0, source_file="x.png"),
            RawLine(page=1, line_no=2, text="low", confidence=0.1, source_file="x.png"),
        ],
        engine="ocr",
    )
    gated = apply_review_gate(raw, ocr_threshold=threshold)
    admitted_texts = {line.text for line in gated.lines}
    assert "low" not in admitted_texts, "未复核的低置信行出现在可传递行里"
    assert [line.text for line in gated.pending_review] == ["low"]


def test_module_side_gate_aligns_with_sample_side_truth():
    """**跨层语义对齐**：模块侧闭环与 M1 样例侧 `case-012` 真值的口径必须一致。

    `data/samples/truth/case-012-lowconf-review.truth.json` 是 M1 在**样例侧**铺的路：
    它把低置信行列进 `pending_review_rows`，且其 `expected`（期望落库集合）**不含**该行。
    本棒做的是**模块侧**闭环——两处若口径不一致（比如一边"未复核不落库"、另一边
    "低置信照落"），那么样例层与模块层会各自"通过"，而真实链路是错的。

    断言三件事：
    1. 该真值文件确实带 `pending_review_rows` 与"未复核不落库"标签（数据侧证据在位）；
    2. 该行的 `confidence` 低于随包阈值（与模块侧同一处定义）；
    3. 拿这个置信度喂模块侧的门 → 该行**不放行**（与真值的期望一致）。
    """
    truth_path = repo_path("data", "samples", "truth", "case-012-lowconf-review.truth.json")
    assert os.path.isfile(truth_path), "样例侧低置信真值不在位：%s" % truth_path
    with open(truth_path, "r", encoding="utf-8") as handle:
        truth = json.load(handle)

    pending_rows = truth.get("pending_review_rows")
    assert pending_rows, "case-012 真值缺 pending_review_rows（样例侧口径不在位）"
    assert "review:pending_not_stored" in truth.get("tags", []), "case-012 未声明未复核不落库语义"

    threshold = _threshold()
    for row in pending_rows:
        confidence = row["confidence"]
        assert confidence < threshold, (
            "真值里的低置信行分值 %r 不低于随包阈值 %r——两处口径已漂移" % (confidence, threshold)
        )
        # 该行的规范化名不在期望落库集合里（真值的核心断言）
        expected_names = {item["canonical_name"] for item in truth.get("expected", [])}
        assert row["canonical_name"] not in expected_names, (
            "低置信行 %r 出现在期望落库集合里（真值自相矛盾）" % row["canonical_name"]
        )

        # 模块侧同口径：该置信度喂进门 → 不放行
        line = RawLine(
            page=1, line_no=1, text="%s %s" % (row["canonical_name"], row["value"]),
            confidence=confidence, source_file="case-012.png",
        )
        gated = apply_review_gate(IngestResult(lines=[line], engine="ocr"), ocr_threshold=threshold)
        assert gated.lines == [], "模块侧放行了真值声明未复核不落库的行"
        assert len(gated.pending_review) == 1


# ============================================================ 门 3：真实扫描件夹具


def test_scan_fixtures_match_truth_when_ocr_available():
    """有 `[ocr]` 时：清晰扫描件必须抽准，降质扫描件的**每一行都低于阈值**。

    没有 `[ocr]` 时跳过（**如实跳过**，不伪造成"通过"——本机/CI 未装 extras 是常态）。
    """
    if not _has_rapidocr():
        pytest.skip("未安装 [ocr]（rapidocr-onnxruntime）；跳过真实 OCR 回归")
    from checkup_ledger.config import load_config

    threshold = load_config().ocr_threshold

    clean = ingest_images_result([_fixture("scan/ingest-scan-clean.png")])
    got = [line.text for line in clean.lines]
    assert got == _truth("ingest-scan-clean")["expected_lines"], "清晰扫描件读数与真值不符：%s" % got
    assert all(line.confidence >= threshold for line in clean.lines), "清晰扫描件有行低于阈值"

    degraded = ingest_images_result([_fixture("scan/ingest-scan-degraded.png")])
    assert degraded.lines, "降质扫描件一行都没抽出来（夹具失效）"
    assert all(line.confidence < threshold for line in degraded.lines), (
        "降质扫描件有行高于阈值：%s" % [(line.text, line.confidence) for line in degraded.lines]
    )


def _has_rapidocr():
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


# ============================================================ 门 4：缺依赖走契约


def _block_imports(monkeypatch, names):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.split(".")[0] in names:
            raise ModuleNotFoundError("No module named %r" % name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for name in names:
        sys.modules.pop(name, None)


def test_missing_pdf_dependency_raises_contract_error(monkeypatch):
    """缺 `[pdf]`：抛 `MissingDependencyError`，**不裸抛 `ModuleNotFoundError`**。

    打桩 `builtins.__import__` 即可在本机复现——无需真的卸载依赖。
    """
    _block_imports(monkeypatch, ("pdfplumber", "pdfminer"))
    with pytest.raises(MissingDependencyError) as excinfo:
        ingest_pdf_text_layer(_fixture("pdf/ingest-pdf-plain.pdf"))
    assert excinfo.value.extra == "pdf"
    assert "pip install" in str(excinfo.value)


def test_missing_ocr_dependency_raises_contract_error(monkeypatch):
    """缺 `[ocr]`：同样走契约错误。"""
    _block_imports(monkeypatch, ("rapidocr_onnxruntime",))
    with pytest.raises(MissingDependencyError) as excinfo:
        ingest_images_result([_fixture("scan/ingest-scan-clean.png")])
    assert excinfo.value.extra == "ocr"


def test_guard_covers_call_time_import_not_just_import_line():
    """**假门防线**：守卫必须包住"从 import 到调用完成"的整条路径。

    做法：让 `pdfplumber` 顶层可导入，但它的 `open()` 在调用时才抛 ImportError
    （真实缺依赖常发生在调用时：pdfplumber 在 open 里才 import pdfminer）。
    只包 import 行的实现会在这里裸抛 `ModuleNotFoundError`。
    """
    import types

    fake_module = types.ModuleType("pdfplumber")

    def fake_open(*args, **kwargs):
        raise ImportError("No module named 'pdfminer'")

    fake_module.open = fake_open
    sys.modules["pdfplumber"] = fake_module
    try:
        with pytest.raises(MissingDependencyError):
            ingest_pdf_text_layer(_fixture("pdf/ingest-pdf-plain.pdf"))
    finally:
        sys.modules.pop("pdfplumber", None)


def test_cli_ingest_exits_three_without_dependency(monkeypatch):
    """CLI 面：缺依赖 → **exit 3**（契约码，不是 1 也不是崩溃）。"""
    _block_imports(monkeypatch, ("pdfplumber", "pdfminer"))
    code, _out, err = run_cli(["ingest", _fixture("pdf/ingest-pdf-plain.pdf")])
    assert code == 3, "缺依赖未走 exit 3，实得 %d：%s" % (code, err)
    assert "缺少可选依赖" in err


@requires_pdf
def test_cli_ingest_reports_real_result():
    """CLI 面正向：有依赖时抽出真实行（不是空结果、不是伪结果）。"""
    code, out, _err = run_cli(["ingest", _fixture("pdf/ingest-pdf-per-char.pdf")])
    assert code == 0, "ingest 未成功：\n%s" % out
    assert "抽取引擎：pdf_text" in out
    assert "ALT" in out, "输出里没有真实抽取内容：\n%s" % out


def test_cli_ingest_unknown_extension_is_findings():
    """不支持的输入类型 → 检出问题（exit 1），不是用法错误也不是崩溃。"""
    import tempfile

    handle = tempfile.NamedTemporaryFile(suffix=".xyz", delete=False)
    handle.write(b"nothing")
    handle.close()
    try:
        code, _out, err = run_cli(["ingest", handle.name])
    finally:
        os.unlink(handle.name)
    assert code == 1, "未知输入类型应走检出问题（exit 1），实得 %d" % code
    assert "无法识别的输入类型" in err


def test_cli_ingest_missing_file_is_findings():
    code, _out, err = run_cli(["ingest", os.path.join(str(repo_path(".")), "no-such-file.pdf")])
    assert code == 1, "文件不存在应走检出问题（exit 1），实得 %d" % code
    assert "不存在" in err


# ============================================================ 装配单元（陷阱的底层证明）


def test_cluster_merges_split_line_fragments():
    """跨行挤断的两截按 y 邻近合回一行。

    几何：三截的垂直中心分别为 16 / 18 / 96；行高中位数 12 → 容差约 7.2。
    前两截中心差 2 ≤ 7.2 → 合回一行；第三截差 80 → 独立成行。
    x 方向留出一个词间距（约等于字符宽），故拼出来是 `ALT 43` 而不是 `ALT43`。
    """
    fragments = [
        Fragment("ALT", 72, 100, 10, 22),
        Fragment("43", 108, 124, 12, 24),   # 中心差 2（同属一行）+ 词间距
        Fragment("U/L", 72, 100, 90, 102),  # 中心差 80 → 另一行
    ]
    lines = assemble_lines(fragments, page=1, source_file="x.pdf")
    assert [line.text for line in lines] == ["ALT 43", "U/L"], "跨行聚类失败"


def test_advance_policy_uses_real_space_chars_first():
    """有真实空格字符时按它判空格（不被步进规则覆盖）。"""
    fragments = [Fragment("A", 0, 5, 0, 10), Fragment(" ", 5, 8, 0, 10), Fragment("B", 8, 13, 0, 10)]
    lines = assemble_lines(fragments, page=1, source_file="x.pdf")
    assert lines[0].text == "A B"


def test_ocr_policy_joins_boxes_with_single_space():
    """OCR 列框策略：每个框是一个词，框间一律单空格（不按步进猜）。"""
    boxes = [
        ([[10, 10], [30, 10], [30, 20], [10, 20]], "ALT", 0.9),
        ([[60, 10], [90, 10], [90, 20], [60, 20]], "43", 0.9),
    ]
    lines = assemble_lines(boxes_to_fragments(boxes), page=1, source_file="x.png", space_policy="always")
    assert lines[0].text == "ALT 43"


def test_line_confidence_takes_weakest_fragment():
    """行的置信度取该行**最弱**碎片（一行里有一截没认准，整行都该复核）。"""
    boxes = [
        ([[10, 10], [30, 10], [30, 20], [10, 20]], "ALT", 0.99),
        ([[60, 10], [90, 10], [90, 20], [60, 20]], "43", 0.31),
    ]
    lines = assemble_lines(boxes_to_fragments(boxes), page=1, source_file="x.png", space_policy="always")
    assert lines[0].confidence == pytest.approx(0.31)


def test_unknown_space_policy_raises():
    with pytest.raises(ValueError):
        assemble_lines([Fragment("a", 0, 1, 0, 1)], page=1, source_file="x", space_policy="nope")


def test_chars_to_fragments_keeps_whitespace():
    """空白字符是真实空格的证据，装配前不得丢掉。"""
    chars = [
        {"text": "A", "x0": 0, "x1": 5, "top": 0, "bottom": 10},
        {"text": " ", "x0": 5, "x1": 8, "top": 0, "bottom": 10},
        {"text": "B", "x0": 8, "x1": 13, "top": 0, "bottom": 10},
    ]
    fragments = chars_to_fragments(chars)
    assert [fragment.text for fragment in fragments] == ["A", " ", "B"]


@requires_pdf
def test_pdf_document_reports_notes_for_imageless_page():
    """没有文本层的页必须**说出来**（不静默当空页）。

    用夹具写出器造一份"整页无文本"的 PDF（空内容流），断言产出 `page_no_text_layer` 注记。
    """
    import tempfile

    from fixtures import pdfwrite

    payload = pdfwrite.build_pdf([[]])
    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    handle.write(payload)
    handle.close()
    try:
        result = ingest_pdf_document(handle.name)
    finally:
        os.unlink(handle.name)

    assert result.lines == [], "无文本层页不应产出任何行"
    codes = [note.code for note in result.notes]
    assert "page_no_text_layer" in codes, "无文本层页未给出注记：%s" % codes

