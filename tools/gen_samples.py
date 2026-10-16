"""合成样例集生成器：**确定性**产出 `data/samples/`（cases + truth + manifest）。

为什么自研 RNG 而不用 stdlib `random`：
- `random` 的默认种子取自系统熵/时钟，**不可复现**；
- 即便 `random.seed(N)`，其内部算法与跨版本实现属"非契约"，`random.shuffle` 在元素
  相等时的行为还依赖实现——本项目要求"两次运行逐字节一致"，不能把产物押在它上面；
- 同理**不用 `hash(str)`**：CPython 的字符串哈希带随机盐（PYTHONHASHSEED），
  同一 key 两次运行会得到不同种子。本模块自写 FNV-1a 作流键哈希。

本模块纪律（plan/04 第三节「生成器纪律」）：
1. **禁 stdlib `random`、禁 `set` 迭代序、禁系统时钟** → 自研 splitmix64 变体 + 固定 seed；
2. **区间数值只在知识库一处定义**：本文件**不写任何区间数值字面量**，全部从
   `src/checkup_ledger/data/indicators.yaml` 取（零字面量门禁守）。需要"与默认值不同"
   的区间（如自印比默认更严）用**平移量**表达，不用新数值；
3. 产物**无时间戳字段**；落盘一律经 `serialize.write_atomic()`（写盘单点）；
4. **真值与引擎共用同一处判定规则**：期望标记由 `engine.compare()` 实算、主体适用性由
   `engine.range_applies_to()` 实算——不复制第二份判定/适用域逻辑；
5. 真值库**只存输入与期望**，不存 `observed`/`actual`/`got`（观测由基准运行时实算）。

关于 `pending`：知识库当前条目一律 `pending`（WS/T 全文不可直连，见 data/README.md）。
样例层把 YAML 区间当**夹具数据**注入 `judge()` 的 `default` 参数，用来模拟"该条已
verified"的形态——**不修改 YAML 的 status**，也不让 pending 进真实判定路径。

用法：
    py -3.12 tools/gen_samples.py            # 生成/覆盖 data/samples/
    py -3.12 tools/gen_samples.py --check    # 只校验"再生成与现有产物位级一致"
"""

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from checkup_ledger.engine.compare import (  # noqa: E402
    compare,
    range_applies_to,
    trend_delta,
    trend_direction,
)
from checkup_ledger.loader import load_indicators  # noqa: E402
from checkup_ledger.model import (  # noqa: E402
    ALL_FLAGS,
    ALL_TRENDS,
    BOUNDS_CLOSED,
    BOUNDS_OPEN,
    FLAG_NOT_ASSESSED,
    RANGE_SOURCE_BUILTIN,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
    SEX_ANY,
    RefRange,
)
from checkup_ledger.serialize import to_json_bytes, write_atomic  # noqa: E402

SAMPLES_DIR = os.path.join(ROOT, "data", "samples")
INDICATORS_PATH = os.path.join(SRC, "checkup_ledger", "data", "indicators.yaml")

SEED = 20261016  # 固定 seed：改它就等于换一套样例（须同步更新台账 sha256）
SCHEMA_VERSION = 1

# ---- 合成数据白名单（与 data/README.md 附录、tools/pii_gate.py 同源）----
SEX_BY_SUBJECT = {"张三": "male", "李四": "female", "王五": "male", "赵六": "female"}


# ============================================================ 确定性 RNG


class SplitMix64:
    """splitmix64 变体：纯整数运算、无 I/O、无时钟、跨平台逐位一致。

    算法（Steele/Lea/Flood，public domain）：
        state += GOLDEN
        z = state ; z = (z ^ (z >> SHIFT_A)) * M1 ; z = (z ^ (z >> SHIFT_B)) * M2
        return z ^ (z >> SHIFT_C)
    取模一律用整数 `% n`（n 为正小整数，无浮点参与）——避免浮点端点在边界上的
    跨平台差异。所有字面量都是**移位位数与结构常数**，不是区间数值。
    """

    __slots__ = ("_state",)

    GOLDEN = 0x9E3779B97F4A7C15
    M1 = 0xBF58476D1CE4E5B9
    M2 = 0x94D049BB133111EB
    MASK = 0xFFFFFFFFFFFFFFFF
    SHIFT_A = 30
    SHIFT_B = 27
    SHIFT_C = 31

    def __init__(self, seed: int):
        self._state = seed & self.MASK

    def next_u64(self) -> int:
        self._state = (self._state + self.GOLDEN) & self.MASK
        z = self._state
        z = ((z ^ (z >> self.SHIFT_A)) * self.M1) & self.MASK
        z = ((z ^ (z >> self.SHIFT_B)) * self.M2) & self.MASK
        return (z ^ (z >> self.SHIFT_C)) & self.MASK

    def below(self, bound: int) -> int:
        """[0, bound) 内的确定性整数。bound 必须为正。"""
        if bound <= 0:
            raise ValueError("bound 必须为正整数，实得 %r" % (bound,))
        return self.next_u64() % bound

    def between(self, low: int, high: int) -> int:
        """[low, high] 闭区间整数（high >= low）。"""
        if high < low:
            raise ValueError("空区间：[%r, %r]" % (low, high))
        return low + self.below(high - low + 1)


