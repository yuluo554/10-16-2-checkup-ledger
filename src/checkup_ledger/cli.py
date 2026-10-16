"""命令行入口。

退出码契约见 `exit_codes.py`（README 同源）。要点：
- 非零 ≠ 跑挂：`1` 是"查出了不合规"这一**成功执行 + 负面结论**；
- 未实现模块一律 `4` 显式拦截，**不伪造空结果**；
- 未知子命令/旗标一律 `2`（用法错误）。

三条通路（`python -m` / 裸 `checkup-ledger` / 冻结 exe）的 `sys.path` 来源不同，
**一种通不等于另一种通**——README 与 CI 都要分别冒烟。
"""

import argparse
import os
import re
import sys
from typing import List, Optional, Tuple

from checkup_ledger import __version__
from checkup_ledger.encoding import _can_encode, ensure_utf8_stdio
from checkup_ledger.exit_codes import (
    EXIT_FINDINGS,
    EXIT_MISSING_DEP,
    EXIT_NOT_READY,
    EXIT_OK,
    EXIT_USAGE,
)

PROG = "checkup-ledger"

_NOT_READY_MODULES = {
    "ingest": "模块① 输入层（PDF/扫描件导入）",
    "normalize": "模块② 指标规范化层",
    "ledger": "模块④ 纵向台账",
    "export": "模块⑤a 就诊摘要导出",
    "report": "模块⑤b 本地 HTML 报告",
}

_KNOWN_SUBCOMMANDS = (
    "version",
    "selftest",
    "indicators",
    "bench",
) + tuple(sorted(_NOT_READY_MODULES))


class UsageError(Exception):
    """用法错误 → EXIT_USAGE。"""


_INVALID_CHOICE_RE = re.compile(r"invalid choice: '([^']*)'")


def _format_usage_error(message: str) -> str:
    """把 argparse 的原始报错整成可读文案。

    未知子命令（`invalid choice`）单独说成"未知命令"，与未知旗标区分——
    两者都是 exit 2，但用户看到的提示不同，排错路径也不同。
    """
    match = _INVALID_CHOICE_RE.search(message)
    if match:
        return "未知命令：%s" % match.group(1)
    return "用法错误：%s" % message


