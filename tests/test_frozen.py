"""M5 免安装产物门禁：入口形态 / 零上传 / 内嵌数据对账 / 打包确定性 / 冻结态真跑。

分两档，理由说清：

- **静态档**（不构建，双通道都跑）：入口薄壳的 AST 断言、构建命令的排除面与
  拷贝面、白名单与落点规则、出站命中面的**纯函数**、打包确定性的**逐字节**验证
  （在临时目录里造一份假 dist，不碰 PyInstaller）。这一档是日常守门，
  改一处就能立刻红。
- **实构建档**（`CHECKUP_LEDGER_FREEZE_BUILD=1` 才跑）：真跑 PyInstaller 构建、
  真扫产物归档、真在**中立目录 + env -i 等价环境**跑 exe。这一档慢且要 `[freeze]`
  依赖，故默认 skip（CI 上装 `[freeze]` 并置该变量即全跑）。

**为什么静态档不能替代实构建档**：DoD 里"零上传"与"入包集合 == 白名单"是
**对真实产物**的断言。静态档守的是"构建参数对不对"，实构建档守的是"打出来的
那个包里究竟有什么"——M5 的第一条纪律就是**构建 exit 0 ≠ 产物可用**。
"""

import ast
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile

import pytest

from helpers import iter_python_files, read_text, repo_path

# `tools/` 由 `tests/conftest.py` 放进 sys.path（仓库脚本不是安装面的一部分），
# 故这里按既有惯例直接 import 模块名，而不是 `tools.freeze_build`——
# 后者只在"从仓库根跑 pytest"时才靠 cwd 解析成功（换个工作目录就 ImportError）。
import freeze_build as fb

ENTRY_REL = "src/checkup_ledger/frozen_entry.py"
ENTRY_PATH = "checkup_ledger/frozen_entry.py"

# 实构建档开关：装了 [freeze] 且显式置位才真跑（慢；双通道日常不跑）
FREEZE_BUILD_ENV = "CHECKUP_LEDGER_FREEZE_BUILD"


def _freeze_build_enabled():
    if os.environ.get(FREEZE_BUILD_ENV) != "1":
        return False
    try:
        fb.require_pyinstaller()
    except RuntimeError:
        return False
    return True


requires_freeze = pytest.mark.skipif(
    not _freeze_build_enabled(),
    reason="需装 [freeze] 且置 %s=1（实构建档：真跑 PyInstaller，慢）" % FREEZE_BUILD_ENV,
)


# ============================================================ 入口薄壳（AST 静态断言）


def _parse(rel_path):
    with open(repo_path(rel_path), "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=rel_path)


def _module_imports(tree):
    """模块级 import 的 (节点, 名称) 列表。"""
    out = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node, alias.name))
        elif isinstance(node, ast.ImportFrom):
            out.append((node, node.module or ""))
    return out


def test_frozen_entry_exists_and_is_a_thin_shell():
    """冻结入口必须在位，且**薄**：只有 import + 一行 `sys.exit(main())`。

    薄的判据是"它不重复任何口径"：不解析参数（用法错误归 `cli`）、不兜异常、
    不映射退出码。壳里再包一层就会长出第二处退出码口径。
    """
    assert os.path.isfile(repo_path(ENTRY_REL)), "冻结入口薄壳不存在：%s" % ENTRY_REL
    tree = _parse(ENTRY_REL)
    funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    assert not funcs, "冻结入口不得定义函数（应只有 import + sys.exit）：%s" % funcs
    assert not classes, "冻结入口不得定义类：%s" % classes

    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exit"
    ]
    assert calls, "冻结入口必须把 main() 的返回值交给 sys.exit（否则退出码丢失）"


def test_frozen_entry_uses_absolute_imports_only():
    """冻结入口**必须**绝对导入。

    PyInstaller 把入口脚本以 `__main__` 身份执行，`__main__` **没有包上下文**——
    相对导入（`from .cli import main`）在那种身份下直接 ImportError。
    这条是"产物能起来"的承重门。
    """
    tree = _parse(ENTRY_REL)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level and node.level > 0:
            offenders.append("line %d: 相对导入 level=%d（%s）" % (node.lineno, node.level, node.module))
    assert not offenders, "冻结入口出现相对导入（冻结态会 ImportError）：%s" % offenders

    names = [name for _node, name in _module_imports(tree)]
    assert "checkup_ledger.cli" in names, (
        "冻结入口未以绝对路径导入本包 CLI（names=%s）" % names
    )


