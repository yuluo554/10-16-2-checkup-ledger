"""样例集与真值库的门禁：把"真值不能退化成比对两份预置答案"变成可执行断言。

三道门（缺一道就有一种假绿）：

1. **真值库不得出现观测类字段**（`observed`/`actual`/`got`…）。
   冻结的若是"观测"，基准就退化成"比对两份预先算好的答案"——引擎全坏也全绿。
   观测必须由观测器在基准运行时**实算**。

2. **真值与引擎共用同一处判定规则**（`engine.compare`），禁止手写第二口径。
   判据 = 真值生成器源码里不得出现自己的边界比较（`> <` 之类），且它确实
   `import` 了引擎。复制一份判定逻辑 = 改一处漏一处，真值跟着引擎一起错。

3. **生成器确定性**：不许 import `random`/`time`/`datetime`，不许用 `set` 做
   取值来源，产物不含时间戳——任何一条破了，"两次运行逐字节一致"都会随机红。
"""

import ast
import os
import re

import pytest

from helpers import read_text, repo_path, run_cli

GEN_PATH = "tools/gen_samples.py"
SAMPLES_DIR = "data/samples"
TRUTH_DIR = "data/samples/truth"
MANIFEST_PATH = "data/samples/manifest.json"

FORBIDDEN_TRUTH_FIELDS = ("observed", "actual", "got", "computed", "result")


def _truth_files():
    base = repo_path(TRUTH_DIR.replace("/", os.sep))
    assert os.path.isdir(base), "真值目录不存在：%s（先跑 tools/gen_samples.py）" % TRUTH_DIR
    names = sorted(name for name in os.listdir(base) if name.endswith(".truth.json"))
    assert names, "真值目录为空：%s" % TRUTH_DIR
    return [os.path.join(base, name) for name in names]


# ---------------------------------------------------------------- 门 1：真值无观测字段


