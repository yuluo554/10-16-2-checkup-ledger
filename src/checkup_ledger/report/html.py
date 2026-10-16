"""报告渲染：本地单文件 HTML（判定表 + 单指标折线 + 自身历史分位 + 参考区间带）。

分层纪律（**AST 静态门禁守**，见 `tests/test_layering.py`）：
本模块**只拼接**——不做算术、不做比较、不 import 判定内核。所有坐标换算与分位
计算都在 `report/chart.py`（那里看不到判定态），所有判定态与区间数值都来自调用方
传入的既有结论。渲染层因此不可能"重算一次判定"。

两条常驻断言（都是**出口行为**，不是"测试里验一次"）：
- `assert_no_external_resources(html)`：产物无任何外链（断网可开 / 零上传）；
- `assert_no_advisory_wording(html)`：产物无建议性词根（渲染层也不许给意见）。

**为什么渲染层也要过词根门**：判定层与导出层都守了，唯独渲染层不守的话，
"界面上的说明文字"就是唯一的漏口——报告是给人看的那一份，恰恰最容易写进
"建议复查"这类话。
"""

import html as html_mod
import os
from typing import Dict, List, Sequence

from checkup_ledger.export import assert_no_advisory_wording
from checkup_ledger.model import (
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_NOT_ASSESSED,
    Judged,
    RANGE_SOURCE_BUILTIN,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
)
from checkup_ledger.report import chart
from checkup_ledger.report.guard import assert_no_external_resources

_FLAG_LABEL = {
    FLAG_HIGH: "H 偏高",
    FLAG_LOW: "L 偏低",
    FLAG_NORMAL: "正常",
    FLAG_NOT_ASSESSED: "拒判（无区间）",
}

_SOURCE_LABEL = {
    RANGE_SOURCE_REPORT: "报告自印区间",
    RANGE_SOURCE_BUILTIN: "内置默认区间",
    RANGE_SOURCE_NONE: "无区间",
}

DISCLAIMER = (
    "本工具不做诊断、不做解读、不做分诊、不做治疗意见。表中标记仅为数值与区间的机械比较结果；"
    "各医疗机构的 LIS 打印区间为最终准绳，一切以报告单和医嘱为准。"
)

_STYLE = """
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       margin: 0; padding: 2rem; color: #1f2933; background: #f7f9fc; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 1.6rem 0 .4rem; }
.sub { color: #5a6672; font-size: .85rem; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%%; background: #fff; font-size: .9rem; }
th, td { border: 1px solid #dde3ea; padding: .45rem .6rem; text-align: left; }
th { background: #eef2f7; font-weight: 600; }
tr.not_assessed, tr.not-assessed { color: #6b7280; }
.disclaimer { margin-top: 1.5rem; padding: .8rem 1rem; background: #fff8e6;
              border: 1px solid #f0dca8; border-radius: 4px; font-size: .85rem; }
.empty { color: #5a6672; font-style: italic; }
.chart { background: #fff; border: 1px solid #dde3ea; border-radius: 4px;
         padding: .6rem .8rem 0; margin-bottom: 1rem; }
.chart svg { display: block; width: 100%%; height: auto; }
.chart .meta { font-size: .82rem; color: #5a6672; padding: .3rem 0 .6rem; }
.band { fill: #7cc4a0; }
.grid { stroke: #e4e9f0; stroke-width: 1; }
.axis { stroke: #b6c0cc; stroke-width: 1; }
.line { fill: none; stroke: #2f6f9f; stroke-width: %(line_stroke)s; }
.dot-h { fill: #c0392b; }
.dot-l { fill: #2c6fb0; }
.dot-normal { fill: #2f855a; }
.dot-not-assessed { fill: #9aa5b1; }
.axis-text { font-size: 11px; fill: #5a6672; }
"""


def _esc(text) -> str:
    return html_mod.escape(str(text), quote=True)


def _display_bound(bound):
    """区间边界的展示形式：缺值显示为占位符。纯展示，不做判定。"""
    return "\u2014" if bound is None else bound


def _flag_class(flag: str) -> str:
    return flag.replace("_", "-")


