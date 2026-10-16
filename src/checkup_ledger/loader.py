"""内置区间知识库加载 + 来源门禁。

**门禁是这一层存在的理由**：判定用的区间数值只能来自知识库，且每条必须挂
来源核对。loader 入口做硬门——不合规的条目**拒绝加载**，并在"未启用清单"里
显式列出原因（静默放行 = 带着不可核证的结论出去）。

三条纪律（plan/04 第二节）：
1. 缺来源字段（`source.standard`）、`status` 不在枚举内、或 `status: verified`
   而 `evidence` 为空 → 拒绝加载该条目，记入未启用清单。
2. `status: pending` **不进判定路径**——可作展示信息，绝不作为区间默认值来源。
3. 区间数值只在 YAML 一处定义（零字面量门禁守）。

本模块只读文件、不联网。
"""

import os
from typing import Dict, List, Optional, Tuple

from checkup_ledger.model import ALL_BOUNDS, ALL_SEX, BOUNDS_CLOSED, SEX_ANY, RefRange
from checkup_ledger.serialize import write_atomic  # noqa: F401  (写盘单点：汇总产物经此写出)

STATUS_PENDING = "pending"
STATUS_VERIFIED = "verified"
ALL_STATUS = (STATUS_PENDING, STATUS_VERIFIED)

# SEX_ANY / ALL_SEX 由 model 定义并在此重导出（同源，避免"主体限制"出现两份口径）


class KnowledgeError(RuntimeError):
    """知识库文件本身不可用（缺失/格式错/schema 不支持）。"""


class IndicatorEntry:
    """一条内置区间条目（已过门禁）。"""

    __slots__ = (
        "canonical_name",
        "display_name",
        "aliases",
        "unit",
        "unit_aliases",
        "default_range",
        "source_standard",
        "status",
        "evidence",
        "applies_to_sex",
    )

    def __init__(
        self,
        canonical_name: str,
        display_name: str,
        aliases: List[str],
        unit: str,
        unit_aliases: List[str],
        default_range: RefRange,
        source_standard: str,
        status: str,
        evidence: str,
        applies_to_sex: str,
    ):
        self.canonical_name = canonical_name
        self.display_name = display_name
        self.aliases = aliases
        self.unit = unit
        self.unit_aliases = unit_aliases
        self.default_range = default_range
        self.source_standard = source_standard
        self.status = status
        self.evidence = evidence
        self.applies_to_sex = applies_to_sex

    @property
    def usable_as_default(self) -> bool:
        """只有 verified 条目可作为区间默认值进入判定路径。"""
        return self.status == STATUS_VERIFIED

    def __repr__(self) -> str:  # pragma: no cover - 调试便利
        return "IndicatorEntry(%r, status=%r)" % (self.canonical_name, self.status)


class DisabledEntry:
    """被门禁拦下的条目（附原因，可审计）。"""

    __slots__ = ("canonical_name", "reason")

    def __init__(self, canonical_name: str, reason: str):
        self.canonical_name = canonical_name
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - 调试便利
        return "DisabledEntry(%r, %r)" % (self.canonical_name, self.reason)


class IndicatorDict:
    """加载后的指标字典：可生效条目 + 未启用清单。"""

    def __init__(
        self,
        entries: List[IndicatorEntry],
        disabled: List[DisabledEntry],
        disclaimer: str = "",
        schema_version: int = 0,
    ):
        self.entries = entries
        self.disabled = disabled
        self.disclaimer = disclaimer
        self.schema_version = schema_version

    def by_canonical(self, name: str) -> Optional[IndicatorEntry]:
        for entry in self.entries:
            if entry.canonical_name == name:
                return entry
        return None

    def verified_defaults(self) -> Dict[str, RefRange]:
        """判定路径唯一入口：只含 verified 条目。pending 一律不进。"""
        table = {}
        for entry in self.entries:
            if entry.usable_as_default:
                table[entry.canonical_name] = entry.default_range
        return table

    def alias_index(self) -> Dict[str, str]:
        """别名 → canonical_name（最长优先由调用方按 key 长度排序实现）。"""
        index = {}
        for entry in self.entries:
            for alias in [entry.canonical_name, entry.display_name] + list(entry.aliases):
                if alias:
                    index[alias] = entry.canonical_name
        return index


def _require_mapping(node, where: str) -> dict:
    if not isinstance(node, dict):
        raise KnowledgeError("%s 应为映射（mapping），实为 %s" % (where, type(node).__name__))
    return node


def _parse_range(raw, where: str) -> RefRange:
    if raw is None:
        return RefRange(low=None, high=None, bounds=BOUNDS_CLOSED)
    node = _require_mapping(raw, where)
    low = node.get("low")
    high = node.get("high")
    bounds = node.get("bounds", BOUNDS_CLOSED)
    if not isinstance(bounds, str) or bounds not in ALL_BOUNDS:
        raise KnowledgeError("%s.bounds 非法：%r（合法值：%s）" % (where, bounds, ", ".join(ALL_BOUNDS)))
    for label, value in (("low", low), ("high", high)):
        if value is not None and not isinstance(value, (int, float)):
            raise KnowledgeError("%s.%s 应为数值，实为 %r" % (where, label, value))
        if isinstance(value, bool):
            raise KnowledgeError("%s.%s 不应为布尔值" % (where, label))
    if low is not None and high is not None and low > high:
        raise KnowledgeError("%s 下限定为 %r 高于上限 %r" % (where, low, high))
    return RefRange(
        low=None if low is None else float(low),
        high=None if high is None else float(high),
        bounds=bounds,
    )


