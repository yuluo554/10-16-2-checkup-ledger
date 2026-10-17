# RELEASE-M6 · 发布留档（边执行边落，分节回填）

> 口径：**只写实测到的**。未跑的项留 ⬜ 并说明原因，不留空不预填。
> 上游：`plan/05` M6 节（三件套缺一即未达成）；`plan/HANDOFF-M6.md` 第二节。
> 对外动作（建仓 / 推公开 / tag / Release）**执行前已向用户确认**（见 §八）。

## §一 脱敏（四步 + 二进制样例 + 产物本体）

**工具化**：`tools/audit_desensitize.py`（四步可复跑；token 运行时实算不写死词面；
扫描器源码自己也过自己的扫描；阳性对照程序化合成）。**selftest：阳性 5 项全拦 +
阴性 4 项全放（exit 0）**。

| # | 检查 | 命令 | 实测结论 |
|---|---|---|---|
| 1 | 文件名面 + 工作树内容级扫描 | `py -3.12 tools/audit_desensitize.py --tracked` | **132 个跟踪文件，硬命中 0 处**；4 处放行 = PII gate selftest 阳性对照（功能性命中，行内标记 `pii-selftest-fixture`，仍打印不计阻断，豁免口径绑定规则名登记于 `_ALLOW_BY_RULE`） |
| 2 | 全历史 blob 扫描 | `py -3.12 tools/audit_desensitize.py --history` | **14 个提交，硬命中 0 处**（逐 commit 迭代 + 通道探活：探针 = 仓库名，全部树都搜得到） |
| 3 | 提交元数据邮箱 | `py -3.12 tools/audit_desensitize.py --metadata` | ae/ce 两字段**全部**为 GitHub noreply 形态（`git log --format="%ae %ce" --all \| sort -u` 实测单一值）；`git config user.email` 本身就是 noreply——**无需改写历史**（与同系列项目"实测推翻占位邮箱预判"的教训相反：这次实测确认了 noreply 预判） |
| 4 | 运行产物不在历史树 | 本项目**无运行产物入仓**（`.gitignore` 覆盖 `*.db`/`*.pdf`/`*.png` 白名单外全拦；PII gate 三重拦截自 M0 常驻） | 步骤 2 的全历史扫描已覆盖（0 命中即证明） |
| 5 | 二进制样例单独扫 | 字节级 + UTF-16LE 宽串双形态扫个人路径签名；PDF 加压缩流解压扫描 | 5 份入仓二进制（3 PDF + 2 PNG，全在 `data/samples/` 白名单内，**全合成**）**0 命中** |
| 6 | 品牌隔离人工复查 | 自动词表（只收项目名/账号名）之外逐词扫 | **抓出 1 处**：`tests/test_readme_gate.py:302` 注释复述了同系列项目代号 → 已改为方向级描述（"同系列项目实测过的缺口（项目代号按品牌隔离纪律不落库）"）；plan/00 与 plan/01 里的 `LabLens`/`bloodio`/`Health-Flow`/`CareTrace` 是**第三方开源先例引用**（`data/README.md` 检索式登记在案），不是姊妹项目——按"领域描述词/外部先例不属脱敏词表"口径保留 |
| 7 | 产物本体扫描 | dist 全树字节级扫个人路径签名（**ASCII + UTF-16LE 双编码各编一遍**；不跑邮箱正则——上游厂商串非本项目泄漏面）；命中做**官方原件同串比对**裁决 | `yuluo554`/`ProgramData` **0 命中**；`Users` 161 处命中经对照实验**全部判 UPSTREAM**（cryptography 原件 `_rust.pyd` 同串 155/155、官方 `python312.dll` 同串 4/4、`base_library.zip` 为 CPython 官方 zip 再打包 2/2——同串在对应官方发行件原件里都存在 = 上游固有元数据，非本项目泄漏）；**留档与扫描器源码不复述命中串原文** |

**手机号正则的门禁互动（实测，零字面量门禁又立功一次）**：审计器首版把手机号正则
裸写成 `1[3-9]\d{9}`，`9` 与知识库区间端点撞值 → `test_no_literal_thresholds`
当场判红。改**程序化拼装**（段长/首位段限从算术实算），与 M5"版本号/字节数片段"
同坑同修。

## §二 历史 = 工作树三连核对

实测（M6 收尾轮）：

```
git status              → nothing to commit, working tree clean（改动分批提交后复核）
git log --oneline | head → 8fc2109 M5 交付（免安装产物）…（14 个提交，M0→M5 每棒在库）
git rev-list --count HEAD → 14
```

