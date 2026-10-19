"""知识库加载与来源门禁：**未挂来源核对的条目不得生效**。

这是"可追溯性"的入口门：光有字段不等于承诺成立——若引擎会把缺来源的条目
照常加载并参与判定，报告就带着不可核证的结论出去了。判据 = "这条条目如果
来源丢了，它是**静默照常判**，还是**进不了引擎并显式报出**？"

**区间夹具一律从知识库取**（`helpers.range_dict` / `inline_range`）：测试里手写
区间数值会让测试成为"区间数值的第二处定义"（零字面量门禁扫 `tests/` 拦这个）。
测试要验的是门禁行为，用哪条区间无所谓——但数值必须与 YAML 同源。
"""

import os
import tempfile

import pytest

from helpers import inline_range, range_dict, repo_path, run_cli, yaml_bounds

from checkup_ledger.loader import (
    STATUS_PENDING,
    STATUS_VERIFIED,
    DisabledEntry,
    IndicatorDict,
    KnowledgeError,
    gate_entry,
    load_indicators,
)

INDICATORS = repo_path("src", "checkup_ledger", "data", "indicators.yaml")

ALT_UNIT = yaml_bounds("ALT")["unit"]
HGB_UNIT = yaml_bounds("HGB")["unit"]


def _write_yaml(tmp, text):
    target = os.path.join(tmp, "indicators.yaml")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return target


BASE_HEADER = """schema_version: 1
disclaimer: "\u4ec5\u4f9b\u673a\u68b0\u5224\u5b9a"
indicators:
"""


def _raw(name="ALT", source=None, applies=None, **range_kwargs):
    """构造一条 raw 条目（区间从知识库取，数值不手写）。"""
    raw = {
        "canonical_name": name,
        "unit": yaml_bounds(name)["unit"] if name in ("ALT", "HGB", "TC", "GLU") else "U/L",
        "default_range": range_dict(name),
    }
    if source is not None:
        raw["source"] = source
    if applies is not None:
        raw["applies_to"] = applies
    return raw


# ---------------------------------------------------------------- 门禁：缺来源必拒


def test_missing_source_block_is_rejected():
    raw = {
        "canonical_name": "ALT",
        "unit": ALT_UNIT,
        "default_range": range_dict("ALT"),
    }
    entry, rejected = gate_entry(raw, 0)
    assert entry is None
    assert rejected is not None
    assert "source" in rejected.reason


def test_missing_standard_is_rejected():
    raw = _raw(source={"status": "verified", "evidence": "x"})
    entry, rejected = gate_entry(raw, 0)
    assert entry is None
    assert "standard" in rejected.reason


def test_invalid_status_is_rejected():
    raw = _raw(source={"standard": "WS/T 404.1-2012", "status": "maybe"})
    entry, rejected = gate_entry(raw, 0)
    assert entry is None
    assert "status" in rejected.reason


def test_verified_without_evidence_is_rejected():
    """verified 却没留核对渠道 → 拒绝（"已核对"必须可指认）。"""
    raw = _raw(source={"standard": "WS/T 404.1-2012", "status": "verified", "evidence": "  "})
    entry, rejected = gate_entry(raw, 0)
    assert entry is None
    assert "evidence" in rejected.reason


def test_missing_canonical_name_is_rejected():
    raw = {"unit": "U/L", "default_range": range_dict("ALT"),
           "source": {"standard": "X", "status": "pending"}}
    entry, rejected = gate_entry(raw, 0)
    assert entry is None
    assert "canonical_name" in rejected.reason


def test_pending_entry_loads_but_cannot_be_default():
    """pending 条目可加载（作展示信息），但**不得**进判定路径。"""
    raw = _raw(source={"standard": "WS/T 404.1-2012", "status": "pending", "evidence": ""})
    entry, rejected = gate_entry(raw, 0)
    assert rejected is None
    assert entry is not None
    assert entry.status == STATUS_PENDING
    assert not entry.usable_as_default


def test_verified_entry_is_usable():
    raw = _raw(source={"standard": "WS/T 404.1-2012", "status": "verified",
                       "evidence": "wsbz 快照 2026-10-20"})
    entry, rejected = gate_entry(raw, 0)
    assert rejected is None
    assert entry.usable_as_default


