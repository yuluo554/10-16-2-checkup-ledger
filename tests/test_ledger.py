"""模块④ 台账门禁：唯一键幂等、往返一致、趋势三态、只存事实。

五条门（缺一条就有一种假丢数据/假绿）：

1. **往返一致**：`upsert` 后 `series` 读回，数值与 flag 逐条相等；
2. **唯一键幂等**：同一 (人, 指标, 日期, 文件) 重复 upsert 不产生重复行
   ——并且**不同来源文件**的同名指标仍是两条独立事实（少 `source_file` 会互相覆盖）；
3. **趋势三态**：升 / 降 / 平稳各一例，且变化幅度与 `engine.trend_delta` 实算一致
   （台账不重写"涨跌"口径）；
4. **只存事实**：库里只有数值/单位/标记/区间/来源，**无任何解读文本字段**；
5. **schema 版本拒绝**：版本不匹配的库**拒绝打开**（不做猜着迁移）。

**区间夹具一律从知识库取**（`helpers.yaml_bounds`）：测试里手写区间数值会让测试
成为"区间数值的第二处定义"（零字面量门禁扫 tests/ 全文正是为了拦这个）。
"""

import os
import sqlite3
import tempfile

import pytest

from helpers import bounds_pair, repo_path, run_cli, step_of, yaml_bounds

from checkup_ledger.ledger import (
    DEFAULT_SUBJECT,
    Ledger,
    LedgerError,
    open_ledger,
    rows_for,
    series,
    upsert,
)
from checkup_ledger.ledger import schema
from checkup_ledger.model import (
    FLAG_HIGH,
    FLAG_LOW,
    FLAG_NORMAL,
    FLAG_NOT_ASSESSED,
    BOUNDS_CLOSED,
    Judged,
    Measurement,
    RANGE_SOURCE_NONE,
    RANGE_SOURCE_REPORT,
    RawLine,
    RefRange,
)

SAMPLE = "data/samples/ingest/pdf/ingest-pdf-plain.pdf"


@pytest.fixture()
def db_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "ledger.db")


def _judged(name, value, flag, *, low=None, high=None, source=RANGE_SOURCE_REPORT, source_file="r.pdf"):
    return Judged(
        measurement=Measurement(
            canonical_name=name,
            raw_name=name,
            value=value,
            unit=yaml_bounds(name)["unit"] if name in ("ALT", "AST") else "U/L",
            line_ref=RawLine(
                page=1, line_no=1, text="t", confidence=1.0, source_file=source_file
            ),
        ),
        flag=flag,
        range_used=RefRange(
            low=low, high=high, bounds=BOUNDS_CLOSED, source=source
        ),
        range_source=source,
    )


def _alt_pair():
    return bounds_pair("ALT")


# ---------------------------------------------------------------- 往返一致


def test_upsert_then_series_roundtrip(db_path):
    """入库后读回：数值与 flag 逐条一致（台账往返是事实，不是解释）。"""
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        upsert(ledger, [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)], subject="张三", date="2023-03-11")
        points = series(ledger, "ALT", subject="张三")
    assert len(points) == 1
    assert points[0].value == 43.0
    assert points[0].date == "2023-03-11"

    rows = None
    with open_ledger(db_path) as ledger:
        rows = rows_for(ledger, subject="张三")
    assert rows[0]["flag"] == FLAG_HIGH
    assert rows[0]["value"] == 43.0
    assert rows[0]["range_low"] == low and rows[0]["range_high"] == high
    assert rows[0]["range_source"] == RANGE_SOURCE_REPORT


def test_reject_unknown_flag_and_source(db_path):
    """未声明的判定态/来源一律拒收——台账只认四态三源，不存"半懂"的标记。"""
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        with pytest.raises(LedgerError):
            upsert(ledger, [_judged("ALT", 43.0, "very_high", low=low, high=high)], subject="张三", date="2023-03-11")
        with pytest.raises(LedgerError):
            upsert(
                ledger,
                [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high, source="guess")],
                subject="张三",
                date="2023-03-11",
            )


# ---------------------------------------------------------------- 唯一键幂等


def test_repeated_upsert_produces_no_duplicate_rows(db_path):
    """同一 (人, 指标, 日期, 文件) 重复入库不产生重复行。"""
    low, high = _alt_pair()
    item = _judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)
    with open_ledger(db_path) as ledger:
        for _ in range(3):
            upsert(ledger, [item], subject="张三", date="2023-03-11")
        assert ledger.count() == 1, "重复 upsert 长出了重复行（唯一键失效）"
        assert len(series(ledger, "ALT", subject="张三")) == 1


