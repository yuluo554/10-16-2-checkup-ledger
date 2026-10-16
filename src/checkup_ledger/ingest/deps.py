"""可选依赖守卫：缺 `[pdf]` / `[ocr]` 时走 exit 3 契约，**不裸抛 ImportError**。

**关键纪律：try/except 必须包住"从 import 到调用完成"的整条路径。**
只包 import 行是假门——真实缺依赖常常发生在**调用时**：pdfplumber 在 `open()`
内部才去 import pdfminer，RapidOCR 在**构造引擎**时才去 import onnxruntime。
只包 import 行的写法在这两种情形下都会裸抛 `ModuleNotFoundError`。

故本模块只提供**一个**入口 `run_guarded()`，由它包住整个可调用对象（而不是某一行）。
"""


class MissingDependencyError(RuntimeError):
    """缺可选依赖（CLI 转 exit 3）。"""

    def __init__(self, module, extra, purpose, detail=""):
        self.module = module
        self.extra = extra
        self.purpose = purpose
        self.detail = detail
        message = "缺少可选依赖 %s（能力：%s）。请安装：pip install -e \".[%s]\"" % (
            module,
            purpose,
            extra,
        )
        if detail:
            message += "；底层错误：%s" % detail
        super().__init__(message)


def run_guarded(module, extra, purpose, func):
    """把 `func` 整体包在 `try/except ImportError` 里（func 内**包含**真实 import 与调用）。

    `ModuleNotFoundError` 是 `ImportError` 的子类，故一并被捕获。
    """
    try:
        return func()
    except ImportError as exc:
        raise MissingDependencyError(
            module, extra, purpose, "%s: %s" % (type(exc).__name__, exc)
        ) from exc


def has_dependency(module) -> bool:
    """该模块此刻是否可导入（只用于提示与测试，不参与判定）。"""
    try:
        __import__(module)
    except ImportError:
        return False
    return True
