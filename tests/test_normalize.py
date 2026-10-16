"""模块② 规范化层门禁：指标名映射、单位最长优先、待人工映射第三态、端到端贯通。

本文件的判据都落在**可指认的实物**上：用 `data/samples/ingest/` 的合成夹具
（PDF，字节冻结）跑真实抽取，再走规范化与判定，与真值比对。

五条门（缺一条就有一种假绿）：

1. **指标名异名映射**：`谷丙转氨酶`/`ALT`/`GPT` 映射到同一 `canonical_name`；
2. **单位最长优先**：`mg` 不被更短的 `g` 吃掉（值会静默放大一千倍）；
3. **单位未识别是第三态**：认不出的单位进 `pending(unit_unmapped)`，**不落 `not_found`**
   （"写了但认不出"与"根本没写"是两件事）；
4. **未映射不猜不丢**：故意写错指标名 → 进 `pending_mapping`，不进 `measurements`；
5. **端到端贯通**：ingest → normalize → judge，`range_source` 在产物里显式可见，
   `Measurement.line_ref` 保留溯源（页/行/来源文件）。

**区间夹具一律从知识库取**：本文件构造报告行时，区间列文本由 `helpers.yaml_bounds`
实算——测试里手写区间数值会让测试成为"区间数值的第二处定义"（零字面量门禁扫
`tests/` 全文，含 docstring，正是为了拦这个）。
"""

import json
import os

import pytest

from helpers import repo_path, run_cli, step_of, yaml_bounds

from checkup_ledger.engine.compare import judge_all
from checkup_ledger.model import (
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_NOT_ASSESSED,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
    IngestResult,
    RawLine,
    RefRange,
)
from checkup_ledger.normalize import (
    REASON_NAME_UNMAPPED,
    REASON_RANGE_UNPARSED,
    REASON_UNIT_ABSENT,
    REASON_UNIT_UNMAPPED,
    REASON_VALUE_UNLOCATED,
    NormalizeError,
    build_dictionary,
    load_dictionary,
    normalize,
    normalize_ingest,
    parse_line,
    pending_summary,
    reason_label,
)
from checkup_ledger.normalize.parse import parse_range_column, split_columns, strip_annotations

FIXTURES = "data/samples/ingest"
PDF_CASES = ("ingest-pdf-plain", "ingest-pdf-per-char", "ingest-pdf-padded")


def _fixture(rel):
    return repo_path(*(FIXTURES.split("/") + rel.split("/")))


