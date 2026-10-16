"""报告行解析：文本 → 结构化字段（**纯函数**：不读文件、不读时钟、不联网）。

一行报告的形态差异很大，本模块只认**结构**、不认具体机构格式：

```
项目名称  结果  单位  参考区间
<项目名>  <数值>  <单位>  <下限> ~ <上限>
<项目名>  <数值>  <单位>  — ~ <上限>
<项目名>  <数值>  <单位>  （未印）
```

产物是**中间结构**（`ParsedLine`），**不做任何判定**：它不知道 H/L，也不知道区间
从哪里来（自印 or 默认是编排层的事）。它只回答四件事：指标名原文是什么、
数值是多少、单位原文是什么、参考区间列印了什么。

三条纪律：

1. **区间列"没印"与"印了但读不出"是两件事**：未印占位符归为"没印"
   （`printed=None`），而区间一侧写了非数字（如上限位置写了个词）归为
   `range_unparsed`（进待人工映射）。把后者也当"没印"，会让"报告印了区间但我们
   读不懂"静默退化成"报告没印区间"，判定结论跟着从"有区间"变成"拒判"——
   一条真实的读错被伪装成一条干净的拒判。
2. **数值抽不到就报 `value_unlocated`**，绝不填默认值（"没看到"与"看到了但没抽到"
   是两种结论，口径见 `plan/04` 第四节）。
3. **不猜指标名**：只认知识库里**登记过的**写法（含含空格写法），前缀不匹配就是
   `name_unmapped`。模糊匹配（编辑距离之类）在医学文本上会把两个形近缩写认成同一个。

**本文件的注释与 docstring 一律不写具体区间端点**——区间数值只能在知识库一处定义
（零字面量门禁扫全文，含注释；本模块自己也在扫描面内）。故示例一律用 `<下限>`
这类**指代**。
"""

import re
from typing import List, Optional, Sequence, Tuple

from checkup_ledger.model import RawLine
from checkup_ledger.normalize.errors import NormalizeError
from checkup_ledger.normalize.mapping import (
    REASON_NAME_UNMAPPED,
    REASON_RANGE_UNPARSED,
    REASON_UNIT_ABSENT,
    REASON_UNIT_UNMAPPED,
    REASON_VALUE_UNLOCATED,
    MeasurementDictionary,
    normalize_key,
    to_halfwidth,
)

# 尾部注记（导出文本常带"[置信度 0.96]"这类附注；它不是数据列，必须摘掉，
# 否则会被当成区间列的一部分而解析失败）
_ANNOTATION_RE = re.compile(r"\[[^\]]*\]")

# 数值写法：可带比较前缀（`<N` / `>N` / `≤N` / `≥N`），带千分位逗号
_NUMBER_RE = re.compile(r"^[<>≤≥]?\s*([-+]?\d+(?:,\d{3})*(?:\.\d+)?)$")

# 数值与单位**粘在一起**的写法（形如 `<数值><单位>`）：拆成数值前缀 + 单位余部。
# 不拆的话整段无法解析，会误报成"数值未定位"——而它其实是"数值有、单位也写了"。
_GLUED_RE = re.compile(r"^(?P<value>[-+]?\d+(?:\.\d+)?)(?P<unit>[A-Za-z%μµ].*)$")

# "未印区间"的几种写法：报告**自己声明**没印（不是"我们没读到"）
_NOT_PRINTED_RE = re.compile(r"^[（(]?(?:未印|未填|未测|未查|无)[）)]?$|^[—–\-~]+$")

# 区间分隔符（`<下限> ~ <上限>`；全角波浪号经半角归一后是同一个字符）
_RANGE_SEP_RE = re.compile(r"[~～]")

# 连字符式区间（`<下限>-<上限>` / `-<上限>` 单侧上限 / `<下限>-` 单侧下限）
_DASH_RANGE_RE = re.compile(r"^(?P<low>\d+(?:\.\d+)?)?[—–\-](?P<high>\d+(?:\.\d+)?)?$")
# 只印一个数 → 视为单侧上限（与 `— ~ <上限>` 同义）
_PLAIN_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")

# 单位列的样子：含字母或百分号。用它把"单位列"与"区间列"分开——
# 区间列只有数字与分隔符，**绝不含字母**。
_UNIT_LIKE_RE = re.compile(r"[A-Za-z%μµ]")

_RANGE_PLACEHOLDERS = ("—", "–", "-", "~", "～")

# 区间一侧的分类结果（**"不设限"与"读不出"必须分开**：
# 前者是报告如实印的单侧区间，后者是读错——混了就把读错静默读成单侧区间）
_SIDE_ABSENT = "absent"
_SIDE_NUMBER = "number"
_SIDE_BAD = "bad"


