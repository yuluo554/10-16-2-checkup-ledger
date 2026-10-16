"""行装配：把"字符 / 碎片"序列归约成行级草稿（模块① 的抽取内核）。

三类常见陷阱在这里一次性处理，调用方不重复实现：

1. **伪空格**（PDF 逐字定位导出）：行内没有空白字符，字间靠坐标跳位。若按"像素间隙"
   插空格，会把窄字形拆开（pdfplumber 原生 `extract_text` 实测会把 `U/` `L` 拆成
   `U/ L`）。本模块规则：**优先认真实空白字符**；整行无空白字符时改用**步进**
   （相邻字符 x0 之差）判空格——真实空格处的步进约为字宽的两倍，而字形宽窄造成的
   抖动远小于此，故阈值取 `步进 > 1.5 × 行内中位步进`。
2. **补白对齐**：整行用大量空格排版 → 行内空白串归一为单空格。
3. **紧贴两行本属同一逻辑行** → 按 y 邻近聚类后再拼（容差取行高中位数的一个比例）。

本模块**不做任何数值语义判断**：只产出文本与位置，不做解析。
"""

import re
from typing import List, Sequence

from checkup_ledger.model import RawLine

# 几何比例（不是临床阈值；取"非区间数值"的值，以免与零字面量门禁的 token 集相撞）
Y_TOLERANCE_RATIO = 0.6
# 空格判定：间隙 > 比例 × 字符均宽 时插空格。
# 实测（plan/00 的 M2 实测证据节）：逐字定位的 PDF 上，相邻字符间隙呈**双峰**——
# 词内是字形间距（很窄；个别窄字形对如斜杠与 L 挨得宽些），词间是"一个空格宽"
# （明显更宽）。字符均宽落在两峰之间偏上，故比例取 0.75 能干净分开，两侧都留有余量。
SPACE_ADVANCE_RATIO = 0.75
TEXT_LAYER_CONFIDENCE = 1.0

SPACE_POLICY_ADVANCE = "advance"  # 逐字符定位（PDF 文本层）：按步进判空格
SPACE_POLICY_ALWAYS = "always"    # OCR 列框：每个框是一个词，框间一律单空格

ALL_SPACE_POLICIES = (SPACE_POLICY_ADVANCE, SPACE_POLICY_ALWAYS)

_WS_RUN = re.compile(r"\s+")


class Fragment:
    """抽取层的原子单元：一段文本 + 包围盒 + 置信度。

    PDF 文本层的**字符**与 OCR 的**行框**都归约成它，后续只有一套装配逻辑
    （两套装配 = 陷阱只在其中一条路径上被处理，另一条静默漏）。
    """

    __slots__ = ("text", "x0", "x1", "top", "bottom", "score")

    def __init__(self, text, x0, x1, top, bottom, score=TEXT_LAYER_CONFIDENCE):
        self.text = text
        self.x0 = float(x0)
        self.x1 = float(x1)
        self.top = float(top)
        self.bottom = float(bottom)
        self.score = float(score)

    @property
    def vcenter(self) -> float:
        """垂直中心（`top` 自页顶向下增大，故中心取上下均值）。"""
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def __repr__(self) -> str:  # pragma: no cover - 调试便利
        return "Fragment(%r, x0=%g, top=%g)" % (self.text, self.x0, self.top)


def chars_to_fragments(chars: Sequence[dict]) -> List[Fragment]:
    """PDF 文本层字符 → 碎片。**空白字符照收**：它是真实空格的证据，不能在装配前丢掉。"""
    out = []
    for char in chars:
        text = char.get("text")
        if text is None:
            continue
        out.append(
            Fragment(text, char["x0"], char["x1"], char["top"], char["bottom"], TEXT_LAYER_CONFIDENCE)
        )
    return out


