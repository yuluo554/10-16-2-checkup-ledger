"""确定性扫描件渲染（纯 stdlib）：笔画字体 → 灰阶 PNG。

为什么自写渲染器而不是 Pillow：**扫描件夹具必须能位级重生成**。
实测 Pillow 10.4 与 12.3 渲染同一段文字得到的 PNG **字节不同**（抗锯齿实现随版本变），
那会让"再生成逐字节一致"的守门在升级 Pillow 时随机变红。本渲染器只用
`zlib` + `struct`，在 3.8 与 3.12 上实测**逐字节一致**。

字形用**笔画折线**（而非点阵块）：点阵块笔画过粗，OCR 识别率显著下降；
笔画折线 + 超采样降采样（抗锯齿）后，实测 RapidOCR 对样例每一格都能读准。

坐标盒：每字形 4 宽 × 6 高，`y` 向上为正，绘制时按 `GH - y` 翻转。
"""

import struct
import zlib
from typing import List, Sequence, Tuple

GW = 4.0
GH = 6.0

# 笔画字体（每个字形 = 若干条折线）。只覆盖合成报告用到的字符集。
STROKES = {
    "0": [[(1.4, 6.0), (2.6, 6.0), (3.5, 4.7), (3.5, 1.3), (2.6, 0.0), (1.4, 0.0), (0.5, 1.3), (0.5, 4.7), (1.4, 6.0)]],
    "1": [[(1.2, 4.7), (2.1, 6.0), (2.1, 0.0)], [(1.1, 0.0), (3.1, 0.0)]],
    "2": [[(0.6, 5.0), (1.2, 5.9), (2.8, 5.9), (3.6, 5.0), (3.6, 4.0), (0.5, 0.0), (3.6, 0.0)]],
    "3": [[(0.6, 5.0), (1.3, 5.9), (2.7, 5.9), (3.5, 5.0), (2.6, 3.6), (1.3, 3.5)],
          [(2.6, 3.6), (3.5, 2.3), (3.4, 1.1), (2.5, 0.1), (1.1, 0.1), (0.5, 0.9)]],
    "4": [[(2.9, 0.0), (2.9, 6.0)], [(2.9, 2.2), (0.4, 2.2), (2.6, 6.0)]],
    "5": [[(3.4, 5.9), (0.8, 5.9), (0.6, 3.3), (2.6, 3.5), (3.5, 2.4), (3.5, 1.2), (2.6, 0.2), (1.1, 0.1), (0.5, 0.8)]],
    "6": [[(3.3, 5.2), (2.4, 5.9), (1.3, 5.6), (0.6, 4.0), (0.5, 2.2), (0.9, 0.5), (2.0, 0.1), (3.2, 0.7), (3.4, 1.9), (2.7, 2.9), (1.4, 3.0), (0.6, 2.3)]],
    "7": [[(0.5, 5.9), (3.5, 5.9)], [(3.5, 5.9), (1.6, 0.0)]],
    "8": [[(1.9, 3.1), (1.0, 3.8), (1.0, 5.1), (1.9, 5.9), (2.9, 5.1), (2.9, 3.8), (1.9, 3.1)],
          [(1.9, 3.1), (0.9, 2.2), (0.6, 1.1), (1.3, 0.2), (2.6, 0.2), (3.4, 1.1), (3.1, 2.2), (1.9, 3.1)]],
    "9": [[(1.0, 5.9), (2.2, 5.9), (3.2, 4.8), (3.2, 3.4), (2.2, 2.3), (1.0, 2.3), (0.1, 3.4), (0.1, 4.8), (1.0, 5.9)],
          [(3.2, 3.0), (2.9, 0.0), (1.4, 0.0), (0.6, 0.5)]],
    "A": [[(0.2, 0.0), (1.7, 6.0), (2.3, 6.0), (3.8, 0.0)], [(0.8, 2.0), (3.2, 2.0)]],
    "B": [[(0.5, 0.0), (0.5, 6.0), (2.6, 6.0), (3.4, 5.2), (3.4, 3.9), (2.6, 3.1), (0.5, 3.1)],
          [(2.7, 3.1), (3.6, 2.2), (3.6, 0.8), (2.8, 0.0), (0.5, 0.0)]],
    "C": [[(3.6, 5.0), (2.7, 5.9), (1.3, 5.9), (0.5, 4.9), (0.5, 1.1), (1.3, 0.1), (2.7, 0.1), (3.6, 1.0)]],
    "D": [[(0.5, 0.0), (0.5, 6.0), (2.3, 6.0), (3.5, 4.9), (3.5, 1.1), (2.3, 0.0), (0.5, 0.0)]],
    "E": [[(3.5, 5.9), (0.5, 5.9), (0.5, 0.1), (3.5, 0.1)], [(0.5, 3.0), (2.8, 3.0)]],
    "F": [[(3.5, 5.9), (0.5, 5.9), (0.5, 0.1)], [(0.5, 3.0), (2.8, 3.0)]],
    "G": [[(3.6, 5.0), (2.7, 5.9), (1.3, 5.9), (0.5, 4.9), (0.5, 1.1), (1.3, 0.1), (2.7, 0.1), (3.6, 1.0), (3.6, 2.6), (2.4, 2.6)]],
    "H": [[(0.5, 0.0), (0.5, 6.0)], [(3.5, 0.0), (3.5, 6.0)], [(0.5, 3.0), (3.5, 3.0)]],
    "I": [[(1.0, 6.0), (3.0, 6.0)], [(2.0, 6.0), (2.0, 0.0)], [(1.0, 0.0), (3.0, 0.0)]],
    "J": [[(3.0, 6.0), (3.0, 1.0), (2.3, 0.1), (1.2, 0.1), (0.5, 1.0)]],
    "K": [[(0.5, 0.0), (0.5, 6.0)], [(3.5, 6.0), (0.6, 2.6)], [(1.6, 3.5), (3.6, 0.0)]],
    "L": [[(0.5, 6.0), (0.5, 0.1), (3.5, 0.1)]],
    "M": [[(0.4, 0.0), (0.4, 6.0), (2.0, 3.4), (3.6, 6.0), (3.6, 0.0)]],
    "N": [[(0.5, 0.0), (0.5, 6.0), (3.5, 0.0), (3.5, 6.0)]],
    "O": [[(1.3, 5.9), (2.7, 5.9), (3.6, 4.8), (3.6, 1.2), (2.7, 0.1), (1.3, 0.1), (0.4, 1.2), (0.4, 4.8), (1.3, 5.9)]],
    "P": [[(0.5, 0.0), (0.5, 6.0), (2.7, 6.0), (3.6, 5.1), (3.6, 3.9), (2.7, 3.0), (0.5, 3.0)]],
    "Q": [[(1.3, 5.9), (2.7, 5.9), (3.6, 4.8), (3.6, 1.2), (2.7, 0.1), (1.3, 0.1), (0.4, 1.2), (0.4, 4.8), (1.3, 5.9)],
          [(2.2, 1.6), (3.8, -0.3)]],
    "R": [[(0.5, 0.0), (0.5, 6.0), (2.7, 6.0), (3.6, 5.1), (3.6, 3.9), (2.7, 3.0), (0.5, 3.0)], [(1.9, 3.0), (3.6, 0.0)]],
    "S": [[(3.5, 5.1), (2.6, 5.9), (1.2, 5.9), (0.5, 5.0), (0.7, 3.9), (1.8, 3.3), (2.8, 3.1), (3.5, 2.2), (3.4, 0.9), (2.4, 0.1), (1.0, 0.1), (0.5, 0.9)]],
    "T": [[(0.3, 5.9), (3.7, 5.9)], [(2.0, 5.9), (2.0, 0.0)]],
    "U": [[(0.5, 6.0), (0.5, 1.2), (1.4, 0.1), (2.6, 0.1), (3.5, 1.2), (3.5, 6.0)]],
    "V": [[(0.3, 6.0), (2.0, 0.0), (3.7, 6.0)]],
    "W": [[(0.2, 6.0), (1.2, 0.0), (2.0, 4.0), (2.8, 0.0), (3.8, 6.0)]],
    "X": [[(0.4, 6.0), (3.6, 0.0)], [(3.6, 6.0), (0.4, 0.0)]],
    "Y": [[(0.4, 6.0), (2.0, 3.2), (3.6, 6.0)], [(2.0, 3.2), (2.0, 0.0)]],
    "Z": [[(0.4, 5.9), (3.6, 5.9), (0.4, 0.1), (3.6, 0.1)]],
    "a": [[(0.6, 4.2), (1.5, 4.5), (2.6, 4.2), (3.0, 3.2), (3.0, 0.0)],
          [(3.0, 3.4), (1.8, 4.5), (0.8, 4.2), (0.5, 3.2), (0.9, 2.4), (2.0, 2.2), (3.0, 1.8)],
          [(2.9, 0.9), (2.1, 0.1), (1.0, 0.1), (0.6, 0.9), (1.0, 1.7), (2.0, 1.9), (3.0, 1.8)]],
    "e": [[(0.6, 2.4), (3.0, 2.4), (3.1, 3.4), (2.4, 4.5), (1.2, 4.5), (0.5, 3.4), (0.5, 1.2), (1.3, 0.1), (2.5, 0.1), (3.1, 0.8)]],
    "i": [[(1.9, 4.5), (1.9, 0.0)], [(1.9, 5.6), (1.9, 5.9)]],
    "l": [[(1.9, 6.5), (1.9, 1.0), (2.5, 0.1)]],
    "m": [[(0.4, 0.0), (0.4, 4.5)],
          [(0.4, 3.6), (1.1, 4.6), (1.8, 3.6), (1.8, 0.0)],
          [(1.8, 3.6), (2.5, 4.6), (3.2, 3.6), (3.2, 0.0)]],
    "n": [[(0.4, 0.0), (0.4, 4.5)], [(0.4, 3.6), (1.2, 4.6), (2.3, 4.0), (2.3, 0.0)]],
    "o": [[(1.8, 4.5), (0.9, 4.1), (0.5, 3.0), (0.8, 1.3), (1.8, 0.1), (2.8, 1.0), (3.1, 2.4), (2.8, 3.9), (1.8, 4.5)]],
    "r": [[(0.5, 0.0), (0.5, 4.5)], [(0.5, 3.4), (1.4, 4.6), (2.5, 4.4)]],
    "s": [[(2.9, 3.6), (1.9, 4.5), (0.8, 4.3), (0.5, 3.5), (1.3, 2.9), (2.4, 2.7), (3.0, 1.9), (2.5, 0.8), (1.3, 0.2), (0.5, 0.9)]],
    "t": [[(1.6, 6.0), (1.6, 0.9), (2.3, 0.1), (3.1, 0.5)], [(0.7, 4.4), (2.8, 4.4)]],
    "u": [[(0.6, 4.5), (0.6, 1.2), (1.4, 0.1), (2.4, 0.1), (3.0, 1.2)], [(3.0, 4.5), (3.0, 0.0)]],
    "/": [[(0.6, -0.2), (3.4, 6.2)]],
    "^": [[(0.9, 3.5), (2.0, 5.7), (3.1, 3.5)]],
    "~": [[(0.4, 3.3), (1.2, 3.9), (2.2, 2.7), (3.0, 3.3), (3.6, 3.0)]],
    ".": [[(1.5, 0.0), (1.5, 0.9), (2.4, 0.9), (2.4, 0.0), (1.5, 0.0)]],
    "-": [[(0.5, 2.9), (3.5, 2.9)]],
    "<": [[(3.4, 5.9), (0.6, 2.9), (3.4, 0.0)]],
    ">": [[(0.6, 5.9), (3.4, 2.9), (0.6, 0.0)]],
    " ": [],
}