_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_U64 = 0xFFFFFFFFFFFFFFFF


def _stream(key: str) -> SplitMix64:
    """按字符串 key 派生确定性流：同 key 必得同序列（跨进程/跨平台一致）。

    不用 `hash(key)`：CPython 字符串哈希带随机盐，同一 key 两次进程会不同
    ——那会让"两次运行逐字节一致"随机变红。
    """
    h = _FNV_OFFSET
    for byte in key.encode("utf-8"):
        h = ((h ^ byte) * _FNV_PRIME) & _U64
    return SplitMix64(SEED ^ h)


# ============================================================ 区间夹具（全部来自 YAML）


def _load_yaml_ranges() -> Dict[str, dict]:
    """从知识库取全部条目的默认区间与主体限制（**区间数值的唯一来源**）。"""
    table = load_indicators(INDICATORS_PATH)
    out = {}
    for entry in table.entries:
        ref = entry.default_range
        out[entry.canonical_name] = {
            "low": ref.low,
            "high": ref.high,
            "bounds": ref.bounds,
            "sex": entry.applies_to_sex,
            "unit": entry.unit,
        }
    return out


YAML = _load_yaml_ranges()


def R(name: str, low_delta: float = 0, high_delta: float = 0, bounds: str = None) -> dict:
    """区间夹具规格：以 YAML 条目为基准，可平移上下限、改开闭。

    `low_delta` / `high_delta` 是**平移量**（结构参数），不是新的区间数值——
    这样"自印比默认更严"这类用例无需在源码里写第二个区间数值。
    """
    base = YAML[name]
    low = base["low"]
    high = base["high"]
    if low is not None and low_delta:
        low = low + low_delta
    if high is not None and high_delta:
        high = high + high_delta
    return {
        "low": low,
        "high": high,
        "bounds": bounds or base["bounds"],
    }


def _to_ref(spec: Optional[dict]) -> Optional[RefRange]:
    if spec is None:
        return None
    return RefRange(low=spec["low"], high=spec["high"], bounds=spec["bounds"])


# ---- 取值带：由"所用区间"与确定性流算出具体数值（源码零数值字面量）----

BAND_IN_RANGE = "in_range"
BAND_AT_LOW = "at_low"
BAND_AT_HIGH = "at_high"
BAND_JUST_ABOVE_LOW = "just_above_low"
BAND_JUST_BELOW_HIGH = "just_below_high"
BAND_ABOVE_HIGH = "above_high"
BAND_BELOW_LOW = "below_low"
BAND_ABOVE_OTHER_HIGH = "above_other_high"


def B(band: str, key: str, ref: str = None, other: dict = None) -> dict:
    """取值带规格。

    - `key`：确定性流键。**同 key 必得同值**——"平稳趋势"两期用同一 key 即天然相等。
    - `ref`：仅用于取值（不作区间）的 YAML 指标名（如"无区间"行仍需一个像样的数值）。
    - `other`：`above_other_high` 用来给出"必须超过的那条区间"（如默认值上限）。
    """
    return {"band": band, "key": key, "ref": ref, "other": other}


def _decimals(value: float) -> int:
    """该数值的展示精度（小数位）——由 YAML 里的写法实算，不写精度常数。"""
    text = repr(float(value))
    if "e" in text or "E" in text:
        raise ValueError("区间数值不应为科学计数法：%r" % (value,))
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1].rstrip("0"))


def _step(low: Optional[float], high: Optional[float]) -> float:
    """取值步长 = 10^(-精度)。精度取自区间端点本身的写法。"""
    probe = high if high is not None else low
    decimals = _decimals(probe)
    return float(10 ** (-decimals))


