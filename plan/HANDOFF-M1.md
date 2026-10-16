# HANDOFF-M1 · 数据先行（续接快照）

> 用法：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务`
> （库内一律相对路径，绝对路径只出现在用户侧启动命令里）
> 上一棒：M0 骨架与基建（已完成，见 plan/00 的 M0 实测证据节）

## 一、当前进度 + 证据

**M0 已达成**：仓库可跑、纪律可验、门禁在位。业务判定链已实现（内核 + 基准），
但**输入/规范化/台账/导出四层尚未落地**（走 exit 4 显式拦截）。

已落盘产物（相对路径）：

| 产物 | 说明 |
|---|---|
| `plan/00–06` | 计划文档全套（00 已按 M0 实测回写） |
| `README.md` | 用户向：定位/快速开始/常驻免责/退出码表/已知环境问题 |
| `pyproject.toml` | extras 分层（dev/pdf/ocr/freeze）+ package-data 白名单 |
| `src/checkup_ledger/` | `cli.py`（五级退出码）/ `model.py`（4 个 IR）/ `engine/compare.py`（判定内核）/ `serialize.py`（写盘单点）/ `encoding.py` / `paths.py` / `loader.py`（来源门禁）/ `report/html.py` + `report/guard.py`（零外链） / `benchmark/runner.py` + `benchmark/cases.json` / `data/indicators.yaml` |
| `tests/` | 154 项：退出码 / README 安装面五面对账 / 编码 / 确定性 / 行尾 / PII gate / 桩哨兵 / 分层与零外链 / 内核契约 / loader / paths |
| `tools/` | `pii_gate.py`（三重拦截面 + 双向自证）/ `mutation_check.py`（12 条变异验证） |
| `.githooks/pre-commit` | PII gate 钩子 |
| `.github/workflows/ci.yml` | CI 三矩阵预置（**从未实跑**） |
| `.gitattributes` | `* text=auto eol=lf` + 二进制/冻结件 `-text` |

**实测证据（本地等价校验，未接远端，CI 待首推验证）**：

```
py -3.12 -m pytest                  → 154 passed
py -3.8  -m pytest                  → 154 passed（收集数一致）
干净 venv 照 README 走              → 154 passed；核心装只拉 PyYAML
py -3.12 tools/mutation_check.py    → 12 条变异全部使目标守门变红，恢复后全绿
py -3.12 -m checkup_ledger bench    → 达标 22/22（exit 0）
... bench --probe-fault             → 未达标（exit 1，探活有效）
python tools/pii_gate.py --selftest → 阳性 6 项被拦 + 阴性 4 项放行
```

**M0 期间修掉的真缺陷**（留档，防重犯）：
1. `judge()` 重复实现"无区间→拒判"（与 `compare()` 两份口径）→ 已改单点 + 守门；
2. `.gitignore` 漏 `.venv-clean/` 通配 → 门禁扫描面扫进第三方包；
3. 门禁扫描面把临时 venv 当仓库内容 → 已加排除项。

## 二、下一棒待办（M1 数据先行）

按 `plan/04-数据计划.md` 第六节"M1 执行清单"逐项做：

1. **`src/checkup_ledger/data/indicators.yaml` 扩条目并核对来源**
   - 覆盖五域（血常规/肝功能/血脂/肾功能/血糖）各 ≥1 项（现有 10 项已覆盖五域）；
   - 凡查不到原文的一律保持 `status: pending` + `evidence` 记渠道；
   - 拿到原文逐条核对后升 `verified`（**必须填 `evidence`**，否则 loader 拒收）。
2. **`tools/gen_samples.py` 确定性生成器**
   - **禁 stdlib `random`、禁 set 迭代序、禁系统时钟** → 自研确定性 RNG（splitmix64 变体），固定 seed；
   - 落盘一律经 `serialize.write_atomic()`；产物无时间戳；
   - 配 `--check` 位级一致守门（两次运行逐字节一致）。
3. **`data/samples/`**：`cases/`（合成报告）+ `truth/*.truth.json` + `manifest.json`
   - 覆盖 `plan/04` 第三节覆盖度门槛表**全部行**，尤其：
     - **自印覆盖默认值**（≥1，结论相反的用例）
     - `threshold_exact` / `near_miss`（边界双向）
     - **反向样例**（"这条规则不该命中"，≥1）
     - 低置信复核（含"未复核不落库"阴性对照）
     - 性别相关（`applies_to.sex` 生效 + 不该命中反向样例）
   - **真值库只存"输入与期望"，禁止 `observed`/`actual`/`got` 字段**（观测由观测器运行时实算）；
   - 真值与引擎**共用同一处判定规则**（import `engine.compare`，禁止复制第二份逻辑）。
4. **`tools/verify_ledger.py --update`** → `data/ledger/assets.csv`（sha256 台账，生成物非手编）。
5. **零字面量门禁** `tests/test_no_literal_thresholds.py`
   - token 集从 YAML **实算**（不手写）；词边界匹配；扫描面含 docstring/注释/字符串字面量；
   - 豁免口径写死（0/1 等结构常数）；**防御性常数不是豁免理由**；
   - **必须做变异验证**：往引擎塞一个区间字面量 → 门禁必红。
6. **基准扩到样例驱动层**：现有 `bench` 是规则驱动层（不读真值库，专治"样本没覆盖的端点"）；
   M1 要加样例驱动层（读 `data/samples/`），两层**分层**且新增套件**注册进 `--only` 白名单**。
7. **真值覆盖度门槛以 manifest 下发**（数据非代码）；覆盖声明**总数/采样数双登记** + 显式"抽样覆盖非穷举"。

**M1 DoD（逐项）**：见 `plan/05-里程碑与发布.md` 的 M1 节。

## 三、既定口径清单（K 编号 · 动了会打挂测试的约定）

| K | 口径 | 落在哪 | 动了会打挂什么 |
|---|---|---|---|
| K1 | 退出码五级语义：0 成功/1 检出问题/2 用法错误/3 缺依赖/**4 阶段未就绪** | `src/checkup_ledger/exit_codes.py` + README 退出码表 | `tests/test_exit_codes.py` 全量 + README 面 1/2 对账 |
| K2 | `4` 退役流程：**删常量 → 改 CLI 分派 → 改文档（README+plan/02）→ 改测试（含 `not hasattr` 防复活）** 四处同步 | 同上 | 少一处 = 幽灵语义复活；`test_exit_codes_module_has_no_resurrected_stage_codes` 会红 |
| K3 | 判定四态：`high`/`low`/`normal`/**`not_assessed`（拒判）**；**拒判 ≠ normal** | `model.py` + `engine/compare.py` | `tests/test_engine.py` + `bench` 的 `negative-*` 用例 |
| K4 | 三级优先：**报告自印 > verified 默认 > 拒判**；`range_source` 必须显式进产物 | `engine/compare.py:select_range`（**唯一实现处**） | `bench` 的 `priority-*` 用例（含自印覆盖默认值 2 例） |
| K5 | **拒判语义单一定义点**：`judge()` 不得自带 `FLAG_NOT_ASSESSED` 分支，全权委托 `compare()` | `engine/compare.py` | `test_not_assessed_decision_has_single_definition_site`（源码断言） |
| K6 | 边界开闭语义：`closed`（闭区间，恰在边界=正常）/ `open`（开区间，恰在边界=越界）；**由 YAML 字段定义，不在代码硬编码** | `model.py:BOUNDS_*` + YAML `bounds` | `bench` 的 `boundary-exact-*` 4 例 |
| K7 | 序列化契约：`json.dumps(sort_keys=True, ensure_ascii=False, indent=2)` + LF + 结尾单换行 | `serialize.py`（**写盘单点**） | `tests/test_determinism.py` + `test_json_dump_only_in_serialize_module` |
| K8 | `ensure_ascii=False` 是中文项目**必选**（否则 diff 不可读） | 同上 | `test_canonical_json_keeps_chinese_readable` |
| K9 | 写盘一律原子（临时文件 → `os.replace`），文本一律 LF 归一 | `serialize.py:write_atomic` | `test_atomic_write_*` 系列 |
| K10 | 区间数值**只能来自 YAML**，源码零字面量（豁免 0/1/2 等结构常数） | 全 `src/` | 零字面量门禁（M1 建立）+ `test_engine_has_no_embedded_range_numbers` |
| K11 | loader 来源门禁：缺 `source.standard` / `status` 非法 / `verified` 而 `evidence` 空 → **拒绝加载**并进"未启用清单" | `loader.py:gate_entry` | `tests/test_loader.py` 12 项 |
| K12 | `pending` 条目**不进判定路径**（可作展示，不可作区间默认值） | `loader.py:IndicatorDict.verified_defaults` | `test_verified_defaults_excludes_pending` + 变异验证 |
| K13 | 判定内核**纯函数**：无 I/O import、无时钟/随机、无解读性措辞（docstring 除外） | `engine/compare.py` | `tests/test_layering.py` 4 条 + `test_engine.py` |
| K14 | 渲染层**零判定**：无大小比较、无算术、不 import 内核 | `report/html.py` | `test_renderer_has_no_arithmetic` / `..._has_no_range_comparisons_via_operators` / `..._does_not_import_engine` |
| K15 | 报告**零外链**：渲染出口**常驻**调用 `assert_no_external_resources`（不是测试里验一次） | `report/html.py` + `report/guard.py` | `test_renderer_calls_external_resource_guard_always` + `test_rendered_report_has_no_external_reference` |
| K16 | 扫描器源码**不得出现完整 scheme 词面**（token 运行时拼接） | `report/guard.py` | `test_guard_source_itself_has_no_scheme_literal` |
| K17 | stdlib 判定用**冻结名单制**，**禁用 `sys.stdlib_module_names`**（3.10+ 才有；3.8 上空集 → 每个标准库判成第三方 → 全量假红） | `tests/test_readme_gate.py:STDLIB_FROZEN` | 新增 stdlib import 忘进名单 → `test_frozen_stdlib_list_covers_actually_used_stdlib` 红 |
| K18 | 门禁扫描面 = `git ls-files --cached --others --exclude-standard`（**含新增未提交文件**）+ 排除 venv/构建产物 | `tests/helpers.py:tracked_files` | 扫描面为空的自证断言会红 |
| K19 | PII gate 三重拦截面（路径/类型/内容）+ **双向**自证 + 白名单是**判定词表**（扩表正常，绕过=造假） | `tools/pii_gate.py` | `tests/test_pii_gate.py` 21 项 |
| K20 | 编码守卫探针式 reconfigure：utf-8/cp936 放行、cp1252/ascii 触发；**不硬改中文控制台** | `encoding.py` | `tests/test_encoding.py` |
| K21 | 冻结态缺随包数据**必须报错**，不静默回落 | `paths.py:resolve_data_dir` | `test_frozen_state_without_bundled_data_raises` + 变异验证 |
| K22 | README 安装面**五面对账**（命令/旗标反射、子命令双向、tests import 落点、extras 双向、包布局） | `tests/test_readme_gate.py` | 改了 CLI 或 README 忘同步 → 红 |
| K23 | dev extras 必须覆盖**全部测试期依赖**；README 与 CI 用**同一 extras 集合** | `pyproject.toml` + README + CI | `test_face4_dev_extra_covers_test_time_deps` |
| K24 | 基准"未启用"不冒充通过：`--only` 未选中套件标 `not_enabled` 且**不计入通过数** | `benchmark/runner.py` | `test_exit_ok_from_bench` + `--only` 行为 |
| K25 | 基准**可证伪探活**：注入已知缺陷 → 必须报未达标 | `benchmark/runner.py:PROBE_FAULT_KIND` | CI 里的 `bench --probe-fault` 步骤（退出码必须 1） |
| K26 | 真值库**只存输入与期望**，禁 `observed` 类字段 | `data/samples/truth/`（M1 建立） | 守门扫描（M1 建立） |
| K27 | 每个里程碑收尾 = **DoD 验证 → plan/00·05·06 回写 → 写 HANDOFF-M\<next\> → commit**（硬约束） | 本文件 | 缺 HANDOFF 即未收尾 |

## 四、本机环境坑（只写实测过的）

- **用 `py` 不是 `python`**（后者可能是商店占位符）；跑中文输出加 `-X utf8`。
- **本机双通道**：`py -3.8`（3.8.8）与 `py -3.12`（3.12.10）**都可用**，各自独立装过本包（`-e .`）。两者收集数必须一致。
- **venv 通道实测**：`py -3.12 -m venv .venv-clean` 可建；**`--no-build-isolation` 会因 venv 内无 setuptools 而失败**（`BackendUnavailable: Cannot import 'setuptools.build_meta'`）——按 README 的**普通 `pip install -e .`** 走（会拉构建依赖），或先 `pip install setuptools`。
- **pip 走镜像**：`-i https://pypi.tuna.tsinghua.edu.cn/simple`；若被代理污染加 `NO_PROXY="*" no_proxy="*"`。
- **全程 `PYTHONDONTWRITEBYTECODE=1`**（含 pip install）：本机 pyc 偶发损坏会造出随机失败/测试数波动；出怪错先清 `__pycache__` 再跑，**单轮崩溃直接重试即恢复**。
- **临时 venv 目录名要进 .gitignore**：用 `.venv-clean/` 这类名字时，`.gitignore` 必须用 `.venv*/` 通配（只写 `.venv/` 会漏），否则门禁扫描面会扫进第三方包造成假红。
- **Git Bash 下 `sed -n`/`grep` 可正常读中文文件**；`git log` 中文乱码仅是显示问题，hash 与 status 可信。
- **变异验证脚本已内建**（`tools/mutation_check.py`）：自己动手改源码做变异时，**每次改完先 `grep` 确认改动真的落盘**再跑断言——本机实测出现过"变异没生效却以为生效"的假结论。

## 五、DoD 逐项 checklist（M0）

- [x] `version`/`selftest`/`--help` 三通路（`python -m` / 裸命令 / 未知旗标）退出码符合契约 —— 裸命令在干净 venv 里验过
- [x] 退出码 0/2/3/4 各至少一条断言（`1` 已由 `bench --probe-fault` 覆盖）
- [x] 双解释器（3.8 + 3.12）全量 pytest 绿，**收集数一致**（154 / 154）
- [x] README 安装面五面对账绿 + 变异验证 ×5（假旗标 / 注册表伪造 / 测试注入 pandas / extras 注入 / packages.find 改名）—— 变异由 `mutation_check.py` 的 12 条覆盖（含 cli/paths/loader/serialize 面）
- [x] 编码守卫在 `TextIOWrapper(cp1252, errors="strict")` 下不 `UnicodeEncodeError`
- [x] 行尾守门：已跟踪文本文件零 `\r`
- [x] 双跑字节一致测试绿
- [x] PII gate：阳性样本被拦 + 阴性对照放行（**双向**）
- [x] 桩哨兵串扫描零命中
- [x] 每条新增守门做过**变异验证**（12/12 全红后恢复绿）
- [x] 干净环境（新 venv 照 README）逐条跑通，暴露的问题已修复并加回归（2 处）
- [x] 无远端期间的"未推送"状态已在 README/plan/00 如实标注
- [x] `plan/00` 状态回写
- [x] `plan/HANDOFF-M1.md` 已落盘（本文件）
- [ ] commit（本对话内完成；**不 push**——无远端）

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -m pytest
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.8  -m pytest

# 冒烟（三条通路）
PYTHONPATH=src py -3.12 -m checkup_ledger selftest
PYTHONPATH=src py -3.12 -m checkup_ledger indicators
PYTHONPATH=src py -3.12 -m checkup_ledger bench
PYTHONPATH=src py -3.12 -m checkup_ledger bench --probe-fault   # 期望 exit 1
PYTHONPATH=src py -3.12 -m checkup_ledger bench --only 边界语义
PYTHONPATH=src py -3.12 -m checkup_ledger ingest                # 期望 exit 4（未就绪）

# 守门自证
py -3.12 tools/mutation_check.py            # 12 条变异验证（期望 exit 0）
py -3.12 tools/pii_gate.py --selftest       # 双向自证（期望 exit 0）
py -3.12 tools/pii_gate.py --staged         # pre-commit 的真实调用形态

# 干净环境（照 README）
py -3.12 -m venv .venv-clean
.venv-clean/Scripts/python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv-clean/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv-clean/Scripts/python.exe -m pytest
rm -rf .venv-clean
```

**启动下一棒（用户侧命令）**：
```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务
```
