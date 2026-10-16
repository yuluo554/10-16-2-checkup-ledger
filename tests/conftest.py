"""测试期路径装配。

`tools/` 下的模块（`fixtures.*` 夹具写出器、`pii_gate`、生成器）是**仓库脚本**，
不是安装面的一部分，故 `pytest` 默认找不到它们。这里把 `tools/` 加进 `sys.path`，
让测试能直接 import 夹具写出器（`from fixtures import pdfwrite`）。

为什么用 `conftest.py` 而不是在每个测试里塞 `sys.path.insert`：
每个文件各写一遍，早晚有一个漏了——那时失败信息是 `ModuleNotFoundError`，
与"这个模块真的不存在"无法区分。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
TOOLS_ROOT = os.path.join(REPO_ROOT, "tools")

if TOOLS_ROOT not in sys.path:
    sys.path.insert(0, TOOLS_ROOT)