def _truth(case_id):
    with open(_fixture("truth/%s.truth.json" % case_id), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _line(text, page=1, line_no=1, source_file="t.txt"):
    return RawLine(page=page, line_no=line_no, text=text, confidence=1.0, source_file=source_file)


# ---------------------------------------------------------------- 行夹具（区间文本从 YAML 实算）


def _num(value):
    """数值的展示写法。非数值字符串**原样透传**——夹具要用它构造"读不出"的形态。"""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else repr(number)


def _range_text(name):
    """该指标知识库区间的**报告写法**（`下限~上限`）。"""
    spec = yaml_bounds(name)
    return "%s~%s" % (_num(spec["low"]), _num(spec["high"]))


def _value_in(name):
    """区间内的一个确定值（取端点中点；端点全缺时抛错——夹具不许瞎编）。"""
    spec = yaml_bounds(name)
    low, high = spec["low"], spec["high"]
    assert low is not None and high is not None, "该指标区间不完整，无法取区间内取值：%s" % name
    return (low + high) / 2.0


def _value_above(name):
    """略高于上限的值（用端点 + 该端点的步长实算，不写死小数）。"""
    high = yaml_bounds(name)["high"]
    assert high is not None, "该指标无上限：%s" % name
    return high + step_of(high)


def _report_line(name, *, unit=None, value=None, range_text=None, suffix=""):
    """构造一行报告文本：`<项目名> <数值> <单位> <区间列><后缀>`。

    `range_text` 缺省取该指标的 YAML 区间；要测"未印/单侧/读不出"时显式传入。
    """
    spec = yaml_bounds(name)
    unit = unit if unit is not None else spec["unit"]
    value = _value_in(name) if value is None else value
    range_text = _range_text(name) if range_text is None else range_text
    return "%s %s %s %s%s" % (name, _num(value), unit, range_text, suffix)


class _StubEntry:
    """构造字典条目（鸭子类型）。

    `unit` 为 None 时区间/单位从知识库取；显式给 `unit` 时**必须同时给 low/high**
    （那是在测"单位表"这类与区间无关的行为，不该借用真实条目的区间）。
    """

    def __init__(self, name, unit=None, aliases=(), unit_aliases=(), standard="WS/T 404.1-2012",
                 bounds="closed", sex="any", low=None, high=None):
        if unit is None:
            spec = yaml_bounds(name)
            self.unit = spec["unit"]
            low, high = spec["low"], spec["high"]
        else:
            self.unit = unit
        self.canonical_name = name
        self.display_name = name
        self.aliases = list(aliases)
        self.unit_aliases = list(unit_aliases)
        self.default_range = RefRange(low=low, high=high, bounds=bounds)
        self.source_standard = standard
        self.status = "pending"
        self.evidence = ""
        self.applies_to_sex = sex


# ============================================================ 门 1：指标名异名映射


def test_aliases_map_to_same_canonical_name():
    """`谷丙转氨酶` / `ALT` / `GPT` / 全名 必须映射到**同一个** `canonical_name`。

    这条是"报告实测词逐一登记"的用处：真实报告上同一个项目的写法五花八门，
    若只认缩写，中文全称的报告就会整行进待人工映射。
    """
    dictionary = load_dictionary()
    names = ["谷丙转氨酶", "ALT", "GPT", "丙氨酸氨基转移酶"]
    canonical = {dictionary.match_name(split_columns(n))[0] for n in names}
    assert canonical == {"ALT"}, "异名未映射到同一 canonical_name：%s" % canonical


def test_alias_index_is_built_from_entries_not_a_second_table():
    """别名索引必须由**传入的条目**构建——本层不另建第二份别名表。

    判据：用一个只含单条目的字典，其别名索引里就只有那一条的别名；
    若模块内部藏了第二份硬编码表，这条会红（它会带来别的指标名）。
    """
    dictionary = build_dictionary([_StubEntry("ALT", aliases=["谷丙转氨酶"], unit_aliases=["IU/L"])])
    index = dictionary.alias_index
    assert set(index) == {"ALT", "谷丙转氨酶"}, "别名索引含未登记的键：%s" % sorted(index)
    assert all(value == "ALT" for value in index.values())


def test_alias_conflict_between_two_indicators_raises():
    """同一别名指向两个不同指标 → **报错**（静默取一会让判定跟着随机）。"""
    entries = [
        _StubEntry("ALT", aliases=["共同名"]),
        _StubEntry("AST", aliases=["共同名"]),
    ]
    with pytest.raises(NormalizeError) as excinfo:
        build_dictionary(entries)
    assert "别名冲突" in str(excinfo.value)


def test_entry_without_source_is_rejected_by_dictionary_gate():
    """第二层来源门禁：缺 `source.standard` 的条目**拒绝进字典**。

    loader 已挡一道；这道挡的是"绕过 loader 自行拼条目"的路径——否则
    "未挂来源核对的条目不得生效"就有了第二条绕过路径。
    """
    with pytest.raises(NormalizeError) as excinfo:
        build_dictionary([_StubEntry("ALT", standard="")])
    assert "source.standard" in str(excinfo.value)


# ============================================================ 门 2：单位最长优先


def test_unit_longest_match_beats_shorter_prefix():
    """**最长优先**：同前缀家族里取最长命中。

    这是**静默数值放大**的经典来源：报告写"毫克"，若先匹配到更短的"克"别名，
    值就从毫克被读成克——值看着没变，语义已错，且没有任何提示。
    """
    entry = _StubEntry("XXX", unit="mmol/L", unit_aliases=["mmol/L", "mM", "m", "mol/L"])
    dictionary = build_dictionary([entry])
    match = dictionary.match_unit("mmol/L")
    assert match.unit == "mmol/L", "长别名未胜出：命中 %r" % match.matched_alias
    assert match.matched_alias == "mmol/L"

    # 反向：短别名单独出现时仍应匹配到它（门没有被收紧成"只认最长表项"）
    assert dictionary.match_unit("m").unit == "mmol/L"


def test_unit_prefix_match_does_not_swallow_shorter_alias_inside_longer_unit():
    """`mg` 里的 `g` **不得**被当成命中——前缀匹配而非包含匹配。

    场景：字典里有"克"（`g`）这个单位，报告写"毫克"（`mg`）。包含式匹配会
    在 `mg` 里找到 `g`，把毫克读成克——值静默放大一千倍且毫无提示。
    """
    entry = _StubEntry("XXX", unit="g", unit_aliases=["g", "G"])
    dictionary = build_dictionary([entry])
    assert dictionary.match_unit("mg").unit is None, (
        "更短的单位别名在更长单位内部被当成了命中（包含式匹配）——值会被静默放大"
    )
    assert dictionary.match_unit("g").unit == "g"


def test_unit_longest_wins_inside_same_prefix_family():
    """同一前缀家族里取最长：`m` 与 `mg` 同时登记时，按原文取最长命中。"""
    entry = _StubEntry("XXX", unit="mg", unit_aliases=["mg", "m"])
    dictionary = build_dictionary([entry])
    assert dictionary.match_unit("mg").matched_alias == "mg", "`mg` 被短别名 `m` 吃掉"
    assert dictionary.match_unit("m").matched_alias == "m"


def test_glued_value_and_unit_is_split_not_misreported():
    """"数值+单位粘住"的写法（形如 `<数值><单位>`）：**数值可用、单位认不出**。

    不能报成"数值未定位"——误报原因码会让人工按"数值没读到"去找，方向就错了。
    """
    dictionary = load_dictionary()
    parsed, reason = parse_line(_line("ALT 2oz"), dictionary)
    assert reason == REASON_UNIT_UNMAPPED, "粘住写法被误报成 %r" % reason
    assert parsed.value == 2.0, "粘住写法里数值未被抽出"
    assert parsed.raw_unit == "oz", "粘住的单位原文未留痕"


def test_unit_that_belongs_to_another_indicator_is_not_used():
    """**认得出但张冠李戴**：ALT 配血脂/血糖量纲的单位 → 不照此判定。

    单位表是全局的（`mmol/L` 被血脂与血糖共享），故"认得这个单位"不等于
    "它属于这个指标"。张冠李戴与"认不出"同属"不能照此判定"。
    """
    dictionary = load_dictionary()
    other_unit = yaml_bounds("GLU")["unit"]  # 血糖量纲的单位，与 ALT 不同
    assert other_unit != yaml_bounds("ALT")["unit"], "夹具前提已变：两者单位相同"
    parsed, reason = parse_line(_line(_report_line("ALT", unit=other_unit)), dictionary)
    assert reason == REASON_UNIT_UNMAPPED, "张冠李戴的单位被照常使用（原因码 %r）" % reason


# ============================================================ 门 3：单位第三态


def test_unmapped_unit_is_pending_not_missing():
    """认不出的单位 → `pending(unit_unmapped)`，**不是**"根本没写"。

    口径（`data/README.md` 第五节）："写了但单位不认识"与"根本没写"是两件事。
    两者都要人工处理，但处置方向不同（扩单位表 vs 核对报告排版）。
    """
    dictionary = load_dictionary()
    parsed, reason = parse_line(_line(_report_line("ALT", unit="oz")), dictionary)
    assert reason == REASON_UNIT_UNMAPPED
    assert parsed.raw_unit == "oz", "单位原文未留痕（人工核对时看不到写了什么）"

    absent, absent_reason = parse_line(_line(_report_line("ALT", unit="")), dictionary)
    assert absent_reason == REASON_UNIT_ABSENT, "没写单位被误报成 %r" % absent_reason
    assert absent.raw_unit == ""


def test_unit_variant_normalizes_to_canonical():
    """同量纲的单位变体归一（口径：首期只做同量纲归一，跨量纲换算不做）。"""
    dictionary = load_dictionary()
    variant = _unit_variant_of("ALT")
    parsed, reason = parse_line(_line(_report_line("ALT", unit=variant)), dictionary)
    assert reason is None, "同量纲变体未归一：%s" % reason
    assert parsed.raw_unit == variant, "单位原文未保留（溯源需要它）"
    assert parsed.name == "ALT"


def _unit_variant_of(canonical_name):
    """从知识库取该指标的一个**非 canonical 写法**的单位别名（不手写单位串）。"""
    from checkup_ledger.loader import load_indicators
    from checkup_ledger.paths import indicators_path

    table = load_indicators(indicators_path())
    for entry in table.entries:
        if entry.canonical_name == canonical_name:
            for alias in entry.unit_aliases:
                if alias != entry.unit:
                    return alias
    raise AssertionError("知识库条目 %s 没有可用的单位变体" % canonical_name)


# ============================================================ 门 4：未映射不猜不丢


def test_unknown_indicator_name_goes_to_pending_not_measurements():
    """故意写错指标名 → 进 `pending_mapping`，**不进** `measurements`（不猜不丢）。"""
    dictionary = load_dictionary()
    text = _report_line("ALT").replace("ALT", "XXX", 1)
    result = normalize([_line(text)], dictionary=dictionary)
    assert result.measurements == [], "未登记的指标名被照常映射"
    assert len(result.pending_mapping) == 1
    item = result.pending_mapping[0]
    assert item.reason == REASON_NAME_UNMAPPED
    assert item.raw_text == text, "待映射队列未留原文（人工看不到原始行）"
    assert item.line_ref.text == text, "溯源链在规范化这层断了"


def test_pending_mapping_never_silently_drops_rows():
    """**不静默丢**：输入行数 == 已映射 + 待映射（每行都有去向）。"""
    dictionary = load_dictionary()
    lines = [
        _line(_report_line("ALT"), line_no=1),
        _line(_report_line("ALT").replace("ALT", "XXX", 1), line_no=2),
        _line(_report_line("ALT", value="abc"), line_no=3),
        _line(_report_line("ALT", unit="oz"), line_no=4),
        _line(_report_line("ALT", range_text="%s~abc" % _num(yaml_bounds("ALT")["low"])), line_no=5),
    ]
    result = normalize(lines, dictionary=dictionary)
    assert len(result.measurements) + len(result.pending_mapping) == len(lines), (
        "有行被静默丢弃：映射 %d + 待映射 %d != 输入 %d"
        % (len(result.measurements), len(result.pending_mapping), len(lines))
    )
    assert len(result.measurements) == 1
    assert {item.reason for item in result.pending_mapping} == {
        REASON_NAME_UNMAPPED, REASON_VALUE_UNLOCATED, REASON_UNIT_UNMAPPED, REASON_RANGE_UNPARSED,
    }


def test_unparsable_printed_range_is_not_silently_read_as_not_printed():
    """**印了但读不出 ≠ 没印**：区间一侧写了非数字 → `range_unparsed`。

    把读错当"没印"，判定会从"有区间"变成"拒判"——一条真实的读错被伪装成
    一条干净的拒判（用户看到"拒判"会以为报告没印区间，于是不去核对）。
    """
    dictionary = load_dictionary()
    low = _num(yaml_bounds("ALT")["low"])
    bad = _line(_report_line("ALT", range_text="%s~abc" % low))
    parsed, reason = parse_line(bad, dictionary)
    assert reason == REASON_RANGE_UNPARSED, "读不出的区间被静默当成 %r" % reason

    # 阴性对照：真·未印 → 无 reason，printed 为 None
    ok, ok_reason = parse_line(_line(_report_line("ALT", range_text="（未印）")), dictionary)
    assert ok_reason is None
    assert ok.printed is None


def test_pending_summary_counts_by_reason():
    """待映射队列的逐原因计数（把"哪一类没看懂"讲清楚）。"""
    dictionary = load_dictionary()
    lines = [
        _line(_report_line("ALT").replace("ALT", "XXX", 1), line_no=1),
        _line(_report_line("AST").replace("AST", "YYY", 1), line_no=2),
        _line(_report_line("ALT", unit="oz"), line_no=3),
    ]
    result = normalize(lines, dictionary=dictionary)
    summary = pending_summary(result.pending_mapping)
    assert summary[REASON_NAME_UNMAPPED] == 2
    assert summary[REASON_UNIT_UNMAPPED] == 1


def test_reason_labels_are_human_readable_and_never_silently_dropped():
    """每个原因码都要有人话说明；未知码**原样返回**（不静默吞掉）。"""
    from checkup_ledger.normalize import ALL_REASONS

    for reason in ALL_REASONS:
        assert reason_label(reason) != reason, "原因码 %s 没有中文说明" % reason
    assert reason_label("some_future_code") == "some_future_code"


# ============================================================ 门 5：端到端贯通


@pytest.mark.parametrize("case_id", PDF_CASES)
def test_end_to_end_pdf_fixtures_match_truth(case_id):
    """**端到端贯通**：夹具 PDF → ingest → normalize → judge，与真值逐行一致。

    真值只给"输入与期望行"，本用例自己从行文本实算判定——观测由运行时产生。
    """
    from checkup_ledger.config import load_config
    from checkup_ledger.ingest import ingest

    threshold = load_config().ocr_threshold
    result = ingest(_fixture("pdf/%s.pdf" % case_id), ocr_threshold=threshold)
    normalized = normalize_ingest(result, dictionary=load_dictionary())
    assert not normalized.pending_mapping, "夹具行竟然进不了映射：%s" % [
        (item.reason, item.raw_text) for item in normalized.pending_mapping
    ]

    texts = [m.line_ref.text for m in normalized.measurements]
    assert texts == _truth(case_id)["expected_lines"], "端到端行文本与真值不符：%s" % texts
    assert len(normalized.measurements) == 4


def test_line_ref_survives_normalization():
    """溯源链在规范化层**不能断**：`Measurement.line_ref` 必须保留页/行/来源文件。"""
    from checkup_ledger.config import load_config
    from checkup_ledger.ingest import ingest

    threshold = load_config().ocr_threshold
    result = ingest(_fixture("pdf/ingest-pdf-plain.pdf"), ocr_threshold=threshold)
    normalized = normalize_ingest(result, dictionary=load_dictionary())
    for measurement in normalized.measurements:
        ref = measurement.line_ref
        assert ref is not None, "规范化后丢了溯源行"
        assert ref.page == 1, "页码丢失"
        assert ref.source_file == "ingest-pdf-plain.pdf", "来源文件丢失"
        assert ref.line_no >= 1


def test_end_to_end_range_source_is_visible_in_judged_output():
    """三级优先在**产物里显式可见**：自印区间 → `report_printed`。

    这条把引擎侧的三级优先与模块② 的输入层贯通：报告行 → 规范化 → 判定。
    """
    from checkup_ledger.config import load_config
    from checkup_ledger.ingest import ingest
    from checkup_ledger.loader import load_indicators
    from checkup_ledger.paths import indicators_path

    threshold = load_config().ocr_threshold
    dictionary = load_dictionary()
    table = load_indicators(indicators_path())

    result = ingest(_fixture("pdf/ingest-pdf-plain.pdf"), ocr_threshold=threshold)
    normalized = normalize_ingest(result, dictionary=dictionary)
    judged = judge_all(
        normalized.measurements, table.verified_defaults(), constraints=dictionary.constraints()
    )

    assert {item.range_source for item in judged} == {RANGE_SOURCE_REPORT}, (
        "夹具印了区间，来源应为 report_printed：%s" % [item.range_source for item in judged]
    )
    assert {item.flag for item in judged} == {FLAG_HIGH, FLAG_LOW, FLAG_NORMAL}, (
        "四态中应有 H/L/正常：%s" % [item.flag for item in judged]
    )


def test_unverified_default_never_reaches_judgement_path():
    """知识库条目一律 `pending` → 未自印区间时**走拒判**（`none`），不是 normal。

    这是设计内行为（宁拒判不臆造）。本用例用一行"未印区间"的报告行覆盖该路径。
    """
    dictionary = load_dictionary()
    from checkup_ledger.loader import load_indicators
    from checkup_ledger.paths import indicators_path

    table = load_indicators(indicators_path())
    assert table.verified_defaults() == {}, "知识库有 verified 条目——本用例前提已变"

    text = _report_line("GLU", range_text="（未印）")
    normalized = normalize([_line(text)], dictionary=dictionary)
    assert len(normalized.measurements) == 1, "未印区间的行进不了映射：%s" % [
        (item.reason, item.raw_text) for item in normalized.pending_mapping
    ]
    judged = judge_all(
        normalized.measurements, table.verified_defaults(), constraints=dictionary.constraints()
    )
    assert judged[0].flag == FLAG_NOT_ASSESSED, "pending 默认值进了判定路径（应拒判）"
    assert judged[0].range_source == RANGE_SOURCE_NONE


def test_normalize_ingest_holds_back_unreviewed_rows():
    """**未复核行不向下传递**：`normalize_ingest` 只吃模块① 放行的行。

    这里在**端到端**再验一次：低置信未复核行既不进 measurements、也不进
    pending_mapping（它压根没到这一层），且被显式记入注记（不静默丢）。
    """
    dictionary = load_dictionary()
    kept = _report_line("ALT")
    held = _report_line("AST")
    raw = IngestResult(
        lines=[_line(kept, line_no=1)],
        engine="ocr",
        pending_review=[_line(held, line_no=2)],
    )
    result = normalize_ingest(raw, dictionary=dictionary)
    assert [m.canonical_name for m in result.measurements] == ["ALT"]
    assert all(item.raw_text != held for item in result.pending_mapping)
    assert any(note.code == "held_back" for note in result.notes), "待复核行被静默丢弃"


def test_normalize_ingest_rejects_leaked_pending_rows():
    """**防绕过**：同一行既在 `lines` 又在 `pending_review` → 报错（复核门被绕过）。

    静默照常处理会让"未复核行不得进入规范化层"这条纪律有第二条绕过路径。
    """
    dictionary = load_dictionary()
    leaked = _line(_report_line("AST"), line_no=2)
    raw = IngestResult(lines=[leaked], engine="ocr", pending_review=[leaked])
    with pytest.raises(NormalizeError) as excinfo:
        normalize_ingest(raw, dictionary=dictionary)
    assert "复核门被绕过" in str(excinfo.value)


# ============================================================ CLI 面


def test_cli_normalize_reports_source_and_pending_mapping():
    """CLI 面：判定来源与待人工映射都要打印出来（产物可审计）。"""
    sample = _fixture("pdf/ingest-pdf-plain.pdf")
    code, out, err = run_cli(["normalize", sample])
    assert code == 0, "normalize 退出码应为 0：%s" % err
    assert "report_printed" in out, "判定来源未在 CLI 产物里可见"
    assert "已映射" in out


def test_cli_normalize_json_is_deterministic():
    """双跑字节一致：同输入两次产出的 JSON 逐字节相等（确定性写盘单点）。"""
    import tempfile

    sample = _fixture("pdf/ingest-pdf-plain.pdf")
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "a.json")
        second = os.path.join(tmp, "b.json")
        code_a, _out_a, err_a = run_cli(["normalize", sample, "--json", first])
        code_b, _out_b, err_b = run_cli(["normalize", sample, "--json", second])
        assert code_a == 0 and code_b == 0, "%s / %s" % (err_a, err_b)
        with open(first, "rb") as handle:
            payload_a = handle.read()
        with open(second, "rb") as handle:
            payload_b = handle.read()
    assert payload_a == payload_b, "同输入双跑 JSON 不一致（写盘不确定）"
    assert b"\r" not in payload_a, "产物含 CR"


