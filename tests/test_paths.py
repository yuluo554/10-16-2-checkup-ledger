"""数据目录解析三分支：源码态 / 安装态 / 冻结态。

为什么必须逐分支验：`sys.path` 的来源在三种通路下不同（CWD / 安装记录 /
PyInstaller 引导），**一种通不等于另一种通**。冻结态尤其——"跑起来但找不到
知识库"正是解析错误最典型的后果。
"""

import os
import tempfile

import pytest

from helpers import repo_path

from checkup_ledger.paths import (
    DataDirError,
    data_dir_in_frozen_root,
    frozen_root,
    indicators_path,
    is_frozen,
    resolve_data_dir,
)

PY38 = "3.8"


# ---------------------------------------------------------------- 显式优先


def test_explicit_dir_takes_priority(monkeypatch):
    """显式传参最高优先：凡带副作用默认值的 API，测试与演示**一律显式传**。"""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CHECKUP_LEDGER_DATA", os.path.join(tmp, "nonexistent-env"))
        assert resolve_data_dir(tmp) == os.path.abspath(tmp)


def test_explicit_missing_dir_raises():
    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "nope")
        with pytest.raises(DataDirError):
            resolve_data_dir(missing)


# ---------------------------------------------------------------- 环境变量


def test_env_override_is_used(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CHECKUP_LEDGER_DATA", tmp)
        assert resolve_data_dir() == os.path.abspath(tmp)


def test_env_override_pointing_nowhere_raises(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CHECKUP_LEDGER_DATA", os.path.join(tmp, "ghost"))
        with pytest.raises(DataDirError):
            resolve_data_dir()


def test_env_override_can_be_cleared(monkeypatch):
    """清空环境变量后回落自动发现（源码态应找到包内 data/）。"""
    monkeypatch.delenv("CHECKUP_LEDGER_DATA", raising=False)
    monkeypatch.setattr("checkup_ledger.paths.is_frozen", lambda: False)
    resolved = resolve_data_dir()
    assert os.path.isdir(resolved)
    assert os.path.isfile(os.path.join(resolved, "indicators.yaml"))


# ---------------------------------------------------------------- 源码/安装态


def test_source_tree_finds_packaged_data(monkeypatch):
    monkeypatch.delenv("CHECKUP_LEDGER_DATA", raising=False)
    monkeypatch.setattr("checkup_ledger.paths.is_frozen", lambda: False)
    assert os.path.isfile(indicators_path())


# ---------------------------------------------------------------- 冻结态


def test_frozen_root_prefers_meipass(monkeypatch):
    monkeypatch.setattr("checkup_ledger.paths.sys", type("S", (), {"_MEIPASS": os.path.abspath(os.sep)})())
    assert frozen_root() == os.path.abspath(os.sep)


def test_frozen_root_falls_back_to_executable_dir(monkeypatch):
    fake_sys = type("S", (), {"executable": os.path.join(os.path.abspath(os.sep), "bin", "checkup-ledger")})()
    monkeypatch.setattr("checkup_ledger.paths.sys", fake_sys)
    expected = os.path.dirname(os.path.join(os.path.abspath(os.sep), "bin", "checkup-ledger"))
    assert frozen_root() == expected


def test_is_frozen_false_in_source_tree():
    assert not is_frozen(), "源码态不得被误判为冻结态"


def test_frozen_state_without_bundled_data_raises(monkeypatch):
    """冻结态找不到随包数据必须**明确报错**，不静默回落——那会让产物"跑起来但没数据"。

    这条是 paths 的承重门：变异成静默回落后，本测试必须红。
    """
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.delenv("CHECKUP_LEDGER_DATA", raising=False)
        monkeypatch.setattr("checkup_ledger.paths.is_frozen", lambda: True)
        monkeypatch.setattr("checkup_ledger.paths.frozen_root", lambda: tmp)
        with pytest.raises(DataDirError) as excinfo:
            resolve_data_dir()
        assert "\u51bb\u7ed3" in str(excinfo.value) or "data" in str(excinfo.value).lower()


def test_frozen_state_with_bundled_data_resolves(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = os.path.join(tmp, "data")
        os.makedirs(data_dir)
        with open(os.path.join(data_dir, "indicators.yaml"), "w", encoding="utf-8") as handle:
            handle.write("schema_version: 1\n")
        monkeypatch.delenv("CHECKUP_LEDGER_DATA", raising=False)
        monkeypatch.setattr("checkup_ledger.paths.is_frozen", lambda: True)
        monkeypatch.setattr("checkup_ledger.paths.frozen_root", lambda: tmp)
        assert resolve_data_dir() == os.path.abspath(data_dir)


def test_data_dir_in_frozen_root_passes_when_inside(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = os.path.join(tmp, "data")
        os.makedirs(data_dir)
        monkeypatch.delenv("CHECKUP_LEDGER_DATA", raising=False)
        monkeypatch.setattr("checkup_ledger.paths.is_frozen", lambda: True)
        monkeypatch.setattr("checkup_ledger.paths.frozen_root", lambda: tmp)
        assert data_dir_in_frozen_root() == 0


def test_data_dir_in_frozen_root_flags_outside(monkeypatch):
    """数据目录落在 exe 目录之外 → 冻结态自检必须报 FAIL（exit 1）。"""
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
        monkeypatch.delenv("CHECKUP_LEDGER_DATA", raising=False)
        monkeypatch.setattr("checkup_ledger.paths.is_frozen", lambda: True)
        monkeypatch.setattr("checkup_ledger.paths.frozen_root", lambda: root)
        monkeypatch.setenv("CHECKUP_LEDGER_DATA", outside)
        assert data_dir_in_frozen_root() == 1


def test_data_dir_in_frozen_root_is_noop_when_not_frozen(monkeypatch):
    """非冻结态不报 FAIL——这条防"源码态被冻结检查误伤"。"""
    monkeypatch.setattr("checkup_ledger.paths.is_frozen", lambda: False)
    assert data_dir_in_frozen_root() == 0


# ---------------------------------------------------------------- 自检集成


def test_selftest_reports_data_dir_check():
    from helpers import run_cli

    code, out, _err = run_cli(["selftest"])
    assert code == 0
    assert "data_dir" in out
    assert "OK" in out