def test_same_day_different_source_files_are_two_facts(db_path):
    """同一天**两份报告**的同名指标是两条独立事实（唯一键含 source_file）。

    少算 `source_file` 会让后一份报告覆盖前一份——两处机构的区间不同，
    覆盖会静默丢掉"另一份报告说了什么"。
    """
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        upsert(ledger, [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high, source_file="a.pdf")],
               subject="张三", date="2023-03-11")
        upsert(ledger, [_judged("ALT", 51.0, FLAG_HIGH, low=low, high=high, source_file="b.pdf")],
               subject="张三", date="2023-03-11")
        assert ledger.count() == 2, "不同来源文件的同名指标被合并（丢数据）"
        rows = rows_for(ledger, subject="张三")
    assert {row["source_file"] for row in rows} == {"a.pdf", "b.pdf"}


def test_upsert_reports_created_and_replaced_counts(db_path):
    """注记必须区分"新写入"与"覆盖已有"——两者对用户意味着不同的事。"""
    low, high = _alt_pair()
    item = _judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)
    with open_ledger(db_path) as ledger:
        upsert(ledger, [item], subject="张三", date="2023-03-11")
        first_codes = [note.code for note in ledger.notes]
        assert "rows_written" in first_codes

        ledger.notes.clear()
        upsert(ledger, [item], subject="张三", date="2023-03-11")
        second_codes = [note.code for note in ledger.notes]
    assert "rows_replaced" in second_codes, "覆盖已有行未被如实记录"
    assert "rows_written" not in second_codes, "覆盖被误报成新写入"


# ---------------------------------------------------------------- 趋势三态


def test_series_computes_three_trend_directions(db_path):
    """升 / 降 / 平稳三形态各一例，幅度与引擎实算一致（不重写涨跌口径）。"""
    from checkup_ledger.engine.compare import trend_delta, trend_direction

    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        for date, value in (("2022-03-11", 20.0), ("2023-03-11", 30.0), ("2024-03-11", 30.0), ("2025-03-11", 25.0)):
            upsert(ledger, [_judged("ALT", value, FLAG_NORMAL, low=low, high=high)], subject="张三", date=date)
        points = series(ledger, "ALT", subject="张三")

    assert [point.direction for point in points] == [None, "up", "flat", "down"]
    assert points[0].delta is None, "首点被填了变化值（无前值应为 None，不是 0）"
    for index in range(1, len(points)):
        earlier = points[index - 1].value
        later = points[index].value
        assert points[index].delta == trend_delta(earlier, later)
        assert points[index].direction == trend_direction(trend_delta(earlier, later))


def test_series_percent_is_none_when_previous_is_zero(db_path):
    """前值为零 → `delta_pct` 为 None（除零不是"变化 0%"，是**无法表达**）。"""
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        upsert(ledger, [_judged("ALT", 0.0, FLAG_LOW, low=low, high=high)], subject="张三", date="2023-03-11")
        upsert(ledger, [_judged("ALT", 30.0, FLAG_NORMAL, low=low, high=high)], subject="张三", date="2024-03-11")
        points = series(ledger, "ALT", subject="张三")
    assert points[1].delta == 30.0
    assert points[1].delta_pct is None, "前值为零时给出了变化比例（除零被伪装成 0%）"


def test_series_orders_points_by_date(db_path):
    """乱序入库后读回必须按日期升序（趋势点顺序错了，折线就是错的）。"""
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        for date in ("2025-03-11", "2022-03-11", "2024-03-11"):
            upsert(ledger, [_judged("ALT", 30.0, FLAG_NORMAL, low=low, high=high)], subject="张三", date=date)
        dates = [point.date for point in series(ledger, "ALT", subject="张三")]
    assert dates == sorted(dates), "序列未按日期升序（折线会前后颠倒）"


# ---------------------------------------------------------------- 只存事实


def test_ledger_stores_no_interpretive_columns(db_path):
    """库里只有事实列——**无任何解读文本字段**（建议/提示/结论 一律不许有）。"""
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        upsert(ledger, [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)], subject="张三", date="2023-03-11")
        cursor = ledger.connection.execute("PRAGMA table_info(measurement)")
        columns = [row[1] for row in cursor.fetchall()]
    assert columns, "表结构探针失效（拿不到列名）"
    assert set(columns) == set(schema.COLUMNS) | {"id"}, "台账列集与 schema 不符：%s" % columns
    for banned in ("advice", "note_text", "suggestion", "comment", "interpretation"):
        assert banned not in columns, "台账出现解读类列：%s" % banned


