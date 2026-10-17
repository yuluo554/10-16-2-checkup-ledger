"""安装面五面对账：测试面 == 安装面 == README 指令面。

五面（缺一面就会漏一类"本机全绿、用户一跑就炸"）：
1. README 命令/旗标 → CLI `build_parser()` 反射（逐条把旗标关联到它的子命令，
   防"旗标写在错的命令行上"的张冠李戴）；
2. CLI 子命令 → README 反向覆盖（防"实现了没写文档"与"写了文档没实现"）；
3. tests/ 全部 import（AST 从严收集，**含函数体内 import**）→ 落点四分法；
4. README 的 `pip install -e ".[...]"` 行 ↔ pyproject 声明的 extras 双向一致；
5. `packages.find` include → 真实包布局（含子包在位 + 包内数据目录在位）。

两条纪律：
- **stdlib 名单用冻结名单制**，不用 `sys.stdlib_module_names`（3.10+ 才有；
  3.8 上取到空集 → 每个标准库都判成第三方 → 全量假红）。
- **脚本自己的取文本过程不能把目标切坏**：每面配"扫描面非空"自证断言
  （抽取到空集也是红不了的原因之一）。
"""

import ast
import os
import re
import sys

import pytest

from helpers import iter_python_files, read_text, repo_path

from checkup_ledger.cli import build_parser

# ---- 冻结的 stdlib 名单（3.8 即存在的模块；新用到的标准库要同步进这里）----
STDLIB_FROZEN = frozenset(
    """
    __future__ abc argparse ast base64 binascii bisect builtins bz2 calendar cmath
    cmd codecs collections colorsys configparser contextlib copy csv ctypes dataclasses
    datetime decimal difflib dis doctest email encodings enum errno faulthandler fnmatch
    fractions ftplib functools gc getopt getpass gettext glob grp gzip hashlib heapq hmac
    html http imaplib importlib inspect io ipaddress itertools json keyword linecache
    locale logging lzma mailbox marshal math mimetypes mmap multiprocessing netrc ntpath
    numbers operator optparse os pathlib pickle pipes pkgutil platform plistlib poplib
    posixpath pprint profile pstats pty py_compile pyclenums queue quopri random re reprlib
    sched secrets select selectors shelve shlex shutil signal site smtplib socket socketserver
    sqlite3 ssl stat statistics string stringprep struct subprocess symtable sys sysconfig
    tarfile tempfile termios textwrap threading time timeit token tokenize traceback tracemalloc
    tty types typing unicodedata unittest urllib uuid venv warnings wave weakref webbrowser
    xml xmlrpc zipfile zipimport zlib
    """.split()
)

# 本包模块（相对 src/ 的顶层名）
PACKAGE_ROOT = "checkup_ledger"

# README 里允许出现的"非命令"词（避免把叙述文字误当命令）
README_COMMAND_RE = re.compile(
    r"^\s*(?:checkup-ledger|python -m checkup_ledger|py -X utf8 -m checkup_ledger|python|py|git|cd)\b.*$",
    re.MULTILINE,
)


# ============================================================ 面 1


def _subparser_names(parser):
    """从 parser 里取子命令名（argparse 内部结构，跨版本用 _actions 反射）。"""
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and choices:
            return dict(choices)
    return {}


def _flag_dest_map(parser):
    """该 parser 认识的旗标集合（含 `--flag` 与 `-f` 形式）。"""
    flags = set()
    for action in parser._actions:
        for opt in action.option_strings:
            flags.add(opt)
    return flags


def test_face1_readme_flags_resolve_on_correct_subcommand():
    """README 里出现的每个 `--flag` 都必须能在其所在命令行上解析到。

    逐行关联：先认出该行是哪个子命令，再断言旗标属于那个子命令——而不是
    "全仓库某处有这个旗标"（那会放过"旗标写在错的命令行上"）。
    """
    readme = read_text("README.md")
    parser = build_parser()
    subs = _subparser_names(parser)
    global_flags = _flag_dest_map(parser)

    checked = 0
    for line in readme.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("checkup-ledger", "python -m checkup_ledger", "py -X utf8 -m checkup_ledger")):
            continue
        tokens = stripped.split()
        subcommand = None
        for token in tokens[1:]:
            if token in subs:
                subcommand = token
                break
        flags = [t for t in tokens if t.startswith("--") and t != "--"]
        for flag in flags:
            checked += 1
            if subcommand is None:
                assert flag in global_flags, "README 行 `%s` 里的旗标 %s 在解析器上不存在" % (stripped, flag)
            else:
                allowed = set(global_flags) | _flag_dest_map(subs[subcommand])
                assert flag in allowed, (
                    "README 行 `%s`：旗标 %s 不能挂在子命令 %s 上" % (stripped, flag, subcommand)
                )
    assert checked > 0, "扫描面为空：README 里没有识别到任何命令行旗标（探针可能把文本切坏了）"