def test_verified_defaults_excludes_pending():
    """判定路径唯一入口只含 verified——这是"pending 不进判定"的机制落点。"""
    raw = _raw(source={"standard": "X", "status": "pending"})
    entry, _ = gate_entry(raw, 0)
    table = IndicatorDict(entries=[entry], disabled=[])
    assert table.verified_defaults() == {}
    assert table.by_canonical("ALT") is entry  # 仍可查询（展示用）


def test_verified_defaults_includes_verified():
    """反向对照：verified 条目**必须**进判定路径（否则门是"一律不进"）。"""
    raw = _raw(source={"standard": "X", "status": "verified", "evidence": "渠道 2026-10-20"})
    entry, _ = gate_entry(raw, 0)
    table = IndicatorDict(entries=[entry], disabled=[])
    assert "ALT" in table.verified_defaults()


# ---------------------------------------------------------------- 区间字段校验


def test_inverted_range_is_rejected():
    raw = _raw(source={"standard": "X", "status": "pending"})
    raw["default_range"] = range_dict("ALT", invert=True)
    entry, rejected = gate_entry(raw, 0)
    assert entry is None
    assert "高于上限" in rejected.reason


def test_bad_bounds_is_rejected():
    raw = _raw(source={"standard": "X", "status": "pending"})
    raw["default_range"] = range_dict("ALT", bounds="half-open")
    entry, rejected = gate_entry(raw, 0)
    assert entry is None
    assert "bounds" in rejected.reason


def test_bad_sex_is_rejected():
    raw = _raw("HGB", source={"standard": "X", "status": "pending"}, applies={"sex": "unknown"})
    entry, rejected = gate_entry(raw, 0)
    assert entry is None
    assert "sex" in rejected.reason


# ---------------------------------------------------------------- 整库加载


def test_load_real_knowledge_base():
    table = load_indicators(INDICATORS)
    assert table.schema_version == 1
    assert table.entries, "知识库没有任何可加载条目"
    assert table.disclaimer.strip(), "知识库缺免责声明（判定产物要带它）"


def test_all_loaded_entries_carry_source():
    """加载成功的每一条都必须挂来源分册——这是本门存在的理由。"""
    table = load_indicators(INDICATORS)
    for entry in table.entries:
        assert entry.source_standard, "条目 %s 缺来源分册" % entry.canonical_name
        assert entry.status in (STATUS_PENDING, STATUS_VERIFIED), (
            "条目 %s status 非法" % entry.canonical_name
        )


def test_real_knowledge_base_covers_required_domains():
    """覆盖度：五指标域各至少一项（plan/04 覆盖度门槛）。"""
    table = load_indicators(INDICATORS)
    names = {entry.canonical_name for entry in table.entries}
    # 五域代表项（每域至少一个；具体条目以 YAML 为准）
    required = {
        "WBC", "RBC", "HGB", "HCT", "PLT",          # 血常规
        "ALT", "AST", "ALP", "GGT", "TBIL", "TP",   # 肝功能
        "TC", "TG", "HDL-C", "LDL-C",               # 血脂
        "CREA", "UREA", "UA",                        # 肾功能
        "GLU",                                       # 血糖
    }
    missing = sorted(required - names)
    assert not missing, "知识库缺这些域的代表项：%s" % missing


def test_duplicate_canonical_name_is_disabled():
    text = BASE_HEADER + """
  - canonical_name: ALT
    unit: %s
    default_range: %s
    source: { standard: X, status: pending }
  - canonical_name: ALT
    unit: %s
    default_range: %s
    source: { standard: X, status: pending }
""" % (ALT_UNIT, inline_range("ALT"), ALT_UNIT, inline_range("ALT", high_delta=1))
    with tempfile.TemporaryDirectory() as tmp:
        table = load_indicators(_write_yaml(tmp, text))
    assert len(table.entries) == 1
    assert any("重复" in item.reason for item in table.disabled)


def test_unsupported_schema_version_is_rejected():
    text = "schema_version: 99\ndisclaimer: x\nindicators:\n"
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(KnowledgeError):
            load_indicators(_write_yaml(tmp, text))


# ---------------------------------------------------------------- 复核锚（next_review）


