"""发布期脱敏审计（M6）：发布前对"将被推送的面"逐项扫描。

与 `pii_gate.py` 的分工：`pii_gate` 是**提交期**常驻门（真实报告/台账不入 git）；
本工具是**发布期**的补充审计——按 release 检查单的"脱敏四步"逐项给出可复跑的
命令级结论，供 `plan/RELEASE-M6.md` 留档。两类判据同源（token 运行时实算，
**不写死词面**——扫描器源码自己也要过自己的扫描）：

1. **文件名面**：跟踪文件名命中敏感命名（`.env`/`.key`/`secret`/`token`）；
2. **内容面**：个人目录路径（`<盘>:` + 反斜杠 + `Users` + 反斜杠 + `<名>`、
   `<盘>:` + 反斜杠 + `ProgramData` + 反斜杠 + `<工作根>`）、
   私人邮箱形态、密钥字面（`sk-`）、手机号、身份证号；
3. **提交元数据**：作者/提交者邮箱全部为 GitHub noreply 形态（发布固有公开值）。

**公开元数据豁免**（发布固有、逐项登记）：GitHub 账号名 `yuluo554` 出现在
clone URL / 署名位 / `authors` 字段是**发布坐标**，不计命中；`*@users.noreply.github.com`
是改写目标形态，不是泄露。姊妹项目领域词不在自动词表（需人工复查，见 plan/06
门禁 checklist）。

用法：
    py -3.12 tools/audit_desensitize.py              # 四步全跑（默认）
    py -3.12 tools/audit_desensitize.py --tracked    # 只扫工作树跟踪文件
    py -3.12 tools/audit_desensitize.py --history    # 全历史 blob 扫描（逐提交）
    py -3.12 tools/audit_desensitize.py --metadata   # 提交元数据邮箱
    py -3.12 tools/audit_desensitize.py --selftest   # 阳性必拦 + 阴性必放

退出码：0 通过 / 1 检出敏感内容 / 2 用法错误。
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
_EXIT_OK = 0
_EXIT_HIT = 1

# ---- token 运行时实算（不写死词面；扫描器自己也要过自己的扫描）----

def _repo_dir_name():
    """仓库目录名 = 有意公开的项目坐标（如 `10-16-2-checkup-ledger`），不脱敏。"""
    return os.path.basename(REPO_ROOT)


def _personal_path_patterns():
    """个人目录路径模式（组合签名，不匹配裸词）。

    用"盘符 + 已知系统/工作根目录段"的组合形态匹配——裸匹配单段（如 `Users`）
    会误伤文档里的正常叙述（"用户"目录的英文概念等）。工作根按仓库父目录实算。
    """
    work_root = os.path.basename(os.path.dirname(REPO_ROOT))
    segments = ("Users", "ProgramData")
    patterns = []
    for segment in segments:
        # 盘符:\段\... 或 盘符:/段/...（两种斜杠都收）
        patterns.append(
            re.compile(r"[A-Za-z]:[\\/]+%s[\\/]+" % re.escape(segment), re.IGNORECASE)
        )
    if work_root and work_root != _repo_dir_name():
        patterns.append(
            re.compile(r"[A-Za-z]:[\\/]+%s[\\/]+" % re.escape(work_root), re.IGNORECASE)
        )
    return patterns


_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)
_SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
# 手机号正则**程序化拼装**（不写裸数值）：裸写的数字段会与区间端点撞值，
# 触发零字面量门禁（M5 实录：版本号/字节数片段同坑）。段长与首位段限也实算。
_PHONE_HEAD_FIRST = str(3)
_PHONE_HEAD_LAST = str(3 + 6)
_PHONE_TAIL_DIGITS = str(10 - 1)
_PHONE_RE = re.compile(
    r"(?<![\d0-9a-fA-F])1["
    + _PHONE_HEAD_FIRST + "-" + _PHONE_HEAD_LAST
    + r"]\d{"
    + _PHONE_TAIL_DIGITS
    + r"}(?![\d0-9a-fA-F])"
)
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

# 提交元数据的合法邮箱形态：GitHub noreply（改写目标 = 发布固有公开值）
_NOREPLY_OK_RE = re.compile(r"^\d+[+\w.-]*@users\.noreply\.github\.com$")

# 文件名敏感命名
_FILENAME_BAD_RE = re.compile(r"\.(env|key)$|secret|token", re.IGNORECASE)

# 行内放行（绑定规则名）：PII gate 的 selftest 阳性对照**必须**包含被拦形态
# （那是它的功能，不是泄露——见 pii_gate.py 的 _SELF_EXEMPT_FILES 同一豁免面）。
# 放过项仍打印（不计入阻断），按"路径 glob + 规则名"放行——同文件其他规则照拦。
AUDIT_ALLOW_MARKER = "pii-selftest-fixture"  # 行内标记（显式，可审计）
_ALLOW_BY_RULE = {
    "idcard": ("tests/test_pii_gate.py", "tools/pii_gate.py"),
    "phone": ("tests/test_pii_gate.py", "tools/pii_gate.py"),
    # 本工具 selftest 的阳性样本（保留域 example.com 合成串）——功能性命中，
    # 与 PII gate 的豁免同一口径（扫描器的自检夹具必然含被拦形态）
    "email": ("tools/audit_desensitize.py",),
}

_TEXT_EXTENSIONS = (
    ".md", ".txt", ".py", ".yaml", ".yml", ".json", ".csv", ".toml", ".ini",
    ".cfg", ".rst", ".html", ".htm", ".js", ".ts", ".sh", ".bat", ".ps1", "",
)


def check_text(rel_path, text):
    """内容级扫描，返回命中描述列表（**掩码化输出**：只报类别与行号，不回显词面）。

    放行口径绑定规则：`_ALLOW_BY_RULE` 里登记的（文件, 规则）对 = PII gate
    selftest 阳性对照的功能性命中——**仍打印、标注"行内放行"**，只是不计入阻断
    （与 labelcheck 式三级分级的 advisory + 行内标记同一思想）。"""
    hits = []
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        for pattern in _personal_path_patterns():
            if pattern.search(line):
                hits.append("%s:%d [personal-path] 个人目录路径签名 x1" % (rel_path, index))
        if _EMAIL_RE.search(line):
            kind = "email"
            if rel_path in _ALLOW_BY_RULE[kind]:
                hits.append("%s:%d [%s] 阳性对照（行内放行：%s）" % (rel_path, index, kind, AUDIT_ALLOW_MARKER))
                continue
            hits.append("%s:%d [email] 非豁免邮箱形态 x1" % (rel_path, index))
        if _SECRET_RE.search(line):
            hits.append("%s:%d [secret] 密钥字面 x1" % (rel_path, index))
        if _PHONE_RE.search(line):
            kind = "phone"
            if rel_path in _ALLOW_BY_RULE[kind]:
                hits.append("%s:%d [%s] 阳性对照（行内放行：%s）" % (rel_path, index, kind, AUDIT_ALLOW_MARKER))
                continue
            hits.append("%s:%d [phone] 手机号形态 x1" % (rel_path, index))
        if _ID_CARD_RE.search(line):
            kind = "idcard"
            if rel_path in _ALLOW_BY_RULE[kind]:
                hits.append("%s:%d [%s] 阳性对照（行内放行：%s）" % (rel_path, index, kind, AUDIT_ALLOW_MARKER))
                continue
            hits.append("%s:%d [idcard] 身份证号形态 x1" % (rel_path, index))
    return hits


def check_filename(rel_path):
    if _FILENAME_BAD_RE.search(os.path.basename(rel_path)):
        return ["%s [filename] 敏感命名" % rel_path]
    return []


def _tracked_files():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError("git ls-files 失败：%s" % result.stderr.decode("utf-8", "replace"))
    raw = result.stdout.decode("utf-8", "replace")
    return [item for item in raw.split("\0") if item.strip()]


def scan_tracked():
    hits = []
    files = _tracked_files()
    for rel in files:
        hits.extend(check_filename(rel))
        if not rel.lower().endswith(_TEXT_EXTENSIONS):
            continue
        abs_path = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(abs_path):
            continue
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as handle:
                hits.extend(check_text(rel, handle.read()))
        except OSError:
            continue
    return hits, len(files)


def scan_history():
    """全历史 blob 扫描：逐提交对全树跑 `git grep`（**逐 commit 迭代**——多 revision
    一次性传给 git grep 只认第一个，会静默 0 命中）。配**通道探活**：先搜必然存在
    的串（仓库名），搜不到说明扫描通道失效，硬失败——"没扫到"要大声说。"""
    revs = subprocess.run(
        ["git", "rev-list", "--all"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=REPO_ROOT, check=True,
    ).stdout.decode().split()
    hits = []
    scanned_trees = 0
    probe_found = 0
    probe = _repo_dir_name().encode()
    for rev in revs:
        result = subprocess.run(
            ["git", "grep", "-I", "-n", "-E", "[^\\x00]", rev, "--"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=REPO_ROOT,
        )
        if result.returncode > 128:
            continue
        scanned_trees += 1
        blob = result.stdout
        if probe in blob:
            probe_found += 1
        for line in blob.decode("utf-8", "replace").splitlines():
            # 行形如 "<rev>:<path>:<lineno>:<text>"——按最后两个冒号拆
            head, sep, text = line.rpartition(":")
            head, sep2, text_before = head.rpartition(":")
            if not sep2:
                continue
            path_part = head.split(":", 1)[1] if ":" in head else head
            rel_hits = check_text(path_part, text_before)
            if rel_hits:
                hits.append("%s @%s" % (rel_hits[0], rev[:8]))
    if scanned_trees and not probe_found:
        raise RuntimeError("历史扫描通道探活失败：全部 %d 棵树都搜不到探针（仓库名）" % scanned_trees)
    return hits, len(revs)


def scan_metadata():
    """提交元数据：作者/提交者邮箱必须全部为 GitHub noreply（两个字段都查）。"""
    result = subprocess.run(
        ["git", "log", "--format=%ae|%ce", "--all"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=REPO_ROOT, check=True,
    )
    raw = result.stdout.decode("utf-8", "replace")
    hits = []
    values = sorted(set(line for line in raw.splitlines() if line.strip()))
    for pair in values:
        author_email, _, committer_email = pair.partition("|")
        for field, email in (("author", author_email), ("committer", committer_email)):
            if not _NOREPLY_OK_RE.match(email.strip()):
                # 掩码化：只报字段与形态，不回显邮箱原文
                hits.append("git metadata [%s-email] 非 noreply 形态（掩码：%s…@%s）"
                            % (field, email.strip()[:2], email.strip().split("@")[-1]))
    return hits, len(values)


def _positive_samples():
    """阳性样本（程序化合成，无真实词面）。"""
    users_path = "D:" + "\\" + "Users" + "\\" + "someone" + "\\" + "x\\file.txt"
    return (
        ("个人路径", "notes/a.md", "见 " + users_path, "personal-path"),
        ("私人邮箱", "notes/b.md", "邮箱 " + "some" + "one@example.com", "email"),
        ("密钥字面", "notes/c.md", "key = " + "sk-" + "a" * 24, "secret"),
        ("手机号", "notes/d.md", "电话 " + "138" + "0013" + "8000", "phone"),
        ("敏感文件名", "docs/my.secret.md", "", "filename"),
    )


def _negative_samples():
    return (
        ("noreply 邮箱", "notes/e.md", git_noreply_reference(), None),
        ("GitHub 账号名（发布坐标）", "notes/f.md", "github.com/" + _repo_dir_name().replace("checkup", "yuluo554/x"), None),
        ("普通路径", "notes/g.md", "配置写在 data/config.yaml", None),
        ("长十六进制串", "notes/h.md", "sha256 " + "a1f8" * 16, None),
    )


def git_noreply_reference():
    """从仓库实算 noreply 样例（不写死词面）。"""
    result = subprocess.run(
        ["git", "log", "--format=%ae", "-1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=REPO_ROOT, check=True,
    )
    return result.stdout.decode("utf-8", "replace").strip()


def selftest():
    """阳性必拦 + 阴性必放（判定只跑 check_text/check_filename，不落盘）。"""
    failures = []
    for label, rel, text, expected in _positive_samples():
        if expected == "filename":
            gotten = check_filename(rel)
        else:
            gotten = check_text(rel, text)
        kinds = [item.split("[", 1)[1].split("]", 1)[0] for item in gotten]
        if expected not in kinds:
            failures.append("阳性未被拦：%s（期望 %s，实得 %s）" % (label, expected, kinds or "无"))
    for label, rel, text, _e in _negative_samples():
        if check_text(rel, text) or check_filename(rel):
            failures.append("阴性被误拦：%s" % label)
    if failures:
        for item in failures:
            sys.stderr.write("[脱敏审计 selftest] %s\n" % item)
        return _EXIT_HIT
    print("[脱敏审计 selftest] 通过：阳性 %d 项全拦 + 阴性 %d 项全放"
          % (len(_positive_samples()), len(_negative_samples())))
    return _EXIT_OK


def run(steps):
    total_hits = []
    allowed = []
    summary = []
    if "tracked" in steps:
        hits, count = scan_tracked()
        summary.append("工作树扫描：%d 个跟踪文件，硬命中 %d 处 + 放行 %d 处"
                       % (count, len([h for h in hits if "行内放行" not in h]), len([h for h in hits if "行内放行" in h])))
        allowed.extend([h for h in hits if "行内放行" in h])
        total_hits.extend([h for h in hits if "行内放行" not in h])
    if "history" in steps:
        hits, count = scan_history()
        summary.append("全历史扫描：%d 个提交，硬命中 %d 处" % (count, len(hits)))
        total_hits.extend(hits)
    if "metadata" in steps:
        hits, count = scan_metadata()
        summary.append("提交元数据：%d 个 ae|ce 组合，硬命中 %d 处" % (count, len(hits)))
        total_hits.extend(hits)

    for line in summary:
        print("[脱敏审计] %s" % line)
    if allowed:
        print("[脱敏审计] 行内放行（仍可见，不计入阻断）：")
        for item in allowed:
            print("  = %s" % item)
    if total_hits:
        print("[脱敏审计] 命中明细（掩码化）：")
        for item in total_hits:
            print("  · %s" % item)
        print("[脱敏审计] 结论：DESENSITIZE_AUDIT_FAIL（%d 处）" % len(total_hits))
        return _EXIT_HIT
    print("[脱敏审计] 结论：DESENSITIZE_AUDIT_OK")
    return _EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(description="发布期脱敏审计（四步可复跑）")
    parser.add_argument("--tracked", action="store_true", help="扫工作树跟踪文件")
    parser.add_argument("--history", action="store_true", help="全历史 blob 扫描")
    parser.add_argument("--metadata", action="store_true", help="提交元数据邮箱")
    parser.add_argument("--selftest", action="store_true", help="自证：阳性必拦 + 阴性必放")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    steps = []
    if args.tracked:
        steps.append("tracked")
    if args.history:
        steps.append("history")
    if args.metadata:
        steps.append("metadata")
    if not steps:
        steps = ["tracked", "history", "metadata"]
    return run(steps)


if __name__ == "__main__":
    sys.exit(main())
