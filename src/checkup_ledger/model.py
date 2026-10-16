"""统一中间表示（IR）。

全链路只有四个 dataclass，两侧输入（PDF 文本层 / OCR）都归约到 `RawLine`，
后续层只认这几个类型——比对问题因此变成结构化对齐。

分层：本模块是纯数据定义，不 import 任何 I/O。
"""

from dataclasses import dataclass, field
from typing import List, Optional

# ---- 判定四态（口径见 data/README.md 第五节第 1/2 条）----
FLAG_HIGH = "high"
FLAG_LOW = "low"
FLAG_NORMAL = "normal"
FLAG_NOT_ASSESSED = "not_assessed"  # 拒判：无可用区间，只展示趋势

ALL_FLAGS = (FLAG_HIGH, FLAG_LOW, FLAG_NORMAL, FLAG_NOT_ASSESSED)

# ---- 区间来源三态（三级优先）----
RANGE_SOURCE_REPORT = "report_printed"  # ① 报告自印区间（最优先）
RANGE_SOURCE_BUILTIN = "builtin_default"  # ② 内置来源标注默认值
RANGE_SOURCE_NONE = "none"  # ③ 无区间 → 拒判

ALL_RANGE_SOURCES = (
    RANGE_SOURCE_REPORT,
    RANGE_SOURCE_BUILTIN,
    RANGE_SOURCE_NONE,
)

# ---- 边界语义 ----
BOUNDS_CLOSED = "closed"  # [low, high]
BOUNDS_OPEN = "open"  # (low, high)

ALL_BOUNDS = (BOUNDS_CLOSED, BOUNDS_OPEN)

# ---- 趋势三态（口径见 data/README.md 第五节第 3 条）----
TREND_UP = "up"
TREND_DOWN = "down"
TREND_FLAT = "flat"

ALL_TRENDS = (TREND_UP, TREND_DOWN, TREND_FLAT)

# ---- 适用域（主体限制）：条目自带的主体约束，不得用 any 掩盖 ----
# 定义在 model（纯数据层）而非 loader：判定内核不得 import loader（loader 含文件 I/O，
# 会让"纯函数"门禁失效），但"适用域"又是判定必须遵守的口径，故常量落在两侧都能安全引用处。
SEX_ANY = "any"
SEX_MALE = "male"
SEX_FEMALE = "female"

ALL_SEX = (SEX_ANY, SEX_MALE, SEX_FEMALE)


@dataclass(frozen=True)
class Note:
    """显式注记：把"没看到 / 看到了但没抽到 / 认不出"说出来，不静默丢。"""

    code: str
    message: str
    count: int = 1


@dataclass(frozen=True)
class RawLine:
    """模块① 产出：行级草稿。只做抽取，不做任何数值语义判断。"""

    page: int
    line_no: int
    text: str
    confidence: float
    source_file: str


@dataclass(frozen=True)
class RefRange:
    """参考区间。`source` 记录它从哪来（三级优先的依据）。"""

    low: Optional[float]
    high: Optional[float]
    bounds: str = BOUNDS_CLOSED
    source: str = RANGE_SOURCE_NONE


@dataclass(frozen=True)
class Measurement:
    """模块② 产出：规范化后的单条指标记录。"""

    canonical_name: str
    raw_name: str
    value: float
    unit: str
    raw_unit: str = ""
    ref_range_printed: Optional[RefRange] = None  # 报告自印区间（可空）
    line_ref: Optional[RawLine] = None
    reviewed: bool = True  # 低置信行复核后才为 True


@dataclass(frozen=True)
class Judged:
    """模块③ 产出：判定结果。只含事实数值与标记，不含任何解读。"""

    measurement: Measurement
    flag: str
    range_used: RefRange
    range_source: str


@dataclass(frozen=True)
class TrendPoint:
    """跨日期的同指标变化。只陈述事实幅度。"""

    canonical_name: str
    date: str
    value: float
    delta: Optional[float] = None
    delta_pct: Optional[float] = None


@dataclass(frozen=True)
class ReviewRecord:
    """模块① 复核留痕：**原始行 → 人工确认值**的对应关系，可审计。

    为什么要有这一条：低置信行放行是"人工背书"的结果，必须能回答
    "当时看到的是什么、改成了什么、依据是什么"。只记一个 `reviewed=True`
    等于没留痕——出了错无从追溯，也无法判断"改对了没有"。

    `line_ref` 直接持有 `RawLine`（而非只存行号）：留痕与原始行是**同一实体**，
    分开存会在序列化/搬运时错位（对不上的留痕 = 没留痕）。
    """

    line_ref: RawLine
    original_text: str
    confirmed_text: str
    reviewer_note: str = ""


@dataclass
class IngestResult:
    lines: List[RawLine] = field(default_factory=list)
    engine: str = ""
    pending_review: List[RawLine] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)


@dataclass
class NormalizeResult:
    measurements: List[Measurement] = field(default_factory=list)
    pending_mapping: List[object] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)
