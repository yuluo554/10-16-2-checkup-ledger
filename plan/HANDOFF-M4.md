# HANDOFF-M4 · 台账可视化与基准（续接快照）

> 用法：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务`
> （库内一律相对路径，绝对路径只出现在用户侧启动命令里）
> 上一棒：M3 规范化与区间层（已完成，见 plan/00 的 M3 实测证据节）

## 一、当前进度 + 证据

**M3 已达成**：模块② 规范化层落地——指标名映射 + 单位归一（最长优先）+ 待人工映射
（五态原因码），且 **`NOT_READY`(4) 的 `normalize` 触发点已退役**（四处同步）。
业务链现在是"输入层 + 规范化 + 内核 + 基准"，**前三层端到端贯通**；
台账/导出/报告三层尚未落地（走 exit 4 显式拦截）。

已落盘产物（相对路径）：

| 产物 | 说明 |
|---|---|
| `plan/00–06` | 计划文档全套（00/02/03/04/05/06 + README + data/README 已按 M3 实测回写） |
| `src/checkup_ledger/normalize/__init__.py` | 模块② 对外三个入口（normalize / normalize_ingest / normalize_document） |
| `src/checkup_ledger/normalize/mapping.py` | 指标名字典 + 单位归一表（**纯函数**，别名/单位表经参数接收；最长优先 + 归属校验） |
| `src/checkup_ledger/normalize/parse.py` | 报告行 → 结构化字段（**纯函数，无 I/O**；区间列三态可分） |
| `src/checkup_ledger/normalize/pipeline.py` | 编排层（**唯一读文件处**；防绕过检查） |
| `src/checkup_ledger/normalize/errors.py` | 规范化层自有错误类型 |
| `src/checkup_ledger/model.py` | 新增 `PendingMap`（`line_ref`/`raw_text`/`reason`/`raw_name`/`raw_unit`） |
| `src/checkup_ledger/cli.py` | `normalize` 子命令（移出 `_NOT_READY_MODULES`，接上实现，**端到端贯通 ingest→normalize→judge**） |
| `tests/test_normalize.py` | 45 项（异名映射 / 单位最长优先 / 第三态 / 不猜不丢 / 端到端 / **跨层对齐**） |
| `tests/test_layering.py` | 新增规范化纯函数分层门（6 条） |
| `tools/mutation_check.py` | 变异表扩到 **39 条**（M3 新增 10 条） |

**实测证据（本地等价校验，未接远端，CI 待首推验证）**：

```
py -3.12 -m pytest                  → 307 passed, 1 skipped
py -3.8  -m pytest                  → 307 passed, 1 skipped（收集数一致）
py -3.12 -m checkup_ledger normalize data/samples/ingest/pdf/ingest-pdf-plain.pdf
                                    → exit 0（端到端：4 行映射 + H/L/正常判定 + range_source 可见）
py -3.12 -m checkup_ledger bench    → 达标 64/64（exit 0）
py -3.12 tools/gen_samples.py --check / gen_ingest_fixtures.py --check
                                    → 25 / 5 个产物逐字节一致
