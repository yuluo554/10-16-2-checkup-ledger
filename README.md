# CheckupLedger · 体检台账工作台

> **三年前那项指标是多少来着？**

把历年体检报告录成个人检验指标台账，做**纵向趋势**与**按参考区间的机械标记**，并导出就诊摘要。

**纯本地、零上传、零遥测。** 数值判定 100% 交给确定性代码（H / L / 趋势），**不做解读、不做分诊、不做诊断建议**。

---

## ⚠️ 免责声明（常驻，请先读）

- 本项目**不是医疗器械**，**不构成诊断依据**。
- 它**不做诊断、不做解读、不做分诊、不做治疗建议**。输出的 `H` / `L` 标记只是"数值与区间边界的**机械比较**结果"。
- 各医疗机构应以**本机构 LIS 打印区间**为最终准绳。内置区间为常见项默认值，**一切以报告单和医嘱为准**。
- 请务必咨询执业医师获取任何医疗建议。
- 本项目**纯本地运行**：不联网、不上传、不遥测。你的报告数据不会离开你的电脑。

---

## 它做什么 / 不做什么

| 做 | 不做 |
|---|---|
| 把历年报告录入成结构化台账 | 判断你"有没有病" |
| 按参考区间做 H / L 机械标记 | 解释指标含义、给健康建议 |
| 画单指标纵向趋势与自身历史分位 | 分诊、风险评级、治疗建议 |
| 导出只陈述事实数值与变化幅度的就诊摘要 | 用大模型"解读"你的报告 |

**为什么走确定性路线**：区间判定必须可复现、可核验。公开研究（经先例项目转述）显示大模型自报参考区间的表现不稳定（CV 26.5%、无检索场景准确率 42.9%），而**各医院、各仪器的区间本就不同——报告上印的才是有效区间**。所以本项目把区间判定做成纯确定性比较。

---

## 快速开始

```bash
git clone https://github.com/yuluo554/10-16-2-checkup-ledger.git
cd 10-16-2-checkup-ledger

# 核心能力零第三方依赖，仅知识库需要 PyYAML
python -m pip install -e .

# 测试（开发用，与 CI 用同一 extras 集合）
python -m pip install -e ".[dev]"
python -m pytest
```

> Windows 上若 `python` 是商店占位符，用 `py` 代替（`py -m pip install -e .`）。

可选能力（按需安装，未装时对应命令走 `exit 3` 契约）：

```bash
python -m pip install -e ".[pdf]"    # PDF 文本层直读（模块①）
python -m pip install -e ".[ocr]"    # 扫描件 OCR 兜底（模块①，ONNX CPU 本地推理）
```

### 命令速查

```bash
checkup-ledger version                      # 版本与环境
checkup-ledger selftest                     # 内置自检：数据目录 / 知识库门禁 / 写盘确定性 / 零外链守卫
checkup-ledger indicators                   # 列出内置区间条目与未启用清单
checkup-ledger bench                        # 跑判定基准（两层：规则驱动 + 样例驱动）
checkup-ledger bench --only 边界语义         # 只跑一个套件（其余标注"未启用"，不计入通过数）
checkup-ledger bench --only 样例真值回归      # 样例驱动层套件（读 data/samples/）
checkup-ledger bench --probe-fault          # 可证伪探活：注入已知缺陷，基准必须报未达标
checkup-ledger ingest 报告.pdf               # 模块① 输入层：抽取行级草稿（PDF 文本层）
checkup-ledger ingest 扫描件.png             # 扫描件走 OCR 兜底（需 [ocr]）
checkup-ledger ingest 报告.pdf --json out.json
checkup-ledger normalize 报告.pdf            # 模块② 规范化：映射指标名/归一单位 → 机械判定（含来源）
checkup-ledger normalize 报告.pdf --json out.json
```

**输入层（模块①）**：把 PDF 文本层 / 扫描件读成**行级草稿**（原始行 + 页码 + 行置信度），
**只做抽取、不做任何数值语义判断**。两条纪律：

