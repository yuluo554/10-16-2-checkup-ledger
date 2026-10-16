"""基准分层调度：规则驱动层 + 样例驱动层，两层各治一类病。

为什么要分层（不是"多写点用例"）：
- **规则驱动层**（`runner.py` + 随包 `cases.json`）：手工枚举四态/边界/优先级的组合，
  **不读真值库**。它治"样本没覆盖到的端点"——样本集再大也可能漏某个组合，
  这一层用穷举式枚举兜住。
- **样例驱动层**（`samples.py` + `data/samples/`）：读植入真值，验端到端判定。
  它治"引擎在真实形态的报告输入上是否仍正确"——规则层的用例是想象出来的形态，
  这一层是"报告长什么样就怎么喂"。

只有规则层 → 测的是想象的形态；只有样例层 → 真值可能有盲区。两层并存且都注册进
`--only` 白名单，才是完整基准。

`--only` 是**跨层全局校验**：给的套件名在两层都不存在才报用法错误（exit 2）——
若只在某一层校验，另一层的套件名会被误判成"不存在"。
"""

from typing import Optional

from checkup_ledger.benchmark import runner as rules_layer
from checkup_ledger.benchmark import samples as samples_layer


def all_suite_names(cases_file=None, samples_root=None) -> list:
    """两层全部套件名（跨层 `--only` 白名单的唯一来源）。"""
    names = list(rules_layer.suite_names(cases_file))
    names.extend(samples_layer.suite_names(samples_root))
    return names


def run_layered_bench(only: Optional[str] = None, probe_fault: bool = False,
                      cases_file=None, samples_root=None) -> dict:
    """跑两层基准并聚合。返回机读报告（含逐层明细与顶层结论）。

    用法错误（`only` 在两层都不存在）→ ValueError，由 CLI 转 exit 2。
    """
    known = all_suite_names(cases_file, samples_root)
    if only is not None and only not in known:
        raise ValueError("未知名套件：%r（已知：%s）" % (only, "、".join(known)))

    # strict=False：套件名可能属于另一层，由上面的全局校验负责报错，
    # 单层不再重复抛（否则 --only 选另一层套件时会误报用法错误）。
    rules_report = rules_layer.run_bench(
        only=only, probe_fault=probe_fault, cases_file=cases_file, strict=False
    )
    samples_report = samples_layer.run_sample_bench(
        root=samples_root, only=only, probe_fault=probe_fault, strict=False
    )

    layers = [rules_report, samples_report]
    enabled_suites = [
        suite for layer in layers for suite in layer["suites"] if not suite.get("not_enabled")
    ]
    total = sum(suite["total"] for suite in enabled_suites)
    passed_count = sum(suite["passed_count"] for suite in enabled_suites)
    passed = bool(enabled_suites) and all(suite["passed"] for suite in enabled_suites)

    return {
        "passed": passed,
        "total": total,
        "passed_count": passed_count,
        "probe_fault": rules_layer.PROBE_FAULT_KIND if probe_fault else None,
        "only": only,
        "layers": [
            {"layer": "规则驱动层（不读真值库）", "report": rules_report},
            {"layer": "样例驱动层（读 data/samples/）", "report": samples_report},
        ],
        "notes": (
            "两层基准：规则驱动层枚举端点组合，样例驱动层读植入真值；"
            "两层均为**采样覆盖，非穷举**。"
            if only is None
            else "本次为 --only 单套件运行：未选中套件标未启用，不计入通过数。"
        ),
    }
