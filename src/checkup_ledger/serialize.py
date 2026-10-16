"""确定性写盘单点。

**所有产物一律经本模块写出**，禁止各子命令各写各的 `open()+json.dump()`——
判别：换一个子命令，写盘形态会变吗？会变 = 迟早出现"一个带 BOM 一个不带 /
一个 sort_keys 一个不排"的漂移。

序列化契约（冻结，写进 plan/02 第七节）：
- JSON：`sort_keys=True` + `ensure_ascii=False` + `indent=2`
- 行尾：LF
- 结尾：单个换行

`ensure_ascii=False` 是中文项目的**必选项**——默认 `True` 会把中文转 `\\uXXXX`，
diff 不可读，与人读产物的定位直接矛盾。

写盘为**原子**（写临时文件再 `os.replace`），防中断留下半个产物。
"""

import json
import os
import tempfile
from typing import Any, List

JSON_INDENT = 2


def to_json_text(payload: Any) -> str:
    """canonical JSON 文本（LF 行尾 + 结尾换行）。"""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=JSON_INDENT)
    return text.replace("\r\n", "\n") + "\n"


def to_json_bytes(payload: Any) -> bytes:
    """canonical JSON 字节。"""
    return to_json_text(payload).encode("utf-8")


def write_atomic(path, data) -> None:
    """原子写：同目录临时文件 → flush/fsync → os.replace。

    `data` 可为 str（按 UTF-8 + LF 写出）或 bytes（原样写出）。
    """
    target = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(target))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    if isinstance(data, bytes):
        payload = data
    else:
        payload = str(data).replace("\r\n", "\n").encode("utf-8")

    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        _unlink_quietly(tmp)
        raise


def write_json(path, payload: Any) -> None:
    """canonical JSON 写盘（原子）。"""
    write_atomic(path, to_json_bytes(payload))


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def find_leftover_temp_files(directory) -> List[str]:
    """扫描残留的临时写盘文件（自检用，证明原子写不留半个产物）。"""
    root = os.fspath(directory)
    if not os.path.isdir(root):
        return []
    leftovers = []
    for name in sorted(os.listdir(root)):
        if name.startswith(".tmp-") and name.endswith(".part"):
            leftovers.append(name)
    return leftovers