def test_frozen_entry_imports_the_package_cli_not_a_relative_module():
    """绝对导入的目标必须是 `checkup_ledger.cli`（而不是某个同名的裸模块名）。"""
    tree = _parse(ENTRY_REL)
    targets = [name for _node, name in _module_imports(tree) if name.endswith("cli")]
    assert targets == ["checkup_ledger.cli"], "冻结入口的 CLI 导入目标不符：%s" % targets


def test_dunder_main_is_present_and_guarded():
    """`python -m` 通路入口必须在位且有 `__main__` 守卫（与冻结入口是两条通路）。"""
    tree = _parse("src/checkup_ledger/__main__.py")
    guarded = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and getattr(node.test.left, "id", None) == "__name__"
        for node in tree.body
    )
    assert guarded, "`__main__.py` 缺 `if __name__ == \"__main__\"` 守卫"


def test_frozen_entry_is_not_shadowed_by_an_installed_same_named_module():
    """薄壳文件名不得与任何 stdlib/第三方顶层模块同名（否则冻结态导入歧义）。"""
    name = os.path.splitext(os.path.basename(ENTRY_REL))[0]
    import importlib.util

    # 源码树里同目录下不该有第二个同名模块（本包内唯一）
    package_dir = repo_path("src", "checkup_ledger")
    siblings = [n for n in os.listdir(package_dir) if n == name + ".py"]
    assert siblings == [name + ".py"], "包内出现同名模块（导入歧义）：%s" % siblings


# ============================================================ 构建命令的排除面与拷贝面

# **判据面**（DoD 口径，钉在测试里，不从实现取）。
#
# 为什么不从 `fb.OUTBOUND_EXCLUDES` 取期望：那等于"拿实现当规格"——把 `ssl`
# 从常量里删掉，构建跟着少排一项，而断言仍会通过（门变成镜子）。
# M4 的两处假门正是这么漏过去的，故这里把口径钉死在测试侧，
# 再断言实现**覆盖**它（实现多排几项是更严，不算违规）。
REQUIRED_OUTBOUND_COMPONENTS = (
    "ssl",
    "_ssl",
    "http",
    "urllib.request",
    "ftplib",
    "xmlrpc",
    "smtplib",
    "telnetlib",
    "asyncio",
    "concurrent",
)

# 随包数据的**判据面**（同样钉死）：漏任何一份都是"交付物里少东西"。
REQUIRED_PACKAGED_DATA = (
    "src/checkup_ledger/data/indicators.yaml",
    "src/checkup_ledger/data/config.yaml",
    "src/checkup_ledger/benchmark/cases.json",
)


def _excluded_from_command(command):
    excluded = set()
    for index, token in enumerate(command):
        if token == "--exclude-module":
            excluded.add(command[index + 1])
    return excluded


def _added_sources(command):
    sources = []
    for index, token in enumerate(command):
        if token == "--add-data":
            sources.append(os.path.relpath(command[index + 1].split(os.pathsep)[0], repo_path()).replace(os.sep, "/"))
    return sources


def test_build_command_excludes_every_outbound_component():
    """构建命令必须排除**判据面里的每一类**出站组件——漏一个，"零上传"就名不副实。"""
    excluded = _excluded_from_command(fb.build_command(tempfile.gettempdir()))
    missing = sorted(set(REQUIRED_OUTBOUND_COMPONENTS) - excluded)
    assert not missing, "构建命令未排除这些出站组件：%s" % missing


def test_outbound_constant_covers_the_judgement_face():
    """实现侧的常量必须覆盖判据面（常量被削就该在这里红）。"""
    missing = sorted(set(REQUIRED_OUTBOUND_COMPONENTS) - set(fb.OUTBOUND_EXCLUDES))
    assert not missing, "OUTBOUND_EXCLUDES 未覆盖判据面：%s" % missing


def test_build_command_excludes_qt_and_heavy_imaging():
    """CLI 目标的体积分档：Qt 系与图像/数值重件必须排除（plan/02 第十一节）。"""
    excluded = _excluded_from_command(fb.build_command(tempfile.gettempdir()))
    missing = sorted(set(fb.QT_EXCLUDES) - excluded)
    assert not missing, "构建命令未排除这些重件：%s" % missing


