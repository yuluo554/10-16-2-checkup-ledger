"""模块④ 纵向台账：SQLite 持久层（**只存事实数值与判定标记**）。

职责边界（plan/03 模块④）：已判定记录 → 本地 SQLite 台账（按人/指标/日期）。
本层**不做判定**（判定是模块③ 的事，台账只接收 `Judged`），也**不做解读**
（不写任何建议/注意/风险类文本——库里只有数值、单位、标记与区间来源）。

分层纪律（静态门禁守）：
- **判定链（`engine/compare.py`）不得 import 本模块**：它是持久层，判定内核必须保持
  纯函数；台账能反向依赖判定层（消费 `Judged`），但不得被判定层依赖。
- 趋势三态由 `engine.trend_direction` **一处实算**（`series()` 调用它），
  台账不重写"涨跌"口径。

三个对外入口：
- `open_ledger(path)`：建表/版本校验，返回 `Ledger`；
- `upsert(ledger, judged, *, subject, date)`：唯一键幂等写入，返回新写入行数；
- `series(ledger, canonical_name, *, subject)`：读回时间序列（含趋势三态）。
"""

import os
import sqlite3
from typing import Dict, List, Optional

from checkup_ledger.engine.compare import trend_delta, trend_direction
from checkup_ledger.ledger import schema
from checkup_ledger.ledger.errors import LedgerError
from checkup_ledger.model import (
    ALL_FLAGS,
    ALL_RANGE_SOURCES,
    ALL_TRENDS,
    Judged,
    Note,
    TrendPoint,
)

DEFAULT_SUBJECT = "default"

# 日期形状的**日历结构**常量（不是参考区间数值，也不是可调阈值）：
# 年 4 位、月 2 位、日 2 位的零填充宽度；一年 12 个月；一月最多 31 天。
DATE_WIDTHS = (4, 2, 2)
MONTHS_PER_YEAR = 12
DAYS_PER_MONTH_MAX = 31

NOTE_EMPTY_SOURCE = "source_file_absent"
NOTE_INSERTED = "rows_written"
NOTE_UPDATED = "rows_replaced"

_MESSAGE_EMPTY_SOURCE = "有 %d 条记录缺来源文件，已按空值落库（空值不是 NULL——否则唯一键会被绕过）"
_MESSAGE_INSERTED = "新写入 %d 行"
_MESSAGE_UPDATED = "覆盖已有 %d 行（同一 (人, 指标, 日期, 文件) 重跑时更新为最新判定）"


class Ledger:
    """台账句柄：包住一个 SQLite 连接（**本模块是唯一持有持久状态处**）。

    `created_at` 一律为**显式传入值或空串**——不读系统时钟。产物要"同输入双跑
    逐字节一致"，读时钟会让同一次重跑产出不同行（口径见 plan/02 第七节）。
    """

    __slots__ = ("path", "_conn", "notes")

    def __init__(self, path: str, conn: sqlite3.Connection):
        self.path = path
        self._conn = conn
        self.notes: List[Note] = []

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def count(self, *, subject: Optional[str] = None) -> int:
        """库内记录数（`subject` 缺省统计全部主体）。"""
        if subject is None:
            cursor = self._conn.execute("SELECT COUNT(*) FROM measurement")
        else:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM measurement WHERE subject_id = ?", (subject,)
            )
        return int(cursor.fetchone()[0])

    def subjects(self) -> List[str]:
        """库内出现过的全部主体（家庭多成员扩展预留列的实际使用者）。"""
        cursor = self._conn.execute(
            "SELECT DISTINCT subject_id FROM measurement ORDER BY subject_id ASC"
        )
        return [row[0] for row in cursor.fetchall()]

    def indicators(self, *, subject: str = DEFAULT_SUBJECT) -> List[str]:
        """该主体已登记的全部指标（供报告/导出枚举，不靠调用方猜）。"""
        cursor = self._conn.execute(schema.SELECT_INDICATORS, (subject,))
        return [row[0] for row in cursor.fetchall()]

    def dates(self, *, subject: str = DEFAULT_SUBJECT) -> List[str]:
        """该主体已登记的全部日期（升序）。"""
        cursor = self._conn.execute(schema.SELECT_DATES, (subject,))
        return [row[0] for row in cursor.fetchall()]


def open_ledger(path) -> Ledger:
    """打开（必要时创建）台账库。

    - 库不存在 → 建表（schema 版本写 `PRAGMA user_version`）；
    - 库存在且版本一致 → 直接用（不重复建表）；
    - 版本不一致 → `LedgerError`（**拒绝打开**，不做猜着迁移）。

    父目录不存在时创建（与 `serialize.write_atomic` 同形态：产物路径由调用方定，
    但"目录不在"是常见失误，直接补上比抛 OSError 更有用）。
    """
    target = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    try:
        conn = sqlite3.connect(target)
    except sqlite3.Error as exc:
        raise LedgerError("台账库无法打开：%s（%s）" % (target, exc))

    try:
        _ensure_schema(conn, target)
    except LedgerError:
        conn.close()
        raise
    except sqlite3.Error as exc:
        conn.close()
        raise LedgerError("台账库建表失败：%s（%s）" % (target, exc))

    return Ledger(target, conn)


