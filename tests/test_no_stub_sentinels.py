"""桩哨兵串扫描：三种桩形态都**不会**让任何门变红，故必须专设一条扫描。

三种形态（收尾期固定扫一遍）：
① 空 `pass` 测试（测试收集成功、`exit 0` —— 看起来"有测试"）；
② `NotImplementedError` 桩函数（调用即炸，但不调用就永远绿）；
③ manifest/数据里的 `"sha256": "placeholder"` 一类占位值。

判据：本项目**允许**存在"显式未就绪"的模块（那走 exit 4 契约，且已单测），
但**不允许**存在静默混过的空壳。
"""

import ast
import os
import re

from helpers import iter_python_files, read_text, repo_path

SENTINEL_PATTERNS = (
    r"NotImplementedError",
    r"TODO:\s*\u5b9e\u73b0",
    r"\bFIXME\b",
    r'"sha256"\s*:\s*"placeholder"',
    r"'sha256'\s*:\s*'placeholder'",
    r"\bplaceholder\b",
)

# 允许的解释性提及（"说明性文字"而非"桩实现"）：限定在本文件与文档里
ALLOWED_FILES = ("tests/test_no_stub_sentinels.py",)


def test_no_sentinel_strings_in_source_or_tools():
    offenders = []
    for rel in iter_python_files():
        if rel in ALLOWED_FILES:
            continue
        text = read_text(rel)
        for pattern in SENTINEL_PATTERNS:
            for match in re.finditer(pattern, text):
                line_no = text[: match.start()].count("\n") + 1
                offenders.append("%s:%d 命中 %s" % (rel, line_no, pattern))
    assert not offenders, "源码/工具里出现桩哨兵串：%s" % offenders


def test_no_empty_test_functions():
    """空 `pass` 测试：收集成功、exit 0，是最隐蔽的假绿。"""
    offenders = []
    scanned = 0
    for rel in iter_python_files():
        if not rel.startswith("tests/") or not os.path.basename(rel).startswith("test_"):
            continue
        with open(repo_path(rel), "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test"):
                continue
            scanned += 1
            body = [item for item in node.body if not _is_docstring(item)]
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                offenders.append("%s::%s" % (rel, node.name))
            if not body:
                offenders.append("%s::%s（空函数体）" % (rel, node.name))
    assert scanned > 0, "扫描面为空：未找到任何测试函数（探针失效）"
    assert not offenders, "存在空测试（假绿来源）：%s" % offenders


def test_every_test_module_has_at_least_one_assertion():
    """每个测试模块都要有真断言——只有 import 与 helper 的模块等于没测。"""
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith("tests/") or not os.path.basename(rel).startswith("test_"):
            continue
        with open(repo_path(rel), "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=rel)
        has_assert = any(isinstance(node, ast.Assert) for node in ast.walk(tree))
        # pytest.raises / pytest.fail / pytest.skip 也算断言路径
        source = read_text(rel)
        has_pytest_assertion = "pytest.raises" in source or "pytest.fail" in source
        if not has_assert and not has_pytest_assertion:
            offenders.append(rel)
    assert not offenders, "测试模块没有任何断言：%s" % offenders


def _is_docstring(node):
    return isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
        and isinstance(node.value.value, str)


def test_no_bare_todo_comments_in_package():
    """包内不得留 TODO/FIXME 注释——那意味着"以为做完了其实没做"。"""
    offenders = []
    for rel in iter_python_files():
        if not rel.startswith("src/"):
            continue
        for match in re.finditer(r"#.*\b(TODO|FIXME|XXX)\b", read_text(rel)):
            line_no = read_text(rel)[: match.start()].count("\n") + 1
            offenders.append("%s:%d" % (rel, line_no))
    assert not offenders, "包内残留 TODO/FIXME 注释：%s" % offenders
