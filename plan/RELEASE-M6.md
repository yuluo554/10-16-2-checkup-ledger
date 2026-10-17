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

## §四 CI（首跑与对账）——⬜ 待建仓后回填

- 矩阵：win/3.8、win/3.12、ubuntu/3.12（test job）+ win/3.12（freeze job，**M6 新增实构建档进 CI**）。
- **M6 可选加项拍板：加**。理由：M5 的实构建档（`CHECKUP_LEDGER_FREEZE_BUILD=1`）
  是"零上传可扫断言"与"内嵌数据对账"对真实产物的唯一实证面——本地真跑过但 CI 从未覆盖；
  加一个 windows/3.12 作业装 `.[dev,freeze]` 置该变量（预计多 1–2 分钟）。**不进 CI 的
  备选方案已被否**（留档口径要求"加与不加都要如实写明"：这条选了"加"）。
- 首跑对账（push 事件 = run 逐条配对）：⬜ 待回填
- 首跑失败（如有）与修复提交配对：⬜ 待回填

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

- tag：⬜（拟 `v0.1.0`，annotated，指向含本留档完整内容的提交——**用
  `git rev-list -n1 v0.1.0` 与 `git rev-parse HEAD` 核对相等**，不写死哈希）
- Release 附件上传与 `gh release view <tag> --json assets,tagName,isDraft`（draft=false +
  附件名在列）：⬜ 待回填

## §六 发布物本体已验——⬜ 待回填

**本地预演已做**（附件 = 本机构建 + 确定性打包；解压冒烟 3/3 过，见 §五）。
但"发布物本体已验"的完整口径是**真下载**（隔着一次上传与一次下载）：
真下载 Release 附件 → sha256 与留档一致 → 中立目录解压跑冻结态自检：
（三步证据各一行，⬜ 待发布后回填）

## §七 发布后全新 clone 复核——⬜ 待回填

GitHub 真克隆 → 全量测试 → 元信息终检（topics/description/assets digest 与 README 定位一致）：
⬜ 待回填

## §八 对外动作的用户确认

⬜ 待确认后回填（确认方式与时间）。
