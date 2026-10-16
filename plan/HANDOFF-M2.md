# HANDOFF-M2 · 解析与 OCR（续接快照）

> 用法：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务`
> （库内一律相对路径，绝对路径只出现在用户侧启动命令里）
> 上一棒：M1 数据先行（已完成，见 plan/00 的 M1 实测证据节）

## 一、当前进度 + 证据

**M1 已达成**：评测地基落位——合成样例集 + 植入真值 + 覆盖度门槛 + 数据台账，
且**内置区间知识库的来源标注已逐条核对修正**。业务链仍是"内核 + 基准"，
**输入/规范化/台账/导出四层尚未落地**（走 exit 4 显式拦截）。

已落盘产物（相对路径）：

| 产物 | 说明 |
|---|---|
| `plan/00–06` | 计划文档全套（00/04/05/06 已按 M1 实测回写） |
| `data/README.md` | 依据查证 + **第六节 M1 来源核对结论**（口径唯一源） |
| `src/checkup_ledger/data/indicators.yaml` | **19 项**覆盖五域（血常规 5 / 肝功能 6 / 血脂 4 / 肾功能 3 / 血糖 1）；分册号已核对修正；区间数值一律 `pending` |
| `src/checkup_ledger/engine/compare.py` | 判定内核 + **`range_applies_to`（适用域硬门）** + `trend_delta`/`trend_direction`（趋势三态） |
| `src/checkup_ledger/model.py` | 4 个 IR + 四态/三来源/开闭区间 + **趋势三态 + 适用域常量（`ALL_SEX`）** |
| `src/checkup_ledger/benchmark/runner.py` | 规则驱动层（不读真值库）；新增 `strict` 开关与 `suite_names()` |
| `src/checkup_ledger/benchmark/samples.py` | **样例驱动层**（读 `data/samples/`；数据不在位时如实标未启用） |
| `src/checkup_ledger/benchmark/layered.py` | **分层调度**（跨层 `--only` 校验 + 聚合结论） |
| `tools/gen_samples.py` | 确定性生成器（splitmix64 + FNV-1a 流键；区间/取值全从 YAML 派生） |
| `tools/verify_ledger.py` | `--update` 生成 / `--verify` 复核 `data/ledger/assets.csv` |
| `data/samples/` | 12 例报告 + 12 份真值 + `manifest.json`（25 个产物） |
| `data/ledger/assets.csv` | 26 条 sha256 台账（生成物） |
| `tests/test_no_literal_thresholds.py` | 零字面量门禁（token 集从 YAML 实算） |
| `tests/test_samples.py` | 真值库无观测 + 真值引擎同源 + 生成器确定性 + 分层基准 + 台账生成物 |
| `tests/helpers.py` | 新增 `yaml_bounds`/`bounds_pair`/`step_of`/`inline_range`/`range_dict`（**测试夹具从 YAML 取**） |
| `tools/mutation_check.py` | 变异表扩到 **19 条**（M1 新增 7 条） |

**实测证据（本地等价校验，未接远端，CI 待首推验证）**：

```
py -3.12 -m pytest                  → 192 passed
py -3.8  -m pytest                  → 192 passed（收集数一致）
干净 venv 照 README 走              → 192 passed；核心装只拉 PyYAML
                                     裸 console script：selftest 6/6 + bench 64/64
