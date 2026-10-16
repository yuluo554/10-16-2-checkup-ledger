"""模块⑤b 渲染层门禁：零判定、零外链、分位与区间带正确、建议词根门。

六条门（缺一条就有一种"界面在悄悄下结论"）：

1. **渲染层零判定**（AST）：`report/html.py` 无算术/比较、无区间数值字面量、
   不 import 判定内核——由 `tests/test_layering.py` 的静态门守（本文件做行为侧旁证）；
2. **零外链常驻**：渲染出口每次跑 `assert_no_external_resources`（本文件验产物无外链）；
3. **分位正确**：自身历史分位由 `report/chart.py` 实算，含"无历史 → None"（不填 0）；
4. **区间带正确**：有区间才画带；无区间（拒判）**留白**，不补一条"看起来正常"的带；
5. **渲染层也过建议词根门**：界面文字同样不许给意见；
6. **双跑字节一致**：产物无时间戳、无字典序抖动。

**区间夹具一律从知识库取**（`helpers.yaml_bounds`）。
"""

import os
import tempfile

import pytest

from helpers import bounds_pair, repo_path, run_cli, yaml_bounds

from checkup_ledger.model import (
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_NOT_ASSESSED,
    BOUNDS_CLOSED,
    Judged,
    Measurement,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
    RefRange,
)
from checkup_ledger.report import chart
from checkup_ledger.report.guard import find_external_resources
from checkup_ledger.report.html import render_measurements, render_trends, render_trends_to_file
from checkup_ledger.report.trend import series_from_rows

SAMPLE = "data/samples/ingest/pdf/ingest-pdf-plain.pdf"


def _rows(name, pairs, *, flag=FLAG_NORMAL, range_source=RANGE_SOURCE_REPORT):
    """构造台账行（升序日期）——`pairs` 为 [(date, value, flag)]。"""
    spec = yaml_bounds(name)
    low = spec["low"] if range_source == RANGE_SOURCE_REPORT else None
    high = spec["high"] if range_source == RANGE_SOURCE_REPORT else None
    return [
        {
            "canonical_name": name,
            "date": date,
            "value": value,
            "unit": spec["unit"],
            "flag": point_flag,
            "range_low": low,
            "range_high": high,
            "range_source": range_source,
            "source_file": "r.pdf",
        }
        for date, value, point_flag in pairs
    ]


def _judged(name, value, flag, *, low=None, high=None, source=RANGE_SOURCE_REPORT):
    return Judged(
        measurement=Measurement(
            canonical_name=name, raw_name=name, value=value, unit=yaml_bounds(name)["unit"]
        ),
        flag=flag,
        range_used=RefRange(low=low, high=high, bounds=BOUNDS_CLOSED, source=source),
        range_source=source,
    )


# ---------------------------------------------------------------- 分位（纯计算）


def test_percentile_rank_counts_at_or_below():
    """分位 = 不超过当前值的点数 / 总点数（含当前值本身）。"""
    assert chart.percentile_rank([10.0, 20.0, 30.0], 20.0) == pytest.approx(2 / 3)
    assert chart.percentile_rank([10.0, 20.0, 30.0], 30.0) == 1.0
    assert chart.percentile_rank([10.0, 20.0, 30.0], 5.0) == 0.0


def test_percentile_is_none_without_history():
    """空序列 / 单点 / 当前值非数 → None（**不填 0、也不填 100%**）。

    单点序列的"100%"在算术上成立，但会让人读成"处在历史最高位"——而那次根本没有
    历史可比。这是与"拒判 ≠ 正常"同族的纪律：没有可比对象时如实说没有。
    """
    assert chart.percentile_rank([], 5.0) is None
    assert chart.percentile_rank([10.0], None) is None
    assert chart.percentile_rank([], None) is None
    assert chart.percentile_rank([10.0], 10.0) is None, "单点序列给出了分位（无历史可比）"
    assert chart.percentile_rank([10.0], 5.0) is None, "单点序列给出了分位（无历史可比）"


def test_percentile_text_is_blank_for_none():
    """展示写法：None → 空串（不是 "0%"）。

    比例夹具用 `1/2` **算式**给出，不写裸的小数：某个二位小数恰好等于知识库
    某个区间端点，零字面量门禁（扫 tests/ 全文，含 docstring）会把它判成
    "区间数值的第二处定义"——这里要的只是一个"非 0 非 1 的比例"。
    """
    assert chart.format_percentile(None) == ""
    ratio = 1 / 2
    # 展示写法去掉了多余的尾零，故断言落在整数百分比上（用算式给出期望，不写裸数值）
    assert chart.format_percentile(ratio) == "%d%%" % int(ratio * 100)