# 渲染参数（结构常数，非区间数值）。实测该组配置下 RapidOCR 对样例逐格读准。
DEFAULT_CHAR_PX = 34
DEFAULT_LINE_GAP = 40
DEFAULT_SUPERSAMPLE = 5
DEFAULT_STROKE_PX = 0.95
CHAR_STEP_RATIO = 1.35
COLUMN_GAP_CHARS = 2  # 列间空隙（以字符步进为单位）
MARGIN = 40

# 降质模式（构造低置信行）：像素被确定性噪声翻转的比例分子/分母。
# 阈值经实测选定：该强度下夹具**每一行**的 OCR 分值都落进阈值以下（见 plan/00 的
# M2 实测证据节）——这样才能给出"未复核行零落库"这种**决定性**断言，
# 而不是"有几行碰巧低了"。
NOISE_THRESHOLD = 6400
NOISE_MODULUS = 65536
NOISE_X_MULT = 73856093
NOISE_Y_MULT = 19349663


class MissingGlyphError(KeyError):
    """字形表缺该字符——**报错而非画出空白**（空白会让 OCR 结果无从解释）。"""


def column_origins(rows: Sequence[Sequence[str]], char_px: int = DEFAULT_CHAR_PX) -> List[float]:
    """按**各列最宽内容**实算列起点（像素）。

    为什么不能写死列坐标：列宽随内容变化（`10^9/L` 比 `U/L` 宽一倍），写死的
    列距会让长单位挤进下一列，OCR 于是把"单位 + 区间"读成一串（实测如此）。
    这里按内容宽度 + 固定间隙推列，与真实报告的列对齐同理。
    """
    step_x = char_px * CHAR_STEP_RATIO
    gap = COLUMN_GAP_CHARS * step_x
    max_cols = max(len(row) for row in rows)
    widths = []
    for col_index in range(max_cols):
        longest = max(len(row[col_index]) for row in rows if len(row) > col_index)
        widths.append(longest * step_x)
    origins = []
    cursor = float(MARGIN)
    for width in widths:
        origins.append(cursor)
        cursor += width + gap
    return origins


