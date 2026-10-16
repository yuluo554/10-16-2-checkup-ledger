"""确定性 PDF 写出（纯 stdlib）。

为什么自写而不是引 reportlab：**报告夹具必须能位级重生成**（与 M1 生成器同一纪律）。
reportlab 的 PDF 里带创建时间戳与随机对象号，两次运行必然不同字节；自写的最小
PDF 写出器没有时间戳、对象号确定，`--check` 才能做"再生成逐字节一致"。

写出的是**文本层可读**的 PDF（用 `Tm`/`Tj` 定位），供 ingest 的 PDF 路径回归。
三种形态都能构造，对应 plan/03 模块① 的必防陷阱：
- `PLAIN`：整行一个 Tj（正常形态）；
- `PER_CHAR`：逐字符定位（伪空格陷阱：字间无空白字符）；
- `PADDED`：整行一个 Tj 但用大量空格补白（补白归一陷阱）。
"""

import io
from typing import List, Sequence, Tuple

PLAIN = "plain"
PER_CHAR = "per_char"
PADDED = "padded"

ALL_LAYOUTS = (PLAIN, PER_CHAR, PADDED)

# 字体度量：Helvetica 10pt 的平均字宽约 6 个 PDF 单位（写死为结构常数，非区间数值）
CHAR_WIDTH = 6.0
FONT_SIZE = 10
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_X = 72
MARGIN_Y = 800
LINE_STEP = 20
PAD_SPACES = 22


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _stream(payload: str) -> bytes:
    body = payload.encode("latin-1")
    return b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream"


def _content_for_lines(lines: Sequence[str], layout: str) -> str:
    """按形态生成页面内容流。`lines` 为自上而下的文本行。"""
    if layout not in ALL_LAYOUTS:
        raise ValueError("未知的 PDF 形态：%r（合法值：%s）" % (layout, ", ".join(ALL_LAYOUTS)))

    commands: List[str] = []
    for index, line in enumerate(lines):
        y = MARGIN_Y - index * LINE_STEP
        if layout == PER_CHAR:
            x = float(MARGIN_X)
            for char in line:
                if char == " ":
                    x += CHAR_WIDTH
                    continue
                commands.append(
                    "BT /F1 %d Tf 1 0 0 1 %g %g Tm (%s) Tj ET" % (FONT_SIZE, x, y, _escape(char))
                )
                x += CHAR_WIDTH
        elif layout == PADDED:
            # 用空格把各字段推到固定列（补白陷阱：行内出现长空白串）
            parts = line.split(" ")
            padded = (" " * PAD_SPACES).join(parts)
            commands.append(
                "BT /F1 %d Tf 1 0 0 1 %d %d Tm (%s) Tj ET"
                % (FONT_SIZE, MARGIN_X, y, _escape(padded))
            )
        else:
            commands.append(
                "BT /F1 %d Tf 1 0 0 1 %d %d Tm (%s) Tj ET"
                % (FONT_SIZE, MARGIN_X, y, _escape(line))
            )
    return "\n".join(commands)


def build_pdf(pages: Sequence[Sequence[Tuple[str, str]]]) -> bytes:
    """构造 PDF 字节。

    `pages`：每页为 `[(layout, line_text), ...]` 序列——同一份 PDF 里可混多种形态
    （真实报告常是"表头正常 + 明细逐字定位"的混合体）。
    """
    objects: List[bytes] = []

    def add(body) -> int:
        objects.append(body if isinstance(body, bytes) else body.encode("latin-1"))
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: List[int] = []
    content_ids: List[int] = []
    for page in pages:
        grouped: List[Tuple[str, List[str]]] = []
        for layout, text in page:
            if grouped and grouped[-1][0] == layout:
                grouped[-1][1].append(text)
            else:
                grouped.append((layout, [text]))
        stream_parts = [_content_for_lines(texts, layout) for layout, texts in grouped]
        content_ids.append(add(_stream("\n".join(part for part in stream_parts if part))))
        page_ids.append(add(b"PAGE_PLACEHOLDER"))

    pages_id = add(b"PAGES_PLACEHOLDER")
    catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    objects[pages_id - 1] = (
        "<< /Type /Pages /Kids [%s] /Count %d >>"
        % (" ".join("%d 0 R" % pid for pid in page_ids), len(page_ids))
    ).encode("latin-1")
    for index, pid in enumerate(page_ids):
        objects[pid - 1] = (
            "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
            "/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_id, PAGE_WIDTH, PAGE_HEIGHT, font_id, content_ids[index])
        ).encode("latin-1")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number)
        out.write(body)
        out.write(b"\nendobj\n")
    xref_at = out.tell()
    count = len(objects) + 1
    out.write(b"xref\n0 %d\n" % count)
    out.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (count, catalog_id, xref_at)
    )
    return out.getvalue()