def _as_str_list(raw, where: str) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise KnowledgeError("%s 应为列表，实为 %s" % (where, type(raw).__name__))
    out = []
    for item in raw:
        if not isinstance(item, str):
            raise KnowledgeError("%s 的元素应为字符串，实为 %r" % (where, item))
        out.append(item)
    return out


def gate_entry(raw: dict, index: int) -> Tuple[Optional[IndicatorEntry], Optional[DisabledEntry]]:
    """单条目的来源门禁。返回 (可生效条目, 被拦条目)，二者恰有一个非空。

    硬门：`source.standard` 缺失 / `status` 非法 / `verified` 而 `evidence` 为空
    → 一律拒绝加载并给出原因。
    """
    name = raw.get("canonical_name")
    if not isinstance(name, str) or not name.strip():
        return None, DisabledEntry(
            "<第 %d 条无 canonical_name>" % (index + 1), "canonical_name 缺失或非字符串"
        )

    source = raw.get("source")
    if not isinstance(source, dict):
        return None, DisabledEntry(name, "source 段缺失（未挂来源核对）")

    standard = source.get("standard")
    if not isinstance(standard, str) or not standard.strip():
        return None, DisabledEntry(name, "source.standard 缺失（未挂来源分册）")

    status = source.get("status")
    if status not in ALL_STATUS:
        return None, DisabledEntry(
            name, "source.status 非法或缺失：%r（合法值：%s）" % (status, ", ".join(ALL_STATUS))
        )

    evidence = source.get("evidence") or ""
    if not isinstance(evidence, str):
        return None, DisabledEntry(name, "source.evidence 应为字符串")

    if status == STATUS_VERIFIED and not evidence.strip():
        return None, DisabledEntry(name, "status=verified 但 source.evidence 为空（核对渠道未留痕）")

    try:
        default_range = _parse_range(raw.get("default_range"), "%s.default_range" % name)
        aliases = _as_str_list(raw.get("aliases"), "%s.aliases" % name)
        unit_aliases = _as_str_list(raw.get("unit_aliases"), "%s.unit_aliases" % name)
    except KnowledgeError as exc:
        return None, DisabledEntry(name, str(exc))

    applies = raw.get("applies_to") or {}
    if not isinstance(applies, dict):
        return None, DisabledEntry(name, "applies_to 应为映射")
    sex = applies.get("sex", SEX_ANY)
    if sex not in ALL_SEX:
        return None, DisabledEntry(name, "applies_to.sex 非法：%r（合法值：%s）" % (sex, ", ".join(ALL_SEX)))

    unit = raw.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        return None, DisabledEntry(name, "unit 缺失或非字符串")

    display_name = raw.get("display_name") or name
    if not isinstance(display_name, str):
        return None, DisabledEntry(name, "display_name 应为字符串")

    entry = IndicatorEntry(
        canonical_name=name,
        display_name=display_name,
        aliases=aliases,
        unit=unit,
        unit_aliases=unit_aliases,
        default_range=default_range,
        source_standard=standard,
        status=status,
        evidence=evidence,
        applies_to_sex=sex,
    )
    return entry, None


def load_indicators(path) -> IndicatorDict:
    """加载并过门禁。文件缺失/格式错 → KnowledgeError（不静默当空库）。"""
    target = os.fspath(path)
    if not os.path.isfile(target):
        raise KnowledgeError("知识库文件不存在：%s" % target)

    try:
        import yaml  # 局部导入：缺 PyYAML 时报出可读提示而非裸 ImportError
    except ImportError as exc:  # pragma: no cover - 核心依赖缺失属环境问题
        raise KnowledgeError("需要 PyYAML 解析知识库（pip install PyYAML>=6.0）：%s" % exc)

    with open(target, "r", encoding="utf-8") as handle:
        try:
            root = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise KnowledgeError("知识库 YAML 解析失败：%s" % exc)

    root = _require_mapping(root, "知识库根节点")
    schema_version = root.get("schema_version")
    if schema_version != 1:
        raise KnowledgeError("不支持的 schema_version：%r（本版本只认 1）" % (schema_version,))

    raw_indicators = root.get("indicators")
    if not isinstance(raw_indicators, list) or not raw_indicators:
        raise KnowledgeError("indicators 应为非空列表")

    entries: List[IndicatorEntry] = []
    disabled: List[DisabledEntry] = []
    seen = set()
    for index, raw in enumerate(raw_indicators):
        raw = _require_mapping(raw, "indicators[%d]" % index)
        entry, rejected = gate_entry(raw, index)
        if rejected is not None:
            disabled.append(rejected)
            continue
        if entry.canonical_name in seen:
            disabled.append(DisabledEntry(entry.canonical_name, "canonical_name 重复"))
            continue
        seen.add(entry.canonical_name)
        entries.append(entry)

    disclaimer = root.get("disclaimer") or ""
    if not isinstance(disclaimer, str):
        raise KnowledgeError("disclaimer 应为字符串")

    return IndicatorDict(
        entries=entries,
        disabled=disabled,
        disclaimer=disclaimer,
        schema_version=int(schema_version),
    )
