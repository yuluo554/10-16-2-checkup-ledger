"""模块① 输入层的合成夹具生成器：确定性产出 `data/samples/ingest/`。

产物（全部位级冻结入仓，`--check` 可再生成逐字节比对）：

| 产物 | 形态 | 治什么 |
|---|---|---|
| `pdf/*.pdf` | 文本层可读 PDF（正常 / 逐字定位 / 补白） | 伪空格、补白归一、跨行聚类 |
| `scan/*.png` | 笔画字体渲染的扫描件（含一份降质） | OCR 兜底、低置信复核闭环 |
| `truth/*.truth.json` | 只存"输入与期望行" | 端到端回归的期望值 |

三条纪律（与 M1 的 `gen_samples.py` 同源）：
1. **禁 stdlib `random` / 时钟 / `hash()`**：产物必须两次运行逐字节一致；
2. **区间数值只在知识库一处定义**：本文件不写任何区间数值，从 `indicators.yaml` 取；
3. **真值库只存输入与期望**，不存观测字段（守门测试扫 `observed`/`actual`/`got`）。

扫描件的低置信行**不用随机噪声碰运气**：用 `scanrender` 的确定性噪声模式，
实测能让 OCR 的该行分值落进阈值以下（`ocr_threshold` 取自随包配置，不写死）。

用法：
    py -3.12 tools/gen_ingest_fixtures.py            # 生成/覆盖
    py -3.12 tools/gen_ingest_fixtures.py --check    # 位级一致校验
"""

import argparse
import json
import os
import sys
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
for extra in (SRC, HERE):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from checkup_ledger.config import load_config  # noqa: E402
from checkup_ledger.ingest.lines import (  # noqa: E402
    SPACE_POLICY_ADVANCE,
    SPACE_POLICY_ALWAYS,
    assemble_lines,
    boxes_to_fragments,
    chars_to_fragments,
)
from checkup_ledger.loader import load_indicators  # noqa: E402
from checkup_ledger.serialize import write_atomic  # noqa: E402

from fixtures import pdfwrite, scanrender  # noqa: E402

OUT_DIR = os.path.join(ROOT, "data", "samples", "ingest")
INDICATORS_PATH = os.path.join(SRC, "checkup_ledger", "data", "indicators.yaml")
SCHEMA_VERSION = 1

# 固定 seed：改它等于换一套夹具（须同步重算台账 sha256）
SEED = 20261016


# ============================================================ 区间夹具（全部来自 YAML）


def _yaml_bounds(canonical_name: str) -> Dict[str, object]:
    """从知识库取该条目的区间（**区间数值的唯一来源**）。"""
    table = load_indicators(INDICATORS_PATH)
    for entry in table.entries:
        if entry.canonical_name == canonical_name:
            ref = entry.default_range
            return {"low": ref.low, "high": ref.high, "bounds": ref.bounds, "unit": entry.unit}
    raise KeyError("知识库无此条目：%s" % canonical_name)


def _format_range(low, high) -> str:
    """把区间端点渲染成报告上的写法（`low-high`）。"""
    def _num(value):
        if value is None:
            return ""
        if float(value).is_integer():
            return str(int(value))
        return repr(value)

    return "%s-%s" % (_num(low), _num(high))


def _row_texts(name: str, value: str, unit: str, range_text: str) -> List[str]:
    """报告里一行的四列文本。"""
    return [name, value, unit, range_text]


# ============================================================ 用例定义（输入 + 期望）


def _value_in_range(low, high) -> str:
    """区间内取一个确定值（两端点的算术中点，用整数写法）。"""
    if low is None or high is None:
        raise ValueError("需要完整区间才能取中点：%r %r" % (low, high))
    mid = (float(low) + float(high)) / 2.0
    if mid.is_integer():
        return str(int(mid))
    return repr(mid)


def _value_above(high) -> str:
    """略高于上限（用端点本身 + 步长 1，步长由 YAML 写法实算）。"""
    if high is None:
        raise ValueError("需要上限")
    step = 1.0 if float(high).is_integer() else 0.1
    out = float(high) + step
    return str(int(out)) if out.is_integer() else repr(out)


def _value_below(low) -> str:
    if low is None:
        raise ValueError("需要下限")
    step = 1.0 if float(low).is_integer() else 0.1
    out = float(low) - step
    return str(int(out)) if out.is_integer() else repr(out)


