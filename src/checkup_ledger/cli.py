"""命令行入口。

退出码契约见 `exit_codes.py`（README 同源）。要点：
- 非零 ≠ 跑挂：`1` 是"查出了不合规"这一**成功执行 + 负面结论**；
- 未知子命令/旗标一律 `2`（用法错误）；
- 首期五模块（输入 / 规范化 / 判定 / 台账 / 导出+报告）**已全部落地**，
  故 `NOT_READY`(4) 的拦截点**整项退役**（本棒）。

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
    EXIT_OK,
    EXIT_USAGE,
)

PROG = "checkup-ledger"

_KNOWN_SUBCOMMANDS = (
    "version",
    "selftest",
    "indicators",
    "bench",
    "ingest",
    "normalize",
    "ledger",
    "export",
    "report",
)


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
        epilog="退出码：0 成功/达标 · 1 检出问题 · 2 用法错误 · 3 缺可选依赖",
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

    p_ingest = sub.add_parser("ingest", help="模块① 输入层：PDF 文本层 / 扫描件 → 行级草稿（低置信行转人工复核）")
    p_ingest.add_argument("paths", nargs="+", help="待解析的 PDF 或图片路径（可多个）")
    p_ingest.add_argument("--data-dir", default=None, help="显式指定运行时数据目录（读取阈值配置）")
    p_ingest.add_argument(
        "--reviews",
        default=None,
        help="人工复核留痕 JSON 文件（复核记录数组；缺省则该行不放行）",
    )
    p_ingest.add_argument("--json", dest="json_out", default=None, help="把抽取结果写为 JSON 文件")

    p_norm = sub.add_parser(
        "normalize",
        help="模块② 规范化层：报告行 → 结构化记录（指标名映射 / 单位归一 / 待人工映射队列）",
    )
    p_norm.add_argument("paths", nargs="+", help="待规范化的报告文件（PDF / 扫描件，可多个）")
    p_norm.add_argument("--data-dir", default=None, help="显式指定运行时数据目录（知识库与阈值配置）")
    p_norm.add_argument(
        "--reviews",
        default=None,
        help="人工复核留痕 JSON 文件（低置信行经复核后才可进入本层）",
    )
    p_norm.add_argument("--json", dest="json_out", default=None, help="把规范化结果写为 JSON 文件")

    p_ledger = sub.add_parser(
        "ledger",
        help="模块④ 纵向台账：把判定结果写入 SQLite 台账 / 查看单指标时间序列",
    )
    p_ledger.add_argument("paths", nargs="*", help="待入库的报告文件（PDF / 扫描件；不给则只读台账）")
    p_ledger.add_argument("--db", default=None, help="台账库路径（缺省 ~/.checkup_ledger/ledger.db）")
    p_ledger.add_argument("--subject", default="default", help="主体标识（家庭多成员扩展用）")
    p_ledger.add_argument("--date", default=None, help="采样日期（ISO 8601，显式传入；入库时必需）")
    p_ledger.add_argument("--indicator", default=None, help="只打印该指标的时间序列")
    p_ledger.add_argument("--data-dir", default=None, help="显式指定运行时数据目录（知识库与阈值配置）")
    p_ledger.add_argument(
        "--reviews", default=None, help="人工复核留痕 JSON 文件（低置信行经复核后才可进入本层）"
    )
    p_ledger.add_argument("--json", dest="json_out", default=None, help="把台账读回结果写为 JSON 文件")

    p_export = sub.add_parser(
        "export",
        help="模块⑤a 就诊摘要导出：CSV / Markdown，只陈述事实数值与变化幅度",
    )
    p_export.add_argument("paths", nargs="+", help="待导出的报告文件（PDF / 扫描件）")
    p_export.add_argument("--fmt", default="csv", help="导出格式：csv | md（缺省 csv）")
    p_export.add_argument("--out", default=None, help="导出文件路径（缺省 <报告名>.summary.<fmt>）")
    p_export.add_argument("--db", default=None, help="台账库路径（用于取既往序列算变化幅度）")
    p_export.add_argument("--subject", default="default", help="主体标识（家庭多成员扩展用）")
    p_export.add_argument("--date", default=None, help="采样日期（ISO 8601，显式传入）")
    p_export.add_argument("--data-dir", default=None, help="显式指定运行时数据目录")
    p_export.add_argument("--reviews", default=None, help="人工复核留痕 JSON 文件")
    p_export.add_argument("--json", dest="json_out", default=None, help="把导出摘要写为 JSON 文件")

    p_report = sub.add_parser(
        "report",
        help="模块⑤b 本地 HTML 报告：单指标折线 + 自身历史分位 + 参考区间带状背景（零外链）",
    )
    p_report.add_argument("paths", nargs="+", help="待出报告的报告文件（PDF / 扫描件）")
    p_report.add_argument("--out", default=None, help="HTML 报告路径（缺省 <报告名>.report.html）")
    p_report.add_argument("--db", default=None, help="台账库路径（用于取纵向序列）")
    p_report.add_argument("--subject", default="default", help="主体标识（家庭多成员扩展用）")
    p_report.add_argument("--date", default=None, help="采样日期（ISO 8601，显式传入）")
    p_report.add_argument("--data-dir", default=None, help="显式指定运行时数据目录")
    p_report.add_argument("--reviews", default=None, help="人工复核留痕 JSON 文件")
    p_report.add_argument("--json", dest="json_out", default=None, help="把报告元信息写为 JSON 文件")

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

    # M4：首期五模块全部落地 → `NOT_READY`(4) 整项退役，集合应为 {0,1,2,3}。
    # 自检同时**防复活**：常量若还在，说明退役只做了一半（分派删了、常量留着）。
    expected = {0, 1, 2, 3}
    if set(exit_codes.ALL_EXIT_CODES) != expected:
        return False, "退出码集合与退役后契约不符：%s" % sorted(exit_codes.ALL_EXIT_CODES)
    if hasattr(exit_codes, "EXIT_NOT_READY"):
        return False, "EXIT_NOT_READY 常量未随退役删除（幽灵语义复活）"
    return True, "退出码契约：0/1/2/3 四级（4 已随首期全落地整项退役）"


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


# ---------------------------------------------------------------- ingest


def _load_reviews(path) -> list:
    """读人工复核留痕 JSON。

    文件形态：`[{"page":1,"line_no":3,"source_file":"x.png","confirmed_text":"...",
    "reviewer_note":"..."}, ...]`。`line_ref` 由这里按 (source_file, page, line_no)
    反查重建——留痕文件只记**定位信息**，不搬 `RawLine` 实体（避免复制走样）。
    """
    import json

    from checkup_ledger.model import RawLine, ReviewRecord

    with open(os.fspath(path), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("复核文件应为记录数组")

    records = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError("复核记录 %d 应为对象" % index)
        for key in ("source_file", "page", "line_no", "confirmed_text"):
            if key not in item:
                raise ValueError("复核记录 %d 缺字段 %s" % (index, key))
        line_ref = RawLine(
            page=int(item["page"]),
            line_no=int(item["line_no"]),
            text=item.get("original_text", ""),
            confidence=float(item.get("confidence", 0.0)),
            source_file=item["source_file"],
        )
        records.append(
            ReviewRecord(
                line_ref=line_ref,
                original_text=item.get("original_text", ""),
                confirmed_text=item["confirmed_text"],
                reviewer_note=item.get("reviewer_note", ""),
            )
        )
    return records


def _ingest_payload(result) -> dict:
    return {
        "engine": result.engine,
        "lines": [
            {
                "page": line.page,
                "line_no": line.line_no,
                "text": line.text,
                "confidence": line.confidence,
                "source_file": line.source_file,
            }
            for line in result.lines
        ],
        "pending_review": [
            {
                "page": line.page,
                "line_no": line.line_no,
                "text": line.text,
                "confidence": line.confidence,
                "source_file": line.source_file,
            }
            for line in result.pending_review
        ],
        "notes": [{"code": note.code, "message": note.message, "count": note.count} for note in result.notes],
    }


def cmd_ingest(args) -> int:
    from checkup_ledger.config import ConfigError, load_config
    from checkup_ledger.ingest import IngestError, MissingDependencyError, ingest

    try:
        threshold = load_config(explicit=args.data_dir).ocr_threshold
    except ConfigError as exc:
        # 阈值必须来自配置：缺配置是**配置缺陷**（检出问题），不是用法错误
        print("配置不可用：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS

    reviews = None
    if args.reviews:
        try:
            reviews = _load_reviews(args.reviews)
        except (OSError, ValueError) as exc:
            print("复核文件不可用：%s" % exc, file=sys.stderr)
            return EXIT_FINDINGS

    results = []
    exit_code = EXIT_OK
    for path in args.paths:
        try:
            result = ingest(path, ocr_threshold=threshold, reviews=reviews)
        except MissingDependencyError as exc:
            print("%s" % exc, file=sys.stderr)
            return EXIT_MISSING_DEP
        except IngestError as exc:
            print("输入层错误：%s" % exc, file=sys.stderr)
            return EXIT_FINDINGS

        print("== %s ==" % os.path.basename(os.fspath(path)))
        print("抽取引擎：%s；可传递行 %d 条；待复核 %d 条" % (result.engine, len(result.lines), len(result.pending_review)))
        for line in result.lines:
            print("  [%s] p%d L%d %.3f %s" % ("可传递", line.page, line.line_no, line.confidence, line.text))
        for line in result.pending_review:
            print("  [%s] p%d L%d %.3f %s" % ("待复核", line.page, line.line_no, line.confidence, line.text))
        for note in result.notes:
            print("  注记[%s]：%s" % (note.code, note.message))
        results.append({"path": os.fspath(path), "result": _ingest_payload(result)})

    if args.json_out:
        from checkup_ledger.serialize import write_json

        write_json(args.json_out, {"ocr_threshold": threshold, "files": results})
        print("已写出：%s" % os.path.abspath(os.fspath(args.json_out)))
    return exit_code


# ---------------------------------------------------------------- normalize


def _measurement_payload(m) -> dict:
    printed = m.ref_range_printed
    return {
        "canonical_name": m.canonical_name,
        "raw_name": m.raw_name,
        "value": m.value,
        "unit": m.unit,
        "raw_unit": m.raw_unit,
        "ref_range_printed": None
        if printed is None
        else {"low": printed.low, "high": printed.high, "bounds": printed.bounds},
        "line_ref": None
        if m.line_ref is None
        else {
            "page": m.line_ref.page,
            "line_no": m.line_ref.line_no,
            "source_file": m.line_ref.source_file,
        },
        "reviewed": m.reviewed,
    }


def _judged_payload(j) -> dict:
    payload = _measurement_payload(j.measurement)
    payload["flag"] = j.flag
    payload["range_source"] = j.range_source
    payload["range_used"] = {
        "low": j.range_used.low,
        "high": j.range_used.high,
        "bounds": j.range_used.bounds,
    }
    return payload


def cmd_normalize(args) -> int:
    """模块② 规范化层：抽取 → 复核门 → 规范化 → 判定（**端到端贯通**）。

    链路只走一条：`ingest()`（含低置信复核门）→ `normalize()` → `judge_all()`。
    `ingest()` 返回的 `lines` 已含"达标 + 复核放行"，`pending_review` 一律不进
    规范化层（`normalize_ingest` 是唯一接续点，它还会挡"复核门被绕过"的形态）。

    判定用的是知识库的 **verified 默认值**（`verified_defaults()`）——当前条目
    一律 `pending`，故报告未自印区间时走拒判（设计内行为）。`range_source` 在产物
    里**显式可见**（三级优先的可审计落点）。
    """
    from checkup_ledger.config import ConfigError, load_config
    from checkup_ledger.engine.compare import judge_all
    from checkup_ledger.ingest import IngestError, MissingDependencyError, ingest
    from checkup_ledger.loader import load_indicators
    from checkup_ledger.normalize import (
        NormalizeError,
        build_dictionary,
        normalize_ingest,
        pending_summary,
        reason_label,
    )
    from checkup_ledger.paths import indicators_path

    try:
        threshold = load_config(explicit=args.data_dir).ocr_threshold
    except ConfigError as exc:
        print("配置不可用：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS

    try:
        table = load_indicators(indicators_path(args.data_dir))
        dictionary = build_dictionary(table.entries, disabled=table.disabled)
    except Exception as exc:  # 知识库不可用属"检出问题"，不是用法错误
        print("知识库不可用：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS

    reviews = None
    if args.reviews:
        try:
            reviews = _load_reviews(args.reviews)
        except (OSError, ValueError) as exc:
            print("复核文件不可用：%s" % exc, file=sys.stderr)
            return EXIT_FINDINGS

    defaults = table.verified_defaults()
    constraints = dictionary.constraints()

    results = []
    for path in args.paths:
        try:
            ingested = ingest(path, ocr_threshold=threshold, reviews=reviews)
        except MissingDependencyError as exc:
            print("%s" % exc, file=sys.stderr)
            return EXIT_MISSING_DEP
        except IngestError as exc:
            print("输入层错误：%s" % exc, file=sys.stderr)
            return EXIT_FINDINGS

        try:
            normalized = normalize_ingest(ingested, dictionary=dictionary)
        except NormalizeError as exc:
            print("规范化层错误：%s" % exc, file=sys.stderr)
            return EXIT_FINDINGS

        judged = judge_all(
            normalized.measurements, defaults, constraints=constraints
        )

        print("== %s ==" % os.path.basename(os.fspath(path)))
        print(
            "抽取引擎：%s；可传递行 %d 条；待复核 %d 条；已映射 %d 条；待人工映射 %d 条"
            % (
                ingested.engine,
                len(ingested.lines),
                len(ingested.pending_review),
                len(normalized.measurements),
                len(normalized.pending_mapping),
            )
        )
        for item in judged:
            m = item.measurement
            ref = item.range_used
            print(
                "  [%s] %-8s %s %s（区间 %s ~ %s，来源 %s）← %s"
                % (
                    item.flag,
                    m.canonical_name,
                    m.value,
                    m.unit,
                    "\u2014" if ref.low is None else ref.low,
                    "\u2014" if ref.high is None else ref.high,
                    item.range_source,
                    "%s 第 %d 页第 %d 行" % (m.line_ref.source_file, m.line_ref.page, m.line_ref.line_no)
                    if m.line_ref
                    else "无溯源",
                )
            )
        for item in normalized.pending_mapping:
            print(
                "  [待人工映射] %s：%s（原文：%s）"
                % (reason_label(item.reason), item.reason, item.raw_text)
            )
        for note in normalized.notes:
            print("  注记[%s]：%s" % (note.code, note.message))

        results.append(
            {
                "path": os.fspath(path),
                "engine": ingested.engine,
                "passed_lines": len(ingested.lines),
                "pending_review": len(ingested.pending_review),
                "judged": [_judged_payload(item) for item in judged],
                "pending_mapping": [
                    {
                        "reason": item.reason,
                        "raw_text": item.raw_text,
                        "raw_name": item.raw_name,
                        "raw_unit": item.raw_unit,
                        "line_ref": {
                            "page": item.line_ref.page,
                            "line_no": item.line_ref.line_no,
                            "source_file": item.line_ref.source_file,
                        },
                    }
                    for item in normalized.pending_mapping
                ],
                "notes": [
                    {"code": note.code, "message": note.message, "count": note.count}
                    for note in normalized.notes
                ],
                "pending_by_reason": pending_summary(normalized.pending_mapping),
            }
        )

    if args.json_out:
        from checkup_ledger.serialize import write_json

        write_json(
            args.json_out,
            {
                "ocr_threshold": threshold,
                "verified_default_count": len(defaults),
                "files": results,
            },
        )
        print("已写出：%s" % os.path.abspath(os.fspath(args.json_out)))
    return EXIT_OK


# ---------------------------------------------------------------- 台账 / 导出 / 报告


DEFAULT_DB_RELPATH = ("checkup_ledger", "ledger.db")


def _default_db_path() -> str:
    """台账库缺省路径：`~/.checkup_ledger/ledger.db`（**用户主目录，不是仓库**）。

    为什么落主目录：台账是**个人健康数据**，落在仓库里会让 `git status` 就看得见
    （PII gate 只在提交时拦，那时文件已经在工作树里了）。主目录也避开"从任意
    CWD 跑都写到一个意外的相对路径"这一坑。
    """
    return os.path.join(os.path.expanduser("~"), *DEFAULT_DB_RELPATH)


def _resolve_db(args) -> str:
    return os.path.abspath(os.fspath(args.db)) if args.db else _default_db_path()


def _load_pipeline(args):
    """加载配置 + 知识库 + 复核留痕（台账/导出/报告三个命令共用的前置）。

    返回 `(threshold, dictionary, constraints, defaults, reviews)`；任一步失败
    返回 `None` 并已打印原因——三个命令共用一处前置，避免三份几乎相同的加载代码
    各漏一项（漏掉 `constraints` 会让适用域门静默失效）。
    """
    from checkup_ledger.config import ConfigError, load_config
    from checkup_ledger.loader import load_indicators
    from checkup_ledger.normalize import build_dictionary
    from checkup_ledger.paths import indicators_path

    try:
        threshold = load_config(explicit=args.data_dir).ocr_threshold
    except ConfigError as exc:
        print("配置不可用：%s" % exc, file=sys.stderr)
        return None

    try:
        table = load_indicators(indicators_path(args.data_dir))
        dictionary = build_dictionary(table.entries, disabled=table.disabled)
    except Exception as exc:
        print("知识库不可用：%s" % exc, file=sys.stderr)
        return None

    reviews = None
    if args.reviews:
        try:
            reviews = _load_reviews(args.reviews)
        except (OSError, ValueError) as exc:
            print("复核文件不可用：%s" % exc, file=sys.stderr)
            return None

    return threshold, dictionary, dictionary.constraints(), table.verified_defaults(), reviews


def _judge_paths(args, pipeline):
    """逐路径跑 ingest → normalize → judge，返回 `(path, judged)` 列表。

    三条命令（台账 / 导出 / 报告）共用本函数——链路只有一条，三处各写一遍就会
    出现"报告里判的是 A、台账里存的是 B"这种最坏形态的分叉。
    """
    from checkup_ledger.engine.compare import judge_all
    from checkup_ledger.ingest import IngestError, MissingDependencyError, ingest
    from checkup_ledger.normalize import NormalizeError, normalize_ingest

    threshold, dictionary, constraints, defaults, reviews = pipeline
    out = []
    for path in args.paths:
        try:
            ingested = ingest(path, ocr_threshold=threshold, reviews=reviews)
        except MissingDependencyError as exc:
            raise _PipelineAbort(EXIT_MISSING_DEP, str(exc))
        except IngestError as exc:
            raise _PipelineAbort(EXIT_FINDINGS, "输入层错误：%s" % exc)

        try:
            normalized = normalize_ingest(ingested, dictionary=dictionary)
        except NormalizeError as exc:
            raise _PipelineAbort(EXIT_FINDINGS, "规范化层错误：%s" % exc)

        judged = judge_all(normalized.measurements, defaults, constraints=constraints)
        out.append((path, judged, ingested, normalized))
    return out


class _PipelineAbort(Exception):
    """链路中途失败（携带应返回的退出码）——由各命令统一转成退出码。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def cmd_ledger(args) -> int:
    """模块④ 纵向台账：入库（给了报告路径）或只读展示（没给路径）。

    读路径与写路径**共用同一个库**：只读时也不建表（`--db` 指向不存在的库时
    如实报"库不存在"，不悄悄建一个空库让人以为"台账是空的"）。
    """
    from checkup_ledger.ledger import LedgerError, open_ledger, rows_for, series, upsert

    db_path = _resolve_db(args)

    if not args.paths:
        if not os.path.isfile(db_path):
            print("台账库不存在：%s（先跑 `ledger <报告路径> --date <日期>` 入库）" % db_path, file=sys.stderr)
            return EXIT_FINDINGS
        try:
            with open_ledger(db_path) as ledger:
                return _print_ledger_view(ledger, args)
        except LedgerError as exc:
            print("台账错误：%s" % exc, file=sys.stderr)
            return EXIT_FINDINGS

    if not args.date:
        print("用法错误：入库必须显式给采样日期（--date YYYY-MM-DD）", file=sys.stderr)
        return EXIT_USAGE

    pipeline = _load_pipeline(args)
    if pipeline is None:
        return EXIT_FINDINGS

    try:
        results = _judge_paths(args, pipeline)
    except _PipelineAbort as exc:
        print(exc.message, file=sys.stderr)
        return exc.code

    try:
        ledger = open_ledger(db_path)
    except LedgerError as exc:
        print("台账错误：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS

    try:
        written = 0
        for path, judged, _ingested, _normalized in results:
            written += upsert(ledger, judged, subject=args.subject, date=args.date)
            print(
                "== %s ==\n入库 %d 条（主体 %s，日期 %s）"
                % (os.path.basename(os.fspath(path)), len(judged), args.subject, args.date)
            )
        print("台账：%s（本次写入 %d 行；库内共 %d 行）" % (db_path, written, ledger.count()))
        for note in ledger.notes:
            print("  注记[%s]：%s" % (note.code, note.message))
        return _print_ledger_view(ledger, args)
    except LedgerError as exc:
        print("台账错误：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS
    finally:
        ledger.close()


def _print_ledger_view(ledger, args) -> int:
    """打印台账读回结果（单指标序列或全部记录）。"""
    from checkup_ledger.ledger import rows_for, series

    if args.indicator:
        points = series(ledger, args.indicator, subject=args.subject)
        if not points:
            print("台账内没有该主体的指标：%s（主体 %s）" % (args.indicator, args.subject), file=sys.stderr)
            return EXIT_FINDINGS
        print("== %s（主体 %s）==" % (args.indicator, args.subject))
        for point in points:
            print(
                "  %s  %s%s"
                % (
                    point.date,
                    point.value,
                    ""
                    if point.direction is None
                    else "（变化 %s，趋势 %s）" % (point.delta, point.direction),
                )
            )
        return EXIT_OK

    rows = rows_for(ledger, subject=args.subject)
    print("== 台账（主体 %s，共 %d 条）==" % (args.subject, len(rows)))
    for row in rows:
        print(
            "  %s  %-8s %s %s  [%s]  区间 %s~%s（%s）"
            % (
                row["date"],
                row["canonical_name"],
                row["value"],
                row["unit"],
                row["flag"],
                "\u2014" if row["range_low"] is None else row["range_low"],
                "\u2014" if row["range_high"] is None else row["range_high"],
                row["range_source"],
            )
        )

    if args.json_out:
        from checkup_ledger.serialize import write_json

        write_json(
            args.json_out,
            {
                "db": ledger.path,
                "subject": args.subject,
                "rows": rows,
                "subjects": ledger.subjects(),
            },
        )
        print("已写出：%s" % os.path.abspath(os.fspath(args.json_out)))
    return EXIT_OK


def _default_out_path(path, suffix: str, fmt: str = "") -> str:
    stem = os.path.splitext(os.path.basename(os.fspath(path)))[0]
    extension = (".%s" % fmt) if fmt else ""
    return os.path.join(os.getcwd(), "%s%s%s" % (stem, suffix, extension))


def cmd_export(args) -> int:
    """模块⑤a 就诊摘要导出：把判定结果导出成 CSV / Markdown。"""
    from checkup_ledger.export import ExportError, AdvisoryWordingError, export_summary, history_from_ledger
    from checkup_ledger.ledger import LedgerError, open_ledger

    pipeline = _load_pipeline(args)
    if pipeline is None:
        return EXIT_FINDINGS

    try:
        results = _judge_paths(args, pipeline)
    except _PipelineAbort as exc:
        print(exc.message, file=sys.stderr)
        return exc.code

    history = {}
    db_path = _resolve_db(args)
    if os.path.isfile(db_path):
        try:
            with open_ledger(db_path) as ledger:
                history = history_from_ledger(ledger, subject=args.subject)
        except LedgerError as exc:
            print("台账错误：%s" % exc, file=sys.stderr)
            return EXIT_FINDINGS
    else:
        print("注记[no_ledger]：台账库不在位（%s），变化幅度列留空——无既往可比值" % db_path)

    payloads = []
    for path, judged, _ingested, _normalized in results:
        out_path = args.out or _default_out_path(path, ".summary", args.fmt)
        try:
            written = export_summary(
                judged,
                fmt=args.fmt,
                out=out_path,
                subject=args.subject,
                date=args.date or "",
                title="就诊摘要（%s）" % args.subject,
                history=history,
            )
        except AdvisoryWordingError as exc:
            print("导出物不合规：%s" % exc, file=sys.stderr)
            return EXIT_FINDINGS
        except ExportError as exc:
            print("用法错误：%s" % exc, file=sys.stderr)
            return EXIT_USAGE
        print("== %s ==\n已导出 %d 条：%s" % (os.path.basename(os.fspath(path)), len(judged), written))
        payloads.append({"path": os.fspath(path), "out": written, "rows": len(judged)})

    if args.json_out:
        from checkup_ledger.serialize import write_json

        write_json(args.json_out, {"subject": args.subject, "fmt": args.fmt, "files": payloads})
        print("已写出：%s" % os.path.abspath(os.fspath(args.json_out)))
    return EXIT_OK


def cmd_report(args) -> int:
    """模块⑤b 本地 HTML 报告：判定表 + 单指标折线 + 自身历史分位 + 区间带。"""
    from checkup_ledger.ledger import LedgerError, open_ledger, rows_for, upsert
    from checkup_ledger.report.html import render_measurements, render_trends_to_file
    from checkup_ledger.report.trend import series_from_rows
    from checkup_ledger.serialize import write_atomic

    pipeline = _load_pipeline(args)
    if pipeline is None:
        return EXIT_FINDINGS

    try:
        results = _judge_paths(args, pipeline)
    except _PipelineAbort as exc:
        print(exc.message, file=sys.stderr)
        return exc.code

    db_path = _resolve_db(args)
    try:
        ledger = open_ledger(db_path)
    except LedgerError as exc:
        print("台账错误：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS

    payloads = []
    try:
        # 报告要"纵向"，故本次结果先入库（有日期时），再读回全序列出图。
        if args.date:
            for _path, judged, _ingested, _normalized in results:
                upsert(ledger, judged, subject=args.subject, date=args.date)
        else:
            print("注记[no_date]：未给采样日期，本次结果不入库；折线只用台账既有记录")

        rows = rows_for(ledger, subject=args.subject)
        series_list = series_from_rows(rows)

        for path, judged, _ingested, _normalized in results:
            out_path = args.out or _default_out_path(path, ".report", "html")
            if series_list:
                written = render_trends_to_file(
                    series_list, out_path, subject=args.subject, title="纵向趋势报告（%s）" % args.subject
                )
            else:
                write_atomic(out_path, render_measurements(judged, subject=args.subject))
                written = os.path.abspath(os.fspath(out_path))
            print(
                "== %s ==\n已出报告：%s（本次判定 %d 条，台账序列 %d 项指标）"
                % (os.path.basename(os.fspath(path)), written, len(judged), len(series_list))
            )
            payloads.append(
                {"path": os.fspath(path), "out": written, "series": len(series_list)}
            )
    except LedgerError as exc:
        print("台账错误：%s" % exc, file=sys.stderr)
        return EXIT_FINDINGS
    finally:
        ledger.close()

    if args.json_out:
        from checkup_ledger.serialize import write_json

        write_json(args.json_out, {"subject": args.subject, "files": payloads})
        print("已写出：%s" % os.path.abspath(os.fspath(args.json_out)))
    return EXIT_OK


# ---------------------------------------------------------------- main


def _first_run_disclaimer(argv) -> None:
    """首启免责：未接受过则打印一次并落标记。

    只在**非自检类**命令上触发——`selftest`/`bench`/`version` 这类不碰用户数据的
    命令不该在 CI 里反复打印免责（那会把 CI 输出淹没）。落标记失败不报错
    （见 `disclaimer` 的注记）。

    **`argv` 为 None 时必须回落 `sys.argv[1:]`**：真实调用路径（`python -m` 与裸
    console script）传的就是 None。若直接对 None 判断，这条豁免逻辑会把"用户真的
    敲了 ledger/export/report"读成"没有参数"，免责永远不打印——而单测里显式传
    `["ledger", ...]` 会通过，于是缺陷只在真实入口暴露（实测抓到的正是这一条）。
    """
    from checkup_ledger import disclaimer

    args = list(sys.argv[1:]) if argv is None else list(argv)
    skip = ("version", "selftest", "bench", "indicators", "--help", "-h")
    if not args or args[0] in skip:
        return
    banner = disclaimer.first_run_banner()
    if not banner:
        return
    print("—" * 60)
    print(banner)
    print("—" * 60)
    disclaimer.mark_accepted()


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

    _first_run_disclaimer(argv)

    if command == "selftest":
        return cmd_selftest(args)
    if command == "indicators":
        return cmd_indicators(args)
    if command == "bench":
        return cmd_bench(args)
    if command == "ingest":
        return cmd_ingest(args)
    if command == "normalize":
        return cmd_normalize(args)
    if command == "ledger":
        return cmd_ledger(args)
    if command == "export":
        return cmd_export(args)
    if command == "report":
        return cmd_report(args)

    print("%s: 未知命令：%r" % (PROG, command), file=sys.stderr)
    return EXIT_USAGE


def _missing_dependency_exit() -> int:  # pragma: no cover - 契约占位说明
    """缺可选依赖的统一出口（模块①②落地后调用）。"""
    return EXIT_MISSING_DEP


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
