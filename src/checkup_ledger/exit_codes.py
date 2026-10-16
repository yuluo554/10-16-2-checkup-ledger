"""退出码契约（M0 锁定，README 与本模块同源）。

语义纪律：
- 1 专指"工具查出了不合规"，即**成功执行 + 负面结论**；非零 ≠ 跑挂。
- 未实现模块一律 4 显式拦截，**绝不返回伪造的空结果**。
- 4 对应模块落地后**整项退役**，退役须四处同步：常量 / CLI 分派 / 文档 / 测试（含 not hasattr 防复活）。
"""

EXIT_OK = 0
"""成功 / 门禁通过 / 基准达标。判定检出 H/L 仍为 0——业务结果不是错误。"""

EXIT_FINDINGS = 1
"""检出问题：门禁或校核**不通过**（区间库条目缺来源、基准未达标、自检失败）。"""

EXIT_USAGE = 2
"""用法错误：未知子命令、未知旗标、缺必需参数、参数值非法。"""

EXIT_MISSING_DEP = 3
"""缺可选依赖：调用需要 [pdf]/[ocr] 的能力但未安装（走契约，不裸抛 ImportError）。"""

EXIT_NOT_READY = 4
"""阶段未就绪：该模块尚未落地。显式拦截，不伪造空结果。"""

ALL_EXIT_CODES = (
    EXIT_OK,
    EXIT_FINDINGS,
    EXIT_USAGE,
    EXIT_MISSING_DEP,
    EXIT_NOT_READY,
)