py -3.12 tools/gen_samples.py --check → 25 个产物与再生成逐字节一致
py -3.12 tools/verify_ledger.py --verify → 26 条资产 sha256 逐字节一致
py -3.12 -m checkup_ledger bench    → 达标 64/64（规则层 22 + 样例层 42，exit 0）
... bench --probe-fault             → 未达标（exit 1，探活有效）
py -3.12 tools/mutation_check.py    → 19 条变异全部使目标守门变红，恢复后全绿
python tools/pii_gate.py --selftest → 阳性 6 项被拦 + 阴性 4 项放行
```

**M1 期间修掉的真缺陷**（留档，防重犯）：
1. **趋势标签与实算不符**（`case-002` 标 up 实为 down）→ 覆盖度表会假达标；已加 `_assert_trend_tags_match`；
2. **生成器首版把区间数值硬编码** → 成了"区间数值的第二处定义"，被零字面量门禁拦下；已改为全从 YAML 派生；
3. **变异载荷自身写死区间数值** → 使该变异**基线就红**；探针值改为从 YAML 实算；
4. **M0 的 YAML 有三处分册号张冠李戴**（TC/TG/GLU 错挂 404.1；CREA 版本号 2012→2015；
   脂类/血糖/尿酸本无对应分册）→ 已按工标网书目核对修正。

## 二、下一棒待办（M2 解析与 OCR）

按 `plan/05-里程碑与发布.md` 的 M2 节逐项做：

1. **模块① 输入层 `src/checkup_ledger/ingest/`**（PDF 文本层直读）
   - `ingest_pdf_text_layer(path) -> list[RawLine]`（依赖 `[pdf]` = pdfplumber）；
   - **必防陷阱**：伪空格（PDF 逐字定位常见）→ 行内多空格归一后再抽取；
     跨行数值/区间 → 按 y/x 邻近聚类合并；CRLF 残留与中文路径；
   - **缺依赖走 `exit 3`**：`try/except ImportError` 必须包住**从 import 到调用完成**的整条路径
     （只包 import 行是假门）；用 `builtins.__import__` 打桩复现，本机即可跑。
2. **RapidOCR 扫描件兜底**（`[ocr]` = rapidocr-onnxruntime，ONNX CPU 本地推理）
   - `ingest_images(paths) -> list[RawLine]`；合成扫描样例回归可用；
   - 权重下载若受阻（国内网络）→ hf-mirror / ModelScope 通道；失败则**如实记偏差**并保留
     `[ocr]` 为"依赖可装但权重待下载"（**不假装跑过**）。
3. **低置信复核闭环**（M1 已在样例侧铺路，本棒做模块侧）
   - `confidence < ocr_threshold` → 进 `pending_review`，**未复核确认的行不得进入规范化层**；
   - 阈值**单点定义**在配置文件单一字段（`data/README.md` 口径节第 4 条），
     **代码零默认值**——缺配置即报错，不静默取 0.8 之类字面值；
   - `ReviewRecord`（`line_ref`/`original_text`/`confirmed_text`/`reviewer_note`）留痕可审计。
   - **样例侧已有可复用资产**：`data/samples/truth/case-012-lowconf-review.truth.json`
     含 `pending_review_rows`（期望落库集合**不含**该行）——模块侧闭环要与它对齐语义。
4. **`NOT_READY`（4）本轮退役**——本模块的拦截点整项退役，**四处同步**：
   ① `exit_codes.py` 删常量 → ② `cli.py` 改分派（`ingest` 从 `_NOT_READY_MODULES` 移出并接实现）
   → ③ 文档（README 退出码表 + `plan/02`）→ ④ 测试（**含 `not hasattr` 防幽灵语义复活**）。
   **少一处 = 幽灵语义复活**。
5. **回写 `plan/00/05/06`** + 写 `plan/HANDOFF-M3.md` + commit。

**M2 DoD（逐项）**：见 `plan/05-里程碑与发布.md` 的 M2 节。

## 三、既定口径清单（K 编号 · 动了会打挂测试的约定）

> M0 的 K1–K27 全部继续生效。M1 新增/变更如下。

| K | 口径 | 落在哪 | 动了会打挂什么 |
|---|---|---|---|
| K1 | 退出码五级语义：0 成功/1 检出问题/2 用法错误/3 缺依赖/**4 阶段未就绪** | `exit_codes.py` + README 退出码表 | `tests/test_exit_codes.py` + README 面 1/2 对账 |
| K2 | `4` 退役流程：**删常量 → 改 CLI 分派 → 改文档（README+plan/02）→ 改测试（含 `not hasattr` 防复活）** 四处同步 | 同上 | 少一处 = 幽灵语义复活；`test_exit_codes_module_has_no_resurrected_stage_codes` 会红 |
| K3 | 判定四态：`high`/`low`/`normal`/**`not_assessed`（拒判）**；**拒判 ≠ normal** | `model.py` + `engine/compare.py` | `tests/test_engine.py` + 两层基准的拒判用例 |
| K4 | 三级优先：**报告自印 > verified 默认 > 拒判**；`range_source` 必须显式进产物 | `engine/compare.py:select_range`（**唯一实现处**） | 规则层 `priority-*` 用例 + 样例层 `case-009` |
| K5 | **拒判语义单一定义点**：`judge()` 不得自带 `FLAG_NOT_ASSESSED` 分支 | `engine/compare.py` | `test_not_assessed_decision_has_single_definition_site`（源码断言） |
| K6 | 边界开闭语义由 **YAML 字段**定义，不在代码硬编码 | `model.py:BOUNDS_*` + YAML `bounds` | 规则层 `boundary-exact-*` + 样例层 `case-006/007` |
| K7 | 序列化契约：`json.dumps(sort_keys=True, ensure_ascii=False, indent=2)` + LF + 结尾单换行 | `serialize.py`（**写盘单点**） | `tests/test_determinism.py` + `test_json_dump_only_in_serialize_module` |
| K8 | `ensure_ascii=False` 是中文项目**必选** | 同上 | `test_canonical_json_keeps_chinese_readable` |
| K9 | 写盘一律原子（临时文件 → `os.replace`），文本一律 LF 归一 | `serialize.py:write_atomic` | `test_atomic_write_*` 系列 |
| K10 | 区间数值**只能来自 YAML**，源码零字面量（豁免仅结构常数 + 逐个登记的文件例外） | 全 `src/`+`tools/`+`tests/` | **零字面量门禁**（M1 建立）+ 变异验证 |
| K11 | loader 来源门禁：缺 `source.standard` / `status` 非法 / `verified` 而 `evidence` 空 → **拒绝加载** | `loader.py:gate_entry` | `tests/test_loader.py` 15 项 |
| K12 | `pending` 条目**不进判定路径** | `loader.py:IndicatorDict.verified_defaults` | `test_verified_defaults_excludes_pending` + 变异 |
| K13 | 判定内核**纯函数**：无 I/O import、无时钟/随机、无解读性措辞 | `engine/compare.py` | `tests/test_layering.py` + `test_engine.py` |
| K14 | 渲染层**零判定**：无大小比较、无算术、不 import 内核 | `report/html.py` | `test_renderer_has_no_*` 三条 |
| K15 | 报告**零外链**：渲染出口**常驻**调用 `assert_no_external_resources` | `report/html.py` + `report/guard.py` | `test_renderer_calls_external_resource_guard_always` |
| K16 | 扫描器源码**不得出现完整 scheme 词面**（token 运行时拼接） | `report/guard.py` | `test_guard_source_itself_has_no_scheme_literal` |
| K17 | stdlib 判定用**冻结名单制**（禁用 `sys.stdlib_module_names`，3.8 上是空集） | `tests/test_readme_gate.py:STDLIB_FROZEN` | `test_frozen_stdlib_list_covers_actually_used_stdlib` |
| K18 | 门禁扫描面 = `git ls-files --cached --others --exclude-standard`（含新增未提交文件） | `tests/helpers.py:tracked_files` | 扫描面为空的自证断言会红 |
| K19 | PII gate 三重拦截面 + **双向**自证 + 白名单是**判定词表** | `tools/pii_gate.py` | `tests/test_pii_gate.py` |
| K20 | 编码守卫探针式 reconfigure（不硬改中文控制台） | `encoding.py` | `tests/test_encoding.py` |
| K21 | 冻结态缺随包数据**必须报错**，不静默回落 | `paths.py:resolve_data_dir` | `test_frozen_state_without_bundled_data_raises` |
| K22 | README 安装面**五面对账** | `tests/test_readme_gate.py` | 改 CLI 或 README 忘同步 → 红 |
| K23 | dev extras 必须覆盖**全部测试期依赖**；README 与 CI 用**同一 extras 集合** | `pyproject.toml` + README + CI | `test_face4_dev_extra_covers_test_time_deps` |
| K24 | 基准"未启用"不冒充通过：`--only` 未选中套件标 `not_enabled` 且**不计入通过数** | `benchmark/runner.py` + `samples.py` | `test_bench_not_enabled_suites_are_excluded_from_pass_count` |
| K25 | 基准**可证伪探活**：注入已知缺陷 → 必须报未达标 | 两层 runner 的 `PROBE_FAULT_KIND` | CI 的 `bench --probe-fault` 步骤（退出码必须 1） |
| K26 | 真值库**只存输入与期望**，禁 `observed` 类字段 | `data/samples/truth/` | `tests/test_samples.py` 扫描 + 变异 |
| **K28** | **适用域是硬门**：`applies_to.sex` 与样本主体不符/未知 → **等同无区间 → 拒判**；未知约束值**抛错**不静默降级 | `engine/compare.py:range_applies_to`（**唯一实现处**）+ `model.py:ALL_SEX` | `test_sex_constraint_*` 5 项 + 样例层 `case-004`（不该命中）+ `case-005`（该命中） |
| **K29** | **趋势三态单一定义点**：`up`/`down`/`flat` 只由 `engine.trend_direction` 定；生成器的 `trend:*` 标签必须被实算覆盖（declared ⊆ computed） | `engine/compare.py` + `tools/gen_samples.py:_assert_trend_tags_match` | `test_trend_direction_three_states` + 生成器自校验 |
| **K30** | **生成器确定性**：禁 stdlib `random`/时钟/`hash()`（字符串哈希带随机盐）/`set` 迭代序；落盘经 `write_atomic` | `tools/gen_samples.py` | `tests/test_samples.py` 三条守门 + 变异"引入时钟→必红" |
| **K31** | **真值与引擎同源**：生成器必须 import 并**调用** `engine.compare`/`range_applies_to`/`trend_direction`，且**不得自写 `value` vs `low/high` 比较** | `tools/gen_samples.py` | `test_generator_calls_engine_compare` + `test_generator_uses_engine_compare_not_own_comparison` |
| **K32** | **数据台账是生成物**：`assets.csv` 由 `verify_ledger.py --update` 重算；手改被 `--verify` 检出 | `tools/verify_ledger.py` + `data/ledger/assets.csv` | `test_ledger_verify_passes` + 变异"手改台账→必红" |
| **K33** | **覆盖度门槛以数据下发**（非代码 if）：`manifest.json` 的 `thresholds` 逐行 `sampled >= minimum`；**总数/采样数双登记** + 显式"抽样覆盖非穷举" | `data/samples/manifest.json` + `benchmark/samples.py:run_coverage_gate` | `test_manifest_thresholds_are_all_met` + `test_manifest_declares_sampling_not_exhaustive` |
| **K34** | **基准分层且 `--only` 跨层校验**：只校验一层会把另一层套件名误判成"不存在" | `benchmark/layered.py:all_suite_names` | `test_bench_only_accepts_suite_names_from_both_layers` |
| **K35** | **测试夹具从 YAML 取**（`helpers.yaml_bounds` 等）：测试里手写区间数值 = 第二处定义，零字面量门禁会红 | `tests/helpers.py` | 零字面量门禁扫 `tests/` |
| **K36** | **样例层数据不在位时如实标未启用**，不伪造通过（`data/samples/` 是开发期资产，不随包分发） | `benchmark/samples.py:_data_unavailable` | `test_sample_layer_reports_unavailable_data_instead_of_faking_pass` |

## 四、本机环境坑（只写实测过的）

- **用 `py` 不是 `python`**（后者是商店占位符，实测直接 `exit 49`）；跑中文输出加 `-X utf8`。
- **本机双通道**：`py -3.8`（3.8.8）与 `py -3.12`（3.12.10）**都可用**，各自独立装过本包（`-e .`）。两者收集数必须一致（当前 192/192）。
- **venv 通道实测**：`py -3.12 -m venv .venv-clean` 可建；**`--no-build-isolation` 会因 venv 内无 setuptools 而失败**——按 README 的普通 `pip install -e .` 走。
- **pip 走镜像**：`-i https://pypi.tuna.tsinghua.edu.cn/simple`；若被代理污染加 `NO_PROXY="*" no_proxy="*"`。
- **全程 `PYTHONDONTWRITEBYTECODE=1`**（含 pip install）：本机 pyc 偶发损坏会造出随机失败/测试数波动；出怪错先清 `__pycache__` 再跑，**单轮崩溃直接重试即恢复**。
- **临时 venv / 探针目录名要进 `.gitignore`**：`.venv*/` 通配。**M1 实测新坑**：随手建的探针目录（如 `.probe-tmp/`）会被门禁扫描面扫进，导致行尾守门假红——**排查用的临时目录一律建在仓库外**（或用完立刻删）。
- **网络探测结论（M1 实测）**：`www.wsbz.org.cn` 无解析；`nhc.gov.cn` 412；`openstd.samr.gov.cn` 不含 WS/T；
  **`csres.com` 书目页可直连**（关键词须 GBK 编码：`urllib.parse.quote(kw.encode("gbk"))`）。全文仍付费。