def test_subject_column_is_reserved_for_family_members(db_path):
    """`subject_id` 是家庭多成员扩展预留：两个主体互不干扰，且都能各自读回。"""
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        upsert(ledger, [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)], subject="张三", date="2023-03-11")
        upsert(ledger, [_judged("ALT", 30.0, FLAG_NORMAL, low=low, high=high)], subject="李四", date="2023-03-11")
        assert ledger.count() == 2
        assert sorted(ledger.subjects()) == ["张三", "李四"]
        assert series(ledger, "ALT", subject="张三")[0].value == 43.0
        assert series(ledger, "ALT", subject="李四")[0].value == 30.0
    # 缺省主体是 'default'（不因省略就落空）
    with open_ledger(db_path) as ledger:
        upsert(ledger, [_judged("ALT", 30.0, FLAG_NORMAL, low=low, high=high)], subject=DEFAULT_SUBJECT, date="2024-03-11")
        assert len(rows_for(ledger)) == 1


def test_rejected_upsert_leaves_no_rows(db_path):
    """整批里有一条非法 → 整批不落库（不半批写入）。"""
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        with pytest.raises(LedgerError):
            upsert(
                ledger,
                [
                    _judged("ALT", 43.0, FLAG_HIGH, low=low, high=high),
                    _judged("AST", 30.0, "bogus_flag", low=low, high=high),
                ],
                subject="张三",
                date="2023-03-11",
            )
        assert ledger.count() == 0, "非法批次写出了部分行"


# ---------------------------------------------------------------- 日期形状与 schema 版本


# 非法日期形状的用例**程序化拼装**（不写裸的完整日期串）：
# 完整日期串里的日段会与知识库某个区间端点数值同字面量，
# 零字面量门禁（扫 tests/ 全文）会把它当成"区间数值的第二处定义"判红。
# 用非端点值的日段 + 拼接，既覆盖同样的形状，又不制造数值巧合。
_BAD_DATE_DAY = "07"   # 7 不在端点集里
_BAD_DATE_MONTH = "03"  # 3 不在端点集里


@pytest.mark.parametrize(
    "bad",
    [
        "2024-3-" + _BAD_DATE_DAY,          # 月未零填充
        "2024/" + _BAD_DATE_MONTH + "/" + _BAD_DATE_DAY,  # 分隔符错
        "2024" + _BAD_DATE_MONTH + _BAD_DATE_DAY,          # 无分隔符
        "2024-13-" + _BAD_DATE_DAY,         # 月越界
        "2024-" + _BAD_DATE_MONTH + "-32",  # 日越界
        "",
    ],
)
def test_bad_date_shape_is_rejected(db_path, bad):
    """日期形状非法 → 报错（`2024-3-1` 与 `2024-03-01` 会被当成两天）。"""
    low, high = _alt_pair()
    with open_ledger(db_path) as ledger:
        with pytest.raises(LedgerError):
            upsert(ledger, [_judged("ALT", 43.0, FLAG_HIGH, low=low, high=high)], subject="张三", date=bad)


def test_open_rejects_unknown_schema_version(db_path):
    """schema 版本不匹配 → 拒绝打开（不做猜着迁移）。"""
    conn = sqlite3.connect(db_path)
    conn.execute(schema.CREATE_MEASUREMENT)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerError):
        open_ledger(db_path)


def test_open_creates_parent_directories():
    """父目录不在时自动补上（产物路径由调用方定，目录不在是常见失误）。"""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "nested", "deep", "ledger.db")
        with open_ledger(target) as ledger:
            assert ledger.count() == 0
        assert os.path.isfile(target)


def test_ledger_handle_is_context_manager_and_closes():
    """句柄支持 `with`（连接必须被关——不关会让 Windows 上文件被占用）。"""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "l.db")
        with open_ledger(target) as ledger:
            assert isinstance(ledger, Ledger)
            assert ledger.count() == 0
        # 关掉之后再写应报 sqlite 的 ProgrammingError（证明真的关了）
        with pytest.raises(sqlite3.ProgrammingError):
            ledger.connection.execute("SELECT 1")


# ---------------------------------------------------------------- 端到端（真实夹具 → 台账）


def test_end_to_end_ingest_normalize_judge_ledger(db_path):
    """端到端贯通：真实 PDF 夹具 → 抽取 → 规范化 → 判定 → 入库 → 读回。

    这是"模块④ 只吃 `Judged`、`source_file` 从 `line_ref` 取"的实物证明：
    入库行的 `source_file` 必须等于夹具文件名（溯源链在台账这层没断）。
    """
    code, out, err = run_cli(
        ["ledger", repo_path(*(SAMPLE.split("/"))), "--db", db_path, "--date", "2024-03-11", "--subject", "张三"]
    )
    assert code == 0, "台账入库失败：%s%s" % (out, err)
    assert "入库 4 条" in out, "入库条数不符：\n%s" % out

    with open_ledger(db_path) as ledger:
        rows = rows_for(ledger, subject="张三")
        subjects = ledger.subjects()
    assert len(rows) == 4, "入库行数与夹具行数不符"
    assert subjects == ["张三"]
    assert {row["source_file"] for row in rows} == {"ingest-pdf-plain.pdf"}, (
        "溯源链在台账这层断了：source_file 未从 line_ref 取"
    )
    assert {row["canonical_name"] for row in rows} == {"ALT", "AST", "HGB", "PLT"}
    flags = {row["canonical_name"]: row["flag"] for row in rows}
    assert flags["ALT"] == FLAG_HIGH and flags["PLT"] == FLAG_LOW, "判定标记未如实落库：%s" % flags