py -3.12 tools/verify_ledger.py --verify → 37 条资产 sha256 逐字节一致
py -3.12 tools/mutation_check.py    → 39 条变异全部变红，恢复后全绿
py -3.12 tools/pii_gate.py --selftest → 阳性 6 项被拦 + 阴性 4 项放行
ingest → exit 0；normalize → exit 0；ledger → exit 4（仍拦截）；缺依赖 → exit 3
```

**M3 期间修掉的真缺陷**（留档，防重犯）：
1. **零字面量门禁判红新模块自身的 12 处端点泄漏**：`parse.py` 为讲清"单侧区间 vs 读不出"
   在注释里写了具体端点（与 YAML 区间数值撞值）→ 示例一律改 `<下限>`/`<上限>` 指代；
2. **单位只做全局匹配会张冠李戴**：ALT 配 `mmol/L` 被照常判定 → 加 `unit_belongs_to` 门；
3. **"没写单位"与"认不出单位"合并成一个原因码**（处置方向不同）→ 拆 `unit_absent`/`unit_unmapped`；
4. **"数值+单位粘住"的写法误报 `value_unlocated`**（人工按"数值没读到"找就错了方向）→ 加拆解；
5. **测试夹具自身成了区间数值的第二处定义**（与 M1 同族）→ 改为从 `helpers.yaml_bounds` 实算。

## 二、下一棒待办（M4 台账可视化与基准）

按 `plan/05-里程碑与发布.md` 的 M4 节逐项做：

1. **模块④ 纵向台账 `src/checkup_ledger/ledger/`**（或 `src/checkup_ledger/ledger.py`）
   - `open_ledger(path) -> Ledger`（建表/迁移；schema 见 `plan/03` 模块④，**M0 定稿**，
     `subject_id` 为家庭多成员扩展预留列）；
   - `upsert(ledger, judged, *, subject, date) -> int`（唯一键 `(subject_id, canonical_name, date, source_file)`；
     重复 upsert 不产生重复行）；
   - `series(ledger, canonical_name, *, subject) -> list[TrendPoint]`（往返一致；趋势三态）；
   - **只存事实数值与判定标记**，不存任何解读文本。
2. **输入衔接**：台账只吃 `Judged`（模块③ 产出）；`Judged.measurement.line_ref` 的溯源链
   已在 M3 保住——台账的 `source_file` 从这里取。
3. **`NOT_READY`（4）本轮退役**——**台账模块的拦截点**整项退役，**四处同步**：
   ① `exit_codes.py` 常量注记 → ② `cli.py` 把 `ledger` 移出 `_NOT_READY_MODULES` 并接实现
   → ③ 文档（README 退出码表 + `plan/02`）→ ④ 测试（含"已落地模块不得留在拦截名单"防复活）。
   **少一处 = 幽灵语义复活**。照抄 M2/M3 的做法即可。
4. **模块⑤a 导出 + ⑤b 渲染**（`plan/03` 模块④⑤）：
   - `export_summary(judged, *, fmt, out)`（CSV/Markdown，**只陈述事实数值与变化幅度**）；
   - `render_html(ledger, *, out, subject)`（单指标折线 + 自身历史分位 + 参考区间带状背景）；
   - **渲染层零判定**（AST 断言：无 `BinOp` 比较、无区间数值字面量）；
   - **零外链常驻硬断言** `assert_no_external_resources`（渲染出口，非测试内一次性——M0 已建）；
   - **导出物建议性词根逐字校验**（负向词表：`建议`/`可能`/`风险提示`/`注意`/`应`/`考虑`；
     含变异验证：塞一个"建议"必红）。
5. **首启免责声明**（借鉴 bloodio 首启范式：读一次标记文件后落 `~/.checkup_ledger/accepted`）
   + README 常驻免责（M0 已落）。
6. **`*.db` 与真实报告不入 git**（PII gate 生效测试；`*.db` 已在 .gitignore）。
7. **回写 `plan/00/02/03/05/06` + `README.md` + `data/README.md` + 写 `plan/HANDOFF-M5.md` + commit。**

**M4 DoD（逐项）**：见 `plan/05-里程碑与发布.md` 的 M4 节。

## 三、既定口径清单（K 编号 · 动了会打挂测试的约定）

> M0 的 K1–K27、M1 的 K28–K36、M2 的 K37–K46 全部继续生效。M3 新增如下。

| K | 口径 | 落在哪 | 动了会打挂什么 |
|---|---|---|---|
| **K47** | **规范化层拆成"纯函数件 + 编排层"**：`mapping.py`/`parse.py` 不碰文件系统；**文件读取唯一落在 `pipeline.py`**；别名/单位表经参数接收 | `normalize/*.py` | `test_normalize_pure_modules_have_no_io_imports` / `..._only_pipeline_reads_files` / `..._does_not_import_loader` / 变异"纯函数件引入 I/O → 必红" |
| **K48** | **单位"最长优先" = 前缀匹配 + 取最长**（非包含匹配）；`mg` 里的 `g` 不得被当成命中 | `normalize/mapping.py:match_unit` | `test_unit_longest_match_beats_shorter_prefix` / `test_unit_prefix_match_does_not_swallow_shorter_alias_inside_longer_unit` / 变异"改成取最短 → 必红" |
| **K49** | **单位还须"属于该指标"**：全局单位表命中 ≠ 该指标可用；张冠李戴与"认不出"同处置 | `normalize/mapping.py:unit_belongs_to` + `parse.py` | `test_unit_that_belongs_to_another_indicator_is_not_used` + 变异"不校验归属 → 必红" |
| **K50** | **原因码按"处置方向"细分**：`unit_absent`（没写）≠ `unit_unmapped`（写了认不出）；"数值+单位粘住"须先拆开（否则误报 `value_unlocated`） | `normalize/mapping.py` + `parse.py` | `test_unmapped_unit_is_pending_not_missing` / `test_glued_value_and_unit_is_split_not_misreported` |
| **K51** | **"印了区间但读不出" ≠ "报告没印区间"**：区间列三态（占位符→None / 一侧非数字→`range_unparsed` / 正常） | `normalize/parse.py:parse_range_column` | `test_unparsable_printed_range_is_not_silently_read_as_not_printed` + 变异"读错静默当没印 → 必红" |
| **K52** | **未映射不猜不丢**：输入行数 == 已映射 + 待映射；每条 `PendingMap` 留原文 + 原因码 + 溯源行 | `normalize/pipeline.py:normalize` | `test_pending_mapping_never_silently_drops_rows` / `test_unknown_indicator_name_goes_to_pending_not_measurements` + 变异"待映射行静默丢弃 → 必红" |
| **K53** | **溯源链不断**：`Measurement.line_ref` 必须保留原始 `RawLine`（页/行/来源文件） | `normalize/pipeline.py` | `test_line_ref_survives_normalization` + 变异"丢掉溯源行 → 必红" |
| **K54** | **复核门不可绕过**：`normalize_ingest` 是唯一接续点；同一行既在 `lines` 又在 `pending_review` → **报错**；待复核行数显式记注记 | `normalize/pipeline.py:normalize_ingest` | `test_normalize_ingest_rejects_leaked_pending_rows` / `..._holds_back_unreviewed_rows` + 变异"绕过不报错 → 必红" |
| **K55** | **别名冲突必报错**（不静默取一）；**第二层来源门禁**（缺 `source.standard` 条目拒绝进字典） | `normalize/mapping.py:build_dictionary` | `test_alias_conflict_between_two_indicators_raises` / `test_entry_without_source_is_rejected_by_dictionary_gate` + 2 条变异 |
| **K56** | **自印区间的开闭沿用知识库条目口径**（`bounds_for()`），不在代码里硬编码某标准的习惯；**局限如实登记** | `normalize/pipeline.py:_printed_range` | `test_end_to_end_*` + `data/README.md` 第八节 |
| **K57** | **`4` 触发点逐个退役**：已落地模块（`ingest`/`normalize`）**不得留在** `_NOT_READY_MODULES`；四处同步 | `cli.py` + `exit_codes.py` + README + `plan/02` | `test_normalize_is_no_longer_intercepted_by_not_ready` / `test_not_ready_module_list_excludes_landed_module` / 变异"未就绪语义复活 → 必红" |
| **K58** | **跨层语义对齐**：模块侧解析结果必须与 M1 样例真值的输入字段**逐条相等** | `tests/test_normalize.py` | `test_sample_reports_normalize_to_truth_inputs`（12 例全跑） |

## 四、本机环境坑（只写实测过的）

- **用 `py` 不是 `python`**（后者是商店占位符，实测直接 `exit 49`）；跑中文输出加 `-X utf8`。
- **本机双通道**：`py -3.8`（3.8.8）与 `py -3.12`（3.12.10）**都可用**，各自独立装过本包（`-e .`）。
  两者收集数必须一致（当前 307/307，各 1 skipped）。
- **`[pdf]` 两通道都已装**（3.8 与 3.12 各装过 `pdfplumber`）→ PDF 相关测试双通道都跑得通。
  若换机器，先 `py -3.12 -m pip install pdfplumber` 再跑。
- **`[ocr]` 本机只在仓库外的探针 venv 里装过**（仓库外目录——临时目录一律建在仓库外，
  否则会被门禁扫描面扫进导致行尾守门假红）。故真实 OCR 回归在常规 pytest 里 **skip**（如实跳过）。
  **要真跑 OCR 回归**：
  ```bash
  py -3.12 -m venv <仓库外目录>/venv-ocr
  <...>/venv-ocr/Scripts/python.exe -m pip install rapidocr-onnxruntime==1.3.24 pytest pdfplumber \
      -i https://pypi.tuna.tsinghua.edu.cn/simple
  <...>/venv-ocr/Scripts/python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
  PYTHONPATH=src <...>/venv-ocr/Scripts/python.exe -m pytest tests/test_ingest.py
  ```
- **`rapidocr-onnxruntime` 的权重随 wheel 内嵌**（约 15MB）——**无需另下**。
- **pip 走镜像**：`-i https://pypi.tuna.tsinghua.edu.cn/simple`；若被代理污染加 `NO_PROXY="*" no_proxy="*"`。
- **全程 `PYTHONDONTWRITEBYTECODE=1`**（含 pip install）：本机 pyc 偶发损坏会造出随机失败/测试数波动；
  出怪错先清 `__pycache__` 再跑，**单轮崩溃直接重试即恢复**。
- **`tempfile` 在 C: 而仓库在 D:**：任何"在临时目录里重生成再与仓库比对"的脚本
  **不能用 `os.path.relpath` 跨盘**（抛 `ValueError`）。生成器已按逻辑前缀拼路径，避开这个坑。
- **网络探测结论**：`www.wsbz.org.cn` 无解析；`nhc.gov.cn` 412；`openstd.samr.gov.cn` 不含 WS/T；
  **`csres.com` 书目页可直连**（关键词须 GBK 编码）。全文仍付费。
- **Git Bash 下 `sed -n`/`grep` 可正常读中文文件**；`git log` 中文乱码仅是显示问题。
- **变异验证脚本已内建**（`tools/mutation_check.py`，39 条）：自己动手改源码做变异时，
  **每次改完先 `grep` 确认改动真的落盘**再跑断言。
- **零字面量门禁扫全文（含 docstring/注释）**：新写模块的注释里**别写具体区间端点**——
  写 `<下限>`/`<上限>` 这类指代（M3 实测被这道门判红了 12 处）。

## 五、DoD 逐项 checklist（M3）

- [x] 指标名字典 loader 门禁（缺来源拒加载 + 未启用清单显式列原因）+ M3 第二层门禁（`build_dictionary`）
- [x] 单位归一（**最长优先**、`unit_unmapped` 第三态、`mg`/`mmol` 边界用例）+ **归属校验**（实测补门）
- [x] 三级优先判定全链：自印 > verified 默认 > 拒判；`range_source` 在产物显式可见（**端到端**贯通）
- [x] 边界 `bounds` 开闭语义（`threshold_exact` / `near_miss` 双向用例）+ 自印区间开闭接知识库口径
- [x] 未映射进 `pending_mapping`（不猜不丢，原因码五态，逐条留原文与溯源）
- [x] 零字面量门禁覆盖**引擎 + CLI + 渲染层**（扫描面随交付形态扩张；门实测抓出 12 处新模块泄漏）
- [x] 判定层纯函数静态门禁（无 I/O import、无时钟）+ **规范化纯函数件**的对应门（6 条）
- [x] **`NOT_READY`（4）本轮退役**（规范化模块拦截点，**四处同步**，含防复活断言）
- [x] 端到端贯通：`ingest` → `normalize` → `judge`（`normalize` 子命令；溯源链保住；跨层对齐 12 例）
- [x] 双解释器全量测试绿，收集数一致（307 / 307，各 1 skipped）
- [x] 台账复核通过（37 条）；基准两层仍 64/64；生成器位级一致（25 / 5）
- [x] 每条新增守门做过**变异验证**（39/39 全红后恢复绿）
- [x] PII gate 双向自证（阳性 6 被拦 + 阴性 4 放行）
- [x] 无远端期间的"未推送"状态已在 README/plan/00 如实标注
- [x] `plan/00/02/03/04/05/06` + `README.md` + `data/README.md` 状态回写
- [x] `plan/HANDOFF-M4.md` 已落盘（本文件）
- [ ] commit（本对话内完成；**不 push**——无远端）

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -m pytest
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.8  -m pytest

# 冒烟
PYTHONPATH=src py -3.12 -m checkup_ledger selftest
PYTHONPATH=src py -3.12 -m checkup_ledger indicators
PYTHONPATH=src py -3.12 -m checkup_ledger bench                       # 两层 64/64
PYTHONPATH=src py -3.12 -m checkup_ledger bench --probe-fault         # 期望 exit 1
PYTHONPATH=src py -3.12 -m checkup_ledger ingest data/samples/ingest/pdf/ingest-pdf-plain.pdf
PYTHONPATH=src py -3.12 -m checkup_ledger normalize data/samples/ingest/pdf/ingest-pdf-plain.pdf
PYTHONPATH=src py -3.12 -m checkup_ledger normalize data/samples/ingest/pdf/ingest-pdf-per-char.pdf --json /tmp/out.json
PYTHONPATH=src py -3.12 -m checkup_ledger ledger                      # 期望 exit 4（M4 退役）
PYTHONPATH=src py -3.12 -m checkup_ledger export                      # 期望 exit 4（M4 退役）
PYTHONPATH=src py -3.12 -m checkup_ledger report                      # 期望 exit 4（M4 退役）

# 数据资产
py -3.12 tools/gen_samples.py             # 生成/覆盖 data/samples/（M1）
py -3.12 tools/gen_samples.py --check     # 位级一致守门
py -3.12 tools/gen_ingest_fixtures.py     # 生成/覆盖 data/samples/ingest/（M2）
py -3.12 tools/gen_ingest_fixtures.py --check
py -3.12 tools/verify_ledger.py --update  # 重算台账（37 条）
py -3.12 tools/verify_ledger.py --verify  # 复核（手改被检出）

# 守门自证
py -3.12 tools/mutation_check.py          # 39 条变异验证（期望 exit 0）
py -3.12 tools/pii_gate.py --selftest     # 双向自证（期望 exit 0）
py -3.12 tools/pii_gate.py --staged       # pre-commit 的真实调用形态
```

**启动下一棒（用户侧命令）**：
```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务
```