def _iter_keys(node):
    """递归产出 JSON 结构里的全部键名。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            for item in _iter_keys(value):
                yield item
    elif isinstance(node, list):
        for item in node:
            for key in _iter_keys(item):
                yield key


def test_truth_files_contain_no_observed_fields():
    """真值库只存"输入与期望"——出现观测类字段即红。

    这条是基准可信度的地基：真值里若有 `observed`，基准就在比对两份预先算好的
    答案，引擎全坏也全绿。
    """
    import json

    offenders = []
    for path in _truth_files():
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for key in _iter_keys(payload):
            if key.lower() in FORBIDDEN_TRUTH_FIELDS:
                offenders.append("%s 出现字段 %r" % (os.path.basename(path), key))
    assert not offenders, "真值库出现观测类字段（基准会退化成比对预置答案）：%s" % offenders


def test_truth_files_declare_inputs_and_expectations():
    """反向：真值库必须**真的**含输入与期望——否则"无观测字段"可被空文件满足。"""
    import json

    checked = 0
    for path in _truth_files():
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        assert payload.get("case_id"), "%s 缺 case_id" % path
        expected = payload.get("expected")
        assert isinstance(expected, list) and expected, "%s 的 expected 为空" % path
        for item in expected:
            assert "value" in item, "真值条目缺输入值 value：%s" % item
            assert "expected_flag" in item, "真值条目缺期望 expected_flag：%s" % item
            assert "expected_range_source" in item, "真值条目缺期望来源：%s" % item
            checked += 1
    assert checked > 0, "未检查到任何真值条目（探针失效）"


def test_truth_files_carry_no_timestamp():
    """产物无时间戳——时间戳会让"两次运行逐字节一致"随机红。"""
    import json

    stamp = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
    for path in _truth_files():
        text = open(path, "r", encoding="utf-8").read()
        assert not stamp.search(text), "%s 含时间戳" % os.path.basename(path)
        payload = json.loads(text)
        for key in _iter_keys(payload):
            assert key.lower() not in ("generated_at", "timestamp", "created_at"), (
                "%s 含时间戳字段 %r" % (os.path.basename(path), key)
            )


# ---------------------------------------------------------------- 门 2：真值与引擎同源


def _module_imports(path):
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_generator_imports_the_engine():
    """真值生成器必须 import 判定引擎——不 import 就意味着它自算了第二份口径。"""
    imports = _module_imports(repo_path(GEN_PATH))
    assert any("engine" in name for name in imports), (
        "真值生成器未 import 判定引擎：%s" % sorted(imports)
    )
    assert "checkup_ledger.engine.compare" in imports, (
        "真值生成器未从 engine.compare 取判定函数（第二口径风险）"
    )


def test_generator_uses_engine_compare_not_own_comparison():
    """真值生成器不得自己做边界比较——那是手写第二份判定口径。

    判据 = 源码里不出现"拿 value 与区间端点做 `>`/`<`"的比较表达式。
    生成器仍需比较（如按 band 组装取值），故只拦"与 low/high 直接比大小"这一形态。
    """
    source = read_text(GEN_PATH)
    tree = ast.parse(source, filename=GEN_PATH)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # 比较的一端是 value，另一端是 low/high 这类端点名 → 疑似自算判定
        names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.add(child.id)
            elif isinstance(child, ast.Attribute):
                names.add(child.attr)
        if "value" in names and ({"low", "high"} & names):
            offenders.append("line %d: %s" % (node.lineno, ast.dump(node)[:70]))
    assert not offenders, (
        "真值生成器出现「value 与 low/high 直接比大小」——疑似手写第二份判定口径，"
        "应改用 engine.compare()：%s" % offenders
    )


def test_generator_calls_engine_compare():
    """正向：生成器必须**调用** engine 的判定函数（只 import 不用 = 假同源）。"""
    tree = ast.parse(read_text(GEN_PATH), filename=GEN_PATH)
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name:
                called.add(name)
    for required in ("compare", "range_applies_to", "trend_direction"):
        assert required in called, (
            "真值生成器未调用 engine.%s（期望值可能来自自写口径）" % required
        )


# ---------------------------------------------------------------- 门 3：生成器确定性


def test_generator_has_no_nondeterministic_imports():
    """禁 stdlib `random`、禁时钟——它们会让产物不可复现。"""
    banned = ("random", "time", "datetime", "secrets", "uuid", "os.urandom")
    imports = _module_imports(repo_path(GEN_PATH))
    offenders = [name for name in imports if name.split(".")[0] in banned]
    assert not offenders, "生成器 import 了非确定性来源：%s" % offenders


def test_generator_does_not_use_hash_or_set_iteration():
    """禁用 `hash()` 做流键（字符串哈希带随机盐）与 `set` 迭代序。

    CPython 的 `hash(str)` 受 PYTHONHASHSEED 影响——同 key 两次进程不同，
    "两次运行逐字节一致"会随机红。生成器改用自写 FNV-1a 派生流键。
    """
    tree = ast.parse(read_text(GEN_PATH), filename=GEN_PATH)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "hash":
                offenders.append("line %d 调用了 hash()" % node.lineno)
        # `for x in set(...)` / 直接迭代集合字面量
        if isinstance(node, (ast.For, ast.comprehension)):
            iterable = node.iter
            if isinstance(iterable, ast.Call):
                fname = iterable.func.attr if isinstance(iterable.func, ast.Attribute) else getattr(iterable.func, "id", None)
                if fname == "set":
                    offenders.append("line %d 迭代 set()" % node.lineno)
            if isinstance(iterable, ast.Set):
                offenders.append("line %d 迭代集合字面量" % node.lineno)
    assert not offenders, "生成器使用非确定性迭代/哈希：%s" % offenders


def test_generator_writes_via_serialize_single_point():
    """落盘一律经 serialize.write_atomic（写盘单点）。"""
    source = read_text(GEN_PATH)
    assert "write_atomic" in source, "生成器未使用 serialize.write_atomic（写盘不单点）"
    tree = ast.parse(source, filename=GEN_PATH)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in ("dump", "dumps") and isinstance(func, ast.Attribute) \
                    and getattr(func.value, "id", None) == "json":
                raise AssertionError("生成器直接调用 json.dumps（应经 serialize 单点）")


# ---------------------------------------------------------------- 门 4：生成器 --check 位级一致


def test_generator_check_passes():
    """`gen_samples.py --check` 必须绿——再生成与磁盘产物逐字节一致。"""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, repo_path(GEN_PATH), "--check"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=repo_path("."), env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
    )
    output = result.stdout.decode("utf-8", "replace")
    assert result.returncode == 0, "生成器位级一致校验失败：\n%s" % output


# ---------------------------------------------------------------- 门 5：manifest 与覆盖度


def test_manifest_thresholds_are_all_met():
    """manifest 的覆盖度门槛必须逐行达标（采样数 ≥ 下限）。"""
    import json

    with open(repo_path(MANIFEST_PATH), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    thresholds = manifest.get("thresholds")
    assert isinstance(thresholds, list) and thresholds, "manifest 缺 thresholds"
    unmet = [
        "%s/%s：%d < %d" % (item["dimension"], item["form"], item["sampled"], item["minimum"])
        for item in thresholds
        if item["sampled"] < item["minimum"]
    ]
    assert not unmet, "覆盖度门槛未达标：%s" % unmet


def test_manifest_declares_sampling_not_exhaustive():
    """覆盖声明必须显式写"抽样覆盖非穷举"——防"各有件"被读成"全穷举"。"""
    import json

    with open(repo_path(MANIFEST_PATH), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    note = manifest.get("coverage_note", "")
    assert "非穷举" in note, "manifest 未声明抽样覆盖非穷举：%r" % note
    assert manifest.get("generator_seed") is not None, "manifest 未登记生成器 seed"


def test_manifest_registers_every_truth_file():
    """manifest 登记的用例必须与真值目录一一对应（防"生成了但没登记"）。"""
    import json

    with open(repo_path(MANIFEST_PATH), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    registered = {case["case_id"] for case in manifest["cases"]}
    on_disk = {
        name.split(".truth.json")[0] for name in os.listdir(repo_path(TRUTH_DIR))
        if name.endswith(".truth.json")
    }
    assert registered == on_disk, "manifest 与真值目录不一致：登记 %s，磁盘 %s" % (
        sorted(registered - on_disk), sorted(on_disk - registered)
    )


# ---------------------------------------------------------------- 门 6：分层基准


def test_bench_reports_both_layers():
    """基准必须跑两层（规则驱动 + 样例驱动），且两层都真的被启用。"""
    code, out, _err = run_cli(["bench"])
    assert code == 0, "基准未达标：\n%s" % out
    assert "规则驱动层" in out, "基准未包含规则驱动层"
    assert "样例驱动层" in out, "基准未包含样例驱动层"
    assert "[未启用]" not in out, "有套件被标未启用——默认运行应启用全部套件"


def test_bench_probe_fault_is_falsifiable():
    """可证伪探活：注入已知缺陷 → 必须报未达标（exit 1）。"""
    code, out, _err = run_cli(["bench", "--probe-fault"])
    assert code == 1, "探活未生效：注入缺陷后基准仍报达标（基准空转）"
    assert "未达标" in out


def test_bench_only_accepts_suite_names_from_both_layers():
    """`--only` 白名单必须**跨层**——只在校验一层的实现会误判另一层的套件名。"""
    from checkup_ledger.benchmark.layered import all_suite_names

    names = all_suite_names()
    assert "边界语义" in names, "跨层白名单缺规则层套件"
    assert "样例真值回归" in names, "跨层白名单缺样例层套件"

    for name in ("边界语义", "样例真值回归", "覆盖度门槛"):
        code, out, _err = run_cli(["bench", "--only", name])
        assert code == 0, "--only %s 未达标：\n%s" % (name, out)


def test_bench_only_unknown_suite_is_usage_error():
    code, _out, err = run_cli(["bench", "--only", "不存在的套件"])
    assert code == 2, "未知名套件应走用法错误（exit 2）"
    assert "未知名套件" in err


def test_bench_not_enabled_suites_are_excluded_from_pass_count():
    """未启用套件不得计入通过数——"整套件未启用"与"跑了没过"必须可区分。"""
    from checkup_ledger.benchmark.layered import run_layered_bench

    report = run_layered_bench(only="边界语义")
    enabled = [
        suite for layer in report["layers"] for suite in layer["report"]["suites"]
        if not suite.get("not_enabled")
    ]
    assert len(enabled) == 1, "只选中一个套件，却启用了 %d 个" % len(enabled)
    assert report["total"] == enabled[0]["total"], "通过数把未启用套件算进去了"


def test_sample_layer_reports_unavailable_data_instead_of_faking_pass(monkeypatch):
    """样例集不在位（安装态/冻结态）时必须**如实标未启用**，不伪造通过。"""
    from checkup_ledger.benchmark import samples as layer

    report = layer.run_sample_bench(root=os.path.join(repo_path("."), "no-such-samples-dir"))
    assert report["data_available"] is False, "样例集缺失却报 data_available=True"
    assert report["total"] == 0, "无数据却计入了通过数"
    assert all(suite["not_enabled"] for suite in report["suites"]), "无数据时套件未标未启用"


# ---------------------------------------------------------------- 门 6b：口径显式化（DEC1=B）


def test_installed_form_bench_prints_scope_note_and_still_exits_zero(monkeypatch, tmp_path):
    """**安装态形态**：样例集不在位时 `bench` 必须打印「本次仅规则驱动层」且仍 exit 0。

    这条挡的是"退出码表没覆盖该形态"这个可读性缺陷：22/22 是真的（未启用不计入），
    但仅凭 exit 0 无法区分"两层都跑"与"只跑一层"。故判据有两面：
    - 输出**出现**该标注（原因码 `samples_absent`，不是被 `--only` 排掉的）；
    - 退出码仍是 0（范围标注不是降级成 exit 1——那会打破冻结产物的既定承诺）。

    用 `tmp_path` 造一个空目录指向 `CHECKUP_LEDGER_SAMPLES`：等价于安装态下
    `data/samples/` 不存在，而无需真去装一个 wheel。
    """
    empty_root = tmp_path / "no-samples-here"
    empty_root.mkdir()
    monkeypatch.setenv("CHECKUP_LEDGER_SAMPLES", str(empty_root))

    code, out, _err = run_cli(["bench"])
    assert code == 0, "安装态形态下 bench 应仍 exit 0（未启用 ≠ 未达标）：\n%s" % out
    assert "本次仅规则驱动层" in out, (
        "未启用套件存在时未打印「本次仅规则驱动层」——exit 0 的含义仍不显式：\n%s" % out
    )
    assert "samples_absent" in out, "未启用原因码缺失（应区分「样例集不在位」与「--only 排除」）：\n%s" % out
    # 结论行必须是最后一行，且标注在它之前——顺序反了读者会先看到结论。
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[-1].startswith("基准结论：达标"), "结论行不在末尾：%r" % lines[-1]
    note_index = next(i for i, line in enumerate(lines) if "本次仅规则驱动层" in line)
    assert note_index < len(lines) - 1, "范围标注写到了结论行之后"


def test_scope_note_is_absent_when_both_layers_run():
    """反面对照：两层都跑时**不得**出现范围标注——否则"能两层"这件事永远读不出来。"""
    code, out, _err = run_cli(["bench"])
    assert code == 0, "源码态（两层齐全）bench 未达标：\n%s" % out
    assert "本次仅" not in out, "两层都跑了却仍打印范围标注（标注失去信息量）：\n%s" % out


def test_scope_note_distinguishes_only_filter_from_absent_samples():
    """「--only 排除」与「样例集不在位」必须是**两个**原因码，不能混成一句。

    混在一起的后果：读者看到"样例层未启用"时无法判断是"我自己排掉的"还是
    "这份安装根本没有样例集"——前者无害，后者需要换到源码检出里跑。
    """
    from checkup_ledger.benchmark.layered import (
        REASON_ONLY_FILTER,
        REASON_SAMPLES_ABSENT,
        run_layered_bench,
    )

    only_report = run_layered_bench(only="边界语义")
    reasons = {item["reason"] for item in only_report["not_enabled_suites"]}
    assert REASON_ONLY_FILTER in reasons, "--only 排除未标 only_filter：%r" % reasons
    assert "本次仅规则驱动层" in only_report["scope_note"], (
        "scope_note 未说明只跑了一层：%r" % only_report["scope_note"]
    )

    absent = run_layered_bench(samples_root=os.path.join(repo_path("."), "no-such-samples-dir"))
    absent_reasons = {item["reason"] for item in absent["not_enabled_suites"]}
    assert REASON_SAMPLES_ABSENT in absent_reasons, (
        "样例集不在位未标 samples_absent：%r" % absent_reasons
    )
    assert REASON_SAMPLES_ABSENT != REASON_ONLY_FILTER


# ---------------------------------------------------------------- 门 7：台账是生成物


def test_ledger_verify_passes():
    """台账 sha256 必须与磁盘一致——手改台账会被当场检出。"""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, repo_path("tools", "verify_ledger.py"), "--verify"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=repo_path("."), env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
    )
    output = result.stdout.decode("utf-8", "replace")
    assert result.returncode == 0, "台账复核失败：\n%s" % output


def test_ledger_lists_knowledge_base_and_samples():
    """台账必须同时登记内置知识库（A 类）与合成样例（B 类）。"""
    import csv

    with open(repo_path("data", "ledger", "assets.csv"), "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "台账为空"
    paths = {row["rel_path"] for row in rows}
    assert "src/checkup_ledger/data/indicators.yaml" in paths, "台账未登记内置知识库"
    assert any(path.startswith("data/samples/") for path in paths), "台账未登记合成样例"
    for row in rows:
        assert len(row["sha256"]) == 64, "sha256 长度非法：%s" % row
        assert int(row["bytes"]) > 0, "字节数非法：%s" % row
