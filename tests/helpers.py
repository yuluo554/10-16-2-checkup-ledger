"""测试期共享辅助：定位仓库根、加载本包、跑 CLI（不装包也能跑）。"""

import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(REPO_ROOT, "src")

if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


def repo_path(*parts) -> str:
    return os.path.join(REPO_ROOT, *parts)


def read_text(rel_path) -> str:
    with open(repo_path(rel_path), "r", encoding="utf-8") as handle:
        return handle.read()


def run_cli(argv=None):
    """跑 CLI 主函数，返回 (退出码, stdout, stderr)。

    注意断言要落在 `out.getvalue()` / `err.getvalue()` 上——对 StringIO **对象**
    做 `in` 判断是按整对象行匹配，中文消息会静默假失败。
    """
    from checkup_ledger.cli import main

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv if argv is not None else [])
    return code, out.getvalue(), err.getvalue()


# 扫描面排除项：虚拟环境 / 构建产物 / 缓存（这些不是"仓库内容"，
# 且第三方包里必然出现与 PII 形态巧合的字符串——不排除就是拿别人的包误报）
EXCLUDED_DIR_PREFIXES = (
    ".venv", "venv", "env", ".eggs", "build", "dist", "__pycache__",
    ".git", "node_modules", ".tox", ".mypy_cache", ".pytest_cache",
)


def _is_excluded(rel_path):
    parts = rel_path.replace("\\", "/").split("/")
    for part in parts[:-1]:
        for prefix in EXCLUDED_DIR_PREFIXES:
            if part == prefix or part.startswith(".venv") or part.startswith("venv"):
                return True
    return False


def tracked_files():
    """仓库内**会入库**的文件（相对仓库根，POSIX 形式）。

    用 `git ls-files --cached --others --exclude-standard`：既含已提交文件，也含
    新增未提交文件（**否则新写的源码不在扫描面里，门禁对着旧快照空转**——
    判据 = "这个文件此刻会在仓库里吗"，而不是"它曾被提交过吗"）。
    `--exclude-standard` 已排除 .gitignore 命中项；不在 git 环境时回落 os.walk
    并手动排除虚拟环境/构建产物。

    子进程显式传 encoding：`text=True` 走 locale，中文文件名在 cp1252 下会
    UnicodeDecodeError（无环境变量可替代）。
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=REPO_ROOT,
        )
        if result.returncode == 0:
            raw = result.stdout.decode("utf-8", "replace")
            files = [item for item in raw.split("\0") if item.strip()]
            if files:
                return [item for item in files if not _is_excluded(item)]
    except OSError:
        pass

    files = []
    for root, dirs, names in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if not _is_excluded(d + "/x")]
        for name in names:
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, REPO_ROOT).replace(os.sep, "/")
            if not _is_excluded(rel):
                files.append(rel)
    return sorted(files)


def iter_source_files():
    """本包源码文件（相对仓库根）。"""
    for rel in tracked_files():
        if rel.startswith("src/") and rel.endswith(".py"):
            yield rel


def iter_python_files():
    """仓库内全部 Python 文件（src + tools + tests）。"""
    for rel in tracked_files():
        if rel.endswith(".py") and rel.split("/")[0] in ("src", "tools", "tests"):
            yield rel