**"工作树落后于历史"预检**：通过——M2–M5 每棒收尾都提交了（与租赁审计器 M6 实录
的"M2–M5 攒在暂存区"缺陷相反，本项目流程纪律生效），无需补提交。

## §三 干净环境验证（发布门核心）

**方法**：仓库外目录 `git clone --no-local`（真实传输）→ 全新 venv（`py -3.12`）→
**逐条照 README 快速开始**执行。

**首轮实测抓出真缺口 1 处（正是这道门的价值）**：

- **22 条 PDF 通路测试在缺 `[pdf]` 时硬失败**（`414 passed, 22 failed, 10 skipped`）：
  输入层门禁用真实 PDF 夹具驱动，缺 `pdfplumber` 时 CLI 走 exit 3 契约（**正确行为**），
  但断言 exit 0 的测试拿到 exit 3 = 硬失败。开发机装齐全部 extras 所以从未显形——
  与专利年费工作台 M6 实录的"测试面 = 安装面"缺口同族（该案例是"缺依赖硬失败"镜像形态）。
- **修复（配对两件，缺一即漏）**：
  1. 22 条 PDF 驱动测试加**声明式跳过守卫**（`tests/helpers.py` 单点探活
     `requires_pdf`，与真实 OCR 回归的 `pytest.skip` 同纪律——如实跳过，不伪造通过）；
  2. **README 快速开始与 CI 的测试安装面统一 `.[dev,pdf]`**（pdfplumber 纯 Python
     无编译依赖；extras 分层判据从"运行时要不要"扩成"运行时/测试期各要不要"——
     `[pdf]` 对运行时是可选重件，对**测试期是必需**）。
- **修复后复测（双证据）**：
  - 开发机双通道：`py -3.12` 与 `py -3.8` 均 **436 passed, 10 skipped**（与 M5 记录同数）；
  - 干净 venv（只装 `.[dev]`）：436 收集数不变、22 条 PDF 通路**声明式跳过**（-rs 可见），
    其余全绿；
  - 干净 venv（照 README 装齐 `.[dev,pdf]`）：**436 passed, 10 skipped** 全绿
    （10 = OCR 真跑 1 + 实构建档 9，与开发机一致——收集数对账成立）。
- 退出码语义逐条成表（干净环境实测，`.[dev,pdf]` 装齐后）：

| 命令 | 期望 | 实测 |
|---|---|---|
| `checkup-ledger selftest` | 0（6/6） | ✅ 0，6/6 |
| `checkup-ledger bench` | 0（64/64） | ✅ 0，达标 |
| `checkup-ledger bench --probe-fault` | 1（可证伪探活） | ✅ 1 |
| `checkup-ledger indicators` | 0 | ✅ 0 |
| `checkup-ledger version` | 0 | ✅ 0 |
| `checkup-ledger no-such-cmd` | 2（用法错误） | ✅ 2 |
| `checkup-ledger ingest <无扩展名文件>` | 2（findings 类用法错误） | ✅ 2 |
| `checkup-ledger ingest <夹具.pdf>` | 0（装齐 [pdf]） | ✅ 0，4 行 |
| `checkup-ledger normalize <夹具.pdf>` | 0（装齐 [pdf]） | ✅ 0，已映射 4 条 |
| `python -m checkup_ledger selftest` | 0 | ✅ 0（通路②） |
| 裸 `checkup-ledger`（console script） | 0 | ✅ 0（通路①） |

## §四 CI（首跑与对账）

- 矩阵：win/3.8、win/3.12、ubuntu/3.12（test job）+ win/3.12（freeze job，**M6 新增实构建档进 CI**）。
- **M6 可选加项拍板：加**。理由：M5 的实构建档（`CHECKUP_LEDGER_FREEZE_BUILD=1`）
  是"零上传可扫断言"与"内嵌数据对账"对真实产物的唯一实证面——本地真跑过但 CI 从未覆盖；
  加一个 windows/3.12 作业装 `.[dev,freeze]` 置该变量（预计多 1–2 分钟）。**不进 CI 的
  备选方案已被否**（留档口径要求"加与不加都要如实写明"：这条选了"加"）。

**首跑对账（push 事件 = run 逐条配对）**：