def _resolve_band(spec: dict, used: dict, yaml_ranges: Dict[str, dict]) -> float:
    """把取值带解析成具体数值。区间缺失/带越界一律**抛错**（不静默取默认值）。"""
    band = spec["band"]
    source = used
    if spec.get("ref") is not None:
        source = yaml_ranges[spec["ref"]]
    low, high = source["low"], source["high"]
    step = _step(low, high)
    rng = _stream(spec["key"])

    if band == BAND_AT_LOW:
        if low is None:
            raise ValueError("at_low 需要下限：%r" % (source,))
        return low
    if band == BAND_AT_HIGH:
        if high is None:
            raise ValueError("at_high 需要上限：%r" % (source,))
        return high
    if band == BAND_JUST_ABOVE_LOW:
        if low is None:
            raise ValueError("just_above_low 需要下限：%r" % (source,))
        return low + step
    if band == BAND_JUST_BELOW_HIGH:
        if high is None:
            raise ValueError("just_below_high 需要上限：%r" % (source,))
        return high - step
    if band == BAND_ABOVE_HIGH:
        if high is None:
            raise ValueError("above_high 需要上限：%r" % (source,))
        return high + step * (1 + rng.below(3))
    if band == BAND_BELOW_LOW:
        if low is None:
            raise ValueError("below_low 需要下限：%r" % (source,))
        return low - step * (1 + rng.below(3))
    if band == BAND_IN_RANGE:
        lo = 0.0 if low is None else low
        if high is None:
            raise ValueError("in_range 至少需要一个端点：%r" % (source,))
        lo_i = int(round(lo / step))
        hi_i = int(round(high / step))
        return rng.between(lo_i, hi_i) * step
    if band == BAND_ABOVE_OTHER_HIGH:
        other = spec.get("other")
        if other is None or other["high"] is None:
            raise ValueError("above_other_high 需要 other.high：%r" % (other,))
        if high is None:
            raise ValueError("above_other_high 需要所用区间的上限：%r" % (source,))
        lo_i = int(round(other["high"] / step)) + 1
        hi_i = int(round(high / step))
        if lo_i > hi_i:
            raise ValueError(
                "above_other_high 的取值区间为空：other.high=%r 已达所用区间上限 %r"
                % (other["high"], high)
            )
        return rng.between(lo_i, hi_i) * step
    raise ValueError("未知取值带：%r" % (band,))


# ============================================================ 用例定义


