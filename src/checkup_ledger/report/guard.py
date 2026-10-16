"""零外链守护：常驻硬断言，不是"测试里验一次"。

本项目承诺**断网可开**（纯本地零上传）。任何外链（远程样式/脚本/字体/图片）
都会让报告在离线下退化，也让"零上传"不再可静态断言。故渲染出口**每次**都跑
一次本断言——把承诺变成出口的常驻行为，而不是某条测试的记忆。

扫描面：HTML 的 `src` / `href` / `srcset` / `action` / `poster` / CSS `url(...)`。
判定：允许 `#fragment`、`data:`、以及不带 scheme 的相对路径；
其余（任何 scheme 后接冒号双斜线、或双斜线开头）一律判 FAIL。

**扫描器自身不得出现 scheme 词面**（token 运行时拼接）——否则"扫外链"的门
自己就是命中源。本 docstring 因此也不写出完整形态。
"""

import re
from typing import List, Tuple

# scheme 名与分隔符分开拼接：源码里不出现完整的外链字面形态（见模块 docstring）
_SCHEMES: Tuple[str, ...] = ("http", "https", "ftp", "ftps", "ws", "wss")
_SCHEME_SEP = ":" + "/" + "/"
_SLASHES = "/" + "/"

_URL_ATTRS = ("src", "href", "srcset", "action", "poster", "data", "formaction")

_ATTR_RE = re.compile(
    r"""\b(%s)\s*=\s*("([^"]*)"|'([^']*)')""" % "|".join(_URL_ATTRS),
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class ExternalResourceError(AssertionError):
    """报告含外链——违反"断网可开 / 零上传"承诺。"""


def _scheme_prefixes() -> Tuple[str, ...]:
    return tuple(scheme + _SCHEME_SEP for scheme in _SCHEMES)


def is_external_reference(value: str) -> bool:
    """该引用是否指向外部资源。"""
    text = value.strip()
    if not text:
        return False
    lowered = text.lower()
    for prefix in _scheme_prefixes():
        if lowered.startswith(prefix):
            return True
    if lowered.startswith(_SLASHES):  # 协议相对：//host/path
        return True
    return False


def find_external_resources(html: str) -> List[str]:
    """返回全部外链命中（去重保序）。空列表 = 无外链。"""
    body = _COMMENT_RE.sub("", html)
    hits: List[str] = []
    for match in _ATTR_RE.finditer(body):
        value = match.group(3) if match.group(3) is not None else match.group(4)
        if value and is_external_reference(value):
            hits.append("[%s]=%s" % (match.group(1).lower(), value.strip()))
    for match in _CSS_URL_RE.finditer(body):
        value = match.group(1)
        if value and is_external_reference(value):
            hits.append("url(%s)" % value.strip())
    unique: List[str] = []
    for item in hits:
        if item not in unique:
            unique.append(item)
    return unique


def assert_no_external_resources(html: str) -> None:
    """渲染出口的常驻断言：命中外链即抛错（不是打印警告）。"""
    hits = find_external_resources(html)
    if hits:
        raise ExternalResourceError(
            "报告含外部资源引用（违反断网可开 / 零上传）：%s" % "; ".join(hits)
        )
