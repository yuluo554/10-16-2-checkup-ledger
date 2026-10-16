"""PII gate：真实体检报告与台账数据库永不入 git。

三重拦截面（缺一层就漏一类）：
1. **路径面**：文件落在禁用路径（真实报告目录）→ 拦；
2. **类型面**：敏感扩展名（pdf/图片/db）**不在样例白名单** → 拦；
3. **内容面**：文本里出现真实机构名模式 / 手机号 / 身份证号 → 拦。

**白名单是判定词表，不是参数**：新增白名单条目须同步登记 data/README.md 附录
（假姓名/假机构名白名单）。绕过词表 = 造假。

用法：
    python tools/pii_gate.py --staged          # 检查暂存区（供 pre-commit 调用）
    python tools/pii_gate.py --paths a b c     # 检查指定路径
    python tools/pii_gate.py --selftest        # 自证：阳性样本必被拦 + 阴性对照必放行

退出码：0 通过 / 1 检出敏感内容（阻止提交）。
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
_EXIT_OK = 0
_EXIT_BLOCKED = 1

# ---- 面 1：禁用路径（真实报告可能落地的目录）----
FORBIDDEN_PATH_SEGMENTS = (
    "real_reports/",
    "_reports/",
    "private/",
    "_private/",
)

# ---- 面 2：敏感扩展名 → 仅样例白名单内放行 ----
SENSITIVE_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".db", ".sqlite", ".sqlite3", ".bmp", ".tif", ".tiff")
SAMPLE_WHITELIST_PREFIXES = ("data/samples/",)

# ---- 面 3：内容特征 ----
# 身份证号（18 位，末位可为 X）与手机号（中国大陆 1[3-9] 开头 11 位）
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# 真实机构名后缀。合成数据一律用"示例体检中心A/示例医院C"这类白名单名，
# 故"体检中心/医院/门诊部/检验所"前**不接"示例"**的写法即命中。
# 注意：正则的 `{2,8}` 贪心会在 "示例体检中心A" 上截出 "示例体检中心"（A 不是汉字），
# 所以判定必须做**双向前缀**比对，而不是单向 startswith——否则会误拦自己的示例名。
_INSTITUTION_RE = re.compile(
    r"(?<!示例)(?:[\u4e00-\u9fa5]{2,8}(?:体检中心|体检医院|人民医院|中心医院|附属医院|门诊部|检验所))"
)

# 假机构名白名单（与 data/README.md 附录同源；扩表是正常维护动作）
INSTITUTION_WHITELIST = ("示例体检中心A", "示例体检中心B", "示例医院C")

# 假姓名白名单（同上）。姓名无法用正则与真实姓名区分，故不做启发式识别——
# 它只作为"合成数据的唯一允许名字集"登记在案，由 M1 生成器与用例纪律约束。
NAME_WHITELIST = ("张三", "李四", "王五", "赵六")

_TEXT_EXTENSIONS = (
    ".md", ".txt", ".py", ".yaml", ".yml", ".json", ".csv", ".toml", ".ini",
    ".cfg", ".rst", ".html", ".htm", ".js", ".ts", ".sh", ".bat", ".ps1", "",
)

# 本门自身的源码与自证样本会**故意**包含被拦形态（阳性对照），须显式豁免——
# 豁免口径写死，不靠"文件里出现过这串字"判断。
_SELF_EXEMPT_FILES = ("tools/pii_gate.py", "tests/test_pii_gate.py", "tests/fixtures/pii_probe.txt")


class Finding:
    __slots__ = ("path", "layer", "detail")

    def __init__(self, path, layer, detail):
        self.path = path
        self.layer = layer
        self.detail = detail

    def __repr__(self):
        return "Finding(%s, %s, %s)" % (self.path, self.layer, self.detail)


def _display(path: str, root: str = None) -> str:
    """展示与判定路径一律 POSIX 相对形式（相对 `root`，默认仓库根）。

    三处坑：
    - 跨盘符（C:→D:）时 `os.path.relpath` 抛 ValueError → 回落绝对路径；
    - Windows 上 relpath 结果带反斜杠，而判据（禁用目录段 / 白名单前缀）按 `/` 写
      —— 不归一就会"路径明明在禁目录里却匹配不到"（假放行）；
    - 路径在 root 之外时（测试临时目录）必须回落绝对路径并同样归一，
      否则白名单前缀匹配失效。
    """
    base = root or REPO_ROOT
    rel = path
    try:
        candidate = os.path.relpath(path, base)
        if not candidate.startswith(".."):
            rel = candidate
    except ValueError:
        rel = path
    return rel.replace(os.sep, "/")


def _is_exempt(rel_path: str) -> bool:
    return rel_path in _SELF_EXEMPT_FILES


def check_path(rel_path: str) -> list:
    """面 1：禁用路径。"""
    findings = []
    normalized = "/" + rel_path.lstrip("/")
    for segment in FORBIDDEN_PATH_SEGMENTS:
        if ("/" + segment) in normalized:
            findings.append(
                Finding(rel_path, "path", "落在禁用路径 %s（真实报告目录永不入库）" % segment)
            )
    return findings


def check_extension(rel_path: str) -> list:
    """面 2：敏感扩展名必须落在样例白名单内。"""
    lowered = rel_path.lower()
    if not lowered.endswith(SENSITIVE_EXTENSIONS):
        return []
    if lowered.startswith(SAMPLE_WHITELIST_PREFIXES):
        return []
    return [
        Finding(
            rel_path,
            "type",
            "敏感文件类型未在样例白名单内（白名单前缀：%s；真实报告与台账永不入库）"
            % ", ".join(SAMPLE_WHITELIST_PREFIXES),
        )
    ]


def _is_whitelisted_institution(value: str) -> bool:
    """白名单机构名判定：双向前缀比对。

    正则 `{2,8}` 贪心会在 "示例体检中心A" 上截出 "示例体检中心"（A 不是汉字），
    故单向 `value.startswith(allowed)` 判不出白名单——必须也允许
    `allowed.startswith(value)`（截断形态）。
    """
    for allowed in INSTITUTION_WHITELIST:
        if value.startswith(allowed) or allowed.startswith(value):
            return True
    return False


def check_content(rel_path: str, text: str) -> list:
    """面 3：内容特征。"""
    if _is_exempt(rel_path):
        return []
    findings = []
    if _ID_CARD_RE.search(text):
        findings.append(Finding(rel_path, "content", "出现身份证号形态（18 位）"))
    if _PHONE_RE.search(text):
        findings.append(Finding(rel_path, "content", "出现手机号形态（11 位）"))
    for match in _INSTITUTION_RE.finditer(text):
        value = match.group(0)
        if _is_whitelisted_institution(value):
            continue
        findings.append(
            Finding(rel_path, "content", "出现疑似真实机构名：%s（合成数据请用示例名白名单）" % value)
        )
    return findings


def check_file(abs_path: str, root: str = None) -> list:
    """检查单个文件。`root` 为判定基准（默认仓库根；测试传临时目录以复用白名单语义）。"""
    rel = _display(abs_path, root)
    findings = check_path(rel) + check_extension(rel)
    if rel.lower().endswith(_TEXT_EXTENSIONS) and os.path.isfile(abs_path):
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as handle:
                findings.extend(check_content(rel, handle.read()))
        except OSError:
            pass
    return findings


def staged_paths() -> list:
    """暂存区文件（相对仓库根的 POSIX 路径）。

    子进程显式传 encoding —— `text=True` 走 locale，中文文件名在 cp1252 下会
    UnicodeDecodeError（无环境变量可替代）。
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        sys.stderr.write("[PII gate] git diff 失败：%s\n" % result.stderr.decode("utf-8", "replace"))
        return []
    raw = result.stdout.decode("utf-8", "replace")
    return [item for item in raw.split("\0") if item.strip()]


