"""分层纪律与零外链：把"渲染层零判定""判定层纯函数"从口号变成静态断言。

两条门（都做 AST 静态分析，不靠"我读过代码"）：
1. **判定内核无 I/O**：`engine/compare.py` 不得 import 文件/网络/时间/随机模块；
2. **渲染层零判定**：`report/html.py` 不得出现算术/比较运算（`BinOp`/`Compare`），
   也不得出现区间数值字面量——界面只消费既有结论、不重算任何判定。
3. **零外链常驻**：渲染出口必须调用断言（不是"测试里验一次"）。
"""

import ast
import os

import pytest

from helpers import iter_python_files, read_text, repo_path

FORBIDDEN_IO_MODULES = (
    "io", "os", "pathlib", "glob", "shutil", "socket", "urllib", "http",
    "requests", "urllib3", "subprocess", "tempfile", "time", "datetime",
    "random", "secrets", "uuid", "sqlite3",
)

RENDERER_PATH = "src/checkup_ledger/report/html.py"
ENGINE_PATH = "src/checkup_ledger/engine/compare.py"


def _parse(rel_path):
    with open(repo_path(rel_path), "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=rel_path)


def _module_level_imports(tree):
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


# ---------------------------------------------------------------- 判定内核纯函数


def test_engine_has_no_io_module_level_imports():
    tree = _parse(ENGINE_PATH)
    imported = [name.split(".")[0] for name in _module_level_imports(tree)]
    offenders = [name for name in imported if name in FORBIDDEN_IO_MODULES]
    assert not offenders, "判定内核 import 了 I/O 类模块（应为纯函数）：%s" % offenders


def test_engine_has_no_function_level_io_imports():
    """函数体内 import 同样破坏纯度——分层越严，边界越靠后越易漏。"""
    tree = _parse(ENGINE_PATH)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IO_MODULES:
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in FORBIDDEN_IO_MODULES:
                offenders.append(node.module)
    assert not offenders, "判定内核存在 I/O 类 import：%s" % offenders


def test_engine_has_no_clock_or_random_calls():
    tree = _parse(ENGINE_PATH)
    banned = {"now", "today", "utcnow", "time", "random", "randint", "choice", "uuid4"}
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in banned:
                offenders.append(name)
    assert not offenders, "判定内核调用了时钟/随机函数：%s" % offenders


def test_engine_has_no_embedded_range_numbers():
    """判定内核不得出现区间数值——它们只能来自知识库（零字面量门禁）。

    豁免：0/1/2 这类结构常数与精度约定（口径写死在 plan/04 第二节）。
    """
    tree = _parse(ENGINE_PATH)
    exempt = {0, 1, 2, -1}
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            if node.value not in exempt:
                offenders.append("%s (line %d)" % (node.value, node.lineno))
    assert not offenders, "判定内核出现区间数值字面量：%s" % offenders


def _docstring_nodes(tree):
    """模块/类/函数的 docstring 节点（这些是**开发者文档**，不是产物文案）。"""
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                nodes.add(id(body[0].value))
    return nodes


def test_engine_emits_no_interpretive_language():
    """判定层不得**输出**解读性措辞（建议/注意/可能/风险/诊断）。

    扫描面 = 非 docstring 的字符串字面量（真正的产物文案）。docstring 与注释里的
    "不产出建议/注意类文字"是**纪律声明**，把它当命中会让门自相矛盾（假门）。
    """
    tree = _parse(ENGINE_PATH)
    docstrings = _docstring_nodes(tree)
    banned = ("\u5efa\u8bae", "\u6ce8\u610f", "\u53ef\u80fd", "\u98ce\u9669", "\u8bca\u65ad", "\u63a8\u8350")
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            for word in banned:
                if word in node.value:
                    offenders.append("line %d: %r" % (node.lineno, word))
    assert not offenders, "判定内核的产物文案出现解读性措辞：%s" % offenders


# ---------------------------------------------------------------- 渲染层零判定


def test_renderer_has_no_arithmetic():
    """渲染层不得做算术——它只消费既有结论（拼接/格式化除外）。

    注意：`x is None` 这类**身份判断**不算判定（空值展示是展示层本职），
    大小比较由下一条测试按运算符类型单独守——两条合起来才是"零判定"。
    """
    tree = _parse(RENDERER_PATH)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and not isinstance(node.op, (ast.Mod, ast.Add)):
            offenders.append("BinOp %s @ line %d" % (type(node.op).__name__, node.lineno))
    assert not offenders, "渲染层出现算术运算（应为纯展示）：%s" % offenders


def test_renderer_has_no_range_comparisons_via_operators():
    """渲染层不得用 < > <= >= 做区间判断（即便藏在表达式里）。"""
    tree = _parse(RENDERER_PATH)
    banned_ops = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if isinstance(op, banned_ops):
                    offenders.append("line %d (%s)" % (node.lineno, type(op).__name__))
    assert not offenders, "渲染层做了大小比较（等于重算判定）：%s" % offenders


def test_renderer_does_not_import_engine():
    """渲染层不得 import 判定内核——那会让"零判定"的边界形同虚设。"""
    tree = _parse(RENDERER_PATH)
    offenders = [name for name in _module_level_imports(tree) if "engine" in name]
    assert not offenders, "渲染层 import 了判定内核：%s" % offenders


def test_renderer_calls_external_resource_guard_always():
    """零外链断言必须是**出口的常驻行为**，不是只在测试里验一次。"""
    source = read_text(RENDERER_PATH)
    assert "assert_no_external_resources" in source, "渲染出口未调用零外链断言"
    tree = _parse(RENDERER_PATH)
    called = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "assert_no_external_resources":
                called = True
    assert called, "零外链断言只被 import 而未被调用（假门）"


# ---------------------------------------------------------------- 零外链守卫本体


def test_guard_detects_all_common_external_forms():
    from checkup_ledger.report.guard import find_external_resources

    sep = ":" + "/" + "/"
    samples = [
        '<link href="ht' + 'tps' + sep + 'a.example.com/x.css">',
        '<img src="ht' + 'tp' + sep + 'a.example.com/x.png">',
        '<script src="' + '/' + '/cdn.example.com/x.js"></script>',
        '<style>body{background:url(ht' + 'tps' + sep + 'a.example.com/bg.png)}</style>',
        '<form action="ht' + 'tps' + sep + 'a.example.com/post">',
        '<video poster="ht' + 'tps' + sep + 'a.example.com/p.jpg"></video>',
    ]
    for sample in samples:
        assert find_external_resources(sample), "外链形态未被识别：%s" % sample


def test_guard_allows_local_and_inline_forms():
    from checkup_ledger.report.guard import find_external_resources

    samples = [
        '<a href="#section">x</a>',
        '<img src="./local.png">',
        '<img src="data:image/png;base64,AAAA">',
        '<style>body{font-family:serif}</style>',
        "<!-- ht" + "tps" + ":" + "/" + "/comment.example.com is inside a comment -->",
    ]
    for sample in samples:
        assert not find_external_resources(sample), "本地/内联形态被误判为外链：%s" % sample


def test_guard_raises_on_external_resource():
    from checkup_ledger.report.guard import ExternalResourceError, assert_no_external_resources

    bad = '<link href="ht' + 'tps:' + '/' + '/x.example.com/a.css">'
    with pytest.raises(ExternalResourceError):
        assert_no_external_resources(bad)


def test_guard_source_itself_has_no_scheme_literal():
    """扫描器源码不得出现完整 scheme 词面——否则"扫外链"的门自己就是命中源。"""
    source = read_text("src/checkup_ledger/report/guard.py")
    for scheme in ("http", "https", "ftp", "ws", "wss"):
        assert (scheme + ":" + "/" + "/") not in source, "守卫源码出现完整 scheme：%s" % scheme


def test_rendered_report_has_no_external_reference():
    """端到端：渲染出的报告整份过零外链守卫。"""
    from checkup_ledger.model import FLAG_NORMAL, BOUNDS_CLOSED, Judged, Measurement, RANGE_SOURCE_BUILTIN, RefRange
    from checkup_ledger.report.guard import find_external_resources
    from checkup_ledger.report.html import render_measurements

    judged = [
        Judged(
            measurement=Measurement(canonical_name="ALT", raw_name="ALT", value=25.0, unit="U/L"),
            flag=FLAG_NORMAL,
            range_used=RefRange(low=9, high=40, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_BUILTIN),
            range_source=RANGE_SOURCE_BUILTIN,
        )
    ]
    document = render_measurements(judged, subject="\u5f20\u4e09")
    assert find_external_resources(document) == []


# ---------------------------------------------------------------- 序列化单点


def test_json_dump_only_in_serialize_module():
    """写盘单点：`json.dump(s)` 只准出现在 serialize 模块（防各子命令各写各的）。"""
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith("src/") or rel.endswith("serialize.py"):
            continue
        source = read_text(rel)
        tree = ast.parse(source, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in ("dump", "dumps") and isinstance(func, ast.Attribute) \
                        and getattr(func.value, "id", None) == "json":
                    offenders.append("%s:%d" % (rel, node.lineno))
    assert not offenders, "json.dump(s) 出现在 serialize 之外（写盘不单点）：%s" % offenders
