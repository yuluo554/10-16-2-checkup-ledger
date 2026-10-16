"""运行时数据目录解析：源码态 / 安装态 / 冻结态三分支。

为什么必须三分支：`sys.path` 的来源在三种通路下不同（CWD / 安装记录 /
PyInstaller 引导），**一种通不等于另一种通**。内置区间知识库是运行时必需的
随包数据，解析错了的后果是"冻结产物跑起来但找不到知识库"。

优先级：
1. 环境变量 `CHECKUP_LEDGER_DATA`（显式覆盖；测试与演示**一律显式传**，
   避免副作用型缺省值）
2. 冻结态（`sys.frozen` / `_MEIPASS`）→ exe 旁的数据目录
3. 源码态 / 安装态 → 本包内 `data/`（`pip install` 会把它装进 site-packages）
"""

import os
import sys

from checkup_ledger.exit_codes import EXIT_FINDINGS, EXIT_OK

_ENV_OVERRIDE = "CHECKUP_LEDGER_DATA"
_PACKAGE_DATA_DIRNAME = "data"
_INDICATORS_FILENAME = "indicators.yaml"


class DataDirError(RuntimeError):
    """运行时数据目录解析失败。"""


def package_root() -> str:
    """本包所在目录（源码态 = <repo>/src/checkup_ledger；安装态 = site-packages/checkup_ledger）。"""
    return os.path.dirname(os.path.abspath(__file__))


def is_frozen() -> bool:
    """是否运行在冻结产物中（PyInstaller）。"""
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def frozen_root() -> str:
    """冻结产物的数据根：exe 所在目录（`_MEIPASS` 为打包内临时解包目录）。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.abspath(meipass)
    return os.path.dirname(os.path.abspath(sys.executable))


def resolve_data_dir(explicit=None) -> str:
    """解析运行时数据目录。

    `explicit` 为 None 时才走环境变量与自动发现——测试/演示须显式传入。
    """
    if explicit:
        candidate = os.path.abspath(os.fspath(explicit))
        if not os.path.isdir(candidate):
            raise DataDirError("指定的数据目录不存在：%s" % candidate)
        return candidate

    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        candidate = os.path.abspath(override)
        if not os.path.isdir(candidate):
            raise DataDirError("%s 指向的目录不存在：%s" % (_ENV_OVERRIDE, candidate))
        return candidate

    if is_frozen():
        candidate = os.path.join(frozen_root(), _PACKAGE_DATA_DIRNAME)
        if os.path.isdir(candidate):
            return candidate
        # 冻结态找不到随包数据是硬错误：明确报出，不静默回落。
        raise DataDirError(
            "冻结态未找到随包数据目录：%s（打包白名单可能漏拷）" % candidate
        )

    candidate = os.path.join(package_root(), _PACKAGE_DATA_DIRNAME)
    if os.path.isdir(candidate):
        return candidate

    raise DataDirError("未找到随包数据目录：%s" % candidate)


def indicators_path(explicit=None) -> str:
    """内置区间知识库路径。"""
    return os.path.join(resolve_data_dir(explicit), _INDICATORS_FILENAME)


def data_dir_in_frozen_root(explicit=None) -> int:
    """冻结态自检：断言数据目录落在 exe 目录内。非冻结态不报 FAIL。"""
    if not is_frozen():
        return EXIT_OK
    resolved = os.path.abspath(resolve_data_dir(explicit))
    root = os.path.abspath(frozen_root())
    try:
        if os.path.commonpath([resolved, root]) != root:
            return EXIT_FINDINGS
    except ValueError:
        return EXIT_FINDINGS
    return EXIT_OK
