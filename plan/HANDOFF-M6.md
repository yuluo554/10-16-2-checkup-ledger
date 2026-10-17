# HANDOFF-M6 · 发布（续接快照）

> 用法：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M6.md" 继续完成任务`
> （库内一律相对路径，绝对路径只出现在用户侧启动命令里）
> 上一棒：M5 免安装交付物（已完成，见 plan/05 的 M5 实测证据节）

## 一、当前进度 + 证据

**M5 已达成**：免安装冻结产物**真构建、真扫、真跑**过，四条自证齐备。

已落盘产物（相对路径）：

| 产物 | 说明 |
|---|---|
| `plan/00–06` | 计划文档全套（00/02/03/05/06 + README + data/README 已按 M5 实测回写） |
| `src/checkup_ledger/frozen_entry.py` | **冻结入口薄壳**（绝对导入 + `sys.exit(main())`，AST 门守） |
| `tools/freeze_build.py` | 冻结构建与产物验证单点（清单 / 构建 / 对账 / 零上传 / 打包确定性 / 真跑） |
| `tests/test_frozen.py` | 两档门禁：静态档 32 项 + 实构建档 9 项（后者 `CHECKUP_LEDGER_FREEZE_BUILD=1` 才跑） |
| `tools/mutation_check.py` | 变异表扩到 **80 条**（M5 新增 16 条，全部变红后恢复绿） |

**M5 实测证据（本地等价校验，未接远端，CI 待首推验证）**：

```
py -3.12 -m pytest                  → 436 passed, 10 skipped
py -3.8  -m pytest                  → 436 passed, 10 skipped（收集数一致）
py -3.12 tools/freeze_build.py --out <仓库外> → 四项齐备（对账 3 份 / 零上传 / 打包确定性 / 真跑）
CHECKUP_LEDGER_FREEZE_BUILD=1 py -3.12 -m pytest tests/test_frozen.py → 41 passed
冻结态 selftest（中立目录 + env -i 等价） → 6/6；data_dir 报 <dist>/_internal/data
反例：数据目录挪出 exe 目录 → data_dir FAIL，整体 exit 1（门可证伪）
冻结产物 ingest / ledger            → exit 0（PDF 文本层 4 行；入库 4 条）
体积：朴素构建 60 MB / PyZ 480 个模块 → 排除后 44 MB / 269 个
py -3.12 tools/mutation_check.py    → 80 条变异全部变红，恢复后全绿
py -3.12 tools/verify_ledger.py --verify → 37 条资产 sha256 逐字节一致（M5 未改数据资产）
```

**M5 期间修掉/登记的实测偏差**（留档，防重犯，详见 plan/05 M5 节）：

1. `--exclude-module socket` 会让 `import pdfplumber` 直接失败（PDF 文本层不可用）→
   零上传口径收窄为"**无可出站能力组件**"，`socket`/`selectors` 残留**显式登记**；
2. 只扫 dist 目录树时 `ssl` 完全不可见（模块在 exe 内的 PYZ 归档里）→ 断言改读归档模块名表；
3. 冻结产物**不吃** `PYTHONUTF8`/`PYTHONIOENCODING`（引导程序自建 `PyConfig`）→
   验证侧先 utf-8、失败回落 locale（初版硬编码 utf-8 造成断言假红）；
4. **exe 构建逐字节可复现不成立**（同机连打两次 sha256 都不同）→ 口径收窄为"打包过程确定"；
5. `package-data` 的空模式 `data/*.yml` → 合法的空模式**逐条登记理由**，未登记仍报错；
6. **中立环境跑产物会在 CWD 里臆造一个 `~` 目录**（`expanduser("~")` 在无主目录变量时
   原样返回 `~`，经 `abspath` 落成"CWD 下的 `~` 文件夹"）→ 解不出主目录 = **不写、不抛、
   绝不回落 CWD**（按未接受处理，免责照念）+ 3 条回归测试 + 1 条端到端冻结态门 + 2 条变异；
7. **两处门是"镜子"**（从被测常量取期望）→ 判据面钉在测试侧，实现只许"覆盖"它。