class ParsedLine:
    """一行的解析结果（**不含判定**）。

    `name` 为命中知识库的 `canonical_name`（未命中为 None）；`printed` 为区间列的
    解析结果——`None` 表示**报告声明没印**，而"印了但读不出"由调用方收到的
    `reason` 表达（两者不可混：混了就把"读不懂"静默读成"没有"）。
    """

    __slots__ = ("name", "raw_name", "value", "raw_unit", "printed")

    def __init__(self, name, raw_name, value, raw_unit, printed):
        self.name = name
        self.raw_name = raw_name
        self.value = value
        self.raw_unit = raw_unit
        self.printed = printed  # Optional[Tuple[Optional[float], Optional[float]]]

    def __repr__(self) -> str:  # pragma: no cover - 调试便利
        return "ParsedLine(%r, value=%r, unit=%r, printed=%r)" % (
            self.name, self.value, self.raw_unit, self.printed,
        )


def strip_annotations(text: str) -> str:
    """摘掉尾部注记（`[置信度 0.96]` 这类）。**只摘方括号段**，不动其余文本。"""
    return _ANNOTATION_RE.sub(" ", str(text)).strip()


def split_columns(text: str) -> List[str]:
    """按空白切列（全角转半角 + 多空格归一为单空格，与模块① 的行装配同源）。"""
    cleaned = to_halfwidth(strip_annotations(text))
    return [part for part in re.split(r"\s+", cleaned) if part]


def parse_number(token: str) -> Optional[float]:
    """解析一个数值 token（带比较前缀/千分位也不拒绝）。抽不到 → None。"""
    if token is None:
        return None
    match = _NUMBER_RE.match(normalize_key(token))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:  # pragma: no cover - 正则已保证可解析
        return None


def _classify_side(text: str) -> Tuple[str, Optional[float]]:
    """区间一侧的分类：`(种类, 数值)`。

    三态必须分开——**"报告如实印的单侧区间"与"这一侧读不出"不是一回事**：
    `— ~ <上限>` 是单侧上限（正常形态），`<下限> ~ <非数字>` 是读错（必须进待人工映射）。
    若把后者也当成"该侧不设限"，一条真实的读错就被伪装成一条干净的单侧区间，
    判定会照着一个残缺的区间下结论。
    """
    stripped = normalize_key(text)
    if not stripped:
        return _SIDE_ABSENT, None
    if stripped in _RANGE_PLACEHOLDERS:
        return _SIDE_ABSENT, None
    number = parse_number(stripped)
    if number is None:
        return _SIDE_BAD, None
    return _SIDE_NUMBER, number


def parse_range_column(tokens: Sequence[str]) -> Tuple[Optional[Tuple], Optional[str]]:
    """解析区间列。返回 `(printed, reason)`：

    - `printed` 非空 → 报告印了区间（元素可为 None 表示单侧，如只印上限）；
    - `printed is None` 且 `reason is None` → 报告**声明没印**（或整列缺失）；
    - `reason` 非空 → 印了但读不出（`range_unparsed`，进待人工映射）。

    **`printed=None` 的两种来源必须由调用方区分**：本函数只在"占位符/空列"
    时返回 `(None, None)`；真正的解析失败一律返回非空 `reason`。
    """
    if not tokens:
        return None, None

    joined = normalize_key(" ".join(tokens))
    if _NOT_PRINTED_RE.match(joined):
        return None, None

    if _RANGE_SEP_RE.search(joined):
        low_kind, low = _classify_side(_RANGE_SEP_RE.split(joined, 1)[0])
        high_kind, high = _classify_side(_RANGE_SEP_RE.split(joined, 1)[1])
        if _SIDE_BAD in (low_kind, high_kind):
            return None, REASON_RANGE_UNPARSED
        if low_kind == _SIDE_ABSENT and high_kind == _SIDE_ABSENT:
            return None, REASON_RANGE_UNPARSED
        return (low, high), None

    dash = _DASH_RANGE_RE.match(joined)
    if dash and (dash.group("low") or dash.group("high")):
        low = parse_number(dash.group("low")) if dash.group("low") else None
        high = parse_number(dash.group("high")) if dash.group("high") else None
        return (low, high), None

    if _PLAIN_NUMBER_RE.match(joined):
        return (None, parse_number(joined)), None

    return None, REASON_RANGE_UNPARSED


