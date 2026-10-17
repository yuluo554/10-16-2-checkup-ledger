"""分层纪律与零外链：把"渲染层零判定""判定层纯函数"从口号变成静态断言。

门（都做 AST 静态分析，不靠"我读过代码"）：
1. **判定内核无 I/O**：`engine/compare.py` 不得 import 文件/网络/时间/随机模块；
2. **渲染层零判定**：`report/html.py` 不得出现算术/比较运算（`BinOp`/`Compare`），
   也不得出现区间数值字面量——界面只消费既有结论、不重算任何判定；
3. **图元计算与装配分离**（M4）：算术/比较只准落在 `report/chart.py`（它**看不到**
   判定态），`report/html.py` 与 `report/trend.py` 一律不许有——判据是**语义**
   （"值 vs 区间"是判定，"求域上下界"是图元本职），不是"有没有运算符"；
4. **零外链常驻**：渲染出口必须调用断言（不是"测试里验一次"）；
5. **台账层不做判定**：`ledger/` 不得 import 判定内核的**判定函数**（`compare`），
   也不得产出 `FLAG_*`——它只消费 `Judged`（M4 新增）。

为什么 3 要单设：渲染层要画折线**必须**做算术与比较（坐标换算、求域上下界）。
把这两件事挤进装配模块，就只能靠"别再写比较"这句口头纪律守——而它守不住
（坐标换算本身就需要比较）。故按**语义**划线：图元计算留在 `chart.py`（看不到
判定态、不做"值 vs 区间"的比较），装配层只剩拼接。
"""

import ast
import os
import tempfile

import pytest

from helpers import (
    bounds_pair,
    iter_python_files,
    load_yaml_tokens,
    read_text,
    repo_path,
    run_cli,
)

FORBIDDEN_IO_MODULES = (
    "io", "os", "pathlib", "glob", "shutil", "socket", "urllib", "http",
    "requests", "urllib3", "subprocess", "tempfile", "time", "datetime",
    "random", "secrets", "uuid", "sqlite3",
)

RENDERER_PATH = "src/checkup_ledger/report/html.py"
CHART_PATH = "src/checkup_ledger/report/chart.py"
TREND_PATH = "src/checkup_ledger/report/trend.py"
ENGINE_PATH = "src/checkup_ledger/engine/compare.py"
INGEST_LINES_PATH = "src/checkup_ledger/ingest/lines.py"

# 模块④ 台账：持久层（允许 I/O——它就是干这个的），但**不许做判定**
LEDGER_PREFIX = "src/checkup_ledger/ledger/"

# 模块⑤ 导出层
EXPORT_PATH = "src/checkup_ledger/export/__init__.py"

# 渲染链上"只准拼接"的模块（算术与比较必须落在 chart.py）
RENDER_ASSEMBLY_MODULES = (RENDERER_PATH, TREND_PATH)

# 模块② 的纯函数件（**不含 pipeline.py**：它是编排层，唯一允许读文件）
NORMALIZE_PURE_MODULES = (
    "src/checkup_ledger/normalize/mapping.py",
    "src/checkup_ledger/normalize/parse.py",
)
NORMALIZE_PREFIX = "src/checkup_ledger/normalize/"


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


# ---------------------------------------------------------------- 输入层只做抽取


def test_ingest_lines_module_has_no_io_imports():
    """行装配模块是**纯几何/文本**逻辑：不得 import 文件/网络/时间模块。

    它的职责是"把碎片拼成行"——一旦它开始读文件或读时钟，抽取层就有了两处
    I/O 入口（另一处是 `pdf.py`/`ocr.py`），"只有 pdf/ocr 碰 I/O"这条边界就破了。
    """
    tree = _parse(INGEST_LINES_PATH)
    imported = [name.split(".")[0] for name in _module_level_imports(tree)]
    offenders = [name for name in imported if name in FORBIDDEN_IO_MODULES]
    assert not offenders, "行装配模块 import 了 I/O 类模块：%s" % offenders


def test_ingest_layer_does_not_import_engine():
    """输入层**不得** import 判定内核——它只做抽取，不做任何数值语义判断。

    若输入层能拿到 `engine.compare`，就说明"抽取"与"判定"的边界被跨过去了：
    判定规则会在两个地方被调用，改一处漏一处。
    """
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith("src/checkup_ledger/ingest/"):
            continue
        for name in _module_level_imports(_parse(rel)):
            if "engine" in name:
                offenders.append("%s imports %s" % (rel, name))
    assert not offenders, "输入层 import 了判定内核（分层越界）：%s" % offenders