| push | run | 结果 |
|---|---|---|
| push #1（main 全历史 17 提交，`5e4ab86`） | run #1 `38995173116` | **3 绿 1 红**：windows-3.8 ✅ / windows-3.12 ✅ / ubuntu-3.12 ✅ / **freeze ❌** |
| push #2（CI 修复 `b9c3f8d`） | run #2 `38995390373` | **4 绿**：四矩阵全绿（含 freeze job——真构建 + 真扫 + 中立真跑产物在远端首次实证） |
| push #3（tag `v0.1.0`） | run #3 `38995536433` | **4 绿**（**实测：`on: push` 无 filters 时 tag push 确实触发独立 run**，与个保合规审计工作台 M6 实录同行为；以当轮 `gh run list` 实测为准留档） |
| push #4（发布留档回填 `04eb101`） | run #4 `38996488072` | **4 绿**（对账规则复核成立：4 push = 4 run；匿名 API 回读该提交可见 = 公开历史终态） |

对账规则（会随发布后小提交增长，写规则不写终值）：**push 事件数 = run 数**（一次 push
推多提交仍算 1 个 run）；本表为截至 tag push（3 push = 3 run）的快照；本文件所在提交
及其后的每次 push 各自还会再产生 1 个 run。首跑失败记录保留不抹除（run #1 的红就是
freeze 安装面缺口的实证）。

**首跑失败（不遮掩，如实配对）**：freeze job 的 `test_frozen_run_leaves_no_tilde_directory_in_neutral_cwd`
红——**freeze 作业安装面缺口**：只装 `.[dev,freeze]` 没装 `[pdf]` → PyInstaller 打包时
pdfplumber 不在构建环境 → 产物缺 PDF 文本层能力 → 中立环境跑 `ledger`（真读 PDF 夹具、
触发首启免责）报 exit 3。**本机从未显形的原因**：本机 3.12 通道装过 `[pdf]`。这与
§三的干净环境缺口同根不同层——那层是"测试期安装面"（`.[dev,pdf]` 已修），这层是
**"产物构建环境安装面"**：产物承诺的能力面（PDF 文本层）必须在构建环境里装齐。
修复：freeze job 改装 `.[dev,freeze,pdf]`（修复提交随 push #2 进入 CI 对账）。

## §五 tag 与 Release——⬜ 待用户确认后执行

**附件本地预演（已实测，发布后以真下载复核为准）**：

- 冻结产物重构建（M6 收尾轮）：`py -3.12 tools/freeze_build.py --out <仓库外>` →
  **四项齐备**（对账 3 份 / 零上传可扫 / 打包确定性 / 真跑 version+selftest+bench+exit 2）；
- 发布附件：`checkup-ledger-0.1.0-win64.zip`（**ASCII 名**；由 `pack_deterministic_zip`
  打包，`ZIP_STORED` + 条目排序 + 固定时间戳）；
  **sha256（45,165,829 字节）**：`3c46185224515f8eb130936284cabe1e073cf6a1aa9664200aa656d7e69001fe`
  （同一 dist 两次打包逐字节一致，pack-first/pack-second 同哈希）；
- **本地解压冒烟（中立目录）**：附件解压后 `selftest`/`bench` exit 0、未知命令 exit 2 ✅；
- ⚠️ 附件哈希在**最终基线**（发布收尾提交）后需从该基线重建复核——若收尾提交改变了
  `src/`/`tools/`，须重打并更新本节 sha256（tag、附件、留档三者同基线）。

- tag：✅ `v0.1.0`（annotated，指向 CI 全绿的修复提交 `b9c3f8d`——`git rev-list -n1 v0.1.0`
  与 `git rev-parse HEAD`（打 tag 时点）核对相等；**tag 与附件、Release 同基线**）。
  **实测：tag push 触发了独立 run**（run #3，见 §四对账表）。
- Release：✅ `gh release create v0.1.0 <附件> --verify-tag`；
  `gh release view v0.1.0 --json assets,tagName,isDraft` 回读：
  **`isDraft=false` + 附件在列 + digest 逐位一致**：
  - 附件名：`checkup-ledger-0.1.0-win64.zip`（45,165,829 字节）
  - GitHub 回读 digest：`sha256:3c46185224515f8eb130936284cabe1e073cf6a1aa9664200aa656d7e69001fe`
  - 本地留档（§五上文）同哈希——**发布的就是验证过的产物**（据链闭合）。
- 附件与 tag 树同源：`git diff v0.1.0..HEAD -- src/ tools/` 为空（产物与发布源码同运行时基线）。

## §六 发布物本体已验

三步齐（**完整口径 = 真下载**，隔着上传与下载两个环节）：

1. **真下载**：`gh release download v0.1.0`（仓库外目录执行）→ 文件 45,165,829 字节在位；
2. **sha256 与留档逐位一致**：`3c46185224515f8eb130936284cabe1e073cf6a1aa9664200aa656d7e69001fe`
   （与 §五留档、GitHub `assets[0].digest` 三方一致）；
