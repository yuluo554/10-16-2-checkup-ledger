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

# 测试（开发用，与 CI 用同一 extras 集合；[pdf] 为输入层门禁的测试期依赖）
python -m pip install -e ".[dev,pdf]"
python -m pytest
```

> Windows 上若 `python` 是商店占位符，用 `py` 代替（`py -m pip install -e .`）。

可选能力（按需安装，未装时对应命令走 `exit 3` 契约）：

```bash
python -m pip install -e ".[pdf]"    # PDF 文本层直读（模块①）
python -m pip install -e ".[ocr]"    # 扫描件 OCR 兜底（模块①，ONNX CPU 本地推理）
python -m pip install -e ".[freeze]" # 冻结构建（打包成免安装 exe，需 PyInstaller ≥6）
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
checkup-ledger ledger 报告.pdf --date 2024-03-11 --subject 张三   # 模块④ 台账：判定结果入库
checkup-ledger ledger --subject 张三 --indicator ALT             # 只读：看单指标时间序列
checkup-ledger ledger --subject 张三 --json out.json             # 只读：导出台账读回结果
checkup-ledger export 报告.pdf --date 2024-03-11 --subject 张三 --fmt csv --out 摘要.csv   # 模块⑤a 就诊摘要
checkup-ledger export 报告.pdf --date 2024-03-11 --fmt md --out 摘要.md
checkup-ledger report 报告.pdf --date 2024-03-11 --subject 张三 --out 报告.html   # 模块⑤b 本地 HTML 报告
```

**台账（模块④）**：把判定结果写入本地 SQLite 台账（按人 / 指标 / 日期），支持
单指标纵向时间序列读回。三条纪律：

- **只存事实数值与判定标记**：数值、单位、标记、所用区间与来源，**不存任何解读文本**；
- **唯一键幂等**：`(subject_id, canonical_name, date, source_file)` 上重复入库不产生重复行；
  `subject_id` 为家庭多成员扩展预留（默认 `default`）；
- **真实报告与台账 `*.db` 永不入 git**（PII gate 拦 `*.db`，已在 `.gitignore`）。
  台账缺省落在 `~/.checkup_ledger/ledger.db`（**用户主目录，不是仓库**）。

**导出（模块⑤a）**：就诊摘要导出 CSV / Markdown，**只陈述事实数值与变化幅度**
（"ALT 由 32 升至 47，变化 +46.9%"）。产物末尾常驻免责段；**建议性词根逐字校验是
导出出口的常驻断言**（`建议`/`可能`/`风险提示`/`注意`/`应`/`考虑` 命中即拒绝写出）。

**报告（模块⑤b）**：本地单文件 HTML，含**单指标折线 + 自身历史分位 + 参考区间带状背景**。
三条纪律：

- **渲染层零判定**：只消费既有判定结果，不重算任何比较（AST 静态门禁守）；
- **零外链常驻硬断言** `assert_no_external_resources`（渲染出口每次跑，断网可开）；
- **渲染层也过建议性词根门**（界面文字同样不许给意见）。

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

> **`4`（阶段未就绪）已整项退役**：首期五模块（输入 / 规范化 / 判定 / 台账 / 导出+报告）
> 全部落地，不再有"尚未落地"的模块需要显式拦截，故 `EXIT_NOT_READY` 常量连同
> `cmd_not_ready` 一并删除。退役走**四处同步**（常量 / CLI 分派 / 文档 / 测试含防复活断言）——
> 少一处即幽灵语义复活。历史轨迹：M2 退役 `ingest` 触发点、M3 退役 `normalize` 触发点
> （两次均保留常量），M4 拦截名单清空后整项退役。

---

## 免安装产物（冻结 CLI）

不想装 Python 也能用：把仓库打包成**目录式自包含产物**（exe + 数据同目录），拷到任意机器直接跑。

```bash
# 构建 + 验证一次跑齐（产物一律落在仓库外的目录）
py -3.12 tools/freeze_build.py --out <仓库外目录>

