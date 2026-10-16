"""行尾守门：已跟踪文本文件零 CR。

`.gitattributes` 的 `eol=lf` 管住**检入**的行尾，但守门要落在**工作树实况**上——
否则"属性写了但没人验"，CRLF 仍会随某次编辑器保存进仓，让跨平台"逐字节一致"红。
"""

import os

from helpers import REPO_ROOT, tracked_files

TEXT_EXTENSIONS = (
    ".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".rst", ".html", ".htm", ".js", ".ts", ".sh", ".bat", ".cmd", ".ps1", ".gitattributes",
    ".gitignore", ".csv",
)

# 空扩展名的文本类文件（如 .gitignore 已含扩展名形式）
KNOWN_TEXT_BASENAMES = ("pre-commit", "commit-msg", "pre-push")

_BINARY_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".db", ".sqlite", ".onnx", ".zip", ".exe")


def _is_text_candidate(rel_path):
    lowered = rel_path.lower()
    if lowered.endswith(_BINARY_EXTENSIONS):
        return False
    if lowered.endswith(TEXT_EXTENSIONS):
        return True
    return os.path.basename(lowered) in KNOWN_TEXT_BASENAMES


def test_no_cr_in_tracked_text_files():
    offenders = []
    checked = 0
    for rel in tracked_files():
        if not _is_text_candidate(rel):
            continue
        abs_path = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(abs_path):
            continue
        checked += 1
        with open(abs_path, "rb") as handle:
            if b"\r" in handle.read():
                offenders.append(rel)
    assert checked > 0, "扫描面为空：未找到任何文本候选文件（守门自身失效）"
    assert not offenders, "以下文件含 CR（应为 LF）：%s" % offenders


def test_no_cr_in_tracked_file_list_covers_source_and_docs():
    """扫描面必须覆盖源码与文档——只扫一边会让另一边静默漏过。"""
    candidates = [rel for rel in tracked_files() if _is_text_candidate(rel)]
    assert any(rel.startswith("src/") for rel in candidates), "扫描面未覆盖 src/"
    assert any(rel.endswith(".md") for rel in candidates), "扫描面未覆盖 markdown"


def test_gitattributes_declares_lf_normalization():
    with open(os.path.join(REPO_ROOT, ".gitattributes"), "r", encoding="utf-8") as handle:
        text = handle.read()
    assert "text=auto" in text, ".gitattributes 缺 text=auto"
    assert "eol=lf" in text, ".gitattributes 缺 eol=lf"


def test_gitattributes_marks_binary_and_frozen_assets():
    """二进制与冻结快照必须显式标 binary/-text——否则克隆时字节被归一化、sha256 失配。"""
    with open(os.path.join(REPO_ROOT, ".gitattributes"), "r", encoding="utf-8") as handle:
        text = handle.read()
    for pattern in ("*.pdf", "*.png", "*.db", "*.onnx", "*.zip", "*.exe"):
        assert pattern in text, ".gitattributes 未登记二进制形态：%s" % pattern
    assert "-text" in text, ".gitattributes 未对冻结快照标 -text"


def test_gitignore_covers_local_health_data():
    """.gitignore 必须覆盖台账 db 与真实报告目录。"""
    with open(os.path.join(REPO_ROOT, ".gitignore"), "r", encoding="utf-8") as handle:
        text = handle.read()
    for pattern in ("*.db", "*.sqlite", "real_reports/", "private/"):
        assert pattern in text, ".gitignore 未覆盖：%s" % pattern