def _split_unit_and_range(rest: Sequence[str], dictionary: MeasurementDictionary) -> Tuple[str, List[str]]:
    """把"数值之后的 token"切成 `(单位原文, 区间列 token)`。

    判据（**先认字典、再认形状**，两道都不靠猜）：

    1. 取 rest 的**最短已登记单位前缀**（如 `U/L`、次方写法那类）——认得出就到此为止；
    2. 认不出时，若首个 token 形状像单位（含字母）→ 它是"写了但认不出"的单位，
       `unit_unmapped` 的原因就落在它身上；否则说明**这行根本没写单位**，
       单位列为空、整段都是区间列。

    第 2 步的意义：`<项目名> <数值> oz <下限>-<上限>` 与 `<项目名> <数值> <下限>-<上限>`
    都是"没有可用单位"，但一个是"写了认不出"、一个是"没写"——两者都进待人工映射，
    可它们的原文不同，留痕必须如实反映（人工核对时看的就是原文）。
    """
    for length in range(1, len(rest) + 1):
        candidate = normalize_key(" ".join(rest[:length]))
        if dictionary.match_unit(candidate).unit is not None:
            return " ".join(rest[:length]), list(rest[length:])
    if rest and _UNIT_LIKE_RE.search(rest[0]):
        return rest[0], list(rest[1:])
    return "", list(rest)


def _split_value_and_unit(token: str) -> Tuple[Optional[float], str]:
    """拆开"数值与单位粘在一起"的写法（`2mg` / `5mmol/L`）。

    为什么值得单独处理：这类写法里**数值是有、单位也写了**。若不拆，整段解析失败
    会误报成"数值未定位"（`value_unlocated`）——把"单位认不出"这个真实原因，
    报成一个错误的原因码，人工核对时按"数值没读到"去找，方向就错了。
    """
    glued = _GLUED_RE.match(normalize_key(token))
    if not glued:
        return None, ""
    return float(glued.group("value")), token[len(glued.group("value")):]


def parse_line(line: RawLine, dictionary: MeasurementDictionary) -> Tuple[ParsedLine, Optional[str]]:
    """解析一行。返回 `(ParsedLine, reason)`——`reason` 非空表示该行进待人工映射。"""
    if dictionary is None:
        raise NormalizeError("解析需要指标名字典（别名表经参数接收，模块不读文件）")

    tokens = split_columns(line.text)
    if not tokens:
        return ParsedLine(None, "", None, "", None), REASON_NAME_UNMAPPED

    matched = dictionary.match_name(tokens)
    if matched is None:
        return ParsedLine(None, tokens[0], None, "", None), REASON_NAME_UNMAPPED

    canonical, used = matched
    raw_name = " ".join(tokens[:used])
    rest = tokens[used:]

    if not rest:
        return ParsedLine(canonical, raw_name, None, "", None), REASON_VALUE_UNLOCATED

    value = parse_number(rest[0])
    if value is None:
        glued_value, glued_unit = _split_value_and_unit(rest[0])
        if glued_value is not None:
            # 数值与单位粘在一起：数值可用，单位原文取粘住的余部
            return (
                ParsedLine(canonical, raw_name, glued_value, glued_unit, None),
                REASON_UNIT_UNMAPPED,
            )
        return ParsedLine(canonical, raw_name, None, "", None), REASON_VALUE_UNLOCATED

    raw_unit, range_tokens = _split_unit_and_range(rest[1:], dictionary)

    if not raw_unit:
        # **报告没写单位**——与"写了但认不出"分开报原因码：两者都要人工处理，
        # 但"没写"该回去核对报告排版，"认不出"该回去扩单位表，处置方向不同。
        return ParsedLine(canonical, raw_name, value, "", None), REASON_UNIT_ABSENT

    unit_match = dictionary.match_unit(raw_unit)
    if unit_match.unit is None or not dictionary.unit_belongs_to(canonical, unit_match.unit):
        # 认不出 / 认得但不是这个指标的量纲——都进待人工映射，
        # **绝不回落成字典单位**（回落 = 拿别的量纲的单位给这行的值背书）
        return ParsedLine(canonical, raw_name, value, raw_unit, None), REASON_UNIT_UNMAPPED

    printed, reason = parse_range_column(range_tokens)
    if reason is not None:
        return ParsedLine(canonical, raw_name, value, raw_unit, None), reason
    return ParsedLine(canonical, raw_name, value, raw_unit, printed), None


def parse_lines(lines: Sequence[RawLine], dictionary: MeasurementDictionary) -> List[tuple]:
    """批量解析。返回 `[(RawLine, ParsedLine, reason), ...]`，**顺序与输入一致**。"""
    if dictionary is None:
        raise NormalizeError("解析需要指标名字典（别名表经参数接收，模块不读文件）")
    out = []
    for line in lines:
        parsed, reason = parse_line(line, dictionary)
        out.append((line, parsed, reason))
    return out