def test_repo_knowledge_base_declares_next_review_in_iso_date():
    """**本仓**的 `indicators.yaml` 必须带机读复核锚，且形状是 `YYYY-MM-DD`。

    判据两面：
    - 锚点**存在**（没有锚点 = "已核对"永远停在过去时，知识库没有下次再核的入口）；
    - 形状**零填充 8 位日期**（不零填充的月份/日会被字符串比较读错序，也会让
      `review_overdue` 的字典序比较给出错误答案）。
    """
    import re

    table = load_indicators(INDICATORS)
    assert table.next_review, "知识库缺 next_review 复核锚"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", table.next_review), (
        "next_review 不是零填充 YYYY-MM-DD：%r" % table.next_review
    )
    assert table.review_interval, "知识库缺 review_interval（复核周期未登记）"


def test_repo_knowledge_base_entries_remain_pending():
    """**复核锚不得被用来改状态**：所有条目仍必须 `pending`。

    "加了 next_review 就等于核对过了"是本迭代最容易犯的错——锚点是**待办提醒**，
    不是核对结果。WS/T 全文仍不可直连，条目一旦被顺手改成 verified，判定路径就会
    开始用未核对原文的区间。
    """
    table = load_indicators(INDICATORS)
    offenders = [e.canonical_name for e in table.entries if e.status != STATUS_PENDING]
    assert not offenders, "条目被改成非 pending：%s（核对原文才可改）" % offenders
    assert table.verified_defaults() == {}, "判定路径出现了 verified 默认值"


def test_missing_anchor_is_legal_and_never_reports_overdue():
    """老知识库（无锚点）**不报逾期**——没有锚点不等于"早就该复核了"。"""
    text = BASE_HEADER + """
  - canonical_name: ALT
    unit: %s
    default_range: %s
    source: { standard: X, status: pending }
""" % (ALT_UNIT, inline_range("ALT"))
    with tempfile.TemporaryDirectory() as tmp:
        table = load_indicators(_write_yaml(tmp, text))
    assert table.next_review is None
    assert table.review_overdue("2099-01-01") is False, "无锚点却判逾期（凭空造判据）"


def test_malformed_next_review_is_rejected():
    """形状错的锚点必须**拒绝加载**——"看起来有复核纪律、实际读不出来"比没有更危险。"""
    for bad in ('"2027-1-6"', '2027/10/16', '""', '20271016'):
        text = 'schema_version: 1\nnext_review: %s\ndisclaimer: x\nindicators:\n' % bad
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(KnowledgeError) as excinfo:
                load_indicators(_write_yaml(tmp, text))
            assert "next_review" in str(excinfo.value)


def test_review_overdue_compares_dates_not_status():
    """逾期判定只比对日期字符串，**不读时钟、不改 status**。"""
    table = IndicatorDict(entries=[], disabled=[], next_review="2027-10-16", review_interval="annual")
    assert table.review_overdue("2027-10-15") is False, "到期前一天就判逾期"
    assert table.review_overdue("2027-10-16") is False, "到期当天不该算逾期"
    assert table.review_overdue("2027-10-17") is True, "到期次日未判逾期"
    assert table.entries == [] and table.disabled == [], "逾期判定改动了条目状态"


def test_missing_file_is_not_silently_empty():
    """文件缺失 → 报错，**不静默当空库**（空库会让一切走拒判，看起来"一切正常"）。"""
    with pytest.raises(KnowledgeError):
        load_indicators(repo_path("src", "checkup_ledger", "data", "no-such-file.yaml"))


def test_malformed_yaml_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(KnowledgeError):
            load_indicators(_write_yaml(tmp, "schema_version: 1\nindicators: [ {unclosed\n"))


def test_empty_indicators_list_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(KnowledgeError):
            load_indicators(_write_yaml(tmp, "schema_version: 1\ndisclaimer: x\nindicators: []\n"))


def test_disabled_entries_are_reported_not_dropped():
    """被拦条目必须显式进"未启用清单"——静默丢弃 = 报告里看不出缺了什么。"""
    text = BASE_HEADER + """
  - canonical_name: GOOD
    unit: %s
    default_range: %s
    source: { standard: X, status: pending }
  - canonical_name: BAD
    unit: %s
    default_range: %s
    source: { status: pending }
""" % (ALT_UNIT, inline_range("ALT"), ALT_UNIT, inline_range("ALT"))
    with tempfile.TemporaryDirectory() as tmp:
        table = load_indicators(_write_yaml(tmp, text))
    assert [e.canonical_name for e in table.entries] == ["GOOD"]
    assert [d.canonical_name for d in table.disabled] == ["BAD"]
    assert table.disabled[0].reason