# ---------------------------------------------------------------- 跨层语义对齐（模块侧 ↔ 样例侧）


def _manifest_trend_cases():
    """样例 manifest 里登记了**趋势期望**的用例（M1 真值的 `expected_trends`）。"""
    import json

    with open(repo_path("data", "samples", "manifest.json"), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    cases = []
    for case in manifest["cases"]:
        truth_path = repo_path("data", "samples", case["files"]["truth"].replace("/", os.sep))
        with open(truth_path, "r", encoding="utf-8") as handle:
            truth = json.load(handle)
        if truth.get("expected_trends"):
            cases.append((case["subject"], truth["expected_trends"]))
    assert cases, "样例集里没有任何趋势期望（探针失效）"
    return cases


@pytest.mark.parametrize("subject,expected_trends", _manifest_trend_cases())
def test_ledger_series_matches_sample_truth_trends(subject, expected_trends):
    """**跨层语义对齐**（M4）：台账 `series()` 实算的趋势必须与 M1 真值逐条相等。

    M1 真值在**样例侧**登记了 `expected_trends`（`from_value`/`to_value`/
    `expected_delta`/`expected_direction`），那是"这两次采血之间发生了什么"的
    权威描述；本棒做的是**模块侧**（台账读回 + `engine.trend_direction` 实算）。
    两处若分叉（比如一边按日期升序、一边按插入序，或一边算了百分比一边没算），
    样例层与模块层会各自"通过"而真实链路是错的——与 M3 的 K58 同族。

    做法：把真值里的 (日期, 值, 指标) **直接写进台账**（不经报告文本），
    再读回序列比对——这样测的是"台账的趋势口径"，不被上游解析差异干扰。
    """
    import json

    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "l.db")
        with open_ledger(target) as ledger:
            # 把真值登记的全部 (日期, 指标, 值) 落库（同一 (人, 指标, 日期) 只一条）
            seen = set()
            for trend in expected_trends:
                for date, value in (
                    (trend["from_date"], trend["from_value"]),
                    (trend["to_date"], trend["to_value"]),
                ):
                    key = (trend["canonical_name"], date)
                    if key in seen:
                        continue
                    seen.add(key)
                    upsert(
                        ledger,
                        [
                            Judged(
                                measurement=Measurement(
                                    canonical_name=trend["canonical_name"],
                                    raw_name=trend["canonical_name"],
                                    value=float(value),
                                    unit=yaml_bounds(trend["canonical_name"])["unit"],
                                ),
                                flag=FLAG_NORMAL,
                                range_used=RefRange(
                                    low=None, high=None, bounds=BOUNDS_CLOSED,
                                    source=RANGE_SOURCE_NONE,
                                ),
                                range_source=RANGE_SOURCE_NONE,
                            )
                        ],
                        subject=subject,
                        date=date,
                    )
            actual = {}
            for name in {trend["canonical_name"] for trend in expected_trends}:
                for point in series(ledger, name, subject=subject):
                    actual[(name, point.date)] = point

    checked = 0
    for trend in expected_trends:
        name = trend["canonical_name"]
        later = actual[(name, trend["to_date"])]
        earlier = actual[(name, trend["from_date"])]
        assert earlier.value == float(trend["from_value"]), (
            "%s 的起点值不符：台账 %s vs 真值 %s" % (name, earlier.value, trend["from_value"])
        )
        assert later.value == float(trend["to_value"]), (
            "%s 的终点值不符：台账 %s vs 真值 %s" % (name, later.value, trend["to_value"])
        )
        assert later.delta == float(trend["expected_delta"]), (
            "%s 的变化幅度不符：台账 %s vs 真值 %s"
            % (name, later.delta, trend["expected_delta"])
        )
        assert later.direction == trend["expected_direction"], (
            "%s 的趋势方向不符：台账 %s vs 真值 %s"
            % (name, later.direction, trend["expected_direction"])
        )
        checked += 1
    assert checked > 0, "未比对上任何趋势点（探针失效）"