def _case_definitions() -> List[dict]:
    """全部用例的显式定义。**区间与取值都由 YAML + 确定性流导出**（本文件零区间数值）。

    覆盖度对齐 plan/04 第三节覆盖度门槛表：每个维度至少一条；`threshold_exact` /
    `near_miss` 双向、自印覆盖默认值（结论相反）、性别适用域（含"不该命中"反向）、
    低置信复核（含"未复核不落库"阴性对照）齐备。
    """
    return [
        # ---- 肝功能基线：自印区间 + 四态 ----
        {
            "case_id": "case-001-zhangsan-2023",
            "subject": "张三",
            "date": "2023-03-11",
            "institution": "示例体检中心A",
            "tags": ["domain:肝功能", "source:report_printed"],
            "rows": [
                # 自印区间比默认更严（上限平移 -10）：值超过自印上限 → H
                {"name": "ALT", "printed": R("ALT", high_delta=-10),
                 "value": B(BAND_ABOVE_HIGH, "alt-2023")},
                {"name": "AST", "printed": R("AST"),
                 "value": B(BAND_IN_RANGE, "ast-2023")},
            ],
        },
        {
            "case_id": "case-002-zhangsan-2024",
            "subject": "张三",
            "date": "2024-03-11",
            "institution": "示例体检中心A",
            "tags": ["domain:肝功能", "trend:down"],
            "rows": [
                # 2023 期取值高于自印上限、本期落回区间内 → 下降
                {"name": "ALT", "printed": R("ALT", high_delta=-10),
                 "value": B(BAND_IN_RANGE, "alt-2024")},
                {"name": "AST", "printed": R("AST"),
                 "value": B(BAND_IN_RANGE, "ast-2024")},
            ],
        },
        {
            "case_id": "case-003-zhangsan-2025",
            "subject": "张三",
            "date": "2025-03-11",
            "institution": "示例医院C",
            "tags": ["domain:肝功能", "trend:flat"],
            "rows": [
                # 与 case-002 同流键 → 值相同 → 平稳（趋势三态里的"平"由此保证）
                {"name": "ALT", "printed": R("ALT", high_delta=-10),
                 "value": B(BAND_IN_RANGE, "alt-2024")},
                {"name": "AST", "printed": R("AST"),
                 "value": B(BAND_IN_RANGE, "ast-2024")},
            ],
        },
        # ---- 血常规 + 性别适用域（含"不该命中"反向样例）----
        {
            "case_id": "case-004-lisi-2024",
            "subject": "李四",
            "date": "2024-05-20",
            "institution": "示例体检中心B",
            "tags": ["domain:血常规", "sex:applies"],
            "rows": [
                # 女性样本 + HGB 条目 applies_to.sex=male：区间**不该命中** → 拒判。
                # 值本身落在该区间内（in_range），故"若实现忽略适用域"会判 normal
                # ——本用例立刻红。这是"这条规则不该命中"的核心反向样例。
                {"name": "HGB", "default": R("HGB"), "default_constraint": "male",
                 "value": B(BAND_IN_RANGE, "hgb-2024", ref="HGB")},
                {"name": "WBC", "printed": R("WBC"),
                 "value": B(BAND_ABOVE_HIGH, "wbc-2024")},
                # PLT 本期贴近下限、下期贴近上限 → 上升（趋势"升"的确定性来源）
                {"name": "PLT", "printed": R("PLT"),
                 "value": B(BAND_JUST_ABOVE_LOW, "plt-2024")},
            ],
        },
        {
            "case_id": "case-005-wangwu-2024",
            "subject": "王五",
            "date": "2024-06-01",
            "institution": "示例体检中心A",
            "tags": ["domain:血常规", "sex:applies", "source:builtin_default"],
            "rows": [
                # 男性样本 + 男性区间 → 适用；值低于下限 → L（builtin_default 来源）
                {"name": "HGB", "default": R("HGB"), "default_constraint": "male",
                 "value": B(BAND_BELOW_LOW, "hgb-wangwu")},
            ],
        },
        # ---- 边界双向 ----
        {
            "case_id": "case-006-boundary-closed",
            "subject": "王五",
            "date": "2024-07-15",
            "institution": "示例体检中心B",
            "tags": ["boundary:threshold_exact", "bounds:closed", "domain:血脂"],
            "rows": [
                # 恰等于闭区间上限 → normal
                {"name": "TC", "printed": R("TC", bounds=BOUNDS_CLOSED),
                 "value": B(BAND_AT_HIGH, "tc-closed")},
            ],
        },
        {
            "case_id": "case-007-boundary-open",
            "subject": "王五",
            "date": "2024-07-16",
            "institution": "示例体检中心B",
            "tags": ["boundary:threshold_exact", "bounds:open", "domain:血脂"],
            "rows": [
                # 恰等于开区间上限 → high（边界归属由 YAML bounds 决定，不在代码硬编码）
                {"name": "TG", "printed": R("TG", bounds=BOUNDS_OPEN),
                 "value": B(BAND_AT_HIGH, "tg-open")},
            ],
        },
        {
            "case_id": "case-008-near-miss",
            "subject": "王五",
            "date": "2024-07-17",
            "institution": "示例体检中心B",
            "tags": ["boundary:near_miss", "domain:血脂"],
            "rows": [
                # 差一步不到上限 → 不命中；差一步高于下限 → 不命中 L
                {"name": "TC", "printed": R("TC"),
                 "value": B(BAND_JUST_BELOW_HIGH, "tc-near")},
                {"name": "HDL-C", "printed": R("HDL-C"),
                 "value": B(BAND_JUST_ABOVE_LOW, "hdl-near")},
            ],
        },
        # ---- 自印覆盖默认值（同一值在两套区间下结论相反）----
        {
            "case_id": "case-009-printed-overrides-default",
            "subject": "赵六",
            "date": "2024-08-08",
            "institution": "示例医院C",
            "tags": ["priority:printed_overrides_default", "domain:肾功能"],
            "rows": [
                # 自印 = YAML 原值；默认 = 上限平移 -7（更严）。
                # 取值落在"默认上限之上、自印上限之内" → 自印判 normal、默认会判 high。
                # 实现若把最优先来源丢掉而回落默认，本用例立刻红。
                {"name": "CREA", "printed": R("CREA"),
                 "default": R("CREA", high_delta=-7),
                 "value": B(BAND_ABOVE_OTHER_HIGH, "crea-priority",
                            other=R("CREA", high_delta=-7))},
            ],
        },
        # ---- 拒判 + 单位变体 ----
        {
            "case_id": "case-010-no-range",
            "subject": "赵六",
            "date": "2024-08-09",
            "institution": "示例医院C",
            "tags": ["source:none", "unit:variant", "domain:血糖"],
            "rows": [
                # 未印区间 + 无可用默认（知识库条目 pending，不进判定路径）→ 拒判
                {"name": "GLU", "printed": None, "default": None,
                 "value": B(BAND_IN_RANGE, "glu-norange", ref="GLU")},
                # 单位变体：报告写 IU/L，canonical 单位 U/L（同量纲归一）
                {"name": "ALT", "printed": None, "default": None, "unit": "IU/L",
                 "canonical_unit": "U/L",
                 "value": B(BAND_IN_RANGE, "alt-norange", ref="ALT")},
            ],
        },
        # ---- 趋势下降 ----
        {
            "case_id": "case-011-lisi-2025",
            "subject": "李四",
            "date": "2025-05-20",
            "institution": "示例体检中心B",
            "tags": ["domain:血常规"],
            "rows": [
                {"name": "WBC", "printed": R("WBC"),
                 "value": B(BAND_IN_RANGE, "wbc-2025")},
                # 与 case-004 的 PLT 配对：贴近下限 → 贴近上限 = 上升
                {"name": "PLT", "printed": R("PLT"),
                 "value": B(BAND_JUST_BELOW_HIGH, "plt-2025")},
            ],
        },
        # ---- 低置信复核：未复核不落库（阴性对照）----
        {
            "case_id": "case-012-lowconf-review",
            "subject": "李四",
            "date": "2025-06-20",
            "institution": "示例体检中心B",
            "tags": ["review:pending_not_stored", "domain:肝功能"],
            "rows": [
                {"name": "ALT", "printed": R("ALT"),
                 "value": B(BAND_IN_RANGE, "alt-2025"),
                 "confidence": "high"},
                # 低置信行（扫描件污损）：**未复核 → 不得落库**。它出现在报告输入里，
                # 但不在 expected 里——这正是阴性对照：实现若照常落库，
                # "输入行数 > 期望落库行数"立即暴露。
                {"name": "AST", "printed": R("AST"),
                 "value": B(BAND_IN_RANGE, "ast-lowconf"),
                 "confidence": "low", "pending_review": True},
            ],
        },
    ]


