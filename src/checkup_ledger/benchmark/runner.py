"""内置基准套件：判定契约的可证伪回归。

**用例是数据，不是代码**：全部用例从 `cases.json` 读取（随包分发），源码里不出现
任何区间数值——这样"判定数值只能来自数据"的纪律在基准侧也成立。

四个设计要点（缺一即"假基准"）：
1. **可证伪探活**：`--probe-fault` 注入一个已知缺陷，基准**必须**报未达标。
   永远全绿的基准证明不了任何事——它只是没在测东西。
2. **未启用不冒充通过**：`--only` 未选中的套件标 `not_enabled` + notes，
   不计入通过数；"整套件未启用"与"跑了没过"是**同码不同义**，文本可区分。
3. **真值只存输入与期望**：用例表是"输入 → 期望"，观测由引擎**运行时实算**。
   不存 `observed` 类字段，否则基准退化成比对两份预先算好的答案。
4. **边界形态双向**：`threshold_exact`（恰在边界）与 `near_miss`（差一点）
   都必须有用例——没有它们，边界开闭语义从未被测过。
"""

import json
import os
from typing import Callable, Dict, List, Optional

from checkup_ledger.model import (
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_NOT_ASSESSED,
    BOUNDS_CLOSED,
    Measurement,
    RANGE_SOURCE_BUILTIN,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
    RefRange,
)
from checkup_ledger.engine.compare import judge

CASES_FILENAME = "cases.json"

_REQUIRED_CASE_FIELDS = ("case_id", "canonical_name", "value", "expected_flag", "expected_source")
_VALID_FLAGS = (FLAG_HIGH, FLAG_LOW, FLAG_NORMAL, FLAG_NOT_ASSESSED)
_VALID_SOURCES = (RANGE_SOURCE_REPORT, RANGE_SOURCE_BUILTIN, RANGE_SOURCE_NONE)


class BenchDataError(RuntimeError):
    """基准数据文件缺失或结构非法。"""


class Case:
    """一个基准用例：输入 + 期望（**不含观测**）。"""

    __slots__ = ("case_id", "measurement", "default", "expected_flag", "expected_source", "why")

    def __init__(self, case_id, measurement, default, expected_flag, expected_source, why=""):
        self.case_id = case_id
        self.measurement = measurement
        self.default = default
        self.expected_flag = expected_flag
        self.expected_source = expected_source
        self.why = why


def _build_range(raw) -> Optional[RefRange]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BenchDataError("区间应为映射或 null，实为 %r" % (raw,))
    bounds = raw.get("bounds", BOUNDS_CLOSED)
    low = raw.get("low")
    high = raw.get("high")
    return RefRange(
        low=None if low is None else float(low),
        high=None if high is None else float(high),
        bounds=bounds,
    )


def _build_case(raw: dict, where: str) -> Case:
    for field in _REQUIRED_CASE_FIELDS:
        if field not in raw:
            raise BenchDataError("%s 缺必填字段 %s" % (where, field))
    if raw["expected_flag"] not in _VALID_FLAGS:
        raise BenchDataError("%s.expected_flag 非法：%r" % (where, raw["expected_flag"]))
    if raw["expected_source"] not in _VALID_SOURCES:
        raise BenchDataError("%s.expected_source 非法：%r" % (where, raw["expected_source"]))

    printed = _build_range(raw.get("printed_range"))
    if printed is not None:
        printed = RefRange(low=printed.low, high=printed.high, bounds=printed.bounds,
                           source=RANGE_SOURCE_REPORT)

    measurement = Measurement(
        canonical_name=str(raw["canonical_name"]),
        raw_name=str(raw.get("raw_name", raw["canonical_name"])),
        value=float(raw["value"]),
        unit=str(raw.get("unit", "")),
        raw_unit=str(raw.get("raw_unit", raw.get("unit", ""))),
        ref_range_printed=printed,
    )
    return Case(
        case_id=str(raw["case_id"]),
        measurement=measurement,
        default=_build_range(raw.get("default_range")),
        expected_flag=raw["expected_flag"],
        expected_source=raw["expected_source"],
        why=str(raw.get("why", "")),
    )


def cases_path(explicit=None) -> str:
    """用例数据文件路径。"""
    if explicit:
        return os.path.abspath(os.fspath(explicit))
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CASES_FILENAME)


