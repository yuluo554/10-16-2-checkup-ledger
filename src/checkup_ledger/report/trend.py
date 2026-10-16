"""趋势序列装配：台账行 → 渲染层可消费的 `series` 结构（**取数与分组**，不做判定）。

为什么单设一个模块（而不是让 CLI 自己拼）："哪个点是哪个指标的、按什么序排、
用哪一条的区间画带"是**取数口径**。CLI、导出、渲染三处若各自分组，早晚一处按
日期升序、另一处按插入序——折线上的点会前后颠倒而**没有任何测试会红**。

本模块只做：
- 从台账读回该主体全部行（`ledger.rows_for` 已按日期、指标升序排好）；
- 按 `canonical_name` 分组（分组键序 = 指标名字典序，不用 set 迭代序）；
- 每组的区间端点取**最新一条**（区间可能随机构变，画带用最近一次的）；
- 每个点的 `flag` **原样透传**（判定由模块③ 做过，本模块不重算）。

**本模块不做任何数值比较**：分组与排序都由取数层（SQL 的 ORDER BY）保证。
"""

from typing import Dict, List, Sequence

from checkup_ledger.ledger.errors import LedgerError

_FLAG_KEYS = ("date", "value", "flag", "range_low", "range_high", "range_source", "unit")


def series_from_rows(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    """把台账行（按日期升序）装配成渲染层要的 `series` 列表。

    `rows` 必须已按 `date` 升序（`ledger.rows_for` 的 ORDER BY 保证）。
    本函数**不重排**——重排就得比日期，而"哪条更早"是取数层的事实。
    """
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        name = row.get("canonical_name")
        if not isinstance(name, str) or not name.strip():
            raise LedgerError("台账行缺 canonical_name（库内容非法）")
        grouped.setdefault(name, []).append(row)

    series_list: List[Dict[str, object]] = []
    for name in sorted(grouped):  # 指标名字典序（不用 set 迭代序）
        points = grouped[name]
        latest = points[-1]
        series_list.append(
            {
                "canonical_name": name,
                "unit": latest.get("unit", ""),
                "flag": latest.get("flag", ""),
                "range_source": latest.get("range_source", ""),
                "points": [_point(point) for point in points],
            }
        )
    return series_list


def _point(row: Dict[str, object]) -> Dict[str, object]:
    return {key: row.get(key) for key in _FLAG_KEYS if key in row or key in ("date", "value", "flag")}
