"""冻结构建与产物验证驱动（M5）。

**为什么构建要写成脚本，而不是一条手敲的 pyinstaller 命令**：
DoD 要求"发行包内无 TLS/出站组件"与"入包集合 == 白名单"这两条**可扫断言**。
断言要可扫，构建的 `--exclude-module` 清单与 `--add-data` 清单就必须是**单点定义**
（一个元组、一处派生），否则"构建时排除了、验证时却按另一份清单核对"——
门守的是验证脚本自己的想象，不是真正打出来的那个包。

四件事，逐条对应 DoD：

1. **构建**：`build_dist()` 走 PyInstaller（**≥6 那条解释器通道**，见 `require_pyinstaller`）。
2. **内嵌数据对账**：`verify_embedded_data()` 双向比对——白名单每条都要在包里
   （查漏拷），包里每份数据都要在白名单内（查多拷），且逐份 sha256 与仓库冻结件一致。
3. **零上传可扫断言**：`scan_no_outbound()` 静态扫 dist 树 + 扫 PYZ 模块名表。
4. **真跑产物**：`run_frozen_smoke()` 在**中立目录**（仓库外临时目录）用
   **`env -i` 等价环境**（Windows 只留 `SYSTEMROOT`）跑 exe。

另加 **打包确定性**：`pack_deterministic_zip()` 用 `ZIP_STORED` + 条目排序 +
固定 `date_time`——同一 dist 两次打包逐字节一致。**exe 构建本身不承诺跨机一致**
（PyInstaller 产物内含构建期时间戳），这条只承诺"同一份 dist 的打包过程确定"。

### 实测偏差（必须如实记录，不许粉饰）

`ssl` / `http.client` / `urllib.request` / `ftplib` / `xmlrpc` / `asyncio` 等**可以**排除，
但 **`socket` 排不掉**：`pdfminer/__init__.py` 在模块级 `from importlib.metadata import
version`，而 `importlib.metadata` 在模块级 `import email`，`email.utils` 又在模块级
`import socket`。强行 `--exclude-module socket` 会让 `import pdfplumber` 直接
`ModuleNotFoundError`（实测：`ingest` 报 exit 3"缺 pdfplumber，底层错误 No module
named 'socket'"）。

故本脚本的口径是：**排除全部"具备出站能力"的组件**（TLS / HTTP / FTP / SMTP /
telnet / 异步与并发调度），保留 `socket` 这个名字本身，并把这份残留**显式登记**
在 `SOCKET_RESIDUE_*` 里（新增残留必须显式改这里 + 同步测试）。仅剩裸 socket 模块
而**无任何出站协议栈**，加上源码侧"零网络调用"的既有断言，才是"零上传"的实况。
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
PKG = os.path.join(SRC, "checkup_ledger")
ENTRY = os.path.join(PKG, "frozen_entry.py")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
EXE_NAME = "checkup-ledger"

# ---------------------------------------------------------------- 清单（单点定义）

# Qt 系与图像/数值重件：体积分档（plan/02 第十一节"冻结产物体积过大"的处置）。
QT_EXCLUDES = (
    "PySide6",
    "PyQt5",
    "PyQt6",
    "shiboken6",
    "matplotlib",
    "numpy",
    "PIL",
    "tkinter",
)

# 出站能力组件：TLS / HTTP / FTP / SMTP / telnet / 异步与并发调度。
# 这份清单就是"零上传"的判据面——新增一项就必须让构建也排除它。
OUTBOUND_EXCLUDES = (
    "ssl",
    "_ssl",
    "http",
    "urllib.request",
    "ftplib",
    "xmlrpc",
    "smtplib",
    "telnetlib",
    "requests",
    "urllib3",
    "asyncio",
    "concurrent",
)

BUILD_EXCLUDES = QT_EXCLUDES + OUTBOUND_EXCLUDES

# 模块名表里的出站命中面（前缀匹配）。
OUTBOUND_MODULE_PREFIXES = OUTBOUND_EXCLUDES

# 产物文件名里的出站命中面（前缀匹配；`libssl-3.dll` 与 `_ssl.pyd` 是 TLS 运行时）。
OUTBOUND_FILE_PREFIXES = ("_ssl", "libssl")

# 实测偏差：排不掉的残留（理由见模块 docstring）。新增残留必须显式登记。
SOCKET_RESIDUE_MODULES = ("socket", "selectors")
SOCKET_RESIDUE_FILES = ("_socket.pyd",)
SOCKET_RESIDUE_REASON = (
    "pdfminer 在模块级经 importlib.metadata 触发 email.utils 的模块级 import socket；"
    "selectors 供 select/pathlib 通路使用。排除 socket 会让 import pdfplumber 直接失败"
    "（实测 ingest 报 exit 3）。二者均不含协议栈，仅保留名字，由动态探针证明从不调用。"
)

# 白名单里**声明为空**的模式：`package-data` 声明的模式必须逐个匹配到文件，
# 匹配不到就是"声明的白名单与实况不符"——那正是本对账要抓的一类漏拷。
# 唯一例外是 `data/*.yml`：仓库当前只有 `.yaml`（19 条知识库条目），`.yml` 是
# 标准 YAML 的另一扩展名，保留它是为将来新增 `.yml` 分册时不必改安装面声明。
# 这类"合法的空模式"必须逐条登记理由，并由 `tests/test_frozen.py` 锁死清单内容
# （与零字面量门禁的 `EXEMPT_FILES` 同一套纪律：豁免要显式、要写理由、要被锁）。
DECLARED_EMPTY_PATTERNS = {
    "data/*.yml": "仓库当前只有 .yaml；保留 .yml 模式供将来新增分册，不构成漏拷",
}


def require_pyinstaller():
    """取 PyInstaller 版本；**<6 直接拒绝**（本项目固定在 ≥6 那条通道）。"""
    try:
        import PyInstaller
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise RuntimeError(
            "未安装 PyInstaller（冻结构建需要 `pip install -e \".[freeze]\"`）：%s" % exc
        )
    version = getattr(PyInstaller, "__version__", "0")
    parts = re.split(r"[.\-+]", version)
    try:
        major = int(parts[0])
    except (ValueError, IndexError):
        raise RuntimeError("无法解析 PyInstaller 版本：%r" % version)
    if major < 6:
        raise RuntimeError(
            "PyInstaller %s < 6：本项目冻结构建固定在装了 ≥6 的那条解释器通道"
            "（当前解释器 %s）" % (version, sys.executable)
        )
    return version


# ---------------------------------------------------------------- 白名单（源自 pyproject）

def _package_data_patterns():
    """从 `pyproject.toml` 的 `[tool.setuptools.package-data]` 读随包数据模式。

    自写极简解析（**不引 tomllib**）：3.8 没有 tomllib，为解析一个配置而给测试期
    引依赖得不偿失。TOML 子集在此够用——段内 `checkup_ledger = ["a", "b"]`，可跨行。

    **为什么从 pyproject 读**：随包数据白名单已在 `package-data` 里定义过一次
    （安装面用它）。构建脚本再手写一份就是第二处定义——改一处忘一处，冻结包里
    就会少拷或多拷而没有任何门发现。
    """
    with open(PYPROJECT, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    start = None
    for index, line in enumerate(lines):
        if line.strip() == "[tool.setuptools.package-data]":
            start = index + 1
            break
    if start is None:
        raise RuntimeError("pyproject.toml 缺 [tool.setuptools.package-data] 段")

    block = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        block.append(line)

    joined = "\n".join(block)
    match = re.search(r"^\s*checkup_ledger\s*=\s*\[(.*?)\]", joined, re.DOTALL | re.MULTILINE)
    if not match:
        raise RuntimeError("package-data 段未声明 checkup_ledger 白名单")
    body = re.sub(r"#.*", "", match.group(1))
    patterns = re.findall(r"[\"']([^\"']+)[\"']", body)
    if not patterns:
        raise RuntimeError("package-data 的 checkup_ledger 白名单为空（探针失效）")
    return patterns


def data_whitelist():
    """白名单的**展开结果**：仓库内相对路径（POSIX），逐条真实存在。

    模式（如 `data/*.yaml`）在这里展开成具体文件——展开只此一处，
    `--add-data` 参数与对账断言共用它。
    """
    import glob

    package_dir = os.path.join(SRC, "checkup_ledger")
    found = []
    for pattern in _package_data_patterns():
        matches = glob.glob(os.path.join(package_dir, pattern.replace("/", os.sep)))
        if not matches:
            if pattern in DECLARED_EMPTY_PATTERNS:
                continue  # 已登记的空模式（理由见 DECLARED_EMPTY_PATTERNS）
            raise RuntimeError("白名单模式未匹配到任何文件：%s" % pattern)
        for match in matches:
            rel = os.path.relpath(match, ROOT).replace(os.sep, "/")
            if rel not in found:
                found.append(rel)
    if not found:
        raise RuntimeError("白名单展开为空（探针失效）")
    return sorted(found)


def dest_for(rel_path):
    """仓库相对路径 → 包内目标路径（`--add-data` 的 dest 与对账共用本函数）。

    两条规则，对应 `paths.py` 的运行时约定：
    - `data/` 下的随包数据落在 exe 旁的 `data/`（`resolve_data_dir()` 冻结态分支读它）；
    - `benchmark/` 下的基准用例落在 `<包名>/benchmark/`（`runner.cases_path()` 按
      `__file__` 定位，故必须保住包目录层级）。
    """
    prefix = "src/checkup_ledger/"
    if not rel_path.startswith(prefix):
        raise ValueError("随包数据必须在 %s 之下：%s" % (prefix, rel_path))
    tail = rel_path[len(prefix):]
    if tail.startswith("data/"):
        return tail
    if tail.startswith("benchmark/"):
        return "checkup_ledger/" + tail
    raise ValueError("未登记的随包数据落点：%s（落点规则只有 data/ 与 benchmark/ 两条）" % tail)


# ---------------------------------------------------------------- 构建

def build_command(out_root, name=EXE_NAME, python=None):
    """PyInstaller 命令行的**唯一构造处**。

    单点构造的理由：`tests/test_frozen.py` 要断言"构建命令真的排除了全部出站组件
    且真的拷了白名单每一份"——若测试自己拼一份期望命令，它守的是测试的想象；
    从本函数取命令，守的才是真正会执行的那条。
    """
    python = python or sys.executable
    work = os.path.join(out_root, "work")
    dist_root = os.path.join(out_root, "dist")
    spec = os.path.join(out_root, "spec")

    command = [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        name,
        "--paths",
        SRC,
        "--distpath",
        dist_root,
        "--workpath",
        work,
        "--specpath",
        spec,
    ]
    for rel in data_whitelist():
        target = dest_for(rel)
        command += [
            "--add-data",
            os.path.join(ROOT, rel.replace("/", os.sep)) + os.pathsep + os.path.dirname(target),
        ]
    for module in BUILD_EXCLUDES:
        command += ["--exclude-module", module]
    command.append(ENTRY)
    return command


def build_dist(out_root, name=EXE_NAME, python=None, quiet=True):
    """跑 PyInstaller 产出 onedir 冻结包，返回 `(dist_dir, log)`。

    产物一律落在 `out_root`（调用方给**仓库外**目录）：构建中间物（work/spec）
    若落在仓库内，会被门禁扫描面扫进（行尾守门、PII gate 都会看到它们）。
    """
    version = require_pyinstaller()
    dist_root = os.path.join(out_root, "dist")
    command = build_command(out_root, name=name, python=python)

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    proc = subprocess.run(
        command,
        cwd=out_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError("PyInstaller 构建失败（exit %d）：\n%s" % (proc.returncode, log[-4000:]))
    if not quiet:
        print(log[-2000:])
    dist_dir = os.path.join(dist_root, name)
    if not os.path.isdir(dist_dir):
        raise RuntimeError("构建报告成功但产物目录不存在：%s" % dist_dir)
    return dist_dir, "PyInstaller %s；%s" % (version, log.strip().splitlines()[-1] if log.strip() else "")


def exe_path(dist_dir, name=EXE_NAME):
    """onedir 产物的可执行文件路径（Windows 带 .exe）。"""
    candidate = os.path.join(dist_dir, name + (".exe" if os.name == "nt" else ""))
    if not os.path.isfile(candidate):
        raise RuntimeError("产物可执行文件不存在：%s" % candidate)
    return candidate


def bundle_root(dist_dir):
    """onedir 的内嵌目录（PyInstaller 6 起为 `_internal/`）。"""
    internal = os.path.join(dist_dir, "_internal")
    return internal if os.path.isdir(internal) else dist_dir


# ---------------------------------------------------------------- 对账：内嵌数据

def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def embedded_data_paths(dist_dir):
    """产物内**随包数据**的实际路径集合（仓库相对路径 → 产物绝对路径）。

    只收白名单可能落到的两个目录（`data/` 与 `<包>/benchmark/`），
    这样"包里多出别的数据文件"不会被误算进来（那是第三方包的私有文件）。
    """
    root = bundle_root(dist_dir)
    out = {}
    for rel in data_whitelist():
        tail = dest_for(rel)
        out[rel] = os.path.join(root, tail.replace("/", os.sep))
    return out


def verify_embedded_data(dist_dir):
    """双向对账 + 逐份 sha256。返回 `(ok, 明细行列表)`。

    三条判据（缺一条就是一类漏网）：
    1. **不丢**：白名单每条都在产物里（查漏拷）；
    2. **不多**：产物那两个数据目录里的文件都在白名单内（查多拷——只查漏拷的门
       对"顺手把样例集也打进去"是瞎的）；
    3. **一致**：逐份 sha256 与仓库冻结件相等（防"构建期被改写/归一化"）。
    """
    details = []
    ok = True
    expected = embedded_data_paths(dist_dir)

    for rel, abs_path in sorted(expected.items()):
        if not os.path.isfile(abs_path):
            ok = False
            details.append("缺失：%s（白名单要求在 %s）" % (rel, abs_path))
            continue
        repo_path = os.path.join(ROOT, rel.replace("/", os.sep))
        if _sha256(abs_path) != _sha256(repo_path):
            ok = False
            details.append("sha256 不一致：%s" % rel)

    # 反向：两个数据目录里不得有白名单之外的文件
    root = bundle_root(dist_dir)
    allowed_dests = {dest_for(rel) for rel in expected}
    for dest_dir in sorted({os.path.dirname(d) for d in allowed_dests}):
        abs_dir = os.path.join(root, dest_dir.replace("/", os.sep))
        if not os.path.isdir(abs_dir):
            continue
        for name in sorted(os.listdir(abs_dir)):
            candidate = os.path.join(abs_dir, name)
            if os.path.isdir(candidate):
                ok = False
                details.append("数据目录内出现子目录（白名单是平铺文件）：%s" % os.path.join(dest_dir, name))
                continue
            if (dest_dir + "/" + name) not in allowed_dests:
                ok = False
                details.append("多拷：%s（不在白名单内）" % os.path.join(dest_dir, name))

    if ok:
        details.append("内嵌数据对账通过：%d 份，逐份 sha256 与仓库冻结件一致，无多拷" % len(expected))
    return ok, details


# ---------------------------------------------------------------- 零上传可扫断言

def outbound_module_hits(module_names):
    """模块名表里的出站命中（纯函数，供产物扫描与合成夹具共用）。"""
    hits = []
    for name in sorted(set(module_names)):
        for prefix in OUTBOUND_MODULE_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                hits.append(name)
                break
    return hits


def outbound_file_hits(dist_dir):
    """产物树里的出站二进制命中（`_ssl.pyd` / `libssl*.dll` 这类 TLS 运行时）。"""
    hits = []
    for dirpath, _dirs, names in os.walk(dist_dir):
        for name in sorted(names):
            for prefix in OUTBOUND_FILE_PREFIXES:
                if name.startswith(prefix):
                    hits.append(os.path.relpath(os.path.join(dirpath, name), dist_dir).replace(os.sep, "/"))
                    break
    return hits


def socket_residue_hits(dist_dir):
    """已登记的 socket 残留**是否精确**——多出未登记的残留也要报出来。

    这条防"登记制退化成免检"：残留清单锁死后，新增的 socket 系残留（比如有人
    又把 `asyncio` 拉回来但名字不同）会在对账里现形。
    """
    root = bundle_root(dist_dir)
    modules = set(bundle_module_names(exe_path(dist_dir)))
    unexpected_modules = sorted(
        name
        for name in modules
        if name.split(".")[0] in ("socket", "selectors")
        and name not in SOCKET_RESIDUE_MODULES
    )
    files = set()
    for dirpath, _dirs, names in os.walk(dist_dir):
        for name in names:
            if name.startswith("_socket"):
                files.add(name)
    unexpected_files = sorted(name for name in files if name not in SOCKET_RESIDUE_FILES)
    return unexpected_modules, unexpected_files


def bundle_module_names(exe):
    """读 PyInstaller 归档里的**模块名表**（PYZ）。

    为什么必须读归档、不能只扫 dist 目录树：PyInstaller 6 的 onedir 把纯 Python
    模块打进 exe 内的 PYZ 归档，**目录里没有对应的 .py/.pyc 文件**。
    只扫目录树的门对"某模块被打进 PYZ"是瞎的——实测：只扫目录时 `ssl` 完全不可见。
    """
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(exe)
    names = []
    for entry in sorted(reader.toc):
        if entry.endswith(".pyz"):
            pyz = reader.open_embedded_archive(entry)
            names.extend(sorted(pyz.toc))
    return names


def scan_no_outbound(dist_dir):
    """零上传可扫断言。返回 `(ok, 明细行列表)`。"""
    details = []
    ok = True

    modules = bundle_module_names(exe_path(dist_dir))
    hits = outbound_module_hits(modules)
    if hits:
        ok = False
        details.append("产物模块表含出站组件：%s" % hits)

    file_hits = outbound_file_hits(dist_dir)
    if file_hits:
        ok = False
        details.append("产物含 TLS 运行时文件：%s" % file_hits)

    extra_modules, extra_files = socket_residue_hits(dist_dir)
    if extra_modules or extra_files:
        ok = False
        details.append(
            "socket 残留超出登记范围：模块 %s / 文件 %s（新增残留必须显式登记并同步测试）"
            % (extra_modules, extra_files)
        )

    if ok:
        details.append(
            "零上传：模块表无 TLS/出站组件；已登记残留 %s（%s）"
            % (list(SOCKET_RESIDUE_MODULES), SOCKET_RESIDUE_REASON)
        )
    return ok, details


# ---------------------------------------------------------------- 打包确定性

ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _zip_members(dist_dir):
    """dist 下全部文件，按 POSIX 相对路径**排序**（条目序确定，不靠目录遍历序）。"""
    members = []
    for dirpath, dirs, names in os.walk(dist_dir):
        dirs.sort()
        for name in sorted(names):
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, dist_dir).replace(os.sep, "/")
            members.append((rel, abs_path))
    members.sort(key=lambda item: item[0])
    return members


def pack_deterministic_zip(dist_dir, zip_path):
    """把 dist 打成 zip，**同一份 dist 两次打包逐字节一致**。

    三件事共同保证（缺一即不确定）：
    1. `ZIP_STORED`——不过 deflate，避免压缩器版本差异进入字节；
    2. 条目按相对路径排序——文件系统遍历序不参与；
    3. `date_time` 固定 + `create_system`/`external_attr` 固定——mtime 与平台属性
       不参与。

    **只承诺"同一份 dist 的打包过程确定"**：exe 本体内含构建期时间戳与 PyInstaller
    自己的元信息，**实测同机连打两次的 exe sha256 都不同**（同一命令、同一源码，
    只差输出目录：两次 `8d35d50b…` 与 `59ae0d15…`，体积却都是 2872954 字节——
    即"内容布局相同、时间戳不同"）。故 "exe 构建逐字节可复现" 这条**跨机、跨次
    都不成立**，只有"给定同一份 dist，打包出的 zip 逐字节一致"成立。
    """
    members = _zip_members(dist_dir)
    if not members:
        raise RuntimeError("dist 为空，无法打包：%s" % dist_dir)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for rel, abs_path in members:
            info = zipfile.ZipInfo(filename=rel, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            with open(abs_path, "rb") as handle:
                archive.writestr(info, handle.read())
    return zip_path


def zip_is_deterministic(dist_dir, work_dir):
    """同一份 dist 连打两次，比较 sha256。返回 `(ok, 明细行列表)`。"""
    first = pack_deterministic_zip(dist_dir, os.path.join(work_dir, "pack-first.zip"))
    second = pack_deterministic_zip(dist_dir, os.path.join(work_dir, "pack-second.zip"))
    digest_first = _sha256(first)
    digest_second = _sha256(second)
    if digest_first != digest_second:
        return False, ["两次打包不一致：%s != %s" % (digest_first, digest_second)]
    return True, ["打包确定性：同一 dist 两次打包 sha256 相同（%s）" % digest_first]


# ---------------------------------------------------------------- 真跑产物（中立目录）

def neutral_env():
    """`env -i` 等价环境：**只留 Windows 必需的系统变量**。

    为什么要清环境：本机环境里有 `CHECKUP_LEDGER_DATA` / `PYTHONPATH` / `PYTHONHOME`
    这类变量，留着就等于让产物"跑在开发机的便利环境里"——那验证不出冻结态
    自己的数据目录解析是否真的成立。Windows 上 `SYSTEMROOT` 不能清
    （少了它连 DLL 加载都失败）。
    """
    env = {}
    systemroot = os.environ.get("SYSTEMROOT")
    if systemroot:
        env["SYSTEMROOT"] = systemroot
    return env


# 实测偏差：**冻结产物不吃 `PYTHONUTF8` / `PYTHONIOENCODING`**。
#
# 两个变量都是 CPython **启动配置**项，而 PyInstaller 的引导程序自己构造
# `PyConfig` 并覆盖了这部分——实测在 `env -i` 里加哪个都不改变输出字节
# （三次构建分别试过：neutral / PYTHONUTF8=1 / PYTHONIOENCODING=utf-8，
# 输出头三个字节恒为 cp936 的 `\xb9\xe6\xd4`）。
# 产物于是**按控制台编码自适应**：管道下走 locale 编码（本机 cp936 能编中文，
# `encoding.py` 的探针按设计不改配置）；窄编码环境才 reconfigure 成 utf-8。
#
# 这是产物的**正确行为**（中文控制台不该被硬改），要改的是验证侧的读取方式：
# 不能假定 utf-8。故 `decode_output()` 先严格试 utf-8（窄编码环境下产物会
# reconfigure 成 utf-8），失败再回落到 locale 编码（能编中文的环境下产物就按
# locale 输出）。两条分支正好覆盖 `encoding.py` 探针的两种结果。
def decode_output(raw):
    """把产物输出字节解成文本（先 utf-8，失败回落 locale 编码）。"""
    if isinstance(raw, str):  # pragma: no cover - 调用方应传 bytes
        return raw
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    import locale

    for encoding in (locale.getpreferredencoding(False), "cp936"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def run_frozen_smoke(dist_dir, args, cwd=None, name=EXE_NAME, timeout=180):
    """在**中立目录**跑产物。返回 `(exit_code, stdout+stderr)`。

    中立目录（不是仓库、也不是 dist 目录）很重要：产物若偷偷依赖"从仓库 CWD
    读到相对路径的数据"，在 dist 目录里跑可能恰好成立（数据就在旁边），
    换个目录才暴露。
    """
    exe = exe_path(dist_dir, name)
    workdir = cwd or tempfile.mkdtemp(prefix="checkup-ledger-neutral-")
    proc = subprocess.run(
        [exe] + list(args),
        cwd=workdir,
        env=neutral_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return proc.returncode, decode_output(proc.stdout)


# ---------------------------------------------------------------- CLI

def _full_run(out_root, name):
    """构建 → 对账 → 零上传 → 确定性 → 真跑（一次跑齐 DoD 各条）。"""
    failures = []
    print("== 冻结构建 ==")
    dist_dir, note = build_dist(out_root, name=name)
    print("产物：%s\n%s" % (dist_dir, note))

    ok, details = verify_embedded_data(dist_dir)
    print("\n== 内嵌数据对账 ==")
    for line in details:
        print("  %s" % line)
    if not ok:
        failures.append("内嵌数据对账")

    ok, details = scan_no_outbound(dist_dir)
    print("\n== 零上传可扫断言 ==")
    for line in details:
        print("  %s" % line)
    if not ok:
        failures.append("零上传")

    work = os.path.join(out_root, "pack")
    os.makedirs(work, exist_ok=True)
    ok, details = zip_is_deterministic(dist_dir, work)
    print("\n== 打包确定性 ==")
    for line in details:
        print("  %s" % line)
    if not ok:
        failures.append("打包确定性")

    print("\n== 真跑产物（中立目录 + env -i 等价） ==")
    for args, expect in (
        (["version"], 0),
        (["selftest"], 0),
        (["bench"], 0),
        (["no-such-command"], 2),
    ):
        code, output = run_frozen_smoke(dist_dir, args)
        mark = "OK" if code == expect else "FAIL"
        print("  [%s] %s → exit %d（期望 %d）" % (mark, " ".join(args), code, expect))
        if code != expect:
            failures.append("真跑 %s" % " ".join(args))
            print(output[-1500:])

    if failures:
        print("\n冻结产物验证失败：%s" % "、".join(failures))
        return 1
    print("\n冻结产物验证通过：对账 / 零上传 / 确定性 / 真跑 四项齐备。")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="冻结构建与产物验证（M5）")
    parser.add_argument("--out", default=None, help="构建输出根目录（缺省：仓库外临时目录）")
    parser.add_argument("--name", default=EXE_NAME, help="产物名（缺省 checkup-ledger）")
    parser.add_argument("--dist", default=None, help="只验证已存在的产物目录（跳过构建）")
    parser.add_argument("--smoke", action="store_true", help="在给定 --dist 上真跑一轮")
    args = parser.parse_args(argv)

    if args.dist:
        dist_dir = os.path.abspath(args.dist)
        failures = []
        ok, details = verify_embedded_data(dist_dir)
        print("== 内嵌数据对账 ==")
        for line in details:
            print("  %s" % line)
        if not ok:
            failures.append("内嵌数据对账")
        ok, details = scan_no_outbound(dist_dir)
        print("\n== 零上传可扫断言 ==")
        for line in details:
            print("  %s" % line)
        if not ok:
            failures.append("零上传")
        if args.smoke:
            print("\n== 真跑产物（中立目录 + env -i 等价） ==")
            for cmd, expect in ((["version"], 0), (["selftest"], 0), (["no-such-command"], 2)):
                code, output = run_frozen_smoke(dist_dir, cmd, name=args.name)
                print("  [%s] %s → exit %d" % ("OK" if code == expect else "FAIL", " ".join(cmd), code))
                if code != expect:
                    failures.append("真跑 %s" % " ".join(cmd))
                    print(output[-1200:])
        return 1 if failures else 0

    out_root = os.path.abspath(args.out) if args.out else tempfile.mkdtemp(prefix="checkup-ledger-freeze-")
    os.makedirs(out_root, exist_ok=True)
    print("构建输出根：%s" % out_root)
    return _full_run(out_root, args.name)


if __name__ == "__main__":
    sys.exit(main())