# ---------------------------------------------------------------- CLI 面


def test_selftest_prints_review_anchor(monkeypatch):
    """`selftest` 的 knowledge 项必须把复核锚**打印出来**（让锚点可见，不只是写进 YAML）。"""
    monkeypatch.delenv("CHECKUP_LEDGER_TODAY", raising=False)
    code, out, _err = run_cli(["selftest"])
    assert code == 0, "自检未通过（复核锚不该影响退出码）：\n%s" % out
    assert "复核锚" in out, "自检输出里看不到复核锚：\n%s" % out
    assert load_indicators(INDICATORS).next_review in out


def test_selftest_overdue_anchor_warns_but_keeps_exit_zero(monkeypatch):
    """逾期只**提示**、`selftest` 仍 exit 0——锚点是待办提醒，不是知识库不可用的理由。

    反面对照必须存在：若逾期也 exit 1，本仓"6/6 通过"会在 2027-10-17 自动变红，
    而那一天知识库的状态其实一个字节都没变。
    """
    monkeypatch.setenv("CHECKUP_LEDGER_TODAY", "2099-01-01")
    code, out, _err = run_cli(["selftest"])
    assert code == 0, "复核锚逾期把自检打成失败（应只提示）：\n%s" % out
    assert "已逾期" in out, "逾期未在自检输出里提示：\n%s" % out
    assert "自检结论：6/6 通过" in out, "逾期改变了自检的通过数"


def test_selftest_reports_missing_anchor_explicitly(monkeypatch, tmp_path):
    """没有锚点时自检要说"未设复核锚"——不静默、也不假称有锚。

    造一份去掉 `next_review` 行的数据目录，经 `CHECKUP_LEDGER_DATA` 指过去
    （`selftest --data-dir` 不参与 knowledge 项，故这里用环境变量走真实解析链）。
    """
    from checkup_ledger.paths import indicators_path

    source_dir = os.path.dirname(indicators_path())
    source = open(indicators_path(), "r", encoding="utf-8").read()
    stripped = "\n".join(
        line for line in source.splitlines() if not line.startswith("next_review:")
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "indicators.yaml").write_text(stripped, encoding="utf-8")
    (data_dir / "config.yaml").write_text(
        open(os.path.join(source_dir, "config.yaml"), "r", encoding="utf-8").read(),
        encoding="utf-8",
    )

    # 剥离自证：解析这份夹具必须真的**读不到**锚点（否则下面的断言来自源文件而非夹具）
    assert load_indicators(str(data_dir / "indicators.yaml")).next_review is None, (
        "剥离未生效：夹具里仍有可解析的 next_review 键（测试自身的构造有问题）"
    )

    monkeypatch.setenv("CHECKUP_LEDGER_DATA", str(data_dir))
    code, out, _err = run_cli(["selftest"])
    assert code == 0, "无锚点不该让自检失败：\n%s" % out
    assert "未设复核锚" in out, "缺锚点未如实报出：\n%s" % out


def test_cli_indicators_lists_disabled_section():
    code, out, _err = run_cli(["indicators"])
    assert code == 0
    assert "\u672a\u542f\u7528\u6761\u76ee" in out


def test_cli_indicators_reports_pending_as_not_usable():
    """当前知识库条目一律 pending → CLI 必须如实标"待核对(不进判定)"。"""
    code, out, _err = run_cli(["indicators"])
    assert code == 0
    assert "\u5f85\u6838\u5bf9" in out


def test_cli_indicators_json_is_deterministic():
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "a.json")
        second = os.path.join(tmp, "b.json")
        run_cli(["indicators", "--json", first])
        run_cli(["indicators", "--json", second])
        with open(first, "r", encoding="utf-8") as handle_a, open(second, "r", encoding="utf-8") as handle_b:
            assert json.load(handle_a) == json.load(handle_b)


def test_cli_indicators_missing_data_dir_reports_findings():
    """数据目录解析失败 → exit 1（检出问题），不是用法错误。"""
    code, _out, err = run_cli(["indicators", "--data-dir", os.path.join(os.sep, "no-such-dir-xyz")])
    assert code == 1
    assert "\u6570\u636e\u76ee\u5f55" in err or "data" in err.lower()