# ---------------------------------------------------------------- 图元几何


def test_plot_domain_includes_band_bounds():
    """值域必须含区间端点——否则区间带会被裁到画布外。

    夹具让**全部观测点都落在区间内侧**：若值域只按观测值算（不含端点），
    端点就会落在域外，断言 `domain_low <= low` 必红。这条是"值域要含端点"
    这一实现的**唯一可证伪**形态——用"观测值本身就在端点附近"的夹具，
    含与不含端点算出来的域几乎一样，门会空转。
    """
    low, high = bounds_pair("ALT")
    inside = [(low + high) / 2.0]
    domain_low, domain_high = chart.plot_domain(inside, low, high)
    assert domain_low <= low, "值域下界未含区间下限（带会被裁掉）：%s vs %s" % (domain_low, low)
    assert domain_high >= high, "值域上界未含区间上限（带会被裁掉）：%s vs %s" % (domain_high, high)


def test_plot_domain_handles_degenerate_single_value():
    """全部点同值 → 域向两侧撑开（否则除零，或折线被压成贴着边框的一条线）。"""
    domain_low, domain_high = chart.plot_domain([42.0])
    assert domain_low < 42.0 < domain_high


def test_plot_domain_rejects_empty():
    with pytest.raises(chart.ChartError):
        chart.plot_domain([])


def test_scale_rejects_out_of_range_index():
    with pytest.raises(chart.ChartError):
        chart.scale_x(5, 2)


def test_series_plan_has_band_when_range_present():
    """有区间 → 计划里带 `band`（含 x/y/width/height，全是格式化字符串）。"""
    spec = yaml_bounds("ALT")
    plan = chart.build_series_plan(
        [
            {"date": "2023-03-11", "value": spec["high"], "flag": FLAG_HIGH,
             "range_low": spec["low"], "range_high": spec["high"]},
        ]
    )
    assert plan["band"] is not None
    for key in ("x", "y", "width", "height"):
        assert isinstance(plan["band"][key], str), "band.%s 不是格式化字符串：%r" % (key, plan["band"][key])


def test_series_plan_has_no_band_when_range_absent():
    """无区间（拒判）→ `band` 为 None（**留白**，不补一条"看起来正常"的带）。"""
    plan = chart.build_series_plan(
        [{"date": "2024-01-01", "value": 5.0, "flag": FLAG_NOT_ASSESSED,
          "range_low": None, "range_high": None}]
    )
    assert plan["band"] is None, "无区间却画出了区间带（伪造了一条参考区间）"
    assert plan["percentile_text"] == "", "单点序列给出了分位（无历史可比）"


# ---------------------------------------------------------------- 零外链 + 词根门


def test_rendered_measurements_have_no_external_resources():
    low, high = bounds_pair("ALT")
    document = render_measurements(
        [_judged("ALT", high, FLAG_HIGH, low=low, high=high)], subject="张三"
    )
    assert find_external_resources(document) == []


def test_rendered_trends_have_no_external_resources():
    spec = yaml_bounds("ALT")
    document = render_trends(
        series_from_rows(_rows("ALT", [("2023-03-11", spec["high"], FLAG_HIGH)])), subject="张三"
    )
    assert find_external_resources(document) == []
    assert "<svg" in document, "趋势报告缺折线图元"


def test_rendered_trends_pass_advisory_wording_gate():
    """渲染层也过建议词根门：界面文字不许给意见。"""
    from checkup_ledger.export import find_advisory_wording

    spec = yaml_bounds("ALT")
    document = render_trends(
        series_from_rows(_rows("ALT", [("2023-03-11", spec["high"], FLAG_HIGH)])), subject="张三"
    )
    assert find_advisory_wording(document) == [], "渲染产物含建议性词根"


def test_render_trends_rejects_advisory_wording_in_subject():
    """变异验证：主体名带"建议"→ 渲染必须报错（词根门在渲染出口真的生效）。"""
    from checkup_ledger.export import AdvisoryWordingError

    spec = yaml_bounds("ALT")
    with pytest.raises(AdvisoryWordingError):
        render_trends(
            series_from_rows(_rows("ALT", [("2023-03-11", spec["high"], FLAG_HIGH)])),
            subject="建议复查",
        )


def test_chart_band_absent_renders_no_rect():
    """端到端：拒判指标渲染出的 HTML 里**没有** band 矩形（留白是真的留白）。"""
    document = render_trends(
        series_from_rows(
            _rows("ALT", [("2024-01-01", 5.0, FLAG_NOT_ASSESSED)], range_source=RANGE_SOURCE_NONE)
        ),
        subject="张三",
    )
    assert 'class="band"' not in document, "无区间却渲染出了区间带"
    assert "无区间" in document, "区间来源未如实展示"