# ============================================================ 置信度（RNG 派生）


def _confidence(kind: str, key: str) -> float:
    """置信度由确定性流派生（不是区间数值，但同样不许手写——保证可复现）。

    低置信取 [0.10, 0.29]，高置信取 [0.90, 0.99]；阈值本身由 M2 的配置字段定义，
    这里只保证"低置信行明确低、高置信行明确高"。
    """
    rng = _stream("conf:" + key)
    if kind == "low":
        return (10 + rng.below(20)) / 100.0
    if kind == "high":
        return (90 + rng.below(10)) / 100.0
    raise ValueError("未知置信度档位：%r" % (kind,))


# ============================================================ 用例 → 具体输入


def _materialize() -> List[dict]:
    """把用例定义解析成**具体数值**的输入集合（区间、值、置信度全部落地）。"""
    cases = []
    for raw in _case_definitions():
        subject = raw["subject"]
        sex = SEX_BY_SUBJECT[subject]
        rows = []
        for row in raw["rows"]:
            printed = row.get("printed")
            default = row.get("default")
            used = printed if printed is not None else (default if default is not None else None)
            band_spec = row["value"]
            if used is None and band_spec.get("ref") is None:
                raise ValueError(
                    "行 %s/%s 既无区间又无取值参考，取值带无从解析" % (raw["case_id"], row["name"])
                )
            value = _resolve_band(band_spec, used if used is not None else YAML[band_spec["ref"]],
                                  YAML)
            entry = {
                "name": row["name"],
                "unit": row.get("unit", YAML[row["name"]]["unit"]),
                "value": value,
                "printed": printed,
                "default": default,
                "default_constraint": row.get("default_constraint", SEX_ANY),
                "pending_review": bool(row.get("pending_review")),
            }
            if "canonical_unit" in row:
                entry["canonical_unit"] = row["canonical_unit"]
            if "confidence" in row:
                entry["confidence"] = _confidence(row["confidence"], raw["case_id"] + ":" + row["name"])
            rows.append(entry)
        cases.append(
            {
                "case_id": raw["case_id"],
                "subject": subject,
                "sex": sex,
                "date": raw["date"],
                "institution": raw["institution"],
                "tags": list(raw["tags"]),
                "rows": rows,
            }
        )
    return cases


# ============================================================ 报告文本


