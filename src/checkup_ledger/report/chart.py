"""图元几何与自身历史分位：**纯计算**，不参与任何判定。

为什么把坐标换算与分位单设一个模块：渲染层要"零判定"，但画折线**必须**做算术
（归一化到画布坐标）与数值间的比较（求域上下界、数分位）。把这两件事挤进渲染
装配模块，就只能靠"别再写比较"这句口头纪律来守——而它守不住（坐标换算本身
就需要比较）。

故这里把**计算**与**装配**分开：
- 本模块（`chart.py`）**只算坐标与分位**：拿到的全是裸数字，**永远看不到判定标记**
  （不出现 `FLAG_*`）、**看不到区间与数值的比较**（不出现"值 vs 上下限"这类比较式），
  也不 import 判定内核；
- 装配模块（`html.py` / `trend.py`）**只拼接**：不做算术、不做比较，只把既有结论
  与算好的坐标摆进模板。

分界线的判据是**语义**而非"有没有运算符"：求域上下界是数值之间的比较（图元本职），
而"这个值是否越界"是判定（模块③ 的本职）。前者留在本模块，后者一律不许出现。

本模块不读文件、不读时钟、不联网。
"""

from typing import List, Optional, Sequence, Tuple

# 画布与留白（**避开知识库区间数值**：这些常量若与某个区间端点同值，零字面量
# 门禁会（正确地）把本文件判成"区间数值的第二处定义"，故取值刻意避开那 31 个 token）
WIDTH = 760
HEIGHT = 240
PAD_LEFT = 52
PAD_RIGHT = 16
PAD_TOP = 18
PAD_BOTTOM = 36

DOT_RADIUS = 3.2
LINE_STROKE = 1.6
BAND_OPACITY = 0.18
DOMAIN_PAD_RATIO = 0.05
MIN_SPAN = 1.0
DECIMALS = 2


class ChartError(ValueError):
    """图元参数非法（空序列、域退化、坐标不可算）。"""


def _finite(value) -> bool:
    """该值是否为可画的有限数（`None`/布尔/NaN 一律排除）。"""
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in (float("inf"), float("-inf"))


def plot_domain(
    values: Sequence,
    band_low: Optional[float] = None,
    band_high: Optional[float] = None,
) -> Tuple[float, float]:
    """折线的值域（下界, 上界）——**含参考区间端点**，故区间带必然落在画布内。

    域退化（全部点同值）时向两侧各撑开 `MIN_SPAN` 的一半：否则除零，或把折线压成
    一条贴着边框的线（"看起来像没有数据"）。
    """
    numbers: List[float] = [float(value) for value in values if _finite(value)]
    for bound in (band_low, band_high):
        if _finite(bound):
            numbers.append(float(bound))
    if not numbers:
        raise ChartError("折线没有任何可画的数值（空序列或全为非数值）")

    low = min(numbers)
    high = max(numbers)
    if high == low:
        low = low - MIN_SPAN / 2
        high = high + MIN_SPAN / 2
        return (low, high)

    pad = (high - low) * DOMAIN_PAD_RATIO
    return (low - pad, high + pad)


def scale_x(index: int, count: int) -> float:
    """第 `index` 个点（共 `count` 个）的横坐标。单点居左（不居中以省 x 轴留白）。"""
    if count <= 0:
        raise ChartError("点数必须为正")
    if index < 0 or index >= count:
        raise ChartError("点下标越界：%d / %d" % (index, count))
    if count == 1:
        return float(PAD_LEFT)
    usable = float(WIDTH - PAD_LEFT - PAD_RIGHT)
    return PAD_LEFT + usable * index / (count - 1)


def scale_y(value: float, domain_low: float, domain_high: float) -> float:
    """数值 → 纵坐标（画布坐标 y 轴向下，故上界映射到小 y）。"""
    if domain_high == domain_low:
        raise ChartError("值域退化为一点，无法换算纵坐标")
    usable = float(HEIGHT - PAD_TOP - PAD_BOTTOM)
    ratio = (float(value) - float(domain_low)) / (float(domain_high) - float(domain_low))
    return PAD_TOP + usable * (1.0 - ratio)


