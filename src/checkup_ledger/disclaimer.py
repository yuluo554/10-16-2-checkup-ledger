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

5. **主目录解不出来时不臆造一个 `~` 目录**（M5 实测抓到的真缺陷）：`os.path.expanduser("~")`
   在环境里没有 `USERPROFILE`/`HOMEDRIVE`+`HOMEPATH`/`HOME` 时**原样返回字符串 `~`**，
   经 `abspath` 就变成"当前工作目录下的 `~` 文件夹"。实测场景：`env -i` 下跑冻结产物
   （`ledger` 触发首启免责）→ 仓库根多出一个 `~/.checkup_ledger/accepted`。
   这是**用户可见的污染**，而且发生在"零上传、不写用户没让写的地方"这种承诺上。
   处置与第 2 条同向：解不出主目录 = 没有可写的标记位置 → **不写**，
   按"未接受"处理（免责照念）。**不回落 CWD**——那等于替用户在他没指定的地方建目录。
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

# `expanduser` 解不出主目录时原样返回的字面量（见模块 docstring 第 5 条）。
_HOME_SENTINEL = "~"

# 模块级别名：测试要模拟"环境里没有主目录变量"，若直接打桩 `os.path.expanduser`，
# 改的是**标准库函数对象本身**——整个 pytest 进程里所有代码都会受影响。
# 打桩这个本地别名才是外科手术（同族纪律：`paths.is_frozen` 也是这么被打桩的）。
_expanduser = os.path.expanduser


def home_dir(home: Optional[str] = None) -> Optional[str]:
    """解析用户主目录；**解不出来返回 `None`**（绝不返回字面 `~`）。

    判据是"解析结果是否仍是那个哨兵字符串"——`expanduser` 在无主目录变量时
    原样返回 `~`，故它与输入相同即等于"解不出来"。
    """
    if home is not None:
        candidate = os.fspath(home)
        if not candidate.strip() or candidate.strip() == _HOME_SENTINEL:
            return None
        return os.path.abspath(_expanduser(candidate))
    expanded = _expanduser(_HOME_SENTINEL)
    if expanded == _HOME_SENTINEL:
        return None
    return os.path.abspath(expanded)


def accepted_path(home: Optional[str] = None, env=None) -> Optional[str]:
    """标记文件路径；**主目录解不出来时返回 `None`**（调用方按"无标记"处理）。

    解析顺序：显式 `home` → 环境变量 `CHECKUP_LEDGER_ACCEPTED`（整文件路径，
    测试与演示用）→ `~/.checkup_ledger/accepted`。
    """
    environment = os.environ if env is None else env
    override = environment.get(ENV_ACCEPTED_PATH)
    if override:
        return os.path.abspath(override)
    base = home_dir(home)
    if base is None:
        return None
    return os.path.join(base, _DIRNAME, _FILENAME)


def is_accepted(home: Optional[str] = None, env=None) -> bool:
    """是否已接受过免责声明（标记文件在位即视为接受过）。

    解不出标记路径（无主目录）→ 视为**未接受**：免责照念，但不去 CWD 里建目录。
    """
    target = accepted_path(home, env)
    return bool(target) and os.path.isfile(target)


def mark_accepted(home: Optional[str] = None, env=None) -> bool:
    """落标记文件。返回是否写入成功。

    **失败不抛错**：写不进去（只读盘/权限）时免责照样打印，只是每次都会再念一遍。
    把"写不进去"当错误会让只读环境直接跑不了工具——那比多念一次免责糟得多。
    **解不出主目录同样返回 `False`**（不写、不抛、不回落 CWD）。
    """
    from checkup_ledger.serialize import write_atomic

    target = accepted_path(home, env)
    if not target:
        return False
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
