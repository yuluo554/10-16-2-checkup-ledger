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


def _yaml_probe_literal():
    """从知识库取一个区间数值作为变异探针（**不在本文件写死**）。

    变异载荷里若直接写死一个区间数值，本文件自己就成了"区间数值的第二处定义"
    ——零字面量门禁会（正确地）把它拦下。故探针值从 YAML 实算。
    """
    import yaml

    path = os.path.join(SRC, "checkup_ledger", "data", "indicators.yaml")
    with open(path, "r", encoding="utf-8") as handle:
        root = yaml.safe_load(handle)
    for entry in root["indicators"]:
        rng = entry.get("default_range") or {}
        for key in ("low", "high"):
            value = rng.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value) if float(value).is_integer() else value
    raise RuntimeError("知识库没有任何区间数值可用作探针")


def _load_mutations():
    """变异表：文件 / 原串 / 新串 / 说明 / 该变红的目标命令。"""
    probe = _yaml_probe_literal()
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
        # ---- M1：数据先行层新增守门 ----
        {
            "name": "engine-塞入区间字面量",
            "file": os.path.join(SRC, "checkup_ledger", "engine", "compare.py"),
            "old": "def compare(value: float, ref: RefRange) -> str:",
            "new": "LEAKED_THRESHOLD = %s  # 变异：往引擎塞区间字面量\n\n\ndef compare(value: float, ref: RefRange) -> str:" % probe,
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_no_literal_thresholds.py"],
            "target": "零字面量门禁（引擎不得出现区间数值）",
        },
        {
            "name": "engine-忽略适用域",
            "file": os.path.join(SRC, "checkup_ledger", "engine", "compare.py"),
            "old": "    if default is not None and range_applies_to(default_constraint, subject_sex):",
            "new": "    if default is not None:  # 变异：忽略适用域",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_samples.py"],
            "target": "样例层（applies_to.sex 生效）",
        },
        {
            "name": "engine-趋势方向判反",
            "file": os.path.join(SRC, "checkup_ledger", "engine", "compare.py"),
            "old": "    if delta > 0:\n        return TREND_UP",
            "new": "    if delta > 0:\n        return TREND_DOWN  # 变异：趋势判反",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_samples.py"],
            "target": "样例层（趋势三态）",
        },
        {
            "name": "gen-改用系统时钟",
            "file": os.path.join(HERE, "gen_samples.py"),
            "old": "import argparse\nimport os\nimport sys",
            "new": "import argparse\nimport os\nimport sys\nimport time  # 变异：引入非确定性来源",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_samples.py"],
            "target": "生成器确定性（禁时钟）",
        },
        {
            "name": "gen-真值改存观测",
            "file": os.path.join(HERE, "gen_samples.py"),
            "old": "            \"expected_flag\": flag,",
            "new": "            \"expected_flag\": flag,\n            \"observed_flag\": flag,  # 变异：真值库里塞观测",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_samples.py"],
            "target": "真值库无观测字段",
        },
        {
            "name": "samples-未复核行也落库",
            "file": os.path.join(HERE, "gen_samples.py"),
            "old": "        if row[\"pending_review\"]:\n            pending.append(",
            "new": "        if False:  # 变异：未复核行也落库\n            pending.append(",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_samples.py"],
            "target": "低置信复核（未复核不落库）",
        },
        {
            "name": "ledger-手改台账",
            "file": os.path.join(ROOT, "data", "ledger", "assets.csv"),
            "old": "asset_class,rel_path,bytes,sha256",
            "new": "asset_class,rel_path,bytes,sha256\nB-伪造,data/samples/伪造.txt,1,0000000000000000000000000000000000000000000000000000000000000000",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_samples.py"],
            "target": "台账是生成物（手改被检出）",
        },
        # ---- M2：输入层新增守门 ----
        {
            "name": "review-未复核也放行",
            "file": os.path.join(SRC, "checkup_ledger", "ingest", "review.py"),
            "old": "        record = table.get(_line_key(line))\n        if record is None:\n            continue",
            "new": "        record = table.get(_line_key(line))\n        if record is None:\n            admitted.append(line)  # 变异：未复核也放行\n            continue",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ingest.py"],
            "target": "输入层（未复核不向下传递）",
        },
        {
            "name": "review-空确认值也放行",
            "file": os.path.join(SRC, "checkup_ledger", "ingest", "review.py"),
            "old": "        confirmed = record.confirmed_text.strip()\n        if not confirmed:\n            continue",
            "new": "        confirmed = record.confirmed_text.strip()\n        if False:\n            continue  # 变异：空确认值也放行",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ingest.py"],
            "target": "输入层（空白确认值不放行）",
        },
        {
            "name": "review-孤儿留痕不报错",
            "file": os.path.join(SRC, "checkup_ledger", "ingest", "review.py"),
            "old": "        if key not in pending_keys:\n            raise IngestError(",
            "new": "        if False:\n            raise IngestError(  # 变异：孤儿留痕静默忽略",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ingest.py"],
            "target": "输入层（留痕对不上必报错）",
        },
        {
            "name": "ingest-低置信切分失效",
            "file": os.path.join(SRC, "checkup_ledger", "ingest", "review.py"),
            "old": "        if line.confidence < threshold:\n            pending.append(line)",
            "new": "        if False:\n            pending.append(line)  # 变异：低置信行不进待复核",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ingest.py"],
            "target": "输入层（低置信行强制复核）",
        },
        {
            "name": "ingest-缺依赖裸抛",
            "file": os.path.join(SRC, "checkup_ledger", "ingest", "deps.py"),
            "old": "    except ImportError as exc:\n        raise MissingDependencyError(",
            "new": "    except ImportError as exc:\n        raise exc  # 变异：缺依赖裸抛，不走契约",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ingest.py"],
            "target": "输入层（缺依赖走 exit 3 契约）",
        },
        {
            "name": "config-缺字段静默取默认",
            "file": os.path.join(SRC, "checkup_ledger", "config.py"),
            "old": "    if OCR_THRESHOLD_KEY not in root:\n        raise ConfigError(",
            "new": "    if OCR_THRESHOLD_KEY not in root:\n        return Config(ocr_threshold=0.8)  # 变异：静默取默认值",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_config.py"],
            "target": "配置（缺字段必报错，代码零默认值）",
        },
        {
            "name": "ingest-伪空格归一失效",
            "file": os.path.join(SRC, "checkup_ledger", "ingest", "lines.py"),
            "old": "        if previous is not None and threshold > 0 and (fragment.x0 - previous.x1) > threshold:\n            pieces.append(\" \")",
            "new": "        if False:\n            pieces.append(\" \")  # 变异：不做伪空格归一",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ingest.py"],
            "target": "输入层（伪空格归一 / 形态无关性）",
        },
        {
            "name": "ingest-行置信度取最强",
            "file": os.path.join(SRC, "checkup_ledger", "ingest", "lines.py"),
            "old": "        confidence = min(item.score for item in cluster)",
            "new": "        confidence = max(item.score for item in cluster)  # 变异：取最强而非最弱",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ingest.py"],
            "target": "输入层（行置信度取最弱碎片）",
        },
        {
            "name": "fixtures-渲染引入时钟",
            "file": os.path.join(HERE, "fixtures", "scanrender.py"),
            "old": "import struct\nimport zlib",
            "new": "import struct\nimport time  # 变异：引入非确定性来源\nimport zlib",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ingest_fixtures.py"],
            "target": "夹具确定性（禁时钟）",
        },
        {
            "name": "ingest-未就绪语义复活",
            "file": os.path.join(SRC, "checkup_ledger", "cli.py"),
            "old": "    if command == \"ingest\":\n        return cmd_ingest(args)",
            "new": "    if command == \"ingest\":\n        return cmd_not_ready(\"ingest\")  # 变异：退役的拦截复活",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_exit_codes.py"],
            "target": "退出码（ingest 不再走 exit 4）",
        },
        # ---- M3：规范化层新增守门 ----
        {
            "name": "normalize-单位非最长优先",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "mapping.py"),
            "old": "                if best_alias is None or len(alias) > len(best_alias):\n                    best_alias = alias",
            "new": "                if best_alias is None or len(alias) < len(best_alias):\n                    best_alias = alias  # 变异：改成取最短（值会被静默放大）",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_normalize.py"],
            "target": "规范化层（单位最长优先）",
        },
        {
            "name": "normalize-别名冲突静默取一",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "mapping.py"),
            "old": "                if existing is not None and existing != entry.canonical_name:\n                    raise NormalizeError(",
            "new": "                if False:\n                    raise NormalizeError(  # 变异：别名冲突静默忽略",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_normalize.py"],
            "target": "规范化层（别名冲突必须报错）",
        },
        {
            "name": "normalize-字典放行缺来源条目",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "mapping.py"),
            "old": "        if not standard or not str(standard).strip():\n            raise NormalizeError(",
            "new": "        if False:\n            raise NormalizeError(  # 变异：缺来源条目也进字典",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_normalize.py"],
            "target": "规范化层（第二层来源门禁）",
        },
        {
            "name": "normalize-单位张冠李戴也放行",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "parse.py"),
            "old": "    if unit_match.unit is None or not dictionary.unit_belongs_to(canonical, unit_match.unit):",
            "new": "    if unit_match.unit is None:  # 变异：不校验单位是否属于该指标",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_normalize.py"],
            "target": "规范化层（单位量纲必须属于该指标）",
        },
        {
            "name": "normalize-读不出的区间当没印",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "parse.py"),
            "old": "        if _SIDE_BAD in (low_kind, high_kind):\n            return None, REASON_RANGE_UNPARSED",
            "new": "        if False:\n            return None, REASON_RANGE_UNPARSED  # 变异：读错静默当没印",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_normalize.py"],
            "target": "规范化层（读不出的区间 ≠ 没印）",
        },
        {
            "name": "normalize-待映射行静默丢弃",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "pipeline.py"),
            "old": "        if reason is not None:\n            if reason not in ALL_REASONS:\n                raise NormalizeError(\"未知的待映射原因码：%r\" % (reason,))",
            "new": "        if reason is not None:\n            continue  # 变异：待映射行静默丢弃",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_normalize.py"],
            "target": "规范化层（未映射不猜不丢）",
        },
        {
            "name": "normalize-溯源链断裂",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "pipeline.py"),
            "old": "                line_ref=line,\n                reviewed=True,",
            "new": "                line_ref=None,\n                reviewed=True,  # 变异：丢掉溯源行",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_normalize.py"],
            "target": "规范化层（溯源链不能断）",
        },
        {
            "name": "normalize-复核门被绕过不报错",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "pipeline.py"),
            "old": "    if leaked:\n        raise NormalizeError(",
            "new": "    if False:\n        raise NormalizeError(  # 变异：待复核行混入也不报错",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_normalize.py"],
            "target": "规范化层（未复核行不得混入）",
        },
        {
            "name": "normalize-未就绪语义复活",
            "file": os.path.join(SRC, "checkup_ledger", "cli.py"),
            "old": "    if command == \"normalize\":\n        return cmd_normalize(args)",
            "new": "    if command == \"normalize\":\n        return cmd_not_ready(\"normalize\")  # 变异：退役的拦截复活",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_exit_codes.py"],
            "target": "退出码（normalize 不再走 exit 4）",
        },
        {
            "name": "normalize-纯函数件引入I/O",
            "file": os.path.join(SRC, "checkup_ledger", "normalize", "parse.py"),
            "old": "import re\nfrom typing import List, Optional, Sequence, Tuple",
            "new": "import os  # 变异：纯函数件引入 I/O\nimport re\nfrom typing import List, Optional, Sequence, Tuple",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "分层（规范化纯函数件无 I/O）",
        },
        # ---- M4：台账 / 导出 / 渲染新增守门 ----
        {
            "name": "ledger-唯一键退化成非幂等",
            "file": os.path.join(SRC, "checkup_ledger", "ledger", "schema.py"),
            "old": "ON CONFLICT(subject_id, canonical_name, date, source_file) DO UPDATE SET",
            "new": "ON CONFLICT(subject_id, canonical_name, date) DO UPDATE SET  # 变异：唯一键少一列",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ledger.py"],
            "target": "台账（唯一键含来源文件）",
        },
        {
            "name": "ledger-覆盖计数退化成不查",
            "file": os.path.join(SRC, "checkup_ledger", "ledger", "__init__.py"),
            "old": "    keys = sorted({(row[name_at], row[source_at]) for row in rows})",
            "new": "    keys = []  # 变异：覆盖计数不查（注记与实际动作对不上）",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ledger.py"],
            "target": "台账（覆盖/新写入注记可区分）",
        },
        {
            "name": "ledger-日期不校验零填充",
            "file": os.path.join(SRC, "checkup_ledger", "ledger", "__init__.py"),
            "old": "    if widths != DATE_WIDTHS:",
            "new": "    if False:  # 变异：日期形状不校验",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ledger.py"],
            "target": "台账（日期形状必须校验）",
        },
        {
            "name": "ledger-溯源链断裂",
            "file": os.path.join(SRC, "checkup_ledger", "ledger", "__init__.py"),
            "old": "        if item.measurement.line_ref is not None:\n            source_file = item.measurement.line_ref.source_file or \"\"",
            "new": "        if False:  # 变异：丢掉溯源来源文件\n            source_file = item.measurement.line_ref.source_file or \"\"",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ledger.py"],
            "target": "台账（source_file 从 line_ref 取）",
        },
        {
            "name": "ledger-未声明判定态也落库",
            "file": os.path.join(SRC, "checkup_ledger", "ledger", "__init__.py"),
            "old": "        if flag not in ALL_FLAGS:\n            raise LedgerError(\"未声明的判定态 flag=%r（台账只收四态）\" % (flag,))",
            "new": "        if False:\n            raise LedgerError(\"未声明的判定态 flag=%r（台账只收四态）\" % (flag,))  # 变异：半懂的标记也落库",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ledger.py"],
            "target": "台账（只收四态三源）",
        },
        {
            "name": "ledger-schema版本不拒绝",
            "file": os.path.join(SRC, "checkup_ledger", "ledger", "__init__.py"),
            "old": "    if version not in (0, schema.SCHEMA_VERSION):",
            "new": "    if False:  # 变异：版本不匹配也打开（猜着迁移）",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_ledger.py"],
            "target": "台账（schema 版本不匹配拒绝打开）",
        },
        {
            "name": "export-建议词根门失效",
            "file": os.path.join(SRC, "checkup_ledger", "export", "__init__.py"),
            "old": "    assert_no_advisory_wording(artifact)",
            "new": "    # 变异：出口不跑建议词根门\n    pass  # assert_no_advisory_wording(artifact)",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_export.py"],
            "target": "导出（建议性词根逐字校验）",
        },
        {
            "name": "export-词根表被清空",
            "file": os.path.join(SRC, "checkup_ledger", "export", "__init__.py"),
            "old": 'ADVISORY_ROOTS = ("建议", "可能", "风险提示", "注意", "应", "考虑")',
            "new": "ADVISORY_ROOTS = ()  # 变异：词根表清空（门形同虚设）",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_export.py"],
            "target": "导出（词根表非空且逐个可检出）",
        },
        {
            "name": "export-无前值填成0",
            "file": os.path.join(SRC, "checkup_ledger", "export", "__init__.py"),
            "old": "    if previous is not None:\n        earlier = float(previous[\"value\"])",
            "new": "    previous = previous or {\"value\": 0.0, \"date\": \"\"}  # 变异：无前值当成 0\n    if previous is not None:\n        earlier = float(previous[\"value\"])",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_export.py"],
            "target": "导出（无前值不填 0）",
        },
        {
            "name": "export-同一天也算可比前值",
            "file": os.path.join(SRC, "checkup_ledger", "export", "__init__.py"),
            "old": "        if date and point_date >= date:\n            break",
            "new": "        if False:  # 变异：同一天的历史也当可比前值\n            break",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_export.py"],
            "target": "导出（可比前值须严格早于当前日期）",
        },
        {
            "name": "export-未知格式静默取默认",
            "file": os.path.join(SRC, "checkup_ledger", "export", "__init__.py"),
            "old": "    if normalized not in (\"csv\", \"md\"):\n        raise ExportError(\"未知导出格式 %r（只认 csv / md）\" % (fmt,))",
            "new": "    if normalized not in (\"csv\", \"md\"):\n        normalized = \"csv\"  # 变异：未知格式静默回落",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_export.py"],
            "target": "导出（未知格式必须报错）",
        },
        {
            "name": "export-空值渲染成None字符串",
            "file": os.path.join(SRC, "checkup_ledger", "export", "__init__.py"),
            "old": "    if value is None:\n        return \"\"\n    return str(value)",
            "new": "    if False:\n        return \"\"\n    return str(value)  # 变异：None 落成字面 None",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_export.py"],
            "target": "导出（缺值渲染为空串）",
        },
        {
            "name": "chart-单点也给分位",
            "file": os.path.join(SRC, "checkup_ledger", "report", "chart.py"),
            "old": "    if len(numbers) < 2 or not _finite(current):\n        return None",
            "new": "    if not numbers or not _finite(current):  # 变异：单点序列也给出分位\n        return None",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_report.py"],
            "target": "渲染（无历史不给分位）",
        },
        {
            "name": "chart-无区间也画带",
            "file": os.path.join(SRC, "checkup_ledger", "report", "chart.py"),
            "old": "    has_band = _finite(band_low) or _finite(band_high)",
            "new": "    has_band = True  # 变异：无区间也画带（伪造参考区间）",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_report.py"],
            "target": "渲染（无区间不画带）",
        },
        {
            "name": "chart-值域不含区间端点",
            "file": os.path.join(SRC, "checkup_ledger", "report", "chart.py"),
            "old": "    for bound in (band_low, band_high):\n        if _finite(bound):\n            numbers.append(float(bound))",
            "new": "    for bound in ():  # 变异：值域不含区间端点（带会被裁到画布外）\n        if _finite(bound):\n            numbers.append(float(bound))",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_report.py"],
            "target": "渲染（值域含区间端点）",
        },
        {
            "name": "html-渲染层重算判定",
            "file": os.path.join(SRC, "checkup_ledger", "report", "html.py"),
            "old": "def _display_bound(bound):",
            "new": "def _recompute(value, ref):\n    return value > ref  # 变异：渲染层做比较\n\n\ndef _display_bound(bound):",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "分层（渲染装配层零判定）",
        },
        {
            "name": "html-渲染层不给词根门",
            "file": os.path.join(SRC, "checkup_ledger", "report", "html.py"),
            "old": "    assert_no_advisory_wording(document)\n    return document\n\n\n# ---------------------------------------------------------------- 趋势图（单指标折线）",
            "new": "    assert_no_external_resources(document)  # 变异：渲染出口跳过词根门\n    return document\n\n\n# ---------------------------------------------------------------- 趋势图（单指标折线）",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "分层（渲染层也过建议词根门）",
        },
        {
            "name": "chart-图元模块出现判定态",
            "file": os.path.join(SRC, "checkup_ledger", "report", "chart.py"),
            "old": "WIDTH = 760",
            "new": "FLAG_HIGH = \"high\"  # 变异：图元计算模块出现判定态\n\nWIDTH = 760",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "分层（图元模块看不到判定态）",
        },
        {
            "name": "ledger-台账层出现判定函数",
            "file": os.path.join(SRC, "checkup_ledger", "ledger", "__init__.py"),
            "old": "from checkup_ledger.engine.compare import trend_delta, trend_direction",
            "new": "from checkup_ledger.engine.compare import compare, trend_delta, trend_direction  # 变异：台账层引入判定函数",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "分层（台账层不做判定）",
        },
        {
            "name": "disclaimer-标记永不落盘",
            "file": os.path.join(SRC, "checkup_ledger", "disclaimer.py"),
            "old": "def mark_accepted(home: Optional[str] = None, env=None) -> bool:",
            "new": "def mark_accepted(home: Optional[str] = None, env=None) -> bool:\n    return False  # 变异：标记永不落盘（免责每次都念）",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "免责（首启标记落盘）",
        },
        {
            "name": "disclaimer-真实入口不触发",
            "file": os.path.join(SRC, "checkup_ledger", "cli.py"),
            "old": "    args = list(sys.argv[1:]) if argv is None else list(argv)",
            "new": "    args = list(argv) if argv is not None else []  # 变异：真实入口（argv=None）不触发免责",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_layering.py"],
            "target": "免责（真实入口也触发）",
        },
        {
            "name": "not-ready-拦截语义复活",
            "file": os.path.join(SRC, "checkup_ledger", "cli.py"),
            "old": "    if command == \"ledger\":\n        return cmd_ledger(args)",
            "new": "    if command == \"ledger\":\n        print(\"尚未落地\", file=sys.stderr)\n        return 4  # 变异：退役的拦截复活",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_exit_codes.py"],
            "target": "退出码（ledger 不再走 exit 4）",
        },
        {
            "name": "not-ready-常量复活",
            "file": os.path.join(SRC, "checkup_ledger", "exit_codes.py"),
            "old": "ALL_EXIT_CODES = (\n    EXIT_OK,",
            "new": "EXIT_NOT_READY = 4  # 变异：退役的常量复活\n\nALL_EXIT_CODES = (\n    EXIT_OK,",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_exit_codes.py"],
            "target": "退出码（常量整项退役）",
        },
        {
            "name": "not-ready-常量混进集合",
            "file": os.path.join(SRC, "checkup_ledger", "exit_codes.py"),
            "old": "    EXIT_MISSING_DEP,\n)",
            "new": "    EXIT_MISSING_DEP,\n    4,  # 变异：退役的码混回集合\n)",
            "cmd": [sys.executable, "-m", "pytest", "-q", "tests/test_exit_codes.py"],
            "target": "退出码（集合为四级）",
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
