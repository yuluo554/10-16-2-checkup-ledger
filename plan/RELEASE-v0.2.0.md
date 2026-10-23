# RELEASE-v0.2.0 — 发布面回填：复核锚 + 基准口径显式化 + `requires-python` 抬到 3.12

> 上一版：`v0.1.0`（2026-10-17）。
> 触发来源：轨 I（发布物一致性）I-1 —— `v0.1.0` 之后 `src/` 有 **4 个文件 / +149 行**的改动
> （复核锚机读化、`bench` 口径显式化、加载器校验），这些改动**从未随任何 tag 发布过**。

## 一、相对 v0.1.0 改了什么

| 类别 | 内容 | 用户能否感知 |
|---|---|---|
`src/checkup_ledger/data/indicators.yaml` | 新增根级 **机读复核锚**：`review_interval: annual` / `next_review: "2027-10-16"` | **能**：`selftest` 会打印它 |
`src/checkup_ledger/loader.py` | `IndicatorDict` 增 `next_review` / `review_interval` 字段与 `review_overdue()`；新增 `_parse_review_anchor()`（**给了就必须合规**：`YYYY-MM-DD` 零填充，形状不对直接 `KnowledgeError`） | **能（严格化）**：坏锚点会被拦，不再"看着有复核纪律、实际读不出来" |
`src/checkup_ledger/cli.py` | `_check_knowledge()` 输出复核锚状态（**逾期只提示、不改退出码**）；新增 `_today_iso()`（`CHECKUP_LEDGER_TODAY` 可注入，便于复现） | **能**：`selftest` 多一行 |
`src/checkup_ledger/benchmark/layered.py` | 新增 `not_enabled_suites` / `scope_note`（含原因码 `samples_absent` / `only_filter`）+ `_disabled_suites()` / `_scope_note()` | **能**：「只跑了一层」与「两层都跑了」现在**在输出里能区分**（退出码仍同为 0） |
`requires-python` | `>=3.8` → **`>=3.12`** | **能（破坏性）**：3.8–3.11 装不上 |
`build-system` | `setuptools>=61` → **`>=77`**（PEP 639） | 构建期 |
`data/`（仓根） | `README.md` +7 行说明、`ledger/assets.csv` 台账一行更新 | 不影响运行时 |

**没有改**：指标判定逻辑（H/L 比较）、参考区间数值（19 项逐条未动且仍全为 `pending`）、
退出码语义（0/1/2/3，`4` 仍整项退役）、报告格式、CLI 子命令与旗标。

## 二、为什么版本号是 0.2.0

`requires-python` 由 3.8 抬到 3.12 是**不兼容变更** → 0.x 阶段走 minor。
另外 `bench` 的输出结构新增两个键（`scope_note` / `not_enabled_suites`）——
按「JSON 消费方可能按固定 schema 解析」的口径，这也算行为变更。

## 三、验证

| 项 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `.venv/Scripts/python.exe -m pytest -q` | **447 passed, 10 skipped** |
| 冻结构建 | `.venv/Scripts/python.exe tools/freeze_build.py --out <仓库外目录>` | rc=0，四段全过 |
| 内嵌数据对账 | （构建自带） | 3 份，逐份 sha256 与仓库冻结件一致，**无多拷** |
| 零上传可扫断言 | （构建自带） | 模块表无 TLS/出站组件；`socket`/`selectors` 为已登记残留（pdfminer 经 `importlib.metadata` → `email.utils` 链路，排除会让 `import pdfplumber` 失败） |
| 打包确定性 | （构建自带 + 发布期重打） | 两次打包同 sha256 `54865d49…de9b` |
| 冻结态真跑（中立目录 + `env -i` 等价） | （构建自带） | `version`→0 / `selftest`→0（6/6）/ `bench`→0 / `no-such-command`→2 |

冻结态 `selftest` 实测输出包含**本轮新增**的那一行，证明改动真的进了 exe：

```
[OK] knowledge — 知识库：19 项可生效（其中 verified 可作默认值 0 项）、0 项未启用；复核锚 2027-10-16（未逾期，annual）
自检结论：6/6 通过
```

## 四、附件与三方对撞

见 `plan/DIST-sha256-v0.2.0.txt`。

- 附件：`checkup-ledger-0.2.0-win64.zip` — **46,445,940 B**
- sha256 `54865d49b60a35db4f2cede988cad930fcfa2b5e85f56913679140aaaaecde9b`
- 一致面：构建期自测 / 发布期重打 / GitHub asset digest / Release 正文

## 五、历史结论是否需重跑

**不需要。** 指标判定逻辑与参考区间**逐字节未改**（19 项仍全部 `pending`，行为与 v0.1.0 完全一致）。
新增的是**元数据与提示**，不参与判定，也不改退出码。

唯一需要留意：如果你解析 `bench --json` 的输出并未做「多余键」容错，
新增的 `scope_note` / `not_enabled_suites` 会让严格 schema 校验失败 —— 这是**新增键**，不是删改。