def _flag_label(flag: str) -> str:
    return _FLAG_LABEL.get(flag, flag)


def _source_label(source: str) -> str:
    return _SOURCE_LABEL.get(source, source)


# ---------------------------------------------------------------- 判定表


def render_measurements(judged: List[Judged], *, subject: str = "", title: str = "") -> str:
    """渲染判定表为完整单文件 HTML 字符串（不写盘；写盘由调用方经 serialize 完成）。"""
    rows = []
    for item in judged:
        m = item.measurement
        ref = item.range_used
        low = _display_bound(ref.low)
        high = _display_bound(ref.high)
        rows.append(
            "<tr class=\"%s\"><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                _esc(_flag_class(item.flag)),
                _esc(m.canonical_name),
                _esc(m.raw_name),
                _esc(m.value),
                _esc(m.unit),
                _esc("%s ~ %s" % (low, high)),
                _esc(_source_label(item.range_source)),
                _esc(_flag_label(item.flag)),
            )
        )

    if rows:
        body = (
            "<table><thead><tr><th>指标</th><th>报告原文</th><th>数值</th><th>单位</th>"
            "<th>所用区间</th><th>区间来源</th><th>标记</th></tr></thead><tbody>%s</tbody></table>"
            % "".join(rows)
        )
    else:
        body = '<p class="empty">本次没有可展示的记录。</p>'

    document = _document(title or "体检台账", subject, body)

    assert_no_external_resources(document)
    assert_no_advisory_wording(document)
    return document


# ---------------------------------------------------------------- 趋势图（单指标折线）


def _chart_svg(plan: Dict) -> str:
    """一张折线图（**只拼接**：坐标、分位、区间带全部由 `chart` 算好）。"""
    parts: List[str] = []
    parts.append(
        '<svg viewBox="0 0 %s %s" role="img" aria-label="单指标纵向趋势">'
        % (_esc(plan["width"]), _esc(plan["height"]))
    )

    band = plan["band"]
    if band is not None:
        parts.append(
            '<rect class="band" x="%s" y="%s" width="%s" height="%s" opacity="%s"></rect>'
            % (
                _esc(band["x"]),
                _esc(band["y"]),
                _esc(band["width"]),
                _esc(band["height"]),
                _esc(plan["band_opacity"]),
            )
        )

    # 参考区间上下沿的细线（**区间来自调用方，本层不做任何比较**）
    for bound in (plan["range_high"], plan["range_low"]):
        if bound is not None:
            y = chart.format_coord(chart.scale_y(bound, plan["domain_low"], plan["domain_high"]))
            parts.append(
                '<line class="grid" x1="%s" x2="%s" y1="%s" y2="%s"></line>'
                % (_esc(plan["plot_left"]), _esc(plan["plot_right"]), _esc(y), _esc(y))
            )

    parts.append(
        '<line class="axis" x1="%s" x2="%s" y1="%s" y2="%s"></line>'
        % (
            _esc(plan["plot_left"]),
            _esc(plan["plot_right"]),
            _esc(plan["plot_bottom"]),
            _esc(plan["plot_bottom"]),
        )
    )
    parts.append(
        '<line class="axis" x1="%s" x2="%s" y1="%s" y2="%s"></line>'
        % (
            _esc(plan["plot_left"]),
            _esc(plan["plot_left"]),
            _esc(plan["plot_top"]),
            _esc(plan["plot_bottom"]),
        )
    )

    parts.append('<polyline class="line" points="%s"></polyline>' % _esc(plan["polyline"]))
    for dot in plan["dots"]:
        parts.append(
            '<circle class="dot-%s" cx="%s" cy="%s" r="%s"></circle>'
            % (
                _esc(_flag_class(dot["flag"])),
                _esc(dot["cx"]),
                _esc(dot["cy"]),
                _esc(plan["dot_radius"]),
            )
        )

    parts.append(
        '<text class="axis-text" x="%s" y="%s">%s</text>'
        % (
            _esc(plan["plot_left"]),
            _esc(plan["plot_bottom"]),
            _esc(chart.format_coord(plan["domain_low"])),
        )
    )
    parts.append(
        '<text class="axis-text" x="%s" y="%s">%s</text>'
        % (
            _esc(plan["plot_left"]),
            _esc(plan["plot_top"]),
            _esc(chart.format_coord(plan["domain_high"])),
        )
    )
    parts.append("</svg>")
    return "".join(parts)