def render_columns(
    rows: Sequence[Sequence[str]],
    path,
    *,
    char_px: int = DEFAULT_CHAR_PX,
    line_gap: int = DEFAULT_LINE_GAP,
    supersample: int = DEFAULT_SUPERSAMPLE,
    stroke_px: float = DEFAULT_STROKE_PX,
    noise: bool = False,
) -> Tuple[int, int]:
    """把列布局文本渲染成灰阶 PNG 并写盘（**原子写 + 二进制，不做文本归一化**）。

    `rows`：每行为 `(项目名, 结果, 单位, 参考区间)` 之类的列文本序列。
    `noise=True`：叠加确定性噪声（构造低置信行用，**不用随机数**）。
    """
    step_x = char_px * CHAR_STEP_RATIO
    line_step = GH * char_px + line_gap
    column_x = column_origins(rows, char_px)
    max_cols = max(len(row) for row in rows)
    max_len = max(len(text) for row in rows for text in row)
    width = int(column_x[max_cols - 1] + max_len * step_x + MARGIN)
    height = int(MARGIN * 2 + len(rows) * line_step)
    hi_w, hi_h = width * supersample, height * supersample
    canvas = bytearray([255]) * (hi_w * hi_h)
    half_stroke = max(1, int(round(stroke_px * supersample / 2.0)))

    def dot(px: int, py: int) -> None:
        for dy in range(-half_stroke, half_stroke + 1):
            row_px = py + dy
            if not (0 <= row_px < hi_h):
                continue
            base = row_px * hi_w
            for dx in range(-half_stroke, half_stroke + 1):
                col_px = px + dx
                if 0 <= col_px < hi_w:
                    canvas[base + col_px] = 0

    def line(x0: float, y0: float, x1: float, y1: float) -> None:
        dx, dy = x1 - x0, y1 - y0
        steps = int(max(abs(dx), abs(dy))) + 1
        for index in range(steps + 1):
            t = index / float(steps) if steps else 0.0
            dot(int(round(x0 + dx * t)), int(round(y0 + dy * t)))

    for row_index, row in enumerate(rows):
        base_y = (MARGIN + row_index * line_step) * supersample
        for col_index, text in enumerate(row):
            origin_x = (MARGIN + column_x[col_index]) * supersample
            for char_index, char in enumerate(text):
                if char not in STROKES:
                    raise MissingGlyphError("字形表缺字符：%r（需要时请补进 STROKES）" % char)
                left = origin_x + char_index * step_x * supersample
                for polyline in STROKES[char]:
                    points = []
                    for nx, ny in polyline:
                        points.append(
                            (
                                left + nx / GW * char_px * supersample,
                                base_y + (GH - ny) / GH * char_px * supersample,
                            )
                        )
                    for index in range(len(points) - 1):
                        line(points[index][0], points[index][1], points[index + 1][0], points[index + 1][1])

    # 盒式降采样（抗锯齿）
    gray = bytearray(width * height)
    factor = supersample * supersample
    for py in range(height):
        for px in range(width):
            total = 0
            for sy in range(supersample):
                base = (py * supersample + sy) * hi_w + px * supersample
                for sx in range(supersample):
                    total += canvas[base + sx]
            gray[py * width + px] = total // factor

    if noise:
        _apply_noise(gray, width, height)

    _write_png(path, width, height, gray)
    return width, height


