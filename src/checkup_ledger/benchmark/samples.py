"""样例驱动基准层：读 `data/samples/`（报告 + 植入真值 + manifest），跑真值回归。

**与规则驱动层（`runner.py`）分层**，两层各治一类病：
- 规则驱动层（`cases.json`，随包）：**不读真值库**，专治"样本没覆盖到的端点"
  ——它手工枚举四态/边界/优先级的组合，样本集没长到的地方它仍在测；
- 样例驱动层（本模块，`data/samples/`）：读植入真值，验"端到端判定与真值一致"
  ——它治的是"引擎在真实形态的报告输入上是否仍正确"。

两层都必须存在：只有规则层 → 覆盖的是想象出来的形态；只有样例层 → 真值本身
可能有盲区（样本没覆盖的端点无人测）。

三条纪律（与 `runner.py` 同源）：
1. **观测由引擎运行时实算**：真值库只给"输入与期望"，实得标记由 `judge()` 现算；
   真值库出现 `observed`/`actual`/`got` 字段即由守门测试拦下。
2. **未启用不冒充通过**：`--only` 未选中的套件标 `not_enabled`，不计入通过数。
3. **覆盖度门槛以 manifest 下发**（数据非代码）：读 `manifest.json` 的 `thresholds`，
   逐行比对 `sampled >= minimum`——某形态没覆盖是**数据事实**，不是代码里的 if。
"""

import json
import os
from typing import Dict, List, Optional, Tuple

from checkup_ledger.engine.compare import judge
from checkup_ledger.model import (
    ALL_FLAGS,
    ALL_RANGE_SOURCES,
    BOUNDS_CLOSED,
    Measurement,
    RANGE_SOURCE_REPORT,
    RefRange,
)

SUITE_NAME = "样例真值回归"
COVERAGE_SUITE_NAME = "覆盖度门槛"
MANIFEST_FILENAME = "manifest.json"

# 真值库禁用的观测类字段名（出现即视为"冻结了观测"→ 基准退化成比对两份答案）
FORBIDDEN_TRUTH_FIELDS = ("observed", "actual", "got", "computed", "result")


class SampleDataError(RuntimeError):
    """样例数据缺失或结构非法。"""


_ENV_OVERRIDE = "CHECKUP_LEDGER_SAMPLES"


def samples_root(explicit=None) -> str:
    """样例集根目录。

    `data/samples/` 按 plan/04 是**开发期资产**（不随包分发），故解析顺序：
    1. 显式传参；
    2. 环境变量 `CHECKUP_LEDGER_SAMPLES`；
    3. **源码检出**：从本包位置回溯到仓库根再取 `data/samples/`
       （`<repo>/src/checkup_ledger/benchmark/` → 上溯三级到 `<repo>`）。
    安装态（site-packages）下这三条都可能落空——那时由 `samples_available()`
    如实报"本层数据不可用"，**不伪造通过**（见 run_sample_bench）。
    """
    if explicit:
        return os.path.abspath(os.fspath(explicit))
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        return os.path.abspath(override)
    here = os.path.dirname(os.path.abspath(__file__))          # .../src/checkup_ledger/benchmark
    package_dir = os.path.dirname(here)                        # .../src/checkup_ledger
    src_dir = os.path.dirname(package_dir)                     # .../src
    repo_root = os.path.dirname(src_dir)                       # <repo>
    return os.path.join(repo_root, "data", "samples")


def samples_available(root=None) -> bool:
    """本层数据是否可用（manifest 在位即视为可用）。"""
    return os.path.isfile(os.path.join(samples_root(root), MANIFEST_FILENAME))