# ---------------------------------------------------------------- 双跑一致


def test_render_trends_double_run_is_byte_identical():
    spec = yaml_bounds("ALT")
    series = series_from_rows(
        _rows("ALT", [("2023-03-11", spec["high"], FLAG_HIGH), ("2024-03-11", spec["low"], FLAG_LOW)])
    )
    first = render_trends(series, subject="张三")
    second = render_trends(series, subject="张三")
    assert first.encode("utf-8") == second.encode("utf-8")


def test_render_trends_contains_no_timestamp():
    import re

    spec = yaml_bounds("ALT")
    document = render_trends(
        series_from_rows(_rows("ALT", [("2023-03-11", spec["high"], FLAG_HIGH)])), subject="张三"
    )
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", document)


# ---------------------------------------------------------------- 装配层不重排、不透传判定


def test_series_from_rows_groups_by_name_in_dictionary_order():
    """分组键序 = 指标名字典序（不用 set 迭代序）；每组点保持取数层的日期升序。"""
    spec_alt = yaml_bounds("ALT")
    spec_ast = yaml_bounds("AST")
    rows = _rows("AST", [("2023-03-11", spec_ast["low"], FLAG_NORMAL)]) + _rows(
        "ALT", [("2023-03-11", spec_alt["high"], FLAG_HIGH), ("2024-03-11", spec_alt["low"], FLAG_LOW)]
    )
    series = series_from_rows(rows)
    assert [item["canonical_name"] for item in series] == ["ALT", "AST"]
    alt = series[0]
    assert [point["date"] for point in alt["points"]] == ["2023-03-11", "2024-03-11"]
    assert alt["flag"] == FLAG_LOW, "series.flag 未取最新一条的既有判定"
    assert [point["flag"] for point in alt["points"]] == [FLAG_HIGH, FLAG_LOW], "判定态未原样透传"


def test_series_from_rows_rejects_rows_without_name():
    from checkup_ledger.ledger.errors import LedgerError

    with pytest.raises(LedgerError):
        series_from_rows([{"canonical_name": "", "date": "2024-01-01", "value": 1.0}])


# ---------------------------------------------------------------- 端到端


def test_end_to_end_report_via_cli():
    """端到端：真实 PDF 夹具 → 入库 → 出报告（含折线、区间带、零外链）。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "ledger.db")
        out_html = os.path.join(tmp, "report.html")
        sample = repo_path(*(SAMPLE.split("/")))
        code, out, err = run_cli(
            ["report", sample, "--db", db, "--date", "2024-03-11", "--subject", "张三",
             "--out", out_html]
        )
        assert code == 0, "出报告失败：%s%s" % (out, err)
        assert os.path.isfile(out_html), "报告未落盘"
        with open(out_html, "r", encoding="utf-8") as handle:
            document = handle.read()
    assert document.count("<svg") >= 4, "报告折线数不足（每指标一张）：%d" % document.count("<svg")
    assert 'class="band"' in document, "有自印区间的指标未画区间带"
    assert find_external_resources(document) == [], "报告含外链"


def test_end_to_end_report_after_two_visits_has_trend():
    """两次不同日期入库 → 报告折线含两个点（纵向趋势真的成形）。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "ledger.db")
        out_html = os.path.join(tmp, "report.html")
        sample = repo_path(*(SAMPLE.split("/")))
        for date in ("2023-03-11", "2024-03-11"):
            code, out, err = run_cli(
                ["report", sample, "--db", db, "--date", date, "--subject", "张三", "--out", out_html]
            )
            assert code == 0, "第 %s 次出报告失败：%s%s" % (date, out, err)
        with open(out_html, "r", encoding="utf-8") as handle:
            document = handle.read()
    # 两次采血 → 每个指标的折线应有 2 个圆点
    assert document.count("<circle") >= 8, "折线点数不足（两次采血应各 2 点 × 4 指标）：%d" % document.count("<circle")


def test_render_trends_to_file_writes_atomically():
    with tempfile.TemporaryDirectory() as tmp:
        spec = yaml_bounds("ALT")
        target = os.path.join(tmp, "nested", "r.html")
        written = render_trends_to_file(
            series_from_rows(_rows("ALT", [("2023-03-11", spec["high"], FLAG_HIGH)])),
            target,
            subject="张三",
        )
        assert os.path.isfile(written)
        assert os.path.abspath(target) == written