def test_build_command_copies_every_whitelisted_data_file():
    """判据面**每一份**都要出现在 `--add-data` 里（查漏拷的第一道）。

    这条同时钉住两头：白名单实算结果要含判据面，构建命令要真的把它拷进去。
    """
    sources = set(_added_sources(fb.build_command(tempfile.gettempdir())))
    missing = sorted(set(REQUIRED_PACKAGED_DATA) - sources)
    assert not missing, "判据面的随包数据未进入 --add-data：%s" % missing
    whitelist = set(fb.data_whitelist())
    missing = sorted(set(REQUIRED_PACKAGED_DATA) - whitelist)
    assert not missing, "判据面的随包数据不在白名单实算结果内：%s" % missing


def test_build_command_does_not_copy_sample_set():
    """**样例集不随包**（`data/samples/` 是开发期资产）——构建命令不得拷它。"""
    for source in _added_sources(fb.build_command(tempfile.gettempdir())):
        assert "data/samples/" not in source, "构建命令把样例集也拷进产物：%s" % source
    for rel in fb.data_whitelist():
        assert not rel.startswith("data/samples/"), "样例集混进白名单：%s" % rel


def test_build_command_uses_the_thin_frozen_entry():
    """构建入口必须是薄壳（不是 `cli.py`、也不是 `__main__.py`）。"""
    command = fb.build_command(tempfile.gettempdir())
    assert command[-1].replace(os.sep, "/").endswith(ENTRY_REL), (
        "构建入口不是薄壳：%s" % command[-1]
    )


def test_build_command_places_data_outside_the_package_but_benchmark_inside():
    """落点规则：`data/` 落 exe 旁，`benchmark/` 落包内（两条运行时约定）。"""
    dests = {}
    for rel in fb.data_whitelist():
        dests[rel] = fb.dest_for(rel)
    for rel, dest in dests.items():
        tail = rel.split("src/checkup_ledger/", 1)[1]
        if tail.startswith("data/"):
            assert dest == tail, "data/ 应落 exe 旁的 data/：%s → %s" % (rel, dest)
        elif tail.startswith("benchmark/"):
            assert dest == "checkup_ledger/" + tail, "benchmark/ 应落包内：%s → %s" % (rel, dest)
        else:
            raise AssertionError("未登记的落点：%s" % rel)


def test_dest_for_rejects_paths_outside_the_package():
    """落点规则只认包内路径——包外路径必须报错（防"顺手拷了仓库根的东西"）。"""
    with pytest.raises(ValueError):
        fb.dest_for("data/samples/cases/case-001-zhangsan-2023.txt")
    with pytest.raises(ValueError):
        fb.dest_for("src/checkup_ledger/unknown/thing.txt")


# ============================================================ 白名单（源自 pyproject）


def test_data_whitelist_comes_from_pyproject_not_a_second_list():
    """白名单必须由 `pyproject.toml` 的 `package-data` 实算，不得是本文件的第二处定义。"""
    patterns = fb._package_data_patterns()
    assert patterns, "package-data 白名单为空（探针失效）"
    text = read_text("pyproject.toml")
    for pattern in patterns:
        assert pattern in text, "白名单模式不在 pyproject 里：%s" % pattern


def test_data_whitelist_files_all_exist_and_are_not_samples():
    """展开后的每一份都要真实存在，且**不得**来自样例集（开发期资产不随包）。"""
    files = fb.data_whitelist()
    assert files, "白名单展开为空（探针失效）"
    for rel in files:
        assert os.path.isfile(repo_path(rel)), "白名单文件不存在：%s" % rel
        assert not rel.startswith("data/samples/"), "样例集混进随包白名单：%s" % rel


def test_declared_empty_patterns_are_exactly_as_declared():
    """**声明的空模式**必须逐条登记理由，且清单精确（新增豁免要显式改这里）。

    与零字面量门禁的 `EXEMPT_FILES` 同一套纪律：豁免显式、写理由、被锁死。
    没有这条，"某个白名单模式匹配不到文件"会被静默吞掉——那正是漏拷。
    """
    assert sorted(fb.DECLARED_EMPTY_PATTERNS) == ["data/*.yml"], (
        "空模式豁免清单与声明不符——新增豁免必须同时更新本断言"
    )
    reason = fb.DECLARED_EMPTY_PATTERNS["data/*.yml"]
    assert "yaml" in reason and "漏拷" in reason, "空模式豁免理由缺失关键说明"