def _read_json(path: str):
    if not os.path.isfile(path):
        raise SampleDataError("样例文件不存在：%s" % path)
    with open(path, "r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except ValueError as exc:
            raise SampleDataError("样例 JSON 解析失败（%s）：%s" % (path, exc))


def load_manifest(root: str) -> dict:
    manifest = _read_json(os.path.join(root, MANIFEST_FILENAME))
    if not isinstance(manifest, dict):
        raise SampleDataError("manifest 根节点应为对象")
    if manifest.get("schema_version") != 1:
        raise SampleDataError("不支持的 manifest schema_version：%r" % (manifest.get("schema_version"),))
    return manifest


def load_truths(root: str, manifest: dict) -> List[dict]:
    """读全部真值文件（路径由 manifest 登记——不靠目录遍历猜）。"""
    truths = []
    for case in manifest.get("cases", []):
        rel = case.get("files", {}).get("truth")
        if not rel:
            raise SampleDataError("manifest 的 case %r 未登记真值文件" % (case.get("case_id"),))
        truths.append(_read_json(os.path.join(root, rel.replace("/", os.sep))))
    if not truths:
        raise SampleDataError("manifest 未登记任何用例")
    return truths


def _scan_forbidden_fields(node, path: str, offenders: List[str]) -> None:
    """递归扫描真值库字段名：出现观测类字段即记违规。"""
    if isinstance(node, dict):
        for key in sorted(node.keys()):
            if key in FORBIDDEN_TRUTH_FIELDS:
                offenders.append("%s.%s" % (path, key))
            _scan_forbidden_fields(node[key], "%s.%s" % (path, key), offenders)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _scan_forbidden_fields(item, "%s[%d]" % (path, index), offenders)


def find_observed_fields(truth: dict) -> List[str]:
    """该真值文件里出现的观测类字段（空列表 = 合规）。"""
    offenders: List[str] = []
    _scan_forbidden_fields(truth, truth.get("case_id", "truth"), offenders)
    return offenders


def _build_ref(raw) -> Optional[RefRange]:
    if raw is None:
        return None
    return RefRange(
        low=None if raw.get("low") is None else float(raw["low"]),
        high=None if raw.get("high") is None else float(raw["high"]),
        bounds=raw.get("bounds", BOUNDS_CLOSED),
    )


def _run_case(truth: dict, fault: Optional[str] = None) -> List[str]:
    """逐条实算观测（**不读预先算好的答案**）并比对期望。"""
    failures = []
    case_id = truth.get("case_id", "<无 case_id>")
    sex = truth.get("sex")

    for index, item in enumerate(truth.get("expected", [])):
        where = "%s[%d] %s" % (case_id, index, item.get("canonical_name"))
        printed = _build_ref(item.get("printed_range"))
        if printed is not None:
            printed = RefRange(low=printed.low, high=printed.high, bounds=printed.bounds,
                               source=RANGE_SOURCE_REPORT)
        default = _build_ref(item.get("default_range"))
        constraint = item.get("default_constraint", "any")

        measurement = Measurement(
            canonical_name=item["canonical_name"],
            raw_name=item.get("canonical_name"),
            value=float(item["value"]),
            unit=item.get("unit", ""),
            raw_unit=item.get("raw_unit", item.get("unit", "")),
            ref_range_printed=printed,
        )
        judged = judge(measurement, default, subject_sex=sex, default_constraint=constraint)
        actual_flag, actual_source = judged.flag, judged.range_source

        if fault is not None:
            actual_flag = _FAULT_HOOKS[fault](actual_flag)

        if actual_flag not in ALL_FLAGS:
            failures.append("%s：实算出未声明的判定态 %r" % (where, actual_flag))
        if actual_source not in ALL_RANGE_SOURCES:
            failures.append("%s：实算出未声明的区间来源 %r" % (where, actual_source))
        if actual_flag != item["expected_flag"]:
            failures.append(
                "%s：flag 期望 %s，实得 %s" % (where, item["expected_flag"], actual_flag)
            )
        if actual_source != item["expected_range_source"]:
            failures.append(
                "%s：range_source 期望 %s，实得 %s"
                % (where, item["expected_range_source"], actual_source)
            )
    return failures


# ---- 探活：注入缺陷的钩子（与规则层同形态：只污染 flag）----
def _fault_force_normal(_actual_flag: str) -> str:
    """缺陷：把任何判定都当正常——最常见的"假合规"实现错误。"""
    from checkup_ledger.model import FLAG_NORMAL

    return FLAG_NORMAL


_FAULT_HOOKS = {"force_normal": _fault_force_normal}

PROBE_FAULT_KIND = "force_normal"


def run_coverage_gate(manifest: dict) -> Tuple[bool, List[str], List[dict]]:
    """覆盖度门槛：读 manifest 的 thresholds 逐行比对（**数据下发，非代码硬编码**）。"""
    thresholds = manifest.get("thresholds")
    if not isinstance(thresholds, list) or not thresholds:
        raise SampleDataError("manifest 缺 thresholds 覆盖度门槛表")
    failures = []
    rows = []
    for item in thresholds:
        dimension = item.get("dimension")
        form = item.get("form")
        minimum = item.get("minimum")
        sampled = item.get("sampled")
        if not isinstance(minimum, int) or not isinstance(sampled, int):
            raise SampleDataError("门槛行 %s/%s 的 minimum/sampled 应为整数" % (dimension, form))
        ok = sampled >= minimum
        rows.append(
            {"dimension": dimension, "form": form, "minimum": minimum, "sampled": sampled, "met": ok}
        )
        if not ok:
            failures.append("%s/%s：采样 %d < 下限 %d" % (dimension, form, sampled, minimum))
    return (not failures), failures, rows


def run_sample_bench(root=None, only=None, probe_fault=False, strict: bool = True) -> dict:
    """跑样例驱动层。返回机读报告（与规则层同结构，便于 CLI 统一渲染）。

    - `only` 未命中的套件标 `not_enabled`（**不计入通过数**）；
    - `only` 给了本层不存在的套件名 → `strict=True` 时 ValueError（用法错误，CLI 转
      exit 2）；`strict=False` 时本层整体标 `not_enabled`（该名属另一层，由分层调度器
      做全局校验并负责报错）；
    - `probe_fault=True` → 注入已知缺陷，**必须报未达标**。
    """
    base = samples_root(root)
    known = (SUITE_NAME, COVERAGE_SUITE_NAME)
    if only is not None and only not in known:
        if strict:
            raise ValueError("未知名套件：%r（已知：%s）" % (only, "、".join(known)))
        return _all_not_enabled(known, only)

    # 样例集是**开发期资产**（plan/04），安装态/冻结态下不存在。数据不可用时
    # **如实标未启用并说明原因**，绝不伪造通过（"没数据"与"跑了没过"是两回事）。
    if not samples_available(base):
        return _data_unavailable(known, base)

    manifest = load_manifest(base)
    truths = load_truths(base, manifest)

    fault = PROBE_FAULT_KIND if probe_fault else None
    suites = []
    total = 0
    passed_count = 0

    # ---- 套件 A：样例真值回归 ----
    if only is not None and only != SUITE_NAME:
        suites.append(_not_enabled(SUITE_NAME, only))
    else:
        failures = []
        # 真值库字段守门：出现观测类字段 → 直接判不达标（基准已退化）
        for truth in truths:
            offenders = find_observed_fields(truth)
            if offenders:
                failures.append(
                    "%s：真值库出现观测类字段（%s）——基准会退化成比对两份预置答案"
                    % (truth.get("case_id"), ", ".join(offenders))
                )
        for truth in truths:
            failures.extend(_run_case(truth, fault=fault))

        # 用例数 = 全部期望条目数
        case_total = sum(len(truth.get("expected", [])) for truth in truths)
        total += case_total
        passed_count += case_total - len(failures)
        notes = ""
        if fault is not None:
            notes = "探活：已注入缺陷 %s——本套件必须报未达标，否则说明基准空转" % fault
        suites.append(
            {
                "name": SUITE_NAME,
                "not_enabled": False,
                "notes": notes,
                "total": case_total,
                "passed_count": case_total - len(failures),
                "passed": not failures,
                "failures": failures,
            }
        )

    # ---- 套件 B：覆盖度门槛 ----
    if only is not None and only != COVERAGE_SUITE_NAME:
        suites.append(_not_enabled(COVERAGE_SUITE_NAME, only))
    else:
        gate_ok, gate_failures, rows = run_coverage_gate(manifest)
        total += len(rows)
        passed_count += len(rows) - len(gate_failures)
        suites.append(
            {
                "name": COVERAGE_SUITE_NAME,
                "not_enabled": False,
                "notes": "覆盖度门槛由 manifest 下发（数据非代码）；%s"
                % manifest.get("coverage_note", ""),
                "total": len(rows),
                "passed_count": len(rows) - len(gate_failures),
                "passed": gate_ok,
                "failures": gate_failures,
                "rows": rows,
            }
        )

    enabled = [s for s in suites if not s["not_enabled"]]
    passed = bool(enabled) and all(s["passed"] for s in enabled)

    return {
        "layer": "samples",
        "passed": passed,
        "total": total,
        "passed_count": passed_count,
        "suites": suites,
        "probe_fault": fault,
        "notes": (
            "覆盖声明：本层为**采样覆盖，非穷举**——逐条真值见 data/samples/truth/。"
            if only is None
            else "覆盖声明：本次为 --only 单套件运行，其余套件未启用（未启用不计入通过数）。"
        ),
    }


def _not_enabled(name: str, only: str) -> dict:
    return {
        "name": name,
        "not_enabled": True,
        "notes": "本套件未启用（--only 选择了 %s）；未启用不等于通过" % only,
        "total": 0,
        "passed_count": 0,
        "passed": False,
        "failures": [],
    }


def _all_not_enabled(known, only) -> dict:
    """整层未启用：`only` 选了别的层的套件名。不计入通过数。"""
    return {
        "layer": "samples",
        "passed": False,
        "total": 0,
        "passed_count": 0,
        "probe_fault": None,
        "data_available": True,
        "suites": [
            {
                "name": name,
                "not_enabled": True,
                "notes": "本套件未启用（--only 选择了 %s，属另一层）；未启用不等于通过" % only,
                "total": 0,
                "passed_count": 0,
                "passed": False,
                "failures": [],
            }
            for name in known
        ],
        "notes": "本层未启用（--only 选择了另一层的套件）。",
    }


def _data_unavailable(known, base) -> dict:
    """样例集不在位（安装态/冻结态）：**如实标未启用**，不伪造通过。

    "本层数据不可用"与"跑了没过"是同码不同义的两件事——文本必须可区分，
    且两者都**不计入通过数**（否则"没有数据"会被读成"全部通过"）。
    """
    reason = (
        "样例集不在位：%s。`data/samples/` 按 plan/04 是**开发期资产**（不随包分发），"
        "安装态/冻结态下不可用；请在源码检出内运行，或用 CHECKUP_LEDGER_SAMPLES 指向样例集。"
        % base
    )
    return {
        "layer": "samples",
        "passed": False,
        "total": 0,
        "passed_count": 0,
        "probe_fault": None,
        "data_available": False,
        "suites": [
            {
                "name": name,
                "not_enabled": True,
                "notes": reason,
                "total": 0,
                "passed_count": 0,
                "passed": False,
                "failures": [],
            }
            for name in known
        ],
        "notes": "本层未启用：样例集不在位（这不是「未达标」，而是「无数据可跑」）。",
    }


def suite_names(root=None) -> list:
    """本层（样例驱动层）的套件名列表——供分层调度器做 `--only` 全局校验。"""
    return [SUITE_NAME, COVERAGE_SUITE_NAME]