- **低置信行强制人工复核**：`confidence < ocr_threshold` 的行进 `pending_review`，
  **未经复核确认不得向下传递**（`--reviews` 传复核留痕才放行）；
- **阈值单点定义在配置**（`src/checkup_ledger/data/config.yaml` 的 `ocr_threshold`），
  **代码零默认值**——缺配置即报错，不静默取 0.8 之类的字面值。

缺 `[pdf]` / `[ocr]` 时走 **`exit 3`**（缺依赖契约），**不裸抛 `ImportError`**。

**规范化层（模块②）**：把**已复核放行**的行映射成结构化记录（指标名 → canonical、
单位归一），再做三级优先的机械判定（`H`/`L`/正常/拒判），判定所用区间的
**来源在产物里显式可见**（`report_printed` / `builtin_default` / `none`）。三条纪律：

- **别名表只在知识库一处定义**（`indicators.yaml` 的 `aliases`），本层经参数接收、
  **不另建第二份**；认不出的指标名进**待人工映射队列**（原文 + 原因码），**不猜、不静默丢弃**；
- **单位按最长优先匹配**：报告写 `2mg` 时若被短单位 `g` 吃掉，值会**静默放大一千倍**；
  认不出的单位是第三态（`unit_unmapped`），**不落 `not_found`**（"写了但认不出"与
  "根本没写"是两件事）；
- **未复核的行不向下传递**：`normalize` 只吃模块① 放行的行，`pending_review` 一律不进。

三条通路等价，任选其一：

```bash
checkup-ledger selftest                     # ① 安装后的控制台脚本
python -m checkup_ledger selftest           # ② 模块形式
py -X utf8 -m checkup_ledger selftest       # ③ Windows 中文控制台推荐写法
```

**基准分两层**（各治一类盲区）：

| 层 | 数据 | 治什么 |
|---|---|---|
| 规则驱动层 | 随包 `benchmark/cases.json` | 手工枚举四态/边界/优先级组合，**不读真值库**——兜住"样例没覆盖到的端点" |
| 样例驱动层 | `data/samples/`（合成报告 + 植入真值） | 读植入真值验端到端判定——治"引擎在真实报告形态上是否仍正确" |

> `data/samples/` 是**开发期资产**（不随包分发）。在安装态/冻结态跑基准时，样例层会**如实标注"数据不在位、本层未启用"**，不计入通过数——**不伪造通过**。

**退出码语义**（非零 ≠ 跑挂）：

| 码 | 含义 |
|---|---|
| `0` | 成功 / 门禁通过 / 基准达标。**判定检出 H/L 仍为 0**——业务结果不是错误 |
| `1` | 检出问题：门禁或校核**不通过**（如知识库条目缺来源、基准未达标） |
| `2` | 用法错误：未知命令、未知旗标、缺必需参数 |
| `3` | 缺可选依赖（如未装 `[pdf]` / `[ocr]` 就调用对应能力） |
| `4` | 阶段未就绪：该模块尚未落地。**显式拦截，不返回伪造的空结果** |

> `4` 的**触发点逐个退役**：模块① 输入层（`ingest`）与模块② 规范化层（`normalize`）
> 已落地，**不再走 `exit 4`**（改走真实实现或 `exit 3` 缺依赖）。剩余模块
> （台账 / 导出 / 报告）落地前仍走 `4`；首期全部落地后 `4` 整项退役。退役须
> **四处同步**（常量 / CLI 分派 / 文档 / 测试含防复活断言），少一处即幽灵语义复活。

---

## 参考区间怎么定（三级优先）

1. **报告自印区间（最优先）**——报告单上印的才是有效区间，各医院仪器试剂不同，这比任何知识库都可靠；
2. **内置默认值**——仅当报告未印区间时兜底，每条都标注来源分册与版本，可读 `src/checkup_ledger/data/indicators.yaml`；
3. **无区间 → 拒判**——只展示趋势、不标异常。**"不判"是明确结论，不是"正常"**。

内置条目当前一律标 `pending`（WS/T 404/405 全文不可直连，区间数值无法逐条核对）。**`pending` 不进判定路径**——也就是说，报告没印区间时会走"拒判"。这是设计内行为：**宁可拒判，也不臆造区间**。

