"""PII gate 双向验证：阳性样本必被拦 + 阴性对照必放行。

**只测一边的门等于没测**：只验"该拦的拦住了"，把白名单写死太严也永远不红；
只验"该放的放行了"，把门整个删掉也永远不红。两侧都要有。
"""

import ast
import os
import subprocess
import sys
import tempfile

import pytest

from helpers import REPO_ROOT, repo_path, run_cli

GATE = repo_path("tools", "pii_gate.py")


def _load_gate():
    """按文件路径加载门禁模块（避免依赖 tools 是包）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("pii_gate_under_test", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def gate():
    return _load_gate()


# ---------------------------------------------------------------- 阳性：必被拦


@pytest.mark.parametrize(
    "rel_path,content,layer",
    [
        ("real_reports/2024.pdf", "", "path"),
        ("private/data.txt", "", "path"),
        ("docs/report.pdf", "", "type"),
        ("output/ledger.db", "", "type"),
        ("notes/x.txt", "\u8eab\u4efd\u8bc1 110101199003072316", "content"),
        ("notes/x.txt", "\u8054\u7cfb\u7535\u8bdd 13800138000", "content"),
        ("notes/x.txt", "\u5c31\u8bca\u4e8e\u5317\u4eac\u534f\u548c\u4f53\u68c0\u4e2d\u5fc3", "content"),
    ],
)
def test_positive_samples_are_blocked(gate, rel_path, content, layer):
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, rel_path)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(content)
        findings = gate.check_file(target, root=tmp)
    layers = {item.layer for item in findings}
    assert layer in layers, "%s 未被 %s 层拦下（实得 %s）" % (rel_path, layer, layers or "无")


# ---------------------------------------------------------------- 阴性：必放行


@pytest.mark.parametrize(
    "rel_path,content",
    [
        ("data/samples/cases/case-001.txt", "\u5f20\u4e09 \u793a\u4f8b\u4f53\u68c0\u4e2d\u5fc3A 2024-03-11"),
        ("data/samples/cases/scan-001.png", ""),
        ("data/samples/cases/scan-001.pdf", ""),
        ("src/checkup_ledger/model.py", "FLAG_HIGH = 'high'"),
        ("data/samples/cases/case-002.txt", "\u674e\u56db \u793a\u4f8b\u533b\u9662C"),
    ],
)
def test_negative_controls_pass(gate, rel_path, content):
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, rel_path)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(content)
        findings = gate.check_file(target, root=tmp)
    assert not findings, "阴性对照被误拦：%s → %s" % (rel_path, findings)


# ---------------------------------------------------------------- 变异验证


def test_mutation_removing_path_check_turns_positive_red(monkeypatch, gate):
    """变异验证：把路径层判据弄坏 → 阳性样本必须不再被拦（证明这门真在用）。"""
    monkeypatch.setattr(gate, "FORBIDDEN_PATH_SEGMENTS", ())
    findings = gate.check_path("real_reports/2024.pdf")
    assert not findings, "路径检查被清空后仍报命中——说明该层判据不生效"


def test_mutation_removing_type_check_turns_positive_red(monkeypatch, gate):
    monkeypatch.setattr(gate, "SENSITIVE_EXTENSIONS", ())
    findings = gate.check_extension("docs/report.pdf")
    assert not findings, "类型检查被清空后仍报命中——说明该层判据不生效"


def test_mutation_disabling_whitelist_blocks_negative(gate):
    """反向变异：把白名单清空 → 阴性对照必须变红（否则白名单是死代码）。"""
    original = gate.SAMPLE_WHITELIST_PREFIXES
    gate.SAMPLE_WHITELIST_PREFIXES = ()
    try:
        findings = gate.check_extension("data/samples/cases/scan-001.pdf")
        assert findings, "白名单清空后样例仍放行——白名单未被真正使用"
    finally:
        gate.SAMPLE_WHITELIST_PREFIXES = original


# ---------------------------------------------------------------- 门禁自证与端到端


def test_selftest_subcommand_passes():
    code, out, _err = run_cli_for_gate(["--selftest"])
    assert code == 0, "PII gate 自证失败：%s" % out
    assert "\u9634\u6027" in out or "negative" in out.lower()


def run_cli_for_gate(args):
    """跑门禁脚本本身（独立进程，验证真实调用形态）。"""
    result = subprocess.run(
        [sys.executable, GATE] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
        env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
    )
    return (
        result.returncode,
        result.stdout.decode("utf-8", "replace"),
        result.stderr.decode("utf-8", "replace"),
    )


def test_selftest_via_subprocess_returns_zero():
    code, out, err = run_cli_for_gate(["--selftest"])
    assert code == 0, "独立进程跑自证失败：%s%s" % (out, err)


def test_staged_mode_runs_without_crash():
    """`--staged` 是本门在 pre-commit 里的真实调用形态，必须能跑通。"""
    code, out, err = run_cli_for_gate(["--staged"])
    assert code in (0, 1), "—staged 形态异常退出：%s%s" % (out, err)


# ---------------------------------------------------------------- 门自身不得豁免过宽


def test_self_exempt_files_are_exactly_listed(gate):
    """豁免名单必须精确——模糊豁免会让门对某类文件整体失效。"""
    assert gate._SELF_EXEMPT_FILES == (
        "tools/pii_gate.py",
        "tests/test_pii_gate.py",
        "tests/fixtures/pii_probe.txt",
    )


def test_repo_tracked_files_pass_gate(gate):
    """当前仓库里**没有任何真实报告**：全量已跟踪文件都应过门。"""
    from helpers import tracked_files

    offenders = []
    for rel in tracked_files():
        if rel in gate._SELF_EXEMPT_FILES:
            continue
        abs_path = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(abs_path):
            continue
        findings = gate.check_file(abs_path)
        if findings:
            offenders.append((rel, [f"{f.layer}:{f.detail}" for f in findings]))
    assert not offenders, "仓库内检出敏感内容（真实报告不得入库）：%s" % offenders


def test_gate_ast_has_no_module_level_optional_imports():
    """门禁脚本本身的依赖必须是最小集（pre-commit 环境未必装 extras）。"""
    with open(GATE, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=GATE)
    allowed = {
        "argparse", "os", "re", "subprocess", "sys", "tempfile", "json", "shutil",
        "pathlib", "typing", "collections", "itertools", "io", "textwrap", "hashlib",
    }
    spec = None
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".")[0]
                if name not in allowed:
                    spec = "%s" % name
        elif isinstance(node, ast.ImportFrom) and node.module:
            name = node.module.split(".")[0]
            if name not in allowed:
                spec = "%s" % name
    assert spec is None, "PII gate 引入非 stdlib 依赖：%s（pre-commit 环境可能没装）" % spec
