"""编码守卫：stdout/stderr 在窄编码下不得 UnicodeEncodeError。

复现手法：用 `TextIOWrapper(BytesIO(), encoding="cp1252", errors="strict")` 造出
"CI 管道 / 非中文控制台"的编码面——**本机即可跑**，不必等 CI 才知道。
"""

import io
import sys

from checkup_ledger.encoding import _can_encode, ensure_utf8_stdio


def _narrow_stream(encoding):
    raw = io.BytesIO()
    return io.TextIOWrapper(raw, encoding=encoding, errors="strict", newline="")


def test_probe_accepts_chinese_capable_encodings():
    for encoding in ("utf-8", "cp936", "gbk", "gb18030", "big5"):
        assert _can_encode(encoding), "%s 应能编码中文" % encoding


def test_probe_rejects_chinese_incapable_encodings():
    for encoding in ("cp1252", "ascii", "latin-1"):
        assert not _can_encode(encoding), "%s 不应能编码中文" % encoding


def test_probe_handles_bogus_encoding_names():
    """编码名本身无效时不抛异常，按"编不动"处理。"""
    assert not _can_encode("no-such-codec-xyz")
    assert not _can_encode(None)
    assert not _can_encode("")


def test_ensure_utf8_stdio_survives_narrow_encoding(monkeypatch):
    """stderr 为 cp1252 时，reconfigure 后中文能写出且不抛错。"""
    stream = _narrow_stream("cp1252")
    monkeypatch.setattr(sys, "stderr", stream, raising=False)
    monkeypatch.setattr(sys, "stdout", _narrow_stream("cp1252"), raising=False)

    ensure_utf8_stdio()

    sys.stderr.write("中文写入检查\n")
    sys.stderr.flush()
    assert _can_encode(sys.stderr.encoding), "reconfigure 后仍编不动中文：%r" % sys.stderr.encoding


def test_ensure_utf8_stdio_keeps_cp936_untouched(monkeypatch):
    """中文控制台（cp936）不该被硬改——它本来就能显示中文。"""
    stream = _narrow_stream("cp936")
    original = stream.encoding
    monkeypatch.setattr(sys, "stdout", stream, raising=False)
    monkeypatch.setattr(sys, "stderr", _narrow_stream("cp936"), raising=False)

    ensure_utf8_stdio()
    assert sys.stdout.encoding == original, "cp936 控制台被无谓 reconfigure：%r" % sys.stdout.encoding


def test_ensure_utf8_stdio_is_idempotent(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _narrow_stream("cp1252"), raising=False)
    monkeypatch.setattr(sys, "stderr", _narrow_stream("cp1252"), raising=False)
    ensure_utf8_stdio()
    first = sys.stdout.encoding
    ensure_utf8_stdio()
    assert sys.stdout.encoding == first


def test_ensure_utf8_stdio_tolerates_streams_without_reconfigure(monkeypatch):
    """StringIO 桩没有 reconfigure，守卫必须容忍（不能因此崩溃）。"""

    class Stub:
        encoding = "cp1252"

        def write(self, _text):
            return 0

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", Stub(), raising=False)
    monkeypatch.setattr(sys, "stderr", Stub(), raising=False)
    ensure_utf8_stdio()  # 不应抛异常


def test_cli_output_survives_narrow_stream(monkeypatch):
    """端到端：窄编码 stream 下跑 CLI，中文输出不得抛 UnicodeEncodeError。"""
    from checkup_ledger import cli

    out_stream = _narrow_stream("cp1252")
    err_stream = _narrow_stream("cp1252")
    monkeypatch.setattr(sys, "stdout", out_stream, raising=False)
    monkeypatch.setattr(sys, "stderr", err_stream, raising=False)

    code = cli.main(["version"])
    assert code == 0
    out_stream.flush()
    err_stream.flush()
    assert _can_encode(out_stream.encoding)
