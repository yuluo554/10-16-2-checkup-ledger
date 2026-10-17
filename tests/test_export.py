"""模块⑤a 导出层门禁：建议性词根逐字校验、数值正确、格式与事实字段。

五条门（缺一条就有一种"看起来导出了、其实在给意见"）：

1. **建议性词根逐字校验**（负向词表：`建议`/`可能`/`风险提示`/`注意`/`应`/`考虑`）：
   遍历导出物，命中即红；含**变异验证**（塞一个"建议"必红）；
2. **出口常驻**：`export_summary` 每次写盘前跑词根门（不是"测试里验一次"）；
3. **变化幅度正确**：含 +0%（持平）与负向变化；由 `engine.trend_delta` 实算；
4. **首点/无前值不填 0**："没有可比前值"与"变化为零"是两件事；
5. **未知格式报错**：不静默选一个默认格式。

**区间夹具一律从知识库取**（`helpers.yaml_bounds`）。
"""

import os
import tempfile

import pytest

from helpers import requires_pdf, repo_path, run_cli, yaml_bounds

from checkup_ledger.export import (
    ADVISORY_ROOTS,
    AdvisoryWordingError,
    DISCLAIMER,
    ExportError,
    assert_no_advisory_wording,
    export_summary,
    find_advisory_wording,
    history_from_ledger,
)
from checkup_ledger.model import (
    FLAG_HIGH,
    FLAG_NORMAL,
    BOUNDS_CLOSED,
    Judged,
    Measurement,
    RANGE_SOURCE_REPORT,
    RefRange,
)

SAMPLE = "data/samples/ingest/pdf/ingest-pdf-plain.pdf"


@pytest.fixture()
def out_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def _judged(name, value, flag, *, low=None, high=None):
    spec = yaml_bounds(name)
    return Judged(
        measurement=Measurement(canonical_name=name, raw_name=name, value=value, unit=spec["unit"]),
        flag=flag,
        range_used=RefRange(low=low, high=high, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_REPORT),
        range_source=RANGE_SOURCE_REPORT,
    )


def _row_of(target, name):
    """把导出的 CSV 读回，取该指标那一行——**按列名取值**，不写位置魔数。

    位置下标是"列序的第二处定义"：`CSV_COLUMNS` 调序时，按下标断言的测试会
    静默取错列（"变化比例"的断言读到"趋势"列，还可能凑巧通过）。
    """
    import csv

    from checkup_ledger.export import CSV_COLUMNS

    with open(target, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = None
        for row in reader:
            if header is None:
                if row and row[0] == CSV_COLUMNS[0]:
                    header = row
                continue
            if row and row[0] == name:
                return dict(zip(header, row))
    raise AssertionError("导出物里没有指标 %s 的行" % name)


def _all_data_rows(target):
    """把导出的 CSV 读回，返回全部**数据行**（按列名取值）。

    只收**列数与表头一致**的行：产物末尾的免责段是单列行，把它当数据行会让
    `zip(header, row)` 造出一个"第一列是免责全文"的假记录（断言会拿到一串散文）。
    """
    import csv

    from checkup_ledger.export import CSV_COLUMNS

    with open(target, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = None
        rows = []
        for row in reader:
            if header is None:
                if row and row[0] == CSV_COLUMNS[0]:
                    header = row
                continue
            if row and len(row) == len(header):
                rows.append(dict(zip(header, row)))
    return rows


# ---------------------------------------------------------------- 建议性词根门


def test_advisory_roots_are_the_declared_six():
    """负向词表必须恰好是声明的那六个——模糊扩表会让门对某类措辞整体失效。"""
    assert ADVISORY_ROOTS == ("建议", "可能", "风险提示", "注意", "应", "考虑")


@pytest.mark.parametrize("root", ADVISORY_ROOTS)
def test_each_advisory_root_is_detected(root):
    """六个词根**逐个**验：任一个漏检，对应那一类措辞就能悄悄出现在产物里。"""
    text = "ALT 43 U/L %s 复查" % root
    assert find_advisory_wording(text) == [root], "词根未被检出：%s" % root
    with pytest.raises(AdvisoryWordingError):
        assert_no_advisory_wording(text)


def test_clean_text_passes_wording_gate():
    """阴性对照：只陈述事实的文本必须放行（否则门可以靠"永远报错"满足）。"""
    text = "ALT 由 32 升至 47，变化 +46.9%"
    assert find_advisory_wording(text) == []
    assert_no_advisory_wording(text)


def test_export_rejects_advisory_wording_in_artifact(out_dir):
    """变异验证：往产物里塞一个"建议" → 导出必须报错（门真的在用）。

    做法是让**标题**带上词根——标题会进产物，故必须被拦下。
    """
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.csv")
    with pytest.raises(AdvisoryWordingError):
        export_summary(
            [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)],
            fmt="csv",
            out=target,
            subject="张三",
            date="2024-03-11",
            title="建议复查",
        )
    assert not os.path.isfile(target), "词根门报错后仍写出了产物"


def test_export_writes_artifact_that_passes_wording_gate(out_dir):
    """出口常驻：正常导出后，把产物读回来过一遍词根门必须干净。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.csv")
    export_summary(
        [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)],
        fmt="csv",
        out=target,
        subject="张三",
        date="2024-03-11",
    )
    with open(target, "r", encoding="utf-8") as handle:
        artifact = handle.read()
    assert find_advisory_wording(artifact) == [], "导出物含建议性词根"
    assert "本摘要只陈述数值与变化幅度的事实" in artifact, "产物缺常驻免责段"


# ---------------------------------------------------------------- 数值正确性


def test_delta_and_percent_are_computed_from_engine(out_dir):
    """变化幅度与比例由引擎实算：正/负/零三形态各一例。"""
    from checkup_ledger.engine.compare import trend_delta

    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.csv")
    history = {"ALT": [{"date": "2023-03-11", "value": 32.0}]}
    export_summary(
        [_judged("ALT", 47.0, FLAG_HIGH, low=low, high=high)],
        fmt="csv",
        out=target,
        subject="张三",
        date="2024-03-11",
        history=history,
    )
    row = _row_of(target, "ALT")
    assert row["上次数值"] == "32", "上次数值未写出：%s" % row
    assert row["变化幅度"] == str(int(trend_delta(32.0, 47.0))), "变化幅度不符：%s" % row
    assert row["变化比例"].startswith("+") and row["变化比例"].endswith("%"), "变化比例格式不符：%s" % row
    assert row["趋势"] == "up", "趋势未标为 up：%s" % row


def test_flat_change_is_zero_percent(out_dir):
    """持平：变化幅度 0、比例 +0%（不是空串——那是"无前值"的表示）。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.csv")
    history = {"ALT": [{"date": "2023-03-11", "value": 43.0}]}
    export_summary(
        [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)],
        fmt="csv",
        out=target,
        subject="张三",
        date="2024-03-11",
        history=history,
    )
    row = _row_of(target, "ALT")
    assert row["变化幅度"] == "0", "持平被写成非零幅度：%s" % row
    assert row["变化比例"] == "0%", "持平比例格式不符（+0%% 亦可）：%s" % row
    assert row["趋势"] == "flat"


