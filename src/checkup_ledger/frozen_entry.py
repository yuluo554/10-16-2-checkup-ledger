"""冻结产物入口薄壳（PyInstaller 的入口脚本）。

为什么单独一个薄壳，而不是直接拿 `cli.py` 或 `__main__.py` 当入口：

- PyInstaller 的入口脚本在产物里以 `__main__` 身份执行。`__main__` **没有包上下文**，
  相对导入（`from .cli import main`）在那种身份下直接 ImportError——所以本壳必须用
  **绝对导入**。这条是"产物能起来"的承重件，由 `tests/test_frozen.py` 的 AST 断言守。
- `__main__.py` 是 `python -m checkup_ledger` 通路的入口。两条通路的 `sys.path`
  来源不同（安装记录 / PyInstaller 引导），共用一个文件会让"某条通路悄悄依赖
  另一条通路的路径假设"——那种缺陷只在冻结态暴露。

本壳只做一件事：把 `main()` 的返回值交给 `sys.exit`。不解析参数、不兜异常、
不重复退出码映射——用法错误（exit 2）与四级退出码契约全部由 `cli.main()` 单点负责。
壳里再包一层就会出现第二处口径。
"""

import sys

from checkup_ledger.cli import main

if __name__ == "__main__":
    sys.exit(main())