def _apply_noise(gray: bytearray, width: int, height: int) -> None:
    """确定性像素噪声：用坐标哈希（非 `random`）决定翻转位置。

    目的：**构造低置信行**——真实扫描件的退化不是均匀噪声，但本夹具只需
    "确定性 + 确实让 OCR 认不准"。用坐标哈希保证两次运行逐字节一致。
    """
    for y in range(height):
        base = y * width
        for x in range(width):
            value = gray[base + x]
            digest = ((x * NOISE_X_MULT) ^ (y * NOISE_Y_MULT)) % NOISE_MODULUS
            if digest >= NOISE_THRESHOLD:
                continue
            if value < 200:
                gray[base + x] = 255
            else:
                gray[base + x] = 0


def _write_png(path, width: int, height: int, gray: bytearray) -> None:
    """写 8 位灰度 PNG（zlib 压缩级别固定，保证逐字节可复现）。"""
    raw = b"".join(
        b"\x00" + bytes(gray[y * width:(y + 1) * width]) for y in range(height)
    )
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    _write_bytes_atomic(path, payload)


def _chunk(tag: bytes, payload: bytes) -> bytes:
    body = tag + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _write_bytes_atomic(path, payload: bytes) -> None:
    """二进制产物的原子写（与 serialize.write_atomic 同形态，但不做文本归一化）。"""
    import os
    import tempfile

    target = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(target))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