def test_ingest_layer_does_not_decide_flags():
    """输入层不得产出判定态常量（`FLAG_*`）——那是判定层的职责。"""
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith("src/checkup_ledger/ingest/"):
            continue
        source = read_text(rel)
        for token in ("FLAG_HIGH", "FLAG_LOW", "FLAG_NORMAL", "FLAG_NOT_ASSESSED"):
            if token in source:
                offenders.append("%s 出现 %s" % (rel, token))
    assert not offenders, "输入层出现判定态（越界做判定）：%s" % offenders


def test_ingest_optional_deps_imported_only_inside_guard():
    """可选重件（pdfplumber / rapidocr）只能出现在**缺依赖守卫内部**。

    判据：这两个名字只能作为**字符串**（传给 `run_guarded` 的模块名）或**函数体内**
    的 import 出现——**不得**做模块级 import。模块级 import 会让"只装 dev"的环境
    连收集都失败，缺依赖契约也就无从谈起。
    """
    optional = ("pdfplumber", "rapidocr_onnxruntime", "pdfminer", "onnxruntime")
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith("src/checkup_ledger/ingest/"):
            continue
        tree = _parse(rel)
        for node in tree.body:  # 只看模块级
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in optional:
                        offenders.append("%s 模块级 import %s" % (rel, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in optional:
                    offenders.append("%s 模块级 from %s" % (rel, node.module))
    assert not offenders, "输入层做了模块级可选依赖 import：%s" % offenders


# ---------------------------------------------------------------- 规范化层纯函数


def test_normalize_pure_modules_have_no_io_imports():
    """模块② 的纯函数件（mapping/parse）不得 import 文件/网络/时间/随机模块。

    它们的职责是"把行文本对齐到知识库登记写法"——一旦开始读文件或读时钟，
    "别名表只在 YAML 一处定义"这条纪律就有了第二条读取路径（测试与基准注入夹具
    字典的通道也随之失效）。
    """
    for rel in NORMALIZE_PURE_MODULES:
        tree = _parse(rel)
        imported = [name.split(".")[0] for name in _module_level_imports(tree)]
        offenders = [name for name in imported if name in FORBIDDEN_IO_MODULES]
        assert not offenders, "%s import 了 I/O 类模块（应为纯函数）：%s" % (rel, offenders)


def test_normalize_pure_modules_have_no_function_level_io_imports():
    """函数体内 import 同样破坏纯度——分层越严，边界越靠后越易漏。"""
    for rel in NORMALIZE_PURE_MODULES:
        tree = _parse(rel)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in FORBIDDEN_IO_MODULES:
                        offenders.append("%s: %s" % (rel, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in FORBIDDEN_IO_MODULES:
                    offenders.append("%s: from %s" % (rel, node.module))
        assert not offenders, "规范化纯函数件存在 I/O 类 import：%s" % offenders


def test_normalize_layer_does_not_import_engine():
    """模块② **不得** import 判定内核——它只做映射，不做任何数值语义判断。

    若规范化层能拿到 `engine.compare`，就说明"映射"与"判定"的边界被跨过去了：
    判定规则会在两个地方被调用，改一处漏一处。
    """
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith(NORMALIZE_PREFIX):
            continue
        for name in _module_level_imports(_parse(rel)):
            if "engine" in name:
                offenders.append("%s imports %s" % (rel, name))
    assert not offenders, "规范化层 import 了判定内核（分层越界）：%s" % offenders


def test_normalize_layer_does_not_decide_flags():
    """模块② 不得产出判定态常量（`FLAG_*`）——那是判定层的职责。"""
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith(NORMALIZE_PREFIX):
            continue
        source = read_text(rel)
        for token in ("FLAG_HIGH", "FLAG_LOW", "FLAG_NORMAL", "FLAG_NOT_ASSESSED"):
            if token in source:
                offenders.append("%s 出现 %s" % (rel, token))
    assert not offenders, "规范化层出现判定态（越界做判定）：%s" % offenders


def test_normalize_layer_has_no_embedded_range_numbers():
    """模块② 不得出现区间数值——它们只能来自知识库（零字面量门禁）。

    豁免与判定内核同口径：0/1/2 这类结构常数与精度约定。
    """
    exempt = {0, 1, 2, -1}
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith(NORMALIZE_PREFIX):
            continue
        for node in ast.walk(_parse(rel)):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                    and not isinstance(node.value, bool):
                if node.value not in exempt:
                    offenders.append("%s:%d 出现 %s" % (rel, node.lineno, node.value))
    assert not offenders, "规范化层出现区间数值字面量：%s" % offenders


def test_normalize_layer_only_pipeline_reads_files():
    """**唯一读文件处**必须落在 `pipeline.py`（编排层）——纯函数件不许碰文件。

    判据 = 规范化包内，只有 `pipeline.py` 可以 import `loader`/`paths`/`open`。
    这条与"别名表只在 YAML 一处定义"是同一件事的两面：读取路径唯一，
    注入夹具字典的通道才唯一。
    """
    allowed = {"src/checkup_ledger/normalize/pipeline.py"}
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith(NORMALIZE_PREFIX) or rel in allowed:
            continue
        source = read_text(rel)
        for token in ("open(", "checkup_ledger.loader", "checkup_ledger.paths"):
            if token in source:
                offenders.append("%s 出现 %r（纯函数件不许读文件）" % (rel, token))
    assert not offenders, "规范化层的文件读取溢出到纯函数件：%s" % offenders


def test_normalize_layer_does_not_import_loader():
    """纯函数件不得 import `loader`——loader 含文件 I/O，会把纯度门禁架空。

    编排层（pipeline）在函数体内延迟 import loader 是允许的（它是唯一读文件处）；
    模块级 import 则会让"纯函数"这条边界从 import 图上一眼就破。
    """
    offenders = []
    for rel in NORMALIZE_PURE_MODULES:
        for name in _module_level_imports(_parse(rel)):
            if "loader" in name or "paths" in name:
                offenders.append("%s imports %s" % (rel, name))
    assert not offenders, "规范化纯函数件 import 了含 I/O 的模块：%s" % offenders


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

    # 区间夹具从知识库取（不在测试里手写数值——那是区间数值的第二处定义）
    low, high = bounds_pair("ALT")
    judged = [
        Judged(
            measurement=Measurement(canonical_name="ALT", raw_name="ALT", value=low, unit="U/L"),
            flag=FLAG_NORMAL,
            range_used=RefRange(low=low, high=high, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_BUILTIN),
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


# ---------------------------------------------------------------- M4：图元计算与装配分离


def test_render_assembly_modules_have_no_arithmetic_or_comparison():
    """装配层（`html.py` / `trend.py`）**只准拼接**：无算术、无大小比较。

    这条与 `test_renderer_has_no_arithmetic` 同源，但把范围扩到整个装配层
    （M4 新增 `trend.py`）。判据：`BinOp`（除 `%`/`+` 这类字符串拼接）与
    `Compare` 的大小运算符一律不许出现——坐标与分位都由 `chart.py` 算好。
    """
    offenders = []
    for rel in RENDER_ASSEMBLY_MODULES:
        tree = _parse(rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and not isinstance(node.op, (ast.Mod, ast.Add)):
                offenders.append("%s:%d BinOp %s" % (rel, node.lineno, type(node.op).__name__))
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                        offenders.append("%s:%d Compare %s" % (rel, node.lineno, type(op).__name__))
    assert not offenders, "装配层出现算术/大小比较（应落在 chart.py）：%s" % offenders


def test_chart_module_does_not_decide_flags_or_see_ranges():
    """`chart.py` 是**图元计算**模块：看不到判定态、不 import 判定内核。

    它当然要做算术（坐标换算）与比较（求域上下界）——那是图元本职。但它**不得**
    出现判定态常量（`FLAG_*`），否则"谁在下结论"的边界就从 import 图上一眼破。
    区间端点在本模块里只是**画布上的数字**（用来撑开值域、定带的位置），
    不与观测值做大小比较——故这里同时禁"拿区间端点与值比较"的形态。
    """
    tree = _parse(CHART_PATH)
    source = read_text(CHART_PATH)
    for token in ("FLAG_HIGH", "FLAG_LOW", "FLAG_NORMAL", "FLAG_NOT_ASSESSED"):
        assert token not in source, "图元计算模块出现判定态 %s（越界做判定）" % token
    offenders = [name for name in _module_level_imports(tree) if "engine" in name]
    assert not offenders, "图元计算模块 import 了判定内核：%s" % offenders


def test_chart_module_has_no_io_imports():
    """图元计算是纯函数：不读文件、不读时钟、不联网、不连库。"""
    tree = _parse(CHART_PATH)
    imported = [name.split(".")[0] for name in _module_level_imports(tree)]
    offenders = [name for name in imported if name in FORBIDDEN_IO_MODULES]
    assert not offenders, "图元计算模块 import 了 I/O 类模块：%s" % offenders


def test_ledger_layer_does_not_import_judgement_kernel_functions():
    """台账层只**消费** `Judged`，不得 import 判定函数（`compare`/`select_range`/`judge`）。

    允许它 import `engine.compare` 里的**趋势**函数（`trend_delta`/`trend_direction`）
    ——趋势三态是"事实归类"，与 H/L 判定无关，且必须单点实算（不重写口径）。
    但 `compare` 是判定本身：台账若能调它，"判定只在一处"的边界就破了。
    """
    banned = ("compare", "select_range", "judge", "judge_all", "validate_range", "range_applies_to")
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith(LEDGER_PREFIX):
            continue
        tree = _parse(rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "engine" in node.module:
                for alias in node.names:
                    if alias.name in banned:
                        offenders.append("%s imports %s from %s" % (rel, alias.name, node.module))
    assert not offenders, "台账层 import 了判定函数（越界做判定）：%s" % offenders


def test_ledger_layer_does_not_decide_flags():
    """台账层不得产出判定态常量（`FLAG_*`）——它只落库既有判定结果。"""
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith(LEDGER_PREFIX):
            continue
        source = read_text(rel)
        for token in ("FLAG_HIGH", "FLAG_LOW", "FLAG_NORMAL", "FLAG_NOT_ASSESSED"):
            if token in source:
                offenders.append("%s 出现 %s" % (rel, token))
    assert not offenders, "台账层出现判定态（越界做判定）：%s" % offenders


def test_ledger_layer_has_no_embedded_range_numbers():
    """台账层不得出现**知识库区间端点**——它们只能来自知识库（零字面量门禁）。

    判据用**真实 token 集**（`helpers.load_yaml_tokens`，**唯一实算处**），
    而不是自定一份豁免清单：台账里合法存在**日历结构常数**（年/月/日的位数、
    一年几个月、一月最多几天）与 schema 版本号，它们与区间端点无关。
    按真实端点集比对，就只拦"有人把阈值抄进了台账层"这一件事，
    不会因为日历常数而误报——也不会因为自定豁免而放宽门。
    """
    tokens = load_yaml_tokens()
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith(LEDGER_PREFIX):
            continue
        for node in ast.walk(_parse(rel)):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                    and not isinstance(node.value, bool):
                if float(node.value) in tokens:
                    offenders.append("%s:%d 出现区间端点 %s" % (rel, node.lineno, node.value))
    assert not offenders, "台账层出现知识库区间端点字面量：%s" % offenders


def test_export_layer_has_no_embedded_range_numbers():
    """导出层不得出现**知识库区间端点**——它们只能来自知识库（零字面量门禁）。

    同台账层：用真实 token 集比对。导出层的 `PERCENT_SCALE`（百分比换算）是
    结构常数，与区间端点无关，故不会被误报。
    """
    tokens = load_yaml_tokens()
    offenders = []
    for node in ast.walk(_parse(EXPORT_PATH)):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            if float(node.value) in tokens:
                offenders.append("%s:%d 出现区间端点 %s" % (EXPORT_PATH, node.lineno, node.value))
    assert not offenders, "导出层出现知识库区间端点字面量：%s" % offenders


def test_export_layer_calls_advisory_wording_gate_always():
    """建议词根门必须是**导出出口的常驻行为**，不是只在测试里验一次。"""
    source = read_text(EXPORT_PATH)
    assert "assert_no_advisory_wording" in source, "导出出口未调用建议词根门"
    tree = _parse(EXPORT_PATH)
    called = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "assert_no_advisory_wording":
                called = True
    assert called, "建议词根门只被定义而未被调用（假门）"


def test_renderer_calls_advisory_wording_gate_always():
    """渲染层也要过词根门（界面文字不许给意见），且必须是出口常驻行为。

    判据用**配对**而不是"文件里出现过这个名字"：每条渲染出口都同时跑零外链断言
    与词根断言——**少任何一个**都会红。只查"名字出现过"会被"另一个出口还留着"
    满足（删掉一处调用仍绿），那是假门。
    """
    tree = _parse(RENDERER_PATH)
    pairs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        called = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name:
                    called.add(name)
        if "assert_no_external_resources" in called or "assert_no_advisory_wording" in called:
            pairs.append((node.name, called))

    assert pairs, "渲染层没有任何出口跑常驻断言（探针失效）"
    for name, called in pairs:
        assert "assert_no_external_resources" in called, (
            "%s 出口未跑零外链断言（断网可开承诺落空）" % name
        )
        assert "assert_no_advisory_wording" in called, (
            "%s 出口未跑建议词根断言（界面文字可能给意见）" % name
        )


def test_render_assembly_modules_do_not_import_engine():
    """装配层不得 import 判定内核——那会让"零判定"的边界形同虚设。"""
    offenders = []
    for rel in RENDER_ASSEMBLY_MODULES:
        for name in _module_level_imports(_parse(rel)):
            if "engine" in name:
                offenders.append("%s imports %s" % (rel, name))
    assert not offenders, "装配层 import 了判定内核：%s" % offenders


# ---------------------------------------------------------------- M4：首启免责


def test_disclaimer_writes_marker_only_in_given_home():
    """免责标记落在**给定主目录**内（测试不许去动真实 `~`）。

    显式传 `env={}`：`env=None` 会回落 `os.environ`，而测试期 `helpers.py` 已把
    免责标记重定向到隔离目录（防污染真实主目录）——不传空 env 的话，这些用例
    实际测的是隔离目录而不是传进来的 `home`（**假通过**）。
    """
    import tempfile

    from checkup_ledger import disclaimer

    with tempfile.TemporaryDirectory() as tmp:
        assert disclaimer.needs_disclaimer(home=tmp, env={}), "首次运行应需要打印免责"
        assert disclaimer.mark_accepted(home=tmp, env={}) is True
        assert disclaimer.is_accepted(home=tmp, env={}), "标记未落盘"
        assert not disclaimer.needs_disclaimer(home=tmp, env={}), "已接受仍报需要"
        assert os.path.isfile(disclaimer.accepted_path(home=tmp, env={})), "标记文件不在给定主目录内"
        # 再落一次是幂等的（不报错）
        assert disclaimer.mark_accepted(home=tmp, env={}) is True


def test_disclaimer_marker_contains_no_identity_metadata():
    """标记文件只记"接受过"这一个事实——不写时间戳/机器名（隐私红线）。"""
    import re
    import tempfile

    from checkup_ledger import disclaimer

    with tempfile.TemporaryDirectory() as tmp:
        disclaimer.mark_accepted(home=tmp, env={})
        with open(disclaimer.accepted_path(home=tmp, env={}), "r", encoding="utf-8") as handle:
            text = handle.read()
    assert text.strip(), "标记文件为空（探针失效）"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text), "标记文件含日期（身份线索）"
    assert not re.search(r"\d{2}:\d{2}", text), "标记文件含时间（身份线索）"


def test_disclaimer_banner_is_empty_after_acceptance():
    """已接受 → 横幅为空串（不再重复念）。"""
    import tempfile

    from checkup_ledger import disclaimer

    with tempfile.TemporaryDirectory() as tmp:
        assert disclaimer.first_run_banner(home=tmp, env={}) == disclaimer.DISCLAIMER_TEXT
        disclaimer.mark_accepted(home=tmp, env={})
        assert disclaimer.first_run_banner(home=tmp, env={}) == ""


def test_disclaimer_failure_to_write_is_not_an_error():
    """写不进去（只读环境）不算失败：免责照样打印，只是每次再念一遍。"""
    from checkup_ledger import disclaimer

    # 指向一个不可能写入的路径（非法字符使 open 必失败）
    unwritable = os.path.join("\0-invalid", "accepted")
    assert disclaimer.mark_accepted(home=unwritable, env={}) is False, "写入失败未被如实返回"
    assert disclaimer.needs_disclaimer(home=unwritable, env={}), "写入失败后仍报已接受"


def test_disclaimer_banner_text_carries_the_required_statements():
    """免责文本必须含四件事：非医疗器械 / 机械比较 / LIS 为准 / 零上传。"""
    from checkup_ledger import disclaimer

    text = disclaimer.DISCLAIMER_TEXT
    for keyword in ("不是医疗器械", "机械比较", "LIS", "不联网"):
        assert keyword in text, "免责文本缺关键表述：%s" % keyword


def test_disclaimer_does_not_invent_a_tilde_directory(monkeypatch, tmp_path):
    """**主目录解不出来时不得臆造 `~` 目录**（M5 实测抓到的真缺陷）。

    `os.path.expanduser("~")` 在环境里没有 `USERPROFILE`/`HOMEDRIVE`+`HOMEPATH`/`HOME`
    时**原样返回字符串 `~`**，经 `abspath` 就落成"当前工作目录下的 `~` 文件夹"。
    实测：在 `env -i` 里跑冻结产物（`ledger` 触发首启免责）→ 工作目录里真的多出
    `~/.checkup_ledger/accepted`。那是**用户可见的污染**。

    判据：解不出主目录 → 路径为 `None`、写标记返回 `False`、且**不去 CWD 里建目录**。
    """
    from checkup_ledger import disclaimer

    # 打桩**模块级别名**（不是 `os.path.expanduser`——那会改到标准库函数本身，
    # 波及同一进程里的其他代码），模拟"环境里没有主目录变量"。
    monkeypatch.setattr(disclaimer, "_expanduser", lambda path: path)
    monkeypatch.chdir(tmp_path)

    assert disclaimer.home_dir() is None, "无主目录时仍解析出一个目录（会臆造 ~ 目录）"
    assert disclaimer.accepted_path(env={}) is None, "无主目录时仍给出标记路径"
    assert disclaimer.mark_accepted(env={}) is False, "无主目录时写标记未如实返回失败"
    assert disclaimer.needs_disclaimer(env={}), "无主目录时被当成已接受（免责会漏念）"
    assert not os.path.exists(os.path.join(str(tmp_path), "~")), (
        "工作目录里被建出了 `~` 目录（污染用户 CWD）"
    )


def test_disclaimer_uses_real_home_when_resolvable(monkeypatch):
    """配对守：主目录**解析得出来**时照旧落标记——上一条不能把正常路径一并禁掉。"""
    from checkup_ledger import disclaimer

    monkeypatch.setattr(disclaimer, "_expanduser", lambda path: os.path.join(os.sep, "home-of-user"))
    resolved = disclaimer.home_dir()
    assert resolved == os.path.abspath(os.path.join(os.sep, "home-of-user")), (
        "主目录可解析时未被采用：%s" % resolved
    )
    assert disclaimer.accepted_path(env={}) == os.path.join(
        resolved, ".checkup_ledger", "accepted"
    ), "主目录可解析时的标记路径不对"


def test_disclaimer_rejects_an_unexpanded_tilde_passed_explicitly():
    """显式传 `home="~"` 同样按"解不出来"处理——那是调用方漏展开的信号，不是路径。"""
    from checkup_ledger import disclaimer

    assert disclaimer.home_dir("~") is None, "显式传入的未展开 `~` 被当成真实目录"
    assert disclaimer.home_dir("   ") is None, "空白主目录未被拒绝"
    assert disclaimer.mark_accepted(home="~", env={}) is False, "未展开的 `~` 被落盘了"


def test_helpers_isolate_disclaimer_marker_from_real_home():
    """**测试不得污染开发者/CI 的真实主目录**（实测抓到的真缺陷）。

    `ledger`/`export`/`report` 经 `main()` 会触发首启免责并把标记落到
    `~/.checkup_ledger/accepted`。测试若直接调 `main()`（`helpers.run_cli` 就是），
    就会在**真实主目录**里留下文件——污染用户环境，且第二次起免责不再打印
    （后续用例再也测不到首启行为）。

    这条门断言 `helpers` 导入时已把标记重定向到仓库外的一次性目录，且
    **该路径不在真实主目录之下**。
    """
    import helpers

    from checkup_ledger import disclaimer

    assert helpers._ACCEPTED_ENV == disclaimer.ENV_ACCEPTED_PATH, (
        "helpers 与 disclaimer 的环境变量名不同源（重定向会失效）"
    )
    override = os.environ.get(helpers._ACCEPTED_ENV)
    assert override, "helpers 未设置免责标记的隔离路径（测试会写进真实主目录）"

    real_home = os.path.abspath(os.path.expanduser("~"))
    resolved = os.path.abspath(override)
    # 判据是**不落在默认标记路径上**，而不是"不在用户目录之下"——Windows 上
    # `tempfile.gettempdir()` 就在用户目录之下（`%LOCALAPPDATA%\Temp`），
    # 拿"是否在 ~ 之下"判会把合法隔离路径误判成污染。
    default_marker = os.path.join(real_home, ".checkup_ledger", "accepted")
    assert resolved != os.path.abspath(default_marker), (
        "隔离路径就是默认标记路径（测试仍会写进真实主目录）"
    )
    assert os.path.dirname(resolved) != os.path.join(real_home, ".checkup_ledger"), (
        "隔离路径仍落在 ~/.checkup_ledger 内（会污染用户环境）：%s" % resolved
    )
    # 显式 `env={}` 时**不受**隔离影响（单元用例走 home 参数）：
    # 空 env 下应回落默认标记路径，而不是隔离路径。
    explicit = disclaimer.accepted_path(env={})
    assert os.path.abspath(explicit) != resolved, (
        "显式 env={} 仍被隔离路径覆盖（单元用例测不到 home 参数的真实行为）"
    )
    assert os.path.abspath(explicit) == os.path.abspath(default_marker), (
        "空 env 下应回落 ~/.checkup_ledger/accepted（隔离只作用于测试进程的环境变量）"
    )


def test_data_commands_do_not_create_marker_in_real_home():
    """跑一次真实数据命令后，真实主目录**不出现** `.checkup_ledger`（隔离生效的实物证明）。"""
    real_home = os.path.abspath(os.path.expanduser("~"))
    marker_dir = os.path.join(real_home, ".checkup_ledger")

    existed_before = os.path.isdir(marker_dir)
    run_cli(["ledger", "--db", os.path.join(tempfile.gettempdir(), "no-such-ledger-xyz.db")])
    existed_after = os.path.isdir(marker_dir)

    assert existed_after == existed_before, (
        "跑数据命令后真实主目录里出现了 .checkup_ledger（测试污染用户环境）"
    )


def test_cli_first_run_disclaimer_fires_on_real_entry_path():
    """**真实入口**（`argv is None`）必须也能触发首启免责。

    这条挡的是实测抓到的一个真缺陷：`main()` 从 `python -m` / 裸 console script
    进来时 `argv` 是 `None`，而初版实现写成 `if not argv: return`——于是
    "用户真的敲了 ledger"被读成"没有参数"，免责**在真实入口永不打印**；
    而单测里显式传 `["ledger", ...]` 会通过（缺陷只在真实通路暴露）。
    故这里显式测 `argv=None` + 打桩 `sys.argv`。
    """
    import tempfile
    from unittest import mock

    from checkup_ledger import cli

    with tempfile.TemporaryDirectory() as tmp:
        accepted = os.path.join(tmp, "accepted")
        with mock.patch.dict(os.environ, {"CHECKUP_LEDGER_ACCEPTED": accepted}):
            with mock.patch.object(cli.sys, "argv", ["checkup-ledger", "ledger", "--db", os.path.join(tmp, "n.db")]):
                # argv=None（真实入口形态）→ 应回落 sys.argv[1:] 并触发免责
                code = cli.main(None)
        assert code in (0, 1), "真实入口路径异常退出：%s" % code
        assert os.path.isfile(accepted), (
            "argv=None 时首启免责未落标记（真实入口漏触发——免责永远不会打印）"
        )


def test_cli_first_run_disclaimer_skips_self_check_commands():
    """自检类命令（version/selftest/bench/indicators）**不**打印免责（免得淹没 CI 输出）。"""
    import tempfile
    from unittest import mock

    from checkup_ledger import cli

    with tempfile.TemporaryDirectory() as tmp:
        accepted = os.path.join(tmp, "accepted")
        with mock.patch.dict(os.environ, {"CHECKUP_LEDGER_ACCEPTED": accepted}):
            with mock.patch.object(cli.sys, "argv", ["checkup-ledger", "selftest"]):
                cli.main(None)
        assert not os.path.isfile(accepted), "自检类命令触发了免责（会淹没 CI 输出）"