def load_suites(path=None) -> "tuple":
    """读用例数据 → (套件名列表, {套件名: [Case]})。"""
    target = cases_path(path)
    if not os.path.isfile(target):
        raise BenchDataError("基准用例文件不存在：%s" % target)
    with open(target, "r", encoding="utf-8") as handle:
        try:
            root = json.load(handle)
        except ValueError as exc:
            raise BenchDataError("基准用例 JSON 解析失败：%s" % exc)

    if not isinstance(root, dict):
        raise BenchDataError("基准用例根节点应为对象")
    if root.get("schema_version") != 1:
        raise BenchDataError("不支持的 schema_version：%r" % (root.get("schema_version"),))

    raw_suites = root.get("suites")
    if not isinstance(raw_suites, list) or not raw_suites:
        raise BenchDataError("suites 应为非空列表")

    order: List[str] = []
    table: Dict[str, List[Case]] = {}
    for index, raw_suite in enumerate(raw_suites):
        where = "suites[%d]" % index
        if not isinstance(raw_suite, dict) or not isinstance(raw_suite.get("name"), str):
            raise BenchDataError("%s 缺 name" % where)
        name = raw_suite["name"]
        if name in table:
            raise BenchDataError("套件名重复：%s" % name)
        raw_cases = raw_suite.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise BenchDataError("套件 %s 的 cases 应为非空列表" % name)
        table[name] = [
            _build_case(item, "%s.cases[%d]" % (name, i)) for i, item in enumerate(raw_cases)
        ]
        order.append(name)
    return order, table


# ---- 探活：注入缺陷的钩子 ----
# 让"注入后基准必须报未达标"成为可执行事实，而不是一句声明。
# 缺陷只污染 flag、不改 range_source——若基准只比对来源而放过 flag，
# 注入后仍会全绿，那才是真正的假基准。
def _fault_force_normal(_actual_flag: str, _expected_flag: str, _case_id: str) -> str:
    """缺陷：把任何判定都当正常——最常见的"假合规"实现错误。"""
    return FLAG_NORMAL


_FAULT_HOOKS: Dict[str, Callable[[str, str, str], str]] = {"force_normal": _fault_force_normal}

PROBE_FAULT_KIND = "force_normal"


def _run_case(case: Case, fault: Optional[str] = None) -> List[str]:
    """观测由引擎**运行时实算**（不读预先算好的答案）。"""
    judged = judge(case.measurement, case.default)
    actual_flag = judged.flag
    actual_source = judged.range_source

    if fault is not None:
        actual_flag = _FAULT_HOOKS[fault](actual_flag, case.expected_flag, case.case_id)
        # 探活缺陷只污染 flag，不改 range_source——这正是"注入一个已知缺陷"的形态：
        # 若基准只比对 source 而放过 flag，注入后仍会全绿（＝假基准）。

    failures = []
    if actual_flag != case.expected_flag:
        failures.append(
            "flag 期望 %s，实得 %s（%s）" % (case.expected_flag, actual_flag, case.why)
        )
    if actual_source != case.expected_source:
        failures.append("range_source 期望 %s，实得 %s" % (case.expected_source, actual_source))
    return failures


def run_bench(only: Optional[str] = None, probe_fault: bool = False, cases_file=None) -> dict:
    """跑基准。返回机读报告（可写 JSON）。

    - `only` 未命中的套件标 `not_enabled`（**不计入通过数**）；
    - `only` 给了一个不存在的套件名 → ValueError（用法错误，CLI 转 exit 2）；
    - `probe_fault=True` → 注入已知缺陷，**基准必须报未达标**。
    """
    order, table = load_suites(cases_file)

    if only is not None and only not in table:
        raise ValueError("未知名套件：%r（已知：%s）" % (only, "、".join(order)))

    fault = PROBE_FAULT_KIND if probe_fault else None
    suites = []
    total = 0
    passed_count = 0

    for name in order:
        cases = table[name]
        if only is not None and name != only:
            suites.append(
                {
                    "name": name,
                    "not_enabled": True,
                    "notes": "本套件未启用（--only 选择了 %s）；未启用不等于通过" % only,
                    "total": 0,
                    "passed_count": 0,
                    "passed": False,
                    "failures": [],
                }
            )
            continue

        failures = []
        for case in cases:
            case_failures = _run_case(case, fault=fault)
            if case_failures:
                failures.append("%s：%s" % (case.case_id, "；".join(case_failures)))

        total += len(cases)
        passed_count += len(cases) - len(failures)
        notes = ""
        if fault is not None:
            notes = "探活：已注入缺陷 %s——本套件必须报未达标，否则说明基准空转" % fault
        suites.append(
            {
                "name": name,
                "not_enabled": False,
                "notes": notes,
                "total": len(cases),
                "passed_count": len(cases) - len(failures),
                "passed": not failures,
                "failures": failures,
            }
        )

    enabled = [s for s in suites if not s["not_enabled"]]
    passed = bool(enabled) and all(s["passed"] for s in enabled)

    return {
        "passed": passed,
        "total": total,
        "passed_count": passed_count,
        "suites": suites,
        "probe_fault": fault,
        "notes": (
            "覆盖声明：本基准为**采样覆盖，非穷举**——逐条用例见 cases.json。"
            if only is None
            else "覆盖声明：本次为 --only 单套件运行，其余套件未启用（未启用不计入通过数）。"
        ),
    }