def _fmt(value) -> str:
    """数值展示：整数不带小数点（保持文本可读且确定）。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _render_report(case: dict) -> str:
    """渲染"文本层可读的合成报告"。

    刻意保持朴素（对齐 PDF 文本层直读形态）：表头 + 逐行"项目 结果 单位 参考区间"。
    参考区间列**按输入如实打印**——没印区间就打印占位符，绝不替报告"补"一个区间
    （那会把"报告未印区间"这一关键形态从输入侧抹掉）。
    """
    lines = [
        "%s 检验报告（合成样例，非真实数据）" % case["institution"],
        "姓名：%s    性别：%s    采样日期：%s" % (case["subject"], case["sex"], case["date"]),
        "本报告为程序生成的合成数据，仅用于软件自检；不构成任何医疗依据。",
        "",
        "项目名称            结果        单位            参考区间",
        "-" * 64,
    ]
    for row in case["rows"]:
        printed = row["printed"]
        if printed is None:
            ref_text = "（未印）"
        else:
            low = "—" if printed["low"] is None else _fmt(printed["low"])
            high = "—" if printed["high"] is None else _fmt(printed["high"])
            ref_text = "%s ~ %s" % (low, high)
        conf_text = ""
        if "confidence" in row:
            conf_text = "  [置信度 %s]" % _fmt(row["confidence"])
        lines.append(
            "%-18s %8s      %-14s  %s%s"
            % (row["name"], _fmt(row["value"]), row["unit"], ref_text, conf_text)
        )
    lines.append("")
    lines.append("说明：参考区间以本机构 LIS 打印为准；本样例为合成数据。")
    return "\n".join(lines) + "\n"


# ============================================================ 真值库


def _range_json(spec: Optional[dict]):
    if spec is None:
        return None
    return {"low": spec["low"], "high": spec["high"], "bounds": spec["bounds"]}


def _build_truth(case: dict) -> dict:
    """真值库：**只存输入与期望**（观测由基准运行时实算）。

    两条关键纪律：
    1. **未复核的低置信行不进 `expected`**——它仍在报告输入里（`pending_review_rows`），
       但期望落库集合不含它。实现若照常落库，"输入行数 > 期望行数"立即暴露。
    2. 期望标记由 `engine.compare()` 实算；"区间是否适用该主体"由
       `engine.range_applies_to()` 实算——不在这里手写第二份判定/适用域口径。
    """
    expected = []
    pending = []
    for row in case["rows"]:
        if row["pending_review"]:
            pending.append(
                {
                    "canonical_name": row["name"],
                    "value": row["value"],
                    "unit": row["unit"],
                    "confidence": row["confidence"],
                    "reason": "低置信行未复核，不得落库",
                }
            )
            continue

        printed = row["printed"]
        default = row["default"]
        # 与引擎 select_range 同源的优先级：自印 > 适用该主体的默认 > 拒判
        if printed is not None:
            source = RANGE_SOURCE_REPORT
            used = printed
        elif default is not None and range_applies_to(row["default_constraint"], case["sex"]):
            source = RANGE_SOURCE_BUILTIN
            used = default
        else:
            source = RANGE_SOURCE_NONE
            used = {"low": None, "high": None, "bounds": BOUNDS_CLOSED}
        flag = compare(row["value"], _to_ref(used))
        if flag not in ALL_FLAGS:
            raise ValueError("实算出未声明的判定态：%r" % (flag,))

        entry = {
            "canonical_name": row["name"],
            "value": row["value"],
            "unit": row.get("canonical_unit", row["unit"]),
            "raw_unit": row["unit"],
            "expected_flag": flag,
            "expected_range_source": source,
            "printed_range": _range_json(printed),
            "default_range": _range_json(default),
            "default_constraint": row["default_constraint"],
        }
        expected.append(entry)

    truth = {
        "case_id": case["case_id"],
        "subject": case["subject"],
        "sex": case["sex"],
        "date": case["date"],
        "institution": case["institution"],
        "tags": list(case["tags"]),
        "expected": expected,
    }
    if pending:
        truth["pending_review_rows"] = pending
    return truth


def _trends_for(cases: List[dict], truths: List[dict]) -> List[dict]:
    """跨日期趋势点：同主体 + 同指标，按日期排序后相邻比较。

    `delta` / `direction` 由 `engine.compare` 的 `trend_delta` / `trend_direction`
    实算——与判定同源，不手写第二份"涨跌"口径。只对**已落库**（非待复核）行计算。
    """
    grouped: Dict[Tuple[str, str], List[dict]] = {}
    for truth in truths:
        for item in truth["expected"]:
            grouped.setdefault((truth["subject"], item["canonical_name"]), []).append(
                {"date": truth["date"], "value": item["value"], "case_id": truth["case_id"]}
            )

    points = []
    for key in sorted(grouped.keys()):  # sorted：不用 set/dict 迭代序
        subject, name = key
        series = sorted(grouped[key], key=lambda item: item["date"])
        for index in range(1, len(series)):
            earlier, later = series[index - 1], series[index]
            delta = trend_delta(earlier["value"], later["value"])
            direction = trend_direction(delta)
            if direction not in ALL_TRENDS:
                raise ValueError("实算出未声明的趋势态：%r" % (direction,))
            points.append(
                {
                    "subject": subject,
                    "canonical_name": name,
                    "from_case": earlier["case_id"],
                    "to_case": later["case_id"],
                    "from_date": earlier["date"],
                    "to_date": later["date"],
                    "from_value": earlier["value"],
                    "to_value": later["value"],
                    "expected_delta": delta,
                    "expected_direction": direction,
                }
            )
    return points


# ============================================================ manifest


def _threshold(dimension, form, minimum, sampled):
    return {"dimension": dimension, "form": form, "minimum": minimum, "sampled": sampled}


def _count_tag(truths, tag):
    return sum(1 for truth in truths if tag in truth["tags"])


def _count_tag_prefix(truths, prefix):
    return sum(1 for truth in truths if any(item.startswith(prefix) for item in truth["tags"]))


def _count_key(counts, key):
    return counts.get(key, 0)


def _build_manifest(cases, truths, trends) -> dict:
    """manifest：覆盖度门槛 + 逐 case 形态登记。**总数/采样数双登记**。

    门槛以**数据**下发（不是代码里的 if）——这样"某个形态没覆盖"是数据事实，
    基准读数据即可判定达标与否，改门槛不必改代码。
    """
    flag_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}
    domain_counts: Dict[str, int] = {}
    for truth in truths:
        for item in truth["expected"]:
            flag_counts[item["expected_flag"]] = flag_counts.get(item["expected_flag"], 0) + 1
            source_counts[item["expected_range_source"]] = (
                source_counts.get(item["expected_range_source"], 0) + 1
            )
        for tag in truth["tags"]:
            if tag.startswith("domain:"):
                domain = tag.split(":", 1)[1]
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

    trend_counts: Dict[str, int] = {}
    for point in trends:
        trend_counts[point["expected_direction"]] = (
            trend_counts.get(point["expected_direction"], 0) + 1
        )

    thresholds = [
        _threshold("指标域", "血常规", 1, _count_key(domain_counts, "血常规")),
        _threshold("指标域", "肝功能", 1, _count_key(domain_counts, "肝功能")),
        _threshold("指标域", "血脂", 1, _count_key(domain_counts, "血脂")),
        _threshold("指标域", "肾功能", 1, _count_key(domain_counts, "肾功能")),
        _threshold("指标域", "血糖", 1, _count_key(domain_counts, "血糖")),
        _threshold("判定形态", "high", 1, _count_key(flag_counts, "high")),
        _threshold("判定形态", "low", 1, _count_key(flag_counts, "low")),
        _threshold("判定形态", "normal", 1, _count_key(flag_counts, "normal")),
        _threshold("判定形态", "not_assessed", 1, _count_key(flag_counts, FLAG_NOT_ASSESSED)),
        _threshold("区间来源", RANGE_SOURCE_REPORT, 1, _count_key(source_counts, RANGE_SOURCE_REPORT)),
        _threshold("区间来源", RANGE_SOURCE_BUILTIN, 1, _count_key(source_counts, RANGE_SOURCE_BUILTIN)),
        _threshold("区间来源", RANGE_SOURCE_NONE, 1, _count_key(source_counts, RANGE_SOURCE_NONE)),
        _threshold("自印覆盖默认值", "结论相反", 1, _count_tag(truths, "priority:printed_overrides_default")),
        _threshold("边界形态", "threshold_exact", 1, _count_tag_prefix(truths, "boundary:threshold_exact")),
        _threshold("边界形态", "near_miss", 1, _count_tag_prefix(truths, "boundary:near_miss")),
        _threshold("边界形态", "bounds_open", 1, _count_tag_prefix(truths, "bounds:open")),
        _threshold("趋势点", "up", 1, _count_key(trend_counts, "up")),
        _threshold("趋势点", "down", 1, _count_key(trend_counts, "down")),
        _threshold("趋势点", "flat", 1, _count_key(trend_counts, "flat")),
        _threshold("低置信复核", "未复核不落库（阴性对照）", 1,
                   _count_tag(truths, "review:pending_not_stored")),
        _threshold("单位变体", "同量纲归一", 1, _count_tag(truths, "unit:variant")),
        _threshold("性别相关", "applies_to.sex 生效", 1, _count_tag(truths, "sex:applies")),
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generator_seed": SEED,
        "coverage_note": (
            "**抽样覆盖，非穷举**：本表逐行登记「下限」与「实际采样数」，采样数 ≥ 下限即达标；"
            "采样数只说明「该形态出现过」，不等于穷举了该形态。"
        ),
        "thresholds": thresholds,
        "totals": {
            "cases": len(cases),
            "measurements": sum(len(truth["expected"]) for truth in truths),
            "trend_points": len(trends),
        },
        "coverage": {
            "flags": _sorted(flag_counts),
            "range_sources": _sorted(source_counts),
            "domains": _sorted(domain_counts),
            "trend_directions": _sorted(trend_counts),
        },
        "cases": [
            {
                "case_id": truth["case_id"],
                "subject": truth["subject"],
                "sex": truth["sex"],
                "date": truth["date"],
                "institution": truth["institution"],
                "tags": truth["tags"],
                "measurements": len(truth["expected"]),
                "pending_review_rows": len(truth.get("pending_review_rows", [])),
                "files": {
                    "report": "cases/%s.txt" % truth["case_id"],
                    "truth": "truth/%s.truth.json" % truth["case_id"],
                },
            }
            for truth in truths
        ],
    }


def _sorted(counts: Dict[str, int]) -> dict:
    return {key: counts[key] for key in sorted(counts)}


# ============================================================ 组装 / 写盘 / 校验


def build_all() -> Dict[str, bytes]:
    """算出全部产物内容（不写盘）：{相对路径: bytes}。"""
    cases = _materialize()
    truths = [_build_truth(case) for case in cases]
    trends = _trends_for(cases, truths)
    _assert_trend_tags_match(truths, trends)

    by_case = {truth["case_id"]: truth for truth in truths}
    for point in trends:
        by_case[point["to_case"]].setdefault("expected_trends", []).append(point)

    files: Dict[str, bytes] = {}
    for case, truth in zip(cases, truths):
        files["cases/%s.txt" % case["case_id"]] = _render_report(case).encode("utf-8")
        files["truth/%s.truth.json" % case["case_id"]] = to_json_bytes(truth)
    files["manifest.json"] = to_json_bytes(_build_manifest(cases, truths, trends))
    return files


def _assert_trend_tags_match(truths: List[dict], trends: List[dict]) -> None:
    """声明的 `trend:*` 标签必须被**实算**出的趋势方向覆盖（declared ⊆ computed）。

    没有这条，"tags 里写了 trend:up 但数据其实是下降"会静默通过——覆盖度表会被
    读成达标而实际形态并不存在。判据 = 标签只是**声明**，方向由
    `engine.trend_direction` 实算，声明不得凭空出现。

    只要求包含关系（不要求相等）：一个用例可以"顺带"产生非头条的趋势
    （如边界用例的相邻期恰好在同一指标上形成下降），那是数据事实，不是错误。
    """
    actual: Dict[str, set] = {}
    for point in trends:
        actual.setdefault(point["to_case"], set()).add(point["expected_direction"])
    for truth in truths:
        declared = {
            tag.split(":", 1)[1] for tag in truth["tags"] if tag.startswith("trend:")
        }
        computed = actual.get(truth["case_id"], set())
        phantom = declared - computed
        if phantom:
            raise ValueError(
                "用例 %s 声明了实算不存在的趋势方向 %s（实算 %s）"
                % (truth["case_id"], sorted(phantom), sorted(computed) or "无")
            )


def _path_for(name: str) -> str:
    return os.path.join(SAMPLES_DIR, name.replace("/", os.sep))


def generate() -> List[str]:
    """生成（覆盖）全部产物，返回写出的相对路径列表（一律经原子写盘单点）。"""
    files = build_all()
    for name in sorted(files):
        write_atomic(_path_for(name), files[name])
    return sorted(files)


def check() -> Tuple[bool, List[str]]:
    """位级一致校验：再生成的内容与磁盘现有产物**逐字节**比对。

    这比"重跑生成器不报错"强得多——后者在产物被手改后照样通过。
    """
    files = build_all()
    problems = []
    for name in sorted(files):
        path = _path_for(name)
        if not os.path.isfile(path):
            problems.append("缺失：%s" % name)
            continue
        with open(path, "rb") as handle:
            on_disk = handle.read()
        if on_disk != files[name]:
            problems.append(
                "字节不一致：%s（磁盘 %d 字节 vs 再生成 %d 字节）"
                % (name, len(on_disk), len(files[name]))
            )
    return (not problems), problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="合成样例集确定性生成器")
    parser.add_argument("--check", action="store_true", help="只校验再生成与现有产物位级一致")
    args = parser.parse_args(argv)

    if args.check:
        ok, problems = check()
        if not ok:
            sys.stderr.write("位级一致校验失败：\n")
            for item in problems:
                sys.stderr.write("  · %s\n" % item)
            return 1
        print("位级一致校验通过：%d 个产物与再生成逐字节一致。" % len(build_all()))
        return 0

    written = generate()
    print("已生成 %d 个产物到 data/samples/：" % len(written))
    for name in written:
        print("  · %s" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
