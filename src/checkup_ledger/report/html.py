"""报告渲染：本地单文件 HTML。

分层纪律：本模块**只消费既有判定结果**，不重算任何比较、不含任何区间数值
（静态门禁守）。渲染出口常驻零外链断言。
"""

import html as html_mod
import os
from typing import List

from checkup_ledger.model import (
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_NOT_ASSESSED,
    RANGE_SOURCE_BUILTIN,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
    Judged,
)
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

_STYLE = """
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       margin: 0; padding: 2rem; color: #1f2933; background: #f7f9fc; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
.sub { color: #5a6672; font-size: .85rem; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; background: #fff; font-size: .9rem; }
th, td { border: 1px solid #dde3ea; padding: .45rem .6rem; text-align: left; }
th { background: #eef2f7; font-weight: 600; }
tr.not_assessed, tr.not-assessed { color: #6b7280; }
.disclaimer { margin-top: 1.5rem; padding: .8rem 1rem; background: #fff8e6;
              border: 1px solid #f0dca8; border-radius: 4px; font-size: .85rem; }
.empty { color: #5a6672; font-style: italic; }
"""


def _esc(text) -> str:
    return html_mod.escape(str(text), quote=True)


def _display_bound(bound):
    """区间边界的展示形式：缺值显示为占位符。纯展示，不做判定。"""
    return "\u2014" if bound is None else bound


def _flag_class(flag: str) -> str:
    return flag.replace("_", "-")


def render_measurements(judged: List[Judged], *, subject: str = "", title: str = "") -> str:
    """渲染判定表为完整单文件 HTML 字符串（不写盘；写盘由调用方经 serialize 完成）。"""
    rows = []
    for item in judged:
        m = item.measurement
        ref = item.range_used
        # 只做展示取空值，不做任何比较/计算——判定结果全部来自 item 既有字段。
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
                _esc(_SOURCE_LABEL.get(item.range_source, item.range_source)),
                _esc(_FLAG_LABEL.get(item.flag, item.flag)),
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

    head_title = title or "体检台账"
    subject_line = ("对象：%s" % subject) if subject else "对象：<未指定>"

    document = (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>%s</title><style>%s</style></head><body>"
        "<h1>%s</h1>"
        '<div class="sub">%s · 判定为机械比较结果（H/L），不构成诊断依据</div>'
        "%s"
        '<div class="disclaimer">本工具不做诊断、不做解读、不做分诊、不做治疗建议。'
        "表中标记仅为数值与区间的机械比较结果；各医疗机构应以本机构 LIS 打印区间为最终准绳，"
        "一切以报告单和医嘱为准。</div>"
        "</body></html>\n"
    ) % (_esc(head_title), _STYLE, _esc(head_title), _esc(subject_line), body)

    assert_no_external_resources(document)
    return document


def render_to_file(judged: List[Judged], out_path, *, subject: str = "", title: str = "") -> str:
    """渲染并原子写盘（经 serialize 单点）。返回写出的绝对路径。"""
    from checkup_ledger.serialize import write_atomic

    document = render_measurements(judged, subject=subject, title=title)
    write_atomic(out_path, document)
    return os.path.abspath(os.fspath(out_path))