class _Parser(argparse.ArgumentParser):
    """把 argparse 的 SystemExit 转成可断言的自有异常。"""

    def error(self, message):  # noqa: D102
        raise UsageError(message)

    def exit(self, status=0, message=None):  # noqa: D102
        if status:
            raise UsageError(message or "用法错误")
        raise SystemExit(status)


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。

    本函数是 README 旗标对账的**反射来源**：README 里出现的每个旗标都必须能在
    这里解析到，且挂在正确的子命令上（防"旗标写在错的命令行上"）。
    """
    parser = _Parser(
        prog=PROG,
        description="体检台账工作台：本地检验指标台账 + 纵向趋势 + 机械判定（不做诊断/解读/分诊）。",
        epilog="退出码：0 成功/达标 · 1 检出问题 · 2 用法错误 · 3 缺可选依赖 · 4 阶段未就绪",
    )
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    sub = parser.add_subparsers(dest="command", metavar="<命令>")

    sub.add_parser("version", help="打印版本信息")

    p_self = sub.add_parser("selftest", help="内置自检（数据目录 / 知识库门禁 / 写盘确定性 / 零外链守卫）")
    p_self.add_argument("--data-dir", default=None, help="显式指定运行时数据目录（测试/演示应显式传）")
    p_self.add_argument("--json", dest="json_out", default=None, help="把自检报告写为 JSON 文件")

    p_ind = sub.add_parser("indicators", help="列出内置区间知识库条目与未启用清单")
    p_ind.add_argument("--data-dir", default=None, help="显式指定运行时数据目录")
    p_ind.add_argument("--json", dest="json_out", default=None, help="把结果写为 JSON 文件")

    p_bench = sub.add_parser("bench", help="运行内置判定契约基准")
    p_bench.add_argument("--only", default=None, help="只跑指定套件（其余标注未启用）")
    p_bench.add_argument("--json", dest="json_out", default=None, help="把基准报告写为 JSON 文件")
    p_bench.add_argument(
        "--probe-fault",
        action="store_true",
        help="可证伪探活：注入一个已知缺陷，基准必须报未达标（用于证明基准不是空转）",
    )

    for name in sorted(_NOT_READY_MODULES):
        p = sub.add_parser(name, help="[未就绪] %s" % _NOT_READY_MODULES[name])
        p.add_argument("--data-dir", default=None, help="显式指定运行时数据目录")

    return parser


# ---------------------------------------------------------------- version


def cmd_version(_args) -> int:
    print("%s %s" % (PROG, __version__))
    print("Python %s" % sys.version.split()[0])
    print("零上传 / 零遥测：本工具不发起任何网络请求。")
    return EXIT_OK


# ---------------------------------------------------------------- indicators


def cmd_indicators(args) -> int:
    from checkup_ledger.loader import load_indicators
    from checkup_ledger.paths import DataDirError, indicators_path

    try:
        path = indicators_path(args.data_dir)
    except DataDirError as exc:
        print("数据目录解析失败：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS

    try:
        table = load_indicators(path)
    except Exception as exc:  # 知识库不可用属"检出问题"，不是用法错误
        print("知识库加载失败：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS

    print("知识库：%s" % path)
    print("可生效条目：%d 项" % len(table.entries))
    for entry in table.entries:
        mark = "可用" if entry.usable_as_default else "待核对(不进判定)"
        rng = entry.default_range
        low = "-" if rng.low is None else rng.low
        high = "-" if rng.high is None else rng.high
        print(
            "  [%s] %-6s %s  %s~%s %s  source=%s / %s"
            % (mark, entry.canonical_name, entry.display_name, low, high, entry.unit,
               entry.source_standard, entry.status)
        )
    if table.disabled:
        print("未启用条目：%d 项（门禁拦下，附原因）" % len(table.disabled))
        for item in table.disabled:
            print("  [禁用] %s：%s" % (item.canonical_name, item.reason))
    else:
        print("未启用条目：0 项")
    print("免责：%s" % table.disclaimer.strip().replace("\n", " "))

    if args.json_out:
        from checkup_ledger.serialize import write_json

        write_json(
            args.json_out,
            {
                "knowledge_path": path,
                "entries": [
                    {
                        "canonical_name": e.canonical_name,
                        "display_name": e.display_name,
                        "unit": e.unit,
                        "status": e.status,
                        "source_standard": e.source_standard,
                        "usable_as_default": e.usable_as_default,
                        "default_range": {
                            "low": e.default_range.low,
                            "high": e.default_range.high,
                            "bounds": e.default_range.bounds,
                        },
                    }
                    for e in table.entries
                ],
                "disabled": [
                    {"canonical_name": d.canonical_name, "reason": d.reason} for d in table.disabled
                ],
            },
        )
        print("已写出：%s" % os.path.abspath(os.fspath(args.json_out)))
    return EXIT_OK


# ---------------------------------------------------------------- selftest


def _check_data_dir() -> Tuple[bool, str]:
    from checkup_ledger.paths import DataDirError, data_dir_in_frozen_root, resolve_data_dir

    try:
        resolved = resolve_data_dir()
    except DataDirError as exc:
        return False, "数据目录解析失败：%s" % exc
    if not os.path.isdir(resolved):
        return False, "数据目录不存在：%s" % resolved
    if data_dir_in_frozen_root() != EXIT_OK:
        return False, "冻结态数据目录未落在 exe 目录内：%s" % resolved
    return True, "数据目录：%s" % resolved


def _check_knowledge() -> Tuple[bool, str]:
    from checkup_ledger.loader import ALL_STATUS, load_indicators
    from checkup_ledger.paths import indicators_path

    try:
        table = load_indicators(indicators_path())
    except Exception as exc:
        return False, "知识库加载失败：%s" % exc

    for entry in table.entries:
        if not entry.source_standard:
            return False, "条目 %s 缺 source.standard" % entry.canonical_name
        if entry.status not in ALL_STATUS:
            return False, "条目 %s status 非法：%r" % (entry.canonical_name, entry.status)
        if entry.status == "verified" and not entry.evidence.strip():
            return False, "条目 %s verified 但 evidence 为空" % entry.canonical_name
    verified = sum(1 for e in table.entries if e.usable_as_default)
    return True, "知识库：%d 项可生效（其中 verified 可作默认值 %d 项）、%d 项未启用" % (
        len(table.entries),
        verified,
        len(table.disabled),
    )


def _check_serialize() -> Tuple[bool, str]:
    import tempfile

    from checkup_ledger.serialize import find_leftover_temp_files, to_json_bytes, write_atomic

    payload = {"b": 1, "a": "\u4e2d\u6587", "nested": {"y": [1, 2], "x": None}}
    first = to_json_bytes(payload)
    second = to_json_bytes(payload)
    if first != second:
        return False, "canonical JSON 双跑不一致"
    if b"\\u" in first:
        return False, "canonical JSON 未使用 ensure_ascii=False（中文被转义）"
    if b"\r" in first:
        return False, "canonical JSON 含 CR"
    if not first.endswith(b"\n"):
        return False, "canonical JSON 缺结尾换行"

    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "out.json")
        write_atomic(target, first)
        with open(target, "rb") as handle:
            if handle.read() != first:
                return False, "原子写读回与写入不一致"
        leftovers = find_leftover_temp_files(tmp)
        if leftovers:
            return False, "原子写残留临时文件：%s" % leftovers
    return True, "写盘：canonical JSON 双跑逐字节一致，原子写零残留"


def _check_encoding() -> Tuple[bool, str]:
    if not _can_encode("utf-8") or not _can_encode("cp936"):
        return False, "编码探针判断异常：utf-8/cp936 应可编码中文"
    if _can_encode("cp1252") or _can_encode("ascii"):
        return False, "编码探针判断异常：cp1252/ascii 应不可编码中文"
    return True, "编码探针：utf-8/cp936 放行、cp1252/ascii 触发 reconfigure"


def _check_report_guard() -> Tuple[bool, str]:
    from checkup_ledger.report.guard import find_external_resources

    # scheme 运行时拼接：自检源码里不出现完整外链词面（否则"扫外链"的门自己就是命中源）
    external = "<link rel=\"stylesheet\" href=\"%scdn.example.com/a.css\">" % (
        "ht" + "tps:" + "/" + "/",
    )
    bad = external
    if not find_external_resources(bad):
        return False, "零外链守卫漏判：外部样式表未被识别"
    if find_external_resources('<a href="#sec">x</a><img src="./local.png">'):
        return False, "零外链守卫误判：相对路径与片段被当作外链"
    return True, "零外链守卫：外链命中、相对路径与片段放行"


def _check_exit_codes() -> Tuple[bool, str]:
    from checkup_ledger import exit_codes

    expected = {0, 1, 2, 3, 4}
    if set(exit_codes.ALL_EXIT_CODES) != expected:
        return False, "退出码集合不完整：%s" % sorted(exit_codes.ALL_EXIT_CODES)
    return True, "退出码契约：0/1/2/3/4 五级齐备"


def cmd_selftest(args) -> int:
    checks = (
        ("data_dir", _check_data_dir),
        ("knowledge", _check_knowledge),
        ("serialize", _check_serialize),
        ("encoding", _check_encoding),
        ("report_guard", _check_report_guard),
        ("exit_codes", _check_exit_codes),
    )
    results = []
    failed = 0
    for name, func in checks:
        try:
            ok, detail = func()
        except Exception as exc:  # 自检不得因单个检查崩溃而中断
            ok, detail = False, "检查抛出异常：%s: %s" % (type(exc).__name__, exc)
        if not ok:
            failed += 1
        results.append({"name": name, "ok": ok, "detail": detail})
        print("[%s] %s — %s" % ("OK" if ok else "FAIL", name, detail))

    print("自检结论：%d/%d 通过" % (len(results) - failed, len(results)))
    if args.json_out:
        from checkup_ledger.serialize import write_json

        write_json(
            args.json_out,
            {"passed": len(results) - failed, "total": len(results), "checks": results},
        )
        print("已写出：%s" % os.path.abspath(os.fspath(args.json_out)))
    return EXIT_OK if failed == 0 else EXIT_FINDINGS


# ---------------------------------------------------------------- bench


def cmd_bench(args) -> int:
    from checkup_ledger.benchmark.layered import run_layered_bench

    try:
        report = run_layered_bench(only=args.only, probe_fault=args.probe_fault)
    except ValueError as exc:
        print("用法错误：%s" % exc, file=sys.stderr)
        return EXIT_USAGE

    for layer in report["layers"]:
        print("== %s ==" % layer["layer"])
        for suite in layer["report"]["suites"]:
            if suite.get("not_enabled"):
                print("  [未启用] %s — %s" % (suite["name"], suite.get("notes", "")))
                continue
            print(
                "  [%s] %s — %d/%d 通过%s"
                % (
                    "达标" if suite["passed"] else "未达标",
                    suite["name"],
                    suite["passed_count"],
                    suite["total"],
                    ("；" + suite.get("notes", "")) if suite.get("notes") else "",
                )
            )
            for failure in suite.get("failures", [])[:10]:
                print("        · %s" % failure)

    if report.get("notes"):
        print(report["notes"])
    print("基准结论：%s（%d/%d）" % ("达标" if report["passed"] else "未达标",
                                     report["passed_count"], report["total"]))

    if args.json_out:
        from checkup_ledger.serialize import write_json

        write_json(args.json_out, report)
        print("已写出：%s" % os.path.abspath(os.fspath(args.json_out)))

    return EXIT_OK if report["passed"] else EXIT_FINDINGS


# ---------------------------------------------------------------- not ready


def cmd_not_ready(name: str) -> int:
    print(
        "%s 尚未落地（首期骨架阶段）。\n"
        "本阶段不产出任何伪造结果——请见 plan/05-里程碑与发布.md 的里程碑安排。"
        % _NOT_READY_MODULES[name],
        file=sys.stderr,
    )
    return EXIT_NOT_READY


# ---------------------------------------------------------------- main


def main(argv: Optional[List[str]] = None) -> int:
    ensure_utf8_stdio()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help / -h
        return int(exc.code or EXIT_OK)
    except UsageError as exc:
        print("%s: %s" % (PROG, _format_usage_error(str(exc))), file=sys.stderr)
        print("用 `%s --help` 查看用法。" % PROG, file=sys.stderr)
        return EXIT_USAGE

    if args.version or args.command == "version":
        return cmd_version(args)

    command = args.command
    if command in (None, ""):
        parser.print_help()
        return EXIT_USAGE
    if command == "selftest":
        return cmd_selftest(args)
    if command == "indicators":
        return cmd_indicators(args)
    if command == "bench":
        return cmd_bench(args)
    if command in _NOT_READY_MODULES:
        return cmd_not_ready(command)

    print("%s: 未知命令：%r" % (PROG, command), file=sys.stderr)
    return EXIT_USAGE


def _missing_dependency_exit() -> int:  # pragma: no cover - 契约占位说明
    """缺可选依赖的统一出口（模块①②落地后调用）。"""
    return EXIT_MISSING_DEP


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
