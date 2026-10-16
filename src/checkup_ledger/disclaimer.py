"""首启免责声明：第一次运行落一次标记文件，之后不再重复念。

借鉴 bloodio 的"首启免责"范式。设计要点与**为什么不这样做**：

1. **标记文件落在用户主目录**（`~/.checkup_ledger/accepted`），不落在仓库/包内：
   它是**用户级**接受状态，不是交付物的一部分；落包内会让"装一次 = 所有人接受过"。
2. **写不进去不算失败**：只读文件系统、权限受限的环境下写标记会失败——那时
   免责**照样打印**（宁可多念一次，不可漏念一次）。故 `mark_accepted()` 的失败
   被吞掉，而 `needs_disclaimer()` 在写失败时恒为 True。
3. **标记文件只记"接受过"这一个事实**：不写时间戳、不写机器名、不写任何可识别
   信息（这是隐私红线的一部分——一个免责标记不该变成指纹）。
4. **纯本地**：本模块不联网、不上报。"接受"只对本地文件系统有意义。

`home` 与 `env` 都可由调用方显式传入（测试不许去动真实主目录——那是用户的家）。
"""

import os
from typing import Optional

DISCLAIMER_TEXT = (
    "免责声明：本工具不是医疗器械，不构成诊断依据。它只做数值与参考区间的机械比较"
    "（H / L）与纵向趋势展示，不做诊断、不做解读、不做分诊、不做治疗意见。"
    "各医疗机构的 LIS 打印区间为最终准绳，一切以报告单和医嘱为准。"
    "本工具纯本地运行：不联网、不上传、不遥测。"
)

ENV_ACCEPTED_PATH = "CHECKUP_LEDGER_ACCEPTED"
_DIRNAME = ".checkup_ledger"
_FILENAME = "accepted"
# 标记内容：**不写时间戳**（时间戳是身份线索，且会让"双跑一致"类断言变复杂）。
_MARK = "accepted\n"


def accepted_path(home: Optional[str] = None, env=None) -> str:
    """标记文件路径。

    解析顺序：显式 `home` → 环境变量 `CHECKUP_LEDGER_ACCEPTED`（整文件路径，
    测试与演示用）→ `~/.checkup_ledger/accepted`。
    """
    environment = os.environ if env is None else env
    override = environment.get(ENV_ACCEPTED_PATH)
    if override:
        return os.path.abspath(override)
    base = home if home is not None else os.path.expanduser("~")
    return os.path.join(os.path.abspath(base), _DIRNAME, _FILENAME)


def is_accepted(home: Optional[str] = None, env=None) -> bool:
    """是否已接受过免责声明（标记文件在位即视为接受过）。"""
    return os.path.isfile(accepted_path(home, env))


def mark_accepted(home: Optional[str] = None, env=None) -> bool:
    """落标记文件。返回是否写入成功。

    **失败不抛错**：写不进去（只读盘/权限）时免责照样打印，只是每次都会再念一遍。
    把"写不进去"当错误会让只读环境直接跑不了工具——那比多念一次免责糟得多。
    """
    from checkup_ledger.serialize import write_atomic

    target = accepted_path(home, env)
    try:
        write_atomic(target, _MARK)
    except (OSError, ValueError):
        # `ValueError` 也要接住：路径里含非法字符（如内嵌 NUL）时 `os.makedirs`
        # 抛的是 ValueError 而不是 OSError。只接 OSError 会让"写不进去"从
        # "多念一次免责"变成"工具直接崩"——那正是本函数要避免的结果。
        return False
    return True


def needs_disclaimer(home: Optional[str] = None, env=None) -> bool:
    """本次运行是否需要打印免责（未接受过 → 需要）。"""
    return not is_accepted(home, env)


def first_run_banner(home: Optional[str] = None, env=None) -> str:
    """首启横幅文本（未接受过时返回全文，否则空串）。

    调用方拿到非空串就打印 + 调 `mark_accepted()`。**打印与落标记是两步**：
    先打印再落标记，即使落标记失败，用户也已经看到了免责。
    """
    if not needs_disclaimer(home, env):
        return ""
    return DISCLAIMER_TEXT