# ============================================================ 面 2


def test_face2_every_subcommand_is_documented():
    """**每个**已实现的子命令都要在 README 出现。

    M4 起首期五模块全部落地、`NOT_READY`(4) 整项退役，故不再有"未就绪命令可
    豁免"这条例外——**全部**子命令都必须在 README 的命令速查里逐条出现。
    这条比旧版更严：旧版允许未就绪命令只被里程碑状态节"点名"就算交代，
    退役后没有任何命令可以靠这个豁免（也就没有"实现了但只在计划里提到"的余地）。
    """
    readme = read_text("README.md")
    parser = build_parser()
    subs = _subparser_names(parser)
    assert subs, "解析器未暴露任何子命令（反射探针失效）"

    missing = [name for name in subs if name not in readme]
    assert not missing, "已实现但 README 未提及的子命令：%s" % missing


def test_face2_every_documented_command_exists():
    readme = read_text("README.md")
    parser = build_parser()
    subs = _subparser_names(parser)
    documented = set(re.findall(r"checkup-ledger\s+([a-z][a-z0-9-]*)", readme))
    unknown = sorted(name for name in documented if name not in subs)
    assert not unknown, "README 提到但未实现的子命令：%s" % unknown
    assert documented, "扫描面为空：README 里没有识别到任何 `checkup-ledger <命令>`"


# ============================================================ 面 3


def _collect_imports(path):
    """AST 从严收集 import（含函数体内 import）。"""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # 相对导入 = 本包
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def _all_declared_import_names():
    """pyproject 声明的**全部** extras 的导入名（dev + 用户可选能力）。

    测试会用到可选 extras（如 `[ocr]` 的 `rapidocr_onnxruntime`），且**只在函数体内
    import、并自行 try/except 跳过**——这是合法用法，故面 3 的落点集合应含全部 extras，
    而不是只看 dev（只看 dev 会把合法的可选依赖误判成"未声明"）。
    """
    names = set()
    for specs in _declared_extras().values():
        for spec in specs:
            names.add(_distribution_to_import(spec))
    return names


# 仓库脚本模块：不是安装面的一部分，由 `tests/conftest.py` 把 `tools/` 加进 sys.path
# （`freeze_build` 是 M5 的冻结构建/验证驱动——测试直接 import 它的纯函数做静态门，
# 而不是走子进程；它同样不属于安装面）
REPO_SCRIPT_MODULES = frozenset({"tools", "fixtures", "helpers", "freeze_build"})


def test_face3_tests_imports_resolve_to_declared_places():
    """tests/ 真 import 的每个顶层库，必须落在：stdlib / 任一 extras / 本包 / 仓库脚本。"""
    declared = _all_declared_import_names()

    unresolved = []
    collected = 0
    for rel in iter_python_files():
        if not rel.startswith("tests/"):
            continue
        for name in _collect_imports(repo_path(rel)):
            collected += 1
            if name in STDLIB_FROZEN:
                continue
            if name == PACKAGE_ROOT:
                continue
            if name in REPO_SCRIPT_MODULES:
                continue
            if name in declared:
                continue
            if name in ("yaml",):  # 核心依赖，同时声明在 dependencies
                continue
            unresolved.append("%s imports %s" % (rel, name))

    assert collected > 0, "扫描面为空：未从 tests/ 收集到任何 import"
    assert not unresolved, "测试依赖未在任何安装面声明：%s" % unresolved