def run(paths) -> int:
    findings = []
    for rel in paths:
        findings.extend(check_file(os.path.join(REPO_ROOT, rel)))

    if findings:
        sys.stderr.write("[PII gate] 检出 %d 处敏感内容，提交被阻止：\n" % len(findings))
        for item in findings:
            sys.stderr.write("  · [%s] %s：%s\n" % (item.layer, item.path, item.detail))
        sys.stderr.write(
            "处置：真实数据一律移除；示例数据请使用 data/README.md 附录的假姓名/假机构名白名单。\n"
        )
        return _EXIT_BLOCKED

    print("[PII gate] 通过：%d 个文件无敏感内容。" % len(paths))
    return _EXIT_OK


# ---- 自证：门必须双向验（只测一边 = 没测）----
_POSITIVE_SAMPLES = (
    # (说明, 相对路径, 内容, 期望命中的层)
    ("真实报告 PDF 不在白名单", "real_reports/2024-report.pdf".replace("real_reports", "private"), "", "path"),
    ("样例外的 pdf 文件", "docs/report.pdf", "", "type"),
    ("样例外的台账数据库", "output/ledger.db", "", "type"),
    ("身份证号", "notes/sample.txt", "身份证 110101199003072316 记录", "content"),
    ("手机号", "notes/sample.txt", "联系电话 13800138000", "content"),
    ("真实机构名", "notes/sample.txt", "就诊于北京协和体检中心", "content"),
)