def _ensure_schema(conn: sqlite3.Connection, target: str) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version not in (0, schema.SCHEMA_VERSION):
        raise LedgerError(
            "台账库 schema 版本不匹配：库为 %d，本版本只认 %d（不猜着迁移；"
            "请另存新库或按 plan/03 迁移）" % (version, schema.SCHEMA_VERSION)
        )

    if version == 0:
        conn.execute(schema.CREATE_MEASUREMENT)
        conn.execute(schema.CREATE_UNIQUE_INDEX)
        conn.execute("PRAGMA user_version = %d" % schema.SCHEMA_VERSION)
        conn.commit()


def upsert(
    ledger: Ledger,
    judged: List[Judged],
    *,
    subject: str,
    date: str,
    created_at: str = "",
) -> int:
    """把判定结果写入台账（**唯一键幂等**）。返回本次写入/覆盖的行数。

    唯一键 = `(subject_id, canonical_name, date, source_file)`：同一份报告重跑
    不会长出重复行；同一 (人, 指标, 日期) 但**不同报告文件**则是两条独立事实
    （不同机构印的区间不同，合并会丢掉"区间从哪来"）。

    **只存事实**：数值、单位、判定标记、所用区间与来源；不存任何解读文本。
    区间端点可以缺（拒判时两列皆空）——`range_source` 仍如实记 `none`。

    `created_at` 缺省空串：**不读系统时钟**（见 `Ledger` docstring）。
    """
    _validate_subject(subject)
    _validate_date(date)

    rows = []
    empty_source = 0
    for item in judged:
        flag = item.flag
        if flag not in ALL_FLAGS:
            raise LedgerError("未声明的判定态 flag=%r（台账只收四态）" % (flag,))
        source = item.range_source
        if source not in ALL_RANGE_SOURCES:
            raise LedgerError("未声明的区间来源 range_source=%r" % (source,))

        source_file = ""
        if item.measurement.line_ref is not None:
            source_file = item.measurement.line_ref.source_file or ""
        if not source_file:
            empty_source += 1

        ref = item.range_used
        rows.append(
            (
                subject,
                item.measurement.canonical_name,
                date,
                float(item.measurement.value),
                item.measurement.unit,
                flag,
                None if ref.low is None else float(ref.low),
                None if ref.high is None else float(ref.high),
                source,
                source_file,
                created_at,
            )
        )

    if not rows:
        return 0

    before = _count_for(ledger, subject, rows, date)

    try:
        ledger.connection.executemany(schema.UPSERT_MEASUREMENT, rows)
        ledger.connection.commit()
    except sqlite3.Error as exc:
        ledger.connection.rollback()
        raise LedgerError("台账写入失败：%s" % exc)

    if empty_source:
        ledger.notes.append(Note(NOTE_EMPTY_SOURCE, _MESSAGE_EMPTY_SOURCE % empty_source))
    # 只报**真的发生过**的动作：全批都是覆盖时，报"新写入 0 行"是噪音，
    # 且会让读注记的人以为"这次没写进东西"（其实写了，只是更新了既有行）。
    inserted = len(rows) - before
    if inserted:
        ledger.notes.append(Note(NOTE_INSERTED, _MESSAGE_INSERTED % inserted))
    if before:
        ledger.notes.append(Note(NOTE_UPDATED, _MESSAGE_UPDATED % before))
    return len(rows)


def _count_for(ledger: Ledger, subject: str, rows: List[tuple], date: str) -> int:
    """本次将**覆盖**的已有行数。

    按**完整唯一键**（含 `source_file`）逐条查，不猜：只数"确实已存在、本次会被
    `DO UPDATE` 覆盖"的行。少算 `source_file` 会把"新插入"报成"覆盖"
    ——注记里的数字与实际动作对不上，读注记的人会误判"这份报告已经录过了"。

    列下标从 `schema.COLUMNS` **实算**（不写位置魔数）：写入语句与列序单点定义在
    schema，这里用名字取下标，schema 调序时本函数不会静默取错列。
    """
    name_at = schema.COLUMNS.index("canonical_name")
    source_at = schema.COLUMNS.index("source_file")
    existing = 0
    keys = sorted({(row[name_at], row[source_at]) for row in rows})
    for name, source_file in keys:
        cursor = ledger.connection.execute(
            "SELECT COUNT(*) FROM measurement "
            "WHERE subject_id = ? AND canonical_name = ? AND date = ? AND source_file = ?",
            (subject, name, date, source_file),
        )
        existing += int(cursor.fetchone()[0])
    return existing


def _validate_subject(subject: str) -> None:
    if not isinstance(subject, str) or not subject.strip():
        raise LedgerError("subject 必须是非空字符串（家庭多成员扩展用；缺省值为 %r）" % DEFAULT_SUBJECT)