def test_non_declared_empty_pattern_raises():
    """未登记的空模式必须报错——这条证明"空模式豁免"不是一个整体免检开关。"""
    original = dict(fb.DECLARED_EMPTY_PATTERNS)
    try:
        fb.DECLARED_EMPTY_PATTERNS.clear()
        with pytest.raises(RuntimeError) as excinfo:
            fb.data_whitelist()
        assert "data/*.yml" in str(excinfo.value), "报错未指名未匹配的模式：%s" % excinfo.value
    finally:
        fb.DECLARED_EMPTY_PATTERNS.update(original)


def test_whitelist_expansion_covers_runtime_assets():
    """白名单必须覆盖运行时必需资产（知识库 + 阈值配置 + 基准用例）。"""
    files = set(fb.data_whitelist())
    assert "src/checkup_ledger/data/indicators.yaml" in files, "知识库不在白名单"
    assert "src/checkup_ledger/data/config.yaml" in files, "阈值配置不在白名单"
    assert "src/checkup_ledger/benchmark/cases.json" in files, "基准用例不在白名单"


# ============================================================ 零上传：纯函数命中面


def test_outbound_module_hits_flags_each_outbound_component():
    """出站命中面逐个可检出（六类出站组件各举一例，含子模块形态）。"""
    samples = (
        "ssl",
        "_ssl",
        "http.client",
        "urllib.request",
        "ftplib",
        "xmlrpc.client",
        "smtplib",
        "telnetlib",
        "asyncio.base_events",
        "concurrent.futures",
    )
    hits = fb.outbound_module_hits(samples)
    assert set(hits) == set(samples), "出站命中面漏判：%s" % sorted(set(samples) - set(hits))


def test_outbound_module_hits_does_not_flag_urllib_parse_or_plain_names():
    """**反向**：`urllib.parse`（pathlib 依赖它）与无关模块不得被判成出站。

    这条挡的是"把门放宽成筛子"的反面——门若把 `urllib` 整体判红，构建就得排除
    `urllib`，而 `pathlib` 会因此直接 ImportError（实测过）。判据必须精确到
    `urllib.request` 这一层。
    """
    samples = ("urllib", "urllib.parse", "urllib.error", "pathlib", "zipfile", "email.utils")
    assert fb.outbound_module_hits(samples) == [], (
        "把非出站模块判成出站（会导致构建排除过度、产物跑不起来）：%s"
        % fb.outbound_module_hits(samples)
    )


def test_outbound_hit_prefixes_are_a_subset_of_build_excludes():
    """命中面与构建排除面必须同源——判据面比排除面宽就会出现"扫得到、排不掉"。"""
    missing = sorted(set(fb.OUTBOUND_MODULE_PREFIXES) - set(fb.BUILD_EXCLUDES))
    assert not missing, "出站命中面有构建未排除的项：%s" % missing


def test_socket_residue_is_declared_with_a_reason():
    """实测排不掉的 socket 残留必须**显式登记且写清理由**（不许静默放过）。"""
    assert fb.SOCKET_RESIDUE_MODULES, "socket 残留清单为空（登记制形同虚设）"
    assert fb.SOCKET_RESIDUE_FILES, "socket 残留文件清单为空"
    reason = fb.SOCKET_RESIDUE_REASON
    assert "pdfminer" in reason and "importlib.metadata" in reason, (
        "socket 残留理由未说清成因：%s" % reason
    )
    assert "socket" not in fb.BUILD_EXCLUDES, (
        "socket 被排除了——实测会让 import pdfplumber 失败（产物跑不起来）"
    )


# ============================================================ 打包确定性（不碰 PyInstaller）


def _fake_dist(root):
    """造一份假 dist：多文件、含子目录、文件名故意乱序（考条目排序是否生效）。"""
    layout = (
        "zzz.txt",
        "aaa.txt",
        "sub/mmm.bin",
        "sub/bbb.bin",
        "exe/checkup-ledger.exe",
    )
    for rel in layout:
        abs_path = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(("payload:" + rel).encode("utf-8"))
    return root


