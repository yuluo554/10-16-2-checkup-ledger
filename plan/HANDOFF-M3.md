# HANDOFF-M3 · 规范化与区间层（续接快照）

> 用法：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务`
> （库内一律相对路径，绝对路径只出现在用户侧启动命令里）
> 上一棒：M2 解析与 OCR（已完成，见 plan/00 的 M2 实测证据节）

## 一、当前进度 + 证据

**M2 已达成**：模块① 输入层落地——PDF 文本层直读 + RapidOCR 扫描件兜底 + 低置信复核闭环，
且 **`NOT_READY`(4) 的 `ingest` 触发点已退役**（四处同步）。
业务链现在是"输入层 + 内核 + 基准"，**规范化/台账/导出三层尚未落地**（走 exit 4 显式拦截）。

已落盘产物（相对路径）：

| 产物 | 说明 |
|---|---|
| `plan/00–06` | 计划文档全套（00/02/03/05/06 + README + data/README 已按 M2 实测回写） |
| `src/checkup_ledger/ingest/lines.py` | 碎片 → 行装配（伪空格/补白归一/跨行聚类；**纯几何文本，无 I/O**） |
| `src/checkup_ledger/ingest/pdf.py` | PDF 文本层直读（**不用 `extract_text()`**，字符坐标自装配） |
| `src/checkup_ledger/ingest/ocr.py` | RapidOCR 兜底 + `make_scripted_engine`（确定性桩引擎，可注入） |
| `src/checkup_ledger/ingest/review.py` | 低置信复核闭环（`partition_by_confidence` / `admit_reviewed` / 孤儿留痕报错） |
| `src/checkup_ledger/ingest/deps.py` | 缺依赖守卫（**包住从 import 到调用完成的整条路径**） |
| `src/checkup_ledger/ingest/errors.py` | 输入层自有错误类型（与"缺依赖"分开） |
| `src/checkup_ledger/config.py` | 运行时配置加载（**阈值单点定义，代码零默认值**） |
| `src/checkup_ledger/data/config.yaml` | 随包配置（`ocr_threshold`；新增进 package-data 白名单） |
| `src/checkup_ledger/model.py` | 新增 `ReviewRecord`（`line_ref`/`original_text`/`confirmed_text`/`reviewer_note`） |
| `src/checkup_ledger/cli.py` | `ingest` 子命令（移出 `_NOT_READY_MODULES`，接上实现） |
| `tools/gen_ingest_fixtures.py` | 确定性夹具生成器（`--check` 位级一致） |
| `tools/fixtures/pdfwrite.py` | 自写最小 PDF 写出器（无时间戳/随机对象号 → 字节可复现） |
| `tools/fixtures/scanrender.py` | 纯 stdlib 笔画字体 → 灰阶 PNG 渲染器（**不用 Pillow**） |
| `data/samples/ingest/` | 3 PDF + 2 PNG + 5 真值 + `manifest.json`（11 个产物） |
| `tests/test_ingest.py` | 抽取陷阱 / 复核闭环 / 缺依赖契约（40 项） |
| `tests/test_config.py` | 配置门禁（阈值单点、代码零默认值） |
| `tests/test_ingest_fixtures.py` | 夹具确定性 / 真值无观测 / 台账登记 |
| `tests/conftest.py` | 把 `tools/` 加进 `sys.path`（测试可 import 夹具写出器） |
| `tests/test_layering.py` | 新增输入层分层门（无 I/O、不 import 内核、不产出判定态、可选依赖不做模块级 import） |
| `tools/mutation_check.py` | 变异表扩到 **29 条**（M2 新增 10 条） |

**实测证据（本地等价校验，未接远端，CI 待首推验证）**：

```
py -3.12 -m pytest                  → 254 passed, 1 skipped
py -3.8  -m pytest                  → 254 passed, 1 skipped（收集数一致）
py -3.12 tools/gen_ingest_fixtures.py --check → 5 组夹具逐字节一致（3.8 亦通过）
py -3.12 tools/verify_ledger.py --verify      → 37 条资产 sha256 逐字节一致
py -3.12 -m checkup_ledger bench              → 达标 64/64（exit 0）
py -3.12 tools/mutation_check.py              → 29 条变异全部变红，恢复后全绿
py -3.12 tools/pii_gate.py --selftest         → 阳性 6 项被拦 + 阴性 4 项放行
ingest <夹具.pdf> → exit 0（真实抽取）；ledger → exit 4（仍拦截）；缺依赖 → exit 3
[ocr] 通道实测（本机单独 venv）：清晰扫描件逐格读准；降质扫描件每行都低于阈值
```

**M2 期间修掉的真缺陷**（留档，防重犯）：
1. **PDF 每行一页**：夹具首版一行一页，造出 4 页"报告"→ 改为单页多行；
2. **列坐标写死致单位挤进下一列**：`10^9/L` 比 `U/L` 宽 → 改为按内容实算列起点；
3. **笔画字体 `9` 上下颠倒**（碗画在下半部）→ OCR 稳定读成 `6`；逐字形 A/B 后修正；
4. **空格判定基准选错**：用"相邻间距中位数"在两三个碎片上退化成"间距=它自己"，
   阈值被抬到判不出空格（`U/L` 粘成 `U/L`）→ 改用**字符均宽**基准；
5. **降质强度不够决定性**：首版有 1 行 0.8087 > 0.8，断言退化成弱断言 → 扫到每行都低于阈值。

## 二、下一棒待办（M3 规范化与区间层）

按 `plan/05-里程碑与发布.md` 的 M3 节逐项做：

1. **模块② 规范化层 `src/checkup_ledger/normalize/`**
   - `normalize(lines, *, dictionary) -> NormalizeResult`（**纯函数不读文件**，别名经参数接收）；
   - **指标名映射**：`谷丙转氨酶`/`ALT`/`GPT` → 同一 `canonical_name`；别名表**只在 YAML 一处定义**；
   - **单位归一**：**最长优先**匹配（否则 `2mg` 被短单位 `g` 吃成 2 克，值静默放大一千倍）；
     认不出的单位 → `pending` + 原因码 `unit_unmapped`，**不落 `not_found`**
     （"写了但单位不认识"与"根本没写"是两件事）；
   - 无法映射 → `pending_mapping`（原文 + 原因码），**不猜、不静默丢弃**。
2. **输入衔接（本棒刚建立的资产要用上）**
   - 规范化层**只接收已复核放行的行**：`ingest()` 返回的 `lines` 已含"达标 + 复核放行"，
     `pending_review` 一律不得进入。**这条已由 `test_gate_never_admits_unreviewed_rows` 守住**，
     但需要**端到端**再验一次（ingest → normalize 的贯通断言）；
   - 输入层产出的 `RawLine` 带 `page`/`line_no`/`source_file`——规范化的
     `Measurement.line_ref` 必须**保留**它（溯源链不能在这里断）。
3. **三级优先判定全链**：自印 > verified 默认 > 拒判；`range_source` 在产物显式可见
   （引擎侧 M1 已实现，本棒做**端到端贯通**：报告行 → 规范化 → 判定 → 台账）。
4. **`NOT_READY`（4）本轮退役**——**规范化模块的拦截点**整项退役，**四处同步**：
   ① `exit_codes.py` 常量注记 → ② `cli.py` 把 `normalize` 移出 `_NOT_READY_MODULES` 并接实现
   → ③ 文档（README 退出码表 + `plan/02`）→ ④ 测试（含"已落地模块不得留在拦截名单"防复活）。
   **少一处 = 幽灵语义复活**。照抄 M2 对 `ingest` 的四处同步做法即可。
5. **单位口径落点**：`plan/04` 第四节与 `data/README.md` 第五节第 4 条已有口径，
   若单位归一引入新的"第三态"（`unit_unmapped`），须回写 `data/README.md` 口径节。
6. **回写 `plan/00/02/03/05/06`** + 写 `plan/HANDOFF-M4.md` + commit。

**M3 DoD（逐项）**：见 `plan/05-里程碑与发布.md` 的 M3 节。

## 三、既定口径清单（K 编号 · 动了会打挂测试的约定）

> M0 的 K1–K27、M1 的 K28–K36 全部继续生效。M2 新增如下。

| K | 口径 | 落在哪 | 动了会打挂什么 |
|---|---|---|---|
| **K37** | **输入层只做抽取，不做数值语义判断**：不 import 判定内核、不产出 `FLAG_*`；行装配模块无 I/O import | `ingest/*.py` | `test_ingest_layer_does_not_import_engine` / `..._does_not_decide_flags` / `test_ingest_lines_module_has_no_io_imports` |
| **K38** | **PDF 文本层不用 `extract_text()`**，取字符坐标自装配；空格判定 = 间隙 > 0.75 × **行内字符均宽**（基准从该行碎片实算） | `ingest/lines.py:_join_fragments` | `test_pdf_layouts_yield_identical_lines` + `test_pseudo_space_is_normalized` + 变异"伪空格归一失效→必红" |
| **K39** | **未复核行不向下传递**：`admit_reviewed` 是唯一放行门；**无记录 / 空确认值 → 不放行**；孤儿留痕 → **抛错** | `ingest/review.py` | `test_gate_never_admits_unreviewed_rows` + 3 条变异 |
| **K40** | **行置信度取该行最弱碎片**（一行里有一截没认准，整行都该复核） | `ingest/lines.py:assemble_lines` | `test_line_confidence_takes_weakest_fragment` + 变异"取最强→必红" |
| **K41** | **`ocr_threshold` 单点定义在随包 `config.yaml`，代码零默认值**；`ingest()` 入口**无默认参数值**；缺文件/缺字段/非法值/越界 → `ConfigError` | `config.py` + `data/config.yaml` | `tests/test_config.py` 13 项 + `test_ingest_entrypoint_has_no_default_threshold` + 变异"缺字段静默取默认→必红" |
| **K42** | **缺依赖守卫包住"从 import 到调用完成"的整条路径**（只包 import 行是假门）；`MissingDependencyError` → exit 3 | `ingest/deps.py:run_guarded` | `test_guard_covers_call_time_import_not_just_import_line` + `test_cli_ingest_exits_three_without_dependency` |
| **K43** | **可选重件只出现在函数体内**（模块级 import 会让"只装 dev"的环境连收集都失败） | `ingest/pdf.py`/`ocr.py` | `test_ingest_optional_deps_imported_only_inside_guard` + README 面 3 的 `test_face3_pdf_and_ocr_deps_are_not_module_level_in_tests` |
| **K44** | **输入层夹具是生成物**：`gen_ingest_fixtures.py --check` 位级一致；渲染器禁 `random`/时钟/`hash()`；**不用 Pillow**（跨版本字节不稳） | `tools/gen_ingest_fixtures.py` + `tools/fixtures/` | `tests/test_ingest_fixtures.py` 11 项 + 变异"渲染引入时钟→必红" |
| **K45** | **`4` 触发点逐个退役**：已落地模块**不得留在** `_NOT_READY_MODULES`；四处同步（常量注记/分派/文档/测试含防复活） | `cli.py` + `exit_codes.py` + README + `plan/02` | `test_ingest_is_no_longer_intercepted_by_not_ready` + `test_not_ready_module_list_excludes_landed_module` + 变异"未就绪语义复活→必红" |
| **K46** | **零字面量门禁的豁免清单精确登记**（现为 2 个文件：`pii_gate.py` 结构位数 + `scanrender.py` 字形几何）；新增例外必须同时改 `EXEMPT_FILES` 与锁死断言 | `tests/test_no_literal_thresholds.py` | `test_exempt_files_are_exactly_as_declared` |

## 四、本机环境坑（只写实测过的）

- **用 `py` 不是 `python`**（后者是商店占位符，实测直接 `exit 49`）；跑中文输出加 `-X utf8`。
- **本机双通道**：`py -3.8`（3.8.8）与 `py -3.12`（3.12.10）**都可用**，各自独立装过本包（`-e .`）。
  两者收集数必须一致（当前 254/254，各 1 skipped）。
- **`[pdf]` 本机只在 3.8 通道装了**；3.12 通道默认没装 → PDF 相关测试在 3.12 上会走
  "缺依赖"分支？**不会**：`test_ingest.py` 的 PDF 用例需要 pdfplumber 真在位。
  **实测 3.12 上已单独装过 `pdfplumber==0.11.5`**（见下条），故两通道都跑得通。
  若换机器，先 `py -3.12 -m pip install pdfplumber` 再跑。
- **`[ocr]` 本机只在仓库外的探针 venv 里装过**（`_probe_ingest/venv-ocr`，**仓库外**——
  临时目录一律建在仓库外，否则会被门禁扫描面扫进导致行尾守门假红）。
  故 `test_scan_fixtures_match_truth_when_ocr_available` 在常规 pytest 里 **skip**（如实跳过）。
  **要真跑 OCR 回归**：
  ```bash
  py -3.12 -m venv <仓库外目录>/venv-ocr
  <...>/venv-ocr/Scripts/python.exe -m pip install rapidocr-onnxruntime==1.3.24 pytest pdfplumber \
      -i https://pypi.tuna.tsinghua.edu.cn/simple
  <...>/venv-ocr/Scripts/python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
  PYTHONPATH=src <...>/venv-ocr/Scripts/python.exe -m pytest tests/test_ingest.py
  ```
- **`rapidocr-onnxruntime` 的权重随 wheel 内嵌**（`ch_PP-OCRv4_det/rec_infer.onnx` 共约 15MB）——
  **无需另下**。plan/05 里"权重待下载"的风险项**在 1.3.x 上不成立**，已如实回写。
- **pip 走镜像**：`-i https://pypi.tuna.tsinghua.edu.cn/simple`；若被代理污染加 `NO_PROXY="*" no_proxy="*"`。
- **全程 `PYTHONDONTWRITEBYTECODE=1`**（含 pip install）：本机 pyc 偶发损坏会造出随机失败/测试数波动；
  出怪错先清 `__pycache__` 再跑，**单轮崩溃直接重试即恢复**。
- **`tempfile` 在 C: 而仓库在 D:**：任何"在临时目录里重生成再与仓库比对"的脚本
  **不能用 `os.path.relpath` 跨盘**（抛 `ValueError`）。`gen_ingest_fixtures.py --check`
  已按逻辑前缀拼路径，避开这个坑。
- **网络探测结论**：`www.wsbz.org.cn` 无解析；`nhc.gov.cn` 412；`openstd.samr.gov.cn` 不含 WS/T；
  **`csres.com` 书目页可直连**（关键词须 GBK 编码）。全文仍付费。
- **Git Bash 下 `sed -n`/`grep` 可正常读中文文件**；`git log` 中文乱码仅是显示问题。
- **变异验证脚本已内建**（`tools/mutation_check.py`，29 条）：自己动手改源码做变异时，
  **每次改完先 `grep` 确认改动真的落盘**再跑断言。

## 五、DoD 逐项 checklist（M2）

- [x] PDF 文本层直读（`[pdf]`）产出 `RawLine[]`，三种形态经装配后**逐字相同**
- [x] RapidOCR 扫描件兜底（`[ocr]`），ONNX CPU 本地推理；合成扫描样例回归可用（权重内嵌）
- [x] 低置信行强制人工复核闭环：`pending_review` → 复核 → 放行；未复核行不进下一层（门禁测试）
- [x] 缺依赖走 `exit 3`（import 打桩复现 + "调用时才抛"的假门防线）
- [x] 复核留痕（原始行 → 人工确认值）可审计（`ReviewRecord` 四字段）
- [x] `ocr_threshold` 单点定义在随包配置，代码零默认值（入口无默认参数的签名断言）
- [x] `NOT_READY`（4）的 ingest 触发点退役，**四处同步**（含防复活断言）
- [x] 输入层夹具确定性：`--check` 位级一致（3.8 与 3.12 双通道）
- [x] 双解释器全量测试绿，收集数一致（254 / 254，各 1 skipped）
- [x] 台账复核通过（37 条）；基准两层仍 64/64
- [x] 每条新增守门做过**变异验证**（29/29 全红后恢复绿）
- [x] PII gate 双向自证（阳性 6 被拦 + 阴性 4 放行）
- [x] 无远端期间的"未推送"状态已在 README/plan/00 如实标注
- [x] `plan/00/02/03/05/06` + `README.md` + `data/README.md` 状态回写
- [x] `plan/HANDOFF-M3.md` 已落盘（本文件）
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
PYTHONPATH=src py -3.12 -m checkup_ledger ingest data/samples/ingest/pdf/ingest-pdf-per-char.pdf
PYTHONPATH=src py -3.12 -m checkup_ledger ingest data/samples/ingest/pdf/ingest-pdf-plain.pdf --json /tmp/out.json
PYTHONPATH=src py -3.12 -m checkup_ledger ledger                      # 期望 exit 4（M3 退役）
PYTHONPATH=src py -3.12 -m checkup_ledger normalize                   # 期望 exit 4（M3 退役）

# 数据资产
py -3.12 tools/gen_samples.py             # 生成/覆盖 data/samples/（M1）
py -3.12 tools/gen_samples.py --check     # 位级一致守门
py -3.12 tools/gen_ingest_fixtures.py     # 生成/覆盖 data/samples/ingest/（M2）
py -3.12 tools/gen_ingest_fixtures.py --check
py -3.12 tools/verify_ledger.py --update  # 重算台账（37 条）
py -3.12 tools/verify_ledger.py --verify  # 复核（手改被检出）

# 守门自证
py -3.12 tools/mutation_check.py          # 29 条变异验证（期望 exit 0）
py -3.12 tools/pii_gate.py --selftest     # 双向自证（期望 exit 0）
py -3.12 tools/pii_gate.py --staged       # pre-commit 的真实调用形态
```

**启动下一棒（用户侧命令）**：
```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务
```
