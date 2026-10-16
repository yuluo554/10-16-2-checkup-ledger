"""测试期共享辅助：定位仓库根、加载本包、跑 CLI（不装包也能跑）。"""

import io
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(REPO_ROOT, "src")

if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

# 免责标记的环境变量名（与 `checkup_ledger.disclaimer.ENV_ACCEPTED_PATH` 同源）
_ACCEPTED_ENV = "CHECKUP_LEDGER_ACCEPTED"

# 测试期的隔离主目录：**测试永不写真实 `~`**。
#
# 为什么要这一条（实测抓到的真缺陷）：`ledger`/`export`/`report` 三个命令会经
# `main()` 触发首启免责，把标记落到 `~/.checkup_ledger/accepted`。测试若直接调
# `main()`，就会在**开发者/CI 机器的真实主目录**里留下文件——测试污染用户环境，
# 且第二次运行起免责不再打印（后续用例再也测不到首启行为）。
# 故这里把免责标记重定向到一个仓库外的一次性目录（进程级，模块导入时设一次）。
_ISOLATED_HOME = tempfile.mkdtemp(prefix="checkup-ledger-test-home-")
os.environ.setdefault(_ACCEPTED_ENV, os.path.join(_ISOLATED_HOME, "accepted"))


def repo_path(*parts) -> str:
    return os.path.join(REPO_ROOT, *parts)


def read_text(rel_path) -> str:
    with open(repo_path(rel_path), "r", encoding="utf-8") as handle:
        return handle.read()


def run_cli(argv=None):
    """跑 CLI 主函数，返回 (退出码, stdout, stderr)。

    注意断言要落在 `out.getvalue()` / `err.getvalue()` 上——对 StringIO **对象**
    做 `in` 判断是按整对象行匹配，中文消息会静默假失败。

    免责标记已由本模块导入时重定向到隔离目录（见上方注记）——但**显式传参的用例
    仍应自己传 `home`/env**，不依赖这条兜底（兜底只保证"不污染真实主目录"，
    不保证"每个用例都拿到干净状态"）。
    """
    from checkup_ledger.cli import main

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv if argv is not None else [])
    return code, out.getvalue(), err.getvalue()


# 扫描面排除项：虚拟环境 / 构建产物 / 缓存（这些不是"仓库内容"，
# 且第三方包里必然出现与 PII 形态巧合的字符串——不排除就是拿别人的包误报）
EXCLUDED_DIR_PREFIXES = (
    ".venv", "venv", "env", ".eggs", "build", "dist", "__pycache__",
    ".git", "node_modules", ".tox", ".mypy_cache", ".pytest_cache",
)


def _is_excluded(rel_path):
    parts = rel_path.replace("\\", "/").split("/")
    for part in parts[:-1]:
        for prefix in EXCLUDED_DIR_PREFIXES:
            if part == prefix or part.startswith(".venv") or part.startswith("venv"):
                return True
    return False