def boxes_to_fragments(boxes: Sequence[tuple]) -> List[Fragment]:
    """OCR 输出 → 碎片。每个 box 为四点（左上/右上/右下/左下），取其包围盒。"""
    out = []
    for box, text, score in boxes:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        out.append(Fragment(text, min(xs), max(xs), min(ys), max(ys), float(score)))
    return out


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def cluster_by_line(fragments: Sequence[Fragment], tolerance_ratio: float = Y_TOLERANCE_RATIO) -> List[List[Fragment]]:
    """按 y 邻近聚类成行。容差 = 行高中位数 × 比例（**从数据实算，不写死像素容差**）。

    跨行数值/区间（同一逻辑行被挤成上下两截）在这里合回一行。
    """
    if not fragments:
        return []
    ordered = sorted(fragments, key=lambda item: (item.vcenter, item.x0))
    tolerance = _median([item.height for item in fragments if item.height > 0]) * tolerance_ratio

    clusters: List[List[Fragment]] = []
    anchor = None
    for fragment in ordered:
        if clusters and anchor is not None and abs(fragment.vcenter - anchor) <= tolerance:
            clusters[-1].append(fragment)
        else:
            clusters.append([fragment])
            anchor = fragment.vcenter
    return clusters


def _join_fragments(items: Sequence[Fragment], space_policy: str) -> str:
    """把一行的碎片拼成文本（按策略处理空格）。"""
    if space_policy not in ALL_SPACE_POLICIES:
        raise ValueError("未知的空格策略：%r（合法值：%s）" % (space_policy, ", ".join(ALL_SPACE_POLICIES)))

    ordered = sorted(items, key=lambda item: item.x0)

    if space_policy == SPACE_POLICY_ALWAYS:
        return _WS_RUN.sub(" ", " ".join(item.text for item in ordered)).strip()

    # advance 策略：真实空白字符优先；无空白字符时才用几何判空格。
    #
    # 判据 = "间隙 > 比例 × 字符均宽"。字符均宽从**该行碎片实算**（不写死像素常数）。
    #
    # 为什么这个比例能干净分开（实测数据见 plan/00 的 M2 实测证据节）：
    # 逐字定位的 PDF 上，同一行内相邻字符的间隙呈**双峰**——词内是字形间距（很窄），
    # 词间是"一个空格宽"（明显更宽）；字符均宽落在两峰之间偏上，故比例取 0.75
    # 落在两峰之间，两侧都有余量。
    #
    # 为什么不用"间隙排序找跳变"：间隙排序后最小的跳变出现在字形抖动的量级上
    # （不是词内/词间的分界），按最大比值取分界会把分界划得很低，于是每个字符之间都插空格
    # ——实测把 `ALT` 拆成 `A L T`。均宽基准不受个别抖动支配。
    solid = [item for item in ordered if item.text.strip()]
    widths = [(item.x1 - item.x0) / float(len(item.text.strip())) for item in solid if item.x1 > item.x0]
    threshold = SPACE_ADVANCE_RATIO * _median(widths) if widths else 0.0

    pieces: List[str] = []
    previous = None
    for fragment in ordered:
        if not fragment.text.strip():
            pieces.append(" ")
            continue
        if previous is not None and threshold > 0 and (fragment.x0 - previous.x1) > threshold:
            pieces.append(" ")
        pieces.append(fragment.text)
        previous = fragment
    return _WS_RUN.sub(" ", "".join(pieces)).strip()


def assemble_lines(
    fragments: Sequence[Fragment],
    *,
    page: int,
    source_file: str,
    line_no_start: int = 1,
    space_policy: str = SPACE_POLICY_ADVANCE,
) -> List[RawLine]:
    """碎片序列 → 行级草稿。

    行的置信度取该行**最弱碎片**的分值（保守：一行里有一截没认准，整行都该复核）。
    """
    lines: List[RawLine] = []
    for offset, cluster in enumerate(cluster_by_line(fragments)):
        text = _join_fragments(cluster, space_policy)
        if not text:
            continue
        confidence = min(item.score for item in cluster)
        lines.append(
            RawLine(
                page=page,
                line_no=line_no_start + len(lines),
                text=text,
                confidence=confidence,
                source_file=source_file,
            )
        )
    return lines
