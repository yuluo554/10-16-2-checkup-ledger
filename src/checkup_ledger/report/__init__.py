"""报告渲染层：本地单文件 HTML（判定表 + 单指标折线 + 自身历史分位 + 参考区间带）。

三层分工（`plan/02` 的"计算/装配分离"）：
- `chart.py`——**图元计算**：坐标换算、值域、分位。看不到判定态、不 import 判定内核；
- `trend.py`——**序列装配**：台账行 → 渲染层可消费的 `series`（分组 + 取数，不重排不重算）；
- `html.py`——**拼接**：只把既有结论与算好的坐标摆进模板（无算术、无比较）。

对外入口：
- `render_html(ledger, *, out, subject)`：**从台账直接出报告**（`plan/03` 模块④ 的接口）；
- `render_measurements(...)`：只渲染判定表（不涉台账）；
- `render_trends(...)` / `render_trends_to_file(...)`：渲染已装配的 series 列表。
"""

import os
from typing import List, Optional

from checkup_ledger.model import Judged
from checkup_ledger.report.guard import (  # noqa: F401  (零外链守卫在此重导出，渲染出口的常驻断言)
    ExternalResourceError,
    assert_no_external_resources,
    find_external_resources,
)
from checkup_ledger.report.html import (
    render_measurements,
    render_trends,
    render_trends_to_file,
    render_to_file,
)
from checkup_ledger.report.trend import series_from_rows

__all__ = [
    "ExternalResourceError",
    "assert_no_external_resources",
    "find_external_resources",
    "render_html",
    "render_measurements",
    "render_to_file",
    "render_trends",
    "render_trends_to_file",
    "series_from_rows",
]


def render_html(
    ledger,
    *,
    out,
    subject: str = "default",
    judged: Optional[List[Judged]] = None,
    title: str = "",
) -> str:
    """从台账出**单指标折线报告**（`plan/03` 模块④ 的对外接口）。

    行为：
    - 台账里有该主体的记录 → 渲染趋势报告（每指标一张折线 + 分位 + 区间带）；
    - 台账为空但调用方传了 `judged` → 退回渲染**判定表**（没有历史就没有折线——
      不伪造一条单点"趋势"）；两者都空 → 仍渲染一份空报告（附免责，不报错）。
    - 写盘经 `serialize` 单点；出口常驻零外链与词根断言（在 `html` 层）。

    返回写出的绝对路径。
    """
    from checkup_ledger.ledger import rows_for

    rows = rows_for(ledger, subject=subject)
    series_list = series_from_rows(rows)
    if series_list:
        return render_trends_to_file(series_list, out, subject=subject, title=title)

    fallback = judged or []
    return render_to_file(fallback, out, subject=subject, title=title)


def render_html_for_rows(
    rows, *, out, subject: str = "default", title: str = "", judged=None
) -> str:
    """同 `render_html`，但取数由调用方给（已在内存里的台账行）。

    为什么留这个口：测试与基准可以不经真实库就验渲染（注入行夹具），
    而不必为了"验一张折线"去建一个 SQLite 库。
    """
    series_list = series_from_rows(rows)
    if series_list:
        return render_trends_to_file(series_list, out, subject=subject, title=title)
    return render_to_file(judged or [], out, subject=subject, title=title)


def output_path_for(source_path, *, suffix: str = ".report.html", directory: Optional[str] = None) -> str:
    """按源文件名派生产物路径（CLI 缺省 `--out` 时用）。"""
    stem = os.path.splitext(os.path.basename(os.fspath(source_path)))[0]
    base = directory if directory is not None else os.getcwd()
    return os.path.join(base, "%s%s" % (stem, suffix))
