"""模块① 输入层的自有错误类型。

与 `deps.MissingDependencyError` 分开：**"缺依赖"与"输入有问题"是两件事**，
退出码也不同（3 与 1）。混成一个类型会让 CLI 无法区分，最后只能一律报同一个码。
"""


class IngestError(RuntimeError):
    """输入层错误：文件不存在 / 类型不支持 / 复核记录与待复核队列对不上。"""