> K 编号已到 **K81**（见下节）；变异表 **80 条**（M5 新增 16 条）。

## 二、下一棒待办（M6 发布）

按 `plan/05-里程碑与发布.md` 的 M6 节逐项做。**对外动作（建仓 / 推公开 / tag / Release）
执行前向用户确认。**

1. **建仓前脱敏四步 + 干净环境验证逐项留档**（含退出码语义逐条成表）。
2. **历史 = 工作树三连核对**：`git status` / `git log --oneline | head` / `git rev-list --count HEAD`。
3. `gh repo create yuluo554/10-16-2-checkup-ledger --public`（署名 yuluo554）。
4. **CI 首跑**（矩阵见 `.github/workflows/ci.yml`：win/3.8、win/3.12、ubuntu/3.12），
   `gh run list` 按 head_sha 逐条与本地 `git log` 配对；**首跑失败不遮掩**，
   失败原因与修复提交如实配对留档。
   - **M6 可选加项（M5 未做，留给 M6 决定）**：CI 目前只装 `.[dev]`，M5 的实构建档
     （`CHECKUP_LEDGER_FREEZE_BUILD=1`）**不在 CI 里跑**——本地真跑过、CI 未覆盖。
     若要进 CI，在 3.12 作业加 `.[dev,freeze]` 与该变量即可（会多约 1–2 分钟构建）。
     加与不加都要在 `plan/RELEASE-M6.md` 里如实写明。
5. **发布物本体已验**：真下载 Release 附件 → sha256 与留档一致 → 中立目录解压跑冻结态自检。
6. `gh release view <tag> --json assets,tagName,isDraft`（draft=false + 附件名在列）。
7. **发布后全新 clone 复核**（GitHub 拉一次真克隆跑测试）。
8. README 状态行转正；缓议项**逐条全表**清零（含显式"跳过"决策）。
9. 元信息终检：topics / description / release assets digest 与 README 定位一致。
10. `plan/RELEASE-M6.md` 只写实测到的（未跑的项留 ⬜ 并说明原因，不留空不预填）。

**M6 DoD（逐项）**：见 `plan/05-里程碑与发布.md` 的 M6 节。

## 三、既定口径清单（K 编号 · 动了会打挂测试的约定）

> M0 的 K1–K27、M1 的 K28–K36、M2 的 K37–K46、M3 的 K47–K58、M4 的 K59–K73
> 全部继续生效。M5 新增如下。