def test_no_history_leaves_change_columns_blank(out_dir):
    """没有既往可比值 → 变化列**留空**（不填 0：0 是"没变化"这一事实）。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.csv")
    export_summary(
        [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)],
        fmt="csv",
        out=target,
        subject="张三",
        date="2024-03-11",
    )
    row = _row_of(target, "ALT")
    assert row["上次数值"] == "", "无前值时写出了上次数值：%s" % row
    assert row["变化幅度"] == "", "无前值时把变化幅度填成了 0：%s" % row
    assert row["趋势"] == "", "无前值时给出了趋势态：%s" % row


def test_history_must_be_strictly_before_current_date(out_dir):
    """同一天的历史**不算**可比前值——否则重跑会把"这次没变"这个假事实写进产物。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.csv")
    history = {"ALT": [{"date": "2024-03-11", "value": 43.0}]}  # 与当前日期相同
    export_summary(
        [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)],
        fmt="csv",
        out=target,
        subject="张三",
        date="2024-03-11",
        history=history,
    )
    row = _row_of(target, "ALT")
    assert row["变化幅度"] == "", "同一天的历史被当成可比前值（造出假的持平）"


def test_percent_is_blank_when_previous_value_is_zero(out_dir):
    """前值为零 → 比例列留空（除零不是"变化 0%"）。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.csv")
    history = {"ALT": [{"date": "2023-03-11", "value": 0.0}]}
    export_summary(
        [_judged("ALT", 30.0, FLAG_NORMAL, low=low, high=high)],
        fmt="csv",
        out=target,
        subject="张三",
        date="2024-03-11",
        history=history,
    )
    row = _row_of(target, "ALT")
    assert row["变化幅度"] == "30", "变化幅度应可算：%s" % row
    assert row["变化比例"] == "", "前值为零时给出了变化比例（除零被伪装成 0%）"


# ---------------------------------------------------------------- 格式与形态


def test_unknown_format_is_rejected(out_dir):
    """未知格式 → 报错，不静默选一个默认（"用户以为导了 md，其实导了 csv"）。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    with pytest.raises(ExportError):
        export_summary(
            [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)],
            fmt="xlsx",
            out=os.path.join(out_dir, "s.xlsx"),
            subject="张三",
            date="2024-03-11",
        )


