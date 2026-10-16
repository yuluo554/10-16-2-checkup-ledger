"""stdio 编码守卫。

为什么需要：本机习惯用 `py -X utf8` 跑命令，那**只改我们敲的那条命令**的 stdio；
用户直接跑 `checkup-ledger`、以及 CI 管道（cp1252）都不受它影响，中文输出会
`UnicodeEncodeError`。故入口按**探针**决定是否 reconfigure：

- 探针可用 `stream.encoding` 试编码一个汉字；
- 编得动（utf-8 / cp936 / gbk / big5 …）→ 保持不动（中文控制台不该被硬改）；
- 编不动（cp1252 / ascii / latin-1 …）→ reconfigure 成 utf-8。
"""

import sys
from typing import Optional

_PROBE = "\u4e2d"  # 汉字"中"
_STREAMS = ("stdout", "stderr")


def _can_encode(encoding: Optional[str], text: str = _PROBE) -> bool:
    """该编码能否表示中文探测字。编码名本身无效/不存在也算编不动。"""
    if not encoding:
        return False
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError, TypeError, ValueError):
        return False
    return True


def ensure_utf8_stdio() -> None:
    """入口调用一次。幂等，可重复调用。"""
    for name in _STREAMS:
        stream = getattr(sys, name, None)
        if stream is None or getattr(stream, "closed", False):
            continue
        if _can_encode(getattr(stream, "encoding", None)):
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # 非 TextIOWrapper（如测试桩）——无法 reconfigure，交由调用方处理。
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue
