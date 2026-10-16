"""模块① 夹具的生成物门禁：**确定性**、真值库无观测字段、台账登记。

三条门（与 M1 的 `test_samples.py` 同源，只是对象换成输入层夹具）：

1. **生成器确定性**：禁 stdlib `random` / 时钟 / `hash()`；落盘经原子写；
2. **位级一致**：`gen_ingest_fixtures.py --check` 绿（再生成与磁盘逐字节一致）；
3. **真值库无观测字段** + 台账登记（夹具是生成物，手改被检出）。

为什么要单独为输入层夹具建一套：它们的产物是 **PDF/PNG 二进制**，
与 M1 的文本产物（`.txt`/`.json`）走的是不同的"字节可复现"风险面
（PDF 对象号、PNG zlib 压缩、字体渲染版本）——同一套门覆盖不到。
"""

import ast
import os

from helpers import read_text, repo_path

GEN_PATH = "tools/gen_ingest_fixtures.py"
FIXTURE_DIR = "data/samples/ingest"
FORBIDDEN_TRUTH_FIELDS = ("observed", "actual", "got", "computed", "result")


def _truth_files():
    base = repo_path(*(FIXTURE_DIR.split("/") + ["truth"]))
    assert os.path.isdir(base), "夹具真值目录不存在：%s" % FIXTURE_DIR
    names = sorted(name for name in os.listdir(base) if name.endswith(".truth.json"))
    assert names, "夹具真值目录为空"
    return [os.path.join(base, name) for name in names]


# ---------------------------------------------------------------- 门 1：生成器确定性


def _module_imports(path):
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_fixture_generator_has_no_nondeterministic_imports():
    """禁 stdlib `random`、禁时钟——它们会让夹具不可复现。"""
    banned = ("random", "time", "datetime", "secrets", "uuid")
    imports = _module_imports(repo_path(GEN_PATH))
    offenders = [name for name in imports if name.split(".")[0] in banned]
    assert not offenders, "夹具生成器 import 了非确定性来源：%s" % offenders


def test_fixture_renderers_are_deterministic():
    """写出器（PDF / PNG）同样禁非确定性来源与 `hash()`。"""
    for rel in ("tools/fixtures/pdfwrite.py", "tools/fixtures/scanrender.py"):
        source = read_text(rel)
        tree = ast.parse(source, filename=rel)
        banned = ("random", "time", "datetime", "secrets", "uuid")
        imports = _module_imports(repo_path(rel))
        offenders = [name for name in imports if name.split(".")[0] in banned]
        assert not offenders, "%s import 了非确定性来源：%s" % (rel, offenders)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                assert name != "hash", "%s 调用了 hash()（字符串哈希带随机盐）" % rel


def test_fixture_generator_writes_via_atomic_path():
    """落盘必须经原子写（不留半个产物）。"""
    source = read_text(GEN_PATH)
    assert "write_atomic" in source, "夹具生成器未使用原子写"


def test_fixture_check_passes():
    """`--check` 必须绿：再生成与磁盘产物逐字节一致。"""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, repo_path(GEN_PATH), "--check"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=repo_path("."), env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
    )
    output = result.stdout.decode("utf-8", "replace")
    assert result.returncode == 0, "夹具位级一致校验失败：\n%s" % output


def test_png_renderer_is_byte_stable_for_same_input(tmp_path):
    """同一输入渲染两次 → 逐字节相同（**渲染器本身**的确定性，与磁盘产物无关）。"""
    import sys

    sys.path.insert(0, repo_path("tools"))
    from fixtures import scanrender

    # 行内容从知识库取（手写区间数值 = 第二处定义，零字面量门禁会红）
    from helpers import bounds_pair, yaml_bounds

    spec = yaml_bounds("ALT")
    low, high = bounds_pair("ALT")
    rows = [["ALT", "51", spec["unit"], "%g-%g" % (low, high)]]
    first = os.path.join(str(tmp_path), "a.png")
    second = os.path.join(str(tmp_path), "b.png")
    scanrender.render_columns(rows, first)
    scanrender.render_columns(rows, second)
    assert _sha256(first) == _sha256(second), "同一输入两次渲染字节不同"


def test_pdf_writer_is_byte_stable_for_same_input(tmp_path):
    """同一输入写出两次 → 逐字节相同（PDF 无时间戳/随机对象号）。"""
    import sys

    sys.path.insert(0, repo_path("tools"))
    from fixtures import pdfwrite

    from helpers import bounds_pair, yaml_bounds

    spec = yaml_bounds("ALT")
    low, high = bounds_pair("ALT")
    line = "ALT 51 %s %g-%g" % (spec["unit"], low, high)
    payload_a = pdfwrite.build_pdf([[(pdfwrite.PLAIN, line)]])
    payload_b = pdfwrite.build_pdf([[(pdfwrite.PLAIN, line)]])
    assert payload_a == payload_b, "同一输入两次写出 PDF 字节不同"


# ---------------------------------------------------------------- 门 2：真值库无观测字段


def _iter_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            for item in _iter_keys(value):
                yield item
    elif isinstance(node, list):
        for item in node:
            for key in _iter_keys(item):
                yield key


def test_fixture_truth_has_no_observed_fields():
    """夹具真值只存"输入与期望"——出现观测类字段即红。"""
    import json

    offenders = []
    for path in _truth_files():
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for key in _iter_keys(payload):
            if key.lower() in FORBIDDEN_TRUTH_FIELDS:
                offenders.append("%s 出现字段 %r" % (os.path.basename(path), key))
    assert not offenders, "夹具真值出现观测类字段：%s" % offenders


def test_fixture_truth_declares_expectations():
    """反向：真值必须**真的**含期望行——否则"无观测字段"可被空文件满足。"""
    import json

    checked = 0
    for path in _truth_files():
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        assert payload.get("case_id"), "%s 缺 case_id" % path
        lines = payload.get("expected_lines")
        assert isinstance(lines, list) and lines, "%s 的 expected_lines 为空" % path
        checked += len(lines)
    assert checked > 0, "未检查到任何期望行（探针失效）"


def test_fixture_truth_has_no_timestamp():
    """产物无时间戳——时间戳会让位级一致随机红。"""
    import re

    stamp = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
    for path in _truth_files():
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        assert not stamp.search(text), "%s 含时间戳" % os.path.basename(path)


# ---------------------------------------------------------------- 门 3：台账登记（生成物）


def test_fixtures_are_registered_in_ledger():
    """输入层夹具必须登记在数据台账里（防"生成了但没登记"）。"""
    import csv

    with open(repo_path("data", "ledger", "assets.csv"), "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    paths = {row["rel_path"] for row in rows}
    for suffix in (".pdf", ".png"):
        matching = [path for path in paths if path.startswith(FIXTURE_DIR) and path.endswith(suffix)]
        assert matching, "台账未登记输入层夹具的 %s 产物" % suffix
    assert any(path.endswith(".truth.json") for path in paths if path.startswith(FIXTURE_DIR)), (
        "台账未登记夹具真值"
    )


def test_fixture_manifest_matches_disk():
    """manifest 登记的用例必须与磁盘一一对应。"""
    import json

    with open(repo_path(*(FIXTURE_DIR.split("/") + ["manifest.json"])), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    registered = {case["case_id"] for case in manifest["cases"]}
    on_disk = {
        name.split(".truth.json")[0]
        for name in os.listdir(repo_path(*(FIXTURE_DIR.split("/") + ["truth"])))
        if name.endswith(".truth.json")
    }
    assert registered == on_disk, "manifest 与真值目录不一致：登记 %s，磁盘 %s" % (
        sorted(registered - on_disk), sorted(on_disk - registered)
    )


def _sha256(path):
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