def _chart_meta(plan: Dict) -> str:
    """图下的**事实**说明：起止、最新值、自身历史分位、所用区间。"""
    low = _display_bound(plan["range_low"])
    high = _display_bound(plan["range_high"])
    percentile = plan["percentile_text"]
    if percentile:
        percentile_text = "自身历史分位 %s" % percentile
    else:
        percentile_text = "自身历史分位：无历史可比"
    return "起 %s（%s）→ 止 %s（%s）· %s · 区间 %s ~ %s（%s）" % (
        _esc(plan["first_date"]),
        _esc(plan["first_value"]),
        _esc(plan["latest_date"]),
        _esc(plan["latest_value"]),
        _esc(percentile_text),
        _esc(low),
        _esc(high),
        _esc(_source_label(plan.get("range_source", ""))),
    )


def render_trends(series_list: Sequence[Dict], *, subject: str = "", title: str = "") -> str:
    """渲染多指标趋势报告（**纯装配**：坐标与分位由 `chart` 算好，判定态原样透传）。

    每项 `series` 为：
    `{"canonical_name", "unit", "flag", "range_source", "points": [{"date","value","flag",
    "range_low","range_high"}, ...]}`（points 按日期升序）。

    `flag` 与 `points[*].flag` 都是**既有判定结果**，本层不重算；缺区间的指标
    画不出区间带（`band` 为 None），如实留白——不补一条"看起来正常"的带。
    """
    sections: List[str] = []
    for series in series_list:
        plan = chart.build_series_plan(series["points"])
        plan["range_source"] = series.get("range_source", "")
        sections.append(
            "<h2>%s（%s）%s</h2>"
            % (
                _esc(series["canonical_name"]),
                _esc(series.get("unit", "")),
                _esc(_flag_label(series.get("flag", ""))),
            )
        )
        sections.append(
            '<div class="chart">%s<div class="meta">%s</div></div>'
            % (_chart_svg(plan), _chart_meta(plan))
        )

    if not sections:
        body = '<p class="empty">台账里还没有这个主体的记录。</p>'
    else:
        body = "".join(sections)

    document = _document(title or "纵向趋势报告", subject, body)
    assert_no_external_resources(document)
    assert_no_advisory_wording(document)
    return document


def _document(head_title: str, subject: str, body: str) -> str:
    subject_line = ("对象：%s" % subject) if subject else "对象：<未指定>"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>%s</title><style>%s</style></head><body>"
        "<h1>%s</h1>"
        '<div class="sub">%s · 判定为机械比较结果（H/L），不构成诊断依据</div>'
        "%s"
        '<div class="disclaimer">%s</div>'
        "</body></html>\n"
    ) % (
        _esc(head_title),
        _STYLE % {"line_stroke": chart.LINE_STROKE},
        _esc(head_title),
        _esc(subject_line),
        body,
        _esc(DISCLAIMER),
    )


# ---------------------------------------------------------------- 写盘


def render_to_file(judged: List[Judged], out_path, *, subject: str = "", title: str = "") -> str:
    """渲染判定表并原子写盘（经 serialize 单点）。返回写出的绝对路径。"""
    from checkup_ledger.serialize import write_atomic

    document = render_measurements(judged, subject=subject, title=title)
    write_atomic(out_path, document)
    return os.path.abspath(os.fspath(out_path))


def render_trends_to_file(
    series_list: Sequence[Dict], out_path, *, subject: str = "", title: str = ""
) -> str:
    """渲染趋势报告并原子写盘。返回写出的绝对路径。"""
    from checkup_ledger.serialize import write_atomic

    document = render_trends(series_list, subject=subject, title=title)
    write_atomic(out_path, document)
    return os.path.abspath(os.fspath(out_path))