def _pdf_cases() -> List[dict]:
    """PDF 夹具用例：三种形态各一份，期望是**同一份正确行文本**。

    这份"同一期望"本身就是断言：三条路径（正常 / 逐字定位 / 补白）经装配后
    必须得到**逐字相同**的行——形态差异不该泄漏到行文本里。
    """
    alt = _yaml_bounds("ALT")
    ast = _yaml_bounds("AST")
    hgb = _yaml_bounds("HGB")
    plt = _yaml_bounds("PLT")

    rows = [
        _row_texts("ALT", _value_above(alt["high"]), alt["unit"], _format_range(alt["low"], alt["high"])),
        _row_texts("AST", _value_in_range(ast["low"], ast["high"]), ast["unit"], _format_range(ast["low"], ast["high"])),
        _row_texts("HGB", _value_in_range(hgb["low"], hgb["high"]), hgb["unit"], _format_range(hgb["low"], hgb["high"])),
        _row_texts("PLT", _value_below(plt["low"]), plt["unit"], _format_range(plt["low"], plt["high"])),
    ]
    expected_lines = [" ".join(row) for row in rows]

    return [
        {
            "case_id": "ingest-pdf-plain",
            "layout": pdfwrite.PLAIN,
            "rows": rows,
            "expected_lines": expected_lines,
            "tags": ["ingest:pdf_text_layer", "layout:plain"],
        },
        {
            "case_id": "ingest-pdf-per-char",
            "layout": pdfwrite.PER_CHAR,
            "rows": rows,
            "expected_lines": expected_lines,
            "tags": ["ingest:pdf_text_layer", "trap:pseudo_space"],
        },
        {
            "case_id": "ingest-pdf-padded",
            "layout": pdfwrite.PADDED,
            "rows": rows,
            "expected_lines": expected_lines,
            "tags": ["ingest:pdf_text_layer", "trap:padding_normalized"],
        },
    ]


def _scan_cases() -> List[dict]:
    """扫描件夹具用例：一份清晰（全部达标）+ 一份降质（含低置信行）。

    **刻意避开"含次方符号的单位写法"**（如十的九次方每升那类）：实测本夹具的笔画
    字体在该字号下，OCR 会把次方符号读成波浪线/大于号（"次方符号"在 4×6 字形盒里
    与波浪线区分度不足）。这是**字体渲染的真实局限**，不是引擎缺陷——故夹具选含
    `umol/L` / `mmol/L` / `U/L` 的条目（覆盖同样多的路径，且读数可靠）。
    该局限如实记入 plan/06。
    """
    alt = _yaml_bounds("ALT")
    crea = _yaml_bounds("CREA")
    tc = _yaml_bounds("TC")
    tbil = _yaml_bounds("TBIL")

    clean_rows = [
        _row_texts("ALT", _value_above(alt["high"]), alt["unit"], _format_range(alt["low"], alt["high"])),
        _row_texts("CREA", _value_in_range(crea["low"], crea["high"]), crea["unit"], _format_range(crea["low"], crea["high"])),
        _row_texts("TBIL", _value_in_range(tbil["low"], tbil["high"]), tbil["unit"], _format_range(tbil["low"], tbil["high"])),
        _row_texts("TC", _value_above(tc["high"]), tc["unit"], _format_range(tc["low"], tc["high"])),
    ]
    return [
        {
            "case_id": "ingest-scan-clean",
            "noise": False,
            "rows": clean_rows,
            "expected_lines": [" ".join(row) for row in clean_rows],
            "tags": ["ingest:ocr", "confidence:above_threshold"],
        },
        {
            "case_id": "ingest-scan-degraded",
            "noise": True,
            "rows": clean_rows,
            "expected_lines": [" ".join(row) for row in clean_rows],
            "tags": ["ingest:ocr", "confidence:below_threshold", "review:pending_not_stored"],
        },
    ]


# ============================================================ 期望行（真值）

NOTE_EXPECTED_TEXT = "期望行文本（由用例的行定义导出；回归测试验装配器能否复现它）"


def _build_truth(case: dict, expected_lines: List[str]) -> dict:
    return {
        "case_id": case["case_id"],
        "expected_lines": list(expected_lines),
        "tags": list(case["tags"]),
        "note": NOTE_EXPECTED_TEXT,
    }


# ============================================================ 生成


def _rel(path: str) -> str:
    """仓库根相对路径（POSIX 形式）。仅用于**仓库内**的路径。"""
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def _logical(rel_under_ingest: str) -> str:
    """`data/samples/ingest/` 下的逻辑相对路径（与磁盘位置无关）。

    `--check` 会在临时目录里重生成，那里可能与仓库**不在同一个盘符**上
    （本机 tempfile 在 C:、仓库在 D:）。用 `os.path.relpath` 跨盘会抛
    ValueError——于是校验在换机器/换盘时直接崩，而不是给出结论。
    故登记路径一律由**逻辑常量**拼出，不依赖临时目录的位置。
    """
    return "data/samples/ingest/" + rel_under_ingest


def _write_json(path: str, payload: dict) -> None:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    write_atomic(path, text.replace("\r\n", "\n") + "\n")


def _render_pdf(case: dict, target: str) -> None:
    """整份报告**单页多行**（一份报告就是一页，不是一行一页）。

    早先按"每行一页"写会造出 4 页的报告——那与真实形态不符，也让"页内行序"
    这类断言失去意义（每页只有一行，行序永远对）。
    """
    page = [(case["layout"], " ".join(row)) for row in case["rows"]]
    payload = pdfwrite.build_pdf([page])
    from checkup_ledger.serialize import write_atomic as write_bytes

    write_bytes(target, payload)


def _render_scan(case: dict, target: str) -> None:
    scanrender.render_columns(case["rows"], target, noise=case["noise"])