def format_coord(value: float) -> str:
    """坐标的展示写法：定小数位、去掉多余的尾零（SVG 里短坐标更易读）。"""
    text = ("%%.%df" % DECIMALS) % float(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_percentile(ratio: Optional[float]) -> str:
    """分位的展示写法（百分比）。`None` → 空串（"无历史可比"不是"0%"）。"""
    if ratio is None:
        return ""
    return "%s%%" % format_coord(float(ratio) * 100.0)



def percentile_rank(values: Sequence, current) -> Optional[float]:
    """`current` 在 `values` 中的**自身历史分位**（落在 [0, 1] 的比例）。

    口径：分位 = 不超过当前值的点数 / 总点数（含当前值本身）。这是"自身历史里的
    相对位置"这一**事实**，与参考区间无关——本函数**看不到**任何区间端点，
    故它不可能被误用成 H/L 判定。

    **至少要有两个观测**才算得出分位：单点序列里"分位 = 100%"在算术上成立，
    但它会让人读成"处在历史最高位"——而那次根本没有历史可比。这是与"拒判 ≠ 正常"
    同族的纪律：**没有可比对象时如实说没有，不给出一个看起来有信息量的数字**。
    故观测数 < 2、序列为空、或当前值非数 → `None`（**不填 0，也不填 100%**）。
    """
    numbers = [float(value) for value in values if _finite(value)]
    if len(numbers) < 2 or not _finite(current):
        return None
    target = float(current)
    at_or_below = 0
    for number in numbers:
        if number <= target:
            at_or_below += 1
    return at_or_below / len(numbers)


# ---------------------------------------------------------------- 图元计划（装配层只消费，不再算）


def build_series_plan(points: Sequence[dict]) -> dict:
    """把一条指标的序列算成**图元计划**（坐标全部算好、格式化成字符串）。

    装配层（`html.py`）拿到本函数的返回值后**只拼接**——不做算术、不做比较。
    这正是"渲染层零判定"能落成静态断言的原因：算术与比较留在本模块，
    而本模块**看不到**判定态（不出现 `FLAG_*`）、也**不做**"值 vs 区间"的比较。

    `points` 每条为 `{"date", "value", "flag", "range_low", "range_high"}`：
    序列按日期升序（由台账读出时已排好，本函数不重排——重排就得比日期，
    而"哪条更早"是事实，交给取数层）。

    返回值：
    - `dots`：每个点的 `{"cx", "cy", "flag"}`（坐标字符串）；
    - `polyline`：折线点串；
    - `band`：参考区间带的 `{"y", "height"}` 或 `None`（无区间 → 不画带）；
    - `percentile`：最新值在自身历史中的分位（`None` = 无可比历史）；
    - `latest_value` / `latest_date` / `first_value` / `first_date`；
    - `range_low` / `range_high`：**最新一条**所用的区间端点（原样透传，不重算）。
    """
    if not points:
        raise ChartError("序列为空，无法构建图元计划")

    values = [point.get("value") for point in points]
    latest = points[-1]
    first = points[0]

    band_low = latest.get("range_low")
    band_high = latest.get("range_high")
    has_band = _finite(band_low) or _finite(band_high)

    domain_low, domain_high = plot_domain(
        values,
        band_low if has_band else None,
        band_high if has_band else None,
    )

    count = len(points)
    dots = []
    coords = []
    for index, point in enumerate(points):
        x = scale_x(index, count)
        y = scale_y(float(point["value"]), domain_low, domain_high)
        coords.append("%s,%s" % (format_coord(x), format_coord(y)))
        dots.append(
            {
                "cx": format_coord(x),
                "cy": format_coord(y),
                "flag": point.get("flag", ""),
            }
        )

    band = None
    if has_band:
        low = float(band_low) if _finite(band_low) else domain_low
        high = float(band_high) if _finite(band_high) else domain_high
        y_top = scale_y(high, domain_low, domain_high)
        y_bottom = scale_y(low, domain_low, domain_high)
        band = {
            "x": format_coord(float(PAD_LEFT)),
            "y": format_coord(y_top),
            "width": format_coord(float(WIDTH - PAD_LEFT - PAD_RIGHT)),
            "height": format_coord(y_bottom - y_top),
        }

    return {
        "dots": dots,
        "polyline": " ".join(coords),
        "band": band,
        "percentile": percentile_rank(values, latest.get("value")),
        "percentile_text": format_percentile(percentile_rank(values, latest.get("value"))),
        "latest_value": latest.get("value"),
        "latest_date": latest.get("date", ""),
        "first_value": first.get("value"),
        "first_date": first.get("date", ""),
        "range_low": band_low,
        "range_high": band_high,
        "domain_low": domain_low,
        "domain_high": domain_high,
        # 画布几何（装配层直接取用，不再自己做加减——否则减法会落进"零判定"扫描面）
        "width": WIDTH,
        "height": HEIGHT,
        "plot_top": PAD_TOP,
        "plot_bottom": HEIGHT - PAD_BOTTOM,
        "plot_left": PAD_LEFT,
        "plot_right": WIDTH - PAD_RIGHT,
        "dot_radius": DOT_RADIUS,
        "line_stroke": LINE_STROKE,
        "band_opacity": BAND_OPACITY,
    }