def _validate_date(date: str) -> None:
    """日期只做**形状**校验（`YYYY-MM-DD`，零填充），不引 datetime（不读时钟、不做时区猜测）。

    为什么要校验：台账的唯一键含 `date`，而 `date` 是**显式传入**的。若不校验，
    `2024-3-1` 与 `2024-03-01` 会被当成两天，同一次采血被拆成两个趋势点
    （用户看到的折线上会多出一个不存在的点）。

    零填充是**必需**的（不是审美）：`2024-3-11` 与 `2024-03-11` 字符串不等，
    但语义相同——唯一键按字符串比对，两种写法会让同一份报告入库两次。
    故宽度必须逐段校验（年 4 位、月 2 位、日 2 位）。

    下界的取值是**日历结构**（一年几个月、一月最多几天），与参考区间端点无关：
    `MONTHS_PER_YEAR` / `DAYS_PER_MONTH_MAX` 是命名常量（不是裸字面量），
    这样零字面量门禁读得懂它们的意图，而不是把它们当成"区间数值的第二处定义"。
    """
    if not isinstance(date, str):
        raise LedgerError("date 必须是字符串（ISO 8601，显式传入）")
    parts = date.split("-")
    if len(parts) != len(DATE_WIDTHS):
        raise LedgerError("date 应为 YYYY-MM-DD 形式，实为 %r" % (date,))
    if not all(part.isdigit() for part in parts):
        raise LedgerError("date 含非数字段：%r" % (date,))
    widths = tuple(len(part) for part in parts)
    if widths != DATE_WIDTHS:
        raise LedgerError(
            "date 各段位数应为 %s（零填充；`2024-3-1` 与 `2024-03-01` 会被当成两天），实为 %r"
            % ("/".join(str(item) for item in DATE_WIDTHS), date)
        )
    _year, month, day = (int(part) for part in parts)
    if not (1 <= month <= MONTHS_PER_YEAR) or not (1 <= day <= DAYS_PER_MONTH_MAX):
        raise LedgerError("date 越界：%r" % (date,))


def series(ledger: Ledger, canonical_name: str, *, subject: str = DEFAULT_SUBJECT) -> List[TrendPoint]:
    """读回单指标时间序列（升序），并实算相邻变化幅度与趋势三态。

    **往返一致**：`upsert` 写入的数值与 `flag` 在 `series` 读回时逐条相等
    （本函数只做读 + 由引擎实算的变化幅度，不重算 H/L）。

    首点无可比前值 → 变化字段为 `None`（不填 0）。
    `delta_pct` 仅在**前值非零**时给出（除零不是"变化 0%"，是**无法表达**）。
    """
    if not isinstance(canonical_name, str) or not canonical_name.strip():
        raise LedgerError("canonical_name 必须是非空字符串")

    cursor = ledger.connection.execute(schema.SELECT_SERIES, (subject, canonical_name))
    rows = cursor.fetchall()

    points: List[TrendPoint] = []
    for index, row in enumerate(rows):
        _name, date, value, _flag, _low, _high, _source = row
        point_value = float(value)
        delta: Optional[float] = None
        delta_pct: Optional[float] = None
        direction: Optional[str] = None
        if index > 0:
            previous = points[index - 1].value
            delta = trend_delta(previous, point_value)
            direction = trend_direction(delta)
            if direction not in ALL_TRENDS:
                raise LedgerError("实算出未声明的趋势态：%r" % (direction,))
            if previous != 0:
                delta_pct = delta / previous
        points.append(
            TrendPoint(
                canonical_name=canonical_name,
                date=date,
                value=point_value,
                delta=delta,
                delta_pct=delta_pct,
                direction=direction,
            )
        )
    return points


def rows_for(ledger: Ledger, *, subject: str = DEFAULT_SUBJECT) -> List[Dict[str, object]]:
    """读回该主体全部记录（按日期、指标排序）——导出/渲染的**唯一取数口**。

    返回的是**事实字段的字典**（不含任何解读）：`canonical_name` / `date` / `value`
    / `unit` / `flag` / `range_low` / `range_high` / `range_source` / `source_file`。
    导出与渲染都从这里取数，不各自写一条 SELECT（两处取数 = 两处口径）。
    """
    cursor = ledger.connection.execute(
        """
        SELECT canonical_name, date, value, unit, flag, range_low, range_high,
               range_source, source_file
        FROM measurement
        WHERE subject_id = ?
        ORDER BY date ASC, canonical_name ASC, id ASC
        """,
        (subject,),
    )
    keys = (
        "canonical_name",
        "date",
        "value",
        "unit",
        "flag",
        "range_low",
        "range_high",
        "range_source",
        "source_file",
    )
    return [dict(zip(keys, row)) for row in cursor.fetchall()]


def latest_series_rows(ledger: Ledger, *, subject: str = DEFAULT_SUBJECT) -> List[Dict[str, object]]:
    """每指标的最新一条记录（供就诊摘要的"最近一次"视图）。"""
    rows = rows_for(ledger, subject=subject)
    latest: Dict[str, Dict[str, object]] = {}
    for row in rows:  # rows 已按 date 升序 → 后写覆盖前写即"最新"
        latest[row["canonical_name"]] = row
    return [latest[name] for name in sorted(latest)]
