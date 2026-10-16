"""变异验证驱动：逐条弄坏被测行为，确认对应守门变红。

用法：py -3.12 tools/mutation_check.py
判定口诀：**"我删掉这段逻辑，测试会红吗？"** 不会红 = 假门。

每条变异都：① 备份 → ② 断言改前能跑绿 → ③ 施加变异并断言文本真变了 →
④ 断言目标守门变红 → ⑤ 恢复并断言回绿。任一步不符即整体失败（exit 1）。
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")

ENV = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _load_mutations():
    """变异表：文件 / 原串 / 新串 / 说明 / 该变红的目标命令。"""
    return [
        {
            "name": "engine-high-判反",
            "file": os.path.join(SRC, "checkup_ledger", "engine", "compare.py"),
            "old": "if value > ref.high:\n            return FLAG_HIGH",
            "new": "if value > ref.high:\n            return FLAG_LOW",
            "cmd": [sys.executable, "-m", "checkup_ledger", "bench"],
            "target": "bench（判定契约）",
        },
        {
            "name": "engine-忽略自印区间",
            "file": os.path.join(SRC, "checkup_ledger", "engine", "compare.py"),
            "old": "printed = measurement.ref_range_printed",
            "new": "printed = None  # 变异：丢弃最优先来源",
            "cmd": [sys.executable, "-m", "checkup_ledger", "bench"],
            "target": "bench（三级优先）",
        },
        {
            "name": "engine-拒判降级为正常",
            "file": os.path.join(SRC, "checkup_ledger", "engine", "compare.py"),
            "old": "    if ref.low is None and ref.high is None:\n        return FLAG_NOT_ASSESSED",
            "new": "    if ref.low is None and ref.high is None:\n        return FLAG_NORMAL  # 变异：拒判降级",
            "cmd": [sys.executable, "-m", "checkup_ledger", "bench"],
            "target": "bench（拒判）",
        },
        {
            "name": "serialize-改用转义中文",
            "file": os.path.join(SRC, "checkup_ledger", "serialize.py"),
            "old": "text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=JSON_INDENT)",
            "new": "text = json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=JSON_INDENT)  # 变异",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_determinism.py"],
            "target": "determinism（中文可读）",
        },
        {
            "name": "serialize-不去CRLF",
            "file": os.path.join(SRC, "checkup_ledger", "serialize.py"),
            "old": "        payload = str(data).replace(\"\\r\\n\", \"\\n\").encode(\"utf-8\")",
            "new": "        payload = str(data).encode(\"utf-8\")  # 变异：不归一 CRLF",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_determinism.py"],
            "target": "determinism（LF 归一）",
        },
        {
            "name": "loader-不校验来源",
            "file": os.path.join(SRC, "checkup_ledger", "loader.py"),
            "old": "    standard = source.get(\"standard\")\n    if not isinstance(standard, str) or not standard.strip():\n        return None, DisabledEntry(name, \"source.standard 缺失（未挂来源分册）\")",
            "new": "    standard = source.get(\"standard\") or \"UNKNOWN\"  # 变异：不校验来源",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_loader.py"],
            "target": "loader（来源门禁）",
        },
        {
            "name": "loader-放行pending",
            "file": os.path.join(SRC, "checkup_ledger", "loader.py"),
            "old": "        return self.status == STATUS_VERIFIED",
            "new": "        return True  # 变异：pending 也当可用",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_loader.py"],
            "target": "loader（pending 不进判定路径）",
        },
        {
            "name": "guard-零外链断言失效",
            "file": os.path.join(SRC, "checkup_ledger", "report", "guard.py"),
            "old": "def assert_no_external_resources(html: str) -> None:",
            "new": "def assert_no_external_resources(html: str) -> None:\n    return  # 变异：守卫失效",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "layering（零外链常驻断言）",
        },
        {
            "name": "html-渲染层重算判定",
            "file": os.path.join(SRC, "checkup_ledger", "report", "html.py"),
            "old": "def _display_bound(bound):",
            "new": "def _recompute(value, ref):\n    return value > ref  # 变异：渲染层做比较\n\n\ndef _display_bound(bound):",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "layering（渲染层零判定）",
        },
        {
            "name": "encoding-守卫不生效",
            "file": os.path.join(SRC, "checkup_ledger", "encoding.py"),
            "old": "def ensure_utf8_stdio() -> None:\n    \"\"\"入口调用一次。幂等，可重复调用。\"\"\"",
            "new": "def ensure_utf8_stdio() -> None:\n    \"\"\"入口调用一次。幂等，可重复调用。\"\"\"\n    return  # 变异：守卫不生效",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_encoding.py"],
            "target": "encoding（窄编码守卫）",
        },
        {
            "name": "cli-用法错误码改动",
            "file": os.path.join(SRC, "checkup_ledger", "cli.py"),
            "old": "    except UsageError as exc:\n        print(\"%s: %s\" % (PROG, _format_usage_error(str(exc))), file=sys.stderr)\n        print(\"用 `%s --help` 查看用法。\" % PROG, file=sys.stderr)\n        return EXIT_USAGE",
            "new": "    except UsageError as exc:\n        print(\"%s: %s\" % (PROG, _format_usage_error(str(exc))), file=sys.stderr)\n        print(\"用 `%s --help` 查看用法。\" % PROG, file=sys.stderr)\n        return EXIT_OK  # 变异：用法错误当成功",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_exit_codes.py"],
            "target": "exit_codes（用法错误=2）",
        },
        {
            "name": "paths-缺数据目录静默回落",
            "file": os.path.join(SRC, "checkup_ledger", "paths.py"),
            "old": "        raise DataDirError(\n            \"冻结态未找到随包数据目录：%s（打包白名单可能漏拷）\" % candidate\n        )",
            "new": "        return package_root()  # 变异：静默回落",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_paths.py"],
            "target": "paths（冻结态缺数据必须报错）",
        },
    ]


def _target_missing(item):
    """目标命令引用的测试文件是否存在（bench/selftest 这类内置命令无需测试文件）。"""
    for token in item["cmd"]:
        if token.startswith("tests/") or token.startswith("tests\\"):
            return not os.path.isfile(os.path.join(ROOT, token.replace("/", os.sep)))
    return False


def main():
    mutations = _load_mutations()
    failures = []
    skipped = []

    for item in mutations:
        path = item["file"]
        if not os.path.isfile(path):
            skipped.append("%s（文件不存在）" % item["name"])
            continue
        if _target_missing(item):
            skipped.append("%s（目标测试文件不存在）" % item["name"])
            continue

        backup = path + ".mutbak"
        shutil.copy2(path, backup)
        try:
            original = _read(path)
            before = _run(item["cmd"])
            if before.returncode != 0:
                failures.append("%s：基线就是红的（改前就不过，无法用于变异验证）" % item["name"])
                continue

            mutated = original.replace(item["old"], item["new"], 1)
            if mutated == original:
                failures.append("%s：变异未生效（原串未找到）——探针失效" % item["name"])
                continue
            _write(path, mutated)

            after = _run(item["cmd"])
            if after.returncode == 0:
                failures.append(
                    "%s：变异后 %s 仍为绿（exit 0）——假门" % (item["name"], item["target"])
                )
            else:
                print("[红✓] %-28s → %s 变红（exit %d）" % (item["name"], item["target"], after.returncode))
        finally:
            shutil.copy2(backup, path)
            os.unlink(backup)

    # 恢复后必须全绿
    final = _run([sys.executable, "-m", "pytest", "-q"])
    if final.returncode != 0:
        failures.append("恢复后测试未回绿（树被污染）")

    print("")
    if skipped:
        for item in skipped:
            print("[跳过] %s" % item)
    if failures:
        print("变异验证失败 %d 项：" % len(failures))
        for item in failures:
            print("  × %s" % item)
        return 1
    print("变异验证通过：%d 条变异全部使目标守门变红，恢复后全绿。" % (len(mutations) - len(skipped)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