def test_face3_pdf_and_ocr_deps_are_not_module_level_in_tests():
    """可选重件（pdf/ocr）不得在测试里做模块级 import——那会让只装 dev 的 CI 直接收集失败。"""
    optional = ("pdfplumber", "rapidocr_onnxruntime", "rapidocr", "fitz", "PySide6")
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith("tests/"):
            continue
        with open(repo_path(rel), "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=rel)
        for node in tree.body:  # 只看模块级
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in optional:
                        offenders.append("%s (module level import %s)" % (rel, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in optional:
                    offenders.append("%s (module level from %s)" % (rel, node.module))
    assert not offenders, "测试模块级 import 了可选重件：%s" % offenders


# ============================================================ 面 4


def _declared_extras():
    """读 pyproject 的 `[project.optional-dependencies]` 声明。

    自写极简解析（**不引 tomli/tomllib**）：tomllib 是 3.11+ 才有，tomli 是第三方——
    为解析一个配置文件而给测试期引入依赖得不偿失（且会让"测试依赖未声明"门自己
    变成缺口）。TOML 子集在这里够用：段内 `name = ["a", "b"]`，数组可跨行。
    """
    text = read_text("pyproject.toml")
    lines = text.splitlines()

    start = None
    for index, line in enumerate(lines):
        if line.strip() == "[project.optional-dependencies]":
            start = index + 1
            break
    if start is None:
        return {}

    block = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            break  # 下一段开始
        block.append(line)

    joined = "\n".join(block)
    extras = {}
    # 形如： name = [ "a>=1", "b" ]   （允许换行、允许行内注释）
    for match in re.finditer(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*\[(.*?)\]", joined, re.DOTALL | re.MULTILINE):
        name = match.group(1).strip()
        body = re.sub(r"#.*", "", match.group(2))
        extras[name] = re.findall(r"[\"']([^\"']+)[\"']", body)
    return extras


def _distribution_to_import(spec):
    """分发名 → import 名（别名表；直接比较会造假红）。"""
    alias = {
        "pyyaml": "yaml",
        "pillow": "PIL",
        "pyinstaller": "PyInstaller",
        "rapidocr-onnxruntime": "rapidocr_onnxruntime",
    }
    name = re.split(r"[<>=!\[; ]", spec.strip(), 1)[0].strip().lower()
    return alias.get(name, name.replace("-", "_"))


def test_face4_readme_extras_match_pyproject():
    """README 的 `pip install -e ".[...]"` 行 ↔ pyproject extras 双向一致。"""
    readme = read_text("README.md")
    declared = set(_declared_extras())
    assert declared, "pyproject 未声明任何 extras（探针可能解析失败）"

    used = set()
    for match in re.finditer(r"pip install[^\n]*?\.\[([^\]]+)\]", readme):
        for name in re.split(r"[,\s]+", match.group(1).strip()):
            if name:
                used.add(name)

    assert used, "扫描面为空：README 里没有识别到任何 `.[extras]` 安装行"

    undeclared = sorted(name for name in used if name not in declared)
    assert not undeclared, "README 使用但 pyproject 未声明的 extras：%s" % undeclared


def test_face4_optional_extras_are_documented_in_readme():
    """反向：pyproject 声明的**可选能力** extras 必须在 README 里出现过。

    这条挡的是同系列项目实测过的缺口（项目代号按品牌隔离纪律不落库）：README
    让用户去跑某工具，而那个工具依赖的 extra 在 README 里从未出现——用户照做到
    那一步才炸。
    """
    readme = read_text("README.md")
    declared = _declared_extras()
    # dev/freeze 是开发与构建用途，其余是用户可选能力
    user_facing = sorted(name for name in declared if name not in ("dev", "freeze"))
    assert user_facing, "pyproject 未声明任何用户可选 extras（探针可能解析失败）"
    missing = [name for name in user_facing if name not in readme]
    assert not missing, "pyproject 声明但 README 未提及的 extras：%s" % missing


def test_face4_dev_extra_covers_test_time_deps():
    """测试套件真 import 的第三方库都要在 dev extras 里。

    **例外**：可选 extras（`[pdf]`/`[ocr]`）里的库可以出现在测试里，前提是它们
    只在函数体内 import 并自行跳过（由 `test_face3_pdf_and_ocr_deps_are_not_module_level_in_tests`
    守住"不做模块级 import"）。把可选依赖也塞进 `[dev]` 会让"只装 dev"的 CI
    拉进 14MB 的 OCR 轮子——那是让测试面与交付面耦合。
    """
    dev = _declared_extras().get("dev", [])
    dev_imports = {_distribution_to_import(spec) for spec in dev}
    optional_imports = {
        _distribution_to_import(spec)
        for name, specs in _declared_extras().items()
        if name not in ("dev", "freeze")
        for spec in specs
    }
    third_party_in_tests = set()
    for rel in iter_python_files():
        if not rel.startswith("tests/"):
            continue
        for name in _collect_imports(repo_path(rel)):
            if name in STDLIB_FROZEN or name in (PACKAGE_ROOT,) or name in REPO_SCRIPT_MODULES:
                continue
            if name == "yaml":
                continue  # 核心依赖（dependencies 已声明），非测试期专有
            if name in optional_imports:
                continue  # 可选 extras：函数体内 import + 自行跳过（由面 3 的另一条守）
            third_party_in_tests.add(name)
    missing = sorted(name for name in third_party_in_tests if name not in dev_imports)
    assert not missing, "测试用的第三方库未在 dev extras 中声明：%s" % missing


# ============================================================ 面 5


def test_face5_packages_find_covers_real_layout():
    """`packages.find` 的 where 解析出的包目录必须真实存在（含子包与包内数据）。"""
    assert os.path.isdir(repo_path("src", PACKAGE_ROOT)), "包目录不存在"
    for sub in ("engine", "report", "benchmark", "ingest", "normalize"):
        init = repo_path("src", PACKAGE_ROOT, sub, "__init__.py")
        assert os.path.isfile(init), "子包 %s 缺 __init__.py（不会被 packages.find 收录）" % sub

    text = read_text("pyproject.toml")
    match = re.search(r"\[tool\.setuptools\.packages\.find\](.*?)(?:\n\[|\Z)", text, re.DOTALL)
    assert match, "pyproject 缺 [tool.setuptools.packages.find] 配置"
    where = re.findall(r"where\s*=\s*\[([^\]]*)\]", match.group(1))
    assert where, "packages.find 未声明 where（探针可能把配置切坏了）"
    roots = [item.strip().strip("\"'") for item in where[0].split(",") if item.strip()]
    assert "src" in roots, "packages.find 的 where 未包含 src：%s" % roots
    assert os.path.isdir(repo_path("src")), "where 声明的 src 目录不存在"


def test_face5_package_data_includes_runtime_assets():
    """包内数据白名单必须覆盖运行时必需资产。"""
    text = read_text("pyproject.toml")
    assert "package-data" in text, "pyproject 缺 package-data 声明"
    assert os.path.isfile(repo_path("src", PACKAGE_ROOT, "data", "indicators.yaml")), "运行时数据缺失"
    assert os.path.isfile(repo_path("src", PACKAGE_ROOT, "benchmark", "cases.json")), "基准用例数据缺失"
    assert "data/*.yaml" in text, "package-data 未包含 data/*.yaml"
    assert "benchmark/*.json" in text, "package-data 未包含 benchmark/*.json"


def test_face5_no_test_or_tools_dir_inside_package():
    """包内不得混入测试/工具目录（否则会被打包进安装面）。"""
    pkg = repo_path("src", PACKAGE_ROOT)
    for name in sorted(os.listdir(pkg)):
        assert name not in ("tests", "tools"), "包内出现不该入包的目录：%s" % name


@pytest.mark.skipif(sys.version_info < (3, 8), reason="require 3.8+")
def test_frozen_stdlib_list_covers_actually_used_stdlib():
    """冻结 stdlib 名单必须覆盖测试**实际**用到的标准库。

    这条是名单的维护门：新增 stdlib import 忘了进名单时，会在这里红
    （而不是让面 3 把标准库误判成第三方、造成全量假红的误导）。
    """
    used = set()
    for rel in iter_python_files():
        if rel.startswith("tests/"):
            used |= _collect_imports(repo_path(rel))
    suspects = sorted(
        name for name in used if name not in STDLIB_FROZEN and name not in (PACKAGE_ROOT,) and name not in REPO_SCRIPT_MODULES
    )
    third_party_ok = _all_declared_import_names()
    third_party_ok |= {"yaml"}  # 核心依赖
    stray = [name for name in suspects if name not in third_party_ok]
    assert not stray, "这些 import 既不在 stdlib 冻结名单、也不在 dev extras：%s（若是标准库请补进名单）" % stray
