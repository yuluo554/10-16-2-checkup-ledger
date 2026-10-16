"""零字面量门禁：区间数值**只能在知识库一处定义**。

判据：把 `indicators.yaml` 里全部上下限数值实算成一个 token 集，然后扫描
`src/` / `tools/` / `tests/` 的**全部源码文本**（含 docstring、注释、字符串字面量），
出现任一 token 即红。

三条设计决定，逐条说清为什么：

1. **token 集从 YAML 实算，不手写。**
   手写清单会在 YAML 增删条目时静默过期——门还在，守的范围已不是当前数据。

2. **扫描面是源码全文（含注释/docstring/字符串），不是 AST 数值常量。**
   破坏"只在 YAML 一处定义"的方式不止"写进比较式"一种：把一对端点抄进一句
   注释、一条 docstring、一个错误消息，同样让**改 YAML 改不动它**，读者还会
   以为那是权威口径。

3. **匹配用词边界 + 连字符数字串排除（精度规则，不是豁免）。**
   日期与标识符里的数字片段（形如 `YYYY-MM-DD`、`case-NNN`）不是独立数值。
   排除"前一个字符是连字符"的匹配，把这类噪声滤掉——这是**匹配精度**，不是
   放行某个区间数值。

豁免口径（**写死，且只有两类**）：

- **结构常数**：索引、长度、切片、正负号这类结构值（`STRUCTURAL_EXEMPT`）。
- **`EXEMPT_FILES` 里逐个登记的例外**，每条必须写理由，且由
  `test_exempt_files_are_exactly_as_declared` 锁死清单内容——新增例外必须
  显式改这个字典，不可能"悄悄多一个文件"。

**防御性常数不是豁免理由**：给"万一"留的兜底数值若恰好等于某个区间端点，
它同样是"第二处定义"，照样红。

**本文件自身也不得写出区间数值**：本门禁的 docstring 与注释若引用了具体端点，
它自己就是命中源。故本文件一律用"某端点""区间上限"这类**指代**，不落数字。
"""

import io
import os
import re
import tokenize

from helpers import iter_python_files, read_text, repo_path

YAML_PATH = "src/checkup_ledger/data/indicators.yaml"

# 结构常数豁免（口径写死在 plan/04 第二节第 3 条）
STRUCTURAL_EXEMPT = frozenset({0.0, 1.0, 2.0, -1.0})

# 文件级例外：**只有一条**，且必须写清理由。清单由测试锁死（改这里必须同步改测试）。
EXEMPT_FILES = {
    "tools/pii_gate.py": (
        "PII 模式里手机号的位数（正则重复次数与提示文案里的位数）与知识库两个区间端点"
        "数值巧合相同。它们是 PII 模式的**结构位数**，与检验参考区间毫无关系；"
        "为一个巧合去改写已通过测试的安全正则，是让门牵着被测代码走。"
    ),
}

# 词边界数值匹配：
# - 前不接标识符字符、小数点、连字符（连字符排除日期与 `case-NNN` 这类片段）；
# - 后不接标识符字符、小数点。
# 这样抄进注释的裸端点会被抓到，而日期/标识符片段与单位写法（十的幂写法）不会误报。
_NUMBER_RE = re.compile(r"(?<![\w.\-])(\d+(?:\.\d+)?)(?![\w.])")


def load_yaml_tokens():
    """从知识库**实算** token 集（全部上下限数值，去掉结构常数豁免）。"""
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


def scan_text(text, tokens):
    """对任意文本跑同一套扫描逻辑（自证与文件扫描共用，避免两套口径）。

    返回 [(行号, 字面量, 片段), ...]。
    """
    hits = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError):
        # 取词失败不静默跳过——退回逐行正则（更严，不是更松）
        for line_no, line in enumerate(text.splitlines(), 1):
            for match in _NUMBER_RE.finditer(line):
                if _is_token(match.group(1), tokens):
                    hits.append((line_no, match.group(1), line.strip()[:80]))
        return hits

    for token in toks:
        if token.type not in (tokenize.NUMBER, tokenize.STRING, tokenize.COMMENT):
            continue
        for match in _NUMBER_RE.finditer(token.string):
            if _is_token(match.group(1), tokens):
                hits.append((token.start[0], match.group(1), token.string.strip()[:80]))
    return hits


def _is_token(literal, tokens):
    try:
        return float(literal) in tokens
    except ValueError:
        return False


def find_literal_thresholds(rel_path, tokens):
    """该文件里出现的区间数值字面量。"""
    return scan_text(read_text(rel_path), tokens)


# ---------------------------------------------------------------- 门


def test_token_set_is_computed_from_yaml_not_hardcoded():
    """token 集必须来自 YAML 实算——手写清单会在数据变动时静默过期。"""
    tokens = load_yaml_tokens()
    assert tokens, "实算 token 集为空（探针失效）"
    assert not (STRUCTURAL_EXEMPT & tokens), (
        "结构常数未被豁免：%s" % sorted(STRUCTURAL_EXEMPT & tokens)
    )