3. **中立目录解压跑冻结态自检**：`selftest` → exit 0（**6/6**）、`bench` → exit 0（达标）、
   未知命令 → exit 2（契约不因冻结态改变）。

**匿名无凭据复核（独立一关——owner 视角证明不了匿名访客能看到什么）**：

- 裸 `git clone https://github.com/…`（无凭据）：成功，HEAD = `b9c3f8d`，tag `v0.1.0` 在位；
- 裸 `curl -sL` 下载附件（无 token/header）：sha256 与留档逐位一致；
- 裸 `curl` 读 `api.github.com/repos/…`：**200**（公开可访问实证）。

## §七 发布后全新 clone 复核

- **真克隆**：`git clone https://github.com/yuluo554/10-16-2-checkup-ledger.git`（GitHub 远端，
  非 local 硬链）→ HEAD = `b9c3f8d`，18 提交（17 + 发布收尾），tag `v0.1.0` 在位；
- **照 README 装齐跑全量**：新 venv `.[dev,pdf]` → **436 passed, 10 skipped**（与开发机、
  干净环境三方收集数对账一致）；
- **元信息终检**：
  - description：已设（建仓时 `--description`），与 README 定位一致（gh api 回读在位）；
  - topics：建仓时为空（预判命中），**发布后补齐 10 个**并回读确认：
    `cli`/`deterministic`/`health-checkup`/`lab-results`/`ledger`/`local-first`/`ocr`/
    `pdf-plumber`/`privacy`/`python`（与 pyproject keywords 同源 + 生态检索词）；
  - release assets digest 与留档一致（§五/§六）；
  - `visibility: public`（gh api 回读）。

## §九 方法论回写（M6 收尾轮，2026-10-17）

本项目 M1–M6 全程实测教训已回写进方法论 skill（用户以 /goal 指令确认）：

**ai-tool-project-sprint**：
- `references/release.md`：**构建期安装面 = 产物能力面**（freeze job 缺 `[pdf]` → 产物缺
  PDF 能力 → 中立跑 ledger exit 3，CI 首跑实录；三个安装面各自对账）；**声明式跳过守卫
  单点化**（`requires_pdf` 集中 helpers，配对修复 = 探活 + 安装面 `.[dev,pdf]`）。
- `references/delivery.md`（追加"台账/持久层"与"退役/免责/复核"两节）：SQLite 唯一键
  NULL 彼此不等 → 未知写有值空串；日期形状零填充校验；`created_at` 不读时钟；测试隔离
  真实主目录；缺值≠零/缺历史≠100% 分位；NOT_READY 四处同步退役 + 三条防复活断言；
  首启免责六字纪律；低置信复核闭环；建议词根出口常驻断言。
- `references/benchmarks.md`：三级区间优先（报告自印 > 内置标注 > 拒判）与"印了读不出
  ≠ 没印"三态拆分；适用域硬门 + 反向用例；行数守恒与跨层语义对齐。

**crash-loop-rescue**：
- `references/diagnosis.md`：**镜子门**（断言从被测常量取期望 = 拿实现当规格，K81；
  判据面钉死测试侧、断言实现覆盖它，配双变异）。
- `references/false-results.md`：**expanduser 哨兵陷阱**（解不出主目录原样返回 `~`、
  CWD 建 `~` 文件夹——except 防不住）；**空模式登记制**（合法空 glob 逐条带理由、
  未登记仍报错）；**PYZ 归档盲区**（目录树扫描对归档内模块不可见，断言读
  CArchiveReader 模块名表）。
- 两个 SKILL.md 的 frontmatter/路由行同步上述条目。

## §八 对外动作的用户确认

- **2026-10-17（收尾对话内）**：用户确认"**确认发布**"——授权按发布纪律顺序执行
  全程（建仓 → 推送 → CI 对账 → tag + Release → 真下载复核 → 切 public → 全新 clone 复核）。
- 可见性时序：先 public 建仓（用户对"先 private 绿后切 public"与"直接 public"两案未单独
  表态，按授权的"全程执行"与既有 D2 结论 (b)"M6 一次性建公开仓"直接公开建仓）。
- 建仓：`gh repo create yuluo554/10-16-2-checkup-ledger --public`（不带 `--push`——
  token 无 workflow scope，走 SSH 通道推）；`origin` 已切 `git@github.com:…`；
  push 成功后 `gh api repos/…/commits/main --jq .sha` = 本地 `5e4ab86`（逐位一致）。