条目的**来源分册号已核对**（工标网书目页）：其中血脂、血糖、尿酸在 WS/T 404/405 系列中**没有对应分册**，故这三类的标准号字段如实标"未定位"，**不用方法标准冒充区间来源**。核对记录见 [`data/README.md`](data/README.md) 第六节。

---

## 合成样例与真值基准

`data/samples/` 提供**程序化生成**的合成报告集与植入真值（假姓名白名单 + 假机构名，**绝无真实报告**）：

```bash
# 生成（确定性：固定 seed，两次运行逐字节一致）
py -3.12 tools/gen_samples.py

# 位级一致校验（再生成与磁盘产物逐字节比对）
py -3.12 tools/gen_samples.py --check

# 台账重算 / 复核（sha256 清单，生成物非手编）
py -3.12 tools/verify_ledger.py --update
py -3.12 tools/verify_ledger.py --verify
```

| 资产 | 位置 | 说明 |
|---|---|---|
| 合成报告（12 例） | `data/samples/cases/*.txt` | 文本层可读形态 |
| 植入真值 | `data/samples/truth/*.truth.json` | **只存"输入与期望"**，观测由基准运行时实算 |
| 覆盖度门槛 | `data/samples/manifest.json` | 门槛以**数据**下发（非代码），总数/采样数双登记 |
| 数据资产台账 | `data/ledger/assets.csv` | sha256 清单，`--update` 重算 |

真值与引擎**共用同一处判定规则**（`engine/compare.py`），不手写第二份口径；区间数值**只在知识库一处定义**（零字面量门禁守）。

---

## 隐私红线

- 真实体检报告与台账数据库**永不入库、永不入 git、永不入示例目录**。
- `pre-commit` 钩子（`tools/pii_gate.py`）三重拦截：禁用路径 / 敏感文件类型 / 内容特征。
- 启用钩子：

```bash
git config core.hooksPath .githooks
```

- 所有示例数据均为**合成报告**（假姓名白名单 + 假机构名）。

---

## 项目状态

- 当前：**M3 规范化与区间层**——模块① 输入层（PDF 文本层直读 + RapidOCR 扫描件兜底 +
  低置信复核闭环）与模块② 规范化层（指标名映射 + 单位归一 + 待人工映射队列）已落地，
  **前三级贯通**（报告行 → 规范化 → 机械判定）；台账/导出/报告三层按里程碑推进。
- 里程碑与 DoD 见 [`plan/05-里程碑与发布.md`](plan/05-里程碑与发布.md)；架构见 [`plan/02-架构与技术选型.md`](plan/02-架构与技术选型.md)。

### 本地等价校验（诚实口径）

本仓库**在 M6 之前无远端**：所有 CI 类结论一律表述为**本地等价校验（未接远端，CI 待首推验证）**。
"未推送 = 未跑 CI"——不把计划中的验证写成已发生的事实。

---

## 已知环境问题

- **Windows 中文控制台**：程序入口会探测 stdio 编码，对 `cp1252`/`ascii` 这类编不动中文的流自动 reconfigure 为 UTF-8；`cp936`（中文 Windows 默认）保持不动。若使用 `python -m` 形式且输出乱码，可显式 `py -X utf8 -m checkup_ledger …`。
- **`python` 是商店占位符**：用 `py` 代替。
- **代理污染 pip**：若 pip 报连不上代理，用 `NO_PROXY="*" python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <pkg>`。
- PDF / OCR 依赖（`[pdf]` / `[ocr]`）为可选重件，**模块①② 已落地**，按需安装即可用（未装时 `ingest`/`normalize` 走 `exit 3` 契约）。`[ocr]` 的 ONNX 权重**随 wheel 内嵌**，`pip install` 即完成，无需另外下载。

---

## 许可

MIT。内置区间数据的来源标注说明见 `src/checkup_ledger/data/indicators.yaml` 文件头与 [`data/README.md`](data/README.md)。