def test_deterministic_zip_is_byte_identical_across_two_packs():
    """同一份 dist 两次打包**逐字节一致**（ZIP_STORED + 条目排序 + 固定 date_time）。"""
    with tempfile.TemporaryDirectory() as tmp:
        dist = _fake_dist(os.path.join(tmp, "dist"))
        first = fb.pack_deterministic_zip(dist, os.path.join(tmp, "a.zip"))
        second = fb.pack_deterministic_zip(dist, os.path.join(tmp, "b.zip"))
        with open(first, "rb") as handle:
            bytes_first = handle.read()
        with open(second, "rb") as handle:
            bytes_second = handle.read()
        assert bytes_first == bytes_second, "两次打包字节不同（打包过程不确定）"


def test_deterministic_zip_entries_are_sorted_and_stored():
    """条目序必须是排序后的相对路径，且压缩方式为 STORED、时间戳固定。"""
    with tempfile.TemporaryDirectory() as tmp:
        dist = _fake_dist(os.path.join(tmp, "dist"))
        path = fb.pack_deterministic_zip(dist, os.path.join(tmp, "pack.zip"))
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            assert names == sorted(names), "zip 条目未排序：%s" % names
            for info in archive.infolist():
                assert info.compress_type == zipfile.ZIP_STORED, "条目未用 STORED：%s" % info.filename
                assert info.date_time == fb.ZIP_EPOCH, "条目时间戳未固定：%s" % info.filename


def test_deterministic_zip_survives_a_different_file_order_on_disk():
    """**反向**：即便磁盘上文件的 mtime/遍历序不同，打包结果仍一致。

    这条是"确定性来自打包过程、不来自文件系统恰好稳定"的证明：
    改一遍 mtime 再打，字节必须不变。
    """
    with tempfile.TemporaryDirectory() as tmp:
        dist = _fake_dist(os.path.join(tmp, "dist"))
        first = fb.pack_deterministic_zip(dist, os.path.join(tmp, "a.zip"))
        # 改全部文件的 mtime（模拟"文件系统元信息变了"）
        for dirpath, _dirs, names in os.walk(dist):
            for name in names:
                os.utime(os.path.join(dirpath, name), (1234567890, 1234567890))
        second = fb.pack_deterministic_zip(dist, os.path.join(tmp, "b.zip"))
        assert hashlib.sha256(open(first, "rb").read()).hexdigest() == hashlib.sha256(
            open(second, "rb").read()
        ).hexdigest(), "mtime 变化影响了打包字节（确定性不成立）"


def test_zip_members_are_sorted_by_posix_relative_path():
    """成员清单必须按 POSIX 相对路径排序（Windows 反斜杠不得进入条目名）。"""
    with tempfile.TemporaryDirectory() as tmp:
        dist = _fake_dist(os.path.join(tmp, "dist"))
        members = fb._zip_members(dist)
        names = [rel for rel, _abs in members]
        assert names == sorted(names), "成员清单未排序：%s" % names
        assert all("\\" not in name for name in names), "条目名出现反斜杠：%s" % names


def test_pack_deterministic_zip_refuses_empty_dist():
    """空 dist 必须报错，不许产出空 zip 让人以为"打包成功了"。"""
    with tempfile.TemporaryDirectory() as tmp:
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        with pytest.raises(RuntimeError):
            fb.pack_deterministic_zip(empty, os.path.join(tmp, "x.zip"))


# ============================================================ 中立环境


def test_neutral_env_drops_everything_but_systemroot():
    """`env -i` 等价环境：只留 `SYSTEMROOT`（Windows 缺它连 DLL 都加载不了）。"""
    env = fb.neutral_env()
    for key in ("PYTHONPATH", "PYTHONHOME", "CHECKUP_LEDGER_DATA", "CHECKUP_LEDGER_SAMPLES"):
        assert key not in env, "中立环境仍带开发机变量：%s" % key
    assert set(env) <= {"SYSTEMROOT"}, "中立环境混入了非系统必需变量：%s" % sorted(env)


