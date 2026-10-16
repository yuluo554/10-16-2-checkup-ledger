"""运行时配置文件加载（**阈值等判定相关数值的单点定义处**）。

为什么要有这个模块：`ocr_threshold` 这类数值一旦在代码里留一个"顺手"的默认值，
它就成了**第二处定义**——改配置改不动它，而且静默生效：
用户以为自己在调阈值，实际代码里的字面值赢了。故本模块的纪律是：

1. **代码零默认值**：缺字段/缺文件一律抛 `ConfigError`，**绝不回落**到某个字面值；
2. 数值只在本文件读出的对象里出现一次，调用方从 `Config` 取，不得自带兜底；
3. 加载失败是**可报出的错误**（CLI 转 exit 1），不是"当作没配置"。

本模块只读一个文件，不联网。
"""

import os
from typing import Optional

CONFIG_FILENAME = "config.yaml"
OCR_THRESHOLD_KEY = "ocr_threshold"
SCHEMA_VERSION = 1


class ConfigError(RuntimeError):
    """配置文件缺失、格式非法或缺必需字段。"""


class Config:
    """运行时配置。字段一旦缺省即视为配置缺陷（无代码兜底）。"""

    __slots__ = ("ocr_threshold", "schema_version")

    def __init__(self, ocr_threshold: float, schema_version: int = SCHEMA_VERSION):
        self.ocr_threshold = ocr_threshold
        self.schema_version = schema_version

    def __repr__(self) -> str:  # pragma: no cover - 调试便利
        return "Config(ocr_threshold=%r)" % (self.ocr_threshold,)


def config_path(explicit=None) -> str:
    """配置文件路径：显式传参优先，否则落在随包数据目录内。

    与 `paths.indicators_path` 同源：配置文件与知识库一样是**运行时必需**的随包数据。
    """
    if explicit:
        return os.path.abspath(os.fspath(explicit))
    from checkup_ledger.paths import resolve_data_dir

    return os.path.join(resolve_data_dir(), CONFIG_FILENAME)


def _require_mapping(node, where: str) -> dict:
    if not isinstance(node, dict):
        raise ConfigError("%s 应为映射（mapping），实为 %s" % (where, type(node).__name__))
    return node


def load_config(path=None, explicit=None) -> Config:
    """加载配置。文件缺失/字段缺失/类型非法 → `ConfigError`（不静默取默认值）。"""
    target = os.fspath(path) if path is not None else config_path(explicit)
    if not os.path.isfile(target):
        raise ConfigError(
            "配置文件不存在：%s（阈值等判定参数必须来自配置，代码不留默认值）" % target
        )

    try:
        import yaml  # 局部导入：缺 PyYAML 时报可读提示而非裸 ImportError
    except ImportError as exc:  # pragma: no cover - 核心依赖缺失属环境问题
        raise ConfigError("需要 PyYAML 解析配置文件（pip install PyYAML>=6.0）：%s" % exc)

    with open(target, "r", encoding="utf-8") as handle:
        try:
            root = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ConfigError("配置文件 YAML 解析失败：%s" % exc)

    root = _require_mapping(root, "配置根节点")
    version = root.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ConfigError("不支持的 schema_version：%r（本版本只认 %d）" % (version, SCHEMA_VERSION))

    if OCR_THRESHOLD_KEY not in root:
        raise ConfigError(
            "配置缺 %s 字段（阈值必须单点定义在配置里，代码不得留默认值）" % OCR_THRESHOLD_KEY
        )
    raw = root[OCR_THRESHOLD_KEY]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ConfigError("%s 应为数值，实为 %r" % (OCR_THRESHOLD_KEY, raw))
    threshold = float(raw)
    if not 0.0 <= threshold <= 1.0:
        raise ConfigError("%s 应落在 [0, 1]，实为 %r" % (OCR_THRESHOLD_KEY, raw))

    return Config(ocr_threshold=threshold, schema_version=int(version))


def resolve_threshold(explicit_path: Optional[str] = None) -> float:
    """便捷取阈值（CLI 用）。**仍然没有默认值**——缺配置即抛错。"""
    return load_config(explicit=explicit_path).ocr_threshold
