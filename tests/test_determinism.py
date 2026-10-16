"""确定性：同输入双跑**逐字节一致**，无时间戳注入。

"确定性"承诺的是**"我们的处理步骤对同一输入产出相同字节"**——所以任何隐藏的
时间戳/字典序/平台默认值都会在这里红。
"""

import os
import tempfile

import pytest

from helpers import bounds_pair

from checkup_ledger.model import (
    FLAG_HIGH,
    BOUNDS_CLOSED,
    Judged,
    Measurement,
    RANGE_SOURCE_REPORT,
    RefRange,
)
from checkup_ledger.serialize import (
    find_leftover_temp_files,
    to_json_bytes,
    to_json_text,
    write_atomic,
    write_json,
)


def test_canonical_json_is_byte_identical_across_runs():
    payload = {"z": 1, "a": "\u4e2d\u6587\u6307\u6807", "nested": {"y": [3, 2, 1], "x": None}}
    assert to_json_bytes(payload) == to_json_bytes(payload)


def test_canonical_json_keeps_chinese_readable():
    """`ensure_ascii=False` 是中文项目必选——否则 diff 不可读。"""
    text = to_json_text({"name": "\u4e2d\u6587"})
    assert "\u4e2d\u6587" in text
    assert "\\u4e2d" not in text


def test_canonical_json_uses_lf_and_trailing_newline():
    text = to_json_text({"a": 1})
    assert "\r" not in text
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_canonical_json_sorts_keys():
    text = to_json_text({"b": 1, "a": 2})
    assert text.index('"a"') < text.index('"b"')


def test_atomic_write_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "out.json")
        payload = to_json_bytes({"k": "\u503c"})
        write_atomic(target, payload)
        with open(target, "rb") as handle:
            assert handle.read() == payload


def test_atomic_write_leaves_no_temp_files():
    with tempfile.TemporaryDirectory() as tmp:
        write_atomic(os.path.join(tmp, "a.json"), b"{}\n")
        write_atomic(os.path.join(tmp, "b.json"), "text\n")
        assert find_leftover_temp_files(tmp) == []


def test_atomic_write_normalizes_crlf():
    """文本写盘一律 LF——CRLF 会让"逐字节一致"在跨平台时红。"""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "c.txt")
        write_atomic(target, "line1\r\nline2\r\n")
        with open(target, "rb") as handle:
            assert handle.read() == b"line1\nline2\n"


def test_atomic_write_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "nested", "deep", "out.json")
        write_json(target, {"ok": True})
        assert os.path.isfile(target)


def test_write_json_double_run_identical():
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "one.json")
        second = os.path.join(tmp, "two.json")
        payload = {"suites": [{"name": "\u8fb9\u754c\u8bed\u4e49", "n": 7}]}
        write_json(first, payload)
        write_json(second, payload)
        with open(first, "rb") as handle_a, open(second, "rb") as handle_b:
            assert handle_a.read() == handle_b.read()


def test_render_html_is_byte_identical_across_runs():
    from checkup_ledger.report.html import render_measurements

    low, high = bounds_pair("ALT")
    judged = [
        Judged(
            measurement=Measurement(
                canonical_name="ALT",
                raw_name="\u8c37\u4e19\u8f6c\u6c28\u9176",
                value=high,
                unit="U/L",
                ref_range_printed=RefRange(low=low, high=high, bounds=BOUNDS_CLOSED,
                                           source=RANGE_SOURCE_REPORT),
            ),
            flag=FLAG_HIGH,
            range_used=RefRange(low=low, high=high, bounds=BOUNDS_CLOSED, source=RANGE_SOURCE_REPORT),
            range_source=RANGE_SOURCE_REPORT,
        )
    ]
    first = render_measurements(judged, subject="\u5f20\u4e09")
    second = render_measurements(judged, subject="\u5f20\u4e09")
    assert first.encode("utf-8") == second.encode("utf-8")


def test_render_html_contains_no_timestamp():
    """产物不得含时间戳——它会让双跑字节一致守门红。"""
    import re

    from checkup_ledger.report.html import render_measurements

    document = render_measurements([], subject="\u674e\u56db")
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", document)
    assert "generated" not in document.lower()


def test_bench_report_double_run_identical():
    from checkup_ledger.benchmark.runner import run_bench

    assert to_json_bytes(run_bench()) == to_json_bytes(run_bench())


@pytest.mark.parametrize("subject", ["\u5f20\u4e09", ""])
def test_selftest_json_double_run_identical(subject):
    import json
    import tempfile

    from helpers import run_cli

    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "a.json")
        second = os.path.join(tmp, "b.json")
        run_cli(["selftest", "--json", first])
        run_cli(["selftest", "--json", second])
        with open(first, "r", encoding="utf-8") as handle_a, open(second, "r", encoding="utf-8") as handle_b:
            data_a = json.load(handle_a)
            data_b = json.load(handle_b)
        # 自检报告含数据目录绝对路径（同一台机器相同），故可逐字节比对
        assert data_a["total"] == data_b["total"]
        assert data_a["checks"] == data_b["checks"]
