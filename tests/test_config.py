"""运行时配置门禁：**阈值只能定义一次**，代码不得留默认值。

为什么这层要有独立门：`threshold=0.8` 这类"顺手默认值"是最容易复活的漂移——
它在功能上完全能用（用户不传就用默认），于是没人会注意到"改配置改不动它"。
故本文件把三件事锁死：

1. **配置是唯一来源**：`config.yaml` 的 `ocr_threshold` 与 `load_config()` 读出的值一致；
2. **代码零默认值**：删字段 / 删文件 / 改非法值都必须**报错**（不是回落某个字面值）；
3. **引擎与夹具都不写死阈值**：`ingest` 的入口签名要求显式传入，没有默认参数。
"""

import os
import re

import pytest

from helpers import read_text, repo_path

from checkup_ledger.config import (
    CONFIG_FILENAME,
    OCR_THRESHOLD_KEY,
    Config,
    ConfigError,
    config_path,
    load_config,
)

CONFIG_REL = "src/checkup_ledger/data/config.yaml"


# ---------------------------------------------------------------- 配置即来源


def test_config_file_is_the_single_definition_site():
    """阈值在配置里**确实存在且是数值**——防"门扫了个空配置"。"""
    text = read_text(CONFIG_REL)
    match = re.search(r"(?m)^\s*%s\s*:\s*([0-9.]+)\s*$" % OCR_THRESHOLD_KEY, text)
    assert match, "配置里没有 %s 字段（阈值单点定义失效）" % OCR_THRESHOLD_KEY
    value = float(match.group(1))
    assert 0.0 <= value <= 1.0, "阈值超出 [0, 1]：%r" % value


def test_loaded_threshold_matches_config_file():
    """读出的阈值必须等于配置里的字面值（防"读了别处"或"加了兜底"）。"""
    text = read_text(CONFIG_REL)
    match = re.search(r"(?m)^\s*%s\s*:\s*([0-9.]+)\s*$" % OCR_THRESHOLD_KEY, text)
    declared = float(match.group(1))
    assert load_config().ocr_threshold == declared, "读出的阈值与配置不符"


def test_config_path_resolves_inside_package_data():
    """配置文件必须落在随包数据目录内（冻结/安装态才找得到）。"""
    resolved = config_path()
    assert os.path.basename(resolved) == CONFIG_FILENAME
    assert os.path.isfile(resolved), "配置文件不在位：%s" % resolved
    assert os.path.isfile(repo_path(CONFIG_REL)), "随包配置未登记在仓库内"


# ---------------------------------------------------------------- 代码零默认值


def test_missing_file_raises_not_falls_back(tmp_path):
    """配置缺失 → 报错，**绝不回落**某个字面默认值。"""
    missing = os.path.join(str(tmp_path), "no-such-config.yaml")
    with pytest.raises(ConfigError):
        load_config(path=missing)


def test_missing_threshold_key_raises(tmp_path):
    """缺 `ocr_threshold` 字段 → 报错（"没配"不等于"用默认"）。"""
    target = os.path.join(str(tmp_path), "config.yaml")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("schema_version: 1\n")
    with pytest.raises(ConfigError):
        load_config(path=target)


@pytest.mark.parametrize("bad", ["true", '"0.8"', "null", "[]"])
def test_non_numeric_threshold_raises(tmp_path, bad):
    """非数值阈值（含布尔、"数字字符串"）→ 报错，不静默强转。"""
    target = os.path.join(str(tmp_path), "config.yaml")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("schema_version: 1\n%s: %s\n" % (OCR_THRESHOLD_KEY, bad))
    with pytest.raises(ConfigError):
        load_config(path=target)


def test_out_of_range_threshold_raises(tmp_path):
    """越界阈值 → 报错（越界值会让全部行进复核或全部放行，属静默错配）。"""
    target = os.path.join(str(tmp_path), "config.yaml")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("schema_version: 1\n%s: 1.5\n" % OCR_THRESHOLD_KEY)
    with pytest.raises(ConfigError):
        load_config(path=target)


def test_bad_schema_version_raises(tmp_path):
    target = os.path.join(str(tmp_path), "config.yaml")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("schema_version: 99\n%s: 0.55\n" % OCR_THRESHOLD_KEY)
    with pytest.raises(ConfigError):
        load_config(path=target)


def test_ingest_entrypoint_has_no_default_threshold():
    """`ingest()` 的 `ocr_threshold` **不得有默认参数值**。

    有默认值就等于代码里又定义了一次阈值——配置改成 0.6，代码默认 0.8 仍会生效。
    """
    import inspect

    from checkup_ledger.ingest import ingest, apply_review_gate

    for func in (ingest, apply_review_gate):
        signature = inspect.signature(func)
        assert "ocr_threshold" in signature.parameters, "%s 缺 ocr_threshold 参数" % func.__name__
        parameter = signature.parameters["ocr_threshold"]
        assert parameter.default is inspect.Parameter.empty, (
            "%s 的 ocr_threshold 有默认值 %r（代码里又定义了一次阈值）"
            % (func.__name__, parameter.default)
        )


def test_config_module_has_no_threshold_literal():
    """配置模块源码不得出现阈值字面值（如 0.8）——它是"第二处定义"的温床。"""
    source = read_text("src/checkup_ledger/config.py")
    assert "0.8" not in source, "config 模块里出现阈值字面值 0.8（应只从配置读）"
    # 范围常量 [0,1] 是结构边界（数值域的合法性），不是阈值本身
    assert isinstance(load_config(), Config)