def tracked_files():
    """仓库内**会入库**的文件（相对仓库根，POSIX 形式）。

    用 `git ls-files --cached --others --exclude-standard`：既含已提交文件，也含
    新增未提交文件（**否则新写的源码不在扫描面里，门禁对着旧快照空转**——
    判据 = "这个文件此刻会在仓库里吗"，而不是"它曾被提交过吗"）。
    `--exclude-standard` 已排除 .gitignore 命中项；不在 git 环境时回落 os.walk
    并手动排除虚拟环境/构建产物。

    子进程显式传 encoding：`text=True` 走 locale，中文文件名在 cp1252 下会
    UnicodeDecodeError（无环境变量可替代）。
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=REPO_ROOT,
        )
        if result.returncode == 0:
            raw = result.stdout.decode("utf-8", "replace")
            files = [item for item in raw.split("\0") if item.strip()]
            if files:
                return [item for item in files if not _is_excluded(item)]
    except OSError:
        pass

    files = []
    for root, dirs, names in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if not _is_excluded(d + "/x")]
        for name in names:
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, REPO_ROOT).replace(os.sep, "/")
            if not _is_excluded(rel):
                files.append(rel)
    return sorted(files)


def iter_source_files():
    """本包源码文件（相对仓库根）。"""
    for rel in tracked_files():
        if rel.startswith("src/") and rel.endswith(".py"):
            yield rel


def iter_python_files():
    """仓库内全部 Python 文件（src + tools + tests）。"""
    for rel in tracked_files():
        if rel.endswith(".py") and rel.split("/")[0] in ("src", "tools", "tests"):
            yield rel


# ---------------------------------------------------------------- 区间夹具（唯一来源 = 知识库）

_INDICATORS_YAML = os.path.join(SRC_ROOT, "checkup_ledger", "data", "indicators.yaml")


def yaml_bounds(canonical_name):
    """从内置知识库取某条目的区间（**测试夹具的唯一来源**）。

    测试里凡是需要"一个区间"的地方都从这里取。否则测试就成了区间数值的
    **第二处定义**：改 YAML 改不动它们，断言退化成对陈年数字的自我确认
    （零字面量门禁扫 tests/ 正是为了拦这个）。
    """
    import yaml

    with open(_INDICATORS_YAML, "r", encoding="utf-8") as handle:
        root = yaml.safe_load(handle)
    for entry in root["indicators"]:
        if entry["canonical_name"] == canonical_name:
            rng = entry.get("default_range") or {}
            applies = entry.get("applies_to") or {}
            return {
                "low": rng.get("low"),
                "high": rng.get("high"),
                "bounds": rng.get("bounds", "closed"),
                "unit": entry["unit"],
                "sex": applies.get("sex", "any"),
            }
    raise KeyError("知识库无此条目：%s" % canonical_name)


def bounds_pair(canonical_name):
    """某条目的 (low, high) 数值对。"""
    spec = yaml_bounds(canonical_name)
    return spec["low"], spec["high"]


def step_of(value):
    """该数值的步长 = 10^(-小数位)，由 YAML 的写法实算（不写精度常数）。

    整数端点的步长为 1；一位小数的端点为 0.1；以此类推。用它构造"刚过边界"
    的探针值，避免在测试里写死小数。
    """
    text = repr(float(value))
    if "." not in text:
        return 1.0
    fraction = text.split(".", 1)[1].rstrip("0")
    return float(10 ** -len(fraction)) if fraction else 1.0


def inline_range(canonical_name, low_delta=0, high_delta=0, bounds=None, invert=False):
    """把某条目的区间渲染成 YAML 片段（供 loader 类测试拼测试用 YAML）。

    测试要验的是 loader 的门禁行为，用哪条区间无所谓——但**不许手写数值**，
    否则那又是一处"改 YAML 改不动"的第二定义。
    """
    spec = _range_spec(canonical_name, low_delta, high_delta, bounds, invert)
    parts = []
    if spec["low"] is not None:
        parts.append("low: %s" % _num(spec["low"]))
    if spec["high"] is not None:
        parts.append("high: %s" % _num(spec["high"]))
    if spec.get("bounds") is not None:
        parts.append("bounds: %s" % spec["bounds"])
    return "{ %s }" % ", ".join(parts)


def range_dict(canonical_name, low_delta=0, high_delta=0, bounds=None, invert=False):
    """把某条目的区间渲染成 dict（供 `gate_entry` 类测试直接构造 raw 条目）。

    `bounds` 为 None 时**不写这个键**——写 `bounds: null` 会被 loader 判成
    "非法边界语义"（正确行为），但那不是本夹具想测的东西。
    """
    spec = _range_spec(canonical_name, low_delta, high_delta, bounds, invert)
    out = {"low": spec["low"], "high": spec["high"]}
    if spec.get("bounds") is not None:
        out["bounds"] = spec["bounds"]
    return out


def _range_spec(canonical_name, low_delta, high_delta, bounds, invert):
    spec = yaml_bounds(canonical_name)
    low, high = spec["low"], spec["high"]
    if low is not None and low_delta:
        low = low + low_delta
    if high is not None and high_delta:
        high = high + high_delta
    if invert:
        low, high = high, low
    out = {"low": low, "high": high, "bounds": bounds}
    return out


def _num(value):
    if float(value).is_integer():
        return str(int(value))
    return repr(value)


# ---------------------------------------------------------------- 区间 token 集（零字面量门禁共用）

YAML_PATH = "src/checkup_ledger/data/indicators.yaml"

# 结构常数豁免（口径写死在 plan/04 第二节第 3 条）
STRUCTURAL_EXEMPT = frozenset({0.0, 1.0, 2.0, -1.0})


def load_yaml_tokens():
    """从知识库**实算**区间端点 token 集（去掉结构常数豁免）。

    **唯一实算处**：零字面量门禁（`test_no_literal_thresholds.py`）与各层的
    "本层不得出现区间端点"子门（`test_layering.py`）共用本函数。各门自写一份
    实算逻辑 = token 集有多份口径，改 YAML 时有的门更新、有的没更新
    （旧口径的门会静默放过新增端点的抄袭）。
    """
    import yaml

    path = repo_path(YAML_PATH)
    assert os.path.isfile(path), "知识库文件不存在：%s" % YAML_PATH
    with open(path, "r", encoding="utf-8") as handle:
        root = yaml.safe_load(handle)

    indicators = root.get("indicators")
    assert isinstance(indicators, list) and indicators, "知识库 indicators 为空（探针失效）"

    tokens = set()
    for entry in indicators:
        default_range = entry.get("default_range") or {}
        for key in ("low", "high"):
            value = default_range.get(key)
            if value is None or isinstance(value, bool):
                continue
            if not isinstance(value, (int, float)):
                continue
            tokens.add(float(value))

    tokens -= STRUCTURAL_EXEMPT
    assert tokens, "token 集为空（知识库没有任何区间数值？探针失效）"
    return tokens