def test_cli_normalize_exits_three_without_pdf_dependency(monkeypatch):
    """缺 `[pdf]` → **exit 3**（与 ingest 同一契约，不裸抛）。"""
    import builtins
    import sys

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.split(".")[0] in ("pdfplumber", "pdfminer"):
            raise ModuleNotFoundError("No module named %r" % name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for name in ("pdfplumber", "pdfminer"):
        sys.modules.pop(name, None)
    code, _out, _err = run_cli(["normalize", _fixture("pdf/ingest-pdf-plain.pdf")])
    assert code == 3, "缺依赖未走 exit 3 契约"


# ============================================================ 跨层语义对齐（M1 样例 ↔ M3 规范化）


def _report_lines(case_id):
    """把 M1 合成报告文本读成 `RawLine[]`（**开发期夹具格式**，非产品输入路径）。

    报告里的 `[置信度 x]` 注记在此还原成 `RawLine.confidence`——这样低置信行
    才能走**真实的**复核门（阈值取自随包配置，与运行期同一处定义）。
    表头/说明行也一并喂入：它们不命中任何指标名，会落进 `pending_mapping`
    （正好用来证明"认不出的行不被静默丢弃"）。
    """
    import re

    path = repo_path("data", "samples", "cases", "%s.txt" % case_id)
    assert os.path.isfile(path), "样例报告不在位：%s" % path
    out = []
    with open(path, "r", encoding="utf-8") as handle:
        for index, raw in enumerate(handle, 1):
            text = raw.rstrip("\n")
            if not text.strip():
                continue
            confidence = 1.0
            match = re.search(r"\[置信度\s*([0-9.]+)\]", text)
            if match:
                confidence = float(match.group(1))
            out.append(
                RawLine(
                    page=1,
                    line_no=index,
                    text=text,
                    confidence=confidence,
                    source_file="%s.txt" % case_id,
                )
            )
    return out


def _manifest_cases():
    with open(repo_path("data", "samples", "manifest.json"), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    return [case["case_id"] for case in manifest["cases"]]


def _truth_expected(case_id):
    path = repo_path("data", "samples", "truth", "%s.truth.json" % case_id)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _printed_tuple(raw):
    if raw is None:
        return None
    return (raw.get("low"), raw.get("high"))


@pytest.mark.parametrize("case_id", _manifest_cases())
def test_sample_reports_normalize_to_truth_inputs(case_id):
    """**跨层语义对齐**：M1 样例报告文本经 M3 规范化后，必须复现 M1 真值的输入字段。

    `data/samples/truth/*.json` 是 M1 在**样例侧**铺的路，它登记的
    `canonical_name`/`value`/`unit`/`printed_range` 就是"报告里写了什么"的权威描述。
    本棒做的是**模块侧**的解析——两处若口径不一致（比如一边把 `IU/L` 归一到 `U/L`、
    另一边保留原文，或一边把未印区间读成单侧上限），样例层与模块层会各自"通过"，
    而真实链路是错的。

    断言三件事（**每一件都落在实物上**）：
    1. 报告文本里能解析出的（指标名, 数值, 单位, 自印区间）**恰好等于**真值期望集合
       ——多一条（把表头当数据）或少一条（漏读某行）都会红；
    2. 真值声明"未复核不落库"的低置信行**不出现在** measurements 里（端到端复核门）；
    3. 认不出的行（表头/说明）全部落进 `pending_mapping`，**不静默丢弃**
       （输入行数 == 已映射 + 待映射）。
    """
    from checkup_ledger.config import load_config
    from checkup_ledger.ingest import apply_review_gate
    from checkup_ledger.model import IngestResult

    truth = _truth_expected(case_id)
    raw_lines = _report_lines(case_id)

    # 真实的复核门：阈值来自随包配置（与运行期同一处定义），不提供复核留痕
    gated = apply_review_gate(
        IngestResult(lines=raw_lines, engine="pdf_text"),
        ocr_threshold=load_config().ocr_threshold,
    )
    normalized = normalize_ingest(gated, dictionary=load_dictionary())

    recovered = {
        (m.canonical_name, m.value, m.unit, _printed_tuple(
            None if m.ref_range_printed is None else
            {"low": m.ref_range_printed.low, "high": m.ref_range_printed.high}
        ))
        for m in normalized.measurements
    }
    expected = {
        (item["canonical_name"], float(item["value"]), item["unit"],
         _printed_tuple(item.get("printed_range")))
        for item in truth["expected"]
    }
    assert recovered == expected, (
        "报告文本解析结果与 M1 真值不符：\n  实得 %s\n  期望 %s" % (sorted(recovered), sorted(expected))
    )

    # 2) 未复核不落库：真值声明的低置信行不在落库集合里
    for row in truth.get("pending_review_rows", []):
        assert row["canonical_name"] not in {m.canonical_name for m in normalized.measurements}, (
            "真值声明未复核不落库的行 %r 出现在 measurements 里" % row["canonical_name"]
        )

    # 3) 不静默丢：每行都有去向（已映射 + 待人工映射 == 进入本层的行数）
    assert len(normalized.measurements) + len(normalized.pending_mapping) == len(gated.lines), (
        "有行被静默丢弃：映射 %d + 待映射 %d != 进入本层 %d"
        % (len(normalized.measurements), len(normalized.pending_mapping), len(gated.lines))
    )
    # 落进待人工映射的只应是表头/说明（指标名未登记），不应是数据行的单位/区间问题
    reasons = {item.reason for item in normalized.pending_mapping}
    assert reasons <= {REASON_NAME_UNMAPPED}, (
        "数据行出现了「非指标名未登记」的待映射原因（解析能力退化）：%s" % reasons
    )


def test_sample_reports_low_confidence_row_is_held_back_end_to_end():
    """`case-012` 的阴性对照在**模块侧**再验一次：低置信行被门拦下，放行后才进入。

    样例侧（M1 真值）声明该行"未复核不落库"；模块侧（M2 复核门 + M3 规范化）
    必须给出**同一结论**——两处若分叉，"样例层绿、模块层绿、真实链路错"就成立了。
    """
    from checkup_ledger.config import load_config
    from checkup_ledger.ingest import apply_review_gate, build_review_record
    from checkup_ledger.model import IngestResult

    threshold = load_config().ocr_threshold
    raw_lines = _report_lines("case-012-lowconf-review")
    dictionary = load_dictionary()

    first = apply_review_gate(
        IngestResult(lines=raw_lines, engine="pdf_text"), ocr_threshold=threshold
    )
    assert first.pending_review, "case-012 的低置信行未被拦下（夹具失效）"
    held_names = {m.canonical_name for m in normalize_ingest(first, dictionary=dictionary).measurements}
    assert "AST" not in held_names, "未复核的低置信行进入了 measurements"

    # 阴性对照：给出复核留痕后，该行才被放行
    records = [
        build_review_record(line, line.text, "人工核对原单") for line in first.pending_review
    ]
    second = apply_review_gate(
        IngestResult(lines=raw_lines, engine="pdf_text"),
        ocr_threshold=threshold,
        reviews=records,
    )
    assert not second.pending_review, "复核后仍有待复核行"
    admitted = {m.canonical_name for m in normalize_ingest(second, dictionary=dictionary).measurements}
    assert "AST" in admitted, "复核后低置信行仍未放行"


# ============================================================ 纯函数自证


def test_normalize_is_pure_and_repeatable():
    """**纯函数**：显式传字典时不读文件——同一输入两次调用结果逐字段一致。"""
    dictionary = load_dictionary()
    lines = [_line(_report_line("ALT"))]
    first = normalize(lines, dictionary=dictionary)
    second = normalize(lines, dictionary=dictionary)
    assert [(m.canonical_name, m.value, m.unit) for m in first.measurements] == [
        (m.canonical_name, m.value, m.unit) for m in second.measurements
    ]
    assert [m.ref_range_printed for m in first.measurements] == [
        m.ref_range_printed for m in second.measurements
    ]


def test_normalize_requires_a_dictionary():
    """无字典 → 报错（别名表经参数接收；模块不读文件，故没有兜底默认表）。"""
    with pytest.raises(NormalizeError):
        normalize([_line(_report_line("ALT"))], dictionary=None)


def test_annotation_stripping_keeps_the_rest_intact():
    """注记摘除**只摘方括号段**：其余文本（含区间写法）不动。"""
    body = _report_line("ALT")
    assert strip_annotations("%s  [置信度 0.25]" % body) == body
    assert strip_annotations(body) == body


def test_range_column_distinguishes_absent_from_unparsed():
    """区间列的三种形态（印全 / 单侧 / 读不出）必须彼此可分。"""
    low = _num(yaml_bounds("ALT")["low"])
    assert parse_range_column(["%s" % low, "~", "abc"]) == (None, REASON_RANGE_UNPARSED)
    # 占位符 → 声明没印（无 reason）
    assert parse_range_column(["（未印）"]) == (None, None)
    # 空列 → 同样视为没印
    assert parse_range_column([]) == (None, None)


def test_line_with_no_text_is_pending_not_crash():
    """空行/纯空白行：进待人工映射而不是崩溃（报告里常有空行）。"""
    dictionary = load_dictionary()
    parsed, reason = parse_line(_line("   "), dictionary)
    assert reason == REASON_NAME_UNMAPPED
    assert parsed.value is None
