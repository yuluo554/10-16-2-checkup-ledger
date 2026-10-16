"""指标名字典与单位归一表（**纯函数**：不读文件、不读时钟、不联网）。

口径来源：`data/README.md` 第五节 + `plan/04` 第四节「单位与口径纪律」。
本模块**不重写口径**，只是它的唯一代码实现处。

三条纪律：

1. **别名表只在知识库 YAML 一处定义**——本模块经参数接收已加载的条目，不另建第二份。
   调用方（`pipeline.py` 之外的 `__init__.normalize_document`）是唯一读文件处，
   故本模块可以保持纯函数。
2. **单位按最长优先匹配**。短串吃长串前缀是**静默数值放大**的经典来源：
   报告写 `2mg`，若先匹配到短别名 `m`，就把它读成另一个量纲的值——值看着没变，
   语义已经错了，且没有任何提示。故匹配规则是"能匹配上的别名里取**最长**的那个"。
3. **认不出的单位是第三态，不是"没写"**：`unit_unmapped`（写了但认不出）
   与"报告根本没写这一项"是两件事，前者进 `pending_mapping`，不静默丢弃。

本模块只做**字符串对齐**：不做任何数值判断、不 import 判定内核、不产出 `FLAG_*`。
"""

import re
from typing import Dict, Iterable, List, Optional, Sequence

from checkup_ledger.model import BOUNDS_CLOSED, SEX_ANY
from checkup_ledger.normalize.errors import NormalizeError

# 待人工映射的原因码（第三态：写了但认不出。**不是**"报告里没有"）
REASON_NAME_UNMAPPED = "name_unmapped"
REASON_UNIT_UNMAPPED = "unit_unmapped"
REASON_UNIT_ABSENT = "unit_absent"
REASON_VALUE_UNLOCATED = "value_unlocated"
REASON_RANGE_UNPARSED = "range_unparsed"

ALL_REASONS = (
    REASON_NAME_UNMAPPED,
    REASON_UNIT_UNMAPPED,
    REASON_UNIT_ABSENT,
    REASON_VALUE_UNLOCATED,
    REASON_RANGE_UNPARSED,
)

# 全角 → 半角（中文报告里括号、斜杠、连字符常是全角；只做字符形态归一，不改语义）
_FULLWIDTH_MAP = {
    "\uff08": "(",
    "\uff09": ")",
    "\uff0f": "/",
    "\uff0d": "-",
    "\uff5e": "~",
    "\u3000": " ",
}
_FULLWIDTH_RE = re.compile("[%s]" % "".join(_FULLWIDTH_MAP))
_WS_RE = re.compile(r"\s+")


def to_halfwidth(text) -> str:
    """字符形态归一：全角标点转半角。**保留空白**（切列需要它）。"""
    if text is None:
        return ""
    return _FULLWIDTH_RE.sub(lambda match: _FULLWIDTH_MAP[match.group(0)], str(text))


def normalize_key(text) -> str:
    """别名/单位键的归一形式：半角 + **去掉全部空白**。

    为什么去空白：知识库登记的"报告实测词"有含空格的写法（`WBC 白细胞`、`GLU-空腹`），
    而报告在列排版下空格数不定（补白/逐字定位都会变）。去空白后比对的是**词的组合**，
    不是排版——形态差异不该泄漏到键里。
    """
    return _WS_RE.sub("", to_halfwidth(text))


class UnitMatch:
    """一次单位匹配的结果：命中的别名 + 归一后的单位（未命中时为 None）。"""

    __slots__ = ("raw", "matched_alias", "unit")

    def __init__(self, raw: str, matched_alias: Optional[str], unit: Optional[str]):
        self.raw = raw
        self.matched_alias = matched_alias
        self.unit = unit