- **Git Bash 下 `sed -n`/`grep` 可正常读中文文件**；`git log` 中文乱码仅是显示问题。
- **变异验证脚本已内建**（`tools/mutation_check.py`，19 条）：自己动手改源码做变异时，**每次改完先 `grep` 确认改动真的落盘**再跑断言。

## 五、DoD 逐项 checklist（M1）

- [x] `indicators.yaml` 覆盖五指标域各 ≥1 项，无未挂来源条目可生效（loader 硬门 15 项）
- [x] 生成器确定性：固定 seed，两次运行**逐字节一致**（`--check` 绿，25 产物）
- [x] `data/samples/` 覆盖覆盖度门槛表**全部 22 行**（含自印覆盖默认值、`threshold_exact` 双向、`near_miss`、反向样例、性别适用域含"不该命中"、低置信复核含阴性对照、单位变体）
- [x] 真值库**无 `observed` 类字段**（守门扫描 + 变异验证）
- [x] 真值与引擎**共用同一处判定规则**（import 并调用引擎；禁止自写比较；守门断言）
- [x] `data/ledger/assets.csv` 由 `verify_ledger.py --update` 重算（26 条；手改被检出，变异验证）
- [x] **零字面量门禁**建立并变异验证（往引擎塞区间字面量 → 必红）
- [x] `gen_samples.py --check` 位级一致守门绿
- [x] 基准跑通（两层 64/64）且**可证伪探活**（`--probe-fault` → exit 1）
- [x] 双解释器全量测试绿，**收集数一致**（192 / 192）
- [x] 干净环境（新 venv 照 README）逐条跑通（192 passed；裸 console script selftest 6/6 + bench 64/64）
- [x] 每条新增守门做过**变异验证**（19/19 全红后恢复绿）
- [x] PII gate 双向自证（阳性 6 被拦 + 阴性 4 放行）
- [x] 无远端期间的"未推送"状态已在 README/plan/00 如实标注
- [x] `plan/00/04/05/06` + `data/README.md` 状态回写
- [x] `plan/HANDOFF-M2.md` 已落盘（本文件）
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
PYTHONPATH=src py -3.12 -m checkup_ledger bench --only 边界语义        # 规则层套件
PYTHONPATH=src py -3.12 -m checkup_ledger bench --only 样例真值回归     # 样例层套件
PYTHONPATH=src py -3.12 -m checkup_ledger ingest                      # 期望 exit 4（M2 退役）

# 数据资产
py -3.12 tools/gen_samples.py             # 生成/覆盖 data/samples/
py -3.12 tools/gen_samples.py --check     # 位级一致守门
py -3.12 tools/verify_ledger.py --update  # 重算台账
py -3.12 tools/verify_ledger.py --verify  # 复核（手改被检出）

# 守门自证
py -3.12 tools/mutation_check.py          # 19 条变异验证（期望 exit 0）
py -3.12 tools/pii_gate.py --selftest     # 双向自证（期望 exit 0）
py -3.12 tools/pii_gate.py --staged       # pre-commit 的真实调用形态

# 干净环境（照 README）
py -3.12 -m venv .venv-clean
.venv-clean/Scripts/python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv-clean/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv-clean/Scripts/python.exe -m pytest
rm -rf .venv-clean
```

**启动下一棒（用户侧命令）**：
```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务
```