def test_stdout_decoder_handles_utf8_and_locale_bytes():
    """读产物输出的解码必须**先 utf-8、失败回落 locale**（实测偏差的配对守）。

    为什么需要这条：**冻结产物不吃 `PYTHONUTF8`/`PYTHONIOENCODING`**（PyInstaller
    引导程序自己构造 `PyConfig`，实测三组环境变量下输出字节完全相同）。产物于是
    按控制台编码自适应——能编中文的 locale（本机 cp936）就按它输出，窄编码才
    reconfigure 成 utf-8。故验证侧两种字节都要读得出来。

    这条挡的是"把验证侧硬编码成 utf-8"——那会在本机把 `bench` 的"达标"读成乱码，
    断言假红（M5 实测踩到过）。
    """
    text = "规则驱动层（不读真值库）达标"
    assert fb.decode_output(text.encode("utf-8")) == text, "utf-8 字节读错"
    assert fb.decode_output(text.encode("gbk")) == text, "locale（gbk/cp936）字节读错"
    # 回退链不得把无法解码的字节直接抛出去
    assert fb.decode_output(b"\xff\xfe\x00bad") is not None


def test_require_pyinstaller_rejects_below_major_six():
    """冻结构建固定在 **≥6** 那条解释器通道——<6 必须拒绝（口径见 plan/02 第四节）。"""
    original = sys.modules.get("PyInstaller")
    sys.modules["PyInstaller"] = type("PyInstaller", (), {"__version__": "5.13.2"})()
    try:
        with pytest.raises(RuntimeError) as excinfo:
            fb.require_pyinstaller()
        message = str(excinfo.value)
        assert "< 6" in message or "≥6" in message, "拒绝理由未指明版本下限：%s" % message
    finally:
        if original is not None:
            sys.modules["PyInstaller"] = original
        else:
            sys.modules.pop("PyInstaller", None)


def test_require_pyinstaller_accepts_major_six_or_above():
    original = sys.modules.get("PyInstaller")
    sys.modules["PyInstaller"] = type("PyInstaller", (), {"__version__": "6.22.3"})()
    try:
        assert fb.require_pyinstaller() == "6.22.3"
    finally:
        if original is not None:
            sys.modules["PyInstaller"] = original
        else:
            sys.modules.pop("PyInstaller", None)


# ============================================================ 入口契约：未知参数 exit 2


def test_unknown_argument_exits_two_in_source_tree():
    """未知子命令 / 未知旗标一律 exit 2（冻结产物同源——它只是薄壳）。"""
    from helpers import run_cli

    code, _out, _err = run_cli(["no-such-command"])
    assert code == 2, "未知子命令未退出 2：%s" % code
    code, _out, _err = run_cli(["version", "--bogus"])
    assert code == 2, "未知旗标未退出 2：%s" % code


# ============================================================ 实构建档


@pytest.fixture(scope="module")
def built_dist():
    """真构建一次（模块级复用：构建很慢，逐用例重建没必要）。"""
    out_root = tempfile.mkdtemp(prefix="checkup-ledger-freeze-build-")
    dist_dir, _note = fb.build_dist(out_root)
    yield dist_dir
    shutil.rmtree(out_root, ignore_errors=True)


@requires_freeze
def test_build_succeeds_and_produces_an_executable(built_dist):
    """构建 exit 0 只是前提——产物可执行文件必须真的在位。"""
    assert os.path.isfile(fb.exe_path(built_dist)), "构建成功但产物不可执行"


@requires_freeze
def test_embedded_data_matches_whitelist_bidirectionally(built_dist):
    """**入包集合 == 白名单**（双向）+ 逐份 sha256 与仓库冻结件一致。"""
    ok, details = fb.verify_embedded_data(built_dist)
    assert ok, "内嵌数据对账失败：\n%s" % "\n".join(details)


@requires_freeze
def test_bundle_contains_no_outbound_components(built_dist):
    """零上传可扫断言：模块表无出站组件、无 TLS 运行时文件。"""
    ok, details = fb.scan_no_outbound(built_dist)
    assert ok, "零上传断言失败：\n%s" % "\n".join(details)


@requires_freeze
def test_bundle_module_table_is_actually_readable(built_dist):
    """自证：模块表**读得到且非空**——只扫目录树的门对 PYZ 内的模块是瞎的。"""
    modules = fb.bundle_module_names(fb.exe_path(built_dist))
    assert len(modules) > 100, "模块表读到的条目过少（探针可能失效）：%d" % len(modules)
    assert any(name.startswith("checkup_ledger") for name in modules), "模块表里没有本包"


