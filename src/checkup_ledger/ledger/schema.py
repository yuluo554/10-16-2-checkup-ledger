"""台账 schema（**M0 定稿**，本模块是它的唯一实现处）。

```sql
CREATE TABLE measurement (
  id INTEGER PRIMARY KEY,
  subject_id TEXT NOT NULL DEFAULT 'default',   -- 家庭多成员扩展预留
  canonical_name TEXT NOT NULL,
  date TEXT NOT NULL,                            -- ISO 8601，显式传入
  value REAL NOT NULL,
  unit TEXT NOT NULL,
  flag TEXT NOT NULL,                            -- high|low|normal|not_assessed
  range_low REAL, range_high REAL,
  range_source TEXT NOT NULL,                    -- report_printed|builtin_default|none
  source_file TEXT,
  created_at TEXT                                -- 仅本机元信息，不入导出物
);
CREATE UNIQUE INDEX ux_measure ON measurement(subject_id, canonical_name, date, source_file);
```

三条落地注记（都是"改了会打挂测试"的口径）：

1. **唯一键四列一列都不能少**：`(subject_id, canonical_name, date, source_file)` 是
   "同一次采血里同一指标"的身份。少了 `source_file`，同一天两份报告的同名指标会
   互相覆盖；少了 `date`，跨年同一份文件名的记录会被合并——**两种丢数据都不报错**。
2. **`source_file` 写入时不留 NULL**：SQLite 的唯一索引里 NULL 彼此不相等，留 NULL
   会让"重复 upsert"绕过唯一键、悄悄长出重复行。故来源未知时写空串（**有值的空串**，
   不是 NULL），并在注记里说明。
3. **schema 版本走 `PRAGMA user_version`**（不是自建 meta 表）：版本号是库级属性，
   不占一张业务表；版本不匹配**拒绝打开**（`LedgerError`），不做"猜着迁移"
   ——静默迁移会把旧库读成半新半旧的状态。
"""

SCHEMA_VERSION = 1

CREATE_MEASUREMENT = """
CREATE TABLE IF NOT EXISTS measurement (
  id INTEGER PRIMARY KEY,
  subject_id TEXT NOT NULL DEFAULT 'default',
  canonical_name TEXT NOT NULL,
  date TEXT NOT NULL,
  value REAL NOT NULL,
  unit TEXT NOT NULL,
  flag TEXT NOT NULL,
  range_low REAL,
  range_high REAL,
  range_source TEXT NOT NULL,
  source_file TEXT,
  created_at TEXT
)
"""

CREATE_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_measure
ON measurement(subject_id, canonical_name, date, source_file)
"""

# 落库列序（写入语句与读回语句共用，防两处列序写歪）。
COLUMNS = (
    "subject_id",
    "canonical_name",
    "date",
    "value",
    "unit",
    "flag",
    "range_low",
    "range_high",
    "range_source",
    "source_file",
    "created_at",
)

INSERT_MEASUREMENT = "INSERT INTO measurement (%s) VALUES (%s)" % (
    ", ".join(COLUMNS),
    ", ".join(["?"] * len(COLUMNS)),
)

# UPSERT：冲突时**覆盖为最新一次判定**（同一份报告重跑，判定口径可能已更新）。
# 不写 `DO NOTHING`——那会让"重跑后库里还是旧结论"且毫无提示。
UPSERT_MEASUREMENT = INSERT_MEASUREMENT + """
ON CONFLICT(subject_id, canonical_name, date, source_file) DO UPDATE SET
  value = excluded.value,
  unit = excluded.unit,
  flag = excluded.flag,
  range_low = excluded.range_low,
  range_high = excluded.range_high,
  range_source = excluded.range_source,
  created_at = excluded.created_at
"""

SELECT_SERIES = """
SELECT canonical_name, date, value, flag, range_low, range_high, range_source
FROM measurement
WHERE subject_id = ? AND canonical_name = ?
ORDER BY date ASC, id ASC
"""

SELECT_INDICATORS = """
SELECT DISTINCT canonical_name
FROM measurement
WHERE subject_id = ?
ORDER BY canonical_name ASC
"""

SELECT_DATES = """
SELECT DISTINCT date
FROM measurement
WHERE subject_id = ?
ORDER BY date ASC
"""