| K | 口径 | 落在哪 | 动了会打挂什么 |
|---|---|---|---|
| **K74** | **冻结入口是薄壳**：**绝对导入**（`from checkup_ledger.cli import main`）、无函数/无类、只把 `main()` 交给 `sys.exit`；`__main__.py` 另有 `__main__` 守卫（两条通路不共用文件） | `src/checkup_ledger/frozen_entry.py` | `test_frozen_entry_uses_absolute_imports_only` / `test_frozen_entry_exists_and_is_a_thin_shell` / `test_frozen_entry_imports_the_package_cli_not_a_relative_module` / `test_dunder_main_is_present_and_guarded` + 2 条变异 |
| **K75** | **随包数据白名单单一来源 = `pyproject.toml` 的 `package-data`**；落点两条（`data/` → exe 旁 `data/`；`benchmark/` → 包内 `checkup_ledger/benchmark/`）；**样例集不随包**；合法的空模式**逐条登记理由**（`DECLARED_EMPTY_PATTERNS`） | `tools/freeze_build.py:_package_data_patterns/data_whitelist/dest_for` | `test_data_whitelist_comes_from_pyproject_not_a_second_list` / `test_build_command_copies_every_whitelisted_data_file` / `test_dest_for_*` / `test_declared_empty_patterns_are_exactly_as_declared` / `test_non_declared_empty_pattern_raises` / `test_build_command_does_not_copy_sample_set` + 3 条变异 |
| **K76** | **内嵌数据对账是双向的**：不丢 + 不多 + 逐份 sha256 与仓库冻结件一致 | `tools/freeze_build.py:verify_embedded_data` | `test_embedded_data_matches_whitelist_bidirectionally`（实构建档） |
| **K77** | **"零上传"判据 = 无可出站能力组件**（TLS/HTTP/FTP/SMTP/telnet/XML-RPC/异步与并发），**不是**"包里没有 socket"；`socket`/`selectors` 残留**显式登记**（清单 + 理由 + 测试锁死）；断言必须读 exe 内**归档模块名表**（只扫目录树对 PYZ 内的模块是瞎的） | `tools/freeze_build.py:OUTBOUND_EXCLUDES` / `SOCKET_RESIDUE_*` / `scan_no_outbound` / `bundle_module_names` | `test_build_command_excludes_every_outbound_component` / `test_outbound_constant_covers_the_judgement_face` / `test_outbound_module_hits_*` / `test_socket_residue_is_declared_with_a_reason` / `test_bundle_contains_no_outbound_components` + 4 条变异 |
| **K78** | **打包确定性只承诺"同一份 dist 的打包过程"**：`ZIP_STORED` + 条目按 POSIX 相对路径排序 + 固定 `date_time`/`create_system`/`external_attr`；**exe 本体逐字节可复现不成立**（跨机、跨次都不成立，实测留档） | `tools/freeze_build.py:pack_deterministic_zip/ZIP_EPOCH` | `test_deterministic_zip_is_byte_identical_across_two_packs` / `test_deterministic_zip_entries_are_sorted_and_stored` / `test_deterministic_zip_survives_a_different_file_order_on_disk` / `test_zip_members_are_sorted_by_posix_relative_path` + 2 条变异 |
| **K79** | **真跑产物换环境**：中立目录（仓库外）+ `env -i` 等价环境（Windows 只留 `SYSTEMROOT`）；**冻结产物不吃 `PYTHONUTF8`/`PYTHONIOENCODING`** → 验证侧 `decode_output()` 先 utf-8、失败回落 locale | `tools/freeze_build.py:neutral_env/run_frozen_smoke/decode_output` | `test_neutral_env_drops_everything_but_systemroot` / `test_stdout_decoder_handles_utf8_and_locale_bytes` / `test_frozen_selftest_passes_and_reports_data_dir_inside_exe_dir` / `test_frozen_data_dir_check_fails_when_data_is_moved_outside` + 3 条变异 |
| **K80** | **冻结构建固定在 PyInstaller ≥6 那条解释器通道**（`require_pyinstaller()` 对 <6 直接拒绝） | `tools/freeze_build.py:require_pyinstaller` | `test_require_pyinstaller_rejects_below_major_six` / `test_require_pyinstaller_accepts_major_six_or_above` + 1 条变异 |
| **K81** | **判据面钉在测试侧，实现只许"覆盖"**：`REQUIRED_OUTBOUND_COMPONENTS` / `REQUIRED_PACKAGED_DATA` 是 DoD 口径的字面登记；断言 = "实现覆盖它"（**不得**从被测常量取期望——那是镜子不是门） | `tests/test_frozen.py` | `test_build_command_excludes_every_outbound_component` / `test_build_command_copies_every_whitelisted_data_file` / `test_outbound_constant_covers_the_judgement_face` |
| **K82** | **免责标记：解不出主目录就不写**（`expanduser("~")` 原样返回 `~` 时按"没有可写位置"处理）——返回 `None`/`False`，不抛错，**绝不回落 CWD**；主目录可解析时行为不变 | `src/checkup_ledger/disclaimer.py:home_dir/accepted_path/mark_accepted` | `test_disclaimer_does_not_invent_a_tilde_directory` / `test_disclaimer_uses_real_home_when_resolvable` / `test_disclaimer_rejects_an_unexpanded_tilde_passed_explicitly` / `test_frozen_run_leaves_no_tilde_directory_in_neutral_cwd` + 2 条变异 |

## 四、本机环境坑（只写实测过的）

- **用 `py` 不是 `python`**（后者是商店占位符，实测直接 `exit 49`）；跑中文输出加 `-X utf8`。
- **本机双通道**：`py -3.8`（3.8.8）与 `py -3.12`（3.12.10）**都可用**，各自独立装过本包（`-e .`）。
  两者收集数必须一致（当前 436/436，各 10 skipped——10 = OCR 真跑 1 + 实构建档 9）。