def generate() -> List[dict]:
    """生成全部夹具，返回产物登记表（供 manifest 与台账使用）。"""
    artifacts: List[dict] = []

    for case in _pdf_cases():
        path = os.path.join(OUT_DIR, "pdf", case["case_id"] + ".pdf")
        _render_pdf(case, path)
        truth_path = os.path.join(OUT_DIR, "truth", case["case_id"] + ".truth.json")
        _write_json(truth_path, _build_truth(case, case["expected_lines"]))
        artifacts.append(
            _register(case, _logical("pdf/%s.pdf" % case["case_id"]),
                      _logical("truth/%s.truth.json" % case["case_id"]), "pdf")
        )

    for case in _scan_cases():
        path = os.path.join(OUT_DIR, "scan", case["case_id"] + ".png")
        _render_scan(case, path)
        truth_path = os.path.join(OUT_DIR, "truth", case["case_id"] + ".truth.json")
        _write_json(truth_path, _build_truth(case, case["expected_lines"]))
        artifacts.append(
            _register(case, _logical("scan/%s.png" % case["case_id"]),
                      _logical("truth/%s.truth.json" % case["case_id"]), "scan")
        )

    _write_manifest(artifacts)
    return artifacts


def _register(case: dict, file_rel: str, truth_rel: str, kind: str) -> dict:
    return {
        "case_id": case["case_id"],
        "kind": kind,
        "file": file_rel,
        "truth": truth_rel,
        "rows": len(case["rows"]),
        "tags": list(case["tags"]),
    }


def _manifest(artifacts: List[dict]) -> dict:
    cfg = load_config()
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_seed": SEED,
        "ocr_threshold_source": _rel(os.path.join(SRC, "checkup_ledger", "data", "config.yaml")),
        "ocr_threshold": cfg.ocr_threshold,
        "coverage_note": "本夹具为**抽样覆盖，非穷举**：三种 PDF 形态 + 一份降质扫描件，"
                         "覆盖伪空格/补白归一/OCR 兜底/低置信复核四条路径。",
        "cases": sorted(artifacts, key=lambda item: item["case_id"]),
    }


def _write_manifest(artifacts: List[dict]) -> None:
    _write_json(os.path.join(OUT_DIR, "manifest.json"), _manifest(artifacts))


# ============================================================ --check


def check() -> int:
    """位级一致校验：再生成与磁盘产物逐字节比对。

    临时目录可能落在**另一个盘符**上（本机 `tempfile` 在 C:，仓库在 D:），
    故比对路径一律由"仓库根的相对路径"拼出，不用 `os.path.relpath` 跨盘计算
    （跨盘会抛 ValueError，那会让校验在换机器时直接崩而不是给结论）。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        global OUT_DIR
        original = OUT_DIR
        temp_out = os.path.join(tmp, "ingest")
        OUT_DIR = temp_out
        try:
            artifacts = generate()
        finally:
            OUT_DIR = original

        prefix = "data/samples/ingest/"

        def _produced(rel: str) -> str:
            """临时目录里该逻辑路径对应的实际文件（按逻辑前缀改写，不用 relpath 跨盘）。"""
            assert rel.startswith(prefix), "登记路径不在预期前缀内：%s" % rel
            return os.path.join(temp_out, rel[len(prefix):].replace("/", os.sep))

        problems = []
        for item in artifacts:
            for key in ("file", "truth"):
                rel = item[key]
                if not os.path.isfile(_produced(rel)):
                    problems.append("再生成未产出：%s（生成器漏写）" % rel)
                    continue
                on_disk = os.path.join(ROOT, rel.replace("/", os.sep))
                if not os.path.isfile(on_disk):
                    problems.append("磁盘缺产物：%s（先跑不带 --check 的生成）" % rel)
                    continue
                if _sha256(_produced(rel)) != _sha256(on_disk):
                    problems.append("位级不一致：%s" % rel)
        manifest_rel = prefix + "manifest.json"
        if not os.path.isfile(_produced(manifest_rel)):
            problems.append("再生成未产出：%s" % manifest_rel)
        elif not os.path.isfile(os.path.join(ROOT, manifest_rel.replace("/", os.sep))):
            problems.append("磁盘缺产物：%s" % manifest_rel)
        elif _sha256(_produced(manifest_rel)) != _sha256(os.path.join(ROOT, manifest_rel.replace("/", os.sep))):
            problems.append("位级不一致：%s" % manifest_rel)

    if problems:
        sys.stderr.write("夹具位级校验失败（%d 项）：\n" % len(problems))
        for item in problems:
            sys.stderr.write("  · %s\n" % item)
        return 1

    print("夹具位级校验通过：%d 组用例的产物与再生成逐字节一致。" % len(artifacts))
    return 0


def _sha256(path: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="模块① 输入层合成夹具（确定性生成）")
    parser.add_argument("--check", action="store_true", help="只校验再生成与磁盘位级一致")
    args = parser.parse_args(argv)

    if args.check:
        return check()

    artifacts = generate()
    print("已生成 %d 组夹具 → %s" % (len(artifacts), _rel(OUT_DIR)))
    for item in artifacts:
        print("  [%s] %s（%d 行）" % (item["kind"], item["file"], item["rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
