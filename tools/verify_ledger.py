"""数据资产台账：`data/ledger/assets.csv`（sha256 清单，**生成物非手编**）。

台账是**生成物**（plan/04 第一节 C 类）：`--update` 重算全部 sha256 写入；
`--verify` 复核磁盘现状与台账是否一致。**手改台账 = 与实算漂移**，
配守门测试当场检出（判据 = 台账每格都能由脚本从被登记对象复算出来）。

登记范围（B 类合成样例集 + A 类内置知识库）：
- `src/checkup_ledger/data/indicators.yaml`（运行时必需，随包分发）；
- `data/samples/` 下全部产物（cases / truth / manifest）。

为什么把 A 类也登记：它同样需要"改了就看得见"——知识库条目变动若无声无息，
"区间数值只在 YAML 一处定义"的纪律就没有可指认的变更痕迹。

用法：
    py -3.12 tools/verify_ledger.py --update   # 重算并写入台账
    py -3.12 tools/verify_ledger.py --verify   # 复核磁盘与台账一致（CI/守门用）
"""

import argparse
import csv
import hashlib
import io
import os
import sys
from typing import List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

LEDGER_PATH = os.path.join(ROOT, "data", "ledger", "assets.csv")
SAMPLES_DIR = os.path.join(ROOT, "data", "samples")
INDICATORS = os.path.join(ROOT, "src", "checkup_ledger", "data", "indicators.yaml")

# CSV 列顺序固定（生成物；手改会被 --verify 检出）
COLUMNS = ("asset_class", "rel_path", "bytes", "sha256")

# 二进制/冻结件的扩展名：这些在 .gitattributes 里标了 -text，字节不该被归一化，
# 故台账必须逐字节核对（一旦有人"顺手格式化"就会失配）。
_BINARY_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".db", ".sqlite", ".zip", ".exe", ".onnx")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def collect_assets() -> List[dict]:
    """收集全部登记对象（**按 POSIX 相对路径排序**，保证台账行序确定）。"""
    assets = []
    if os.path.isfile(INDICATORS):
        assets.append(
            {
                "asset_class": "A-内置知识库",
                "rel_path": _rel(INDICATORS),
                "abs_path": INDICATORS,
            }
        )
    else:
        raise RuntimeError("内置知识库缺失：%s" % INDICATORS)

    if not os.path.isdir(SAMPLES_DIR):
        raise RuntimeError("样例集目录缺失：%s（先跑 tools/gen_samples.py）" % SAMPLES_DIR)

    found = 0
    for dirpath, dirs, names in os.walk(SAMPLES_DIR):
        dirs.sort()  # 目录序确定（不用集合迭代序）
        for name in sorted(names):
            abs_path = os.path.join(dirpath, name)
            assets.append(
                {
                    "asset_class": "B-合成样例",
                    "rel_path": _rel(abs_path),
                    "abs_path": abs_path,
                }
            )
            found += 1
    if found == 0:
        raise RuntimeError("样例集为空：%s（先跑 tools/gen_samples.py）" % SAMPLES_DIR)

    assets.sort(key=lambda item: item["rel_path"])
    return assets


def build_rows() -> List[dict]:
    """算出台账每一行（class / 路径 / 字节数 / sha256）——台账的唯一真值来源。"""
    rows = []
    for asset in collect_assets():
        rows.append(
            {
                "asset_class": asset["asset_class"],
                "rel_path": asset["rel_path"],
                "bytes": os.path.getsize(asset["abs_path"]),
                "sha256": _sha256(asset["abs_path"]),
            }
        )
    return rows


def render_csv(rows: List[dict]) -> str:
    """台账 CSV 文本：固定列序 + LF + 结尾单换行（与 serialize 的约定一致）。"""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    text = buffer.getvalue()
    return text.replace("\r\n", "\n")


def update() -> int:
    rows = build_rows()
    from checkup_ledger.serialize import write_atomic  # 写盘单点

    write_atomic(LEDGER_PATH, render_csv(rows))
    print("台账已更新：%s（%d 条资产）" % (_rel(LEDGER_PATH), len(rows)))
    return 0


def verify() -> int:
    """复核：磁盘现状与台账逐行一致（**含手改检测**）。"""
    if not os.path.isfile(LEDGER_PATH):
        sys.stderr.write("台账缺失：%s（先跑 --update）\n" % _rel(LEDGER_PATH))
        return 1

    with open(LEDGER_PATH, "r", encoding="utf-8", newline="") as handle:
        on_disk = list(csv.DictReader(handle))

    expected = build_rows()

    problems = []
    disk_by_path = {row["rel_path"]: row for row in on_disk}
    expected_by_path = {row["rel_path"]: row for row in expected}

    for path in sorted(set(disk_by_path) | set(expected_by_path)):
        if path not in disk_by_path:
            problems.append("台账漏登记：%s" % path)
            continue
        if path not in expected_by_path:
            problems.append("台账多登记（磁盘已无此文件）：%s" % path)
            continue
        disk_row, want_row = disk_by_path[path], expected_by_path[path]
        for column in COLUMNS:
            if str(disk_row.get(column)) != str(want_row[column]):
                problems.append(
                    "%s 的 %s 不一致：台账 %r vs 实算 %r"
                    % (path, column, disk_row.get(column), want_row[column])
                )

    if problems:
        sys.stderr.write("台账复核失败（%d 项）：\n" % len(problems))
        for item in problems:
            sys.stderr.write("  · %s\n" % item)
        sys.stderr.write("处置：跑 `py tools/verify_ledger.py --update` 重算（台账是生成物，不手改）。\n")
        return 1

    print("台账复核通过：%d 条资产的 sha256 与磁盘逐字节一致。" % len(expected))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="数据资产台账（sha256，生成物）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--update", action="store_true", help="重算并写入台账")
    mode.add_argument("--verify", action="store_true", help="复核磁盘与台账一致")
    args = parser.parse_args(argv)

    if args.update:
        return update()
    return verify()


if __name__ == "__main__":
    sys.exit(main())