class MeasurementDictionary:
    """指标名字典 + 单位归一表（由已过来源门禁的条目构建，只读）。

    `entries` 为 loader 的 `IndicatorEntry`（鸭子类型：只要具备
    `canonical_name`/`aliases`/`display_name`/`unit`/`unit_aliases`/`default_range`/
    `applies_to_sex`/`source_standard` 这些属性即可——本模块不 import loader，
    免得纯函数模块被拖进文件 I/O）。
    """

    __slots__ = ("entries", "disabled", "_aliases", "_units", "_bounds", "_constraints")

    def __init__(self, entries: Sequence, disabled: Sequence = ()):
        self.entries = list(entries)
        self.disabled = list(disabled)
        self._aliases = self._build_alias_index()
        self._units = self._build_unit_index()
        self._bounds = {}
        self._constraints = {}
        for entry in self.entries:
            self._bounds[entry.canonical_name] = self._entry_bounds(entry)
            self._constraints[entry.canonical_name] = getattr(entry, "applies_to_sex", SEX_ANY)

    # ---------------------------------------------------------- 索引构建

    def _build_alias_index(self) -> Dict[str, str]:
        """别名 → canonical_name。

        **同一别名指向两个不同指标 → 报错**：静默取其一会让"谷丙转氨酶"这类词
        随机落到两项之一，判定结果跟着随机。别名表是数据，冲突必须在加载时报出。
        """
        index: Dict[str, str] = {}
        for entry in self.entries:
            for alias in self._entry_aliases(entry):
                key = normalize_key(alias)
                if not key:
                    continue
                existing = index.get(key)
                if existing is not None and existing != entry.canonical_name:
                    raise NormalizeError(
                        "别名冲突：%r 同时指向 %s 与 %s（别名表必须一一对应）"
                        % (alias, existing, entry.canonical_name)
                    )
                index[key] = entry.canonical_name
        return index

    def _build_unit_index(self) -> Dict[str, str]:
        """单位别名 → canonical 单位。**同一别名指向两个不同单位 → 报错**。"""
        index: Dict[str, str] = {}
        for entry in self.entries:
            for alias in self._entry_unit_aliases(entry):
                key = normalize_key(alias)
                if not key:
                    continue
                existing = index.get(key)
                if existing is not None and existing != entry.unit:
                    raise NormalizeError(
                        "单位别名冲突：%r 同时指向 %r 与 %r（单位表必须一一对应）"
                        % (alias, existing, entry.unit)
                    )
                index[key] = entry.unit
        return index

    @staticmethod
    def _entry_aliases(entry) -> List[str]:
        out = [entry.canonical_name, getattr(entry, "display_name", "") or ""]
        out.extend(getattr(entry, "aliases", ()) or ())
        return [item for item in out if item]

    @staticmethod
    def _entry_unit_aliases(entry) -> List[str]:
        out = [entry.unit]
        out.extend(getattr(entry, "unit_aliases", ()) or ())
        return [item for item in out if item]

    @staticmethod
    def _entry_bounds(entry) -> str:
        ref = getattr(entry, "default_range", None)
        bounds = getattr(ref, "bounds", None)
        return bounds or BOUNDS_CLOSED

    # ---------------------------------------------------------- 查询

    @property
    def alias_index(self) -> Dict[str, str]:
        return dict(self._aliases)

    @property
    def unit_index(self) -> Dict[str, str]:
        return dict(self._units)

    def bounds_for(self, canonical_name: str) -> str:
        """该指标的边界开闭语义（口径节第 2 条：**由 YAML 字段定义**，不在代码里硬编码）。

        报告自印的区间只印端点，**不印开闭**；开闭是该指标的既定口径，来自知识库条目。
        故打印区间也据此赋 bounds——否则"不超过上限"这类区间的边界值会被判反。
        （**局限如实登记**：开闭是口径属性，不是报告文本能表达的事实；见 data/README 第八节。）
        """
        return self._bounds.get(canonical_name, BOUNDS_CLOSED)

    def constraints(self) -> Dict[str, str]:
        """canonical_name → 适用域（`applies_to.sex`）。判定层的硬门输入。"""
        return dict(self._constraints)

    def canonical_unit(self, canonical_name: str) -> Optional[str]:
        """该指标的 canonical 单位（未登记 → None）。"""
        for entry in self.entries:
            if entry.canonical_name == canonical_name:
                return entry.unit
        return None

    def unit_belongs_to(self, canonical_name: str, unit: str) -> bool:
        """该单位是否属于这个指标的量纲。

        为什么要有这道门：单位表是**全局**的（`mmol/L` 被血脂与血糖共享），
        故"认得这个单位"不等于"它属于这个指标"。报告把 ALT 写成 `mmol/L` 时，
        若只做全局单位匹配，会拿血糖量纲的单位给肝酶的值背书——**认得出但张冠李戴**。
        张冠李戴与"认不出"同属"不能照此判定"，故同样进待人工映射（不换算、不猜）。
        """
        for entry in self.entries:
            if entry.canonical_name != canonical_name:
                continue
            aliases = [normalize_key(entry.unit)]
            aliases.extend(normalize_key(item) for item in getattr(entry, "unit_aliases", ()) or ())
            return normalize_key(unit) in aliases
        return False

    def match_name(self, tokens: Sequence[str]) -> Optional[tuple]:
        """在一行开头的若干 token 里找**最长的已登记别名**（精确匹配，非模糊猜）。

        为什么要按 token 前缀试：知识库里登记的"报告实测词"有含空格的写法
        （如 `WBC 白细胞`、`GLU-空腹`）。报告把它排成两列时，逐 token 比对会漏；
        逐段拼回再比对，命中的仍是**登记过的**写法——这不是猜，是精确匹配。

        返回 `(canonical_name, 命中的 token 个数)`；未命中返回 None。
        """
        for length in range(len(tokens), 0, -1):
            candidate = normalize_key(" ".join(tokens[:length]))
            if candidate in self._aliases:
                return self._aliases[candidate], length
        return None

    def match_unit(self, raw_unit: str) -> UnitMatch:
        """单位归一：**最长优先**。

        匹配规则 = "归一后的原文**以某别名开头**"的别名集合里取最长者。
        前缀匹配（而非"包含"）是必要的：包含式匹配会把 `2mg` 里的 `g` 也认成命中，
        于是"毫克"被读成"克"，值静默放大一千倍且毫无提示。
        取最长者则是为了处理 `m` / `mg` / `mmol/L` 这类同前缀的别名家族。

        `unit_aliases` 里带括号注释的写法（如 `U/L(速率法)`）在**去空白**后是 `U/L(速率法)`；
        报告常只写 `U/L`，故这类长别名不会误伤——前缀匹配要求原文以它开头，反过来不成立。
        """
        key = normalize_key(raw_unit)
        if not key:
            return UnitMatch(raw_unit, None, None)
        best_alias = None
        for alias in self._units:
            if key.startswith(alias):
                if best_alias is None or len(alias) > len(best_alias):
                    best_alias = alias
        if best_alias is None:
            return UnitMatch(raw_unit, None, None)
        return UnitMatch(raw_unit, best_alias, self._units[best_alias])


def build_dictionary(entries: Iterable, disabled: Iterable = ()) -> MeasurementDictionary:
    """由已加载条目构建字典（**第二层来源门禁**）。

    loader 已在入口拦掉缺来源的条目；这里再挡一道：调用方若绕过 loader 自行拼条目，
    缺 `source_standard` 的条目**拒绝进字典**——否则"未挂来源核对的条目不得生效"
    这条纪律就有了第二条绕过路径（判定的默认值、单位表都能被无来源条目污染）。
    """
    checked = []
    for entry in entries:
        name = getattr(entry, "canonical_name", None)
        if not name:
            raise NormalizeError("条目缺 canonical_name，无法进字典：%r" % (entry,))
        standard = getattr(entry, "source_standard", None)
        if not standard or not str(standard).strip():
            raise NormalizeError(
                "条目 %s 缺 source.standard（未挂来源核对）——拒绝进字典" % name
            )
        unit = getattr(entry, "unit", None)
        if not unit or not str(unit).strip():
            raise NormalizeError("条目 %s 缺 unit——无法参与单位归一" % name)
        checked.append(entry)
    return MeasurementDictionary(checked, disabled=disabled)