_NEGATIVE_SAMPLES = (
    ("白名单内的合成样例 pdf", "data/samples/cases/case-001.txt", "张三 示例体检中心A 2024-03-11", None),
    ("白名单内的合成样例图片", "data/samples/cases/scan-001.png", "", None),
    ("普通源码文件", "src/checkup_ledger/model.py", "FLAG_HIGH = 'high'", None),
    ("白名单机构名", "data/samples/cases/case-002.txt", "李四 示例医院C", None),
)


def _materialize(root, rel_path, content):
    target = os.path.join(root, rel_path)
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return target


def selftest() -> int:
    """在临时目录里跑阳性样本与阴性对照（判定基准 = 该临时目录）。"""
    import tempfile

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for label, rel, content, expected_layer in _POSITIVE_SAMPLES:
            target = _materialize(tmp, rel, content)
            gotten = check_file(target, root=tmp)
            layers = {f.layer for f in gotten}
            if expected_layer not in layers:
                failures.append("阳性样本未被拦：%s（期望层 %s，实得 %s）" % (label, expected_layer, layers or "无"))
        for label, rel, content, _expected in _NEGATIVE_SAMPLES:
            target = _materialize(tmp, rel, content)
            gotten = check_file(target, root=tmp)
            if gotten:
                failures.append("阴性对照被误拦：%s → %s" % (label, gotten))

    if failures:
        for item in failures:
            sys.stderr.write("[PII gate selftest] %s\n" % item)
        print("[PII gate selftest] 失败：%d 项" % len(failures))
        return _EXIT_BLOCKED

    total = len(_POSITIVE_SAMPLES) + len(_NEGATIVE_SAMPLES)
    print(
        "[PII gate selftest] 通过：阳性样本 %d 项全部被拦，阴性对照 %d 项全部放行（共 %d 项）"
        % (len(_POSITIVE_SAMPLES), len(_NEGATIVE_SAMPLES), total)
    )
    return _EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PII gate：真实报告与台账永不入 git")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="检查暂存区（供 pre-commit 调用）")
    mode.add_argument("--paths", nargs="+", metavar="PATH", help="检查指定路径（相对仓库根）")
    mode.add_argument("--selftest", action="store_true", help="自证：阳性必拦 + 阴性必放行")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.staged:
        paths = staged_paths()
        if not paths:
            print("[PII gate] 暂存区为空，跳过。")
            return _EXIT_OK
        return run(paths)
    return run(args.paths)


if __name__ == "__main__":
    sys.exit(main())
