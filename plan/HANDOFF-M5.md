# HANDOFF-M5 · 免安装交付物（续接快照）

> 用法：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务`
> （库内一律相对路径，绝对路径只出现在用户侧启动命令里）
> 上一棒：M4 台账可视化与基准（已完成，见 plan/00 的 M4 实测证据节）

## 一、当前进度 + 证据

**M4 已达成**：**首期五模块全部落地**，全链路端到端贯通：

```
① 输入层 ingest ──► ② 规范化 normalize ──► ③ 判定 judge ──► ④ 台账 ledger ──► ⑤a 导出 / ⑤b 渲染
```

且 **`NOT_READY`(4) 整项退役**（拦截名单清空，`EXIT_NOT_READY` 常量与 `cmd_not_ready`
一并删除；四处同步 + 三条防复活断言）。

已落盘产物（相对路径）：

| 产物 | 说明 |
|---|---|
| `plan/00–06` | 计划文档全套（00/02/03/04/05/06 + README + data/README 已按 M4 实测回写） |
| `src/checkup_ledger/ledger/` | 模块④ 台账（`schema.py` 单点 schema / `errors.py` / `__init__.py` 三入口） |
| `src/checkup_ledger/export/__init__.py` | 模块⑤a 导出（CSV/MD + 六词根负向词表 + 出口常驻断言） |
| `src/checkup_ledger/report/chart.py` | 图元计算（坐标/值域/分位；**看不到判定态**） |
| `src/checkup_ledger/report/trend.py` | 序列装配（分组 + 取数；不重排不重算） |
| `src/checkup_ledger/report/html.py` | 渲染拼接（判定表 + 折线 + 区间带；**零判定/零外链/过词根门**） |
| `src/checkup_ledger/disclaimer.py` | 首启免责（标记落 `~/.checkup_ledger/accepted`；写失败不报错） |
| `src/checkup_ledger/exit_codes.py` | 退出码四级（0/1/2/3；`4` 整项退役） |
| `src/checkup_ledger/cli.py` | `ledger` / `export` / `report` 三子命令接实现；首启免责挂钩 |
| `tests/test_ledger.py` | 25 项（唯一键幂等 / 往返 / 趋势三态 / 只存事实 / 日期形状 / schema 版本 / **跨层趋势对齐**） |
| `tests/test_export.py` | 23 项（六词根逐个 / 出口常驻 / 变化幅度 / 缺值≠零 / 格式 / 双跑一致） |
| `tests/test_report.py` | 21 项（分位 / 值域 / 无区间留白 / 零外链 / 词根门 / 双跑一致 / 端到端） |
| `tests/test_layering.py` | 新增 17 项（计算/装配分离 / 台账层不做判定 / 免责落点与真实入口触发） |
| `tests/test_pii_gate.py` | 新增 3 项（真建台账库被拦 / `.gitignore` 覆盖 / 仓库无被跟踪 db） |
| `tests/test_exit_codes.py` | 退役后重写（四条防复活断言 + 三条命令真实实现断言） |
| `tools/mutation_check.py` | 变异表扩到 **63 条**（M4 新增 24 条） |

**实测证据（本地等价校验，未接远端，CI 待首推验证）**：

```
py -3.12 -m pytest                  → 396 passed, 1 skipped
py -3.8  -m pytest                  → 396 passed, 1 skipped（收集数一致）
ledger <夹具.pdf> --date 2024-03-11 --subject 张三 --db <临时库> → exit 0（入库 4 条）
ledger --subject 张三 --indicator ALT      → exit 0（序列 + 变化幅度 + 趋势三态）
export <夹具.pdf> --fmt csv --out 摘要.csv → exit 0（过词根门）
report <夹具.pdf> --out 报告.html          → exit 0（4 折线 + 区间带 + 零外链）
selftest → 6/6；bench → 达标 64/64（--probe-fault → exit 1）
no-such-cmd / version --bogus → exit 2；ledger 缺库 → exit 1；入库缺 --date → exit 2
gen_samples.py --check / gen_ingest_fixtures.py --check → 25 / 5 个产物逐字节一致
verify_ledger.py --verify → 37 条资产 sha256 逐字节一致
mutation_check.py → 63 条变异全部变红，恢复后全绿
pii_gate.py --selftest → 阳性 6 被拦 + 阴性 4 放行
```

**M4 期间修掉的真缺陷**（留档，防重犯）：
1. **首启免责在真实入口（`argv=None`）永不触发**：单测显式传 `["ledger", …]` 会通过，
   缺陷只在命令行实测暴露 → `argv is None` 回落 `sys.argv[1:]` + 补回归测试；
2. **单点序列给出"100% 分位"**（伪造"历史最高位"）→ 观测数 < 2 → `None`；
3. **`None` 落成字面 `"None"`** → 统一 `_text()`；
4. **日期形状不校验零填充**（同一报告入库两次）→ `DATE_WIDTHS` 逐段校验；
5. **`mark_accepted` 只接 `OSError`**（非法路径使工具崩）→ 同时接 `ValueError`；
6. **台账"覆盖计数"漏算 `source_file`**（注记与实际动作对不上）→ 按完整唯一键查；
7. **两处假门（变异验证抓出）**：渲染词根门只查"名字出现过" → 改**配对**守；
   "值域含端点"测试夹具不可证伪 → 改"观测点全在区间内侧"。

## 二、下一棒待办（M5 交付 / 免安装产物）

按 `plan/05-里程碑与发布.md` 的 M5 节逐项做：

1. **PyInstaller 冻结构建**（`[freeze]` = `pyinstaller>=6.0`；**固定装在 ≥6 那条解释器通道**）
   - **首次实构建真跑过**——**构建 exit 0 ≠ 产物可用**，必须真跑产物（中立目录 + `env -i`）；
   - CLI 目标 `excludes` 排除 Qt 系（体积分档，见 `plan/02` 第十一节的体积风险处置）。
2. **入口为绝对导入的薄模块 + 有 `__main__`**（AST 静态断言守）+ 未知参数 `exit 2`。
   - `src/checkup_ledger/__main__.py` 已在位（M0）；冻结入口需另建薄壳（`pyinstaller` 的 `--entry`）。
3. **冻结态自检断言数据目录落在 exe 目录内**（`paths.data_dir_in_frozen_root()` 已实现，
   非冻结态不报 FAIL——M5 只需真跑一次证明它在冻结态生效）。
4. **"零上传"可扫产物断言**：发行包内无 TLS/出站组件（`ssl`/`socket`/`urllib.request` 等
   不得进包；用 `pyi-archive_viewer` 或对 dist 目录做静态扫描）。
5. **打包确定性**：同一 dist 两次打 zip **逐字节一致**（`ZIP_STORED` + 条目 sort +
   固定 `date_time`）；**留档写明"exe 构建不承诺跨机一致"**（PyInstaller 产物含构建期时间戳）。
6. **内嵌数据对账**：入包集合 **== 白名单**（不只查漏拷）+ 逐份 sha256 与仓库冻结件一致。
   - 白名单 = `src/checkup_ledger/data/*.yaml|yml` + `benchmark/*.json`（见 `pyproject.toml`
     的 `package-data`）。**样例集不随包**（`data/samples/` 是开发期资产）。
7. **回写 `plan/00/02/03/05/06` + `README.md` + `data/README.md` + 写 `plan/HANDOFF-M6.md` + commit。**

**M5 DoD（逐项）**：见 `plan/05-里程碑与发布.md` 的 M5 节。

## 三、既定口径清单（K 编号 · 动了会打挂测试的约定）

> M0 的 K1–K27、M1 的 K28–K36、M2 的 K37–K46、M3 的 K47–K58 全部继续生效。M4 新增如下。

| K | 口径 | 落在哪 | 动了会打挂什么 |
|---|---|---|---|
| **K59** | **台账唯一键是四列** `(subject_id, canonical_name, date, source_file)`，**缺一列即静默丢数据**；`source_file` **不留 NULL**（NULL 彼此不相等 → 绕过唯一键长出重复行），未知时写有值的空串 | `ledger/schema.py` + `ledger/__init__.py:upsert` | `test_same_day_different_source_files_are_two_facts` / `test_repeated_upsert_produces_no_duplicate_rows` + 变异"唯一键少一列 → 必红" |
| **K60** | **日期形状逐段校验零填充**（`DATE_WIDTHS=(4,2,2)`，日历常数用命名常量）；日期是**显式传入**、**不读时钟** | `ledger/__init__.py:_validate_date` | `test_bad_date_shape_is_rejected`（6 例）+ 变异"日期不校验 → 必红" |
| **K61** | **台账只存事实**：无解读文本列；`created_at` 不读系统时钟；只收四态三源 | `ledger/__init__.py` + `schema.py` | `test_ledger_stores_no_interpretive_columns` / `test_reject_unknown_flag_and_source` + 变异"半懂标记也落库 → 必红" |
| **K62** | **趋势三态由 `engine` 一处实算**；首点与"前值为零"的变化字段为 `None`（**不填 0**） | `ledger/__init__.py:series` | `test_series_computes_three_trend_directions` / `test_series_percent_is_none_when_previous_is_zero` |
| **K63** | **跨层趋势对齐**：台账侧实算趋势必须与 M1 真值 `expected_trends` **逐条相等** | `tests/test_ledger.py` | `test_ledger_series_matches_sample_truth_trends`（真值里全部趋势用例） |
| **K64** | **建议性词根是导出/渲染两处的出口常驻断言**：六词根命中即**拒绝写出**；产物免责段措辞**刻意避开六词根** | `export/__init__.py:assert_no_advisory_wording` + `report/html.py` | `test_each_advisory_root_is_detected`（6 例）/ `test_export_rejects_advisory_wording_in_artifact` / `test_render_trends_rejects_advisory_wording_in_subject` + 2 条变异 |
| **K65** | **缺值 ≠ 零**：无前值 → 变化列留空；持平 → `0`/`0%`；**同一天不算可比前值**；标记与来源用 canonical token | `export/__init__.py:_latest_before` + `_csv_cell` | `test_no_history_leaves_change_columns_blank` / `test_flat_change_is_zero_percent` / `test_history_must_be_strictly_before_current_date` / `test_export_uses_canonical_flag_and_source_tokens` + 3 条变异 |
| **K66** | **渲染"计算/装配分离"**：算术与比较只准落 `report/chart.py`（看不到判定态、不做"值 vs 区间"比较、不 import 引擎）；`html.py`/`trend.py` 只剩拼接 | `report/chart.py` vs `report/html.py`/`trend.py` | `test_render_assembly_modules_have_no_arithmetic_or_comparison` / `test_chart_module_does_not_decide_flags_or_see_ranges` / `test_render_assembly_modules_do_not_import_engine` + 3 条变异 |
| **K67** | **无历史可比不给分位**（观测数 < 2 → `None`，不填 0 也不填 100%）；**无区间不画带**（如实留白）；值域**必须含区间端点** | `report/chart.py` | `test_percentile_is_none_without_history` / `test_series_plan_has_no_band_when_range_absent` / `test_plot_domain_includes_band_bounds` + 3 条变异 |
| **K68** | **零外链 + 词根门在渲染出口是配对常驻**（缺一即红）；台账层**不得** import 判定函数/产出 `FLAG_*` | `report/html.py` + `ledger/` | `test_renderer_calls_advisory_wording_gate_always` / `test_ledger_layer_does_not_decide_flags` / `test_ledger_layer_does_not_import_judgement_kernel_functions` + 3 条变异 |
| **K69** | **首启免责**：标记落**用户主目录**、写失败不报错、标记不含身份元信息；**真实入口（`argv=None`）必须触发**（回落 `sys.argv[1:]`），自检类命令跳过 | `disclaimer.py` + `cli.py:_first_run_disclaimer` | `test_disclaimer_writes_marker_only_in_given_home` / `test_cli_first_run_disclaimer_fires_on_real_entry_path` / `..._skips_self_check_commands` + 2 条变异 |
| **K70** | **`NOT_READY`(4) 整项退役**：常量 + `cmd_not_ready` + 拦截名单**一并删除**（不留死码）；四处同步 + 三条防复活断言 | `exit_codes.py` + `cli.py` + README + `plan/02` | `test_not_ready_module_list_is_gone` / `test_exit_codes_module_has_no_resurrected_stage_codes` / `test_ledger_export_report_are_no_longer_intercepted_by_not_ready` + 3 条变异 |
| **K71** | **零字面量 token 集唯一实算处** = `tests/helpers.py:load_yaml_tokens`（各层子门共用）；各层按**真实 token 集**比对，不自定豁免清单 | `tests/helpers.py` + `test_layering.py` + `test_no_literal_thresholds.py` | `test_ledger_layer_has_no_embedded_range_numbers` / `test_export_layer_has_no_embedded_range_numbers` |
| **K72** | **台账 `*.db` 与真实报告永不入 git**：`.gitignore` 覆盖 + PII gate 类型面拦；台账库缺省落 `~/.checkup_ledger/ledger.db` | `tools/pii_gate.py` + `.gitignore` + `cli.py` | `test_real_ledger_database_is_blocked_by_gate` / `test_ledger_db_is_gitignored` / `test_repo_contains_no_tracked_database_files` |

## 四、本机环境坑（只写实测过的）

- **用 `py` 不是 `python`**（后者是商店占位符，实测直接 `exit 49`）；跑中文输出加 `-X utf8`。
- **本机双通道**：`py -3.8`（3.8.8）与 `py -3.12`（3.12.10）**都可用**，各自独立装过本包（`-e .`）。
  两者收集数必须一致（当前 396/396，各 1 skipped）。
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
- **Git Bash 会把 `CHECKUP_LEDGER_ACCEPTED=/tmp/x` 这类值改写成 `D:\tmp\x`**（MSYS 路径转换）：
  测首启免责时要么用 `MSYS_NO_PATHCONV=1`，要么直接用 `py -c` 走 Python 层（本机实测踩过）。
- **网络探测结论**：`www.wsbz.org.cn` 无解析；`nhc.gov.cn` 412；`openstd.samr.gov.cn` 不含 WS/T；
  **`csres.com` 书目页可直连**（关键词须 GBK 编码）。全文仍付费。
- **Git Bash 下 `sed -n`/`grep` 可正常读中文文件**；`git log` 中文乱码仅是显示问题。
- **变异验证脚本已内建**（`tools/mutation_check.py`，63 条）：自己动手改源码做变异时，
  **每次改完先 `grep` 确认改动真的落盘**再跑断言。
- **零字面量门禁扫全文（含 docstring/注释）**：新写模块的注释里**别写具体区间端点**——
  写 `<下限>`/`<上限>` 这类指代（M3 实测被这道门判红了 12 处，M4 又被判红 5 处）。
  **M4 新增的坑**：完整日期串的日段（如 `.../11`）、比例值（如某个二位小数）都可能与
  端点数值同字面量 → 用**程序化拼装**或**算式**（`1/2`）给出，不写裸数值。
- **Windows 下 SQLite 连接不关会让文件被占用**：台账句柄支持 `with`，测试/脚本一律用 `with`。

## 五、DoD 逐项 checklist（M4）

- [x] SQLite 台账（唯一键四列幂等、往返一致、`subject_id` 预留列）
- [x] 单指标折线 + 自身历史分位 + 参考区间带状背景（本地渲染）
- [x] **渲染层零判定**静态门禁（**计算/装配分离**：算术与比较只落 `chart.py`）
- [x] **零外链常驻硬断言** `assert_no_external_resources`（与词根门**配对**守）
- [x] 就诊摘要导出 CSV/Markdown，**建议性词根逐字校验**（六词根逐个 + 出口常驻 + 变异验证）
- [x] **首启免责声明**（标记落用户主目录；真实入口触发；写失败不报错）+ README 常驻免责
- [x] 真值基准**回归全绿**（64/64），覆盖度门槛 manifest 逐项达标；探活 exit 1
- [x] `*.db` 与真实报告**不入 git**（PII gate 三条新测试：真库被拦 / gitignore / 仓库无跟踪 db）
- [x] **`NOT_READY`（4）整项退役**（常量 + 分派 + 名单一并删除；四处同步 + 三条防复活断言）
- [x] 跨层趋势对齐（台账侧 ↔ M1 真值 `expected_trends` 逐条相等）
- [x] 双解释器全量测试绿，收集数一致（396 / 396，各 1 skipped）
- [x] 台账复核通过（37 条）；基准两层 64/64；生成器位级一致（25 / 5）
- [x] 每条新增守门做过**变异验证**（63/63 全红后恢复绿）
- [x] PII gate 双向自证（阳性 6 被拦 + 阴性 4 放行）
- [x] 无远端期间的"未推送"状态已在 README/plan/00 如实标注
- [x] `plan/00/02/03/04/05/06` + `README.md` + `data/README.md` 状态回写
- [x] `plan/HANDOFF-M5.md` 已落盘（本文件）
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
PYTHONPATH=src py -3.12 -m checkup_ledger ledger data/samples/ingest/pdf/ingest-pdf-plain.pdf \
    --db <临时库> --date 2024-03-11 --subject 张三                  # 入库 4 条
PYTHONPATH=src py -3.12 -m checkup_ledger ledger --db <临时库> --subject 张三 --indicator ALT
PYTHONPATH=src py -3.12 -m checkup_ledger export data/samples/ingest/pdf/ingest-pdf-plain.pdf \
    --db <临时库> --date 2024-03-11 --fmt csv --out <临时>/s.csv
PYTHONPATH=src py -3.12 -m checkup_ledger report data/samples/ingest/pdf/ingest-pdf-plain.pdf \
    --db <临时库> --date 2024-03-11 --out <临时>/r.html
PYTHONPATH=src py -3.12 -m checkup_ledger no-such-cmd                  # 期望 exit 2

# 数据资产
py -3.12 tools/gen_samples.py             # 生成/覆盖 data/samples/（M1）
py -3.12 tools/gen_samples.py --check     # 位级一致守门
py -3.12 tools/gen_ingest_fixtures.py     # 生成/覆盖 data/samples/ingest/（M2）
py -3.12 tools/gen_ingest_fixtures.py --check
py -3.12 tools/verify_ledger.py --update  # 重算台账（37 条）
py -3.12 tools/verify_ledger.py --verify  # 复核（手改被检出）

# 守门自证
py -3.12 tools/mutation_check.py          # 63 条变异验证（期望 exit 0）
py -3.12 tools/pii_gate.py --selftest     # 双向自证（期望 exit 0）
py -3.12 tools/pii_gate.py --staged       # pre-commit 的真实调用形态
```

**启动下一棒（用户侧命令）**：
```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务
```