- **PyInstaller 只装在 3.12 通道**（6.22.3）；`py -3.8` 上是 5.13.2——**M5 起冻结构建只在
  3.12 通道做**（`require_pyinstaller()` 拒绝 <6）。若换机器：`py -3.12 -m pip install pyinstaller>=6.0`。
- **`[pdf]` 两通道都已装**（3.8 与 3.12 各装过 `pdfplumber`）→ PDF 相关测试双通道都跑得通。
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
  **不能用 `os.path.relpath` 跨盘**（抛 `ValueError`）。生成器与冻结构建已按逻辑前缀拼路径。
  **冻结构建产物一律用 `--out <仓库外目录>`**：work/spec/dist 落在仓库内会被门禁扫描面扫进。
- **Git Bash 会把 `CHECKUP_LEDGER_ACCEPTED=/tmp/x` 这类值改写成 `D:\tmp\x`**（MSYS 路径转换）：
  测首启免责时要么用 `MSYS_NO_PATHCONV=1`，要么直接用 `py -c` 走 Python 层（本机实测踩过）。
  同理，给产物传 Windows 路径（`--out`/`--db`/`--data-dir`）时加 `MSYS_NO_PATHCONV=1`。
- **网络探测结论**：`www.wsbz.org.cn` 无解析；`nhc.gov.cn` 412；`openstd.samr.gov.cn` 不含 WS/T；
  **`csres.com` 书目页可直连**（关键词须 GBK 编码）。全文仍付费。
- **Git Bash 下 `sed -n`/`grep` 可正常读中文文件**；`git log` 中文乱码仅是显示问题。
- **变异验证脚本已内建**（`tools/mutation_check.py`，80 条）：自己动手改源码做变异时，
  **每次改完先 `grep` 确认改动真的落盘**再跑断言。
- **零字面量门禁扫全文（含 docstring/注释）**：新写模块的注释里**别写具体区间端点**——
  写 `<下限>`/`<上限>` 这类指代。**M5 新增的坑**：版本号如 `6.22.3`、字节数如 `45164838` 里的
  片段都可能与端点同字面量 → 用**指代或程序化拼装**，不写裸数值。
- **冻结产物输出编码**：产物不吃 `PYTHONUTF8`/`PYTHONIOENCODING`（PyInstaller 引导程序自建
  `PyConfig`），按控制台编码自适应。脚本里读产物输出**必须走 `freeze_build.decode_output()`**
  （先 utf-8、失败回落 locale），否则本机会把"达标"读成乱码造成**断言假红**（实测踩过）。
- **`env -i` 裸环境里没有主目录变量**：免责标记**不写**（设计内行为，免责每次都念）。
  别把"多出一遍免责"读成缺陷；也别在那种环境里期望 `~` 被展开——`expanduser` 会原样
  返回 `~`（那正是会在 CWD 里建出 `~` 目录的那个坑，已修）。要固定标记位置就传
  `CHECKUP_LEDGER_ACCEPTED=<整文件路径>`。
- **Windows 下 SQLite 连接不关会让文件被占用**：台账句柄支持 `with`，测试/脚本一律用 `with`。

## 五、DoD 逐项 checklist（M5）