@pytest.mark.parametrize("fmt,marker", [("csv", "指标,日期,数值"), ("md", "| 指标 | 日期 | 数值 |")])
def test_both_formats_contain_header_and_disclaimer(out_dir, fmt, marker):
    """CSV / Markdown 两种形态都含表头与常驻免责段。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.%s" % fmt)
    export_summary(
        [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)],
        fmt=fmt,
        out=target,
        subject="张三",
        date="2024-03-11",
    )
    with open(target, "r", encoding="utf-8") as handle:
        text = handle.read()
    assert marker in text, "缺表头：%s" % fmt
    assert DISCLAIMER in text, "缺常驻免责段：%s" % fmt


def test_export_uses_canonical_flag_and_source_tokens(out_dir):
    """产物里的标记与来源用 canonical token（不换人话）——两处各自维护标签早晚分叉。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    target = os.path.join(out_dir, "s.csv")
    export_summary(
        [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)],
        fmt="csv",
        out=target,
        subject="张三",
        date="2024-03-11",
    )
    row = _row_of(target, "ALT")
    assert row["标记"] == FLAG_HIGH, "标记未用 canonical token：%s" % row
    assert row["区间来源"] == "report_printed", "来源未用 canonical token：%s" % row


def test_rows_are_sorted_by_date_then_name(out_dir):
    """多行产物按 (日期, 指标) 排序——顺序不定会让"双跑一致"随机红。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    ast_low, ast_high = yaml_bounds("AST")["low"], yaml_bounds("AST")["high"]
    target = os.path.join(out_dir, "s.csv")
    export_summary(
        [
            _judged("HGB", 152.5, FLAG_NORMAL, low=low, high=high),
            _judged("ALT", 43.0, FLAG_HIGH, low=low, high=high),
            _judged("AST", 27.5, FLAG_NORMAL, low=ast_low, high=ast_high),
        ],
        fmt="csv",
        out=target,
        subject="张三",
        date="2024-03-11",
    )
    rows = _all_data_rows(target)
    data = [row["指标"] for row in rows]
    assert data == sorted(data), "导出行未按指标名排序：%s" % data
    assert set(data) == {"ALT", "AST", "HGB"}, "排序用例缺行：%s" % data


def test_export_double_run_is_byte_identical(out_dir):
    """同输入双跑逐字节一致（产物无时间戳、无字典序抖动）。"""
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    first = os.path.join(out_dir, "a.csv")
    second = os.path.join(out_dir, "b.csv")
    judged = [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)]
    history = {"ALT": [{"date": "2023-03-11", "value": 32.0}]}
    export_summary(judged, fmt="csv", out=first, subject="张三", date="2024-03-11", history=history)
    export_summary(judged, fmt="csv", out=second, subject="张三", date="2024-03-11", history=history)
    with open(first, "rb") as handle_a, open(second, "rb") as handle_b:
        assert handle_a.read() == handle_b.read()


# ---------------------------------------------------------------- 端到端


@requires_pdf
def test_end_to_end_export_via_cli(out_dir):
    """端到端：真实 PDF 夹具 → 抽取/规范化/判定 → 导出 CSV（产物过词根门）。"""
    db = os.path.join(out_dir, "ledger.db")
    out_csv = os.path.join(out_dir, "summary.csv")
    sample = repo_path(*(SAMPLE.split("/")))
    code, out, err = run_cli(
        ["export", sample, "--db", db, "--date", "2024-03-11", "--subject", "张三",
         "--out", out_csv, "--fmt", "csv"]
    )
    assert code == 0, "导出失败：%s%s" % (out, err)
    assert os.path.isfile(out_csv), "导出物未落盘"
    with open(out_csv, "r", encoding="utf-8") as handle:
        artifact = handle.read()
    assert find_advisory_wording(artifact) == [], "端到端导出物含建议性词根"
    for name in ("ALT", "AST", "HGB", "PLT"):
        assert name in artifact, "导出物缺指标 %s" % name


def test_history_from_ledger_groups_by_indicator(tmp_path):
    """台账取数口：按指标分组（升序），导出层不再自己写一条 SELECT。"""
    from checkup_ledger.ledger import open_ledger, upsert

    db = str(tmp_path / "l.db")
    low, high = yaml_bounds("ALT")["low"], yaml_bounds("ALT")["high"]
    with open_ledger(db) as ledger:
        upsert(ledger, [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)], subject="张三", date="2023-03-11")
        upsert(ledger, [_judged("ALT", 13.0, FLAG_NORMAL, low=low, high=high)], subject="张三", date="2024-03-11")
        history = history_from_ledger(ledger, subject="张三")
    assert list(history) == ["ALT"]
    assert [row["date"] for row in history["ALT"]] == ["2023-03-11", "2024-03-11"]