def test_yaml_is_the_single_definition_site():
    """知识库自身当然是"定义处"——断言它确实含这些数值（防"门扫了个空集"）。"""
    import yaml

    with open(repo_path(YAML_PATH), "r", encoding="utf-8") as handle:
        root = yaml.safe_load(handle)
    found = 0
    for entry in root["indicators"]:
        default_range = entry.get("default_range") or {}
        for key in ("low", "high"):
            if default_range.get(key) is not None:
                found += 1
    assert found > 0, "知识库没有任何区间数值——零字面量门禁将退化为空扫描"


def test_no_range_literals_in_source_tools_tests():
    """扫描面 = src/ + tools/ + tests/ 全部 .py 的全文（含注释/docstring/字符串）。

    本门禁自身也在扫描面内——它的 docstring 与注释若引用具体端点，它就是命中源。
    故本文件一律用"某端点"这类指代，不落数字。
    """
    tokens = load_yaml_tokens()
    offenders = []
    scanned = 0
    for rel in iter_python_files():
        if rel in EXEMPT_FILES:
            continue
        scanned += 1
        for line_no, literal, snippet in find_literal_thresholds(rel, tokens):
            offenders.append("%s:%d 出现区间数值 %s —— %s" % (rel, line_no, literal, snippet))
    assert scanned > 0, "扫描面为空：未找到任何 Python 文件（门自身失效）"
    assert not offenders, (
        "以下位置出现区间数值字面量——区间数值只能在 %s 一处定义"
        "（改 YAML 改不动它们，读者还会误以为那是权威口径）：\n%s"
        % (YAML_PATH, "\n".join(offenders))
    )


def test_engine_module_has_no_range_numbers():
    """承重断言：判定内核（区间数值的唯一消费者）必须在扫描面内且零命中。"""
    tokens = load_yaml_tokens()
    hits = find_literal_thresholds("src/checkup_ledger/engine/compare.py", tokens)
    assert not hits, "判定内核出现区间数值字面量：%s" % hits


def test_exempt_files_are_exactly_as_declared():
    """豁免清单必须精确——模糊豁免会让门对某类文件整体失效。

    这条同时是"清单不许悄悄长大"的锁：新增例外必须显式改 `EXEMPT_FILES` 与本断言。
    """
    assert list(EXEMPT_FILES) == ["tools/pii_gate.py"], (
        "豁免清单与声明不符——新增豁免必须同时更新本断言"
    )
    reason = EXEMPT_FILES["tools/pii_gate.py"]
    assert "结构位数" in reason and "巧合" in reason, "豁免理由缺失关键说明"


def test_exempt_files_all_exist_and_carry_reasons():
    """豁免的每个文件都要真实存在且理由非空——防"豁免一个不存在的路径"混过。"""
    for rel, reason in EXEMPT_FILES.items():
        assert os.path.isfile(repo_path(rel)), "豁免文件不存在：%s" % rel
        assert reason.strip(), "豁免理由为空：%s" % rel


# ---------------------------------------------------------------- 自证（扫描面够不够宽/够不够准）


def test_scanner_detects_literal_in_comment_docstring_and_string():
    """自证：token 塞进注释/docstring/字符串，扫描器都必须抓到。

    只扫 AST 数值常量的实现会在这里红——这正是"扫描面够宽"的证明。
    """
    tokens = load_yaml_tokens()
    literal = _format_probe(sorted(tokens)[0])
    samples = {
        "注释": "# 这里抄了个区间端点 %s\nx = 1\n" % literal,
        "docstring": 'def f():\n    """区间上限 %s。"""\n    return 1\n' % literal,
        "字符串": 'MESSAGE = "上限 %s"\n' % literal,
    }
    for label, text in samples.items():
        hits = scan_text(text, tokens)
        assert hits, "扫描器漏掉了%s里的区间数值 %s（扫描面不够宽）" % (label, literal)


def test_scanner_ignores_dates_and_identifiers():
    """自证反向：日期片段与标识符里的数字**不得**被当成命中——否则门会误报。

    这条锁住"连字符数字串排除"这条精度规则：日期尾部与 `case-NNN` 的编号
    都不是独立数值。
    """
    tokens = load_yaml_tokens()
    # 构造"日期/标识符片段恰好等于某 token"的形态
    probe = _format_probe(sorted(tokens)[0])
    text = 'DATE = "2024-01-%s"\ncase_%s = 1\n' % (probe.zfill(2), probe.zfill(3))
    hits = scan_text(text, tokens)
    assert not hits, "日期/标识符片段被误判为区间字面量：%s" % hits


def test_scanner_still_catches_bare_number_in_code():
    """自证正向：裸写在代码里的同一数值必须被抓到（精度规则没有把门放宽成筛子）。"""
    tokens = load_yaml_tokens()
    literal = _format_probe(sorted(tokens)[0])
    hits = scan_text("LIMIT = %s\n" % literal, tokens)
    assert hits, "裸写的区间数值未被抓到（门被放宽成筛子）"


def _format_probe(value):
    if float(value).is_integer():
        return str(int(value))
    return repr(value)