- [x] PyInstaller 冻结构建（≥6 通道），**首次实构建真跑过**（构建 exit 0 ≠ 产物可用）
- [x] 入口为**绝对导入的薄模块** + 有 `__main__`（AST 静态断言守）+ 未知参数 `exit 2`
- [x] 冻结态自检断言**数据目录落在 exe 目录内**（非冻结态不报 FAIL；反例可证伪）
- [x] 中立目录 + `env -i`（Windows 保留 `SYSTEMROOT`）真跑产物
- [x] **"零上传"可扫产物断言**（发行包内无 TLS/出站组件；读归档模块名表）
- [x] 打包**确定性**：同一 dist 两次打 zip 逐字节一致；留档写明 exe 构建**跨机/跨次都不可复现**
- [x] 内嵌数据对账：**入包集合 == 白名单**（双向）+ 逐份 sha256 与仓库冻结件一致
- [x] 双解释器全量测试绿，收集数一致（436 / 436，各 10 skipped）
- [x] 每条新增守门做过**变异验证**（80/80 全红后恢复绿）
- [x] 台账复核通过（37 条）；生成器位级一致（25 / 5）
- [x] PII gate 双向自证（阳性 6 被拦 + 阴性 4 放行）
- [x] 无远端期间的"未推送"状态已在 README/plan/00 如实标注
- [x] `plan/00/02/03/05/06` + `README.md` + `data/README.md` 状态回写
- [x] `plan/HANDOFF-M6.md` 已落盘（本文件）
- [ ] commit（本对话内完成；**不 push**——无远端）

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -m pytest
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.8  -m pytest

# 冻结构建与产物验证（M5）
py -3.12 -m pip install -e ".[dev,freeze]"
py -3.12 tools/freeze_build.py --out <仓库外目录>            # 四项齐备
py -3.12 tools/freeze_build.py --dist <产物目录> --smoke      # 只验证已有产物
CHECKUP_LEDGER_FREEZE_BUILD=1 py -3.12 -m pytest tests/test_frozen.py   # 实构建档

# 冒烟
PYTHONPATH=src py -3.12 -m checkup_ledger selftest
PYTHONPATH=src py -3.12 -m checkup_ledger indicators
PYTHONPATH=src py -3.12 -m checkup_ledger bench                       # 两层
PYTHONPATH=src py -3.12 -m checkup_ledger bench --probe-fault         # 期望 exit 1
PYTHONPATH=src py -3.12 -m checkup_ledger ingest data/samples/ingest/pdf/ingest-pdf-plain.pdf
PYTHONPATH=src py -3.12 -m checkup_ledger ledger data/samples/ingest/pdf/ingest-pdf-plain.pdf \
    --db <临时库> --date 2024-03-11 --subject 张三                  # 入库 4 条
PYTHONPATH=src py -3.12 -m checkup_ledger export data/samples/ingest/pdf/ingest-pdf-plain.pdf \
    --db <临时库> --date 2024-03-11 --fmt csv --out <临时>/s.csv
PYTHONPATH=src py -3.12 -m checkup_ledger report data/samples/ingest/pdf/ingest-pdf-plain.pdf \
    --db <临时库> --date 2024-03-11 --out <临时>/r.html
PYTHONPATH=src py -3.12 -m checkup_ledger no-such-cmd                  # 期望 exit 2

# 冻结产物冒烟（中立目录 + env -i 等价）
cd <仓库外中立目录>
MSYS_NO_PATHCONV=1 env -i SYSTEMROOT="C:\\Windows" <产物>/checkup-ledger.exe selftest
MSYS_NO_PATHCONV=1 env -i SYSTEMROOT="C:\\Windows" <产物>/checkup-ledger.exe bench
MSYS_NO_PATHCONV=1 env -i SYSTEMROOT="C:\\Windows" <产物>/checkup-ledger.exe no-such-cmd  # 期望 2

# 数据资产
py -3.12 tools/gen_samples.py --check            # 位级一致守门
py -3.12 tools/gen_ingest_fixtures.py --check
py -3.12 tools/verify_ledger.py --verify         # 37 条资产

# 守门自证
py -3.12 tools/mutation_check.py                 # 80 条变异验证（期望 exit 0）
py -3.12 tools/pii_gate.py --selftest            # 双向自证（期望 exit 0）
py -3.12 tools/pii_gate.py --staged              # pre-commit 的真实调用形态

# M6 发布（对外动作执行前向用户确认）
git tag -a v0.1.0 -m "..."        # 先确认
gh repo create yuluo554/10-16-2-checkup-ledger --public
gh run list --limit 20 --json headSha,conclusion,status
gh release view <tag> --json assets,tagName,isDraft
```

**启动下一棒（用户侧命令）**：
```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M6.md" 继续完成任务
```