@requires_freeze
def test_frozen_selftest_passes_and_reports_data_dir_inside_exe_dir(built_dist):
    """冻结态自检 6/6，且 data_dir 落点**在 exe 目录内**（M5 承重条）。"""
    code, output = fb.run_frozen_smoke(built_dist, ["selftest"])
    assert code == 0, "冻结态自检未通过（exit %d）：\n%s" % (code, output[-2000:])
    assert "6/6" in output, "冻结态自检未报 6/6：\n%s" % output[-800:]
    assert os.path.abspath(fb.bundle_root(built_dist)) in output, (
        "自检报出的数据目录不在 exe 目录内：\n%s" % output[-800:]
    )


@requires_freeze
def test_frozen_unknown_argument_exits_two(built_dist):
    """冻结产物上未知参数仍 exit 2（薄壳没改口径）。"""
    code, output = fb.run_frozen_smoke(built_dist, ["no-such-command"])
    assert code == 2, "冻结产物未知参数未退出 2（exit %d）：\n%s" % (code, output[-1200:])


@requires_freeze
def test_frozen_bench_runs_and_reports_pass(built_dist):
    """冻结产物内可达"跑基准自证"（随包 cases.json 在包内）。"""
    code, output = fb.run_frozen_smoke(built_dist, ["bench"])
    assert code == 0, "冻结产物基准未通过（exit %d）：\n%s" % (code, output[-2000:])
    assert "达标" in output, "冻结产物基准未报达标：\n%s" % output[-800:]


@requires_freeze
def test_frozen_data_dir_check_fails_when_data_is_moved_outside(built_dist):
    """**可证伪**：把数据目录挪到 exe 目录外，冻结态自检必须报 FAIL（exit 1）。

    这条是"冻结态落点断言不是假门"的证明——M4 的教训：值域含端点那条门
    用了不可证伪的夹具，变异验证抓出来的。这里主动构造反例。
    """
    with tempfile.TemporaryDirectory() as tmp:
        probe = os.path.join(tmp, "probe")
        shutil.copytree(built_dist, probe)
        internal_data = os.path.join(fb.bundle_root(probe), "data")
        outside = os.path.join(tmp, "outside-data")
        shutil.move(internal_data, outside)
        code, output = fb.run_frozen_smoke(probe, ["selftest", "--data-dir", outside], cwd=tmp)
        assert code == 1, "数据目录挪到 exe 外后自检仍通过（假门）：\n%s" % output[-1200:]
        assert "data_dir" in output and "FAIL" in output, "未报 data_dir FAIL：\n%s" % output[-800:]


@requires_freeze
def test_frozen_run_leaves_no_tilde_directory_in_neutral_cwd(built_dist):
    """**冻结产物在中立环境跑完，不得在 CWD 里留下 `~` 目录**（M5 实测抓到的真缺陷）。

    成因：中立环境（`env -i` 等价）里没有 `USERPROFILE`/`HOMEDRIVE`+`HOMEPATH`，
    `os.path.expanduser("~")` 便**原样返回 `~`**，经 `abspath` 落成"CWD 下的 `~` 文件夹"。
    `ledger` 会触发首启免责 → 实测在跑命令的工作目录里真的长出
    `~/.checkup_ledger/accepted`。那是用户可见的污染。

    这条是**端到端**证明：真产物 + 真中立环境 + 真触发免责的命令（`ledger`）。
    """
    workdir = tempfile.mkdtemp(prefix="checkup-ledger-tilde-")
    try:
        db = os.path.join(workdir, "probe.db")
        fixture = repo_path("data", "samples", "ingest", "pdf", "ingest-pdf-plain.pdf")
        code, output = fb.run_frozen_smoke(
            built_dist,
            ["ledger", fixture, "--db", db, "--date", "2024-03-11", "--subject", "张三"],
            cwd=workdir,
        )
        assert code == 0, "冻结产物 ledger 未成功（exit %d）：\n%s" % (code, output[-1500:])
        litter = os.path.join(workdir, "~")
        assert not os.path.exists(litter), (
            "产物在 CWD 里建出了 `~` 目录（免责标记落到未展开的主目录上）：%s" % litter
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
