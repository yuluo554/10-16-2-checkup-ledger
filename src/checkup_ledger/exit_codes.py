"""退出码契约（M0 锁定，README 与本模块同源）。

语义纪律：
- 1 专指"工具查出了不合规"，即**成功执行 + 负面结论**；非零 ≠ 跑挂。
- 未实现模块一律 4 显式拦截，**绝不返回伪造的空结果**。
- 4 对应模块落地后**整项退役**，退役须四处同步：常量 / CLI 分派 / 文档 / 测试（含 not hasattr 防复活）。

**退役记录（触发点逐个退役）**：
- M2：模块① 输入层（`ingest`）落地 → 从拦截名单移出并接上实现。
- M3：模块② 规范化层（`normalize`）落地 → 同上。

剩余未落地模块（ledger / export / report）**暂时借用** `EXIT_USAGE`？不——那会把
"阶段未就绪"读成"用法错误"。故本里程碑的处置是：保留 `EXIT_NOT_READY` 直到
**首期全部模块落地**（M4 整项退役），但**逐个移除触发点**。README 的退出码表随之更新。
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
"""阶段未就绪：该模块尚未落地。显式拦截，不伪造空结果。

M2 起**触发点逐个退役**：`ingest`（M2）与 `normalize`（M3）已落地并从拦截名单移出；
本常量在首期剩余模块（ledger/export/report）落地前保留，M4 整项退役。
"""

ALL_EXIT_CODES = (
    EXIT_OK,
    EXIT_FINDINGS,
    EXIT_USAGE,
    EXIT_MISSING_DEP,
    EXIT_NOT_READY,
)