# 只验证一份已有产物（可选 --smoke 追加真跑）
py -3.12 tools/freeze_build.py --dist <产物目录> --smoke
```

产物在 `<仓库外目录>/dist/checkup-ledger/`：`checkup-ledger.exe` + `_internal/`（随包数据
在 `_internal/data/`，基准用例在 `_internal/checkup_ledger/benchmark/`）。用法与源码态一致：

```bash
checkup-ledger.exe selftest     # 6/6（含"数据目录落在 exe 目录内"的冻结态断言）
checkup-ledger.exe bench        # 内置基准（随包用例，无需样例集）
checkup-ledger.exe ingest <报告.pdf>
```

构建脚本每次都会自证四条，任一不过即 exit 1：

1. **内嵌数据对账**——白名单**双向**核对（不丢 / 不多）且逐份 sha256 与仓库冻结件一致；样例集**不随包**；
2. **"零上传"可扫断言**——读 exe 内归档的模块名表 + 扫 dist 树，**无可出站能力的组件**
   （TLS / HTTP / FTP / SMTP / telnet / 异步与并发一律不在包内）；
3. **打包确定性**——同一份 dist 两次打 zip **逐字节一致**（`ZIP_STORED` + 条目排序 + 固定时间戳）；
4. **真跑产物**——在中立目录（仓库外）+ `env -i` 等价环境（Windows 只留 `SYSTEMROOT`）下
   跑 `version`/`selftest`/`bench`（exit 0）与未知命令（exit 2）。

两条**如实口径**，不美化：

- **"零上传"= 无可出站能力组件，不是"包里字面上没有 socket"**。实测 `socket` 这个**名字**
  排不掉——`pdfminer` 在模块级经 `importlib.metadata` → `email.utils` 触发了模块级
  `import socket`，强行排除会让 PDF 文本层直接不可用。故保留这个**不含协议栈**的名字并
  **显式登记**（清单 + 理由 + 测试锁死 + 变异验证），而 TLS/HTTP 等真正能出站的组件一个不留。
- **"确定性"只覆盖打包过程**：exe 本体含构建期时间戳，**同机连打两次的 exe sha256 都不同**
  （实测），故不承诺 exe 逐字节可复现；承诺的是"给定同一份 dist，打包出的 zip 逐字节一致"。

> 冻结构建固定在**装了 PyInstaller ≥6 的那条解释器通道**（本机 `py -3.12`）；`py -3.8` 上是
> PyInstaller 5.13，构建脚本会直接拒绝（口径见 [`plan/02`](plan/02-架构与技术选型.md) 第四节）。
> 详细测试点与实测偏差见 [`plan/03`](plan/03-模块详设.md)「冻结交付面」与
> [`plan/05`](plan/05-里程碑与发布.md) M5 节。

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

- 当前：**M6 发布收尾中**——首期五模块**全部落地**，全链路贯通：
  模块① 输入层（PDF 文本层直读 + RapidOCR 扫描件兜底 + 低置信复核闭环）→
  模块② 规范化层（指标名映射 + 单位归一 + 待人工映射队列）→
  模块③ 区间判定层（三级优先 + 四态机械标记）→
  **模块④ 纵向台账（SQLite，唯一键幂等 + 单指标时间序列）** →
  **模块⑤ 导出（CSV/Markdown 就诊摘要）+ 本地 HTML 报告（折线 + 自身历史分位 + 参考区间带）**。
  **`NOT_READY`(4) 已整项退役**（不再有"尚未落地"的模块）。
  **M5 起另有免安装冻结产物**（PyInstaller，见上方「免安装产物」节）：数据随包、零上传可扫、打包过程确定、真跑过。
- 下一棒：**M6 发布执行**（建仓 + 推送 + CI 首跑对账 + tag + GitHub Release 附产物）。
  发布留档见 [`plan/RELEASE-M6.md`](plan/RELEASE-M6.md)（边执行边回填，只写实测到的）。
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
- **冻结产物不吃 `PYTHONUTF8` / `PYTHONIOENCODING`**：二者是 CPython 启动配置项，PyInstaller 引导程序自己构造 `PyConfig` 并覆盖（实测三组环境变量下输出字节完全相同）。产物按**控制台编码自适应**（与源码态同一条守卫逻辑）；脚本化调用冻结产物时，请按目标控制台编码解码其输出。
- **环境里没有主目录变量时，首启免责每次都念**：解不出主目录（缺 `USERPROFILE`/`HOMEDRIVE`+`HOMEPATH`/`HOME`，如 `env -i` 这类裸环境）时**不写免责标记**——这是刻意的：`expanduser("~")` 那种情形下会原样返回 `~`，照着写会在**当前工作目录**里建出一个 `~` 文件夹。宁可多念一次免责，也不在用户没指定的地方建目录。（想让标记落到指定位置，用 `CHECKUP_LEDGER_ACCEPTED=<整文件路径>`。）

---

## 许可

MIT。内置区间数据的来源标注说明见 `src/checkup_ledger/data/indicators.yaml` 文件头与 [`data/README.md`](data/README.md)。
